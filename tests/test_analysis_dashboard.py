"""Spike tests: the mission-compromise dashboard -- data prep, the pure
scoring/threshold contracts, and the live traitlet wiring (no browser
needed)."""

import json
from pathlib import Path

import pytest

import sysml2
from sysml2.analysis import AnalysisError, dashboard

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def model():
    return sysml2.load(EXAMPLES / "uav_missions.sysml", cache=False)


@pytest.fixture(scope="module")
def data(model):
    return dashboard.mission_dashboard_data(model)


CANDS = [
    {"metric": {"a": 10.0, "b": 0.0}, "feasible": {"a": True, "b": False}},
    {"metric": {"a": 20.0, "b": 5.0}, "feasible": {"a": True, "b": True}},
    {"metric": {"a": 30.0, "b": 1.0}, "feasible": {"a": True, "b": True}},
]


class TestCompromiseScores:
    def test_normalization_and_weighting(self):
        # equal weights: c2 tops mission a (norm 1) but trails on b
        scores = dashboard.compromise_scores(CANDS, {"a": 50, "b": 50})
        assert scores[1] == pytest.approx(0.5 * 0.5 + 0.5 * 1.0)
        # mission b normalizes over its FEASIBLE set (1.0..5.0): c2's
        # b = 1.0 is the feasible floor, norm 0
        assert scores[2] == pytest.approx(0.5 * 1.0 + 0.5 * 0.0)
        # all weight on a: the ranking follows a alone
        only_a = dashboard.compromise_scores(CANDS, {"a": 100, "b": 0})
        assert only_a[2] > only_a[1] > only_a[0]

    def test_infeasibility_costs_the_weight(self):
        """The documented penalty: an infeasible mission subtracts
        weight * INFEASIBLE_PENALTY instead of scoring a silent zero."""

        scores = dashboard.compromise_scores(CANDS, {"a": 0, "b": 100})
        assert scores[0] == pytest.approx(-dashboard.INFEASIBLE_PENALTY)
        assert scores[1] == pytest.approx(1.0)
        # the infeasible candidate's b = 0.0 never stretches the scale:
        # bounds come from the feasible set (1..5), so c2 floors at 0.0
        # rather than the 0.2 an all-candidate normalization would give
        assert scores[2] == pytest.approx(0.0)

    def test_all_zero_weights_fall_back_to_equal(self):
        zero = dashboard.compromise_scores(CANDS, {"a": 0, "b": 0})
        equal = dashboard.compromise_scores(CANDS, {"a": 70, "b": 70})
        assert zero == pytest.approx(equal)

    def test_degenerate_feasible_set_pins_to_one(self):
        cands = [
            {"metric": {"a": 7.0}, "feasible": {"a": True}},
            {"metric": {"a": 7.0}, "feasible": {"a": True}},
        ]
        assert dashboard.compromise_scores(cands, {"a": 10}) == [1.0, 1.0]

    def test_needs_missions(self):
        with pytest.raises(AnalysisError):
            dashboard.compromise_scores(CANDS, {})


OPTIONED = [
    {
        "options": {
            "m": [
                {"mix": {"kit": "small"}, "metric": 10.0, "values": {"load": 1.0}, "ok": True},
                {"mix": {"kit": "big"}, "metric": 30.0, "values": {"load": 4.0}, "ok": False},
                {"mix": {"kit": "mid"}, "metric": 20.0, "values": {"load": 2.5}, "ok": True},
            ]
        }
    },
]


class TestApplyThresholds:
    def test_best_eligible_option_represents_the_candidate(self):
        live = dashboard.apply_thresholds(OPTIONED, {"m": {"load": 0.0}})[0]
        # 'big' scores highest but breaks a non-threshold constraint
        assert live["mission_mix"]["m"] == {"kit": "mid"}
        assert live["metric"]["m"] == 20.0
        assert live["feasible"]["m"] is True

    def test_raising_a_floor_switches_the_pick_then_kills_it(self):
        live = dashboard.apply_thresholds(OPTIONED, {"m": {"load": 2.0}})[0]
        assert live["mission_mix"]["m"] == {"kit": "mid"}  # small filtered out
        dead = dashboard.apply_thresholds(OPTIONED, {"m": {"load": 3.0}})[0]
        assert dead["feasible"]["m"] is False
        assert dead["metric"]["m"] == 0.0
        # the red card still knows the best (broken) option and values
        assert dead["mission_mix"]["m"] == {"kit": "big"}
        assert dead["values"]["m"] == {"load": 4.0}

    def test_missing_mission_thresholds_mean_no_floors(self):
        live = dashboard.apply_thresholds(OPTIONED, {})[0]
        assert live["feasible"]["m"] is True
        assert live["metric"]["m"] == 20.0


