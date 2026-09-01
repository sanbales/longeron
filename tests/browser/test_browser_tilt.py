"""Browser-truth: the tilt-rotor conversion slider drives the 3D scene.

The kernel-side tests (tests/test_tilt_tri.py, test_analysis_geometry)
prove the pivot chains and the swept-arc clearances headless.  What only
a browser can prove is the AFFORDANCE end to end: a genuine pointer drag
on the ``tilt deg`` slider re-bakes the scene through ``scene_for`` at
the commanded angle, and the tip pods and nose unit visibly stand up --
the same conversion the interference gate samples, driven the way a
human drives it.

Each stage saves a PNG under ``build/evidence/``.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from .conftest import REPO

pytestmark = pytest.mark.browser

NOTEBOOK = "tilt_scenario.ipynb"
EVIDENCE = REPO / "build" / "evidence"


def _drag_slider(lab: Any, description: str, fraction: float) -> None:
    """Drag the slider labeled ``description`` to a track fraction."""

    row = lab.page.locator(".widget-hslider").filter(has_text=description).first
    handle = row.locator(".noUi-handle").first
    track = row.locator(".noUi-base").first
    grip = handle.bounding_box()
    rail = track.bounding_box()
    assert grip is not None and rail is not None, f"slider {description!r} not visible"
    y = grip["y"] + grip["height"] / 2
    lab.page.mouse.move(grip["x"] + grip["width"] / 2, y)
    lab.page.mouse.down()
    lab.page.mouse.move(rail["x"] + rail["width"] * fraction, y, steps=12)
    lab.page.mouse.up()


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


def test_the_tilt_slider_drives_the_scene(lab: Any) -> None:
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=240)  # no diagram cell here: settle on quiet, not on sprotty
    lab.page.wait_for_selector(".longeron-viewer3d canvas", timeout=120_000)
    lab.page.wait_for_selector(".widget-hslider", timeout=60_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- baked state: hover attitude (tilt 90), scene == the 90-deg bake ----
    state = lab.run_cell_json(1)
    assert state["tilt"] == 90.0
    assert state["matches"] is True
    assert state["label"].endswith("tilt 90 deg")
    hover_y_min = state["prop_y_min"]
    lab.page.screenshot(path=str(EVIDENCE / "tilt_hover_90.png"), full_page=True)

    # -- drag the slider to cruise: the pods lie down, the scene re-bakes ---
    _drag_slider(lab, "tilt deg", 0.0)
    state = _poll_checker(lab, lambda s: s["tilt"] == 0.0)
    assert state["matches"] is True  # the slider value IS the baked scene
    assert state["label"].endswith("tilt 0 deg")
    # geometric truth that the meshes moved: the vertical cruise discs
    # reach a full radius below the chord plane, deeper than the level
    # hover discs hanging on their pivot arms
    assert state["prop_y_min"] < hover_y_min
    lab.page.screenshot(path=str(EVIDENCE / "tilt_cruise_0.png"), full_page=True)

    lab.assert_no_errors()
