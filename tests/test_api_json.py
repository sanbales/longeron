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


@pytest.fixture(scope="module")
def derived_records():
    return api.to_api_records(longeron.loads(TestDerivedEndpoints.MODEL))


@pytest.fixture(scope="module")
def drone_records():
    from pathlib import Path

    drone = Path(__file__).parent.parent / "examples" / "drone.sysml"
    return api.to_api_records(longeron.load(drone, cache=False))


class TestDerivedEndpoints:
    """to_api_records(derived=True), the default: relationship records
    carry the spec-derived ``source``/``target`` endpoint arrays that the
    pilot-implementation API servers serialize (and that consumers such
    as pymbe require to recognize and navigate relationships)."""

    MODEL = """package P {
        part def A { attribute m : Real; }
        part def B :> A { attribute m2 : Real :>> m; }
        part a1 : A;
        part a2 subsets a1;
    }"""

    @staticmethod
    def _id_of(records, name):
        return next(r["@id"] for r in records if r.get("declaredName") == name)

    def _endpoints(self, records, type_):
        record = next(r for r in records if r["@type"] == type_)
        return record, record["source"], record["target"]

    def test_subclassification(self, derived_records):
        record, source, target = self._endpoints(derived_records, "Subclassification")
        assert source == [record["subclassifier"]] == [{"@id": self._id_of(derived_records, "B")}]
        assert target == [record["superclassifier"]] == [{"@id": self._id_of(derived_records, "A")}]

    def test_feature_typing(self, derived_records):
        record, source, target = self._endpoints(derived_records, "FeatureTyping")
        assert source == [record["typedFeature"]] == [{"@id": self._id_of(derived_records, "a1")}]
        assert target == [record["type"]] == [{"@id": self._id_of(derived_records, "A")}]

    def test_subsetting(self, derived_records):
        record, source, target = self._endpoints(derived_records, "Subsetting")
        assert source == [record["subsettingFeature"]]
        assert target == [record["subsettedFeature"]]
        assert target == [{"@id": self._id_of(derived_records, "a1")}]

    def test_redefinition(self, derived_records):
        _record, source, target = self._endpoints(derived_records, "Redefinition")
        assert source == [{"@id": self._id_of(derived_records, "m2")}]
        assert target == [{"@id": self._id_of(derived_records, "m")}]

    def test_memberships_owner_to_member(self, derived_records):
        # membership endpoints fall back to the stored containment roles:
        # source = owningRelatedElement, target = ownedRelatedElement
        memberships = [r for r in derived_records if r["@type"].endswith("Membership")]
        assert memberships
        for record in memberships:
            assert record["source"] == [record["owningRelatedElement"]]
            assert record["target"] == record["ownedRelatedElement"]

    def test_parameter_memberships(self):
        records = api.to_api_records(
            longeron.loads("package P { calc def C { in x : Real; return : Real = x; } }")
        )
        calc_id = next(r["@id"] for r in records if r.get("declaredName") == "C")
        for type_ in ("ParameterMembership", "ReturnParameterMembership"):
            record = next(r for r in records if r["@type"] == type_)
            assert record["source"] == [{"@id": calc_id}]
            assert len(record["target"]) == 1

    def test_underivable_endpoints_omitted(self):
        # the projector never resolves import targets: no endpoint fields
        records = api.to_api_records(
            longeron.loads("package Q { part def X; } package P { import Q::*; }")
        )
        imported = next(r for r in records if r["@type"] == "NamespaceImport")
        assert "source" not in imported and "target" not in imported

    def test_derived_false_restores_minimal_records(self, derived_records):
        plain = api.to_api_records(longeron.loads(self.MODEL), derived=False)
        assert not any("source" in r or "target" in r for r in plain)
        stripped = [
            {k: v for k, v in r.items() if k not in ("source", "target")} for r in derived_records
        ]
        assert plain == stripped

    def test_non_relationship_records_unaffected(self, derived_records):
        for record in derived_records:
            if record["@type"] in ("Namespace", "Package", "PartDefinition", "AttributeUsage"):
                assert "source" not in record and "target" not in record

    def test_round_trip_lossless(self, derived_records):
        spec = api.from_api_records(derived_records)
        again = api.to_api_records(spec)
        assert {r["@id"]: r for r in again} == {r["@id"]: r for r in derived_records}

    def test_implied_records_carry_endpoints(self):
        records = api.to_api_records(longeron.loads(self.MODEL), implied=True)
        implied = [r for r in records if r.get("isImplied")]
        assert implied
        for record in implied:
            assert record["source"] and record["target"]
        plain = api.to_api_records(longeron.loads(self.MODEL), implied=True, derived=False)
        assert not any("source" in r for r in plain if r.get("isImplied"))

    def test_json_flag_threaded(self):
        text = api.to_api_json(longeron.loads(self.MODEL), derived=False)
        assert '"source"' not in text
        assert '"source"' in api.to_api_json(longeron.loads(self.MODEL))


