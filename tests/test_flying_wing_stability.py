"""The flying wings' stability & control checks, end to end.

The tailless shells of examples/deepscout carry no tail, so the model
must EARN their pitch trim story: quarter-chord sweep moves the neutral
point aft of the bay-loaded CG (static margin), the elevon band buys
pitch and roll authority, and the winglets on the swept tips buy yaw.
These tests pin the closed-form S&C figures the interpreter computes
from the StabilityControl calc package, the three requirement verdicts
(ScoutMissions::StabilityRequirements), the satisfy edges, and the
teaching beat: an UNSWEPT variant of either shell busts PitchStability,
so the constraint has teeth -- sweep is the trim mechanism, not styling.
"""

from math import radians, tan
from pathlib import Path

import pytest

import longeron
from longeron import model as M

EXAMPLES = Path(__file__).parent.parent / "examples"

SHELLS = ("FlyingWingSingle", "FlyingWingTwin")
REQUIREMENTS = ("PitchStability", "PitchRollAuthority", "YawStability")


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def interp(model):
    return longeron.Interpreter(model)


@pytest.fixture(scope="module")
def instances(interp):
    return {name: interp.instantiate(f"FlyingWings::{name}") for name in SHELLS}


def req(name):
    return f"ScoutMissions::StabilityRequirements::{name}"


class TestDerivedFigures:
    """The interpreter is the oracle: every S&C figure is a model calc."""

    def test_single_static_margin_matches_the_closed_form(self, instances):
        # hand derivation of the classic estimate, kept independent of
        # the model text: the CRANKED planform's two panels per side
        # (flat-TE center to the crank, swept trapezoid outboard),
        # composed by Raymer's multi-panel method -- area-weighted MAC
        # and area-weighted quarter-chord-of-MAC stations -- all over
        # the declared 0.82-MAC CG
        s = instances["FlyingWingSingle"].slots
        c_r = 2.0 * 0.32 / 1.45
        c_t = 0.45 * c_r
        half = 1.1
        le_slope = tan(radians(22.0)) + 0.25 * (c_r - c_t) / half
        te_slope = tan(radians(22.0)) - 0.75 * (c_r - c_t) / half
        y_c = (0.2794 + 2 * 0.03) / 2  # reference disc + declared margin
        crank_chord = c_r - (c_r - c_t) * y_c / half
        flat_te = c_r + te_slope * y_c  # the flat TE = center root chord

        def panel(root, tip, width, ac_of):
            t = tip / root
            area = width * (root + tip) / 2
            mac = 2.0 / 3.0 * root * (1 + t + t * t) / (1 + t)
            y_mac = width / 3.0 * (1 + 2 * t) / (1 + t)
            return area, mac, ac_of(y_mac)

        center = panel(flat_te, crank_chord, y_c, lambda y: 0.25 * flat_te + 0.75 * le_slope * y)
        outer = panel(
            crank_chord,
            c_t,
            half - y_c,
            lambda y: 0.25 * c_r + (y_c + y) * tan(radians(22.0)),
        )
        area = center[0] + outer[0]
        mac = (center[0] * center[1] + outer[0] * outer[1]) / area
        x_np = (center[0] * center[2] + outer[0] * outer[2]) / area
        assert s["rootChord"] == pytest.approx(c_r)
        assert s["mac"] == pytest.approx(mac)
        assert s["neutralPointAft"] == pytest.approx(x_np)
        assert s["staticMargin"] == pytest.approx((x_np - 0.82 * mac) / mac)

    def test_twin_stays_single_panel(self, instances):
        # the twin keeps the straight trapezoid: its MAC and neutral
        # point are the classic one-panel closed forms
        s = instances["FlyingWingTwin"].slots
        c_r = 2.0 * 0.327 / 1.45
        mac = 2.0 / 3.0 * c_r * (1 + 0.45 + 0.45**2) / 1.45
        y_mac = 2.6 / 6.0 * (1 + 2 * 0.45) / 1.45
        x_np = 0.25 * c_r + y_mac * tan(radians(22.0))
        assert s["mac"] == pytest.approx(mac)
        assert s["staticMargin"] == pytest.approx(x_np / mac - 0.91)

    def test_static_margins_sit_inside_the_tailless_band(self, instances):
        # the twin rides ~0.09 MAC ahead of its neutral point; the
        # single's flat-TE center carries chord the straight taper did
        # not have, so its composite MAC grows, its neutral point sits
        # at 0.892 MAC (not the trapezoid's 0.908), and the margin
        # lands at ~0.07 -- both inside the 0.05..0.15 teaching band
        assert instances["FlyingWingSingle"].slots["staticMargin"] == pytest.approx(
            0.0721, abs=0.0005
        )
        assert instances["FlyingWingTwin"].slots["staticMargin"] == pytest.approx(
            0.0885, abs=0.0005
        )

    def test_control_volumes(self, instances):
        # elevon pitch volume ~0.132/0.144 (S_e l_e / S MAC), the shared
        # band proxy's roll volume 3/64 exactly, and the winglet yaw
        # volumes above the 0.008 tailless floor -- the single's read
        # against its composite MAC and CG station
        single = instances["FlyingWingSingle"].slots
        twin = instances["FlyingWingTwin"].slots
        assert single["elevonPitchVolume"] == pytest.approx(0.1317, abs=0.0005)
        assert twin["elevonPitchVolume"] == pytest.approx(0.1436, abs=0.0005)
        for shell in (single, twin):
            assert shell["elevonRollVolume"] == pytest.approx(3.0 / 64.0)
        assert single["wingletYawVolume"] == pytest.approx(0.01067, abs=0.0002)
        assert twin["wingletYawVolume"] == pytest.approx(0.01181, abs=0.0002)

    def test_sweep_buys_the_margin_the_bay_spends(self, interp, instances):
        # the neutral point in MAC units RISES with sweep while the
        # declared CG stays on its bay rail: the margin is genuinely
        # sweep-dependent, not a constant offset
        for name in SHELLS:
            stock = instances[name].slots["staticMargin"]
            steeper = interp.instantiate(f"FlyingWings::{name}", sweepDeg=26.0)
            shallower = interp.instantiate(f"FlyingWings::{name}", sweepDeg=18.0)
            assert steeper.slots["staticMargin"] > stock > shallower.slots["staticMargin"]


