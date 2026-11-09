"""Browser-truth: the grand tour's selection hub (``grand.grand_dashboard``).

The kernel-side tests (tests/test_grand_tour.py) prove the subject
wiring headless: the tree, the diagram, the knobs and the mission
selector each write the subject, and every pane follows it.  What only a
browser can prove is the seam end to end through the REAL rendered
surfaces: a genuine click on a containment-tree row, on a sprotty
diagram label, on a dropdown, a slider and a toggle button, each
repainting the panes beside it.

The scenarios, each on a fresh kernel:

1. a tree row click changes the subject: the diagram repaints its
   selection and the 3D pane rebuilds its scene for the new craft;
2. a diagram click on a catalog craft reveals its tree row and changes
   the subject, while a build configuration only visits;
3. a knob change repaints the 3D pane (the battery dropdown) and
   re-scores the scoreboard (the station-time slider), and a span
   slider rebuilds the 3D scene and the Cesium model (scenario 3b);
4. the mission toggle to logistics shows the honest-absence card in the
   sizing strip and swaps the knob card;
5. row 1 shares its width: after the 240 px tree, the diagram, the 3D
   pane and the scoreboard take 2 : 1 : 1 of the rest, and the 3D pane
   and the scoreboard stay between 280 and 300 px wide.  The scenario
   measures the panes with the left sidebar open, collapsed, and on a
   1900 px page.  The 3D canvas and the scoreboard SVG fill their panes
   and do not hang below the row, one re-share costs the diagram one
   refit, and a click on the scaled SVG selects the clicked requirement.
6. the mission starts and ends on the drawn surface: at the first and
   the last instant of the Cesium clock, the drone model sits less than
   2 m above the globe under it (the track heights are above ground).
   A front-end that cannot load CesiumJS from the CDN skips this
   scenario.

6. the Cesium pane's onboard view: the kernel switches the view mode to
   ``'onboard'`` and seeks the playhead, and the Cesium camera sits on
   the drone and looks along the subject's declared camera at the
   slider angles.  A click on the stage's ``free`` button gives the
   camera back to the user.  Cesium loads from the pinned CDN, so an
   offline front-end SKIPS this scenario.

6. the *maximize* button fills the sizing strip's driver renderings:
   the history plot, the active flags of the table and the N2 matrix fit
   the width of the sizing card.  Each one is no taller than the card,
   so one scroll position of the card shows all of it.  The measurements go to
   ``build/evidence/grand_tour_sizing.json``.

7. ``dock()`` moves the tour into nine JupyterLab main-area panels with
   titled tabs, in the inline order: row 1, row 2, and the Cesium pane
   beside the notebook.  A drag of the split bar between the tree and
   the diagram widens one and narrows the other.  A drag of the 3D tab
   onto the tree pane moves the tab into the tree's tab bar.  A tree row
   click still changes the subject, and ``undock()`` closes the panels
   and shows the inline layout again.

Scenarios 1, 2, 4 and 6 collapse JupyterLab's left sidebar first.  At the
harness viewport (1500 px) the open file browser leaves the output area
about 1070 px wide, and the diagram then gets about 270 px.  Scenarios 3
and 4 also record the layout (row-1 pane widths, and whether a row-2
card's content is taller than the card) in
``build/evidence/grand_tour_layout_<state>.json``.  Those values are a
record.  Scenario 5 is the only one that asserts geometry.  Each stage
saves a PNG under ``build/evidence/``.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

import pytest

from .conftest import REPO, scroll_into_view

pytestmark = pytest.mark.browser

NOTEBOOK = "grand_tour_scenario.ipynb"
EVIDENCE = REPO / "build" / "evidence"
ISR_TASKING = "ScoutMissions::MissionRequirements::IsrTasking"
TWIN_VARIANT = "ScoutMissions::Catalog::AirframeChoice::flyingWingTwin"

#: count the 3D pane's scene rebuilds: the viewer's rebuild() is the only
#: code that writes the canvas aria-label, and a mutation record is queued
#: on every write, also when the text does not change
_ARM_REBUILDS_JS = """() => {
    const canvas = document.querySelector('.longeron-viewer3d canvas');
    if (!canvas) return false;
    window.__lgnRebuilds = 0;
    new MutationObserver((records) => { window.__lgnRebuilds += records.length; })
        .observe(canvas, {attributes: true, attributeFilter: ['aria-label']});
    return true;
}"""

#: row-1 pane boxes, and each row-2 card's content height against its own
#: height (a card scrolls vertically when its content is taller)
_LAYOUT_JS = """() => {
    const viewer = document.querySelector('.longeron-viewer3d');
    const row = viewer ? viewer.closest('.widget-hbox') : null;
    const names = ['tree', 'diagram', '3D', 'scoreboard'];
    const box = (el) => {
        const r = el.getBoundingClientRect();
        return {width: Math.round(r.width), height: Math.round(r.height)};
    };
    const output = viewer ? viewer.closest('.jp-OutputArea-output') : null;
    return {
        viewport: {width: window.innerWidth, height: window.innerHeight},
        output_width: output ? Math.round(output.getBoundingClientRect().width) : null,
        row1_width: row ? Math.round(row.getBoundingClientRect().width) : null,
        row1: row ? Object.fromEntries(
            [...row.children].map((el, i) => [names[i] || String(i), box(el)])) : null,
        cards: [...document.querySelectorAll('.lgn-grand-card')].map((card) => ({
            title: (card.firstElementChild ? card.firstElementChild.textContent : '')
                .trim().slice(0, 70),
            width: Math.round(card.getBoundingClientRect().width),
            client_height: card.clientHeight,
            scroll_height: card.scrollHeight,
            overflows: card.scrollHeight > card.clientHeight,
        })),
    };
}"""


def _poll_checker(
    lab: Any, predicate: Any, timeout: float = 60.0, *, cell: int = 1
) -> dict[str, Any]:
    """Re-run the checker cell until the kernel state satisfies ``predicate``."""

    deadline = time.monotonic() + timeout
    state: dict[str, Any] = {}
    while time.monotonic() < deadline:
        state = lab.run_cell_json(cell)
        if predicate(state):
            return state
        time.sleep(1.0)
    raise TimeoutError(f"checker never satisfied the predicate; last state: {state}")


#: JupyterLab's own "collapse the left area" (View > Show Left Sidebar off)
_COLLAPSE_LEFT_JS = """() => {
    (window.jupyterapp || window.jupyterlab).shell.collapseLeft();
    return true;
}"""


def _collapse_sidebar(lab: Any) -> None:
    assert lab.evaluate(_COLLAPSE_LEFT_JS, label="collapse the left sidebar")


def _open(lab: Any, *, collapse_sidebar: bool = True, notebook: str = NOTEBOOK) -> dict[str, Any]:
    """Run the scenario notebook; return the settled checker state."""

    lab.open_notebook(notebook)
    if collapse_sidebar:
        _collapse_sidebar(lab)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=300)
    lab.page.wait_for_selector(".longeron-viewer3d canvas", timeout=120_000)
    lab.page.wait_for_selector(".lgx-row", state="attached", timeout=60_000)
    lab.page.wait_for_selector(".lgn-sb-cell", state="attached", timeout=60_000)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    state = lab.run_cell_json(1)
    # the default subject: the ISR mission with its computed winner
    assert state["mission"] == "ISR", state
    assert state["craft"] == state["current"], state
    return state


#: the drone's height at the clock's start or stop.  ``track`` is the
#: CZML position height (above ground), ``model`` the height where Cesium
#: draws the model (the center of its bounding sphere, after the height
#: reference), and ``surface`` the globe height under the model.  Null
#: while the Cesium viewer or its data source is not there yet.
_ALTITUDE_JS = """async (at) => {
    const C = window.Cesium;
    const stage = document.querySelector('.longeron-mission3d-stage');
    const viewer = stage && stage.longeronViewer;
    const source = viewer && viewer.dataSources.length ? viewer.dataSources.get(0) : null;
    const drone = source && source.entities.getById('mission-drone');
    if (!drone) return null;
    const time = (at === 'stop' ? viewer.clock.stopTime : viewer.clock.startTime).clone();
    viewer.clock.currentTime = time;
    const sphere = new C.BoundingSphere();
    let done = false;
    for (let frame = 0; frame < 900 && !done; frame++) {
        viewer.scene.requestRender();
        await new Promise((resolve) => requestAnimationFrame(resolve));
        done = viewer.scene.globe.tilesLoaded && viewer.dataSourceDisplay
            .getBoundingSphere(drone, false, sphere) === C.BoundingSphereState.DONE;
    }
    if (!done) return {done};
    const drawn = C.Cartographic.fromCartesian(sphere.center);
    const surface = viewer.scene.globe.getHeight(drawn);
    return {
        done,
        seconds: C.JulianDate.secondsDifference(time, viewer.clock.startTime),
        track: C.Cartographic.fromCartesian(drone.position.getValue(time)).height,
        model: drawn.height,
        surface: surface === undefined ? null : surface,
    };
}"""


def _altitude(lab: Any, at: str) -> dict[str, Any]:
    """The drone's height record at the clock's ``start`` or ``stop``."""

    record = lab.evaluate(_ALTITUDE_JS, at, timeout=60.0, label=f"drone height at {at}")
    assert record and record["done"], f"the globe never settled at {at}: {record}"
    assert record["surface"] is not None, f"no globe height under the drone at {at}: {record}"
    return dict(record)


def _wait_for_cesium(lab: Any, timeout: float = 120.0) -> None:
    """The mission pane boots its Cesium viewer or shows the offline
    notice.  The offline notice is a skip, because the CDN is network."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = lab.evaluate(
            """() => ({
                cesium: Boolean(document.querySelector('.longeron-mission3d-stage')
                    ?.longeronViewer?.dataSources.length),
                offline: Boolean(document.querySelector('.longeron-mission3d-offline')),
            })""",
            label="the mission pane booted",
        )
        if found["cesium"]:
            return
        if found["offline"]:
            pytest.skip("CesiumJS CDN unreachable: the mission pane shows the offline notice")
        time.sleep(1.0)
    raise TimeoutError("the Cesium viewer never loaded the mission")


