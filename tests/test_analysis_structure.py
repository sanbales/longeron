"""Spike tests: the analysis-structure diagrams -- N2 payload/orientation
and the bipartite constraint network (payload shape + node-run JS math)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import sysml2
from sysml2.analysis import structure, trades

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def model():
    return sysml2.load(EXAMPLES / "uav_missions.sysml", cache=False)


@pytest.fixture(scope="module")
def build(model):
    mdao = pytest.importorskip("sysml2.analysis.mdao")
    pytest.importorskip("openmdao")
    return mdao.build_problem(
        model, "UavMissions::IsrPrime", requirements=("UavMissions::IsrStation",)
    )


class TestN2Payload:
    def test_components_in_execution_order(self, build):
        payload = structure.n2_payload(build)
        names = [c["name"] for c in payload["components"]]
        assert names[0] == "consts"  # independents run first
        assert {"loiterPowerW", "stationMinutes", "IsrStation_stationFloor_margin"} <= set(names)
        # every cell indexes a real component, no self-couplings
        n = len(names)
        for cell in payload["cells"]:
            assert 0 <= cell["row"] < n and 0 <= cell["col"] < n
            assert cell["row"] != cell["col"]

    def test_couplings_carry_variable_names(self, build):
        payload = structure.n2_payload(build)
        names = [c["name"] for c in payload["components"]]
        i_power = names.index("loiterPowerW")
        i_station = names.index("stationMinutes")
        cell = next(c for c in payload["cells"] if c["row"] == i_station and c["col"] == i_power)
        assert cell["vars"] == ["loiterPowerW \u2192 loiterPowerW"]

    def test_feedforward_problem_has_no_feedback(self, build):
        """This sizing chain is a pure feed-forward cascade: with the
        source in the column and the target in the row, every dot sits
        BELOW the diagonal (col < row) and none is marked feedback."""

        payload = structure.n2_payload(build)
        assert payload["cells"]  # a real matrix, not an empty grid
        for cell in payload["cells"]:
            assert cell["col"] < cell["row"]
            assert cell["feedback"] is False

    def test_feedback_lands_above_the_diagonal(self):
        """A deliberately cyclic two-component group: the back edge gets
        col > row and the feedback flag."""

        om = pytest.importorskip("openmdao.api")
        prob = om.Problem(reports=False)
        prob.model.add_subsystem("a", om.ExecComp("y = 2 * x"), promotes=[])
        prob.model.add_subsystem("b", om.ExecComp("z = y - 1"), promotes=[])
        prob.model.connect("a.y", "b.y")
        prob.model.connect("b.z", "a.x")  # the feedback edge
        prob.model.nonlinear_solver = om.NonlinearBlockGS()
        prob.model.linear_solver = om.LinearBlockGS()
        prob.setup()
        payload = structure.n2_payload(prob)
        names = [c["name"] for c in payload["components"]]
        ia, ib = names.index("a"), names.index("b")
        forward = next(c for c in payload["cells"] if c["row"] == ib and c["col"] == ia)
        back = next(c for c in payload["cells"] if c["row"] == ia and c["col"] == ib)
        assert forward["feedback"] is False
        assert back["feedback"] is True
        assert back["col"] > back["row"]  # above the diagonal

    def test_auto_ivc_is_skipped(self, build):
        payload = structure.n2_payload(build)
        assert all(c["name"] != "_auto_ivc" for c in payload["components"])


@pytest.fixture(scope="module")
def study(model):
    return trades.TradeStudy(model, "UavMissions::InterceptUav")


class TestConstraintNetworkPayload:
    def test_bipartite_shape(self, study):
        payload = structure.constraint_network_payload(study)
        assert [v["name"] for v in payload["variables"]] == [
            "airframe",
            "motors",
            "props",
            "battery",
        ]
        assert {c["name"] for c in payload["constraints"]} == {
            "propFit",
            "packPower",
            "launchLift",
            "canCatch",
        }
        n_v = len(payload["variables"])
        n_c = len(payload["constraints"])
        for vi, ci in payload["edges"]:
            assert 0 <= vi < n_v and 0 <= ci < n_c

    def test_participation_is_transitive(self, study):
        """propFit touches only props+motors directly; canCatch reaches
        every point THROUGH the derived maxTargetSpeed build-up."""

        payload = structure.constraint_network_payload(study)
        names = [v["name"] for v in payload["variables"]]
        cons = {c["name"]: i for i, c in enumerate(payload["constraints"])}

        def touched(name):
            return {names[vi] for vi, ci in payload["edges"] if ci == cons[name]}

        assert touched("propFit") == {"props", "motors"}
        assert touched("canCatch") == {"airframe", "motors", "props", "battery"}

    def test_violation_tinting(self, study):
        space = study.all_architectures()
        payload = structure.constraint_network_payload(study, space)
        by_name = {c["name"]: c for c in payload["constraints"]}
        # every constraint kills someone in this catalog; counts match
        # the brute-force census
        from collections import Counter

        census = Counter(v for a in space if not a.verified for v in a.violations)
        for name, entry in by_name.items():
            assert entry["violations"] == census[name]
            assert entry["tinted"] is (census[name] > 0)
        # without architectures nothing is tinted
        plain = structure.constraint_network_payload(study)
        assert all(not c["tinted"] for c in plain["constraints"])


class TestWidgets:
    def test_n2_widget(self, build):
        pytest.importorskip("anywidget")
        widget = structure.n2_view(build, width_px=500)
        payload = json.loads(widget.payload_json)
        assert payload["components"] and payload["cells"]
        assert widget.width_px == 500
        for token in ("mouseenter", "click", "pinned", "sysml2-n2-feedback-ring"):
            assert token in widget._esm, token

    def test_constraint_network_widget(self, study):
        pytest.importorskip("anywidget")
        widget = structure.constraint_network(study)
        payload = json.loads(widget.payload_json)
        assert payload["variables"] and payload["edges"]
        for token in ("neighborhood", "mouseenter", "tinted"):
            assert token in widget._esm, token


class TestJsMath:
    """The pure DOM-free JS helpers, exercised via node (skipped when
    node is unavailable, like the parcoords brush-math test)."""

    @pytest.fixture()
    def node(self):
        path = shutil.which("node")
        if path is None:
            pytest.skip("node not available")
        return path

    def test_n2_math(self, node, tmp_path):
        module = tmp_path / "n2_math.mjs"
        module.write_text(structure._N2_MATH_JS + "\nexport { isFeedback, related };\n")
        script = tmp_path / "test.mjs"
        script.write_text(f"""
