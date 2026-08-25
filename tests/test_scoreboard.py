"""The MAUT requirements scoreboard: utilities, aggregation, the widget.

Widget assertions are headless -- payload traits and front-end (ESM)
contracts, like tests/test_explorer.py and test_analysis_viewer3d.py.
"""

import json
import math

import pytest

import longeron
from longeron.analysis import AnalysisError
from longeron.analysis.scoreboard import (
    AGGREGATORS,
    UTILITY_FUNCTIONS,
    Row,
    Scoreboard,
    architecture_values,
    scoreboard,
)

# ---------------------------------------------------------------------------
# fixture models
# ---------------------------------------------------------------------------

#: a 3-level hierarchy with every utility shape, model-declared weights,
#: an inherited declaration, and an unmeasured leaf
UAV_MODEL = """
package ScoutUAV {
    attribute totalMass : Real = 1.62;
    attribute flightTime : Real = 32.0;
    attribute radius_km : Real = 8.5;
    attribute unitCost : Real = 950.0;
    attribute noise_dB : Real = 68.0;

    requirement mission {
        requirement performance {
            attribute weight : Real = 3.0;
            requirement endurance {
                attribute weight : Real = 3.0;
                attribute utility : String = "larger-is-better";
                attribute ramp0 : Real = 15.0;
                attribute ramp1 : Real = 45.0;
                attribute measure : Real = flightTime;
            }
            requirement radius {
                attribute weight : Real = 2.0;
                attribute utility : String = "larger-is-better";
                attribute ramp0 : Real = 3.0;
                attribute ramp1 : Real = 12.0;
                attribute measure : Real = radius_km;
            }
        }
        requirement affordability {
            attribute weight : Real = 2.0;
            requirement cost {
                attribute utility : String = "smaller-is-better";
                attribute ramp0 : Real = 1500.0;
                attribute ramp1 : Real = 500.0;
                attribute measure : Real = unitCost;
            }
        }
        requirement operability {
            attribute weight : Real = 2.0;
            requirement mass {
                attribute utility : String = "smaller-is-better";
                attribute ramp0 : Real = 2.5;
                attribute ramp1 : Real = 1.0;
                attribute measure : Real = totalMass;
            }
            requirement regulatory {
                require constraint { totalMass <= 25.0 }
            }
            requirement quiet {
                attribute utility : String = "target-is-best";
                attribute target : Real = 60.0;
                attribute limit : Real = 15.0;
                attribute measure : Real = noise_dB;
            }
            requirement futureProofing;
        }
    }
}
"""

#: weight/utility declarations inherited from a typing requirement def,
#: with the usage overriding one of them
INHERIT_MODEL = """
package Reqs {
    attribute speed : Real = 40.0;
    requirement def FastEnough {
        attribute weight : Real = 4.0;
        attribute utility : String = "larger-is-better";
        attribute ramp0 : Real = 10.0;
        attribute ramp1 : Real = 50.0;
        attribute measure : Real = speed;
    }
    requirement fast : FastEnough;
    requirement fastButCheap : FastEnough {
        attribute weight : Real = 1.0;
    }
}
"""


@pytest.fixture(scope="module")
def uav_model():
    return longeron.loads(UAV_MODEL)


@pytest.fixture(scope="module")
def uav(uav_model):
    return scoreboard(uav_model)


def rows_by_name(board: Scoreboard) -> dict[str, Row]:
    return {row.name: row for row in board.table()}


# ---------------------------------------------------------------------------
# utility function shapes
# ---------------------------------------------------------------------------