def _arm_rebuilds(lab: Any) -> None:
    assert lab.evaluate(_ARM_REBUILDS_JS, label="arm the 3D rebuild counter")


def _wait_rebuilt(lab: Any, label: str) -> None:
    lab.wait_until(
        lambda _s: (lab.evaluate("() => window.__lgnRebuilds || 0", label=label) or 0) >= 1,
        timeout=60,
        label=label,
    )


def _wait_caption(lab: Any, text: str) -> None:
    caption = lab.page.locator(".longeron-viewer3d-captions")
    lab.wait_until(
        lambda _s: text in (caption.first.text_content() or ""),
        timeout=60,
        label=f"3D caption names {text}",
    )


def _header(lab: Any) -> Any:
    return lab.page.locator(".widget-html", has_text="the grand tour").first


def _click_label(lab: Any, label: str, fit_cell: int) -> None:
    """Zoom onto the node (the fit-tool affordance), then click its label.

    The whole-program diagram fits the pane below the label LOD threshold
    (the sprotty view culls a label when ``zoom * height <= 3``), so the
    fit driver cell zooms onto the target first, as a human does with the
    toolbar's fit button.
    """

    assert "fitted" in lab.run_cell(fit_cell)
    target = lab.page.locator(f'.sprotty text.elklabel:text-is("{label}")').first
    target.wait_for(state="visible", timeout=60_000)
    scroll_into_view(target)
    target.click()


def _drag_slider(lab: Any, description: str, fraction: float) -> None:
    """Drag the slider labeled ``description`` to a track fraction."""

    row = lab.page.locator(".widget-hslider").filter(has_text=description).first
    scroll_into_view(row)
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


def _dropdown(lab: Any, description: str) -> Any:
    return (
        lab.page.locator(".widget-dropdown")
        .filter(has=lab.page.locator(f'label:text-is("{description}")'))
        .locator("select")
    )


