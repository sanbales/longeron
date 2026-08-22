"""Spike tests: variation/variant catalogs -> CP-SAT architecture trades."""

from pathlib import Path

import pytest

pytest.importorskip("ortools")

import longeron
from longeron.analysis import trades

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def catalog():
    return longeron.load(EXAMPLES / "drone_catalog.sysml", cache=False)


@pytest.fixture(scope="module")
def study(catalog):
    return trades.TradeStudy(catalog, "DroneCatalog::TradeQuad")


class TestModelIntrospection:
    def test_variation_points(self, study):
        assert set(study.points) == {"motors", "props", "battery", "esc"}
        assert study.points["motors"].count == 4
        assert set(study.points["motors"].variants) == {"emax2306", "tmotorF60", "sunnySky2212"}
        assert study.points["motors"].variants["emax2306"]["mass"] == 0.033

    def test_derived_attributes(self, study):
        assert [n for n, _ in study.derived_order] == [
            "totalMass",
            "totalCost",
            "totalThrust",
            "hoverMinutes",
        ]

    def test_constraints_found(self, study):
        assert "cellMatch" in study.constraint_names
        assert "enduranceReq" in study.constraint_names


class TestEnumeration:
    def test_feasible_count(self, study):
        archs = study.enumerate()
        # hand check: tmotorF60 fails endurance; emax needs esc45 + 5" props;
        # sunnySky pairs with any prop and either ESC -> 2 + 6 of 54 combos
        assert len(archs) == 8
        assert all(a.verified for a in archs)
        motors = {a.selection["motors"] for a in archs}
        assert motors == {"emax2306", "sunnySky2212"}

    def test_compatibility_rules_hold(self, study):
        for a in study.enumerate():
            if a.selection["motors"] == "emax2306":
                assert a.selection["esc"] == "esc45"  # escCurrent
                assert a.selection["battery"] == "lipo4s1500"  # cellMatch
                assert a.selection["props"] != "apc1045"  # propFit (10" > 5.1")

    def test_exact_metrics(self, study):
        archs = {tuple(sorted(a.selection.items())): a for a in study.enumerate()}
        key = tuple(
            sorted(
                {
                    "motors": "sunnySky2212",
                    "props": "hq5x43",
                    "battery": "lipo3s2200",
                    "esc": "esc20",
                }.items()
            )
        )
        a = archs[key]
        assert a.metrics["totalCost"] == pytest.approx(118.0)
        assert a.metrics["totalMass"] == pytest.approx(0.979)
        assert a.metrics["hoverMinutes"] == pytest.approx(15.0)


class TestOptimization:
    def test_minimize_cost(self, study):
        best = study.minimize("totalCost")
        assert best is not None
        assert best.metrics["totalCost"] == pytest.approx(118.0)
        assert best.selection["motors"] == "sunnySky2212"
        assert best.selection["esc"] == "esc20"

    def test_maximize_endurance(self, study):
        best = study.maximize("hoverMinutes")
        assert best is not None
        assert best.metrics["hoverMinutes"] == pytest.approx(15.0)

    def test_pareto_front(self, study):
        front = trades.pareto(
            study.enumerate(), minimize=("totalCost", "totalMass"), maximize=("hoverMinutes",)
        )
        picks = {(a.selection["motors"], a.selection["props"], a.selection["esc"]) for a in front}
        assert ("sunnySky2212", "hq5x43", "esc20") in picks  # cheapest
        assert ("emax2306", "hq5x43", "esc45") in picks  # lightest
        assert len(front) == 2

    def test_pareto_two_objective_cost_hover_front(self, study):
        """Regression: the 2D (min cost, max hover) front of the catalog.

        The cheapest feasible mix also hovers longest, so the cost-hover
        front is a *single* point -- the $118 cruiser.  The 0.9 kg racer
        is Pareto-optimal only once mass counts as a third objective; a
        3-objective front projected onto these two axes would wrongly
        include it (that projection was notebook 07's original bug).
        """

        archs = study.enumerate()
        front = trades.pareto(archs, minimize=("totalCost",), maximize=("hoverMinutes",))

        def dominates(b, a):  # brute-force weak dominance cross-check
            return (
                b.metrics["totalCost"] <= a.metrics["totalCost"]
                and b.metrics["hoverMinutes"] >= a.metrics["hoverMinutes"]
            ) and (
                b.metrics["totalCost"] < a.metrics["totalCost"]
                or b.metrics["hoverMinutes"] > a.metrics["hoverMinutes"]
            )

        brute = [a for a in archs if not any(dominates(b, a) for b in archs)]
        key = lambda a: tuple(sorted(a.selection.items()))  # noqa: E731
        assert {key(a) for a in front} == {key(a) for a in brute}
        assert len(front) == 1
        assert front[0].selection == {
            "motors": "sunnySky2212",
            "props": "hq5x43",
            "battery": "lipo3s2200",
            "esc": "esc20",
        }
        assert front[0].metrics["totalCost"] == pytest.approx(118.0)
        assert front[0].metrics["hoverMinutes"] == pytest.approx(15.0)

    def test_pareto_keeps_equal_key_duplicates(self):
        a = trades.Architecture({"m": "a"}, {"cost": 1.0, "hover": 5.0})
        b = trades.Architecture({"m": "b"}, {"cost": 1.0, "hover": 5.0})
        c = trades.Architecture({"m": "c"}, {"cost": 2.0, "hover": 4.0})
        front = trades.pareto([a, b, c], minimize=("cost",), maximize=("hover",))
        assert front == [a, b]  # ties survive; c is dominated

    def test_pareto_weak_dominance(self):
        a = trades.Architecture({"m": "a"}, {"cost": 1.0, "hover": 5.0})
        d = trades.Architecture({"m": "d"}, {"cost": 1.0, "hover": 6.0})
        front = trades.pareto([a, d], minimize=("cost",), maximize=("hover",))
        assert front == [d]  # equal on cost, better on hover: dominates