class TestFrontFlags:
    def test_min_cost_max_moe_front(self):
        points = [(100.0, 0.2), (150.0, 0.9), (200.0, 0.5), (120.0, 0.9)]
        flags = dashboard._front_flags(points, [True, True, True, True])
        # (150, .9) is dominated by (120, .9); (200, .5) by both
        assert flags == [True, False, False, True]

    def test_ineligible_points_never_join_the_front(self):
        points = [(100.0, 1.0), (200.0, 0.5)]
        assert dashboard._front_flags(points, [False, True]) == [False, True]


class TestDashboardData:
    def test_shared_points_and_size(self, data):
        assert data["shared"] == ["airframe", "motors", "props", "battery", "material"]
        assert len(data["candidates"]) == 4 * 3 * 3 * 3 * 2
        assert [m["name"] for m in data["missions"]] == ["ISR", "logistics", "intercept"]

    def test_thresholds_anchored_in_the_model(self, data):
        """Slider defaults are the model's own requirement attributes
        (minStationMinutes, minPayloadKg, minDeliveryRadiusKm,
        targetSpeed); ranges widen to the achieved values."""

        specs = {m: {s["key"]: s for s in ss} for m, ss in data["thresholds"].items()}
        assert specs["ISR"]["stationMinutes"]["default"] == 25.0
        assert specs["logistics"]["payloadKg"]["default"] == 1.0
        assert specs["logistics"]["deliveryRadiusKm"]["default"] == 8.0
        assert specs["intercept"]["maxTargetSpeed"]["default"] == 25.0
        for spec in (s for ss in data["thresholds"].values() for s in ss):
            assert spec["max"] > spec["default"]

    def test_every_equipment_option_is_baked(self, data):
        cand = data["candidates"][0]
        assert len(cand["options"]["ISR"]) == 3  # sensors
        assert len(cand["options"]["logistics"]) == 3  # bays
        assert len(cand["options"]["intercept"]) == 1
        option = cand["options"]["ISR"][0]
        assert {"mix", "metric", "values", "ok"} <= set(option)
        assert "stationMinutes" in option["values"]

    def test_default_thresholds_reproduce_the_model_verdicts(self, data, model):
        """apply_thresholds at the model's own defaults must agree with
        the interpreter's constraint verdicts, mission by mission."""

        from sysml2.analysis import trades

        live = dashboard.apply_thresholds(
            data["candidates"],
            {m: {s["key"]: s["default"] for s in ss} for m, ss in data["thresholds"].items()},
        )
        study = trades.TradeStudy(model, "UavMissions::IsrUav")
        for cand, row in zip(data["candidates"][:20], live[:20], strict=False):
            best_feasible = any(
                study.evaluate({**cand["selection"], "sensor": sensor}).verified
                for sensor in ("pathfinderEO", "stareEoIr", "hawkeyeGimbal")
            )
            assert row["feasible"]["ISR"] == best_feasible

    def test_cost_is_the_shared_base_buildup(self, data):
        cand = data["candidates"][0]
        arch = data["studies"]["intercept"].evaluate(cand["selection"])
        assert cand["cost"] == pytest.approx(arch.metrics["baseCost"])


@pytest.fixture(scope="module")
def dash(data):
    pytest.importorskip("anywidget")
    pytest.importorskip("ipywidgets")
    return dashboard.mission_dashboard(data)


@pytest.fixture(autouse=True)
def _reset(dash, request):
    """Every wiring test starts from the default dashboard state."""

    if "dash" not in request.fixturenames:
        yield
        return
    yield
    for slider in dash.sliders.values():
        slider.value = 50
    for sliders in dash.requirements.values():
        for key, slider in sliders.items():
            spec = next(s for ss in dash.data["thresholds"].values() for s in ss if s["key"] == key)
            slider.value = spec["default"]
    dash.top_n.value = 4
    dash.parcoords.selected = "[]"


