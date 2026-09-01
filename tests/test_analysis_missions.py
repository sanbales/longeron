"""The multi-mission trade space of the DeepScout program.

``examples/deepscout/missions.sysml`` leans on real physics (sqrt/pow,
conditionals, calc invocations), which the CP-SAT mapper deliberately does
not encode -- these tests exercise the honest pattern for that scale:
``TradeStudy.all_architectures()``/``evaluate()`` walk the Cartesian
candidate space and the interpreter scores every mix exactly.  No solver
extra is required.
"""

import typing
from pathlib import Path

import pytest

import longeron
from longeron.analysis import AnalysisError, trades

EXAMPLES = Path(__file__).parent.parent / "examples"

MISSIONS = {
    "isr": ("ScoutMissions::IsrUav", "stationMinutes"),
    "logistics": ("ScoutMissions::LogisticsUav", "payloadRangeKgKm"),
    "intercept": ("ScoutMissions::InterceptUav", "maxTargetSpeed"),
}

#: the catapult-launched branch of 0.12 (never hover-capable); the tip-prop
#: twin of 0.13 crosses the courier's pusher stations root-against-tip
FLYING_WINGS = {"flyingWingSingle", "flyingWingTwin", "flyingWingTwinTip"}


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


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
        assert longeron.validate(model) == []

    def test_mission_points(self, studies):
        shared = {"airframe", "motors", "props", "battery", "material"}
        assert set(studies["isr"].points) == shared | {"sensor"}
        assert set(studies["logistics"].points) == shared | {"cargo"}
        assert set(studies["intercept"].points) == shared
        assert set(studies["intercept"].points["airframe"].variants) == {
            "boxQuad",
            "teardropQuad",
            "openTri",
            "hexLifter",
            "coaxOcto",
            "ringOcto",
            "vtolWing",
            "dartInterceptor",
            "flyingWingSingle",
            "flyingWingTwin",
            "flyingWingTwinTip",
        }
        assert set(studies["intercept"].points["battery"].variants) == {
            "tattu3s",
            "tattu5200",
            "tattu10000",
            "tattu16000",
            "liion6s6p",
        }
        assert set(studies["intercept"].points["motors"].variants) == {
            "mt2213",
            "mn4006",
            "x4112s",
            "at4120",
        }
        assert set(studies["intercept"].points["material"].variants) == {
            "aluminum",
            "carbonFiber",
        }

    def test_candidate_space_sizes(self, spaces):
        # the architecture x part-class crossing: 11 airframes x 4 motors
        # x 4 props x 5 packs x 2 materials (the legacy fleet space was
        # 4 x 3 x 3 x 4 x 2 = 288 shared mixes; the flying wings of 0.12
        # grew the 8-airframe crossing to 10, and the twin's tip-prop
        # variant makes it 11)
        assert len(spaces["isr"]) == 11 * 4 * 4 * 5 * 2 * 3
        assert len(spaces["logistics"]) == 11 * 4 * 4 * 5 * 2 * 3
        assert len(spaces["intercept"]) == 11 * 4 * 4 * 5 * 2

    def test_derived_order_is_dependency_sorted(self, studies):
        # mission metrics may reference inherited derived attributes
        # (baseMass, usableEnergyJ, ...) regardless of member order
        for study in studies.values():
            seen = set()
            names = [n for n, _ in study.derived_order]
            for name, expr in study.derived_order:
                from longeron.analysis._expr import free_refs

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

    LEGACY: typing.ClassVar[dict[str, set[str]]] = {
        "airframe": {"boxQuad", "teardropQuad", "vtolWing", "dartInterceptor"},
        "motors": {"mn4006", "x4112s", "at4120"},
        "props": {"apc11x55", "apc13x65", "tm15x5"},
        "battery": {"tattu5200", "tattu10000", "tattu16000", "liion6s6p"},
    }

    def test_feasible_counts(self, spaces):
        counts = {name: sum(a.verified for a in archs) for name, archs in spaces.items()}
        # the crossed catalog after the dash-envelope honesty of 0.13:
        # ISR and logistics grow by exactly the tip twin's seats (the
        # gust placard and the tilt cap live in the intercept chain
        # only; the tail-sitter's tip-structure mass retires a few of
        # its courier margins), while intercept collapses from 526 --
        # the placard caps every wing at its wing loading, the tilt cap
        # retires five of the six rotor families outright, and only the
        # teardrop keeps a rotor-borne catcher's seat
        assert counts == {"isr": 328, "logistics": 397, "intercept": 316}

    def test_crossing_is_purely_additive(self, spaces):
        # every pre-crossing mix keeps its verdict axes: restricted to
        # the legacy variants, the ISR count is still the historical 54,
        # and the two missions the 0.13 physics touches move for stated
        # reasons -- the dash envelope retires the legacy catchers that
        # only ever caught on paper speed (166 -> 120), and the
        # tail-sitter's tip-structure mass costs it six courier margins
        # (64 -> 58)
        def legacy(arch):
            return all(arch.selection[k] in v for k, v in self.LEGACY.items())

        counts = {
            name: sum(a.verified for a in archs if legacy(a)) for name, archs in spaces.items()
        }
        assert counts == {"isr": 54, "logistics": 58, "intercept": 120}

    def test_intercept_front_pits_wings_against_the_teardrop(self, spaces):
        """The design-space answer to "are wings necessary?": both the
        winged dart and the wingless teardrop earn front seats."""

        front = front_2d(spaces["intercept"], "maxTargetSpeed")
        airframes = {a.selection["airframe"] for a in front}
        assert {"dartInterceptor", "teardropQuad"} <= airframes
        assert len(front) >= 4


