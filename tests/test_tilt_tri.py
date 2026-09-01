"""The tilt-rotor tri's model chains, interpreter-exact.

``examples/deepscout/tilttri.sysml`` derives every price and prize of
the convertible from declared geometry and cited NOMINAL figures: the
tilt-mechanism mass per pivot, the wing-shadow hover download (the
shadowed disc fraction from the planform, the XV-15 / V-22 class
download factor), the tip-recovery uplift, and the centerline cruise
engine-out verdict.  These tests pin each chain against an independent
hand derivation, prove the download reaches BOTH hover ledgers (lift
and energy), and pin the honest absences: no FailSafeHover story for a
tri, no EngineOutYaw case for a craft that never cruises asymmetric.
"""

from math import acos, pi, sqrt
from pathlib import Path

import pytest

import longeron
from longeron import model as M

EXAMPLES = Path(__file__).parent.parent / "examples"

QNAME = "TiltRotors::TiltTriWing"


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def interp(model):
    return longeron.Interpreter(model)


@pytest.fixture(scope="module")
def shell(interp):
    return interp.instantiate(QNAME).slots


class TestDeclaredShell:
    """The buildups are chains over declared geometry, not quotes."""

    def test_mechanism_mass_is_per_pivot(self, shell):
        # 1% of design gross PER PIVOT, three pivots: the 3% total sits
        # inside the 2..4% tiltrotor conversion-system band
        assert shell["tiltMechMass"] == pytest.approx(3 * 0.01 * shell["designGrossKg"])
        assert shell["mass"] == pytest.approx(1.95 + shell["tipStructMass"] + shell["tiltMechMass"])
        assert shell["tipStructMass"] > 0.15  # the doubler is real mass

    def test_pod_chain_reuses_arc_b_with_the_pivot_member(self, shell):
        # base housing + disc clearance (the flying-wing chain) plus the
        # pivot bearing's setback -- and the disc rides tiltArm aft of
        # the pivot, the conversion-clearance guarantee
        assert shell["tiltArm"] == pytest.approx(0.06 + 0.03)
        assert shell["podLength"] == pytest.approx(shell["tiltPivotSetback"] + shell["tiltArm"])
        assert shell["podStation"] == pytest.approx(0.5 * shell["wingSpan"])

    def test_shadow_fraction_matches_the_segment_closed_form(self, shell):
        # independent hand derivation: the disc centre lands at the
        # pivot in plan view, so the shadow is the circular segment
        # between the setback and the setback + tip chord, halved for
        # the inboard half-disc
        r = 0.5 * 0.2794
        tip_chord = 0.5 * (2.0 * 0.30 / 1.5)

        def segment(m):
            m = min(1.0, m)
            return (acos(m) - m * sqrt(1.0 - m * m)) / pi

        expected = 0.5 * (segment(0.04 / r) - segment((0.04 + tip_chord) / r))
        assert shell["tipShadowFraction"] == pytest.approx(expected)
        # the whole chord band lies inside the disc radius here, so the
        # far segment is empty and the tip shadow is a real ~16%
        assert 0.10 < shell["tipShadowFraction"] < 0.25
        # two of three discs shadow the wing; the nose disc rides clear
        assert shell["hoverShadowFraction"] == pytest.approx(2.0 / 3.0 * shell["tipShadowFraction"])

    def test_download_reaches_both_hover_ledgers(self, shell):
        lift = 1.0 - 0.10 * shell["hoverShadowFraction"]
        assert shell["hoverLiftFraction"] == pytest.approx(lift)
        # the LIFT ledger: thrust covers weight over the shadowed lift
        assert shell["hoverThrustFactor"] == pytest.approx(1.45 / lift)
        assert shell["hoverThrustFactor"] > 1.45  # the tax is a tax
        # the ENERGY ledger: momentum power scales T^1.5 / sqrt(A) at
        # T = W / lift, so the effective disk area carries lift^3
        # exactly (on top of the openTri-convention yaw-trim haircut)
        assert shell["diskAreaFactor"] == pytest.approx(2.9 * lift**3)

    def test_tip_recovery_is_the_derived_family_figure(self, shell):
        assert shell["tipPropBonus"] == pytest.approx(1.0 + 2.0 * 0.2794 / 2.4)

    def test_the_wing_pays_less_skin_than_the_cruciform(self, interp, shell):
        # the tiltrotor's cruise case, earned in the wetted-area ledger:
        # one wing + hull + tail + two pods undercuts the tail-sitter's
        # two cruciform pairs
        vtol = interp.instantiate("WingedVtol::VtolWing").slots
        assert shell["dragArea"] < vtol["dragArea"]
        assert shell["dragArea"] > 0.015  # ... but it is no dart


class TestCruiseEngineOut:
    """The centerline redundancy: a verdict, not a doc claim."""

    REQ = "TiltRotors::CruiseEngineOut"

    def test_the_tilt_tri_passes(self, interp):
        inst = interp.instantiate(QNAME)
        assert interp.check_requirement(self.REQ, subject=inst).satisfied

    def test_power_check_matches_the_closed_form(self, shell):
        # hand derivation of the model's CruisePower call at design
        # gross, bare Oswald (the shut tips surrender their recovery),
        # reference-station efficiencies
        w = shell["designGrossKg"] * 9.81
        v = shell["cruiseSpeed"]
        parasite = 0.5 * 1.225 * shell["dragArea"] * v**3
        induced = 2.0 * w * w / (1.225 * v * pi * shell["oswald"] * shell["wingSpan"] ** 2)
        expected = (parasite + induced) / (0.82 * 0.83)
        assert shell["engineOutCruisePowerW"] == pytest.approx(expected)
        # the nose puller holds cruise with a wide margin: the prize the
        # attrition ledger will price low
        assert shell["engineOutCruisePowerW"] < 0.25 * shell["engineOutStationW"]

    def test_satisfy_edge_lives_in_the_branch_file(self, model):
        edges = {
            (e.subsets[0], e.by)
            for e in model.find("TiltRotors").members
            if isinstance(e, M.SatisfyUsage)
        }
        assert edges == {("CruiseEngineOut", "TiltTriWing")}

    def test_honest_absences_point_both_ways(self, model):
        # hover engine-out is fatal for a tri: no FailSafeHover edge
        # exists for the tilt-tri anywhere (and none CAN -- the shell is
        # not a MultiRotor), and the craft never cruises asymmetric, so
        # no EngineOutYaw edge names it either
        for package in ("Rotorcraft", "ScoutMissions::StabilityRequirements", "TiltRotors"):
            for e in model.find(package).members:
                if isinstance(e, M.SatisfyUsage):
                    assert (e.subsets[0], e.by) == ("CruiseEngineOut", "TiltTriWing") or (
                        "TiltTri" not in e.by
                    )

    def test_tip_twin_still_has_no_cruise_engine_out_subject(self, interp):
        # the tip twin keeps NOTHING once its mirror station is shut:
        # its shell declares no engineOutCruisePowerW, so the check's
        # assume constraint cannot even bind -- the honest absence the
        # requirement doc states
        twin = interp.instantiate("FlyingWings::FlyingWingTwinTip")
        assert "engineOutCruisePowerW" not in twin.slots


class TestTransitionCeiling:
    """The declared fidelity limit is IN the model text."""

    def test_the_branch_doc_declares_the_ceiling(self, model):
        doc = model.find("TiltRotors").doc or ""
        assert "TRANSITION is not modeled" in doc
        assert "ENDPOINT" in doc