def _record_layout(lab: Any, state: str) -> dict[str, Any]:
    layout = dict(lab.evaluate(_LAYOUT_JS, label=f"layout record ({state})"))
    path = EVIDENCE / f"grand_tour_layout_{state}.json"
    path.write_text(json.dumps(layout, indent=1), encoding="utf-8")
    return layout


def _cell_fill(lab: Any, qname: str) -> str | None:
    cell = lab.page.locator(f'.lgn-sb-cell[data-qname="{qname}"]').first
    return cell.get_attribute("fill") if cell.count() else None


def test_tree_row_click_changes_the_subject(lab: Any) -> None:
    """Tree -> diagram selection, 3D pane and header (scenario 1)."""

    state = _open(lab)
    assert state["airframe"] != "flyingWingTwin", state  # the click must change it
    _arm_rebuilds(lab)

    # the containment tree's own filter reveals the catalog variant row
    search = lab.page.locator(".lgx-tree-search").first
    scroll_into_view(search)
    search.fill("flyingWingTwin")
    row = lab.page.locator(f'.lgx-row[data-id="{TWIN_VARIANT}"]')
    row.first.wait_for(state="visible", timeout=60_000)
    row.first.click()

    state = _poll_checker(lab, lambda s: s["airframe"] == "flyingWingTwin")
    assert state["craft"] == "FlyingWings::FlyingWingTwin", state
    assert state["current"] == "FlyingWings::FlyingWingTwin", state
    assert state["diagram"] == [TWIN_VARIANT], state
    assert state["tree"] == [TWIN_VARIANT], state
    assert "flyingWingTwin" in state["header"], state
    # the browser repaints: the diagram selection, the 3D scene and its caption
    lab.wait_until(
        lambda _s: lab.page.locator(".sprotty .elknode.selected").count() >= 1,
        timeout=60,
        label="the diagram repainted its selection",
    )
    _wait_rebuilt(lab, "the 3D pane rebuilt its scene")
    _wait_caption(lab, "FlyingWings::FlyingWingTwin -- the ISR subject")
    assert "flyingWingTwin" in (_header(lab).text_content() or "")
    lab.page.screenshot(path=str(EVIDENCE / "grand_tree_click_twin.png"), full_page=True)

    lab.assert_no_errors()


def test_diagram_click_reveals_the_tree_row_and_a_build_only_visits(lab: Any) -> None:
    """Diagram -> tree reveal and subject; a build configuration visits (scenario 2)."""

    _open(lab)

    # -- a catalog craft: the subject changes and the tree reveals its row --
    _click_label(lab, "FlyingWingTwin", fit_cell=2)
    state = _poll_checker(lab, lambda s: s["airframe"] == "flyingWingTwin")
    assert state["craft"] == "FlyingWings::FlyingWingTwin", state
    assert state["tree"] == ["FlyingWings::FlyingWingTwin"], state
    selected = lab.page.locator('.lgx-row.lgx-selected[data-id="FlyingWings::FlyingWingTwin"]')
    selected.first.wait_for(state="visible", timeout=60_000)
    _wait_caption(lab, "FlyingWings::FlyingWingTwin -- the ISR subject")
    assert "visiting" not in (_header(lab).text_content() or "")
    lab.page.screenshot(path=str(EVIDENCE / "grand_diagram_click_twin.png"), full_page=True)

    # -- a build configuration: the pane shows it, the subject stays --------
    _click_label(lab, "QuadCopter", fit_cell=3)
    state = _poll_checker(lab, lambda s: s["current"] == "Rotorcraft::QuadCopter")
    assert state["airframe"] == "flyingWingTwin", state
    assert state["craft"] == "FlyingWings::FlyingWingTwin", state
    assert "visiting Rotorcraft::QuadCopter" in state["header"], state
    assert "The subject did not change" in state["header"], state
    lab.wait_until(
        lambda _s: "visiting Rotorcraft::QuadCopter" in (_header(lab).text_content() or ""),
        timeout=60,
        label="the header names the visiting craft",
    )
    _wait_caption(lab, "Rotorcraft::QuadCopter")
    lab.page.screenshot(path=str(EVIDENCE / "grand_diagram_click_quad.png"), full_page=True)

    lab.assert_no_errors()


def test_knob_changes_repaint_the_3d_pane_and_rescore_the_board(lab: Any) -> None:
    """Battery dropdown -> 3D scene; station-time slider -> scoreboard (scenario 3)."""

    # the harness page as it opens (file browser shown), then collapsed
    state = _open(lab, collapse_sidebar=False)
    narrow = _record_layout(lab, "ISR_sidebar_open")["row1"]["diagram"]["width"]
    _collapse_sidebar(lab)
    lab.wait_until(
        lambda _s: (
            lab.evaluate(_LAYOUT_JS, label="diagram widens")["row1"]["diagram"]["width"] > narrow
        ),
        timeout=60,
        label="the diagram widened after the sidebar collapsed",
    )
    _record_layout(lab, "ISR")
    battery = state["selection"]["battery"]
    assert battery != "tattu3s", state

    # -- the battery dropdown: the subject's mix changes, the scene rebakes --
    _arm_rebuilds(lab)
    select = _dropdown(lab, "battery").first
    scroll_into_view(select)
    select.select_option("tattu3s")
    state = _poll_checker(lab, lambda s: s["selection"]["battery"] == "tattu3s")
    assert state["airframe"] == "flyingWingSingle", state  # a dropdown keeps the airframe
    _wait_rebuilt(lab, "the 3D pane rebuilt the tattu3s scene")
    lab.page.screenshot(path=str(EVIDENCE / "grand_knob_battery.png"), full_page=True)

    # -- the station-time floor slider: the IsrTasking leaf re-scores -------
    before_score = state["scores"][ISR_TASKING]
    before_fill = _cell_fill(lab, ISR_TASKING)
    assert before_score == 1.0, state  # today's ISR winner holds station for 25 min
    assert before_fill is not None, "the scoreboard draws no IsrTasking cell"
    _drag_slider(lab, "minStationMinutes", 1.0)
    state = _poll_checker(lab, lambda s: s["overrides"].get("minStationMinutes", 0) >= 200)
    assert state["scores"][ISR_TASKING] < before_score, state
    lab.wait_until(
        lambda _s: _cell_fill(lab, ISR_TASKING) != before_fill,
        timeout=60,
        label="the IsrTasking cell repainted",
    )
    lab.page.screenshot(path=str(EVIDENCE / "grand_knob_station.png"), full_page=True)

    lab.assert_no_errors()