import {{ isFeedback, related }} from {json.dumps(str(module))};
import assert from "node:assert/strict";
assert.equal(isFeedback(2, 1), false);  // below diagonal: feed-forward
assert.equal(isFeedback(1, 2), true);   // above diagonal: feedback
const cells = [{{row: 1, col: 0}}, {{row: 2, col: 0}}, {{row: 2, col: 1}},
               {{row: 5, col: 4}}];
assert.deepEqual(related(cells, 0), [1]);  // shares col 0
assert.deepEqual(related(cells, 2), [1]);  // shares row 2
assert.deepEqual(related(cells, 3), []);
console.log("node n2 math ok");
""")
        out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert "node n2 math ok" in out.stdout

    def test_network_math(self, node, tmp_path):
        module = tmp_path / "net_math.mjs"
        module.write_text(structure._NET_MATH_JS + "\nexport { neighborhood };\n")
        script = tmp_path / "test.mjs"
        script.write_text(f"""
import {{ neighborhood }} from {json.dumps(str(module))};
import assert from "node:assert/strict";
const edges = [[0, 0], [0, 1], [1, 1], [2, 0]];
assert.deepEqual(neighborhood(edges, 0, 0),
                 {{ edges: [0, 1], nodes: [0, 1] }});
assert.deepEqual(neighborhood(edges, 1, 1),
                 {{ edges: [1, 2], nodes: [0, 1] }});
assert.deepEqual(neighborhood(edges, 0, 3), {{ edges: [], nodes: [] }});
console.log("node net math ok");
""")
        out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=30)
        assert out.returncode == 0, out.stderr
        assert "node net math ok" in out.stdout