class TestPilotNavigability:
    """Interop regression distilled from loading a longeron export with
    pymbe (github.com/sanbales/pymbe): pilot-API consumers detect
    relationships via the presence of ``source``+``target``
    (pymbe ``model.py:521``) and navigate exclusively through those
    arrays.  The drone-model counts (182 relationships / 175 element
    nodes) pin pymbe's LPG projection of this export."""

    @staticmethod
    def _relationships(records):
        # exactly pymbe's Element._is_relationship test
        return [r for r in records if "source" in r and "target" in r]

    def test_relationship_and_node_counts(self, drone_records):
        relationships = self._relationships(drone_records)
        assert len(relationships) == 313  # pymbe LPG edges
        assert len(drone_records) - len(relationships) == 271  # pymbe LPG nodes

    def test_every_endpoint_resolves(self, drone_records):
        ids = {r["@id"] for r in drone_records}
        for record in self._relationships(drone_records):
            for end in ("source", "target"):
                assert record[end], (record["@type"], end)
                assert all(ref["@id"] in ids for ref in record[end])

    def test_through_feature_membership(self, drone_records):
        # pymbe: QuadCopter.throughFeatureMembership -> owned features
        names = {r["@id"]: r.get("declaredName") for r in drone_records}
        quad = next(r["@id"] for r in drone_records if r.get("declaredName") == "QuadCopter")
        owned = {
            names[ref["@id"]]
            for r in self._relationships(drone_records)
            if r["@type"] == "FeatureMembership" and r["source"] == [{"@id": quad}]
            for ref in r["target"]
        }
        assert owned == {
            # own members only: the shared equipment and physics chain
            # moved to the abstract MultiRotor base when the TriCopter
            # configuration split the family (inherited features are
            # reached through the Specialization edge, pymbe-style)
            "rotorCount",
            "totalMass",
            "thrustPerRotor",
            "motorMaxCurrent",
            "frontalArea",
            "maxCruiseSpeed",
            "motors",
            "propellers",
            "phaseLeads",
        }

    def test_through_feature_typing(self, drone_records):
        # pymbe: partUsage.throughFeatureTyping -> its definition
        names = {r["@id"]: r.get("declaredName") for r in drone_records}
        typed = {
            (names[r["source"][0]["@id"]], names[r["target"][0]["@id"]])
            for r in self._relationships(drone_records)
            if r["@type"] == "FeatureTyping"
        }
        # chassis is typed twice: Frame on the MultiRotor base, TriFrame
        # on the TriCopter's redefinition -- so assert pairs, not a map
        assert ("chassis", "Frame") in typed
        assert ("chassis", "TriFrame") in typed
        assert ("battery", "Battery") in typed
        assert ("motors", "Motor") in typed
        assert ("frontMotors", "Motor") in typed
        assert ("tailMotor", "Motor") in typed
        assert ("propellers", "Propeller") in typed
        assert ("camera", "Camera") in typed


GARAGE_MODEL = """
package Garage {
    doc /* The garage. */
    abstract part def Machine;
    part def Car :> Machine {
        attribute wheels;
        part engine : Engine {
            in item fuel;
        }
    }
    part def Engine;
    part fleetCar : Car;
    enum def Color { red; green; }
    requirement def Safe {
        subject vehicle : Car;
    }
}
"""


@pytest.fixture(scope="module")
def rebuilt():
    records = api.to_api_records(longeron.loads(GARAGE_MODEL))
    return api.model_from_api_records(records)