class TestDashboardWiring:
    def test_composition(self, dash, data):
        assert set(dash.sliders) == {"ISR", "logistics", "intercept"}
        assert set(dash.requirements["logistics"]) == {"payloadKg", "deliveryRadiusKm"}
        payload = json.loads(dash.parcoords.table_json)
        assert len(payload["lines"]) == len(data["candidates"])
        names = [a["name"] for a in payload["axes"]]
        assert names[:5] == data["shared"]
        assert names[-1] == "MOE"  # the score IS an axis
        assert {"cost", "stationMinutes", "payloadRangeKgKm", "maxTargetSpeed"} <= set(names)
        assert len(dash.picks) == 4
        assert dash.viewer.label.startswith("\u2605")
        assert json.loads(dash.scatter.payload_json)["points"]

    def test_priority_sliders_update_every_downstream_traitlet(self, dash, data):
        """THE reported bug, as a wiring contract: mutating a priority
        slider programmatically must update the downstream traitlets a
        front-end repaints from -- the parcoords table (MOE axis), the
        MOE-vs-cost scatter payload, the viewer scene + caption, and the
        cards -- not just an internal score list."""

        before = {
            "table": dash.parcoords.table_json,
            "scatter": dash.scatter.payload_json,
            "mesh": dash.viewer.mesh_json,
            "label": dash.viewer.label,
            "card": dash.cards["intercept"].value,
        }
        dash.sliders["ISR"].value = 0
        dash.sliders["logistics"].value = 0
        dash.sliders["intercept"].value = 100
        assert dash.parcoords.table_json != before["table"]  # MOE re-baked
        assert dash.scatter.payload_json != before["scatter"]
        assert dash.viewer.mesh_json != before["mesh"]
        assert dash.viewer.label != before["label"]
        assert dash.cards["intercept"].value != before["card"]
        top = data["candidates"][dash.picks[0]]
        assert top["selection"]["airframe"] == "dartInterceptor"
        dash.sliders["ISR"].value = 100
        dash.sliders["intercept"].value = 0
        top = data["candidates"][dash.picks[0]]
        assert top["selection"]["airframe"] == "vtolWing"

    def test_requirement_sliders_refilter_live(self, dash):
        """Moving a requirement threshold re-evaluates feasibility over
        the baked options and re-filters the pool -- and relaxing it
        re-admits candidates."""

        base = sum(1 for row in dash.live if row["feasible"]["ISR"])
        dash.requirements["ISR"]["stationMinutes"].value = 120.0
        tightened = sum(1 for row in dash.live if row["feasible"]["ISR"])
        assert 0 < tightened < base
        assert "stationMinutes >= 120" in dash.cards["ISR"].value
        dash.requirements["ISR"]["stationMinutes"].value = 5.0
        relaxed = sum(1 for row in dash.live if row["feasible"]["ISR"])
        assert relaxed >= base
        # the parcoords feasible flags follow the thresholds
        payload = json.loads(dash.parcoords.table_json)
        dash.requirements["ISR"]["stationMinutes"].value = 1e9
        dash.requirements["logistics"]["payloadKg"].value = 1e9
        dash.requirements["intercept"]["maxTargetSpeed"].value = 1e9
        dead = json.loads(dash.parcoords.table_json)
        assert sum(ln["feasible"] for ln in dead["lines"]) < sum(
            ln["feasible"] for ln in payload["lines"]
        )

    def test_payload_floor_forces_bigger_bays(self, dash):
        dash.requirements["logistics"]["payloadKg"].value = 3.0
        picks_mixes = {
            row["mission_mix"]["logistics"]["cargo"]
            for row in dash.live
            if row["feasible"]["logistics"]
        }
        assert picks_mixes == {"parcelBayL"}  # only the 4 kg bay clears 3 kg

    def test_moe_front_highlights_the_pareto_set(self, dash):
        payload = json.loads(dash.scatter.payload_json)
        points = [(p["x"], p["y"]) for p in payload["points"]]
        eligible = [p["feasible"] for p in payload["points"]]
        assert [p["front"] for p in payload["points"]] == dashboard._front_flags(points, eligible)
        assert any(p["front"] for p in payload["points"])
        assert any(p["pick"] for p in payload["points"])

    def test_top_n_slider_sizes_the_lineup_grid(self, dash):
        dash.top_n.value = 6
        scene = json.loads(dash.viewer.mesh_json)
        assert len({p["name"].split(":")[0] for p in scene["parts"]}) == 6
        assert len(scene["labels"]) == 6  # per-cell in-scene captions
        zs = {entry["anchor"][2] for entry in scene["labels"]}
        assert len(zs) == 2  # 6 -> 2 rows x 3 cols
        dash.top_n.value = 2
        scene = json.loads(dash.viewer.mesh_json)
        assert len(scene["labels"]) == 2

    def test_brush_downselects_live(self, dash, data):
        boxes = [
            i for i, c in enumerate(data["candidates"]) if c["selection"]["airframe"] == "boxQuad"
        ]
        dash.parcoords.selected = json.dumps(boxes)
        assert set(dash.picks) <= set(boxes)
        assert len(dash.picks) == 4
        dash.parcoords.selected = json.dumps(boxes[:2])
        assert len(dash.picks) == 2  # up to N, never padded
        dash.parcoords.selected = "[]"  # cleared brush = full pool
        assert len(dash.picks) == 4

    def test_cards_show_margins_green_red(self, dash, data):
        dash.parcoords.selected = json.dumps(
            [
                i
                for i, c in enumerate(data["candidates"])
                if c["label"].startswith("dartInterceptor/sprintMotor/slim")
            ]
        )
        log_card = dash.cards["logistics"].value
        assert "infeasible" in log_card
        assert "cargoFits" in log_card
        assert dashboard._BAD in log_card
        int_card = dash.cards["intercept"].value
        assert "feasible" in int_card
        assert dashboard._OK in int_card

    def test_scatter_rerenders_on_payload_change(self, dash):
        assert "change:payload_json" in dash.scatter._esm
        assert "change:table_json" in dash.parcoords._esm  # live re-bakes