def test_span_slider_widens_the_3d_wing_and_the_flight(lab: Any) -> None:
    """The span slider rebuilds the 3D scene and the Cesium model (scenario 3b)."""

    state = _open(lab)
    assert state["airframe"] == "flyingWingSingle", state
    assert "airframe.wingSpan" in state["knobs"], state
    pane = lab.page.locator(".longeron-viewer3d").first
    scroll_into_view(pane)
    pane.screenshot(path=str(EVIDENCE / "grand_span_default.png"))
    _arm_rebuilds(lab)
    _drag_slider(lab, "wingSpan", 1.0)
    after = _poll_checker(lab, lambda s: s["overrides"].get("airframe.wingSpan", 0) >= 2.8)
    assert after["mesh"] != state["mesh"], after  # the subject mesh follows the what-if
    assert after["czml"] != state["czml"], after  # ... and so does the Cesium glTF
    _wait_rebuilt(lab, "the 3D pane rebuilt the wider wing")
    scroll_into_view(pane)
    pane.screenshot(path=str(EVIDENCE / "grand_span_max.png"))

    lab.assert_no_errors()


def test_mission_toggle_shows_absence_and_swaps_the_knobs(lab: Any) -> None:
    """ISR -> logistics: the honest-absence card and the cargo knob (scenario 4)."""

    state = _open(lab)
    assert "sensor" in state["knobs"] and "cargo" not in state["knobs"], state
    assert _dropdown(lab, "sensor").count() == 1

    toggle = lab.page.locator('button.widget-toggle-button:text-is("logistics")').first
    scroll_into_view(toggle)
    toggle.click()
    state = _poll_checker(lab, lambda s: s["mission"] == "logistics")
    assert "cargo" in state["knobs"] and "sensor" not in state["knobs"], state
    assert "no context for logistics" in state["sizing"], state
    absence = lab.page.locator(".lgn-grand-card", has_text="no sizing context for logistics")
    absence.first.wait_for(state="attached", timeout=60_000)
    lab.wait_until(
        lambda _s: _dropdown(lab, "cargo").count() == 1 and _dropdown(lab, "sensor").count() == 0,
        timeout=60,
        label="the knob card swapped sensor for cargo",
    )
    _record_layout(lab, "logistics")
    scroll_into_view(absence.first)
    lab.page.screenshot(path=str(EVIDENCE / "grand_mission_logistics.png"), full_page=True)

    lab.assert_no_errors()


#: row-1 pane widths, the 3D canvas and the scoreboard SVG against their
#: panes, and the SVG's scale (its rendered width over its viewBox width)
_PANES_JS = """() => {
    const viewer = document.querySelector('.longeron-viewer3d');
    const row = viewer.closest('.widget-hbox');
    const width = (el) => el ? el.getBoundingClientRect().width : null;
    const [tree, diagram, view, board] = [...row.children];
    const svg = board.querySelector('.lgn-sb-wrap svg');
    const bottom = (el) => Math.round(el.getBoundingClientRect().bottom);
    return {
        row: width(row), tree: width(tree), diagram: width(diagram),
        viewer: width(view), board: width(board),
        canvas: width(view.querySelector('canvas')), svg: width(svg),
        svg_scale: width(svg) / svg.viewBox.baseVal.width,
        // nothing of the side panes may hang below the row (it clips)
        overhang: Math.max(bottom(view.querySelector('.longeron-viewer3d-captions')),
                           bottom(svg)) - bottom(row),
    };
}"""

#: a screen point inside a scoreboard cell: the cell's vertex centroid (a
#: Voronoi cell is convex) in viewBox units, mapped to the screen through
#: the SVG's own transform, and the element the browser hit-tests there
_CELL_POINT_JS = """(qname) => {
    const path = document.querySelector(`.lgn-sb-cell[data-qname="${qname}"]`);
    if (!path) return null;
    const nums = (path.getAttribute('d').match(/-?[0-9.]+(?:e-?[0-9]+)?/g) || []).map(Number);
    let x = 0, y = 0;
    for (let i = 0; i + 1 < nums.length; i += 2) { x += nums[i]; y += nums[i + 1]; }
    const point = path.ownerSVGElement.createSVGPoint();
    point.x = x / (nums.length / 2);
    point.y = y / (nums.length / 2);
    const inside = path.isPointInFill(point);
    const screen = point.matrixTransform(path.getScreenCTM());
    return {x: screen.x, y: screen.y, inside,
            hit: document.elementFromPoint(screen.x, screen.y) === path};
}"""

#: the tree's width, and the bounds of the 3D pane and the scoreboard
#: (grand._TREE_PX, grand._PANE_MIN_PX, grand._PANE_MAX_PX)
_TREE, _SIDE_MIN, _SIDE_MAX = 240, 280, 300


def _panes(lab: Any) -> dict[str, float]:
    return dict(lab.evaluate(_PANES_JS, label="row-1 pane widths"))


def _assert_shares(panes: dict[str, float]) -> None:
    """Row 1 shares 2 : 1 : 1 after the tree, within the side panes' bounds."""

    rest = panes["row"] - _TREE
    side = min(_SIDE_MAX, max(_SIDE_MIN, rest / 4))
    assert abs(panes["tree"] - _TREE) <= 1, panes
    assert abs(panes["viewer"] - side) <= 2 and abs(panes["board"] - side) <= 2, panes
    assert abs(panes["diagram"] - (rest - 2 * side)) <= 3, panes
    # the panes follow their containers: the canvas and the SVG fill them
    assert abs(panes["canvas"] - panes["viewer"]) <= 2, panes
    assert abs(panes["svg"] - panes["board"]) <= 2, panes
    assert panes["overhang"] <= 0, panes