class TestModelFromApiRecords:
    """Reverse structural import: flat API records -> longeron Model
    (pyecore-free; the forward projection in these tests needs it)."""

    MODEL = GARAGE_MODEL

    def test_structure_and_kinds(self, rebuilt):
        garage = rebuilt.find("Garage")
        assert [e.name for e in garage.members if e.name] == [
            "Machine",
            "Car",
            "Engine",
            "fleetCar",
            "Color",
            "Safe",
        ]
        assert rebuilt.find("Garage::Car::engine").kind == "part"
        assert rebuilt.find("Garage::Car::engine::fuel").kind == "item"

    def test_relationships_come_back_qualified(self, rebuilt):
        assert rebuilt.find("Garage::Car").supers == ["Garage::Machine"]
        assert rebuilt.find("Garage::fleetCar").types == ["Garage::Car"]
        assert rebuilt.find("Garage::Car::engine").types == ["Garage::Engine"]

    def test_flags_and_directions(self, rebuilt):
        assert rebuilt.find("Garage::Machine").is_abstract
        assert rebuilt.find("Garage::Car::engine::fuel").direction == "in"

    def test_membership_kinds(self, rebuilt):
        subject = rebuilt.find("Garage::Safe::vehicle")
        assert subject.kind == "subject"

    def test_enum_literals(self, rebuilt):
        color = rebuilt.find("Garage::Color")
        assert [lit.name for lit in color.literals] == ["red", "green"]

    def test_documentation(self, rebuilt):
        assert rebuilt.find("Garage").doc == "The garage."

    def test_reexport_parses(self, rebuilt):
        text = longeron.to_sysml(rebuilt)
        assert longeron.loads(text).find("Garage::Car") is not None

    def test_round_trip_is_id_stable(self):
        # element/membership @ids are deterministic path-based UUIDs and
        # survive the round trip; typing/specialization record ids may
        # differ (their id embeds the reference *text*, which the reverse
        # import qualifies), so compare those by count per kind instead
        records = api.to_api_records(longeron.loads(self.MODEL))
        again = api.to_api_records(api.model_from_api_records(records))
        relationship_kinds = {"FeatureTyping", "Subclassification", "Subsetting", "Redefinition"}

        def ids(recs):
            return sorted(r["@id"] for r in recs if r["@type"] not in relationship_kinds)

        def kind_counts(recs):
            counts: dict[str, int] = {}
            for r in recs:
                if r["@type"] in relationship_kinds:
                    counts[r["@type"]] = counts.get(r["@type"], 0) + 1
            return counts

        assert ids(records) == ids(again)
        assert kind_counts(records) == kind_counts(again)

    def test_accepts_identity_payload_post_form(self):
        records = api.to_api_records(longeron.loads(self.MODEL))
        post_form = [{"identity": {"@id": r["@id"]}, "payload": r} for r in records]
        model = api.model_from_api_records(post_form)
        assert model.find("Garage::Car") is not None

    def test_unknown_types_are_skipped_not_fatal(self):
        model = api.model_from_api_records(
            [
                {"@type": "PartDefinition", "@id": "a", "declaredName": "Known"},
                {"@type": "MysteryMetaclass", "@id": "b", "declaredName": "Ghost"},
            ]
        )
        assert [e.name for e in model.members] == ["Known"]

    def test_json_variant(self):
        text = api.to_api_json(longeron.loads(self.MODEL))
        assert api.model_from_api_json(text).find("Garage::Color") is not None


RICH_MODEL = """
package Rich {
    part def Plug; part a; part b;
    connection def Link;
    connection c1 : Link connect a to b;
    binding bnd bind a = b;
    rep raw language "text" /* body text */
    part def <SN> Named;
    calc def Twice { in x : Real; return : Real = 2.0 * x; }
    action def Go {
        merge m1;
        decide d1;
    }
    variation part def Choice :> Plug {
        variant part v1 : Plug;
    }
}
"""