class TestFamilyWinners:
    def test_flying_wing_wins_isr(self, spaces):
        """The catapult-launched single-pusher wing spends nothing on
        hover and turns the li-ion pack's watt-hours straight into
        loiter -- it out-sits every hover-capable airframe."""

        best = max(
            (a for a in spaces["isr"] if a.verified), key=lambda a: a.metrics["stationMinutes"]
        )
        assert best.selection["airframe"] == "flyingWingSingle"
        assert best.selection["material"] == "carbonFiber"  # grams buy minutes
        assert best.selection["battery"] == "liion6s6p"  # chemistry buys the loiter
        assert best.metrics["stationMinutes"] > 240.0  # past the four-hour ramp

    def test_winged_vtol_keeps_the_hover_capable_isr_crown(self, spaces):
        best = max(
            (
                a
                for a in spaces["isr"]
                if a.verified and a.selection["airframe"] not in FLYING_WINGS
            ),
            key=lambda a: a.metrics["stationMinutes"],
        )
        assert best.selection["airframe"] == "vtolWing"
        assert best.selection["material"] == "carbonFiber"  # grams buy minutes
        assert best.selection["battery"] == "liion6s6p"  # chemistry buys the loiter
        assert best.metrics["stationMinutes"] > 100.0

    def test_flying_wing_twin_wins_logistics(self, spaces):
        """The twin's gentle Antigravity pushers stay inside the li-ion
        discharge ceiling (no hover climb to feed), so the ENERGY pack
        wins the delivery trade the winged VTOL had to fly on LiPo --
        and the TIP-STATION variant takes the crown from the root: at
        courier speed the derived vortex recovery buys more radius than
        its tip-structure mass costs (the engine-out price it pays
        instead is pinned by the stability tests)."""

        best = max(
            (a for a in spaces["logistics"] if a.verified),
            key=lambda a: a.metrics["payloadRangeKgKm"],
        )
        assert best.selection["airframe"] == "flyingWingTwinTip"
        assert best.selection["motors"] == "mn4006"
        assert best.selection["battery"] == "liion6s6p"
        assert best.metrics["payloadRangeKgKm"] > 180.0

    def test_winged_vtol_keeps_the_hover_capable_logistics_crown(self, spaces):
        best = max(
            (
                a
                for a in spaces["logistics"]
                if a.verified and a.selection["airframe"] not in FLYING_WINGS
            ),
            key=lambda a: a.metrics["payloadRangeKgKm"],
        )
        assert best.selection["airframe"] == "vtolWing"
        # punch over chemistry: the parcel lift wants LiPo watts
        assert best.selection["battery"] == "tattu16000"

    def test_interceptor_wins_the_dash(self, spaces):
        feasible = [a for a in spaces["intercept"] if a.verified]
        best = max(feasible, key=lambda a: a.metrics["maxTargetSpeed"])
        assert best.selection["airframe"] == "dartInterceptor"
        assert best.selection["motors"] == "at4120"
        # the punch axis: no li-ion pack feeds the 2 kW dash motor
        assert all(
            a.selection["battery"] != "liion6s6p"
            for a in feasible
            if a.selection["motors"] == "at4120"
        )
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

    def test_cheap_corners_split_by_mission(self, spaces):
        # the flying wing takes the ISR cheap corner (a bench-kit MT2213
        # and 3S pack loiter 37 wing-borne minutes -- no multirotor gets
        # the gimbal aloft on the small class); the quad keeps the
        # logistics corner; the crossing hands intercept's to the
        # small-class teardrop (an MT2213 dash bird on the slick shell
        # undercuts every 6S mix)
        cheapest = min(
            (a for a in spaces["isr"] if a.verified), key=lambda a: a.metrics["missionCost"]
        )
        assert cheapest.selection["airframe"] == "flyingWingSingle"
        assert cheapest.selection["motors"] == "mt2213"
        assert cheapest.selection["battery"] == "tattu3s"
        assert cheapest.selection["material"] == "aluminum"  # Al owns cheap
        cheapest = min(
            (a for a in spaces["logistics"] if a.verified),
            key=lambda a: a.metrics["missionCost"],
        )
        assert cheapest.selection["airframe"] == "boxQuad"
        assert cheapest.selection["material"] == "aluminum"
        cheapest = min(
            (a for a in spaces["intercept"] if a.verified),
            key=lambda a: a.metrics["missionCost"],
        )
        assert cheapest.selection["airframe"] == "teardropQuad"
        assert cheapest.selection["motors"] == "mt2213"
        assert cheapest.selection["battery"] == "tattu3s"
        assert cheapest.selection["material"] == "aluminum"

    def test_the_specialists_split_the_fronts(self, spaces):
        """Before the flying wings joined, one winged-VTOL base mix sat
        on both the ISR and logistics fronts -- the buy-once bird.  The
        specialists ended that: the single wing owns the whole ISR
        front, the tip-station twin takes the logistics top (its root
        sibling is dominated seat for seat: same invoice, less radius),
        and no base mix sits on two fronts anymore, let alone three."""

        fronts = {
            name: {base_mix(a) for a in front_2d(spaces[name], MISSIONS[name][1])}
            for name in MISSIONS
        }
        assert {dict(mix)["airframe"] for mix in fronts["isr"]} == {"flyingWingSingle"}
        log_airframes = {dict(mix)["airframe"] for mix in fronts["logistics"]}
        assert "flyingWingTwinTip" in log_airframes
        assert "flyingWingTwin" not in log_airframes  # dominated by its tip variant
        assert not (fronts["isr"] & fronts["logistics"])
        assert not (fronts["isr"] & fronts["logistics"] & fronts["intercept"])

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


