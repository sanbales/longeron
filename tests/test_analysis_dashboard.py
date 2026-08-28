"""Spike tests: the mission-compromise dashboard -- data prep, the pure
scoring/threshold contracts, and the live traitlet wiring (no browser
needed)."""

import json
from pathlib import Path

import pytest

import longeron
from longeron.analysis import AnalysisError, dashboard

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "uav_missions.sysml", cache=False)


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


class TestParetoMask:
    def test_simple_dominance(self):
        rows = [(1.0, 1.0), (2.0, 2.0), (0.5, 3.0)]
        # (1,1) is dominated by (2,2); the others are incomparable
        assert dashboard.pareto_mask(rows) == [False, True, True]

    def test_exact_ties_survive_together(self):
        rows = [(1.0, 5.0), (1.0, 5.0), (0.0, 4.0)]
        assert dashboard.pareto_mask(rows) == [True, True, False]

    def test_weak_dominance_on_one_axis(self):
        rows = [(1.0, 5.0), (1.0, 6.0)]
        assert dashboard.pareto_mask(rows) == [False, True]

    def test_ineligible_rows_never_join_or_dominate(self):
        rows = [(9.0, 9.0), (1.0, 1.0)]
        assert dashboard.pareto_mask(rows, [False, True]) == [False, True]

    def test_front_flags_is_the_min_cost_max_moe_projection(self):
        points = [(100.0, 0.2), (150.0, 0.9), (200.0, 0.5), (120.0, 0.9)]
        flags = dashboard.pareto_mask([(-x, y) for x, y in points])
        assert flags == dashboard._front_flags(points, [True] * 4)


class TestFrontFlags:
    def test_min_cost_max_moe_front(self):
        points = [(100.0, 0.2), (150.0, 0.9), (200.0, 0.5), (120.0, 0.9)]
        flags = dashboard._front_flags(points, [True, True, True, True])
        # (150, .9) is dominated by (120, .9); (200, .5) by both
        assert flags == [True, False, False, True]

    def test_ineligible_points_never_join_the_front(self):
        points = [(100.0, 1.0), (200.0, 0.5)]
        assert dashboard._front_flags(points, [False, True]) == [False, True]


class TestFrontJustifications:
    """The pure alibi contract: a full-space front member that looks
    dominated in the drawn plane names the hidden metric(s) on which it
    strictly beats EVERY point that 2-D-dominates it."""

    def test_names_the_metric_that_beats_every_plane_beater(self):
        points = [(100.0, 0.9), (110.0, 0.5)]  # the second looks dominated
        metrics = [{"a": 5.0, "b": 9.0}, {"a": 7.0, "b": 1.0}]
        whys = dashboard.front_justifications(points, metrics, [True, True])
        assert whys[0] == "front: unbeaten in this plane"
        assert whys[1] == "front: a 7 tops every pick that beats it in this plane"

    def test_off_front_rows_get_none(self):
        points = [(100.0, 0.9), (110.0, 0.5)]
        metrics = [{"a": 5.0}, {"a": 1.0}]
        assert dashboard.front_justifications(points, metrics, [True, False]) == [
            "front: unbeaten in this plane",
            None,
        ]

    def test_every_winning_metric_is_named(self):
        points = [(1.0, 1.0), (2.0, 0.5)]
        metrics = [{"a": 1.0, "b": 1.0}, {"a": 2.0, "b": 3.0}]
        whys = dashboard.front_justifications(points, metrics, [True, True])
        assert whys[1] == "front: a 2, b 3 top every pick that beats it in this plane"

    def test_only_metrics_beating_all_beaters_qualify(self):
        # the last row is beaten by BOTH others; only "b" clears both
        points = [(1.0, 1.0), (1.5, 0.9), (2.0, 0.5)]
        metrics = [{"a": 9.0, "b": 1.0}, {"a": 1.0, "b": 2.0}, {"a": 5.0, "b": 3.0}]
        whys = dashboard.front_justifications(points, metrics, [True, True, True])
        assert whys[2] == "front: b 3 tops every pick that beats it in this plane"

    def test_exact_plane_ties_never_count_as_beaters(self):
        points = [(1.0, 1.0), (1.0, 1.0)]
        metrics = [{"a": 2.0}, {"a": 1.0}]
        whys = dashboard.front_justifications(points, metrics, [True, True])
        assert whys == ["front: unbeaten in this plane"] * 2

    def test_greedy_cover_when_no_single_metric_beats_every_beater(self):
        """Real-data shape (teardrop quads at 'Pareto only'): each beater
        trails somewhere, but no one metric covers ALL beaters.  The line
        then names a minimal covering set, joined by 'or'."""

        points = [(1.0, 1.0), (1.5, 0.9), (2.0, 0.5)]
        metrics = [{"a": 9.0, "b": 1.0}, {"a": 1.0, "b": 9.0}, {"a": 5.0, "b": 5.0}]
        whys = dashboard.front_justifications(points, metrics, [True, True, True])
        expect = "front: every pick that beats it in this plane trails it on a 5 or b 5"
        assert whys[2] == expect


