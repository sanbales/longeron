"""Browser-truth: the config-keyed 3D pane (``link.bind_config_view``).

The kernel-side tests (tests/test_analysis_link.py, test_grand_tour.py)
prove the dispatch table and the traitlets wiring headless.  What only a
browser can prove is the seam end to end through the REAL rendered
surfaces: a genuine pointer click on a sprotty diagram node driving the
three.js canvas beside it.  The maintainer's ask, verbatim: click the
``TeardropQuad`` and the teardrop shell renders; click ``HexaCopter``
and the six-disc hexa renders.

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


def _click_node(lab: Any, label: str) -> None:
    """Click the diagram node named ``label`` (via its name label)."""

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
    _click_node(lab, "TeardropQuad")
    state = _poll_checker(lab, lambda s: s["current"] == "Rotorcraft::TeardropQuad")
    assert state["keys"] == ["Rotorcraft::TeardropQuad"]  # whole-craft identity
    assert state["discs"] == 0  # a shell render carries no analytic discs
    assert state["label"] == "Rotorcraft::TeardropQuad"
    lab.page.screenshot(path=str(EVIDENCE / "cfg3d_click_teardropquad.png"), full_page=True)

    # -- click HexaCopter: the six-arm build bakes from its population ------
    _click_node(lab, "HexaCopter")
    state = _poll_checker(lab, lambda s: s["current"] == "Rotorcraft::HexaCopter")
    assert state["discs"] == 6
    assert any(key.startswith("Rotorcraft::HexaCopter#0") for key in state["keys"])
    lab.page.screenshot(path=str(EVIDENCE / "cfg3d_click_hexacopter.png"), full_page=True)

    lab.assert_no_errors()
