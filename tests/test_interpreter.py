"""Interpreter tests: calcs, instantiation, constraints, requirements."""

import pytest

import longeron
from longeron.errors import EvaluationError
from longeron.interpreter import Env


class TestCalc:
    def test_simple_call(self, vehicle_interp):
        assert vehicle_interp.call("Vehicles::TotalMass", 1000.0, 200.0) == 1200.0

    def test_default_parameter(self, vehicle_interp):
        assert vehicle_interp.call("Vehicles::TotalMass", 1000.0) == 1000.0

    def test_named_arguments(self, vehicle_interp):
        result = vehicle_interp.call("Vehicles::TotalMass", vehicleMass=800.0, cargoMass=50.0)
        assert result == 850.0

    def test_local_bindings(self, vehicle_interp):
        # KineticEnergy uses an intermediate attribute (vSquared)
        assert vehicle_interp.call("Vehicles::KineticEnergy", m=2.0, v=3.0) == 9.0

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
        assert isinstance(engine, longeron.Instance)
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

    def test_instance_dependent_value_not_cached_across_instances(self):
        # Regression: the constant cache memoized package-level values by
        # element id alone, so a value computed against one instance leaked
        # into checks of another, silently flipping the verdict.
        model = longeron.loads(
            """
            package P {
                attribute halfMass : Real = mass / 2.0;
                part def V {
                    attribute mass : Real = 100.0;
                    assert constraint c { halfMass < 100.0 }
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        first = interp.check(interp.instantiate("P::V", mass=100.0))
        assert first[0].passed is True  # 50 < 100
        second = interp.check(interp.instantiate("P::V", mass=400.0))
        assert second[0].passed is False  # 200 < 100 must fail

    def test_negated_constraint_inverts_the_verdict(self):
        # 'assert not constraint' flips the raw expression value in both
        # directions: inner False -> PASS, inner True -> FAIL
        model = longeron.loads(
            """
            package Neg {
                part def Box {
                    attribute mass : Real = 10.0;
                    assert not constraint tooHeavy { mass > 100.0 }
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        light = interp.check(interp.instantiate("Neg::Box"))
        assert light[0].passed is True  # 10 > 100 is False, negated -> True
        heavy = interp.check(interp.instantiate("Neg::Box", mass=500.0))
        assert heavy[0].passed is False  # 500 > 100 is True, negated -> False

    def test_unevaluable_constraint_reports_none_not_false(self):
        model = longeron.loads(
            """
            package Broken {
                part def Box {
                    attribute mass : Real = 1.0;
                    constraint c { mass < noSuchLimit }
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        results = interp.check(interp.instantiate("Broken::Box"))
        assert results[0].passed is None  # unevaluable, not a FAIL
        assert results[0].message  # ...and the reason is recorded


class TestEnvAssign:
    def test_failed_dotted_assign_leaves_no_partial_state(self):
        # Regression: assign() bound a bogus dotted key into the frame
        # *before* raising on an unknown dotted path (validate-then-mutate)
        model = longeron.loads("package P { part def V; }")
        env = Env(longeron.Interpreter(model), model, [{}])
        with pytest.raises(EvaluationError, match="cannot assign to unknown path"):
            env.assign("nope.x", 5)
        assert env.frames == [{}]  # the failed assignment bound nothing

    def test_plain_assign_still_binds_new_names(self):
        model = longeron.loads("package P { part def V; }")
        env = Env(longeron.Interpreter(model), model, [{}])
        env.assign("x", 5)
        assert env.frames[0] == {"x": 5}


class TestRequirements:
    def test_requirement_satisfied(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        result = vehicle_interp.check_requirement("Vehicles::MassRequirement", subject=car)
        assert result.applicable
        assert result.satisfied is True
        assert result.requirements[0].name == "underLimit"

    def test_requirement_violated(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle", mass=3000.0)
        result = vehicle_interp.check_requirement("Vehicles::MassRequirement", subject=car)
        assert result.applicable
        assert result.satisfied is False

    def test_requirement_not_applicable(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle", mass=-5.0)
        result = vehicle_interp.check_requirement("Vehicles::MassRequirement", subject=car)
        assert not result.applicable
        assert result.satisfied is None

    def test_multi_constraint_requirement_needs_all_to_pass(self):
        # one passing + one failing constraint discriminates all() from any()
        model = longeron.loads(
            """
            package Multi {
                part def Item { attribute mass : Real = 50.0; }
                requirement def TwoChecks {
                    subject box : Item;
                    require constraint light { box.mass < 100.0 }
                    require constraint featherweight { box.mass < 10.0 }
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        box = interp.instantiate("Multi::Item")
        result = interp.check_requirement("Multi::TwoChecks", subject=box)
        assert result.applicable
        assert [r.passed for r in result.requirements] == [True, False]
        assert result.satisfied is False  # one failure fails the requirement
        feather = interp.check_requirement(
            "Multi::TwoChecks", subject=interp.instantiate("Multi::Item", mass=5.0)
        )
        assert [r.passed for r in feather.requirements] == [True, True]
        assert feather.satisfied is True


class TestResolution:
    def test_resolve_through_alias(self):
        model = longeron.loads("""
            package A { part def Thing { attribute x : Real = 1.0; } }
            package B { alias TheThing for A::Thing; }
        """)
        interp = longeron.Interpreter(model)
        inst = interp.instantiate("B::TheThing")
        assert inst.slots["x"] == 1.0

    def test_resolve_through_import(self):
        model = longeron.loads("""
            package Lib { attribute k : Real = 2.5; }
            package App {
                private import Lib::*;
                calc def UseK { in x : Real; return : Real = x * k; }
            }
        """)
        interp = longeron.Interpreter(model)
        assert interp.call("App::UseK", 4.0) == 10.0

    def test_inherited_attributes(self):
        model = longeron.loads("""
            package P {
                part def Base { attribute a : Real = 1.0; }
                part def Derived :> Base { attribute b : Real = 2.0; }
            }
        """)
        interp = longeron.Interpreter(model)
        inst = interp.instantiate("P::Derived")
        assert inst.slots == {"b": 2.0, "a": 1.0}

    def test_redefinition_overrides(self):
        model = longeron.loads("""
            package P {
                part def Base { attribute a : Real = 1.0; }
                part def Derived :> Base {
                    attribute a : Real :>> Base::a = 42.0;
                }
            }
        """)
        interp = longeron.Interpreter(model)
        assert interp.instantiate("P::Derived").slots["a"] == 42.0


class TestInstancePaths:
    def test_dotted_set_updates_nested_slot(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        car.set("engine.power", 200.0)
        assert car.get("engine.power") == 200.0
        car.set("mass", 1300.0)  # single-segment path still works
        assert car.slots["mass"] == 1300.0

    def test_dotted_set_through_non_instance_raises(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        with pytest.raises(EvaluationError, match="cannot traverse 'deeper'"):
            car.set("mass.deeper.more", 1.0)  # mass is a scalar, not a part


SNAPSHOT_MODEL = """
package P {
    enum def Color { red; green; }
    part def Point { attribute x : Real; }
    part def Palette {
        attribute main : Color = Color::red;
        attribute nums = (1, 2, 3);
        attribute offset : Real = 2.0;
        attribute shifted : Point = new Point(x = 1.0 + offset);
    }
}
"""


class TestSnapshotValues:
    def test_enum_list_and_nested_instance_snapshot(self):
        interp = longeron.Interpreter(longeron.loads(SNAPSHOT_MODEL))
        inst = interp.instantiate("P::Palette")
        snap = interp.snapshot(inst, name="snapped")
        members = {m.name: m for m in snap.members}
        assert members["main"].value.expr.to_text() == "P::Color::red"
        assert members["nums"].value.expr.to_text() == "(1, 2, 3)"
        nested = members["shifted"]
        assert nested.types == ["P::Point"]  # instances become typed parts
        assert nested.member_named("x").value.expr.to_text() == "3.0"


class TestConstructors:
    def test_constructor_evaluates_expression_arguments(self):
        interp = longeron.Interpreter(longeron.loads(SNAPSHOT_MODEL))
        inst = interp.instantiate("P::Palette")
        shifted = inst.slots["shifted"]
        assert isinstance(shifted, longeron.Instance)
        assert shifted.slots["x"] == 3.0  # 1.0 + offset evaluated at bind time

    def test_definition_name_is_callable_with_positional_args(self):
        interp = longeron.Interpreter(longeron.loads(SNAPSHOT_MODEL))
        point = interp.evaluate("Point(2.0)", context="P")
        assert isinstance(point, longeron.Instance)
        assert point.slots["x"] == 2.0


class TestPerformInline:
    def test_inline_perform_members_execute_in_the_outer_env(self):
        model = longeron.loads(
            """
            package B {
                action def Outer {
                    out result : Real;
                    perform action inner {
                        assign result := 42.0;
                    }
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        run = interp.run_action("B::Outer")
        assert run.outputs == {"result": 42.0}
        assert "perform action inner" in run.trace


class TestConstraintExprFallback:
    def test_constraint_usage_typed_by_a_constraint_def(self):
        # the usage itself carries no expression; _check_constraint must
        # fall back to the typing constraint def's result expression
        model = longeron.loads(
            """
            package P {
                part def Box {
                    attribute mass : Real = 5.0;
                    constraint def MassPositive { mass > 0.0 }
                    constraint c1 : MassPositive;
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        good = interp.check(interp.instantiate("P::Box"))
        assert good[0].name == "c1"
        assert good[0].expression == "mass > 0.0"
        assert good[0].passed is True
        bad = interp.check(interp.instantiate("P::Box", mass=-1.0))
        assert bad[0].passed is False


class TestArrowOpErrors:
    def test_unknown_collection_operator(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="->frobnicate is not supported"):
            vehicle_interp.evaluate("(1, 2, 3)->frobnicate()")

    def test_unknown_body_operator(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="->frobnicate with a body is not supported"):
            vehicle_interp.evaluate("(1, 2, 3)->frobnicate { in x; x }")


class TestRuntimeErrorMessages:
    def test_instance_get_unknown_feature(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        with pytest.raises(EvaluationError, match="has no feature 'nofeature'"):
            car.get("nofeature")

    def test_instance_get_through_scalar(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        with pytest.raises(EvaluationError, match=r"cannot access 'deep' on 1200\.0"):
            car.get("mass.deep")

    def test_instance_repr_shows_type_and_slots(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        assert repr(car).startswith("Vehicles::Vehicle(mass=1200.0")

    def test_type_value_repr(self, vehicle_interp):
        assert repr(vehicle_interp.evaluate("Vehicle", context="Vehicles")) == (
            "<type Vehicles::Vehicle>"
        )

    def test_member_access_on_unknown_feature(self, vehicle_interp):
        car = vehicle_interp.instantiate("Vehicles::Vehicle")
        with pytest.raises(EvaluationError, match="has no feature 'bogus'"):
            vehicle_interp.evaluate("v.bogus", v=car)

    def test_call_without_result_expression(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="Vehicle has no result expression"):
            vehicle_interp.call("Vehicles::Vehicle")

    def test_call_with_too_many_positional_args(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="takes 2 parameters, got 3"):
            vehicle_interp.call("Vehicles::TotalMass", 1.0, 2.0, 3.0)

    def test_check_requirement_rejects_a_package(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="is not a requirement"):
            vehicle_interp.check_requirement("Vehicles")

    def test_instantiate_rejects_non_definitions(self, vehicle_interp):
        with pytest.raises(EvaluationError, match="cannot instantiate 42"):
            vehicle_interp.instantiate(42)
