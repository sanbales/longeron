"""Spike tests: trade-study viz -- payload/brush logic and figures."""

import json
from pathlib import Path

import pytest

import sysml2
from sysml2.analysis import AnalysisError, viz
from sysml2.analysis.trades import Architecture

EXAMPLES = Path(__file__).parent.parent / "examples"

ROWS = [
    {"motor": "a", "prop": "p1", "cost": 100.0, "mass": 0.9,
     "feasible": True},
    {"motor": "b", "prop": "p1", "cost": 150.0, "mass": 1.0,
     "feasible": True},
    {"motor": "a", "prop": "p2", "cost": 200.0, "mass": 1.1,
     "feasible": False},
]


@pytest.fixture(scope="module")
def study():
    from sysml2.analysis import trades

    catalog = sysml2.load(EXAMPLES / "drone_catalog.sysml", cache=False)
    return trades.TradeStudy(catalog, "DroneCatalog::TradeQuad")


class TestParcoordsPayload:
    def test_axes_and_ticks(self):
        payload = viz.parcoords_payload(ROWS)
        names = [a["name"] for a in payload["axes"]]
        assert names == ["motor", "prop", "cost", "mass"]  # not 'feasible'
        cost = payload["axes"][2]
        assert [t["label"] for t in cost["ticks"]] == ["100", "200"]
        assert [t["t"] for t in cost["ticks"]] == [0.0, 1.0]

    def test_categorical_first_appearance_order(self):
        motor = viz.parcoords_payload(ROWS)["axes"][0]
        assert [t["label"] for t in motor["ticks"]] == ["a", "b"]
        assert [t["t"] for t in motor["ticks"]] == [0.0, 1.0]

    def test_line_normalization(self):
        lines = viz.parcoords_payload(ROWS)["lines"]
        assert lines[0]["t"] == [0.0, 0.0, 0.0, 0.0]
        assert lines[1]["t"] == [1.0, 0.0, 0.5, 0.5]
        assert lines[2]["feasible"] is False
        assert lines[0]["label"] == "a / p1"
        assert lines[0]["v"][2] == "100"

    def test_constant_axis_pins_middle(self):
        rows = [{"x": 1.0, "k": "only"}, {"x": 1.0, "k": "only"}]
        payload = viz.parcoords_payload(rows)
        assert all(line["t"] == [0.5, 0.5] for line in payload["lines"])

    def test_axis_subset_and_errors(self):
        payload = viz.parcoords_payload(ROWS, axes=["cost", "motor"])
        assert [a["name"] for a in payload["axes"]] == ["cost", "motor"]
        with pytest.raises(AnalysisError):
            viz.parcoords_payload(ROWS, axes=["nope"])
        with pytest.raises(AnalysisError):
            viz.parcoords_payload([])


class TestMixTable:
    def test_full_candidate_space(self, study):
        rows = viz.mix_table(study)
        assert len(rows) == 54
        assert sum(r["feasible"] for r in rows) == 8
        assert {"motors", "props", "battery", "esc", "totalCost",
                "feasible"} <= set(rows[0])

    def test_derived_columns(self, study):
        rows = viz.mix_table(study, derived={
            "tw": lambda a: a.metrics["totalThrust"]
            / (a.metrics["totalMass"] * 9.81)})
        assert all(r["tw"] > 0 for r in rows)