class TestUtilityFunctions:
    def test_registry_names(self):
        assert sorted(UTILITY_FUNCTIONS) == [
            "larger-is-better",
            "ramp",
            "smaller-is-better",
            "step",
            "target-is-best",
        ]

    def test_larger_is_better_shape(self):
        fn = UTILITY_FUNCTIONS["larger-is-better"]
        params = {"ramp0": 10.0, "ramp1": 50.0}
        assert fn(10.0, params) == 0.0
        assert fn(30.0, params) == pytest.approx(0.5)
        assert fn(50.0, params) == 1.0
        assert fn(-1e9, params) == 0.0  # clamped below
        assert fn(1e9, params) == 1.0  # clamped above

    def test_larger_is_better_orientation_is_validated(self):
        with pytest.raises(AnalysisError, match="ramp0 < ramp1"):
            UTILITY_FUNCTIONS["larger-is-better"](1.0, {"ramp0": 50.0, "ramp1": 10.0})

    def test_smaller_is_better_shape(self):
        fn = UTILITY_FUNCTIONS["smaller-is-better"]
        params = {"ramp0": 2.5, "ramp1": 1.0}
        assert fn(2.5, params) == 0.0
        assert fn(1.75, params) == pytest.approx(0.5)
        assert fn(1.0, params) == 1.0
        assert fn(100.0, params) == 0.0  # clamped (worse than worst)
        assert fn(0.0, params) == 1.0  # clamped (better than best)

    def test_smaller_is_better_orientation_is_validated(self):
        with pytest.raises(AnalysisError, match="ramp1 < ramp0"):
            UTILITY_FUNCTIONS["smaller-is-better"](1.0, {"ramp0": 1.0, "ramp1": 2.0})

    def test_ramp_accepts_either_orientation(self):
        fn = UTILITY_FUNCTIONS["ramp"]
        assert fn(15.0, {"ramp0": 10.0, "ramp1": 20.0}) == pytest.approx(0.5)
        assert fn(15.0, {"ramp0": 20.0, "ramp1": 10.0}) == pytest.approx(0.5)
        assert fn(9.0, {"ramp0": 10.0, "ramp1": 20.0}) == 0.0

    def test_ramp_needs_distinct_anchors(self):
        with pytest.raises(AnalysisError, match="must differ"):
            UTILITY_FUNCTIONS["ramp"](1.0, {"ramp0": 5.0, "ramp1": 5.0})

    def test_ramp_needs_both_anchors(self):
        with pytest.raises(AnalysisError, match=r"ramp0.*ramp1"):
            UTILITY_FUNCTIONS["ramp"](1.0, {"ramp0": 5.0})

    def test_target_is_best_shape(self):
        fn = UTILITY_FUNCTIONS["target-is-best"]
        params = {"target": 60.0, "limit": 15.0}
        assert fn(60.0, params) == 1.0
        assert fn(75.0, params) == 0.0  # exactly at the limit
        assert fn(45.0, params) == 0.0  # symmetric
        assert fn(67.5, params) == pytest.approx(0.5)
        assert fn(1e6, params) == 0.0  # clamped far out

    def test_target_is_best_needs_positive_limit(self):
        with pytest.raises(AnalysisError, match="positive 'limit'"):
            UTILITY_FUNCTIONS["target-is-best"](1.0, {"target": 1.0, "limit": 0.0})

    def test_step_is_pass_fail(self):
        fn = UTILITY_FUNCTIONS["step"]
        assert fn(True, {}) == 1.0
        assert fn(False, {}) == 0.0
        assert fn(1.5, {}) == 1.0
        assert fn(0.0, {}) == 0.0
        assert math.isnan(fn(float("nan"), {}))


# ---------------------------------------------------------------------------
# aggregation strategies
# ---------------------------------------------------------------------------