def _wait_panes(lab: Any, predicate: Any, label: str) -> dict[str, float]:
    lab.wait_until(lambda _s: predicate(_panes(lab)), timeout=60, label=label)
    return _panes(lab)


def test_row1_shares_its_width_and_the_panes_follow(lab: Any) -> None:
    """Sidebar open, collapsed, then a wide page: the shares and one refit (scenario 5)."""

    # -- the harness page as it opens: the file browser takes ~430 px -------
    _open(lab, collapse_sidebar=False)
    started = time.monotonic()
    narrow = _wait_panes(lab, lambda p: p["canvas"] <= p["viewer"] + 2, "3D canvas fits")
    _assert_shares(narrow)
    assert narrow["diagram"] >= 240, narrow  # never the 28 px of the fixed panes
    refits = _poll_checker(lab, lambda _s: True)["refits"]

    # -- collapsed: the diagram takes the freed width, the side panes keep 280
    _collapse_sidebar(lab)
    wide = _wait_panes(lab, lambda p: p["row"] > narrow["row"] + 100, "row 1 re-shared")
    wide = _wait_panes(lab, lambda p: abs(p["canvas"] - p["viewer"]) <= 2, "3D canvas follows")
    _assert_shares(wide)
    assert wide["diagram"] > narrow["diagram"] + 100, (narrow, wide)
    # one re-share is one AutoFit refit (the resize reporter debounces), not a loop
    after = _poll_checker(lab, lambda s: s["refits"] > refits, timeout=30)["refits"]
    time.sleep(3.0)
    assert _poll_checker(lab, lambda _s: True)["refits"] == after == refits + 1
    _record_layout(lab, "row1_collapsed")

    # -- a wide page: the side panes stop at their maximum, the SVG scales --
    lab.page.set_viewport_size({"width": 1900, "height": 1100})
    big = _wait_panes(lab, lambda p: p["board"] >= _SIDE_MAX - 1, "the side panes grew")
    big = _wait_panes(lab, lambda p: abs(p["canvas"] - p["viewer"]) <= 2, "3D canvas follows")
    _assert_shares(big)
    assert big["svg_scale"] > 1.05, big
    # a cell click on the scaled SVG still selects that requirement
    scroll_into_view(lab.page.locator(f'.lgn-sb-cell[data-qname="{ISR_TASKING}"]').first)
    point = lab.evaluate(_CELL_POINT_JS, ISR_TASKING, label="IsrTasking cell point")
    assert point and point["inside"] and point["hit"], point
    lab.page.mouse.click(point["x"], point["y"])
    state = _poll_checker(lab, lambda s: s["board"] == [ISR_TASKING])
    assert state["diagram"] == [ISR_TASKING], state
    selected = f'.lgn-sb-cell.lgn-sb-selected[data-qname="{ISR_TASKING}"]'
    lab.page.locator(selected).first.wait_for(state="attached", timeout=60_000)
    lab.page.screenshot(path=str(EVIDENCE / "grand_row1_wide.png"), full_page=True)
    record = {"open": narrow, "collapsed": wide, "wide_1900": big, "refits": [refits, after]}
    record["seconds"] = round(time.monotonic() - started, 1)
    (EVIDENCE / "grand_tour_row1_shares.json").write_text(json.dumps(record, indent=1))

    lab.assert_no_errors()


def test_the_mission_starts_and_ends_on_the_drawn_surface(lab: Any) -> None:
    """Takeoff and landing sit on the globe, not in the air (scenario 6)."""

    _open(lab)
    stage = lab.page.locator(".longeron-mission3d-stage").first
    scroll_into_view(stage)
    _wait_for_cesium(lab)
    takeoff = _altitude(lab, "start")
    stage.screenshot(path=str(EVIDENCE / "grand_mission_takeoff.png"))
    landing = _altitude(lab, "stop")
    (EVIDENCE / "grand_mission_heights.json").write_text(
        json.dumps({"takeoff": takeoff, "landing": landing}, indent=1)
    )
    for record in (takeoff, landing):
        assert abs(record["track"]) < 2.0, record  # the CZML height above ground
        assert abs(record["model"] - record["surface"]) < 2.0, record  # as drawn

    lab.assert_no_errors()


ONBOARD_NOTEBOOK = "grand_tour_onboard_scenario.ipynb"

#: the Cesium camera against the drone entity at the current clock time:
#: the distance between them, the camera angles in degrees, the field of
#: view, whether the user drives the camera, and the active mode button
_ONBOARD_JS = """() => {
    const stage = document.querySelector('.longeron-mission3d-stage');
    const viewer = stage && stage.longeronViewer;
    if (!viewer) return {
        cesium: false,
        offline: Boolean(document.querySelector('.longeron-mission3d-offline')),
    };
    const C = window.Cesium;
    const time = viewer.clock.currentTime;
    const source = viewer.dataSources.length ? viewer.dataSources.get(0) : null;
    const drone = source ? source.entities.getById('mission-drone') : null;
    const at = drone ? drone.position.getValue(time) : null;
    const camera = viewer.camera;
    return {
        cesium: true,
        seconds: C.JulianDate.secondsDifference(time, viewer.clock.startTime),
        offset_m: at ? C.Cartesian3.distance(camera.positionWC, at) : null,
        height_m: camera.positionCartographic.height,
        heading: C.Math.toDegrees(camera.heading),
        pitch: C.Math.toDegrees(camera.pitch),
        roll: C.Math.toDegrees(camera.roll),
        fov: C.Math.toDegrees(camera.frustum.fov),
        inputs: viewer.scene.screenSpaceCameraController.enableInputs,
        tracked: Boolean(viewer.trackedEntity),
        tiles: viewer.scene.globe.tilesLoaded,
        active: [...stage.querySelectorAll('.longeron-mission3d-modes button.active')]
            .map((button) => button.textContent),
    };
}"""