class TestVolumeLedger:
    """The bayFit axis: payloads need ROOM, not just lift."""

    def test_catalog_declares_the_volumes(self, studies):
        sensors = studies["isr"].points["sensor"].variants
        assert sensors["runcamSplit"]["volumeM3"] == pytest.approx(0.00006)
        assert sensors["zenmuseH20"]["volumeM3"] == pytest.approx(0.00276)
        assert sensors["gremsyT3"]["volumeM3"] == pytest.approx(0.0088)
        cargo = studies["logistics"].points["cargo"].variants
        # the winch stows only its mechanism (the parcel rides the line):
        # the heaviest lift makes the smallest bay demand
        assert cargo["parcelBayL"]["stowedVolume"] < cargo["parcelBayS"]["stowedVolume"]
        assert cargo["parcelBayM"]["stowedVolume"] > cargo["parcelBayS"]["stowedVolume"]
        packs = studies["isr"].points["battery"].variants
        assert all(slots["volumeM3"] > 0 for slots in packs.values())
        # the li-ion holders make a boxier brick than the biggest LiPo
        assert packs["liion6s6p"]["volumeM3"] > packs["tattu16000"]["volumeM3"]

    def test_every_airframe_declares_a_usable_bay(self, studies):
        frames = studies["isr"].points["airframe"].variants
        for name, slots in frames.items():
            assert slots["grossVolume"] > 0, name
            assert 0.5 <= slots["usableVolumeFraction"] <= 0.8, name
            assert slots["usableVolume"] == pytest.approx(
                slots["grossVolume"] * slots["usableVolumeFraction"]
            ), name
            assert slots["bayShape"] in {"box", "hull", "ogive"}, name
            assert slots["equipmentBayFactor"] in (0.0, 1.0), name
        # shapes per family: boxes under the open rotor hubs, hull bays
        # inside the lathed bodies, blended ogive pods on the wings
        for name in ("boxQuad", "openTri", "hexLifter", "coaxOcto", "ringOcto"):
            assert frames[name]["bayShape"] == "box"
            assert frames[name]["equipmentBayFactor"] == 0.0  # pack on the hub stack
        for name in ("teardropQuad", "vtolWing", "dartInterceptor"):
            assert frames[name]["bayShape"] == "hull"
            assert frames[name]["equipmentBayFactor"] == 1.0
        for name in ("flyingWingSingle", "flyingWingTwin"):
            assert frames[name]["bayShape"] == "ogive"
            assert frames[name]["equipmentBayFactor"] == 1.0

    def test_gimbal_no_longer_fits_the_teardrop(self, studies):
        # the teardrop carries the H20's 0.68 kg with ease -- but the
        # hull that earns its drag advantage has no ROOM for a gimbal
        # plus the pack plus the avionics: the mass ledger admits what
        # the volume ledger refuses
        mix = {
            "airframe": "teardropQuad",
            "motors": "mt2213",
            "props": "apc1045",
            "battery": "tattu3s",
            "sensor": "zenmuseH20",
            "material": "carbonFiber",
        }
        arch = studies["isr"].evaluate(mix)
        assert "bayFit" in arch.violations
        margins = studies["isr"].margins(mix)
        assert margins["bayFit"]["margin"] < 0.0
        assert margins["sensorFits"]["ok"]  # the mass ledger still admits it

    def test_survey_kit_needs_the_wide_ring(self, spaces):
        # the assembled Gremsy + a7R envelope outgrows every bay but the
        # flat octo's wide box: the survey kit's only feasible perch
        perches = {
            a.selection["airframe"]
            for a in spaces["isr"]
            if a.verified and a.selection["sensor"] == "gremsyT3"
        }
        assert perches == {"ringOcto"}

    def test_winch_hangs_where_the_cradle_cannot_stow(self, studies):
        # the tail-sitter's 0.12 m fuselage refuses the mid-size cradle's
        # parcel envelope, but the winch bay stows only its mechanism --
        # the 4 kg slung load keeps flying
        base = {
            "airframe": "vtolWing",
            "motors": "x4112s",
            "props": "apc11x55",
            "battery": "tattu16000",
            "material": "carbonFiber",
        }
        cradle = studies["logistics"].evaluate({**base, "cargo": "parcelBayM"})
        assert cradle.violations == ["bayFit"]
        winch = studies["logistics"].evaluate({**base, "cargo": "parcelBayL"})
        assert winch.verified

    def test_winner_bays_close_with_margin(self, studies):
        # the mission winners keep flying because their bays genuinely
        # hold their stowage -- demand strictly inside the usable volume
        isr = studies["isr"].evaluate(
            {
                "airframe": "flyingWingSingle",
                "motors": "mn4006",
                "props": "apc11x55",
                "battery": "liion6s6p",
                "sensor": "zenmuseH20",
                "material": "carbonFiber",
            }
        )
        assert isr.verified
        assert isr.metrics["bayDemandVolume"] == pytest.approx(0.00276 + 0.00108 + 0.0003)
        log = studies["logistics"].evaluate(
            {
                "airframe": "flyingWingTwinTip",
                "motors": "mn4006",
                "props": "apc11x55",
                "battery": "liion6s6p",
                "cargo": "parcelBayM",
                "material": "carbonFiber",
            }
        )
        assert log.verified
        assert log.metrics["bayDemandVolume"] == pytest.approx(0.0055 + 0.00108 + 0.0003)

    def test_open_frames_stack_their_equipment(self, studies):
        # equipmentBayFactor 0: the box quad's pack and avionics ride the
        # hub stack, so only the payload draws on the slung box
        arch = studies["logistics"].evaluate(
            {
                "airframe": "boxQuad",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "tattu16000",
                "cargo": "parcelBayS",
                "material": "aluminum",
            }
        )
        assert arch.metrics["equipmentBayVolume"] == 0.0
        assert arch.metrics["bayDemandVolume"] == pytest.approx(0.0022)