class TestExplainability:
    def test_feasible_has_no_core(self, study):
        assert study.explain() == []

    def test_infeasible_names_conflict(self, catalog):
        picnic = trades.TradeStudy(catalog, "DroneCatalog::PicnicQuad")
        assert picnic.enumerate() == []
        core = picnic.explain()
        assert core  # a sufficient subset is reported...
        assert "longEndurance" in core  # ...naming the impossible requirement


class TestErrors:
    def test_no_variation_points(self, catalog):
        with pytest.raises(longeron.analysis.AnalysisError):
            trades.TradeStudy(catalog, "DroneCatalog::Emax2306")

    def test_unknown_metric(self, study):
        with pytest.raises(longeron.analysis.AnalysisError):
            study.minimize("nope")


class TestExactEvaluation:
    """evaluate()/all_architectures() need only the interpreter."""

    def test_evaluate_feasible_mix(self, study):
        arch = study.evaluate(
            {"motors": "sunnySky2212", "props": "hq5x43", "battery": "lipo3s2200", "esc": "esc20"}
        )
        assert arch.verified
        assert arch.metrics["totalCost"] == pytest.approx(118.0)

    def test_evaluate_infeasible_mix(self, study):
        arch = study.evaluate(
            {"motors": "tmotorF60", "props": "hq5x43", "battery": "lipo6s1300", "esc": "esc45"}
        )
        assert not arch.verified  # fails enduranceReq (4.875 min)
        assert arch.metrics["hoverMinutes"] == pytest.approx(4.875)

    def test_evaluate_validates_selection(self, study):
        with pytest.raises(longeron.analysis.AnalysisError):
            study.evaluate({"motors": "emax2306"})  # missing points
        with pytest.raises(longeron.analysis.AnalysisError):
            study.evaluate(
                {"motors": "nope", "props": "hq5x43", "battery": "lipo4s1500", "esc": "esc45"}
            )
        with pytest.raises(longeron.analysis.AnalysisError):
            study.evaluate(
                {
                    "motors": "emax2306",
                    "props": "hq5x43",
                    "battery": "lipo4s1500",
                    "esc": "esc45",
                    "extra": "x",
                }
            )

    def test_all_architectures_is_the_candidate_space(self, study):
        archs = study.all_architectures()
        assert len(archs) == 54  # 3 * 3 * 3 * 2
        feasible = [a for a in archs if a.verified]
        assert len(feasible) == 8  # matches enumerate()
        enumerated = {tuple(sorted(a.selection.items())) for a in study.enumerate()}
        assert {tuple(sorted(a.selection.items())) for a in feasible} == enumerated


MINI_CATALOG = """
package MiniCatalog {
    part def Widget { attribute factor : Real; attribute cost : Real; }
    part def SmallW :> Widget { attribute factor : Real = 2.0; attribute cost : Real = 1.0; }
    part def BigW :> Widget { attribute factor : Real = 5.0; attribute cost : Real = 4.0; }
    part def Gadget { attribute factor : Real; attribute cost : Real; }
    part def SlowG :> Gadget { attribute factor : Real = 1.0; attribute cost : Real = 2.0; }
    part def FastG :> Gadget { attribute factor : Real = 3.0; attribute cost : Real = 6.0; }
    variation part def WidgetChoice :> Widget {
        variant part smallW : SmallW;
        variant part bigW : BigW;
    }
    variation part def GadgetChoice :> Gadget {
        variant part slowG : SlowG;
        variant part fastG : FastG;
    }
    part def Rig {
        part widget : WidgetChoice;
        part gadget : GadgetChoice;
        attribute power : Real = widget.factor * gadget.factor;
        attribute cost : Real = widget.cost + gadget.cost;
        constraint feasible { (power >= 6.0 and cost <= 10.0) or cost <= 3.5 }
    }
}
"""