#: put the free camera 2.5 km above the drone, looking down
_PARK_JS = """() => {
    const viewer = document.querySelector('.longeron-mission3d-stage').longeronViewer;
    const C = window.Cesium;
    const drone = viewer.dataSources.get(0).entities.getById('mission-drone');
    const at = C.Cartographic.fromCartesian(drone.position.getValue(viewer.clock.currentTime));
    viewer.camera.setView({destination: C.Cartesian3.fromRadians(
        at.longitude, at.latitude, 2500.0)});
    viewer.scene.requestRender();
    return true;
}"""


def _expected_view(attitude: list[float], camera: dict[str, float]) -> tuple[float, float]:
    """The heading and pitch (degrees) of the declared boresight in the world.

    The craft frame is the one ``mission3d._attitude_quaternion`` bakes:
    nose along the heading at the pitch, roll about the nose with the
    right wing down.  Azimuth yaws the boresight left of the nose and
    elevation pitches it above the nose.
    """

    _t, heading, pitch, roll = (math.radians(v) for v in attitude)
    az, el = math.radians(camera["azimuth"]), math.radians(camera["elevation"])
    nose = (
        math.sin(heading) * math.cos(pitch),
        math.cos(heading) * math.cos(pitch),
        math.sin(pitch),
    )
    right = (math.cos(heading), -math.sin(heading), 0.0)
    top = (  # right x nose, then rolled toward right (right wing down)
        right[1] * nose[2] - right[2] * nose[1],
        right[2] * nose[0] - right[0] * nose[2],
        right[0] * nose[1] - right[1] * nose[0],
    )
    top = tuple(
        tp * math.cos(roll) + rt * math.sin(roll) for tp, rt in zip(top, right, strict=True)
    )
    left = (  # top x nose
        top[1] * nose[2] - top[2] * nose[1],
        top[2] * nose[0] - top[0] * nose[2],
        top[0] * nose[1] - top[1] * nose[0],
    )
    look = [
        math.cos(el) * math.cos(az) * n + math.cos(el) * math.sin(az) * lf + math.sin(el) * tp
        for n, lf, tp in zip(nose, left, top, strict=True)
    ]
    return math.degrees(math.atan2(look[0], look[1])) % 360.0, math.degrees(math.asin(look[2]))


def _angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _onboard(lab: Any, predicate: Any, label: str) -> dict[str, Any]:
    lab.wait_until(
        lambda _s: predicate(lab.evaluate(_ONBOARD_JS, label=label)), timeout=60, label=label
    )
    return dict(lab.evaluate(_ONBOARD_JS, label=label))


def _assert_onboard(
    view: dict[str, Any], state: dict[str, Any], record: list[dict[str, Any]]
) -> None:
    """The Cesium camera rides the drone along the declared boresight."""

    start, end = state["attitude"]
    assert start[1:] == end[1:], state  # the playhead sits on a held attitude
    heading, pitch = _expected_view(start, state["camera"])
    record.append({"kernel": state, "expected": [heading, pitch], "browser": view})
    assert view["offset_m"] < 3.0, view  # the placement offset, a few centimetres
    assert _angle_gap(view["heading"], heading) <= 2.0, (view, heading)
    assert abs(view["pitch"] - pitch) <= 2.0, (view, pitch)
    assert abs(view["fov"] - state["camera"]["fieldOfView"]) <= 0.01, view
    assert view["inputs"] is False and view["tracked"] is False, view
    assert view["active"] == ["onboard"], view


def _shoot_stage(lab: Any, name: str) -> None:
    """Save the Cesium stage once its imagery tiles load (a record, not asserted)."""

    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline and not lab.evaluate(_ONBOARD_JS, label="tiles")["tiles"]:
        time.sleep(0.5)
    stage = lab.page.locator(".longeron-mission3d-stage").first
    stage.screenshot(path=str(EVIDENCE / name))


def test_onboard_view_rides_the_declared_camera(lab: Any) -> None:
    """Kernel onboard switch -> the camera rides the drone; free -> the user's (scenario 6)."""

    _open(lab, notebook=ONBOARD_NOTEBOOK)
    record: list[dict[str, Any]] = []
    stage = lab.page.locator(".longeron-mission3d-stage").first
    scroll_into_view(stage)
    deadline = time.monotonic() + 120.0
    while not lab.evaluate(_ONBOARD_JS, label="cesium boots")["cesium"]:
        if lab.evaluate(_ONBOARD_JS, label="cesium boots").get("offline"):
            pytest.skip("CesiumJS CDN unreachable: the globe degraded to the offline notice")
        assert time.monotonic() < deadline, "the Cesium viewer never appeared"
        time.sleep(1.0)

    # -- the kernel switches to onboard at 60 s, the declared angles --------
    lab.run_cell(5)
    state = lab.run_cell_json(4)
    assert state["view_mode"] == "onboard" and state["time"] == 60.0, state
    assert state["camera"]["elevation"] == state["elevation"], state
    view = _onboard(lab, lambda v: abs(v["seconds"] - 60.0) < 1e-3, "the clock at 60 s")
    _assert_onboard(view, state, record)
    _shoot_stage(lab, "grand_onboard_60s.png")

    # -- a later playhead: the camera follows the drone onto the next leg ---
    lab.run_cell(6)
    state = lab.run_cell_json(4)
    view = _onboard(lab, lambda v: abs(v["seconds"] - 90.0) < 1e-3, "the clock at 90 s")
    _assert_onboard(view, state, record)
    _shoot_stage(lab, "grand_onboard_90s.png")

    # -- the camera what-if sliders turn the onboard view -------------------
    lab.run_cell(7)
    state = lab.run_cell_json(4)
    angles = (state["camera"]["elevation"], state["camera"]["azimuth"])
    assert angles == pytest.approx((30.0, 45.0)), state  # the slider snaps to its step
    view = _onboard(lab, lambda v: v["pitch"] > 20.0, "the onboard view tilted up")
    _assert_onboard(view, state, record)
    _shoot_stage(lab, "grand_onboard_90s_elevation30.png")
    lab.run_cell(8)
    state = lab.run_cell_json(4)
    view = _onboard(lab, lambda v: abs(v["pitch"]) < 5.0, "the onboard view on the horizon")
    _assert_onboard(view, state, record)
    _shoot_stage(lab, "grand_onboard_90s_elevation0.png")

    # -- the stage's free button: the user's camera, no tick lock -----------
    button = lab.page.locator('.longeron-mission3d-modes button:text-is("free")').first
    button.click()
    _poll_checker(lab, lambda s: s["view_mode"] == "free", cell=4)  # the click reached the kernel
    view = _onboard(lab, lambda v: v["inputs"] and v["active"] == ["free"], "free mode")
    assert view["tracked"] is False and abs(view["fov"] - 60.0) <= 0.01, view
    assert lab.evaluate(_PARK_JS, label="park the free camera")
    parked = _onboard(lab, lambda v: v["height_m"] > 2000.0, "the parked camera holds")
    assert parked["offset_m"] > 1000.0, parked  # no tick put it back on the drone
    record.append({"free": view, "parked": parked})
    (EVIDENCE / "grand_onboard_views.json").write_text(json.dumps(record, indent=1))

    lab.assert_no_errors()