class TestModelFromApiRecordsRichClasses:
    """The reverse structural import rebuilds special usage classes,
    directions, variants, control nodes, and textual representations."""

    @pytest.fixture(scope="class")
    def rebuilt(self):
        import longeron.model as M  # noqa: F401

        records = api.to_api_records(longeron.loads(RICH_MODEL))
        return api.model_from_api_records(records)

    def test_special_usage_classes(self, rebuilt):
        import longeron.model as M

        assert isinstance(rebuilt.find("Rich::c1"), M.ConnectionUsage)
        assert isinstance(rebuilt.find("Rich::bnd"), M.BindingConnector)

    def test_textual_representation_and_short_name(self, rebuilt):
        import longeron.model as M

        rep = next(e for e in rebuilt.iter_tree() if isinstance(e, M.TextualRepresentation))
        assert rep.language == "text" and rep.body == "/* body text */"
        assert rebuilt.find("Rich::Named").short_name == "SN"

    def test_control_nodes_and_directions(self, rebuilt):
        import longeron.model as M

        controls = [e for e in rebuilt.iter_tree() if isinstance(e, M.ControlNode)]
        assert sorted(c.kind for c in controls) == ["decision", "merge"]
        twice = rebuilt.find("Rich::Twice")
        dirs = [(u.name, u.direction) for u in twice.members if isinstance(u, M.Usage)]
        assert dirs == [("x", "in"), (None, "return")]

    def test_variant_membership(self, rebuilt):
        import longeron.model as M

        choice = rebuilt.find("Rich::Choice")
        assert choice.is_variation
        variants = [u for u in choice.members if isinstance(u, M.Usage)]
        assert [(u.name, u.is_variant) for u in variants] == [("v1", True)]

    def test_json_text_path_matches(self, rebuilt):
        via_json = api.model_from_api_json(api.to_api_json(longeron.loads(RICH_MODEL)))
        assert via_json.find("Rich::c1") is not None
        assert via_json.find("Rich::Choice") is not None


def test_satisfy_of_requirement_definition_projects():
    model = longeron.loads(
        """
        package P {
            requirement def R1 { require constraint { true } }
            part sys { satisfy R1 by sys; }
        }
        """
    )
    records = api.to_api_records(model)  # used to raise pyecore BadValueError
    by_type: dict[str, list] = {}
    for record in records:
        by_type.setdefault(record["@type"], []).append(record)
    req_def = next(r for r in by_type["RequirementDefinition"] if r["declaredName"] == "R1")
    (satisfy,) = by_type["SatisfyRequirementUsage"]
    # the definition-targeted satisfy projects as a FeatureTyping (the
    # satisfied requirement usage is *typed by* R1), not a Subsetting
    typings = [
        r
        for r in by_type["FeatureTyping"]
        if r["typedFeature"] == {"@id": satisfy["@id"]} and r["type"] == {"@id": req_def["@id"]}
    ]
    assert len(typings) == 1
    assert not any(
        r["subsettedFeature"] == {"@id": req_def["@id"]} for r in by_type.get("Subsetting", [])
    )


VIEWS_MODEL = """
package Rig {
    part def Axle {
        part hub : Hub [2];
    }
    part def Hub;
    part axle : Axle;
    view 'axle structure' : StandardViewDefinitions::InterconnectionView {
        expose Rig::**;
        render Views::asInterconnectionDiagram;
    }
    view detail {
        expose Rig::axle;
        expose Rig::*[not @SysML::ConnectionUsage];
        filter @SysML::PartUsage;
    }
}
"""