class TestAggregators:
    def test_registry_names(self):
        assert sorted(AGGREGATORS) == ["geometric", "min", "saw"]

    def test_saw_is_weight_normalized(self):
        assert AGGREGATORS["saw"]([(3.0, 1.0), (1.0, 0.0)]) == pytest.approx(0.75)

    def test_min_ignores_weights(self):
        assert AGGREGATORS["min"]([(100.0, 0.9), (0.1, 0.2)]) == pytest.approx(0.2)

    def test_geometric_is_the_weighted_geometric_mean(self):
        # equal weights: sqrt(0.25 * 1.0) = 0.5
        assert AGGREGATORS["geometric"]([(1.0, 0.25), (1.0, 1.0)]) == pytest.approx(0.5)

    def test_geometric_zero_child_zeroes_the_parent(self):
        assert AGGREGATORS["geometric"]([(1.0, 0.0), (1.0, 1.0)]) == 0.0

    def test_saw_on_the_uav_hierarchy(self, uav):
        rows = rows_by_name(uav)
        # leaves, hand-computed from the fixture's raw values
        assert rows["endurance"].utility == pytest.approx((32 - 15) / 30)
        assert rows["cost"].utility == pytest.approx((950 - 1500) / (500 - 1500))
        assert rows["regulatory"].utility == 1.0
        # performance = (3*u_end + 2*u_rad) / 5
        perf = (3 * rows["endurance"].utility + 2 * rows["radius"].utility) / 5
        assert rows["performance"].aggregate == pytest.approx(perf)
        # mission = (3*perf + 2*afford + 2*oper) / 7 == the root score
        oper = (rows["mass"].utility + 1.0 + rows["quiet"].utility) / 3
        expected = (3 * perf + 2 * rows["cost"].utility + 2 * oper) / 7
        assert rows["mission"].aggregate == pytest.approx(expected)
        assert uav.score == pytest.approx(expected)

    def test_min_on_the_uav_hierarchy(self, uav_model, uav):
        board = scoreboard(uav_model, aggregation="min")
        leaves = [r.utility for r in uav.table() if r.kind == "leaf" and not math.isnan(r.utility)]
        assert board.score == pytest.approx(min(leaves))

    def test_geometric_on_the_uav_hierarchy(self, uav_model):
        board = scoreboard(uav_model, aggregation="geometric")
        assert 0.0 < board.score < 1.0
        assert board.aggregation == "geometric"

    def test_custom_aggregator_callable(self, uav_model):
        def harmonic(children):
            total = sum(w for w, _ in children)
            return total / sum(w / u for w, u in children)

        board = scoreboard(uav_model, aggregation=harmonic)
        assert board.aggregation == "harmonic"
        assert 0.0 < board.score < scoreboard(uav_model).score  # HM <= AM

    def test_unknown_aggregation_name_is_rejected(self, uav_model):
        with pytest.raises(AnalysisError, match="aggregation must be one of"):
            scoreboard(uav_model, aggregation="median")


# ---------------------------------------------------------------------------
# model-attribute conventions (weights, utility declarations)
# ---------------------------------------------------------------------------


