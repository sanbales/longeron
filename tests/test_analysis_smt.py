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
    return longeron.load(EXAMPLES / "drone.sysml", cache=False)


class TestConsistency:
    def test_drone_requirements_are_consistent(self, drone):
        system = smt.to_smt(drone, "Drone::QuadCopter", requirements=("Drone::FlightEnvelope",))
        assert system.gaps == []
        result = system.check()
        assert result.status == "sat"
        assert result.witness["payloadMass"] == pytest.approx(0.2)
        assert result.witness["totalMass"] == pytest.approx(1.24)

    def test_calc_invocations_inline(self, drone):
        system = smt.to_smt(drone, "Drone::QuadCopter", requirements=("Drone::FlightEnvelope",))
        labels = [label for label, _ in system.assertions]
        assert "FlightEnvelope::hoverMargin [require]" in labels


class TestConflictCore:
    def test_over_constrained_names_conflict(self, drone):
        pkg = drone.find("Drone")
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
            "Drone::QuadCopter",
            requirements=("Drone::FlightEnvelope", "Drone::HeavyPayload"),
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
            "Drone::QuadCopter",
            requirements=("Drone::FlightEnvelope",),
            free=("payloadMass",),
        )
        bound, result = system.maximize("payloadMass")
        assert result.status == "sat"
        assert Fraction(bound) == Fraction(23, 50)  # 0.46, exact

    def test_strict_bound_is_open(self, drone):
        # only canHover (strict >): the supremum is reported with -epsilon
        system = smt.to_smt(drone, "Drone::QuadCopter", free=("payloadMass",))
        bound, result = system.maximize("payloadMass", exclude=("QuadCopter::takeoffMassLimit",))
        assert result.status == "sat"
        assert "epsilon" in bound
        assert bound.startswith(str(Fraction(7166, 2725)))  # ~2.6297 kg

    def test_witness_respects_free_variable(self, drone):
        system = smt.to_smt(drone, "Drone::QuadCopter", free=("payloadMass",))
        labels = [label for label, _ in system.assertions]
        assert "payloadMass.value" not in labels
        assert "maxTakeoffMass.value" in labels
