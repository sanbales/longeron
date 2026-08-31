"""Browser-truth: the mission dashboard on one 1080p screen.

The kernel-side tests (tests/test_analysis_dashboard.py) prove the pareto
mask, the tab structure, the state-matrix invariant, and the traitlet
wiring.  What only a browser can prove is the layout contract and the
front-end round trip:

* the whole dashboard renders inside a 1920x950 content area AND fills
  the available output width (the fluid layout), so a 1080p screen shows
  everything without vertical scrolling;
* the lineup-N slider keeps a usable track in the header strip;
* clicking the ``Pareto only`` ToggleButton reaches the kernel and prunes
  the candidate pool in place;
* hovering a lineup card shows its front justification and traces that
  candidate's line in the parallel coordinates (the projection defect:
  a front pick can look dominated in the cost-MOE plane);
* with the toggle pressed EVERY scatter point wears the front ink --
  filled staircase members plus open hidden-axis rings, zero dominated
  gray -- the in-plot legend and the toggle-side hint say so, and
  releasing the toggle returns gray only on truly dominated points;
* a BRUSH gesture on a parcoords axis syncs its interval to the kernel,
  and a card selected while brushing stays visible: the selection violet
  is distinct from the brush blue, on the card border, the traced
  parcoords line, and the scatter halo at once;
* clicking a 3D model in the lineup selects its card (and the background
  clears the selection) -- the reverse direction of the selection seam;
* the missions render as ONE tab set whose tabs actually switch;
* dragging a priority slider re-ranks the 3D lineup that sits BESIDE it.

The TALL-HOST test proves the resizable-sections contract (the
maintainer's whitespace report: Create-New-View-for-Output docked the
dashboard in a tall panel and the fixed row budget left dead space):

* inline in the notebook the one-screen floor still stands;
* docked via ``Create New View for Output`` the dashboard grows to the
  host's height -- no dead space below -- and every plot re-renders to
  its new box (svg heights track their containers, the 3D canvas fills
  the viewer);
* dragging the rows gutter re-balances the plot/control rows, the moved
  ratio round-trips to the kernel trait, and double-click restores the
  design ratio.

Each stage saves a PNG under ``build/evidence/`` -- the review artifacts
for the T4 dashboard polish.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from .conftest import REPO, _lab_page, scroll_into_view

EVIDENCE = REPO / "build" / "evidence"


@pytest.fixture()
def lab1080(browser: Any, lab_server: Any, request: pytest.FixtureRequest) -> Any:
    """A 1920x1080 page: the fit contract is stated at 1080p exactly."""

    yield from _lab_page(browser, lab_server, request, {"width": 1920, "height": 1080})


@pytest.fixture()
def labtall(browser: Any, lab_server: Any, request: pytest.FixtureRequest) -> Any:
    """A 1200x1900 portrait-ish page: the tall-host fill contract."""

    yield from _lab_page(browser, lab_server, request, {"width": 1200, "height": 1900})


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


def _poll_count(lab: Any, selector: str, expect: int, timeout: float = 30.0) -> None:
    """Wait until ``selector`` matches exactly ``expect`` DOM nodes."""

    deadline = time.monotonic() + timeout
    count = -1
    while time.monotonic() < deadline:
        count = lab.page.locator(selector).count()
        if count == expect:
            return
        time.sleep(0.5)
    raise TimeoutError(f"{selector!r}: expected {expect} nodes, last saw {count}")


def test_dashboard_fits_1080p_and_links_every_view(lab1080: Any) -> None:
    lab = lab1080
    lab.open_notebook("dashboard_scenario.ipynb")
    lab.run_all()
    # settle counts elk diagrams; the dashboard is plain ipywidgets, so
    # settle on "nothing busy" and then wait for the widget DOM itself
    lab.wait_settled(timeout=420)
    lab.page.wait_for_selector(".jp-OutputArea .widget-vbox", timeout=120_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- baked state: 1600 crossed candidates, one tab set, toggle off ------
    state = lab.run_cell_json(1)
    assert state["candidates"] == 1600
    assert state["tabs"] == ["all missions", "ISR", "logistics", "intercept"]
    assert state["toggle"] is False
    assert state["pool"] == 1600
    assert 0 < state["front"] < 1600

    # -- (1) the whole dashboard fits a 1080p content area AND fills the
    # available output width (finding 3: no more fixed 1500 px on a wide
    # screen; the fluid rows stretch, the row heights hold the budget)
    root = lab.page.locator(".jp-OutputArea .widget-vbox").first
    root.evaluate("el => el.scrollIntoView({block: 'start'})")  # no stability wait
    lab.page.wait_for_timeout(1500)
    box = root.bounding_box()
    assert box is not None
    assert box["width"] <= 1880, f"dashboard too wide for 1920: {box}"
    assert box["height"] <= 950, f"dashboard needs vertical scrolling: {box}"
    host_w = root.evaluate("el => el.parentElement.clientWidth")
    assert box["width"] >= 0.95 * host_w, f"dashboard leaves width unused: {box} vs {host_w}"
    assert box["width"] >= 1450, f"fluid layout narrower than the old fixed one: {box}"
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_full_1920x1080.png"))

    # -- (1b) the lineup-N slider keeps a usable track (finding 2) --------
    n_row = lab.page.locator(".widget-hslider").filter(has_text="lineup N").first
    n_track = n_row.locator(".slider-container").first.bounding_box()
    assert n_track is not None and n_track["width"] >= 200, f"lineup-N track: {n_track}"

    # -- (2) the Pareto toggle prunes the pool, then restores it ------------
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_pareto_off.png"))
    toggle = lab.page.get_by_role("button", name="Pareto only")
    toggle.click()
    state = _poll_checker(lab, lambda s: s["toggle"] is True)
    assert state["pool"] == state["front"] < 1600
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

    # -- (2c) THE third report: toggle ON means every drawn point IS
    # front, so NONE may wear the dominated gray -- filled accent for
    # the staircase members, open accent rings for the hidden-axis
    # members, the legend naming both, the hint beside the toggle
    # saying the state out loud (legend swatches carry .legend and are
    # excluded from the point counts)
    scatter_el = lab.page.locator(".longeron-moefront").first
    scroll_into_view(scatter_el)
    n_front = state["front"]
    _poll_count(lab, ".longeron-moefront-dot:not(.legend)", n_front)
    assert lab.page.locator(".longeron-moefront-dot.front:not(.legend)").count() == n_front
    filled = lab.page.locator(".longeron-moefront-dot.front.stair:not(.legend)").count()
    assert 0 < filled < n_front, f"marker kinds: {filled} of {n_front} filled"
    for words in (
        "front: leads this plane",
        "front: wins on hidden axes",
        "frontier in this plane only",
    ):
        assert lab.page.locator(".longeron-moefront-legend", has_text=words).count() == 1, words
    assert lab.page.locator(".longeron-moefront-legend", has_text="dominated").count() == 0
    lab.page.wait_for_selector("text=all shown are non-dominated (4 objectives)", timeout=15_000)
    scatter_el.screenshot(path=str(EVIDENCE / "t4_dashboard_front_ink_pareto_on.png"))

    card = lab.page.locator(".longeron-lineup-card", has_text="tops every pick").first
    scroll_into_view(card)
    card.hover()
    lab.page.wait_for_selector(".longeron-pc-line.hover", timeout=15_000)
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_lineup_justification.png"))

    toggle.click()
    # the toggle flag flips before the pool recount lands (a starved CI
    # runner exposed the gap): poll to the POSTCONDITION, not the flag
    state = _poll_checker(lab, lambda s: s["toggle"] is False and s["pool"] == 1600)
    assert state["pool"] == 1600

    # -- (2d) toggle OFF: gray returns, but ONLY on truly dominated
    # points -- the front keeps its ink in the full cloud, and the
    # legend now names the gray too; the hint is gone
    _poll_count(lab, ".longeron-moefront-dot:not(.legend)", 1600)
    assert lab.page.locator(".longeron-moefront-dot.front:not(.legend)").count() == state["front"]
    assert (
        lab.page.locator(
            ".longeron-moefront-legend", has_text="dominated: a better design exists"
        ).count()
        == 1
    )
    assert lab.page.locator("text=all shown are non-dominated").count() == 0
    scroll_into_view(scatter_el)
    scatter_el.screenshot(path=str(EVIDENCE / "t4_dashboard_front_ink_pareto_off.png"))

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
    _drag_slider(lab, "ISR", 0.52)  # weights back to neutral for stage 5
    _drag_slider(lab, "logistics", 0.52)
    _drag_slider(lab, "intercept", 0.52)

    # -- (5) brush + selection: the violet selection stays visible while
    # the blue brush is active (finding 4), across card, parcoords line,
    # and scatter halo at once (finding 5, forward direction)
    # anchor on the stable container: the svg child is REPLACED by
    # re-bakes, so a scroll on it races DOM detachment (seen twice at
    # landing); the container div survives every re-render
    holder = lab.page.locator(".longeron-parcoords").first
    scroll_into_view(holder)
    lab.page.wait_for_timeout(400)
    plot = lab.page.locator(".longeron-parcoords svg").first.bounding_box()
    assert plot is not None
    moe_x = plot["x"] + plot["width"] - 56  # the last axis (MOE), M.right = 56
    lab.page.mouse.move(moe_x, plot["y"] + 0.42 * plot["height"])
    lab.page.mouse.down()
    lab.page.mouse.move(moe_x, plot["y"] + 0.78 * plot["height"], steps=10)
    lab.page.mouse.up()
    state = _poll_checker(lab, lambda s: "MOE" in s["brushes"])
    card = lab.page.locator(".longeron-lineup-card").first
    scroll_into_view(card)
    card.click()
    state = _poll_checker(lab, lambda s: s["selected"] is not None)
    pinned = lab.page.locator(".longeron-lineup-card.pinned").first
    card_border = pinned.evaluate("el => getComputedStyle(el).borderTopColor")
    brush_stroke = lab.page.locator(".longeron-pc-brush").first.evaluate(
        "el => getComputedStyle(el).stroke"
    )
    assert card_border == "rgb(123, 79, 166)", card_border  # the selection violet
    assert brush_stroke == "rgb(47, 107, 143)", brush_stroke  # the brush blue
    assert card_border != brush_stroke
    assert lab.page.locator(".longeron-pc-line.selected").count() == 1
    assert lab.page.locator(".longeron-moefront-sel").count() == 1
    assert state["highlight"] == [f"cand:{state['selected']}"]  # 3D pops too
    assert state["traced"] >= 0
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_brush_plus_selection.png"))

    # -- (6) the reverse direction: clicking a 3D model selects its card,
    # a background click clears (finding 5)
    canvas = lab.page.locator(".longeron-viewer3d canvas").first
    scroll_into_view(canvas)
    stage = canvas.bounding_box()
    assert stage is not None
    lab.page.mouse.click(stage["x"] + 8, stage["y"] + 8)  # sky: clears
    state = _poll_checker(lab, lambda s: s["selected"] is None)
    assert lab.page.locator(".longeron-lineup-card.pinned").count() == 0
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_click3d_before.png"))
    # probe a denser grid: the lineup's top picks are now flying wings
    # (thin shells in plan view) after the catalog grew to 1600 -- the
    # old five probe points could all land in gaps between meshes
    probe_points = [(0.5, 0.58), (0.36, 0.6), (0.64, 0.6), (0.5, 0.45), (0.42, 0.68)]
    probe_points += [(fx / 100.0, fy / 100.0) for fy in range(35, 76, 8) for fx in range(28, 73, 6)]
    for fx, fy in probe_points:
        lab.page.mouse.click(stage["x"] + fx * stage["width"], stage["y"] + fy * stage["height"])
        try:
            state = _poll_checker(lab, lambda s: s["selected"] is not None, timeout=8.0)
            break
        except TimeoutError:
            continue
    assert state["selected"] is not None, "no 3D model hit at any probe point"
    pinned = lab.page.locator(".longeron-lineup-card.pinned").first
    assert state["selected_label"] in pinned.inner_text()
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_click3d_after.png"))
    lab.page.mouse.click(stage["x"] + 8, stage["y"] + 8)  # tidy: clear again
    _poll_checker(lab, lambda s: s["selected"] is None)

    lab.assert_no_errors()


def _poll_geometry(page: Any, measure: Any, predicate: Any, timeout: float = 30.0) -> Any:
    """Re-measure DOM geometry until the predicate holds (layout settles)."""

    deadline = time.monotonic() + timeout
    state = None
    while time.monotonic() < deadline:
        state = measure()
        if state is not None and predicate(state):
            return state
        page.wait_for_timeout(500)
    raise TimeoutError(f"geometry never satisfied the predicate; last: {state}")


def test_dashboard_fills_a_tall_host_and_gutters_resize(labtall: Any) -> None:
    """The whitespace report: a tall docked host must be FILLED, and the
    sections must be re-balanceable by dragging the gutters."""

    lab = labtall
    lab.open_notebook("dashboard_scenario.ipynb")
    lab.run_all()
    lab.wait_settled(timeout=420)
    lab.page.wait_for_selector(".jp-OutputArea .widget-vbox", timeout=120_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- inline reference: the notebook flow keeps its natural content
    # height (the 1080p no-scroll floor is the OTHER test's contract, at
    # its stated 1920 width; at 1200 the header blurb wraps taller) --
    # recorded so the docked growth below is provably growth, not reflow
    inline_root = lab.page.locator(".jp-OutputArea .widget-vbox").first
    inline_root.evaluate("el => el.scrollIntoView({block: 'start'})")
    lab.page.wait_for_timeout(1200)
    inline = inline_root.bounding_box()
    assert inline is not None

    # -- dock the dashboard output in its own tall panel (the reported
    # scenario: Lab's Create New View for Output) ---------------------------
    lab.page.evaluate(
        "() => { const app = window.jupyterapp || window.jupyterlab;"
        " const panel = [...app.shell.widgets('main')].find("
        "   (w) => w.content && w.content.model && w.content.model.cells);"
        " panel.content.activeCellIndex = 0;"  # the dashboard cell
        " void app.commands.execute('notebook:create-output-view');"
        " return true; }"
    )
    lab.page.wait_for_selector(".jp-LinkedOutputView .longeron-parcoords svg", timeout=120_000)
    host = lab.page.locator(".jp-LinkedOutputView").first

    # grow the docked panel: drag the horizontal dock handle upward so the
    # host is decisively taller than the ~850 px floor
    handles = lab.page.locator("#jp-main-dock-panel .lm-DockPanel-handle:not(.lm-mod-hidden)")
    hb = host.bounding_box()
    assert hb is not None
    for k in range(handles.count()):
        grip = handles.nth(k).bounding_box()
        if grip and grip["width"] > grip["height"] and abs(grip["y"] - hb["y"]) < 40:
            x, y = grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2
            lab.page.mouse.move(x, y)
            lab.page.mouse.down()
            lab.page.mouse.move(x, y - 520, steps=10)
            lab.page.mouse.up()
            break
    hb = host.bounding_box()
    assert hb is not None and hb["height"] >= 1100, f"tall host not tall: {hb}"

    # -- (1) HEIGHT ADAPTIVITY: the dashboard fills the host -- root height
    # ~== host height (small chrome allowance), zero dead space below,
    # and NO overflow (nothing to scroll)
    root = host.locator(".widget-vbox").first

    def _fill_state() -> dict[str, float] | None:
        hbox, rbox = host.bounding_box(), root.bounding_box()
        if hbox is None or rbox is None:
            return None
        return {
            "host": hbox["height"],
            "root": rbox["height"],
            "dead": (hbox["y"] + hbox["height"]) - (rbox["y"] + rbox["height"]),
            "top": rbox["y"] - hbox["y"],
        }

    fill = _poll_geometry(
        lab.page, _fill_state, lambda s: -6 <= s["dead"] <= 30 and s["root"] > 1000
    )
    assert fill["root"] >= inline["height"] + 80, f"no growth over the inline flow: {fill}"
    scroll = host.evaluate("el => el.scrollHeight - el.clientHeight")
    assert scroll <= 4, f"the filled host still scrolls by {scroll}px"

    # every plot re-rendered to its new box: the svg heights track their
    # containers (a stale 330 px draw would leave a visible gap), the 3D
    # canvas fills the viewer minus its caption strip
    def _plot_state() -> dict[str, float] | None:
        boxes = {}
        for name, sel in (
            ("pc", ".longeron-parcoords"),
            ("pcsvg", ".longeron-parcoords svg"),
            ("sc", ".longeron-moefront"),
            ("scsvg", ".longeron-moefront svg"),
            ("viewer", ".longeron-viewer3d"),
            ("canvas", ".longeron-viewer3d canvas"),
        ):
            b = host.locator(sel).first.bounding_box()
            if b is None:
                return None
            boxes[name] = b["height"]
        return boxes

    plots = _poll_geometry(
        lab.page,
        _plot_state,
        lambda s: (
            abs(s["pc"] - s["pcsvg"]) <= 8
            and abs(s["sc"] - s["scsvg"]) <= 8
            and s["pcsvg"] > 380
            and s["canvas"] >= s["viewer"] - 80  # minus the caption strip (it wraps)
        ),
    )
    assert plots["canvas"] > 450, f"3D canvas did not grow: {plots}"
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_tall_host_filled.png"))

    # -- (2) RESIZABLE SECTIONS: drag the rows gutter down -- the plot row
    # grows by the drag, the control row shrinks, both plots re-render ----
    gutter = host.locator(".longeron-gutter.y").first
    row_h = "el => el.previousElementSibling.getBoundingClientRect().height"
    before = float(gutter.evaluate(row_h))
    gb = gutter.bounding_box()
    assert gb is not None
    cx, cy = gb["x"] + gb["width"] / 2, gb["y"] + gb["height"] / 2
    lab.page.mouse.move(cx, cy)
    lab.page.mouse.down()
    lab.page.mouse.move(cx, cy + 160, steps=8)
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_gutter_mid_drag.png"))
    lab.page.mouse.up()
    after = float(gutter.evaluate(row_h))
    assert after - before >= 120, f"plot row did not follow the drag: {before} -> {after}"

    # the moved ratio round-trips to the kernel trait (persisted layout)
    state = _poll_checker(lab, lambda s: s["ratios"]["rows"] > s["ratio_defaults"]["rows"] + 0.03)
    # the plots re-rendered to the dragged boxes
    plots = _poll_geometry(
        lab.page,
        _plot_state,
        lambda s: abs(s["pc"] - s["pcsvg"]) <= 8 and s["pcsvg"] >= after - 12,
    )
    lab.page.screenshot(path=str(EVIDENCE / "t4_dashboard_gutter_after_drag.png"))

    # -- (3) double-click resets to the design ratio ------------------------
    gutter.dblclick()
    state = _poll_checker(
        lab, lambda s: abs(s["ratios"]["rows"] - s["ratio_defaults"]["rows"]) < 0.005
    )
    assert state["ratios"]["rows"] == state["ratio_defaults"]["rows"]
    _poll_geometry(lab.page, lambda: float(gutter.evaluate(row_h)), lambda h: abs(h - before) <= 25)

    lab.assert_no_errors()