class TestParcoordsWidget:
    def test_widget_payload_and_selected(self):
        pytest.importorskip("anywidget")
        widget = viz.parcoords(ROWS, width_px=600)
        payload = json.loads(widget.table_json)
        assert len(payload["lines"]) == 3
        assert widget.width_px == 600
        assert widget.selected_indices() == [0, 1, 2]  # no brush: all pass
        widget.selected = "[1]"
        assert widget.selected_indices() == [1]

    def test_brush_semantics_documented_in_js(self):
        pytest.importorskip("anywidget")
        widget = viz.parcoords(ROWS)
        assert "pointerdown" in widget._esm  # brushing is a drag
        assert "selected" in widget._esm  # syncs back to Python
        # editable brushes: move/resize/clear + cursor affordances
        for token in ("brushZone", "moveInterval", "resizeInterval",
                      "ns-resize", "grab", "crosshair", "dblclick"):
            assert token in widget._esm, token

    def test_brush_math_with_node(self, tmp_path):
        """The pure JS interval/hit-test helpers, exercised via node."""

        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        module = tmp_path / "pc_math.mjs"
        module.write_text(viz._PC_MATH_JS + "\nexport { clamp01, interval,"
                          " inBrush, brushZone, moveInterval,"
                          " resizeInterval };\n")
        script = tmp_path / "test.mjs"
        script.write_text(f"""
import {{ brushZone, moveInterval, resizeInterval, inBrush }}
  from {json.dumps(str(module))};
import assert from "node:assert/strict";
assert.equal(brushZone(0.4, [0.2, 0.6], 0.02), "body");
assert.equal(brushZone(0.21, [0.2, 0.6], 0.02), "lo");
assert.equal(brushZone(0.615, [0.2, 0.6], 0.02), "hi");
assert.equal(brushZone(0.9, [0.2, 0.6], 0.02), null);
assert.deepEqual(moveInterval([0.2, 0.4], 0.3), [0.5, 0.7]);
assert.deepEqual(moveInterval([0.6, 0.9], 0.5), [0.7, 1]);
assert.deepEqual(resizeInterval([0.2, 0.6], "lo", 0.7),
                 {{ brush: [0.6, 0.7], end: "hi" }});
assert.equal(inBrush([0.2, 0.6], 0.6), true);
console.log("node brush math ok");
""")
        out = subprocess.run([node, str(script)], capture_output=True,
                             text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert "node brush math ok" in out.stdout


def _arch(motor, cost, hover, mass, feasible=True):
    return Architecture(
        selection={"motor": motor},
        metrics={"cost": cost, "hover": hover, "mass": mass},
        verified=feasible)


class TestFigures:
    @pytest.fixture(autouse=True)
    def _agg(self):
        matplotlib = pytest.importorskip("matplotlib")
        matplotlib.use("Agg")

    @staticmethod
    def _front_points(fig):
        return [tuple(p) for c in fig.axes[0].collections
                if c.get_label() == "Pareto frontier"
                for p in c.get_offsets()]

    def test_pareto_figure(self):
        archs = [_arch("a", 100, 15, 1.0), _arch("b", 150, 7, 0.9),
                 _arch("c", 180, 6, 1.1), _arch("d", 120, 5, 1.2, False)]
        fig = viz.pareto_figure(
            archs, x="cost", y="hover", panel_y="mass",
            annotate={"cruiser": archs[0]})
        assert len(fig.axes) == 2  # main + small multiple
        texts = [t.get_text() for t in fig.axes[0].texts]
        assert "cruiser" in texts
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_pareto_figure_front_is_computed_from_plotted_axes(self):
        """Regression: a mix that is Pareto-optimal only via an unplotted
        third metric (b: lightest) must NOT appear on the drawn cost-hover
        frontier -- projecting a 3-objective front here was the bug."""

        archs = [_arch("a", 100, 15, 1.0), _arch("b", 150, 7, 0.9),
                 _arch("c", 180, 6, 1.1), _arch("d", 120, 5, 1.2, False)]
        fig = viz.pareto_figure(archs, x="cost", y="hover", panel_y="mass")
        assert self._front_points(fig) == [(100.0, 15.0)]  # a alone
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_pareto_figure_senses(self):
        archs = [_arch("a", 100, 15, 1.0), _arch("b", 150, 7, 0.9),
                 _arch("c", 180, 6, 1.1)]
        fig = viz.pareto_figure(archs, x="cost", y="mass", y_sense="min")
        # min cost / min mass: a (cheaper) and b (lighter); c dominated
        assert sorted(self._front_points(fig)) == [(100.0, 1.0),
                                                   (150.0, 0.9)]
        import matplotlib.pyplot as plt

        plt.close(fig)
        with pytest.raises(AnalysisError):
            viz.pareto_figure(archs, x="cost", y="mass", y_sense="down")

    def test_pareto_figure_catalog_front_matches_brute_force(self, study):
        """Regression on the shipped catalog: the drawn cost-hover front
        is the brute-force 2D non-dominated set -- one mix, the $118
        cruiser (cheapest AND longest-hovering)."""

        archs = study.all_architectures()
        feasible = [a for a in archs if a.verified]
        brute = {(a.metrics["totalCost"], a.metrics["hoverMinutes"])
                 for a in feasible
                 if not any(
                     b.metrics["totalCost"] <= a.metrics["totalCost"]
                     and b.metrics["hoverMinutes"]
                     >= a.metrics["hoverMinutes"]
                     and (b.metrics["totalCost"] < a.metrics["totalCost"]
                          or b.metrics["hoverMinutes"]
                          > a.metrics["hoverMinutes"])
                     for b in feasible)}
        fig = viz.pareto_figure(archs, x="totalCost", y="hoverMinutes",
                                panel_y="totalMass")
        assert set(self._front_points(fig)) == brute == {(118.0, 15.0)}
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_pareto_figure_single_panel(self):
        archs = [_arch("a", 100, 15, 1.0), _arch("b", 150, 7, 0.9)]
        fig = viz.pareto_figure(archs, x="cost", y="hover")
        assert len(fig.axes) == 1
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_margin_sweep_figure_marks_binding_constraint(self):
        class Stub:  # duck-typed OpenMDAO problem
            def __init__(self):
                self.x = 0.0

            def set_val(self, name, value):
                self.x = value

            def run_model(self):
                pass

            def get_val(self, name):
                if name == "x":
                    return [self.x]
                return [0.5 - self.x if name == "tight" else 2.0 - self.x]

        stub = Stub()
        values = [i / 10 for i in range(11)]
        fig = viz.margin_sweep_figure(
            stub, "x", values, {"tight": "tight", "loose": "loose"})
        assert stub.x == 0.0  # baseline restored
        texts = " ".join(t.get_text() for t in fig.axes[0].texts)
        assert "tight binds at 0.50" in texts
        assert "feasible" in texts  # the shaded band is labeled
        assert "infeasible" in texts
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_margin_sweep_figure_needs_margins(self):
        with pytest.raises(AnalysisError):
            viz.margin_sweep_figure(object(), "x", [0.0], {})