class TestModelAttributes:
    def test_declared_weights_are_read_from_the_model(self, uav):
        rows = rows_by_name(uav)
        assert rows["performance"].weight == 3.0
        assert rows["endurance"].weight == 3.0
        assert rows["radius"].weight == 2.0

    def test_missing_weight_defaults_to_one(self, uav):
        rows = rows_by_name(uav)
        assert rows["mission"].weight == 1.0
        assert rows["cost"].weight == 1.0
        assert rows["regulatory"].weight == 1.0

    def test_utility_shape_is_read_from_the_model(self, uav):
        rows = rows_by_name(uav)
        assert rows["endurance"].shape == "larger-is-better"
        assert rows["mass"].shape == "smaller-is-better"
        assert rows["quiet"].shape == "target-is-best"

    def test_undeclared_shape_defaults_to_step(self, uav):
        assert rows_by_name(uav)["regulatory"].shape == "step"

    def test_step_pass_fail_comes_from_the_requirement_check(self, uav):
        row = rows_by_name(uav)["regulatory"]
        assert row.raw is True  # 1.62 <= 25.0
        assert row.utility == 1.0

    def test_declarations_inherit_through_typing(self):
        board = scoreboard(longeron.loads(INHERIT_MODEL))
        rows = rows_by_name(board)
        assert rows["fast"].weight == 4.0  # from the def
        assert rows["fast"].shape == "larger-is-better"
        assert rows["fast"].utility == pytest.approx(0.75)  # (40-10)/40

    def test_own_declaration_overrides_the_inherited_one(self):
        rows = rows_by_name(scoreboard(longeron.loads(INHERIT_MODEL)))
        assert rows["fastButCheap"].weight == 1.0  # usage overrides def
        assert rows["fastButCheap"].shape == "larger-is-better"  # still inherited

    def test_negative_weight_is_rejected(self, uav_model):
        with pytest.raises(AnalysisError, match="non-negative"):
            scoreboard(uav_model, weights={"endurance": -1.0})

    def test_unknown_utility_shape_is_rejected(self, uav_model):
        with pytest.raises(AnalysisError, match="unknown utility shape"):
            scoreboard(uav_model, utilities={"endurance": "sigmoid"})

    def test_missing_shape_parameters_name_the_requirement(self):
        src = """
        package P {
            requirement broken {
                attribute utility : String = "larger-is-better";
                attribute measure : Real = 5.0;
            }
        }
        """
        with pytest.raises(AnalysisError, match=r"P::broken.*ramp0"):
            scoreboard(longeron.loads(src))

    def test_weight_and_utility_overrides_are_exploration_kwargs(self, uav_model):
        board = scoreboard(
            uav_model,
            weights={"ScoutUAV::mission::performance": 100.0},
            utilities={"quiet": "step"},
        )
        rows = rows_by_name(board)
        assert rows["performance"].weight == 100.0
        assert rows["quiet"].shape == "step"
        assert rows["quiet"].utility == 1.0  # 68.0 is truthy

    def test_custom_utility_callable_override(self, uav_model):
        board = scoreboard(uav_model, utilities={"endurance": lambda raw: raw / 100.0})
        assert rows_by_name(board)["endurance"].utility == pytest.approx(0.32)


# ---------------------------------------------------------------------------
# unmeasured requirements
# ---------------------------------------------------------------------------


class TestUnmeasured:
    def test_leaf_without_measure_or_constraint_is_unmeasured(self, uav):
        row = rows_by_name(uav)["futureProofing"]
        assert row.raw is None
        assert math.isnan(row.utility)
        assert math.isnan(row.aggregate)

    def test_unmeasured_leaves_are_excluded_from_aggregation(self, uav):
        rows = rows_by_name(uav)
        # operability aggregates its three measured children only
        expected = (rows["mass"].utility + 1.0 + rows["quiet"].utility) / 3
        assert rows["operability"].aggregate == pytest.approx(expected)

    def test_fully_unmeasured_subtree_is_nan(self):
        src = """
        package P {
            requirement root {
                requirement a { requirement x; requirement y; }
                requirement b { require constraint { 1 < 2 } }
            }
        }
        """
        board = scoreboard(longeron.loads(src))
        rows = rows_by_name(board)
        assert math.isnan(rows["a"].aggregate)
        assert rows["root"].aggregate == 1.0  # only b counts

    def test_failed_assumption_means_not_applicable(self):
        src = """
        package P {
            attribute speed : Real = 5.0;
            requirement narrow {
                assume constraint { speed > 100.0 }
                require constraint { speed < 200.0 }
            }
        }
        """
        row = rows_by_name(scoreboard(longeron.loads(src)))["narrow"]
        assert row.raw is None
        assert math.isnan(row.utility)

    def test_unresolvable_measure_is_unmeasured_not_an_error(self):
        src = """
        package P {
            requirement r {
                attribute utility : String = "ramp";
                attribute ramp0 : Real = 0.0;
                attribute ramp1 : Real = 1.0;
                attribute measure : Real = notDefinedAnywhere;
            }
        }
        """
        row = rows_by_name(scoreboard(longeron.loads(src)))["r"]
        assert row.raw is None and math.isnan(row.utility)


# ---------------------------------------------------------------------------
# values= injection and the trade-study bridge
# ---------------------------------------------------------------------------


