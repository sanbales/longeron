"""Stage E prototype tests: OMG Systems Modeling API JSON interchange."""

import json

import pytest

pytest.importorskip("pyecore")

from conftest import VEHICLE_MODEL

import longeron
from longeron import api


@pytest.fixture(scope="module")
def records():
    return api.to_api_records(longeron.loads(VEHICLE_MODEL))


class TestExport:
    def test_flat_records(self, records):
        assert isinstance(records, list)
        assert all("@type" in r and "@id" in r for r in records)

    def test_metaclass_names(self, records):
        types = {r["@type"] for r in records}
        assert {
            "Namespace",
            "Package",
            "PartDefinition",
            "CalculationDefinition",
            "OwningMembership",
            "FeatureMembership",
            "FeatureTyping",
        } <= types

    def test_references_are_id_objects(self, records):
        pkg = next(r for r in records if r.get("declaredName") == "Vehicles")
        owned = pkg["ownedRelationship"]
        assert isinstance(owned, list)
        assert all(set(ref) == {"@id"} for ref in owned)

    def test_ids_unique_and_stable(self, records):
        ids = [r["@id"] for r in records]
        assert len(ids) == len(set(ids))
        again = api.to_api_records(longeron.loads(VEHICLE_MODEL))
        assert sorted(ids) == sorted(r["@id"] for r in again)

    def test_json_serializable(self, records):
        text = api.to_api_json(longeron.loads(VEHICLE_MODEL))
        assert json.loads(text)


class TestImport:
    def test_round_trip_counts(self, records):
        spec = api.from_api_records(records)
        assert len(spec.all_instances()) == len(records)

    def test_round_trip_names_and_ownership(self, records):
        spec = api.from_api_records(records)
        by_name = {getattr(o, "declaredName", None): o for o in spec.all_instances()}
        vehicle = by_name["Vehicle"]
        assert vehicle.eClass.name == "PartDefinition"
        assert vehicle.eContainer() is not None  # re-parented via containment

    def test_round_trip_typing_references(self, records):
        spec = api.from_api_records(records)
        typings = [o for o in spec.all_instances() if o.eClass.name == "FeatureTyping"]
        pairs = {
            (t.typedFeature.declaredName, t.type.declaredName)
            for t in typings
            if t.typedFeature is not None and t.type is not None
        }
        assert ("engine", "Engine") in pairs

    def test_records_survive_second_export(self, records):
        spec = api.from_api_records(records)
        again = api.to_api_records(spec)
        assert {r["@id"] for r in again} == {r["@id"] for r in records}
        first = {r["@id"]: r["@type"] for r in records}
        second = {r["@id"]: r["@type"] for r in again}
        assert first == second

    def test_unknown_type_raises(self):
        with pytest.raises(longeron.SysMLError, match="unknown or abstract"):
            api.from_api_records([{"@type": "Bogus", "@id": "x"}])


def test_direction_survives_round_trip():
    model = longeron.loads("package P { calc def C { in x : Real; return : Real = x; } }")
    records = api.to_api_records(model)
    spec = api.from_api_records(records)
    param = next(o for o in spec.all_instances() if getattr(o, "declaredName", None) == "x")
    assert str(param.direction) == "in"


class TestImpliedSpecializations:
    """to_api_records(implied=True): 'isImplied' Subclassification /
    Subsetting records for the implied standard-library bases."""

    MODEL = "package P { part def A; part b; part a1 : A; }"

    def test_default_off(self, records):
        assert not any(r.get("isImplied") for r in records)

    def test_implied_records_emitted(self):
        records = api.to_api_records(longeron.loads(self.MODEL), implied=True)
        implied = [r for r in records if r.get("isImplied")]
        by_type = {r["@type"] for r in implied}
        # part def A implies Parts::Part; the untyped usage b implies
        # Parts::parts; a1 (explicitly typed by A) implies nothing
        assert by_type == {"Subclassification", "Subsetting"}
        assert len(implied) == 2
        sub = next(r for r in implied if r["@type"] == "Subclassification")
        a_record = next(r for r in records if r.get("declaredName") == "A")
        assert sub["subclassifier"] == {"@id": a_record["@id"]}
        # the library base is not part of the export: its @id is a
        # deterministic UUID of the qualified name, dangling by design
        exported_ids = {r["@id"] for r in records}
        assert sub["superclassifier"]["@id"] not in exported_ids

    def test_explicit_specializations_not_flagged(self):
        records = api.to_api_records(
            longeron.loads("package P { part def A; part def B :> A; }"), implied=True
        )
        implied = [r for r in records if r.get("isImplied")]
        # B specializes A explicitly -> only A gets an implied record
        assert len(implied) == 1

    def test_ids_stable_and_unique(self):
        model_text = self.MODEL
        first = api.to_api_records(longeron.loads(model_text), implied=True)
        second = api.to_api_records(longeron.loads(model_text), implied=True)
        assert sorted(r["@id"] for r in first) == sorted(r["@id"] for r in second)
        assert len({r["@id"] for r in first}) == len(first)

    def test_implied_records_reimport(self):
        records = api.to_api_records(longeron.loads(self.MODEL), implied=True)
        spec = api.from_api_records(records)
        implied = [
            o for o in spec.all_instances() if o.eClass.name in ("Subclassification", "Subsetting")
        ]
        assert len(implied) == 2
        assert all(o.isImplied for o in implied)

    def test_implied_json(self):
        text = api.to_api_json(longeron.loads(self.MODEL), implied=True)
        assert '"isImplied": true' in text

    def test_spec_model_input_rejected(self):
        from longeron.ecore import to_spec

        spec = to_spec(longeron.loads(self.MODEL))
        with pytest.raises(longeron.SysMLError, match="needs a longeron Model"):
            api.to_api_records(spec, implied=True)