#: the sizing card and its three driver renderings: each rendering's box
#: against the card's content box, and the card's scroll extents
_SIZING_JS = """() => {
    const card = [...document.querySelectorAll('.lgn-grand-card')]
        .find((el) => el.textContent.includes('OpenMDAO sizing'));
    if (!card) return null;
    const style = getComputedStyle(card);
    const inner = card.clientWidth - parseFloat(style.paddingLeft)
        - parseFloat(style.paddingRight);
    const box = (selector) => {
        const el = card.querySelector(selector);
        if (!el) return null;
        const r = el.closest('.widget-html').getBoundingClientRect();
        return {width: Math.round(r.width), height: Math.round(r.height)};
    };
    return {
        card: {width: Math.round(card.getBoundingClientRect().width), inner: Math.round(inner),
               client_width: card.clientWidth, scroll_width: card.scrollWidth,
               client_height: card.clientHeight, scroll_height: card.scrollHeight},
        history: box('svg[aria-label="driver iteration history"]'),
        table: box('table'),
        n2: box('svg[aria-label="N2 matrix"]'),
    };
}"""

#: the driver renderings: name -> the selector of an element inside each one
_RENDERINGS = {
    "history": 'svg[aria-label="driver iteration history"]',
    "table": "table",
    "n2": 'svg[aria-label="N2 matrix"]',
}


def test_maximize_draws_the_driver_history(lab: Any) -> None:
    """Maximize -> the history plot, the active flags, the N2 matrix (scenario 6)."""

    _open(lab)
    button = lab.page.locator('button:text-is("maximize station time")').first
    scroll_into_view(button)
    button.click()
    _poll_checker(lab, lambda s: s["loiter"] == 11.0)  # the stall floor binds
    history = lab.page.locator(_RENDERINGS["history"]).first
    history.wait_for(state="attached", timeout=60_000)

    sizing = dict(lab.evaluate(_SIZING_JS, label="the sizing card renderings"))
    (EVIDENCE / "grand_tour_sizing.json").write_text(json.dumps(sizing, indent=1))
    card = sizing["card"]
    assert card["scroll_width"] <= card["client_width"], sizing  # nothing clips in x
    for name in _RENDERINGS:
        assert sizing[name] is not None, sizing
        assert sizing[name]["width"] <= card["inner"] + 1, sizing
        assert sizing[name]["height"] <= card["client_height"], sizing
    sizing_card = lab.page.locator(".lgn-grand-card", has_text="OpenMDAO sizing").first
    table = sizing_card.locator("table").first
    assert "\u25cf" in (table.text_content() or ""), "no active flag after maximize"
    scroll_into_view(sizing_card)
    sizing_card.screenshot(path=str(EVIDENCE / "grand_sizing_card.png"))
    for name, selector in _RENDERINGS.items():
        rendering = sizing_card.locator(".widget-html", has=lab.page.locator(selector)).first
        rendering.screenshot(path=str(EVIDENCE / f"grand_sizing_{name}.png"))

    lab.assert_no_errors()


DOCK_NOTEBOOK = "grand_tour_dock_scenario.ipynb"
GRAND_TABS = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey^="grand-"]'

#: every docked pane: its tab label, the keys of the tabs in the same tab
#: bar, and the box of its panel.  LabShell writes the panel's DOM id into
#: the tab's dataset, so ``data-id`` finds the panel of a tab
_DOCK_JS = """() => {
    const out = {};
    for (const tab of document.querySelectorAll(
        '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey^="grand-"]')) {
        const panel = tab.dataset.id ? document.getElementById(tab.dataset.id) : null;
        const r = panel ? panel.getBoundingClientRect() : null;
        out[tab.dataset.lgxkey] = {
            label: tab.textContent.trim(),
            bar: [...tab.closest('.lm-TabBar').querySelectorAll('.lm-TabBar-tab')]
                .map((t) => t.dataset.lgxkey || 'other'),
            box: r && {x: r.x, y: r.y, width: r.width, height: r.height},
        };
    }
    return out;
}"""

#: the center of the dock handle between the panels of two panes, side by
#: side: a visible handle in the gap between them, at their shared height
_HANDLE_JS = """([leftKey, rightKey]) => {
    const box = (key) => {
        const tab = document.querySelector(
            `#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="${key}"]`);
        const panel = tab && document.getElementById(tab.dataset.id);
        return panel ? panel.getBoundingClientRect() : null;
    };
    const a = box(leftKey), b = box(rightKey);
    if (!a || !b) return null;
    for (const handle of document.querySelectorAll(
        '#jp-main-dock-panel > .lm-DockPanel-handle')) {
        const r = handle.getBoundingClientRect();
        if (!r.width || !r.height) continue;
        if (r.x >= a.right - 6 && r.right <= b.left + 6 && r.top <= a.top + 40
            && r.bottom >= a.top + a.height / 2) {
            return {x: r.x + r.width / 2, y: a.top + a.height / 2};
        }
    }
    return null;
}"""


