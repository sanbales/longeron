"""Hash-seed determinism of the diagram outputs, and a tripwire for ipyelk #262.

ipyelk 3.0.0 (the version that ``pixi.lock`` pins) rebuilds a ``cssClasses``
string from a Python set in ``BaseElement.add_class`` and
``BaseElement.remove_class``.  Its ``VisibilityPipe`` calls ``remove_class`` on
every port and edge in each projection, that is, in each pass of the ipyelk
pipeline over the user's tree.  The class order on the tree therefore follows
the hash seed (``PYTHONHASHSEED``).  The upstream report is
https://github.com/jupyrdf/ipyelk/issues/262.

The tests here prove that longeron's own outputs do not follow the hash seed:

- each output is byte-identical in subprocesses that run with different hash seeds;
- each output stays byte-identical when the classes on the tree change order;
- the tripwire fails when the installed ipyelk stops reordering classes.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("ipyelk")
if shutil.which("node") is None:
    pytest.skip("node executable not available", allow_module_level=True)

import longeron
from longeron import diagrams, render

TESTS = Path(__file__).parent

#: 0, the seed of the CI failure (1075), and two more seeds at which the
#: drawn-ports classes change order in both refreshes of the fixpoint test
SEEDS = (0, 1075, 12, 154)

#: one subprocess per hash seed: the drawn-ports fixpoint scenario of
#: tests/test_render.py and every output that carries the classes or depends on them
_OUTPUTS = r"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, sys.argv[1])

import longeron
from ipyelk.elements.serialization import to_json
from longeron import diagrams, render
from test_render import TestBrowserPipelineFixpoint as Fixpoint

model = longeron.loads(Fixpoint._DRAWN_PORTS)
widget = diagrams.structure_diagram(model)
out = {
    "tree.built": json.dumps(to_json(widget.source.value, None), sort_keys=True),
    "svg.model": render.to_svg(model.member_named("Ports")),
}
try:
    from fastapi.testclient import TestClient
except ImportError:  # the server extra is optional
    out["svg.served"] = "fastapi not installed"
else:
    from longeron.server import create_app

    with tempfile.TemporaryDirectory() as work:
        (Path(work) / "ports.sysml").write_text(Fixpoint._DRAWN_PORTS, encoding="utf-8")
        response = TestClient(create_app(work)).get("/x/render/Ports.svg")
        out["svg.served"] = f"{response.status_code} {response.text}"
for cycle in ("cycle1", "cycle2"):
    if cycle == "cycle2":
        widget.source.flow = ("node.layoutOptions",)  # a routing-style refresh
    Fixpoint._run_cycle(widget)
    out[f"geometry.{cycle}"] = Fixpoint._geometry(widget)
    out[f"elk_json.{cycle}"] = json.dumps(render._to_elk_json(widget.source.value))
    out[f"svg.{cycle}"] = render.to_svg(widget)
    out[f"classes.{cycle}"] = json.dumps(Fixpoint._class_lists(widget))
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def outputs_by_seed():
    outputs = {}
    for seed in SEEDS:
        result = subprocess.run(
            [sys.executable, "-c", _OUTPUTS, str(TESTS)],
            env={**os.environ, "PYTHONHASHSEED": str(seed)},
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stderr
        outputs[seed] = json.loads(result.stdout.splitlines()[-1])
    return outputs


class TestHashSeedDeterminism:
    def test_relayout_is_a_fixpoint_at_every_seed(self, outputs_by_seed):
        for seed, out in outputs_by_seed.items():
            assert out["geometry.cycle2"] == out["geometry.cycle1"], seed

    @pytest.mark.parametrize(
        "output",
        [
            "tree.built",
            "svg.model",
            "svg.served",
            "geometry.cycle1",
            "geometry.cycle2",
            "elk_json.cycle1",
            "elk_json.cycle2",
            "svg.cycle1",
            "svg.cycle2",
        ],
    )
    def test_output_is_byte_identical_across_seeds(self, outputs_by_seed, output):
        """Each output that longeron makes has the same bytes at each hash seed.

        The tree that longeron builds is the same at each seed.  After ipyelk
        projects it, only the class order changes, and no output shows it.
        """

        reference = outputs_by_seed[SEEDS[0]][output]
        for seed in SEEDS[1:]:
            assert outputs_by_seed[seed][output] == reference, (output, seed)

    @pytest.mark.parametrize("cycle", ["cycle1", "cycle2"])
    def test_seeds_change_only_the_class_order(self, outputs_by_seed, cycle):
        """Each element has the same classes at each seed.  Only their order may differ."""

        def class_sets(out):
            return {
                element: sorted(classes)
                for element, classes in json.loads(out[f"classes.{cycle}"]).items()
            }

        reference = class_sets(outputs_by_seed[SEEDS[0]])
        for seed in SEEDS[1:]:
            assert class_sets(outputs_by_seed[seed]) == reference, seed


def _elements(element):
    yield element
    for key in ("children", "ports", "labels", "edges"):
        for sub in getattr(element, key, None) or []:
            yield from _elements(sub)


@pytest.mark.parametrize("order", ["reversed", "rotated"])
def test_outputs_ignore_the_class_order(order):
    """Reorder every multi-class list on a projected tree: the outputs keep their bytes.

    This check does not depend on the hash seed.  The reversed and the rotated
    orders together reach every order of a list of three classes.
    """

    from test_render import TestBrowserPipelineFixpoint as Fixpoint

    widget = diagrams.structure_diagram(longeron.loads(Fixpoint._DRAWN_PORTS))
    Fixpoint._run_cycle(widget)
    root = widget.source.value
    elk_json, svg = json.dumps(render._to_elk_json(root)), render.to_svg(widget)

    moved = 0
    for element in _elements(root):
        classes = (element.properties.cssClasses or "").split()
        if len(classes) > 1:
            classes = classes[::-1] if order == "reversed" else classes[1:] + classes[:1]
            element.properties.cssClasses = " ".join(classes)
            moved += 1
    assert moved >= 3  # the three drawn ports at least

    assert json.dumps(render._to_elk_json(root)) == elk_json
    assert render.to_svg(widget) == svg


#: the class lists that the tripwire reorders: the port classes of the CI failure,
#: then 64 synthetic lists so that some list changes order at any hash seed
_REMOVE_CLASS = r"""
from ipyelk.elements import Port, PortProperties
from ipyelk.elements.elements import BaseElement

