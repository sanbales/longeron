"""Stage B prototype tests: projection onto the OMG spec metamodel."""

import pytest

pytest.importorskip("pyecore")

from conftest import VEHICLE_MODEL

import sysml2
from sysml2 import ecore


@pytest.fixture(scope="module")
def spec(vehicle_model=None):
    model = sysml2.loads(VEHICLE_MODEL)
    return ecore.to_spec(model)


class TestMetamodel:
    def test_loads(self):
        package = ecore.spec_metamodel()
        assert package.name == "sysml"

    def test_class_count(self):
        assert len(ecore.spec_class_names()) == 175

    def test_expected_metaclasses_present(self):
        names = set(ecore.spec_class_names())
        assert {"Element", "Namespace", "Feature", "Type", "Classifier",
                "OwningMembership", "PartDefinition", "PartUsage",
                "FeatureTyping", "Subclassification"} <= names

    def test_unknown_class_raises(self):
        with pytest.raises(sysml2.SysMLError, match="no metaclass"):
            ecore.spec_class("NoSuchMetaclass")


class TestProjection:
    def test_root_is_namespace(self, spec):
        assert spec.root.eClass.name == "Namespace"

    def test_definitions_get_spec_classes(self, spec):
        by_name = {getattr(obj, "declaredName", None): obj.eClass.name
                   for obj in spec.all_instances()}
        assert by_name["Vehicle"] == "PartDefinition"
        assert by_name["Color"] == "EnumerationDefinition"
        assert by_name["TotalMass"] == "CalculationDefinition"
        assert by_name["MassRequirement"] == "RequirementDefinition"

    def test_ownership_is_reified(self, spec):
        pkg = next(o for o in spec.all_instances()
                   if getattr(o, "declaredName", None) == "Vehicles")
        memberships = list(pkg.ownedRelationship)
        assert memberships
        assert all("Membership" in m.eClass.name or
                   m.eClass.name.endswith("ing") or
                   "Relationship" in m.eClass.name or
                   m.eClass.name in ("Subclassification",)
                   for m in memberships)
        owned = [e for m in memberships
                 for e in getattr(m, "ownedRelatedElement", [])]
        names = {getattr(e, "declaredName", None) for e in owned}
        assert "Vehicle" in names

    def test_feature_typing_resolved_in_model(self, spec):
        typings = [o for o in spec.all_instances()
                   if o.eClass.name == "FeatureTyping"]
        typed = {(t.typedFeature.declaredName, t.type.declaredName)
                 for t in typings if t.typedFeature is not None
                 and t.type is not None}
        assert ("engine", "Engine") in typed
        assert ("wheels", "Wheel") in typed

    def test_subclassification(self, spec):
        subs = [o for o in spec.all_instances()
                if o.eClass.name == "Subclassification"]
        pairs = {(s.subclassifier.declaredName,
                  s.superclassifier.declaredName)
                 for s in subs if s.subclassifier and s.superclassifier}
        assert ("Vehicle", "Machine") in pairs

    def test_unresolved_stdlib_refs_reported(self, spec):
        assert "Real" in spec.report.unresolved_references

    def test_parameters_use_parameter_membership(self, spec):
        calc = next(o for o in spec.all_instances()
                    if getattr(o, "declaredName", None) == "TotalMass")
        kinds = [m.eClass.name for m in calc.ownedRelationship]
        assert "ParameterMembership" in kinds

    def test_direction_mapped(self, spec):
        param = next(o for o in spec.all_instances()
                     if getattr(o, "declaredName", None) == "vehicleMass")
        assert str(param.direction) == "in"

    def test_element_ids_stable(self):
        model = sysml2.loads(VEHICLE_MODEL)
        first = ecore.to_spec(model)
        second = ecore.to_spec(model)
        ids1 = sorted(o.elementId for o in first.all_instances())
        ids2 = sorted(o.elementId for o in second.all_instances())
        assert ids1 == ids2

    def test_report_counts(self, spec):
        assert spec.report.elements > 30
        assert spec.report.memberships > 15
        assert spec.report.relationships >= 5


class TestXMI:
    def test_save_and_reload(self, spec, tmp_path):
        path = tmp_path / "vehicle.xmi"
        spec.save_xmi(path)
        assert path.exists() and path.stat().st_size > 1000

        from pyecore.resources import URI, ResourceSet

        rset = ResourceSet()
        rset.metamodel_registry[ecore.spec_metamodel().nsURI] = \
            ecore.spec_metamodel()
        resource = rset.get_resource(URI(str(path)))
        root = resource.contents[0]
        names = {getattr(o, "declaredName", None)
                 for o in root.eAllContents()}
        assert "Vehicle" in names


def test_statements_projected():
    model = sysml2.loads("""
        package P {
            action def Go {
                in n : Integer;
                assign n := n + 1;
                if n > 0 { assign n := 0; }
                send n;
                fork f1;
            }
            state def S { entry; then a; state a;
                          transition first a accept go then a; }
        }
    """)
    spec = ecore.to_spec(model)
    class_names = {o.eClass.name for o in spec.all_instances()}
    assert {"AssignmentActionUsage", "IfActionUsage", "SendActionUsage",
            "ForkNode", "TransitionUsage", "StateUsage"} <= class_names