class TestValuesInjection:
    def test_injection_by_qualified_name(self, uav_model):
        qname = "ScoutUAV::mission::performance::endurance"
        board = scoreboard(uav_model, values={qname: 45.0})
        assert rows_by_name(board)["endurance"].utility == 1.0

    def test_injection_by_requirement_name(self, uav_model):
        board = scoreboard(uav_model, values={"endurance": 15.0})
        assert rows_by_name(board)["endurance"].utility == 0.0

    def test_injection_binds_free_names_in_measure_expressions(self, uav_model):
        board = scoreboard(uav_model, values={"flightTime": 45.0, "unitCost": 500.0})
        rows = rows_by_name(board)
        assert rows["endurance"].raw == 45.0
        assert rows["endurance"].utility == 1.0
        assert rows["cost"].utility == 1.0
        # untouched measures still evaluate from the model
        assert rows["mass"].raw == pytest.approx(1.62)

    def test_injection_binds_free_names_in_constraint_bodies(self, uav_model):
        board = scoreboard(uav_model, values={"totalMass": 30.0})
        rows = rows_by_name(board)
        assert rows["regulatory"].raw is False  # 30 > 25
        assert rows["regulatory"].utility == 0.0

    def test_injection_moves_the_score(self, uav_model):
        base = scoreboard(uav_model).score
        better = scoreboard(uav_model, values={"flightTime": 44.0, "unitCost": 600.0}).score
        assert better > base

    def test_architecture_values_bridges_trade_studies(self, uav_model):
        class FakeArchitecture:  # duck-typed like trades.Architecture
            def __init__(self):
                self.metrics = {"flightTime": 40.0, "unitCost": 800.0}

        values = architecture_values(FakeArchitecture())
        assert values == {"flightTime": 40.0, "unitCost": 800.0}
        board = scoreboard(uav_model, values=values)
        assert rows_by_name(board)["endurance"].raw == 40.0

    def test_architecture_values_rejects_non_architectures(self):
        with pytest.raises(AnalysisError, match="metrics"):
            architecture_values(object())


# ---------------------------------------------------------------------------
# scope resolution and the table
# ---------------------------------------------------------------------------


class TestScopesAndTable:
    def test_table_is_preorder_with_depths(self, uav):
        rows = uav.table()
        assert [r.name for r in rows[:4]] == ["mission", "performance", "endurance", "radius"]
        assert [r.depth for r in rows[:4]] == [0, 1, 2, 2]
        assert all(isinstance(r, Row) for r in rows)

    def test_row_kinds(self, uav):
        rows = rows_by_name(uav)
        assert rows["mission"].kind == "group"
        assert rows["endurance"].kind == "leaf"

    def test_sibling_shares_sum_to_one(self, uav):
        rows = uav.table()
        top = [r.share for r in rows if r.depth == 1]
        assert sum(top) == pytest.approx(1.0)
        assert rows[0].share == 1.0  # the root

    def test_qnames_are_qualified_names(self, uav):
        qnames = [r.qname for r in uav.table()]
        assert "ScoutUAV::mission" in qnames
        assert "ScoutUAV::mission::performance::endurance" in qnames

    def test_multiple_roots_aggregate_under_a_synthetic_root(self):
        src = """
        package P {
            requirement a { require constraint { 1 < 2 } }
            requirement b { require constraint { 2 < 1 } }
        }
        """
        board = scoreboard(longeron.loads(src))
        assert board.root.qname == "~root"
        assert board.score == pytest.approx(0.5)

    def test_requirement_definition_as_the_explicit_root(self):
        model = longeron.loads(INHERIT_MODEL)
        definition = model.members[0].members[1]
        assert definition.name == "FastEnough"
        board = scoreboard(definition)
        assert board.root.qname == "Reqs::FastEnough"
        assert board.score == pytest.approx(0.75)

    def test_no_requirements_is_an_error(self):
        model = longeron.loads("package Empty { part def Widget; }")
        with pytest.raises(AnalysisError, match="no requirement usages"):
            scoreboard(model)

    def test_str_renders_an_aligned_table_with_the_score(self, uav):
        text = str(uav)
        assert "requirement" in text and "aggregate" in text
        assert "score (saw)" in text
        assert "endurance" in text

    def test_scoreboard_is_deterministic(self, uav_model):
        a = scoreboard(uav_model)
        b = scoreboard(uav_model)
        # NaN-safe: the widget payload scrubs NaN to None
        assert a._payload(a.root) == b._payload(b.root)
        assert a.score == b.score


