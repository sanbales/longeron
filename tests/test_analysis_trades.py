"""Spike tests: variation/variant catalogs -> CP-SAT architecture trades."""

from pathlib import Path

import pytest

pytest.importorskip("ortools")

import sysml2
from sysml2.analysis import trades

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def catalog():
    return sysml2.load(EXAMPLES / "drone_catalog.sysml", cache=False)


@pytest.fixture(scope="module")
def study(catalog):
    return trades.TradeStudy(catalog, "DroneCatalog::TradeQuad")


class TestModelIntrospection:
    def test_variation_points(self, study):
        assert set(study.points) == {"motors", "props", "battery", "esc"}
        assert study.points["motors"].count == 4
        assert set(study.points["motors"].variants) == {
            "emax2306", "tmotorF60", "sunnySky2212"}
        assert study.points["motors"].variants["emax2306"]["mass"] == 0.033

    def test_derived_attributes(self, study):
        assert [n for n, _ in study.derived_order] == [
            "totalMass", "totalCost", "totalThrust", "hoverMinutes"]

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
        archs = {tuple(sorted(a.selection.items())): a
                 for a in study.enumerate()}
        key = tuple(sorted({"motors": "sunnySky2212", "props": "hq5x43",
                            "battery": "lipo3s2200", "esc": "esc20"}.items()))
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
        front = trades.pareto(study.enumerate(),
                              minimize=("totalCost", "totalMass"),
                              maximize=("hoverMinutes",))
        picks = {(a.selection["motors"], a.selection["props"],
                  a.selection["esc"]) for a in front}
        assert ("sunnySky2212", "hq5x43", "esc20") in picks  # cheapest
        assert ("emax2306", "hq5x43", "esc45") in picks  # lightest
        assert len(front) == 2


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
        with pytest.raises(sysml2.analysis.AnalysisError):
            trades.TradeStudy(catalog, "DroneCatalog::Emax2306")

    def test_unknown_metric(self, study):
        with pytest.raises(sysml2.analysis.AnalysisError):
            study.minimize("nope")
