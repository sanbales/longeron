"""Browser-truth: the mission dashboard on one 1080p screen.

The kernel-side tests (tests/test_analysis_dashboard.py) prove the pareto
mask, the tab structure, and the traitlet wiring.  What only a browser can
prove is the layout contract and the front-end round trip:

* the whole dashboard renders inside a 1920x950 content area, so a 1080p
  screen shows everything without vertical scrolling;
* clicking the ``Pareto only`` ToggleButton reaches the kernel and prunes
  the candidate pool in place;
* hovering a lineup card shows its front justification and traces that
  candidate's line in the parallel coordinates (the projection defect:
  a front pick can look dominated in the cost-MOE plane);
* the missions render as ONE tab set whose tabs actually switch;
* dragging a priority slider re-ranks the 3D lineup that sits BESIDE it.

Each stage saves a PNG under ``build/evidence/`` -- the review artifacts
for the T4 dashboard rework.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from .conftest import _PHASE_REPORTS, ARTIFACTS, REPO, LabPage, _shutdown_sessions

EVIDENCE = REPO / "build" / "evidence"


@pytest.fixture()
def lab1080(browser: Any, lab_server: Any, request: pytest.FixtureRequest) -> Any:
    """A 1920x1080 page: the fit contract is stated at 1080p exactly."""

    page = browser.new_page(viewport={"width": 1920, "height": 1080})
    driver = LabPage(page, lab_server)
    yield driver
    try:
        reports = request.node.stash.get(_PHASE_REPORTS, {})
        if any(report.failed for report in reports.values()):
            driver.save_artifacts(ARTIFACTS, request.node.name)
    finally:
        page.close()
        _shutdown_sessions(lab_server)


def _drag_slider(lab: Any, description: str, fraction: float) -> None:
    """Drag the priority slider labeled ``description`` to a track fraction."""

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


def test_dashboard_fits_1080p_and_links_every_view(lab1080: Any) -> None:
    lab = lab1080
    lab.open_notebook("dashboard_scenario.ipynb")
    lab.run_all()
    # settle counts elk diagrams; the dashboard is plain ipywidgets, so
    # settle on "nothing busy" and then wait for the widget DOM itself
    lab.wait_settled(timeout=420)
    lab.page.wait_for_selector(".jp-OutputArea .widget-vbox", timeout=120_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- baked state: 288 candidates, one tab set, toggle off ---------------
    state = lab.run_cell_json(1)
    assert state["candidates"] == 288
    assert state["tabs"] == ["all missions", "ISR", "logistics", "intercept"]
    assert state["toggle"] is False
    assert state["pool"] == 288
    assert 0 < state["front"] < 288

    # -- (1) the whole dashboard fits a 1080p content area ------------------
    root = lab.page.locator(".jp-OutputArea .widget-vbox").first
    root.evaluate("el => el.scrollIntoView({block: 'start'})")  # no stability wait
    lab.page.wait_for_timeout(1500)
    box = root.bounding_box()
    assert box is not None
    assert box["width"] <= 1880, f"dashboard too wide for 1920: {box}"
    assert box["height"] <= 950, f"dashboard needs vertical scrolling: {box}"
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_full_1920x1080.png"))

    # -- (2) the Pareto toggle prunes the pool, then restores it ------------
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_pareto_off.png"))
    toggle = lab.page.get_by_role("button", name="Pareto only")
    toggle.click()
    state = _poll_checker(lab, lambda s: s["toggle"] is True)
    assert state["pool"] == state["front"] < 288
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_pareto_on.png"))

    # -- (2b) the reported scenario: 'Pareto only' at N=8 shows picks that
    # LOOK dominated in the scatter; their lineup cards must say where
    # each earns its front membership, and hovering a card must trace
    # that candidate's line in the parallel coordinates.  The lineup-N
    # readout is contenteditable: type 8 (one kernel update; dragging the
    # short header track fires a recompute storm and is gesture-flaky)
    row = lab.page.locator(".widget-hslider").filter(has_text="lineup N").first
    readout = row.locator(".widget-readout").first
    readout.click()
    readout.fill("8")
    readout.press("Enter")
    state = _poll_checker(lab, lambda s: s["picks"] == 8)
    card = lab.page.locator(".longeron-lineup-card", has_text="tops every pick").first
    card.scroll_into_view_if_needed()
    card.hover()
    lab.page.wait_for_selector(".longeron-pc-line.hover", timeout=15_000)
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_lineup_justification.png"))

    toggle.click()
    state = _poll_checker(lab, lambda s: s["toggle"] is False)
    assert state["pool"] == 288

    # -- (3) the mission tabs switch: ISR shows its floors and card ---------
    lab.page.locator(".jp-OutputArea .lm-TabBar-tab", has_text="ISR").first.click()
    lab.page.wait_for_selector("text=stationMinutes >=", timeout=15_000)
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_tab_isr.png"))
    lab.page.locator(".jp-OutputArea .lm-TabBar-tab", has_text="all missions").first.click()
    lab.page.wait_for_selector("text=best compromise", timeout=15_000)

    # -- (4) priority sliders re-rank the 3D lineup sitting beside them -----
    _drag_slider(lab, "intercept", 1.05)  # past the right end -> 100
    _drag_slider(lab, "ISR", -0.05)  # past the left end -> 0
    _drag_slider(lab, "logistics", -0.05)
    state = _poll_checker(lab, lambda s: s["top"] == "dartInterceptor")
    assert state["picks"] >= 1
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_intercept_priority.png"))

    lab.assert_no_errors()