class TestDashboardData:
    def test_shared_points_and_size(self, data):
        assert data["shared"] == ["airframe", "motors", "props", "battery", "material"]
        assert len(data["candidates"]) == 4 * 3 * 3 * 4 * 2
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

        from longeron.analysis import trades

        live = dashboard.apply_thresholds(
            data["candidates"],
            {m: {s["key"]: s["default"] for s in ss} for m, ss in data["thresholds"].items()},
        )
        study = trades.TradeStudy(model, "UavMissions::IsrUav")
        for cand, row in zip(data["candidates"][:20], live[:20], strict=False):
            best_feasible = any(
                study.evaluate({**cand["selection"], "sensor": sensor}).verified
                for sensor in ("runcamSplit", "zenmuseH20", "gremsyT3")
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
    dash.pareto_toggle.value = False
    for slider in dash.sliders.values():
        slider.value = 50
    for sliders in dash.requirements.values():
        for key, slider in sliders.items():
            spec = next(s for ss in dash.data["thresholds"].values() for s in ss if s["key"] == key)
            slider.value = spec["default"]
    dash.top_n.value = 4
    dash.parcoords.selected = "[]"
    dash.lineup.hover = -1


class TestDashboardLayout:
    """The one-screen composition: header strip, plots side by side,
    the mission Tab next to the 3D viewer."""

    def test_three_rows(self, dash):
        header, plot_row, control_row = dash.children
        assert list(header.children)[-2:] == [dash.pareto_toggle, dash.top_n]
        assert list(plot_row.children) == [dash.parcoords, dash.scatter]
        assert list(control_row.children) == [dash.tabs, dash.lineup, dash.viewer]

    def test_missions_are_one_tab(self, dash, data):
        names = [m["name"] for m in data["missions"]]
        assert len(dash.tabs.children) == 1 + len(names)
        assert dash.tabs.get_title(0) == "all missions"
        assert [dash.tabs.get_title(i + 1) for i in range(len(names))] == names

    def test_summary_tab_holds_priorities_and_the_scorecard(self, dash):
        children = list(dash.tabs.children[0].children)
        assert children[0] is dash.ranking
        for slider in dash.sliders.values():
            assert slider in children
        assert children[-1] is dash.summary
        assert "best compromise" in dash.summary.value

    def test_each_mission_tab_holds_its_floors_and_card(self, dash, data):
        for position, mission in enumerate(m["name"] for m in data["missions"]):
            children = list(dash.tabs.children[position + 1].children)
            for slider in dash.requirements[mission].values():
                assert slider in children
            assert children[-1] is dash.cards[mission]

    def test_plots_share_one_row_height(self, dash):
        assert dash.parcoords.height_px == dash.scatter.height_px == 330
        assert dash.viewer.height_px == 430


class TestParetoToggle:
    """The dominated-candidate filter: dominance over -cost and the
    thresholded mission metrics, ties surviving, weights ignored."""

    def test_front_matches_brute_force(self, dash, data):
        names = [m["name"] for m in data["missions"]]
        rows = [
            (
                -float(cand["cost"]),
                *(float(row["metric"][n]) for n in names),
            )
            for cand, row in zip(data["candidates"], dash.live, strict=True)
        ]
        eligible = [any(row["feasible"].values()) for row in dash.live]

        def dominated(i):
            return any(
                eligible[j]
                and all(b >= a for a, b in zip(rows[i], rows[j], strict=True))
                and rows[j] != rows[i]
                for j in range(len(rows))
            )

        brute = [eligible[i] and not dominated(i) for i in range(len(rows))]
        assert dash.front == brute
        assert 0 < sum(brute) < len(rows)

    def test_toggle_filters_every_linked_view(self, dash, data):
        full = json.loads(dash.parcoords.table_json)
        assert len(full["lines"]) == len(data["candidates"])
        dash.pareto_toggle.value = True
        front = [i for i, on in enumerate(dash.front) if on]
        assert dash.pool == front
        pruned = json.loads(dash.parcoords.table_json)
        assert len(pruned["lines"]) == len(front)
        scatter = json.loads(dash.scatter.payload_json)
        assert len(scatter["points"]) == len(front)
        assert all(p["feasible"] for p in scatter["points"])
        assert set(dash.picks) <= set(front)
        assert "non-dominated" in dash.ranking.value
        dash.pareto_toggle.value = False
        assert len(json.loads(dash.parcoords.table_json)["lines"]) == len(data["candidates"])

    def test_weights_never_change_the_front(self, dash):
        before = list(dash.front)
        dash.sliders["intercept"].value = 100
        dash.sliders["ISR"].value = 0
        assert dash.front == before  # MOE re-weights, dominance holds still

    def test_thresholds_do_change_the_front(self, dash):
        before = list(dash.front)
        dash.requirements["ISR"]["stationMinutes"].value = 120.0
        assert dash.front != before  # metrics re-filtered, front re-derived


class TestFrontJustificationsLive:
    """THE reported legibility defect: 'Pareto only' at N=8 keeps picks
    that LOOK dominated in the cost-MOE scatter (148-151 sit below-right
    of 172/173).  The filter is correct -- dominance spans all four
    objectives -- so the display must say where each pick wins."""

    @staticmethod
    def _pareto_n8(dash):
        dash.pareto_toggle.value = True
        dash.top_n.value = 8

    def test_every_front_member_has_a_justification(self, dash):
        self._pareto_n8(dash)
        assert all(dash.front[i] for i in dash.picks)  # the filter was never wrong
        for point in json.loads(dash.scatter.payload_json)["points"]:
            assert point["why"], point  # 4-D front members, all justified

    def test_the_looks_dominated_picks_name_station_minutes(self, dash):
        self._pareto_n8(dash)
        cards = {dash.pool[c["line"]]: c for c in json.loads(dash.lineup.cards_json)}
        for index in (148, 149, 150, 151):
            assert index in dash.picks
            why = cards[index]["why"]
            assert why.startswith("front: stationMinutes ")
            assert why.endswith("tops every pick that beats it in this plane")

    def test_named_metrics_really_beat_all_plane_beaters(self, dash, data):
        """Honesty, brute-forced, over every front member in the pool:
        a 'tops' line names metrics that each strictly beat the SAME
        metric of every 2-D dominator; a 'trails it on' line names a set
        such that every 2-D dominator strictly trails on at least one."""

        self._pareto_n8(dash)
        metric_of = {m["name"]: m["metric"] for m in data["missions"]}
        pool = dash.pool
        points = [(float(data["candidates"][i]["cost"]), dash.scores[i]) for i in pool]
        payload = json.loads(dash.scatter.payload_json)
        beaten = 0
        for j, index in enumerate(pool):
            why = payload["points"][j]["why"]
            beaters = [
                k
                for k, (bx, by) in enumerate(points)
                if bx <= points[j][0] and by >= points[j][1] and (bx, by) != points[j]
            ]
            if not beaters:
                assert why == "front: unbeaten in this plane"
                continue
            beaten += 1
            named = [name for name, metric in metric_of.items() if metric in why]
            assert named, why  # non-domination guarantees hidden winners
            mine = {name: dash.live[index]["metric"][name] for name in named}
            if "trails it on" in why:
                for k in beaters:  # every beater trails on some named metric
                    assert any(mine[n] > dash.live[pool[k]]["metric"][n] for n in named)
            else:
                for name in named:  # every named metric beats every beater
                    assert all(mine[name] > dash.live[pool[k]]["metric"][name] for k in beaters)
        assert beaten >= 4  # picks 148-151 at least


class TestLineupCards:
    """The pick cards and their hover trace into the parallel coordinates."""

    def test_cards_align_with_picks(self, dash, data):
        cards = json.loads(dash.lineup.cards_json)
        assert len(cards) == len(dash.picks) == 4
        assert cards[0]["mark"] == "\u2605 "
        for card, index in zip(cards, dash.picks, strict=True):
            assert card["label"] == data["candidates"][index]["label"]
            assert dash.pool[card["line"]] == index
            assert card["moe"] == f"{dash.scores[index]:+.2f}"
            assert card["cost"] == f"{data['candidates'][index]['cost']:.0f}"

    def test_dominated_picks_say_so(self, dash, data):
        dominated = [i for i, on in enumerate(dash.front) if not on]
        dash.parcoords.selected = json.dumps(dominated)  # pool = identity here
        cards = json.loads(dash.lineup.cards_json)
        assert cards
        assert not any(card["front"] for card in cards)
        assert all(card["why"].startswith("dominated") for card in cards)

    def test_card_hover_traces_the_parcoords_line(self, dash):
        assert dash.parcoords.highlight == -1
        dash.lineup.hover = 7
        assert dash.parcoords.highlight == 7
        dash.lineup.hover = -1
        assert dash.parcoords.highlight == -1

    def test_recompute_resets_a_stale_trace(self, dash):
        dash.lineup.hover = 2
        dash.top_n.value = 5  # cards re-baked: the old line index is stale
        assert dash.lineup.hover == -1
        assert dash.parcoords.highlight == -1

    def test_frontend_seams(self, dash):
        # the composed parcoords ESM keeps ONE export and gains the hook
        assert dash.parcoords._esm.count("export default") == 1
        assert "change:highlight" in dash.parcoords._esm
        assert "change:table_json" in dash.parcoords._esm  # live re-bakes
        assert "change:cards_json" in dash.lineup._esm
        assert "why" in dash.scatter._esm  # the tooltip carries the alibi


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
                if c["label"].startswith("dartInterceptor/at4120/apc11x55")
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
