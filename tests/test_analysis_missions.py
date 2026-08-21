"""The multi-mission UAV catalog: interpreter-exact trades per mission.

``examples/uav_missions.sysml`` leans on real physics (sqrt/pow,
conditionals, calc invocations), which the CP-SAT mapper deliberately does
not encode -- these tests exercise the honest pattern for that scale:
``TradeStudy.all_architectures()``/``evaluate()`` walk the Cartesian
candidate space and the interpreter scores every mix exactly.  No solver
extra is required.
"""

from pathlib import Path

import pytest

import sysml2
from sysml2.analysis import AnalysisError, trades

EXAMPLES = Path(__file__).parent.parent / "examples"

MISSIONS = {
    "isr": ("UavMissions::IsrUav", "stationMinutes"),
    "logistics": ("UavMissions::LogisticsUav", "payloadRangeKgKm"),
    "intercept": ("UavMissions::InterceptUav", "maxTargetSpeed"),
}


@pytest.fixture(scope="module")
def model():
    return sysml2.load(EXAMPLES / "uav_missions.sysml", cache=False)


@pytest.fixture(scope="module")
def studies(model):
    return {name: trades.TradeStudy(model, qname) for name, (qname, _) in MISSIONS.items()}


@pytest.fixture(scope="module")
def spaces(studies):
    return {name: study.all_architectures() for name, study in studies.items()}


def front_2d(archs, metric):
    """The feasible (min missionCost, max metric) front."""

    feasible = [a for a in archs if a.verified]
    return trades.pareto(feasible, minimize=("missionCost",), maximize=(metric,))


def base_mix(arch):
    """A mix projected onto the shared points (equipment stripped)."""

    return tuple(
        sorted(
            (k, v)
            for k, v in arch.selection.items()
            if k in ("airframe", "motors", "props", "battery", "material")
        )
    )


class TestModelShape:
    def test_example_is_clean(self, model):
        assert sysml2.validate(model) == []

    def test_mission_points(self, studies):
        shared = {"airframe", "motors", "props", "battery", "material"}
        assert set(studies["isr"].points) == shared | {"sensor"}
        assert set(studies["logistics"].points) == shared | {"cargo"}
        assert set(studies["intercept"].points) == shared
        assert set(studies["intercept"].points["airframe"].variants) == {
            "boxQuad",
            "teardropQuad",
            "vtolWing",
            "dartInterceptor",
        }
        assert set(studies["intercept"].points["material"].variants) == {
            "aluminum",
            "carbonFiber",
        }

    def test_candidate_space_sizes(self, spaces):
        assert len(spaces["isr"]) == 4 * 3 * 3 * 3 * 2 * 3
        assert len(spaces["logistics"]) == 4 * 3 * 3 * 3 * 2 * 3
        assert len(spaces["intercept"]) == 4 * 3 * 3 * 3 * 2

    def test_derived_order_is_dependency_sorted(self, studies):
        # mission metrics may reference inherited derived attributes
        # (baseMass, usableEnergyJ, ...) regardless of member order
        for study in studies.values():
            seen = set()
            names = [n for n, _ in study.derived_order]
            for name, expr in study.derived_order:
                from sysml2.analysis._expr import free_refs

                for ref in free_refs(expr):
                    if ref[0] in names:
                        assert ref[0] in seen, f"{name} evaluated before its input {ref[0]}"
                seen.add(name)

    def test_cpsat_mapper_refuses_the_physics(self, studies):
        # sqrt/pow/conditionals are beyond the fixed-point encoder: the
        # solver methods stay loud instead of silently mis-encoding
        pytest.importorskip("ortools")
        with pytest.raises(AnalysisError):
            studies["isr"].enumerate()


class TestFronts:
    @pytest.mark.parametrize("name", list(MISSIONS))
    def test_front_is_a_real_staircase(self, spaces, name):
        metric = MISSIONS[name][1]
        front = front_2d(spaces[name], metric)
        assert len(front) >= 4  # a real trade, not a single point
        # brute-force cross-check of weak dominance
        feasible = [a for a in spaces[name] if a.verified]

        def dominated(a):
            return any(
                b.metrics["missionCost"] <= a.metrics["missionCost"]
                and b.metrics[metric] >= a.metrics[metric]
                and (
                    b.metrics["missionCost"] < a.metrics["missionCost"]
                    or b.metrics[metric] > a.metrics[metric]
                )
                for b in feasible
            )

        brute = {tuple(sorted(a.selection.items())) for a in feasible if not dominated(a)}
        assert {tuple(sorted(a.selection.items())) for a in front} == brute

    def test_feasible_counts(self, spaces):
        counts = {name: sum(a.verified for a in archs) for name, archs in spaces.items()}
        # teardropQuad adds ISR mixes (its bay takes the grade-2 sensor)
        # and intercept mixes; its 1.0 kg bay excludes every parcel; the
        # material axis doubles the space without moving the stories
        assert counts == {"isr": 50, "logistics": 47, "intercept": 114}

    def test_intercept_front_pits_wings_against_the_teardrop(self, spaces):
        """The design-space answer to "are wings necessary?": both the
        winged dart and the wingless teardrop earn front seats."""

        front = front_2d(spaces["intercept"], "maxTargetSpeed")
        airframes = {a.selection["airframe"] for a in front}
        assert {"dartInterceptor", "teardropQuad"} <= airframes
        assert len(front) >= 4