class TestPodClearance:
    """The pusher pods buy their length from clearance geometry: base
    housing + disc clearance + the swept TE's aft rise across the disc
    -- so the single's flat-TE crank keeps the base pod, and the twin
    pays for the sweep at its outboard stations."""

    def test_center_section_covers_the_reference_disc(self, instances):
        s = instances["FlyingWingSingle"].slots
        assert s["centerSectionSpan"] == pytest.approx(0.2794 + 2 * 0.03)
        assert s["crankY"] > 0.2794 / 2  # the disc rides inside the flat TE
        assert s["podTeRise"] == 0.0
        assert s["podLength"] == pytest.approx(0.06 + 0.03)

    def test_twin_pays_the_te_rise(self, instances):
        # TE slope = tan(sweep) - 0.75 (c_r - c_t) / half; the worst
        # point under a disc at station y is y + r on an aft-swept TE
        s = instances["FlyingWingTwin"].slots
        c_r = 2.0 * 0.327 / 1.45
        te_slope = tan(radians(22.0)) - 0.75 * (c_r - 0.45 * c_r) / 1.3
        rise = te_slope * 0.2794 / 2
        assert s["podStation"] == pytest.approx(2.6 / 6.0)
        assert s["podTeRise"] == pytest.approx(rise)
        assert s["podLength"] == pytest.approx(0.09 + rise)
        assert s["podLength"] > instances["FlyingWingSingle"].slots["podLength"]

    def test_unswept_variant_clamps_the_rise(self, interp):
        # zero sweep rakes the TE forward: the rise clamps at 0 and the
        # pod falls back to the base + clearance housing
        for name in SHELLS:
            plank = interp.instantiate(f"FlyingWings::{name}", sweepDeg=0.0)
            assert plank.slots["podTeRise"] == 0.0
            assert plank.slots["podLength"] == pytest.approx(0.09)

    def test_sweep_costs_twin_drag_and_the_single_keeps_its_buildup(self, instances):
        # the derived pod prices the sweep in the drag ledger (the
        # twin's CdA carries the longer pods, +0.33% over the fixed
        # 0.09 m pods), and both shells now carry their blended bay
        # pod's exposed skin on top of the pre-bay buildup (single
        # 0.014363, twin 0.017604)
        assert instances["FlyingWingSingle"].slots["dragArea"] == pytest.approx(0.015363, abs=2e-6)
        assert instances["FlyingWingTwin"].slots["dragArea"] == pytest.approx(0.018463, abs=2e-6)


