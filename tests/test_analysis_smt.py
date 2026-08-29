"""Spike tests: requirement consistency / conflict cores / bounds on Z3."""

from fractions import Fraction
from pathlib import Path

import pytest

pytest.importorskip("z3")

import longeron
from longeron import model as M
from longeron.analysis import smt

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture()
def drone():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


class TestConsistency:
    def test_drone_requirements_are_consistent(self, drone):
        system = smt.to_smt(
            drone, "Rotorcraft::QuadCopter", requirements=("DeepScout::FlightEnvelope",)
        )
        assert system.gaps == []
        result = system.check()
        assert result.status == "sat"
        assert result.witness["payloadMass"] == pytest.approx(0.2)
        assert result.witness["totalMass"] == pytest.approx(1.41)

    def test_calc_invocations_inline(self, drone):
        system = smt.to_smt(
            drone, "Rotorcraft::QuadCopter", requirements=("DeepScout::FlightEnvelope",)
        )
        labels = [label for label, _ in system.assertions]
        assert "FlightEnvelope::hoverMargin [require]" in labels


class TestConflictCore:
    def test_over_constrained_names_conflict(self, drone):
        pkg = drone.find("Rotorcraft")
        req = M.Definition(kind="requirement", name="HeavyPayload")
        req.add(M.Usage(kind="subject", name="drone", types=["QuadCopter"]))
        req.add(
            M.Usage(
                kind="constraint",
                name="bigPayload",
                constraint_kind="require",
                result=longeron.parse_expression("drone.payloadMass >= 0.6"),
            )
        )
        pkg.add(req)
        system = smt.to_smt(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope", "Rotorcraft::HeavyPayload"),
            free=("payloadMass",),
        )
        result = system.check()
        assert result.status == "unsat"
        # payload >= 0.6 pushes totalMass past the 1.5 kg takeoff limit
        assert "HeavyPayload::bigPayload [require]" in result.core
        assert "QuadCopter::takeoffMassLimit" in result.core
        assert "QuadCopter::canHover" not in result.core


class TestDesignSpace:
    def test_max_payload_with_all_constraints(self, drone):
        system = smt.to_smt(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
        )
        bound, result = system.maximize("payloadMass")
        assert result.status == "sat"
        assert Fraction(bound) == Fraction(29, 100)  # 0.29, exact

    def test_strict_bound_is_open(self, drone):
        # only canHover (strict >): the supremum is reported with -epsilon
        system = smt.to_smt(drone, "Rotorcraft::QuadCopter", free=("payloadMass",))
        bound, result = system.maximize("payloadMass", exclude=("QuadCopter::takeoffMassLimit",))
        assert result.status == "sat"
        assert "epsilon" in bound
        # 4 * thrustPerRotor / 9.81 - 1.21, interpreter-exact: ~2.1841 kg
        assert bound.startswith(str(Fraction(89274526868647, 40875000000000)))

    def test_witness_respects_free_variable(self, drone):
        system = smt.to_smt(drone, "Rotorcraft::QuadCopter", free=("payloadMass",))
        labels = [label for label, _ in system.assertions]
        assert "payloadMass.value" not in labels
        assert "maxTakeoffMass.value" in labels


LOGIC_MODEL = """
package Logic {
    attribute ceiling : Real = 10.0;
    attribute enabled : Boolean = true;
    part def OrBox {
        attribute u : Boolean = false;
        attribute v : Boolean = false;
        constraint either { u or v }
        constraint notU { not u }
    }
    part def XorBox {
        attribute a : Boolean = true;
        attribute b : Boolean = true;
        constraint aHolds { a }
        constraint bHolds { b }
        constraint exclusive { a xor b }
    }
    part def ImplBox {
        attribute p : Boolean = true;
        attribute q : Boolean = false;
        constraint rule { p implies q }
        constraint notQ { not q }
    }
    part def PowBox {
        attribute x : Real = 1.0;
        constraint square { x ** 2.0 == 4.0 }
        constraint negative { x < 0.0 }
        constraint distinct { x != -2.0 }
    }
    part def ConstBox {
        attribute y : Real = 1.0;
        constraint below { y <= ceiling }
        constraint gated { enabled implies y >= 0.0 }
    }
}
"""


