"""Interpreter tests: calcs, instantiation, constraints, requirements."""

import pytest

import sysml2
from sysml2.errors import EvaluationError


class TestCalc:
    def test_simple_call(self, vehicle_interp):
        assert vehicle_interp.call("Vehicles::TotalMass", 1000.0, 200.0) == 1200.0

    def test_default_parameter(self, vehicle_interp):
        assert vehicle_interp.call("Vehicles::TotalMass", 1000.0) == 1000.0

    def test_named_arguments(self, vehicle_interp):
        result = vehicle_interp.call("Vehicles::TotalMass",
                                     vehicleMass=800.0, cargoMass=50.0)
        assert result == 850.0

    def test_local_bindings(self, vehicle_interp):
        # KineticEnergy uses an intermediate attribute (vSquared)
        assert vehicle_interp.call("Vehicles::KineticEnergy",
                                   m=2.0, v=3.0) == 9.0

    def test_missing_argument(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="missing argument"):
            vehicle_interp.call("Vehicles::KineticEnergy", m=2.0)

    def test_unknown_parameter(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="no parameter"):
            vehicle_interp.call("Vehicles::TotalMass", bogus=1)


class TestInstantiate:
    def test_attributes_evaluated(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        assert car.slots["mass"] == 1200.0
        assert car.slots["maxMass"] == 2000.0

    def test_derived_attribute_references_sibling(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        assert car.slots["dryMass"] == 1100.0

    def test_nested_parts(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        engine = car.slots["engine"]
        assert isinstance(engine, sysml2.Instance)
        assert engine.slots["power"] == 150.0

    def test_multiplicity_expansion(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        wheels = car.slots["wheels"]
        assert isinstance(wheels, list) and len(wheels) == 4
        assert all(w.slots["diameter"] == 0.66 for w in wheels)

    def test_bindings_override(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle", mass=1500.0)
        assert car.slots["mass"] == 1500.0
        assert car.slots["dryMass"] == 1400.0  # recomputed from override

    def test_path_access(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        assert car.get("engine.power") == 150.0

    def test_to_dict(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        data = car.to_dict()
        assert data["@type"] == "Vehicles::Vehicle"
        assert data["engine"]["power"] == 150.0

    def test_unknown_binding_rejected(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="no feature"):
            vehicle_interp.instantiate("Vehicles::Vehicle", bogus=1)


class TestConstraints:
    def test_constraint_passes(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        results = vehicle_interp.check(car)
        assert len(results) == 1
        assert results[0].name == "massLimit"
        assert results[0].passed is True

    def test_constraint_fails_with_bad_values(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle", mass=99999.0)
        results = vehicle_interp.check(car)
        assert results[0].passed is False

    def test_expression_recorded(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        assert vehicle_interp.check(car)[0].expression == "mass <= maxMass"


class TestRequirements:
    def test_requirement_satisfied(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        result = vehicle_interp.check_requirement(
            "Vehicles::MassRequirement", subject=car)
        assert result.applicable
        assert result.satisfied is True
        assert result.requirements[0].name == "underLimit"

    def test_requirement_violated(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle", mass=3000.0)
        result = vehicle_interp.check_requirement(
            "Vehicles::MassRequirement", subject=car)
        assert result.applicable
        assert result.satisfied is False

    def test_requirement_not_applicable(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle", mass=-5.0)
        result = vehicle_interp.check_requirement(
            "Vehicles::MassRequirement", subject=car)
        assert not result.applicable
        assert result.satisfied is None


class TestResolution:
    def test_resolve_through_alias(self):
        model = sysml2.loads("""
            package A { part def Thing { attribute x : Real = 1.0; } }
            package B { alias TheThing for A::Thing; }
        """)
        interp = sysml2.Interpreter(model)
        inst = interp.instantiate("B::TheThing")
        assert inst.slots["x"] == 1.0

    def test_resolve_through_import(self):
        model = sysml2.loads("""
            package Lib { attribute k : Real = 2.5; }
            package App {
                private import Lib::*;
                calc def UseK { in x : Real; return : Real = x * k; }
            }
        """)
        interp = sysml2.Interpreter(model)
        assert interp.call("App::UseK", 4.0) == 10.0

    def test_inherited_attributes(self):
        model = sysml2.loads("""
            package P {
                part def Base { attribute a : Real = 1.0; }
                part def Derived :> Base { attribute b : Real = 2.0; }
            }
        """)
        interp = sysml2.Interpreter(model)
        inst = interp.instantiate("P::Derived")
        assert inst.slots == {"b": 2.0, "a": 1.0}

    def test_redefinition_overrides(self):
        model = sysml2.loads("""
            package P {
                part def Base { attribute a : Real = 1.0; }
                part def Derived :> Base {
                    attribute a : Real :>> Base::a = 42.0;
                }
            }
        """)
        interp = sysml2.Interpreter(model)
        assert interp.instantiate("P::Derived").slots["a"] == 42.0