# ---------------------------------------------------------------------------
# the widget (headless: traits + front-end contracts)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def widget(uav):
    pytest.importorskip("anywidget")
    return uav.widget()


class TestWidget:
    def test_payload_mirrors_the_scoreboard(self, widget, uav):
        payload = json.loads(widget.nodes_json)
        assert payload["qname"] == "ScoutUAV::mission"
        assert payload["aggregate"] == pytest.approx(uav.score)
        names = [child["label"] for child in payload["children"]]
        assert names == ["performance", "affordability", "operability"]

    def test_payload_encodes_unmeasured_as_null_not_nan(self, widget):
        payload = json.loads(widget.nodes_json)  # strict JSON: would reject NaN
        (oper,) = [c for c in payload["children"] if c["label"] == "operability"]
        (future,) = [c for c in oper["children"] if c["label"] == "futureProofing"]
        assert future["utility"] is None
        assert future["measured"] is False

    def test_default_traits(self, widget):
        assert widget.tessellation == "treemap"
        assert widget.aggregation == "saw"
        assert widget.selected == []
        assert widget.collapsed == []
        assert widget.seed == 42

    def test_voronoi_tessellation_and_seed(self, uav):
        pytest.importorskip("anywidget")
        widget = uav.widget("voronoi", seed=7)
        assert widget.tessellation == "voronoi"
        assert widget.seed == 7

    def test_unknown_tessellation_is_rejected(self, uav):
        pytest.importorskip("anywidget")
        with pytest.raises(ValueError, match=r"treemap.*voronoi"):
            uav.widget("sunburst")

    def test_precollapsed_subtrees_are_validated(self, uav):
        pytest.importorskip("anywidget")
        widget = uav.widget(collapsed=["ScoutUAV::mission::operability"])
        assert widget.collapsed == ["ScoutUAV::mission::operability"]
        with pytest.raises(ValueError, match="unknown collapsed qname"):
            uav.widget(collapsed=["Nope::nothere"])

    def test_selection_observer_idiom(self, widget):
        seen = []
        widget.on_select(seen.append)
        widget.selected = ["ScoutUAV::mission::performance"]
        assert seen == [["ScoutUAV::mission::performance"]]

    def test_esm_bundles_the_vendored_voronoi(self, widget):
        # the vendored d3-voronoi-treemap IIFE, licenses in its header
        assert "lgnVoronoi" in widget._esm
        assert "BSD-3-Clause" in widget._esm
        assert "d3-voronoi-treemap 1.1.2" in widget._esm

    def test_esm_interaction_contracts(self, widget):
        # squarified treemap, seeded voronoi, hover/click/double-click,
        # collapse-in-place, and the perceptual color ramp
        for token in (
            "lgnSbSquarify",
            "voronoiTreemap",
            "prng",
            "pointermove",
            "dblclick",
            "change:collapsed",
            "change:selected",
            "lgnSbColor",
            "lgnSbOklabToRgb",
            "-hatch",
        ):
            assert token in widget._esm, token

    def test_css_contracts(self, widget):
        for token in ("lgn-sb-cell", "lgn-sb-selected", "lgn-sb-tip", "--jp-brand-color1"):
            assert token in widget._css, token

    def test_widget_payload_is_deterministic(self, uav_model):
        pytest.importorskip("anywidget")
        one = scoreboard(uav_model).widget().nodes_json
        two = scoreboard(uav_model).widget().nodes_json
        assert one == two