class TestStructureStory:
    """The arm-root gussets: hub structure out of the main body."""

    def test_gussets_carry_their_mass(self, studies):
        arch = studies["intercept"].evaluate(
            {
                "airframe": "boxQuad",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "tattu10000",
                "material": "aluminum",
            }
        )
        m = arch.metrics
        assert m["gussetMass"] > 0.0
        assert m["armRootMomentNm"] == pytest.approx(33.0 * m["armLength"])
        assert m["structureMass"] == pytest.approx(
            m["armStructMass"] + m["gussetMass"] + m["sparStructMass"]
        )
        # the doubler sleeve is a root detail, not a second arm
        assert m["gussetMass"] < 0.5 * m["armStructMass"]

    def test_wings_grow_no_gussets(self, studies):
        arch = studies["intercept"].evaluate(
            {
                "airframe": "flyingWingSingle",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "tattu10000",
                "material": "carbonFiber",
            }
        )
        assert arch.metrics["gussetMass"] == 0.0  # no rotor arms to root


class TestExplainableInfeasibility:
    def test_interceptor_cannot_do_logistics(self, spaces):
        darts = [a for a in spaces["logistics"] if a.selection["airframe"] == "dartInterceptor"]
        assert darts and all(not a.verified for a in darts)
        assert all("cargoFits" in a.violations for a in darts)

    def test_single_flying_wing_is_an_isr_specialist(self, spaces):
        # 1.0 kg capacity < the smallest bay + parcel (1.12 kg): the
        # loiter specialist is honestly excluded from the freight trade,
        # exactly like the teardrop
        wings = [a for a in spaces["logistics"] if a.selection["airframe"] == "flyingWingSingle"]
        assert wings and all(not a.verified for a in wings)
        assert all("cargoFits" in a.violations for a in wings)

    def test_twin_pays_for_its_second_motor(self, studies):
        # the redundancy price in watts: TWO X4112S climb-outs
        # (2 x 800 W at the wings' full-throttle catapult climb) burst
        # the li-ion ceiling the single stays inside
        for airframe, ok in (("flyingWingSingle", True), ("flyingWingTwin", False)):
            arch = studies["isr"].evaluate(
                {
                    "airframe": airframe,
                    "motors": "x4112s",
                    "props": "apc11x55",
                    "battery": "liion6s6p",
                    "sensor": "zenmuseH20",
                    "material": "carbonFiber",
                }
            )
            assert arch.verified is ok
            if not ok:
                assert "packPower" in arch.violations

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
                "motors": "at4120",
                "props": "apc11x55",
                "battery": "tattu16000",
                "material": "aluminum",
            }
        )
        assert not arch.verified
        assert "packPower" in arch.violations  # 0.7 x 4 x 2000 W > any pack

    def test_antigravity_motors_cannot_lift_the_survey_kit(self, studies):
        for material in ("aluminum", "carbonFiber"):  # even carbon's grams
            arch = studies["isr"].evaluate(
                {
                    "airframe": "vtolWing",
                    "motors": "mn4006",
                    "props": "apc11x55",
                    "battery": "tattu16000",
                    "sensor": "gremsyT3",
                    "material": material,
                }
            )
            assert not arch.verified
            # two honest refusals at once: the Antigravity motors cannot
            # lift the kit, and the assembled gimbal cannot stow in a
            # 0.12 m fuselage either
            assert arch.violations == ["isrLift", "bayFit"]

    def test_liion_cannot_feed_the_lifter_motors(self, studies):
        # the chemistry cliff: 447 Wh of 18650s, but 10 A cells -- the
        # X4110S climb-out draw (0.7 x 4 x 700 W) exceeds the pack ceiling
        arch = studies["isr"].evaluate(
            {
                "airframe": "vtolWing",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "liion6s6p",
                "sensor": "zenmuseH20",
                "material": "carbonFiber",
            }
        )
        assert not arch.verified
        assert "packPower" in arch.violations

    def test_feasible_mix_has_no_violations(self, studies):
        arch = studies["isr"].evaluate(
            {
                "airframe": "vtolWing",
                "motors": "mn4006",
                "props": "apc11x55",
                "battery": "liion6s6p",
                "sensor": "zenmuseH20",
                "material": "carbonFiber",
            }
        )
        assert arch.verified and arch.violations == []
        assert arch.metrics["stationMinutes"] == pytest.approx(200.351, abs=0.01)


