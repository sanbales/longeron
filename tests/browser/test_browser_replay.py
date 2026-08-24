"""Scenario 2: the state-machine replay widget animates in a real browser.

Deterministic driving: the checker cell prints the recorded timeline, the
test scrubs the range input to each fired transition's own time and
asserts the fired styling appears.  The arrowhead assertion is the
crbug-528196 regression fence: every fired edge path must reference a
marker that RESOLVES in the document, and must NOT carry
``vector-effect: non-scaling-stroke`` (Chromium skips painting markers on
such paths).
"""

import json

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "replay_scenario.ipynb"

_SEEK_JS = """(t) => {
    const root = document.querySelector('.longeron-replay');
    const scrub = root.querySelector('input[type=range]');
    scrub.value = String(t);
    scrub.dispatchEvent(new Event('input', {bubbles: true}));
    const edges = [...root.querySelectorAll('.longeron-fired path')].map((path) => {
        const markerEnd = getComputedStyle(path).markerEnd || '';
        const match = markerEnd.match(/#([^\\")]+)/);
        const id = match ? match[1] : null;
        return {
            marker: id,
            resolves: Boolean(id && document.getElementById(id)),
            vectorEffect: getComputedStyle(path).vectorEffect,
        };
    });
    return {
        fired: root.querySelectorAll('.longeron-fired').length,
        active: root.querySelectorAll('.longeron-active').length,
        edges,
    };
}"""

_MARKERS_JS = """() => {
    const root = document.querySelector('.longeron-replay');
    return [...root.querySelectorAll('[data-edge] path')].map((path) => {
        const attr = path.getAttribute('marker-end') || '';
        const match = attr.match(/#([^\\")]+)/);
        const id = match ? match[1] : null;
        return {marker: id, resolves: Boolean(id && document.getElementById(id))};
    });
}"""


def test_replay_fires_edges_with_resolving_arrowheads(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=180)
    lab.page.wait_for_selector(".longeron-replay svg", state="attached", timeout=60_000)

    timeline = json.loads(lab.cell_output(index=-1))
    fired = timeline["fired"]
    assert len(fired) >= 3, f"simulation recorded too few transitions: {timeline}"

    # every baked edge arrowhead must resolve to a marker in the document
    markers = lab.page.evaluate(_MARKERS_JS)
    assert markers, "no [data-edge] paths in the replay SVG"
    assert all(edge["resolves"] for edge in markers), markers

    # scrub the playhead onto each fired transition: the fired styling
    # (recolored stroke + swapped arrowhead marker) must appear
    for record in fired:
        state = lab.page.evaluate(_SEEK_JS, record["t"])
        assert state["fired"] >= 1, f"transition at t={record['t']} never lit up: {state}"
        assert state["active"] >= 1, f"no active state at t={record['t']}: {state}"
        for edge in state["edges"]:
            assert edge["resolves"], f"fired arrowhead does not resolve: {edge}"
            assert edge["vectorEffect"] != "non-scaling-stroke", edge

    lab.assert_no_errors()