def _dock(lab: Any) -> dict[str, Any]:
    return dict(lab.evaluate(_DOCK_JS, label="the docked panes"))


def _drag(lab: Any, start: tuple[float, float], end: tuple[float, float]) -> None:
    """A user drag: press, move in steps, release."""

    mouse = lab.page.mouse
    mouse.move(*start)
    mouse.down()
    mouse.move(start[0] + 4, start[1] + 40, steps=6)  # past lumino's detach threshold
    mouse.move(*end, steps=20)
    mouse.up()


def test_dock_resizes_and_rearranges_the_panes(lab: Any) -> None:
    """The docked tour: nine Lab panels, a drag handle, a tab drag (scenario 7)."""

    _open(lab, notebook=DOCK_NOTEBOOK)
    assert lab.page.locator(GRAND_TABS).count() == 0

    docked = lab._extract_json(lab.run_cell(4))
    assert len(docked["panels"]) == 9 and docked["children"] == 2, docked
    lab.wait_until(
        lambda _s: lab.page.locator(GRAND_TABS).count() == 9,
        timeout=60,
        label="nine grand-tour tabs in the main dock",
    )
    # the inline output keeps only the note (the notebook is behind the Mission tab)
    lab.page.wait_for_selector(".jp-OutputArea .lgn-grand-docked", state="attached")
    assert lab.page.locator(".jp-OutputArea .longeron-viewer3d").count() == 0
    lab.page.wait_for_selector(".lgn-grand-pane .longeron-viewer3d canvas", timeout=120_000)
    lab.page.wait_for_selector(".lgn-grand-pane .lgx-row", timeout=60_000)
    panes = _dock(lab)
    labels = {key: pane["label"] for key, pane in panes.items()}
    assert labels == {
        "grand-tree": "Tree",
        "grand-structure": "Structure",
        "grand-3d": "3D",
        "grand-scoreboard": "Scoreboard",
        "grand-subject": "Subject",
        "grand-camera": "Camera what-if",
        "grand-sizing": "Sizing",
        "grand-z3": "Z3",
        "grand-mission": "Mission",
    }, labels
    # the first view follows the inline layout: row 1 left to right, row 2 below
    row1 = [panes[f"grand-{p}"]["box"] for p in ("tree", "structure", "3d", "scoreboard")]
    row2 = [panes[f"grand-{p}"]["box"] for p in ("subject", "camera", "sizing", "z3")]
    assert all(box and box["width"] > 100 and box["height"] > 100 for box in row1), panes
    assert [b["x"] for b in row1] == sorted(b["x"] for b in row1), row1
    assert min(b["y"] for b in row2) > max(b["y"] for b in row1), (row1, row2)
    assert panes["grand-mission"]["box"]["y"] > min(b["y"] for b in row2), panes
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "grand_tour_dock_first.json").write_text(json.dumps(panes, indent=1), "utf-8")
    lab.page.screenshot(path=str(EVIDENCE / "grand_tour_docked.png"))

    # a drag of the handle between the tree and the structure diagram
    handle = lab.evaluate(_HANDLE_JS, ["grand-tree", "grand-structure"], label="tree handle")
    assert handle, f"no dock handle between the tree and the diagram: {panes}"
    mouse = lab.page.mouse
    mouse.move(handle["x"], handle["y"])
    mouse.down()
    mouse.move(handle["x"] + 120, handle["y"], steps=12)
    mouse.up()
    resized = _dock(lab)
    tree_grew = resized["grand-tree"]["box"]["width"] - panes["grand-tree"]["box"]["width"]
    diagram_shrank = (
        panes["grand-structure"]["box"]["width"] - resized["grand-structure"]["box"]["width"]
    )
    assert tree_grew > 60 and diagram_shrank > 60, (panes, resized)

    # a drag of the 3D tab onto the middle of the tree pane joins the tree's tab bar
    tab = lab.page.locator('#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="grand-3d"]')
    grip = tab.bounding_box()
    tree = resized["grand-tree"]["box"]
    assert grip is not None
    start = (grip["x"] + grip["width"] / 2, grip["y"] + grip["height"] / 2)
    _drag(lab, start, (tree["x"] + tree["width"] / 2, tree["y"] + tree["height"] / 2))
    lab.wait_until(
        lambda _s: "grand-tree" in _dock(lab)["grand-3d"]["bar"],
        timeout=30,
        label="the 3D tab joined the tree's tab bar",
    )
    moved = _dock(lab)
    assert "grand-3d" not in moved["grand-scoreboard"]["bar"], moved
    lab.page.screenshot(path=str(EVIDENCE / "grand_tour_docked_rearranged.png"))

    # the hub still works: a tree row click changes the subject
    lab.page.locator('#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="grand-tree"]').click()
    search = lab.page.locator(".lgn-grand-pane .lgx-tree-search").first
    search.wait_for(state="visible", timeout=30_000)
    search.fill("flyingWingTwin")
    row = lab.page.locator(f'.lgn-grand-pane .lgx-row[data-id="{TWIN_VARIANT}"]').first
    row.wait_for(state="visible", timeout=60_000)
    row.click()
    state = _poll_checker(lab, lambda s: s["airframe"] == "flyingWingTwin")
    assert state["diagram"] == [TWIN_VARIANT], state

    # undock: the panels close and the inline layout comes back
    undocked = lab._extract_json(lab.run_cell(5))
    assert undocked == {"panels": [], "children": 5}, undocked
    lab.wait_until(
        lambda _s: lab.page.locator(GRAND_TABS).count() == 0,
        timeout=60,
        label="every grand-tour tab closed",
    )
    lab.page.wait_for_selector(".jp-OutputArea .longeron-viewer3d canvas", timeout=120_000)
    assert lab.page.locator(".jp-OutputArea .lgn-grand-docked").count() == 0
    # the new view of the tree shows the query that its rows still apply
    search = lab.page.locator(".jp-OutputArea .lgx-tree-search").first
    assert search.input_value() == "flyingWingTwin"
    scroll_into_view(_header(lab))
    lab.page.screenshot(path=str(EVIDENCE / "grand_tour_undocked.png"))