lists = [["sysml-adornment", "sysml-port", "sysml-port-in"]]
lists += [[f"a{index}", f"b{index}", f"c{index}"] for index in range(64)]
moved = 0
for classes in lists:
    port = Port(properties=PortProperties(cssClasses=" ".join(classes)))
    BaseElement.remove_class(port, "slack-port")  # what VisIndex.clear_slack does
    moved += port.properties.cssClasses.split() != classes
print(moved)
"""


def test_ipyelk_remove_class_still_reorders_classes():
    """Tripwire for https://github.com/jupyrdf/ipyelk/issues/262 (ipyelk 3.0.0 in ``pixi.lock``).

    The test calls ``BaseElement.remove_class`` with a class that the element does
    not have, as ``VisIndex.clear_slack`` does.  In ipyelk 3.0.0, the call changes
    the order of the remaining classes at ``PYTHONHASHSEED=1075``.  If no list
    changes order, the installed ipyelk keeps the order, and the test reports what
    to remove.
    """

    result = subprocess.run(
        [sys.executable, "-c", _REMOVE_CLASS],
        env={**os.environ, "PYTHONHASHSEED": "1075"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert int(result.stdout) > 0, (
        "ipyelk #262 is fixed in the installed ipyelk: drop the class_sets shortcut "
        "in tests/test_render.py and this tripwire"
    )