class TestVariableProductsAndNestedLogic:
    """var*var multiplication and nested and/or reification in CP-SAT.

    Hand enumeration of the 4 combos:
      smallW+slowG: power  2, cost  3 -> feasible via 'cost <= 3.5'
      smallW+fastG: power  6, cost  7 -> feasible via the and-arm
      bigW+slowG:   power  5, cost  6 -> INFEASIBLE (both arms fail)
      bigW+fastG:   power 15, cost 10 -> feasible via the and-arm
    Swapping and<->or in either position changes the feasible count.
    """

    @pytest.fixture(scope="class")
    def rig(self):
        return trades.TradeStudy(longeron.loads(MINI_CATALOG), "MiniCatalog::Rig")

    def test_feasible_set(self, rig):
        archs = rig.enumerate()
        assert all(a.verified for a in archs)
        combos = {(a.selection["widget"], a.selection["gadget"]) for a in archs}
        assert combos == {("smallW", "slowG"), ("smallW", "fastG"), ("bigW", "fastG")}

    def test_variable_product_metric_is_exact(self, rig):
        archs = {(a.selection["widget"], a.selection["gadget"]): a for a in rig.enumerate()}
        assert archs[("bigW", "fastG")].metrics["power"] == pytest.approx(15.0)
        assert archs[("smallW", "slowG")].metrics["power"] == pytest.approx(2.0)

    def test_optimize_over_the_product(self, rig):
        best = rig.maximize("power")
        assert best is not None
        assert best.selection == {"widget": "bigW", "gadget": "fastG"}
        cheapest = rig.minimize("cost")
        assert cheapest.selection == {"widget": "smallW", "gadget": "slowG"}


MINI_CATALOG_2 = """
package Mini2 {
    part def Widget { attribute factor : Real; attribute cost : Real; }
    part def SmallW :> Widget { attribute factor : Real = 2.0; attribute cost : Real = 1.0; }
    part def BigW :> Widget { attribute factor : Real = 5.0; attribute cost : Real = 4.0; }
    variation part def WidgetChoice :> Widget {
        variant part smallW : SmallW;
        variant part bigW : BigW;
    }
    part def Rig2 {
        part widget : WidgetChoice;
        attribute margin : Real = 10.0 [kg] - widget.cost;
        attribute neg : Real = -widget.factor;
        constraint posMargin { not (margin < 6.5) }
        constraint always { 1.0 < 2.0 }
    }
    part def Rig3 {
        part widget : WidgetChoice;
        constraint impossible { 1.0 > 2.0 }
    }
    part def Rig4 {
        part widget : WidgetChoice;
        attribute broken : Real = widget.factor / 0.0;
        constraint c { broken >= 0.0 }
    }
}
"""


class TestEncodingEdges:
    @pytest.fixture(scope="class")
    def mini2(self):
        return longeron.loads(MINI_CATALOG_2)

    def test_negated_comparison_subtraction_and_units(self, mini2):
        # not(margin < 6.5): smallW margin 9.0 passes, bigW margin 6.0 fails;
        # flipping the not-encoding would invert the feasible set
        rig = trades.TradeStudy(mini2, "Mini2::Rig2")
        archs = rig.enumerate()
        assert [a.selection for a in archs] == [{"widget": "smallW"}]
        assert archs[0].metrics["margin"] == pytest.approx(9.0)
        assert archs[0].metrics["neg"] == pytest.approx(-2.0)  # unary minus
        assert str(archs[0]) == "[widget=smallW] margin=9, neg=-2"

    def test_statically_false_constraint_empties_the_space(self, mini2):
        rig = trades.TradeStudy(mini2, "Mini2::Rig3")
        assert rig.enumerate() == []

    def test_division_by_constant_zero_is_rejected(self, mini2):
        rig = trades.TradeStudy(mini2, "Mini2::Rig4")
        with pytest.raises(longeron.analysis.AnalysisError, match="division by constant zero"):
            rig.enumerate()

    def test_non_part_assembly_rejected(self, mini2):
        with pytest.raises(longeron.analysis.AnalysisError, match="is not a part definition"):
            trades.TradeStudy(mini2, "Mini2")