class TestPhysicsSanity:
    def test_wing_beats_rotor_loiter(self, studies):
        """The whole point of the wing: loiter power is a fraction of hover."""

        winged = studies["isr"].evaluate(
            {
                "airframe": "vtolWing",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "tattu16000",
                "sensor": "zenmuseH20",
                "material": "carbonFiber",
            }
        )
        assert winged.metrics["loiterPowerW"] < 0.15 * winged.metrics["hoverPowerW"]

    def test_asymmetric_logistics_legs(self, studies):
        arch = studies["logistics"].evaluate(
            {
                "airframe": "vtolWing",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "tattu16000",
                "cargo": "parcelBayM",
                "material": "aluminum",
            }
        )
        assert arch.metrics["outboundPowerW"] > arch.metrics["returnPowerW"]

    def test_intercept_triangle(self, studies):
        arch = studies["intercept"].evaluate(
            {
                "airframe": "dartInterceptor",
                "motors": "at4120",
                "props": "apc11x55",
                "battery": "tattu5200",
                "material": "aluminum",
            }
        )
        # the triangle reads the USABLE dash speed: on the small pack
        # the dart is light, its wing loading drops, and the gust
        # placard caps a 73 m/s drag balance at ~49 m/s
        vd = arch.metrics["usableDashSpeed"]
        assert arch.metrics["dashPlacard"] < arch.metrics["dashSpeed"]
        assert vd == arch.metrics["dashPlacard"]
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
        # a 2 kW sprint quad on the small pack: the dash is fast but the
        # pack dies in ~40 s, the intercept triangle collapses, and the
        # guarded sqrt keeps the metric at a clean 0, not a crash
        arch = studies["intercept"].evaluate(
            {
                "airframe": "boxQuad",
                "motors": "at4120",
                "props": "apc11x55",
                "battery": "tattu5200",
                "material": "aluminum",
            }
        )
        assert not arch.verified
        assert "canCatch" in arch.violations
        assert arch.metrics["maxTargetSpeed"] == 0.0

    def test_wings_versus_teardrop_is_a_drag_story(self, studies, spaces):
        """The model answers "are wings necessary?" from physics, not
        from a hardcoded verdict: with identical components the teardrop
        shell out-dashes the box quad purely on its BUILT-UP CdA (the
        skinned lathe earns ~0.0125 m^2 vs the open frame's 0.055).  The
        dash ENVELOPE then decides who keeps a seat: the box quad's
        tilt-capped translation never reaches the crossing floor (no
        feasible seat at all), the teardrop's slick shell tilt-caps near
        49 m/s, and the dart placards near 67 -- wings, watts, and wing
        loading win the top end."""

        def dash(airframe):
            return (
                studies["intercept"]
                .evaluate(
                    {
                        "airframe": airframe,
                        "motors": "x4112s",
                        "props": "apc11x55",
                        "battery": "tattu10000",
                        "material": "aluminum",
                    }
                )
                .metrics["dashSpeed"]
            )

        assert dash("teardropQuad") > 1.3 * dash("boxQuad")
        feasible = [a for a in spaces["intercept"] if a.verified]
        assert not any(a.selection["airframe"] == "boxQuad" for a in feasible)
        best = {
            af: max(a.metrics["maxTargetSpeed"] for a in feasible if a.selection["airframe"] == af)
            for af in ("teardropQuad", "dartInterceptor")
        }
        gap = best["dartInterceptor"] - best["teardropQuad"]
        assert 10.0 < gap < 25.0  # the placard-vs-tilt-cap gap at the top


