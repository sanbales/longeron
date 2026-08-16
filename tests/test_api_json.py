"""Stage E prototype tests: OMG Systems Modeling API JSON interchange."""

import json

import pytest

pytest.importorskip("pyecore")

from conftest import VEHICLE_MODEL

import sysml2
from sysml2 import api


@pytest.fixture(scope="module")
def records():
    return api.to_api_records(sysml2.loads(VEHICLE_MODEL))


class TestExport:
    def test_flat_records(self, records):
        assert isinstance(records, list)
        assert all("@type" in r and "@id" in r for r in records)

    def test_metaclass_names(self, records):
        types = {r["@type"] for r in records}
        assert {"Namespace", "Package", "PartDefinition",
                "CalculationDefinition", "OwningMembership",
                "FeatureMembership", "FeatureTyping"} <= types

    def test_references_are_id_objects(self, records):
        pkg = next(r for r in records if r.get("declaredName") == "Vehicles")
        owned = pkg["ownedRelationship"]
        assert isinstance(owned, list)
        assert all(set(ref) == {"@id"} for ref in owned)

    def test_ids_unique_and_stable(self, records):
        ids = [r["@id"] for r in records]
        assert len(ids) == len(set(ids))
        again = api.to_api_records(sysml2.loads(VEHICLE_MODEL))
        assert sorted(ids) == sorted(r["@id"] for r in again)

    def test_json_serializable(self, records):
        text = api.to_api_json(sysml2.loads(VEHICLE_MODEL))
        assert json.loads(text)


class TestImport:
    def test_round_trip_counts(self, records):
        spec = api.from_api_records(records)
        assert len(spec.all_instances()) == len(records)

    def test_round_trip_names_and_ownership(self, records):
        spec = api.from_api_records(records)
        by_name = {getattr(o, "declaredName", None): o
                   for o in spec.all_instances()}
        vehicle = by_name["Vehicle"]
        assert vehicle.eClass.name == "PartDefinition"
        assert vehicle.eContainer() is not None  # re-parented via containment

    def test_round_trip_typing_references(self, records):
        spec = api.from_api_records(records)
        typings = [o for o in spec.all_instances()
                   if o.eClass.name == "FeatureTyping"]
        pairs = {(t.typedFeature.declaredName, t.type.declaredName)
                 for t in typings
                 if t.typedFeature is not None and t.type is not None}
        assert ("engine", "Engine") in pairs

    def test_records_survive_second_export(self, records):
        spec = api.from_api_records(records)
        again = api.to_api_records(spec)
        assert {r["@id"] for r in again} == {r["@id"] for r in records}
        first = {r["@id"]: r["@type"] for r in records}
        second = {r["@id"]: r["@type"] for r in again}
        assert first == second

    def test_unknown_type_raises(self):
        with pytest.raises(sysml2.SysMLError, match="unknown or abstract"):
            api.from_api_records([{"@type": "Bogus", "@id": "x"}])


def test_direction_survives_round_trip():
    model = sysml2.loads(
        "package P { calc def C { in x : Real; return : Real = x; } }")
    records = api.to_api_records(model)
    spec = api.from_api_records(records)
    param = next(o for o in spec.all_instances()
                 if getattr(o, "declaredName", None) == "x")
    assert str(param.direction) == "in"