class TestViewPersistenceRecords:
    """The API expose projection (view-persistence design, finding 2).

    ``to_api_records`` used to keep the ViewUsage shell but silently drop
    every Expose and ElementFilter -- a view pushed through the API
    arrived empty.  These tests pin the fixed projection (MembershipExpose
    / NamespaceExpose / ElementFilterMembership records) and its inverse.
    """

    @pytest.fixture(scope="class")
    @staticmethod
    def records():
        return api.to_api_records(longeron.loads(VIEWS_MODEL))

    @staticmethod
    def by_type(records):
        out: dict[str, list] = {}
        for record in records:
            out.setdefault(record["@type"], []).append(record)
        return out

    def test_expose_and_filter_records_exist(self, records):
        by_type = self.by_type(records)
        assert len(by_type["MembershipExpose"]) == 2
        assert len(by_type["NamespaceExpose"]) == 1
        # detail's view filter + the namespace expose's bracket filter
        assert len(by_type["ElementFilterMembership"]) == 2

    def test_expose_records_carry_the_spec_constraints(self, records):
        # validateExposeIsImportAll / validateExposeVisibility (spec
        # 8.3.26.2): always import-all, always protected
        for record in records:
            if record["@type"] in ("MembershipExpose", "NamespaceExpose"):
                assert record["isImportAll"] is True
                assert record["visibility"] == "protected"

    def test_recursive_flag_projected(self, records):
        by_type = self.by_type(records)
        recursive = [r for r in by_type["MembershipExpose"] if r.get("isRecursive")]
        assert len(recursive) == 1  # expose Rig::**

    def test_membership_expose_targets_the_owning_membership(self, records):
        by_id = {r["@id"]: r for r in records}
        by_type = self.by_type(records)
        rig = next(r for r in by_type["Package"] if r["declaredName"] == "Rig")
        recursive = next(r for r in by_type["MembershipExpose"] if r.get("isRecursive"))
        membership = by_id[recursive["importedMembership"]["@id"]]
        assert membership["@type"].endswith("Membership")
        assert membership["ownedRelatedElement"] == [{"@id": rig["@id"]}]

    def test_namespace_expose_targets_the_namespace(self, records):
        by_type = self.by_type(records)
        rig = next(r for r in by_type["Package"] if r["declaredName"] == "Rig")
        (namespace_expose,) = by_type["NamespaceExpose"]
        assert namespace_expose["importedNamespace"] == {"@id": rig["@id"]}

    def test_filter_condition_rides_a_textual_representation(self, records):
        # standard vocabulary for text the projection does not structure:
        # the condition Expression owns a TextualRepresentation
        by_type = self.by_type(records)
        bodies = {r["body"] for r in by_type["TextualRepresentation"]}
        assert "@SysML::PartUsage" in bodies
        assert "not (@SysML::ConnectionUsage)" in bodies

    def test_derived_endpoints_present_on_expose_records(self, records):
        for record in records:
            if record["@type"] in ("MembershipExpose", "NamespaceExpose"):
                assert record["source"], record
                assert record["target"], record

    def test_spec_level_round_trip_lossless(self, records):
        again = api.to_api_records(api.spec_from_api_records(records))
        assert again == records

    def test_model_round_trip_preserves_expose_semantics(self):
        model = longeron.loads(VIEWS_MODEL)
        clone = api.model_from_api_records(api.to_api_records(model))
        view = clone.find("Rig::axle structure")
        exposes = [m for m in view.members if isinstance(m, longeron.model.Expose)]
        assert [(e.target, e.is_namespace, e.is_recursive) for e in exposes] == [
            ("Rig", False, True)
        ]
        detail = clone.find("Rig::detail")
        exposes = [m for m in detail.members if isinstance(m, longeron.model.Expose)]
        assert [(e.target, e.is_namespace, e.is_recursive) for e in exposes] == [
            ("Rig::axle", False, False),
            ("Rig", True, False),
        ]
        # the bracket filter and the view filter come back as expressions
        assert [f.to_text() for f in exposes[1].filters] == ["not (@SysML::ConnectionUsage)"]
        filters = [m for m in detail.members if isinstance(m, longeron.model.ElementFilter)]
        assert [f.condition.to_text() for f in filters] == ["@SysML::PartUsage"]

    def test_model_round_trip_reaches_a_textual_fixpoint(self):
        # rt := to_api_records -> model_from_api_records; after one trip
        # (which qualifies names), a second trip must be a fixpoint
        def rt(model):
            return api.model_from_api_records(api.to_api_records(model))

        once = rt(longeron.loads(VIEWS_MODEL))
        assert longeron.to_sysml(rt(once)) == longeron.to_sysml(once)

    def test_condition_payload_never_leaks_into_the_model(self):
        clone = api.model_from_api_records(api.to_api_records(longeron.loads(VIEWS_MODEL)))
        # no stray roots: the filter-condition Expression's textual
        # representation is a payload, not a model member
        assert [type(el).__name__ for el in clone.members] == ["Package"]
        assert not any(
            isinstance(el, longeron.model.TextualRepresentation) for el in clone.iter_tree()
        )

    def test_dangling_expose_target_drops_the_expose_not_the_view(self):
        # a target that never resolved projects without a reference; the
        # inverse drops the (textually unrepresentable) expose, keeps the view
        model = longeron.loads("package P { part a; view v { expose P::gone; expose P::a; } }")
        clone = api.model_from_api_records(api.to_api_records(model))
        view = clone.find("P::v")
        exposes = [m for m in view.members if isinstance(m, longeron.model.Expose)]
        assert [e.target for e in exposes] == ["P::a"]