class TestFamilyWinners:
    def test_winged_vtol_wins_isr(self, spaces):
        best = max(
            (a for a in spaces["isr"] if a.verified), key=lambda a: a.metrics["stationMinutes"]
        )
        assert best.selection["airframe"] == "vtolWing"
        assert best.selection["material"] == "carbonFiber"  # grams buy minutes
        assert best.metrics["stationMinutes"] > 100.0

    def test_winged_vtol_wins_logistics(self, spaces):
        best = max(
            (a for a in spaces["logistics"] if a.verified),
            key=lambda a: a.metrics["payloadRangeKgKm"],
        )
        assert best.selection["airframe"] == "vtolWing"

    def test_interceptor_wins_the_dash(self, spaces):
        feasible = [a for a in spaces["intercept"] if a.verified]
        best = max(feasible, key=lambda a: a.metrics["maxTargetSpeed"])
        assert best.selection["airframe"] == "dartInterceptor"
        assert best.selection["motors"] == "sprintMotor"
        # every non-interceptor stays below the interceptor's top three
        darts = sorted(
            (
                a.metrics["maxTargetSpeed"]
                for a in feasible
                if a.selection["airframe"] == "dartInterceptor"
            ),
            reverse=True,
        )
        others = max(
            a.metrics["maxTargetSpeed"]
            for a in feasible
            if a.selection["airframe"] != "dartInterceptor"
        )
        assert others < darts[2]

    def test_cheap_quad_wins_the_low_cost_corners(self, spaces):
        for name in ("isr", "logistics", "intercept"):
            cheapest = min(
                (a for a in spaces[name] if a.verified), key=lambda a: a.metrics["missionCost"]
            )
            assert cheapest.selection["airframe"] == "boxQuad", name
            assert cheapest.selection["material"] == "aluminum", name  # Al owns cheap

    def test_a_robust_mix_sits_on_two_fronts(self, spaces):
        fronts = {
            name: {base_mix(a) for a in front_2d(spaces[name], MISSIONS[name][1])}
            for name in MISSIONS
        }
        overlap = fronts["isr"] & fronts["logistics"]
        assert overlap  # the winged std/slim bird serves both
        assert any(dict(mix)["airframe"] == "vtolWing" for mix in overlap)
        # nothing is on all three fronts: missions really pull apart
        assert not (overlap & fronts["intercept"])

    def test_both_materials_earn_front_seats(self, spaces):
        """The material axis is a real trade: carbon's lighter structure
        buys endurance/payload-range seats on the mass-driven fronts,
        aluminum keeps every cheap corner -- and the intercept front is
        ALL aluminum, because dash physics never rewards the grams."""

        mats = {
            name: {a.selection["material"] for a in front_2d(spaces[name], MISSIONS[name][1])}
            for name in MISSIONS
        }
        assert mats["isr"] == {"aluminum", "carbonFiber"}
        assert mats["logistics"] == {"aluminum", "carbonFiber"}
        assert mats["intercept"] == {"aluminum"}


class TestExplainableInfeasibility:
    def test_interceptor_cannot_do_logistics(self, spaces):
        darts = [a for a in spaces["logistics"] if a.selection["airframe"] == "dartInterceptor"]
        assert darts and all(not a.verified for a in darts)
        assert all("cargoFits" in a.violations for a in darts)

    def test_teardrop_bay_too_slim_for_parcels(self, spaces):
        # 1.0 kg capacity < the smallest bay + parcel (1.12 kg): the
        # dash specialist is honestly excluded from the freight trade
        tears = [a for a in spaces["logistics"] if a.selection["airframe"] == "teardropQuad"]
        assert tears and all(not a.verified for a in tears)
        assert all("cargoFits" in a.violations for a in tears)

    def test_interceptor_cannot_carry_the_isr_sensor(self, spaces):
        darts = [a for a in spaces["isr"] if a.selection["airframe"] == "dartInterceptor"]
        assert darts and all(not a.verified for a in darts)
        for arch in darts:
            assert {"sensorFits", "sensorGrade"} & set(arch.violations)

    def test_sprint_motors_need_more_battery_than_exists(self, studies):
        arch = studies["intercept"].evaluate(
            {
                "airframe": "boxQuad",
                "motors": "sprintMotor",
                "props": "slimProp",
                "battery": "packMax",
                "material": "aluminum",
            }
        )
        assert not arch.verified
        assert "packPower" in arch.violations  # 4 x 950 W > any pack

    def test_eco_motors_cannot_vtol_the_big_pack(self, studies):
        for material in ("aluminum", "carbonFiber"):  # even carbon's grams
            arch = studies["isr"].evaluate(
                {
                    "airframe": "vtolWing",
                    "motors": "ecoMotor",
                    "props": "slimProp",
                    "battery": "packMax",
                    "sensor": "stareEoIr",
                    "material": material,
                }
            )
            assert not arch.verified
            assert arch.violations == ["isrLift"]

    def test_feasible_mix_has_no_violations(self, studies):
        arch = studies["isr"].evaluate(
            {
                "airframe": "vtolWing",
                "motors": "stdMotor",
                "props": "slimProp",
                "battery": "packMax",
                "sensor": "stareEoIr",
                "material": "carbonFiber",
            }
        )
        assert arch.verified and arch.violations == []
        assert arch.metrics["stationMinutes"] == pytest.approx(147.386, abs=0.01)


