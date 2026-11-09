"""Browser-truth: the grand tour's selection hub (``grand.grand_dashboard``).

The kernel-side tests (tests/test_grand_tour.py) prove the subject
wiring headless: the tree, the diagram, the knobs and the mission
selector each write the subject, and every pane follows it.  What only a
browser can prove is the seam end to end through the REAL rendered
surfaces: a genuine click on a containment-tree row, on a sprotty
diagram label, on a dropdown, a slider and a toggle button, each
repainting the panes beside it.

Six scenarios, each on a fresh kernel:

1. a tree row click changes the subject: the diagram repaints its
   selection and the 3D pane rebuilds its scene for the new craft;
2. a diagram click on a catalog craft reveals its tree row and changes
   the subject, while a build configuration only visits;
3. a knob change repaints the 3D pane (the battery dropdown) and
   re-scores the scoreboard (the station-time slider);
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

Scenarios 1, 2 and 4 collapse JupyterLab's left sidebar first.  At the
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


#: JupyterLab's own "collapse the left area" (View > Show Left Sidebar off)
_COLLAPSE_LEFT_JS = """() => {
    (window.jupyterapp || window.jupyterlab).shell.collapseLeft();
    return true;
}"""


def _collapse_sidebar(lab: Any) -> None:
    assert lab.evaluate(_COLLAPSE_LEFT_JS, label="collapse the left sidebar")


def _open(lab: Any, *, collapse_sidebar: bool = True) -> dict[str, Any]:
    """Run the scenario notebook; return the settled checker state."""

    lab.open_notebook(NOTEBOOK)
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