class TestOperatorEncodings:
    """or / xor / implies / ** / == / != reach Z3 with their own semantics
    (each case is discriminating: swapping the operator flips the verdict)."""

    @pytest.fixture()
    def logic(self):
        return longeron.loads(LOGIC_MODEL)

    def test_or_forces_the_unconstrained_arm(self, logic):
        system = smt.to_smt(logic, "Logic::OrBox", free=("u", "v"))
        assert system.gaps == []
        result = system.check()
        assert result.status == "sat"
        assert result.witness == {"u": False, "v": True}  # and() would be unsat

    def test_xor_rejects_both_arms_true(self, logic):
        system = smt.to_smt(logic, "Logic::XorBox", free=("a", "b"))
        result = system.check()
        assert result.status == "unsat"  # or() would be sat
        assert "XorBox::exclusive" in result.core

    def test_implies_with_true_antecedent_is_binding(self, logic):
        # p is pinned true by its value binding; q is free but 'not q' holds
        system = smt.to_smt(logic, "Logic::ImplBox", free=("q",))
        result = system.check()
        assert result.status == "unsat"  # or() would be sat via p
        assert "ImplBox::rule" in result.core

    def test_implies_vacuous_truth_with_false_antecedent(self, logic):
        system = smt.to_smt(logic, "Logic::ImplBox", free=("p", "q"))
        result = system.check()
        assert result.status == "sat"  # and() would be unsat
        assert result.witness["p"] is False

    def test_power_equality_and_disequality(self, logic):
        system = smt.to_smt(logic, "Logic::PowBox", free=("x",))
        result = system.check()
        assert result.status == "unsat"  # x**2 == 4 and x < 0 pin x = -2
        assert "PowBox::distinct" in result.core
        relaxed = system.check(exclude=("PowBox::distinct",))
        assert relaxed.status == "sat"
        assert relaxed.witness["x"] == pytest.approx(-2.0)

    def test_model_level_constants_resolve_in_refs(self, logic):
        # 'ceiling' and 'enabled' live on the package, not the part: they
        # must encode as constants, not free variables
        system = smt.to_smt(logic, "Logic::ConstBox", free=("y",))
        assert system.gaps == []
        assert set(system.variables) == {"y"}
        bound, result = system.maximize("y")
        assert result.status == "sat"
        assert float(Fraction(bound)) == pytest.approx(10.0)


def test_constraint_usage_typed_by_a_def_reaches_the_solver():
    # the usage has no body: its expression must come from the typing def
    model = longeron.loads(
        """
        package Typed {
            part def Box {
                attribute x : Real = 1.0;
                constraint def InRange { x >= 0.0 and x <= 5.0 }
                constraint c1 : InRange;
            }
        }
        """
    )
    system = smt.to_smt(model, "Typed::Box", free=("x",))
    assert system.gaps == []
    assert any("c1" in label for label, _ in system.assertions)
    bound, result = system.maximize("x")
    assert result.status == "sat"
    assert float(Fraction(bound)) == pytest.approx(5.0)


CALC_MODEL = """
package Calcs {
    calc def Sq { in v : Real; attribute v2 : Real = v * v; return : Real = v2; }
    calc def NoResult { in v : Real; }
    part def Box {
        attribute x : Real = 1.0;
        constraint bounded { abs(x) <= 2.0 }
        constraint squared { Sq(x) <= 4.0 }
        assert not constraint ceiling { x > 5.0 }
    }
    part def Gappy {
        attribute y : Real = 1.0;
        constraint broken { NoResult(y) <= 1.0 }
        constraint mystery { unknownFn(y) <= 1.0 }
    }
    part def Root2 {
        attribute r : Real = 1.0;
        constraint sq2 { r * r == 2.0 }
        constraint pos { r > 0.0 }
    }
}
"""


class TestCalcInliningAndEdges:
    @pytest.fixture()
    def calcs(self):
        return longeron.loads(CALC_MODEL)

    def test_abs_and_inlined_calc_with_local_binding(self, calcs):
        system = smt.to_smt(calcs, "Calcs::Box", free=("x",))
        assert system.gaps == []
        bound, result = system.maximize("x")
        assert result.status == "sat"
        assert float(Fraction(bound)) == pytest.approx(2.0)  # abs() binds tighter

    def test_negated_constraint_is_negated_in_the_encoding(self, calcs):
        system = smt.to_smt(calcs, "Calcs::Box", free=("x",))
        bound, result = system.maximize("x", exclude=("Box::bounded", "Box::squared"))
        assert result.status == "sat"
        assert float(Fraction(bound)) == pytest.approx(5.0)  # not(x > 5) == x <= 5

    def test_unencodable_invocations_become_gaps_not_crashes(self, calcs):
        system = smt.to_smt(calcs, "Calcs::Gappy", free=("y",))
        assert len(system.gaps) == 2
        assert any("has no result expression" in gap for gap in system.gaps)
        assert any("is not encodable" in gap for gap in system.gaps)
        assert system.check().status == "sat"  # the encodable rest still solves

    def test_algebraic_real_witness(self, calcs):
        system = smt.to_smt(calcs, "Calcs::Root2", free=("r",))
        result = system.check()
        assert result.status == "sat"
        assert result.witness["r"] == pytest.approx(2.0**0.5)  # sqrt(2), irrational

    def test_maximize_over_an_unsat_system_reports_it(self, calcs):
        system = smt.to_smt(calcs, "Calcs::Root2", free=("r",))
        system.assertions.append(("pin", system.variables["r"] == 0))
        bound, result = system.maximize("r")
        assert bound == "" and result.status == "unsat"

    def test_to_smt_rejects_non_parts_and_non_requirements(self, calcs):
        with pytest.raises(longeron.analysis.AnalysisError, match="is not a part definition"):
            smt.to_smt(calcs, "Calcs")
        with pytest.raises(longeron.analysis.AnalysisError, match="is not a requirement"):
            smt.to_smt(calcs, "Calcs::Box", requirements=("Calcs",))