class TestRequirementVerdicts:
    def test_both_shells_pass_all_three_checks(self, interp, instances):
        for shell, inst in instances.items():
            for name in REQUIREMENTS:
                result = interp.check_requirement(req(name), subject=inst)
                assert result.satisfied, (shell, name)

    def test_unswept_variant_busts_pitch_stability(self, interp):
        """THE TEACHING BEAT: zero the quarter-chord sweep and the
        neutral point falls back to the root quarter-chord, roughly
        half a MAC AHEAD of the bay-loaded CG -- a tailless plank has
        no pitch trim mechanism, and the check says so."""

        for name in SHELLS:
            plank = interp.instantiate(f"FlyingWings::{name}", sweepDeg=0.0)
            assert plank.slots["staticMargin"] < -0.4
            result = interp.check_requirement(req("PitchStability"), subject=plank)
            assert not result.satisfied, name

    def test_unswept_variant_loses_its_control_arms_too(self, interp):
        # the same sweep pays the elevon and winglet arms: the plank
        # busts authority and yaw along with stability
        plank = interp.instantiate("FlyingWings::FlyingWingSingle", sweepDeg=0.0)
        for name in ("PitchRollAuthority", "YawStability"):
            assert not interp.check_requirement(req(name), subject=plank).satisfied, name

    def test_margin_ceiling_has_teeth_as_well(self, interp):
        # a CG parked too far forward is over-stable: the washout/reflex
        # trim would have to carry a nose-down moment that spends the
        # cruise L/D, and the band's UPPER edge refuses it
        nose_heavy = interp.instantiate("FlyingWings::FlyingWingSingle", cgMac=0.70)
        assert nose_heavy.slots["staticMargin"] > 0.15
        assert not interp.check_requirement(req("PitchStability"), subject=nose_heavy).satisfied


class TestArchitectureWiring:
    def test_satisfy_edges_name_the_tailless_shells_only(self, model):
        # honest absence: the multirotors hover on their mixers and the
        # dart flies on a real tail -- none of them subjects a tailless
        # check, so the ONLY edges are the two flying wings' six
        edges = {
            (e.subsets[0], e.by)
            for e in model.find("ScoutMissions::StabilityRequirements").members
            if isinstance(e, M.SatisfyUsage)
        }
        assert edges == {
            (r, shell) for r in REQUIREMENTS for shell in ("FlyingWingSingle", "FlyingWingTwin")
        }

    def test_the_bands_live_in_the_model(self, interp):
        # every constant a check reads is a model attribute the
        # interpreter evaluates -- nothing is baked into Python
        base = "ScoutMissions::StabilityRequirements"
        assert interp.evaluate(f"{base}::PitchStability::marginFloor") == 0.05
        assert interp.evaluate(f"{base}::PitchStability::marginCeiling") == 0.15
        assert interp.evaluate(f"{base}::PitchRollAuthority::pitchVolumeFloor") == 0.05
        assert interp.evaluate(f"{base}::PitchRollAuthority::rollVolumeFloor") == 0.02
        assert interp.evaluate(f"{base}::YawStability::yawVolumeFloor") == 0.008

    def test_mission_reference_numbers_did_not_move(self, interp):
        # the S&C arc must not touch the mission story: the scoreboard's
        # reference design point stays exactly the T4 winners
        assert interp.evaluate("ScoutMissions::stationMinutes") == 274.6
        assert interp.evaluate("ScoutMissions::payloadRangeKgKm") == 184.7
        assert interp.evaluate("ScoutMissions::maxTargetSpeed") == 72.9
        assert interp.evaluate("ScoutMissions::fleetCost") == 9666.0