class TestPhysicsSanity:
    def test_wing_beats_rotor_loiter(self, studies):
        """The whole point of the wing: loiter power is a fraction of hover."""

        winged = studies["isr"].evaluate(
            {
                "airframe": "vtolWing",
                "motors": "stdMotor",
                "props": "slimProp",
                "battery": "packMax",
                "sensor": "stareEoIr",
                "material": "carbonFiber",
            }
        )
        assert winged.metrics["loiterPowerW"] < 0.15 * winged.metrics["hoverPowerW"]

    def test_asymmetric_logistics_legs(self, studies):
        arch = studies["logistics"].evaluate(
            {
                "airframe": "vtolWing",
                "motors": "stdMotor",
                "props": "slimProp",
                "battery": "packMax",
                "cargo": "parcelBayL",
                "material": "aluminum",
            }
        )
        assert arch.metrics["outboundPowerW"] > arch.metrics["returnPowerW"]

    def test_intercept_triangle(self, studies):
        arch = studies["intercept"].evaluate(
            {
                "airframe": "dartInterceptor",
                "motors": "sprintMotor",
                "props": "slimProp",
                "battery": "packLite",
                "material": "aluminum",
            }
        )
        vd = arch.metrics["dashSpeed"]
        vt = 25.0
        d0 = 3000.0
        assert arch.metrics["interceptSeconds"] == pytest.approx(
            d0 / (vd * vd - vt * vt) ** 0.5, rel=1e-9
        )
        # the battery-limited reachable target speed inverts the triangle
        t_max = arch.metrics["dashSeconds"]
        assert arch.metrics["maxTargetSpeed"] == pytest.approx(
            (vd * vd - (d0 / t_max) ** 2) ** 0.5, rel=1e-9
        )

    def test_unreachable_dash_clamps_to_zero(self, studies):
        # eco quad with a lifter prop: dash speed under the target's --
        # the guarded sqrt keeps the metric at a clean 0, not a crash
        arch = studies["intercept"].evaluate(
            {
                "airframe": "boxQuad",
                "motors": "stdMotor",
                "props": "lifterProp",
                "battery": "packLite",
                "material": "aluminum",
            }
        )
        assert not arch.verified
        assert "canCatch" in arch.violations

    def test_wings_versus_teardrop_is_a_drag_story(self, studies, spaces):
        """The model answers "are wings necessary?" from physics, not
        from a hardcoded verdict: with identical components the teardrop
        shell out-dashes the box quad purely on its BUILT-UP CdA (the
        skinned lathe earns ~0.0125 m^2 vs the open frame's 0.055), and
        each airframe's best feasible mix ranks dart > teardrop > box
        quad -- the dart's ~0.006 buildup beats even a 4-motor power
        advantage, but only narrowly."""

        def dash(airframe):
            return (
                studies["intercept"]
                .evaluate(
                    {
                        "airframe": airframe,
                        "motors": "stdMotor",
                        "props": "slimProp",
                        "battery": "packMid",
                        "material": "aluminum",
                    }
                )
                .metrics["dashSpeed"]
            )

        assert dash("teardropQuad") > 1.3 * dash("boxQuad")
        best = {
            af: max(
                a.metrics["maxTargetSpeed"]
                for a in spaces["intercept"]
                if a.verified and a.selection["airframe"] == af
            )
            for af in ("boxQuad", "teardropQuad", "dartInterceptor")
        }
        assert best["teardropQuad"] > best["boxQuad"] + 5.0
        gap = best["dartInterceptor"] - best["teardropQuad"]
        assert 0.0 < gap < 5.0  # wings win the top end, narrowly
