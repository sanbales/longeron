"""Browser-truth: the config-keyed 3D pane (``link.bind_config_view``).

The kernel-side tests (tests/test_analysis_link.py, test_grand_tour.py)
prove the dispatch table and the traitlets wiring headless.  What only a
browser can prove is the seam end to end through the REAL rendered
surfaces: a genuine pointer click on a sprotty diagram node driving the
three.js canvas beside it -- and a genuine raycast pick on the canvas
driving the diagram back.  The maintainer's asks, verbatim: click the
``TeardropQuad`` and the teardrop shell renders; click ``HexaCopter``
and the six-disc hexa renders; and the equipment "as elements in the
model so they are clickable" -- click the battery in the 3D scene and
the BATTERY element is what gets selected.

Each stage saves a PNG under ``build/evidence/``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from .conftest import REPO, scroll_into_view

pytestmark = pytest.mark.browser

NOTEBOOK = "config_view_scenario.ipynb"
EVIDENCE = REPO / "build" / "evidence"


def _poll_checker(lab: Any, predicate: Any, timeout: float = 60.0) -> dict[str, Any]:
    """Re-run the checker cell until the kernel state satisfies ``predicate``."""

    deadline = time.monotonic() + timeout
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = lab.run_cell_json(1)
        if predicate(state):
            return state
        time.sleep(1.0)
    raise TimeoutError(f"checker never satisfied the predicate; last state: {state}")


def _click_node(lab: Any, label: str, fit_cell: int) -> None:
    """Zoom onto the craft (the fit-tool affordance), then click its label.

    The grown Rotorcraft package fits the pane below the label LOD
    threshold (the sprotty view culls a label when ``zoom * height <=
    3``), so the whole-package view renders NO text to click.  The
    scenario's fit driver cell zooms the view onto the target craft
    first -- what a human does with the toolbar's fit button.
    """

    assert "fitted" in lab.run_cell(fit_cell)
    target = lab.page.locator(f'.sprotty text.elklabel:text-is("{label}")').first
    scroll_into_view(target)
    target.click()


def test_clicking_a_craft_renders_that_craft(lab: Any) -> None:
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=240)
    lab.page.wait_for_selector(".longeron-viewer3d canvas", timeout=120_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- baked state: the quad's own M0 population, four discs --------------
    state = lab.run_cell_json(1)
    assert state["current"] == "Rotorcraft::QuadCopter"
    assert state["discs"] == 4
    lab.page.screenshot(path=str(EVIDENCE / "cfg3d_home_quad.png"), full_page=True)

    # -- click TeardropQuad: the fleet shell replaces the quad --------------
    _click_node(lab, "TeardropQuad", fit_cell=2)
    state = _poll_checker(lab, lambda s: s["current"] == "Rotorcraft::TeardropQuad")
    # the shell carries the craft identity; the clickable internals
    # (battery / flight controller / camera) carry their own elements
    assert state["keys"] == [
        "Rotorcraft::TeardropQuad",
        "Rotorcraft::TeardropQuad::battery",
        "Rotorcraft::TeardropQuad::camera",
        "Rotorcraft::TeardropQuad::flightController",
    ]
    assert state["discs"] == 0  # a shell render carries no analytic discs
    assert state["label"] == "Rotorcraft::TeardropQuad"
    lab.page.screenshot(path=str(EVIDENCE / "cfg3d_click_teardropquad.png"), full_page=True)

    # -- click HexaCopter: the six-arm build bakes from its population ------
    _click_node(lab, "HexaCopter", fit_cell=3)
    state = _poll_checker(lab, lambda s: s["current"] == "Rotorcraft::HexaCopter")
    assert state["discs"] == 6
    assert any(key.startswith("Rotorcraft::HexaCopter#0") for key in state["keys"])
    lab.page.screenshot(path=str(EVIDENCE / "cfg3d_click_hexacopter.png"), full_page=True)

    lab.assert_no_errors()


def test_clicking_the_battery_selects_the_battery(lab: Any) -> None:
    """The clickable-internals round trip, browser-truth: a raycast pick
    on the teardrop's indigo battery sleeve selects the shell's OWN
    ``battery`` part usage in the diagram (and the selection drives the
    highlight back onto the battery mesh)."""

    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=240)
    lab.page.wait_for_selector(".longeron-viewer3d canvas", timeout=120_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # show the teardrop shell: its battery is the proud indigo sleeve
    # around the hull -- a raycast target a pointer can genuinely hit
    _click_node(lab, "TeardropQuad", fit_cell=2)
    _poll_checker(lab, lambda s: s["current"] == "Rotorcraft::TeardropQuad")

    canvas = lab.page.locator(".longeron-viewer3d canvas").first
    scroll_into_view(canvas)
    stage = canvas.bounding_box()
    assert stage is not None
    battery_key = "Rotorcraft::TeardropQuad::battery"
    lab.page.screenshot(path=str(EVIDENCE / "cfg3d_battery_before.png"), full_page=True)

    # probe down the hull's centreline (the sleeve rides the upper
    # third), then widen: the first pick that lands on the sleeve wins
    probe_points = [(0.5, fy / 100.0) for fy in range(28, 52, 3)]
    probe_points += [(fx / 100.0, fy / 100.0) for fy in range(24, 60, 6) for fx in range(42, 59, 4)]
    state: dict[str, Any] = {}
    for fx, fy in probe_points:
        lab.page.mouse.click(stage["x"] + fx * stage["width"], stage["y"] + fy * stage["height"])
        try:
            state = _poll_checker(lab, lambda s: s["selection"] == [battery_key], timeout=6.0)
            break
        except TimeoutError:
            continue
    assert state.get("selection") == [battery_key], "no probe point hit the battery sleeve"
    # the selection drives the highlight back onto the battery mesh
    assert state["highlight"] == [battery_key]
    lab.page.screenshot(path=str(EVIDENCE / "cfg3d_battery_selected.png"), full_page=True)

    lab.assert_no_errors()