class TestDashEnvelope:
    """The intercept dash envelope: gust placard + tilt cap.

    The drag balance says what the watts buy; the envelope says what the
    airframe survives using.  These tests pin the FAR 23.341-style
    placard against an independent hand derivation, prove it BINDS for
    the mission winner, and pin the teaching beat: the courier wing
    would out-dash its own placard by better than two to one, and the
    placard demotes it for exactly the wing-loading reason a real
    interceptor is stubby and dense.
    """

    DART: typing.ClassVar[dict[str, str]] = {
        "airframe": "dartInterceptor",
        "motors": "at4120",
        "props": "apc11x55",
        "battery": "tattu16000",
        "material": "aluminum",
    }
    TWIN: typing.ClassVar[dict[str, str]] = {**DART, "airframe": "flyingWingTwin"}

    def test_placard_matches_the_closed_form(self, studies):
        # hand derivation of FAR 23.341 + Pratt, kept independent of the
        # model text: n(V) = 1 + Kg rho U V a / (2 W/S) solved for the
        # spar chain's design point n = 2.5 at gustU = 2.0
        arch = studies["intercept"].evaluate(self.DART)
        m = arch.metrics
        ws = m["missionMass"] * 9.81 / 0.179  # the dart's declared wingArea
        ar = 1.05 * 1.05 / 0.179
        a = 2.0 * 3.141592653589793 * ar / (ar + 2.0)
        mu = 2.0 * ws / (1.225 * 0.17 * a * 9.81)  # mean chord 0.17
        kg = 0.88 * mu / (5.3 + mu)
        placard = (2.5 - 1.0) * 2.0 * ws / (kg * 1.225 * 2.0 * a)
        assert m["dashWingLoading"] == pytest.approx(ws)
        assert m["dashPlacard"] == pytest.approx(placard)
        assert m["usableDashSpeed"] == pytest.approx(min(m["dashSpeed"], placard))

    def test_placard_binds_for_the_winner(self, spaces):
        # the placard is live for the crown, not decoration: the winning
        # dart rides its own placard (the 73 m/s drag balance is capped
        # near 67), and every dart seat keeps the crown anyway
        best = max(
            (a for a in spaces["intercept"] if a.verified),
            key=lambda a: a.metrics["maxTargetSpeed"],
        )
        assert best.selection["airframe"] == "dartInterceptor"
        assert best.metrics["dashPlacard"] < best.metrics["dashSpeed"]
        assert best.metrics["usableDashSpeed"] == best.metrics["dashPlacard"]
        assert best.metrics["maxTargetSpeed"] == pytest.approx(66.80, abs=0.05)

    def test_placard_has_teeth_for_the_wing(self, studies):
        """THE TEACHING BEAT: unplacarded, the 55 N/m^2 courier wing
        "dashes" at 63 m/s -- more than twice the speed at which a
        2 m/s gust already loads its spar to the 2.5 g design point.
        The placard caps it near 30 m/s, and the REASON is wing
        loading: the dart carries 3.6x the twin's W/S and placards
        2.2x higher on the same formula."""

        twin = studies["intercept"].evaluate(self.TWIN).metrics
        dart = studies["intercept"].evaluate(self.DART).metrics
        assert twin["dashSpeed"] > 2.0 * twin["dashPlacard"]  # would out-dash it
        assert twin["usableDashSpeed"] == twin["dashPlacard"]  # ... and may not
        assert twin["maxTargetSpeed"] == pytest.approx(27.54, abs=0.05)
        # the wing-loading reason, stated as numbers
        assert twin["dashWingLoading"] < 0.3 * dart["dashWingLoading"]
        assert twin["dashPlacard"] < 0.5 * dart["dashPlacard"]
        # demoted, NOT infeasible: the teaching story survives
        assert studies["intercept"].evaluate(self.TWIN).verified

    def test_tilt_cap_reuses_the_bench_idiom(self, studies):
        # the rotor-borne dash cap IS MaxCruiseSpeed at the shell's
        # 25-deg commanded tilt: the teardrop's 65.8 m/s paper dash
        # lands at the 48.6 the bench idiom sustains
        from math import radians, tan

        arch = studies["intercept"].evaluate(
            {
                "airframe": "teardropQuad",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "tattu16000",
                "material": "aluminum",
            }
        )
        m = arch.metrics
        cda = studies["intercept"].points["airframe"].variants["teardropQuad"]["dragArea"]
        cap = (m["missionMass"] * 9.81 * tan(radians(25.0)) / (0.5 * 1.225 * cda)) ** 0.5
        assert m["tiltDashCap"] == pytest.approx(cap)
        assert m["usableDashSpeed"] == m["tiltDashCap"] < m["dashSpeed"]
        assert arch.verified  # the teardrop keeps its rotor-borne seat

    def test_tilt_cap_retires_the_paper_catchers(self, spaces):
        # the open frames only ever caught on paper speed: tilt-capped,
        # five of the six rotor families lose every intercept seat, and
        # the slick teardrop is the one rotor-borne catcher left
        rotor = {"boxQuad", "teardropQuad", "openTri", "hexLifter", "coaxOcto", "ringOcto"}
        seated = {
            a.selection["airframe"]
            for a in spaces["intercept"]
            if a.verified and a.selection["airframe"] in rotor
        }
        assert seated == {"teardropQuad"}


