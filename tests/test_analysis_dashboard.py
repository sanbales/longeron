"""Spike tests: the mission-compromise dashboard -- data prep, the pure
scoring contract, and the live traitlet wiring (no browser needed)."""

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


class TestDashboardData:
    def test_shared_points_and_size(self, data):
        assert data["shared"] == ["airframe", "motors", "props", "battery"]
        assert len(data["candidates"]) == 4 * 3 * 3 * 3
        assert [m["name"] for m in data["missions"]] == ["ISR", "logistics", "intercept"]

    def test_best_equipment_per_mission(self, data):
        """Per candidate the metric is the best FEASIBLE equipment fit;
        infeasible missions display 0 but keep a mix for the red card."""

        best = next(
            c for c in data["candidates"] if c["label"] == "vtolWing/stdMotor/slimProp/packMax"
        )
        assert best["feasible"] == {"ISR": True, "logistics": True, "intercept": True}
        assert best["metric"]["ISR"] == pytest.approx(115.137, abs=0.01)
        assert best["mission_mix"]["ISR"]["sensor"] in ("stareEoIr", "hawkeyeGimbal")
        dart = next(
            c for c in data["candidates"] if c["label"].startswith("dartInterceptor/sprintMotor")
        )
        assert dart["feasible"]["logistics"] is False
        assert dart["metric"]["logistics"] == 0.0
        assert "cargo" in dart["mission_mix"]["logistics"]

    def test_cost_is_the_shared_base_buildup(self, data):
        cand = data["candidates"][0]
        arch = data["studies"]["intercept"].evaluate(cand["selection"])
        assert cand["cost"] == pytest.approx(arch.metrics["baseCost"])


@pytest.fixture(scope="module")
def dash(data):
    pytest.importorskip("anywidget")
    pytest.importorskip("ipywidgets")
    return dashboard.mission_dashboard(data)


class TestDashboardWiring:
    def test_composition(self, dash, data):
        assert set(dash.sliders) == {"ISR", "logistics", "intercept"}
        payload = json.loads(dash.parcoords.table_json)
        assert len(payload["lines"]) == len(data["candidates"])
        names = [a["name"] for a in payload["axes"]]
        assert names[:4] == data["shared"]
        assert {"cost", "stationMinutes", "payloadRangeKgKm", "maxTargetSpeed"} <= set(names)
        assert len(dash.picks) == 4
        assert dash.viewer.label.startswith("\u2605")

    def test_best_compromise_leads_the_lineup(self, dash, data):
        scene = json.loads(dash.viewer.mesh_json)
        prefixes = {p["name"].split(":")[0] for p in scene["parts"]}
        assert prefixes == {"1", "2", "3", "4"}  # four labeled configs
        best = data["candidates"][dash.picks[0]]
        assert all(best["feasible"].values())  # with weights up, it flies

    def test_sliders_reweight_live(self, dash, data):
        dash.sliders["ISR"].value = 0
        dash.sliders["logistics"].value = 0
        dash.sliders["intercept"].value = 100
        top = data["candidates"][dash.picks[0]]
        assert top["selection"]["airframe"] == "dartInterceptor"
        dash.sliders["ISR"].value = 100
        dash.sliders["intercept"].value = 0
        top = data["candidates"][dash.picks[0]]
        assert top["selection"]["airframe"] == "vtolWing"

    def test_brush_downselects_live(self, dash, data):
        boxes = [
            i for i, c in enumerate(data["candidates"]) if c["selection"]["airframe"] == "boxQuad"
        ]
        dash.parcoords.selected = json.dumps(boxes)
        assert set(dash.picks) <= set(boxes)
        assert len(dash.picks) == 4
        dash.parcoords.selected = json.dumps(boxes[:2])
        assert len(dash.picks) == 2  # up to 4, never padded
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
        dash.parcoords.selected = "[]"
