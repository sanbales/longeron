"""Spike tests: trade-study viz -- payload/brush logic and figures."""

import json
from pathlib import Path

import pytest

import longeron
from longeron.analysis import AnalysisError, viz
from longeron.analysis.trades import Architecture

EXAMPLES = Path(__file__).parent.parent / "examples"

ROWS = [
    {"motor": "a", "prop": "p1", "cost": 100.0, "mass": 0.9, "feasible": True},
    {"motor": "b", "prop": "p1", "cost": 150.0, "mass": 1.0, "feasible": True},
    {"motor": "a", "prop": "p2", "cost": 200.0, "mass": 1.1, "feasible": False},
]


@pytest.fixture(scope="module")
def study():
    from longeron.analysis import trades

    catalog = longeron.load(EXAMPLES / "drone_catalog.sysml", cache=False)
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
        assert sum(r["feasible"] for r in rows) == 4
        assert {"motors", "props", "battery", "esc", "totalCost", "feasible"} <= set(rows[0])

    def test_derived_columns(self, study):
        rows = viz.mix_table(
            study,
            derived={"tw": lambda a: a.metrics["totalThrust"] / (a.metrics["totalMass"] * 9.81)},
        )
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
        for token in (
            "brushZone",
            "moveInterval",
            "resizeInterval",
            "ns-resize",
            "grab",
            "crosshair",
            "dblclick",
        ):
            assert token in widget._esm, token

    def test_brush_math_with_node(self, tmp_path):
        """The pure JS interval/hit-test helpers, exercised via node."""

        import shutil
        import subprocess

        node = shutil.which("node")
        if node is None:
            pytest.skip("node not available")
        module = tmp_path / "pc_math.mjs"
        module.write_text(
            viz._PC_MATH_JS + "\nexport { clamp01, interval,"
            " inBrush, brushZone, moveInterval,"
            " resizeInterval };\n"
        )
        script = tmp_path / "test.mjs"
        script.write_text(f"""
import {{ brushZone, moveInterval, resizeInterval, inBrush }}
  from {json.dumps(module.as_uri())};
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
        out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert "node brush math ok" in out.stdout


def _arch(motor, cost, hover, mass, feasible=True):
    return Architecture(
        selection={"motor": motor},
        metrics={"cost": cost, "hover": hover, "mass": mass},
        verified=feasible,
    )


class TestFigures:
    @pytest.fixture(autouse=True)
    def _agg(self):
        matplotlib = pytest.importorskip("matplotlib")
        matplotlib.use("Agg")

    @staticmethod
    def _front_points(fig):
        return [
            tuple(p)
            for c in fig.axes[0].collections
            if c.get_label() == "Pareto frontier"
            for p in c.get_offsets()
        ]

    def test_pareto_figure(self):
        archs = [
            _arch("a", 100, 15, 1.0),
            _arch("b", 150, 7, 0.9),
            _arch("c", 180, 6, 1.1),
            _arch("d", 120, 5, 1.2, False),
        ]
        fig = viz.pareto_figure(
            archs,
            x="cost",
            y="hover",
            sense=("min", "max"),
            panel_y="mass",
            annotate={"cruiser": archs[0]},
        )
        assert len(fig.axes) == 2  # main + small multiple
        texts = [t.get_text() for t in fig.axes[0].texts]
        assert "cruiser" in texts
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_pareto_figure_front_is_computed_from_plotted_axes(self):
        """Regression: a mix that is Pareto-optimal only via an unplotted
        third metric (b: lightest) must NOT appear on the drawn cost-hover
        frontier -- projecting a 3-objective front here was the bug."""

        archs = [
            _arch("a", 100, 15, 1.0),
            _arch("b", 150, 7, 0.9),
            _arch("c", 180, 6, 1.1),
            _arch("d", 120, 5, 1.2, False),
        ]
        fig = viz.pareto_figure(archs, x="cost", y="hover", sense=("min", "max"), panel_y="mass")
        assert self._front_points(fig) == [(100.0, 15.0)]  # a alone
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_pareto_figure_senses(self):
        archs = [_arch("a", 100, 15, 1.0), _arch("b", 150, 7, 0.9), _arch("c", 180, 6, 1.1)]
        # the default sense is the conservative (min, min): a maximize-y
        # chart must say so explicitly -- there is no silent max default
        fig = viz.pareto_figure(archs, x="cost", y="mass")
        # min cost / min mass: a (cheaper) and b (lighter); c dominated
        assert sorted(self._front_points(fig)) == [(100.0, 1.0), (150.0, 0.9)]
        import matplotlib.pyplot as plt

        plt.close(fig)
        with pytest.raises(AnalysisError):
            viz.pareto_figure(archs, x="cost", y="mass", sense=("min", "down"))
        with pytest.raises(AnalysisError):
            viz.pareto_figure(archs, x="cost", y="mass", sense=("up", "min"))

    @staticmethod
    def _step_line(fig):
        lines = [ln for ln in fig.axes[0].get_lines() if len(ln.get_xdata()) > 1]
        assert len(lines) == 1
        return lines[0]

    def test_step_line_bounds_the_attainable_side(self):
        """Staircase orientation follows the x sense: best-so-far y holds
        while x worsens, so no front point ever hangs outside its own
        step line."""

        import matplotlib.pyplot as plt

        archs = [_arch("a", 100, 10, 1.0), _arch("b", 150, 20, 0.9), _arch("c", 200, 30, 1.1)]
        fig = viz.pareto_figure(archs, x="cost", y="hover", sense=("min", "max"))
        assert self._step_line(fig).get_drawstyle() == "steps-post"
        plt.close(fig)
        fig = viz.pareto_figure(archs, x="hover", y="cost", sense=("max", "min"))
        assert self._step_line(fig).get_drawstyle() == "steps-pre"
        plt.close(fig)

    def test_pareto_figure_catalog_front_matches_brute_force(self, study):
        """Regression on the shipped catalog: the drawn cost-hover front
        is the brute-force 2D non-dominated set -- one mix, the $122
        cruiser (cheapest AND longest-hovering)."""

        archs = study.all_architectures()
        feasible = [a for a in archs if a.verified]
        brute = {
            (a.metrics["totalCost"], a.metrics["hoverMinutes"])
            for a in feasible
            if not any(
                b.metrics["totalCost"] <= a.metrics["totalCost"]
                and b.metrics["hoverMinutes"] >= a.metrics["hoverMinutes"]
                and (
                    b.metrics["totalCost"] < a.metrics["totalCost"]
                    or b.metrics["hoverMinutes"] > a.metrics["hoverMinutes"]
                )
                for b in feasible
            )
        }
        fig = viz.pareto_figure(
            archs, x="totalCost", y="hoverMinutes", sense=("min", "max"), panel_y="totalMass"
        )
        assert set(self._front_points(fig)) == brute == {(122.0, 15.0)}
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_pareto_figure_single_panel(self):
        archs = [_arch("a", 100, 15, 1.0), _arch("b", 150, 7, 0.9)]
        fig = viz.pareto_figure(archs, x="cost", y="hover", sense=("min", "max"))
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
        fig = viz.margin_sweep_figure(stub, "x", values, {"tight": "tight", "loose": "loose"})
        assert stub.x == 0.0  # baseline restored
        texts = [t.get_text() for t in fig.axes[0].texts]
        assert any("infeasible:" in t and "tight" in t for t in texts)
        # ONLY infeasible bands shade: no accent span, no 'feasible' caption
        assert not any(t.strip() == "feasible" for t in texts)
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_sweep_bands_union_over_all_constraints(self):
        """The regression the user reported: EVERY constraint that goes
        negative anywhere contributes a band -- a floor broken at the
        low end, a ceiling broken at the high end, and a requirement
        lost in the middle each carry their own names, with overlaps
        merged and labeled with all binding constraints."""

        values = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        curves = {
            "floor": [x - 2.0 for x in values],  # negative below 2
            "middle": [(x - 4.0) * (x - 6.0) for x in values],  # negative in (4, 6)
            "ceiling": [8.0 - x for x in values],  # negative above 8
        }
        bands = viz._sweep_bands(values, curves)
        assert bands == [
            {"x0": 0.0, "x1": 2.0, "binding": ["floor"]},
            {"x0": 4.0, "x1": 6.0, "binding": ["middle"]},
            {"x0": 8.0, "x1": 10.0, "binding": ["ceiling"]},
        ]

    def test_sweep_bands_overlaps_stack_their_labels(self):
        """Where two constraints are broken at once the band carries BOTH
        names; the union splits exactly where the violated set changes."""

        values = [0.0, 1.0, 2.0, 3.0, 4.0]
        curves = {
            "a": [1.0, -1.0, -1.0, -1.0, 1.0],  # negative in (0.5, 3.5)
            "b": [1.0, 1.0, -1.0, 1.0, 1.0],  # negative in (1.5, 2.5)
        }
        bands = viz._sweep_bands(values, curves)
        assert bands == [
            {"x0": 0.5, "x1": 1.5, "binding": ["a"]},
            {"x0": 1.5, "x1": 2.5, "binding": ["a", "b"]},
            {"x0": 2.5, "x1": 3.5, "binding": ["a"]},
        ]

    def test_margin_sweep_bands_match_sign_structure(self):
        """A sweep that leaves and re-enters feasibility shades exactly
        the negative stretch, with interpolated boundaries -- and the
        feasible stretches produce no bands at all."""

        values = [0.0, 1.0, 2.0, 3.0, 4.0]
        curves = {
            "m1": [3.0, 0.0 + 1e-12, -1.0, 0.0, 3.0],  # dips below zero mid-sweep
            "m2": [5.0, 4.0, 3.0, 2.0, 1.0],  # always holds
        }
        bands = viz._sweep_bands(values, curves)
        assert len(bands) == 1
        assert bands[0]["binding"] == ["m1"]
        # boundaries interpolate m1's zero crossings
        assert bands[0]["x0"] == pytest.approx(1.0, abs=1e-6)
        assert bands[0]["x1"] == pytest.approx(3.0, abs=1e-6)

        class Stub:
            def __init__(self):
                self.x = 0.0

            def set_val(self, name, value):
                self.x = value

            def run_model(self):
                pass

            def get_val(self, name):
                if name == "x":
                    return [self.x]
                if name == "m1":
                    return [-(self.x - 1.0) * (3.0 - self.x) if 1.0 <= self.x <= 3.0 else 1.0]
                return [5.0 - self.x]

        fig = viz.margin_sweep_figure(Stub(), "x", [i / 4 for i in range(17)], ["m1", "m2"])
        texts = " ".join(t.get_text() for t in fig.axes[0].texts)
        assert "infeasible:" in texts and "m1" in texts
        # tint + hatch per infeasible band, nothing shaded elsewhere
        assert len(fig.axes[0].patches) == 2  # one tint + one hatch overlay
        import matplotlib.pyplot as plt

        plt.close(fig)

    def test_sweep_bands_all_infeasible_names_the_culprit(self):
        bands = viz._sweep_bands([0.0, 1.0], {"a": [-1.0, -2.0], "b": [1.0, 1.0]})
        assert bands == [{"x0": 0.0, "x1": 1.0, "binding": ["a"]}]
        with pytest.raises(AnalysisError):
            viz._sweep_bands([0.0, 1.0], {})

    def test_notebook_sweep_shows_stall_and_cruise_bands(self):
        """The reported gap: the stall floor and transit-speed ceiling
        must appear as their own infeasible bands when the sweep range
        actually crosses them (the old notebook swept exactly the legal
        [11, 24] window, so only stationFloor could ever bind)."""

        pytest.importorskip("openmdao")
        from longeron.analysis import mdao

        model = longeron.load(EXAMPLES / "uav_missions.sysml", cache=False)
        build = mdao.build_problem(
            model, "UavMissions::IsrPrime", requirements=("UavMissions::IsrStation",)
        )
        p = build.problem
        values = [9.0 + 0.35 * i for i in range(50)]
        curves = {label: [] for label in build.constraints}
        for v in values:
            p.set_val("loiterSpeed", v)
            p.run_model()
            for label, output in build.constraints.items():
                curves[label].append(float(p.get_val(output)[0]))
        bands = viz._sweep_bands(values, curves)
        named = [tuple(b["binding"]) for b in bands]
        assert ("aboveStall",) in named  # below 11 m/s
        assert any("IsrStation::stationFloor" in b for b in named)  # past ~19.5
        assert any("belowCruise" in b for b in named)  # above 24 m/s
        # above 24 BOTH the ceiling and the station floor are broken
        assert any(set(b) >= {"belowCruise", "IsrStation::stationFloor"} for b in named)

    def test_margin_sweep_figure_needs_margins(self):
        with pytest.raises(AnalysisError):
            viz.margin_sweep_figure(object(), "x", [0.0], {})


MISSION_CHARTS = {
    "isr": ("UavMissions::IsrUav", "stationMinutes"),
    "logistics": ("UavMissions::LogisticsUav", "payloadRangeKgKm"),
    "intercept": ("UavMissions::InterceptUav", "maxTargetSpeed"),
}


@pytest.fixture(scope="module")
def mission_spaces():
    from longeron.analysis import trades

    model = longeron.load(EXAMPLES / "uav_missions.sysml", cache=False)
    out = {}
    for name, (qname, metric) in MISSION_CHARTS.items():
        study = trades.TradeStudy(model, qname)
        out[name] = (study.all_architectures(), metric)
    return out


class TestMissionFrontFigures:
    """Regression for the reported symptom: on every mission chart the
    drawn frontier must be exactly the brute-force 2D non-dominated set
    of the *feasible* mixes, and no feasible point may sit outside it
    (strictly better on both plotted objectives than a front member)."""

    @pytest.fixture(autouse=True)
    def _agg(self):
        matplotlib = pytest.importorskip("matplotlib")
        matplotlib.use("Agg")

    @staticmethod
    def _points(fig, label):
        return [
            tuple(p)
            for c in fig.axes[0].collections
            if c.get_label() == label
            for p in c.get_offsets()
        ]

    @pytest.mark.parametrize("name", list(MISSION_CHARTS))
    def test_front_matches_brute_force_and_bounds_the_cloud(self, mission_spaces, name):
        import matplotlib.pyplot as plt

        archs, metric = mission_spaces[name]
        fig = viz.pareto_figure(archs, x="missionCost", y=metric, sense=("min", "max"))
        drawn = sorted(self._points(fig, "Pareto frontier"))

        feasible = [(a.metrics["missionCost"], a.metrics[metric]) for a in archs if a.verified]
        brute = sorted(
            {
                (c, m)
                for c, m in feasible
                if not any(bc <= c and bm >= m and (bc, bm) != (c, m) for bc, bm in feasible)
            }
        )
        assert drawn == brute
        assert len(drawn) >= 4  # a real staircase, not a lone point

        # the exact geometric symptom: a non-front feasible point strictly
        # cheaper AND better than a front point would plot outside the
        # staircase -- there must be none
        front = set(drawn)
        for c, m in feasible:
            if (c, m) in front:
                continue
            assert not any(c < fc and m > fm for fc, fm in front), (c, m)
            # equivalently: it sits on the attainable side of the stair
            stair = max((fm for fc, fm in front if fc <= c), default=None)
            assert stair is not None and m <= stair + 1e-9

        # the step line is drawn through the front, oriented for min-x
        lines = [ln for ln in fig.axes[0].get_lines() if len(ln.get_xdata()) > 1]
        assert len(lines) == 1
        assert lines[0].get_drawstyle() == "steps-post"
        assert sorted(zip(lines[0].get_xdata(), lines[0].get_ydata(), strict=True)) == brute
        plt.close(fig)

    def test_intercept_front_carries_wings_and_teardrop(self, mission_spaces):
        import matplotlib.pyplot as plt

        archs, metric = mission_spaces["intercept"]
        fig = viz.pareto_figure(archs, x="missionCost", y=metric, sense=("min", "max"))
        drawn = set(self._points(fig, "Pareto frontier"))
        on_front = {
            a.selection["airframe"]
            for a in archs
            if a.verified and (a.metrics["missionCost"], a.metrics[metric]) in drawn
        }
        assert {"dartInterceptor", "teardropQuad"} <= on_front
        plt.close(fig)