class TestTipPropTrade:
    """The twin's root-against-tip pusher-station axis.

    The tip station is a real trade, not a free bonus: the derived
    vortex recovery (TipPropRecovery) buys cruise efficiency, the spar
    doubler (tipStructMass) and the engine-out yaw case price it.  The
    stability tests pin the engine-out bust; here the MISSION ledger
    shows where the tip wins.
    """

    def test_tip_bonus_is_derived_not_free(self, studies):
        frames = studies["logistics"].points["airframe"].variants
        # root stations earn no recovery; the tip and the tail-sitter
        # derive theirs from the same reference disc and span
        assert frames["flyingWingTwin"]["tipPropBonus"] == 1.0
        derived = 1.0 + 2.0 * 0.2794 / 2.6
        assert frames["flyingWingTwinTip"]["tipPropBonus"] == pytest.approx(derived)
        # the retrofit: the tail-sitter's old free 1.28 is gone
        assert frames["vtolWing"]["tipPropBonus"] == pytest.approx(derived)

    def test_tip_station_pays_structure(self, studies):
        frames = studies["logistics"].points["airframe"].variants
        tip, root = frames["flyingWingTwinTip"], frames["flyingWingTwin"]
        assert tip["tipStructMass"] > 0.15
        assert tip["mass"] == pytest.approx(root["mass"] + tip["tipStructMass"])
        # the tail-sitter pays for all FOUR tips (two spans)
        assert frames["vtolWing"]["tipStructMass"] > tip["tipStructMass"]
        # and the pod chain prices the tip station's clearance too
        assert tip["podLength"] == pytest.approx(root["podLength"])
        assert tip["podStation"] == pytest.approx(1.3)

    def test_tip_wins_the_courier_trade(self, studies, spaces):
        """Where the numbers say the tip wins: at 22 m/s courier speed
        the induced-drag recovery outbuys the doubler's mass, so the
        tip variant beats the root mix for mix on delivery work -- and
        the fleet crown moves to the tip twin.  What the mission ledger
        cannot see (and the stability ledger pins): the winning courier
        cannot hold a dead engine at the tip arm."""

        pairs = 0
        for a in spaces["logistics"]:
            if not (a.verified and a.selection["airframe"] == "flyingWingTwinTip"):
                continue
            root_mix = {**a.selection, "airframe": "flyingWingTwin"}
            root = studies["logistics"].evaluate(root_mix)
            if root.verified:
                assert a.metrics["payloadRangeKgKm"] > root.metrics["payloadRangeKgKm"]
                pairs += 1
        assert pairs >= 100  # the dominance is space-wide, not a lucky mix

    def test_intercept_does_not_reward_the_bonus(self, studies):
        # the dash chain is parasite-drag physics: the recovery buys
        # nothing there, and the placard governs both stations alike --
        # the tip variant's hair of extra metric is its doubler RAISING
        # the wing loading, not the bonus
        mix = {
            "motors": "at4120",
            "props": "apc11x55",
            "battery": "tattu16000",
            "material": "aluminum",
        }
        tip = studies["intercept"].evaluate({**mix, "airframe": "flyingWingTwinTip"}).metrics
        root = studies["intercept"].evaluate({**mix, "airframe": "flyingWingTwin"}).metrics
        assert tip["dashSpeed"] == pytest.approx(root["dashSpeed"])  # same CdA, same watts
        assert tip["dashPlacard"] > root["dashPlacard"]  # grams buy placard
