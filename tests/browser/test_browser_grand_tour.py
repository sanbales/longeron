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
   slider rebuilds the 3D scene and the Cesium model (scenario 3b).
   The 3D pane keeps its camera across the span rebuild, so the wing
   draws wider, and a catalog craft click re-fits the camera;
4. the mission toggle to logistics shows the honest-absence card in the
   sizing strip and swaps the knob card;
5. the dashboard fits a 1080p screen: on a 1920x1080 page, the whole
   dashboard is no taller than the visible output area of a 1080p
   browser window (860 px).  No element scrolls and no control is
   clipped at any tab of the two tab groups, and each Views tab shows
   its pane at least 500 px on each side.  The tree column spans the
   dashboard below the header and collapses to a strip, which costs the
   diagram one refit.  The Cesium globe renders at its full size after
   its first reveal, and a click on the scaled scoreboard SVG selects the
   clicked requirement.
5b. the same fit holds in a wider font (Verdana, or DejaVu Sans, the
   Linux default font) at 100 % and with the page's font sizes at 115 %,
   before and after a *maximize* run.
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

Every scenario but 3 collapses JupyterLab's left sidebar first.  A
scenario selects the tab of a pane before it clicks or measures the pane,
for example the *Requirements* tab before a scoreboard cell or the
*Mission* tab before the Cesium stage.  Scenarios 3 and 4 also record
the layout (the widths of the three body columns, and whether an
Analysis card's content is taller than the card) in
``build/evidence/grand_tour_layout_<state>.json``.  Those values are a
record.  Scenario 5 is the only one that asserts geometry.  Each stage
saves a PNG under ``build/evidence/``.
"""

from __future__ import annotations

import base64
import json
import math
import time
from typing import Any

import pytest

from .conftest import REPO, _lab_page, scroll_into_view

pytestmark = pytest.mark.browser

NOTEBOOK = "grand_tour_scenario.ipynb"
EVIDENCE = REPO / "build" / "evidence"
ISR_TASKING = "ScoutMissions::MissionRequirements::IsrTasking"
TWIN_VARIANT = "ScoutMissions::Catalog::AirframeChoice::flyingWingTwin"
TEARDROP_VARIANT = "ScoutMissions::Catalog::AirframeChoice::teardropQuad"

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

#: the body row's column boxes (the tree column, the centre column and the
#: Views tabs), and each Analysis card's content height against its own
#: height (a card scrolls vertically when its content is taller)
_LAYOUT_JS = """() => {
    const dash = document.querySelector('.jp-OutputArea-output .lgn-grand-tour');
    const row = dash ? dash.children[2] : null;
    const viewer = document.querySelector('.longeron-viewer3d');
    const names = ['tree', 'centre', 'views'];
    const box = (el) => {
        const r = el.getBoundingClientRect();
        return {width: Math.round(r.width), height: Math.round(r.height)};
    };
    const output = viewer ? viewer.closest('.jp-OutputArea-output') : null;
    return {
        viewport: {width: window.innerWidth, height: window.innerHeight},
        output_width: output ? Math.round(output.getBoundingClientRect().width) : null,
        body_width: row ? Math.round(row.getBoundingClientRect().width) : null,
        body: row ? Object.fromEntries(
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


def _tab(lab: Any, title: str) -> None:
    """Click the dashboard tab titled ``title`` (a Views or an Analysis tab)."""

    tab = lab.page.locator(
        ".jp-OutputArea-output .lgn-grand-tabs .lm-TabBar-tab", has_text=title
    ).first
    tab.click()
    lab.wait_until(
        lambda _s: "lm-mod-current" in (tab.get_attribute("class") or ""),
        timeout=30,
        label=f"the {title} tab is current",
    )


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
    narrow = _record_layout(lab, "ISR_sidebar_open")["body_width"]
    _collapse_sidebar(lab)
    lab.wait_until(
        lambda _s: lab.evaluate(_LAYOUT_JS, label="body widens")["body_width"] > narrow,
        timeout=60,
        label="the body row widened after the sidebar collapsed",
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
    _tab(lab, "Requirements")  # the scoreboard beside the knob card
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


#: landmarks in a PNG of the 3D canvas, decoded by the page (the test
#: needs no image library): the centroid of the red propeller hub (the
#: hub does not depend on the span), the centroids of the slate wingtip
#: fins left and right of the hub, and the box of the dark pixels of the
#: solid parts
_LANDMARKS_JS = """async (b64) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + b64;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    const box = () => ({x0: c.width, x1: -1, y0: c.height, y1: -1, n: 0});
    const grow = (b, x, y) => {
        b.n++;
        b.x0 = Math.min(b.x0, x); b.x1 = Math.max(b.x1, x);
        b.y0 = Math.min(b.y0, y); b.y1 = Math.max(b.y1, y);
    };
    const dark = box(), fins = [];
    let hx = 0, hy = 0, hn = 0;
    for (let y = 0; y < c.height; y++) {
        for (let x = 0; x < c.width; x++) {
            const i = 4 * (y * c.width + x);
            const r = d[i], g = d[i + 1], b = d[i + 2];
            const luma = 0.299 * r + 0.587 * g + 0.114 * b;
            if (r - g > 40 && r - b > 50) { hx += x; hy += y; hn++; }
            if (b - r > 4 && b - g > 2 && luma < 120) fins.push([x, y]);
            if (luma < 150) grow(dark, x, y);
        }
    }
    const hub = hn ? [hx / hn, hy / hn] : null;
    const centroid = (side) => {
        const own = fins.filter(([x]) => hub && side * (x - hub[0]) > 0);
        return own.length ? [own.reduce((s, p) => s + p[0], 0) / own.length,
                             own.reduce((s, p) => s + p[1], 0) / own.length] : null;
    };
    return {width: c.width, height: c.height, hub, fins: [centroid(-1), centroid(1)], dark};
}"""

#: one wheel step of the 3D pane: the viewer scales the camera distance
#: by exp(0.001 * deltaY), so +800 then -800 restores the distance
_ZOOM_OUT = 800


def _landmarks(lab: Any, pane: Any, name: str) -> dict[str, Any]:
    """Screenshot the 3D canvas to ``EVIDENCE/name`` and measure its landmarks.

    The screenshot paints the binding hint over the canvas in the
    background colour, so the hint text does not count as a solid part.
    """

    png = pane.locator("canvas").first.screenshot(
        path=str(EVIDENCE / name),
        mask=[pane.locator(".longeron-viewer3d-hint")],
        mask_color="#f4f4f2",
    )
    found = lab.evaluate(
        _LANDMARKS_JS, base64.b64encode(png).decode(), label=f"3D landmarks ({name})"
    )
    return dict(found)


def _wheel(lab: Any, pane: Any, delta: float) -> None:
    pane.locator("canvas").first.hover()
    lab.page.mouse.wheel(0, delta)


def test_span_slider_widens_the_3d_wing_and_the_flight(lab: Any) -> None:
    """The span slider rebuilds the 3D scene and the Cesium model (scenario 3b).

    The 3D pane keeps its camera across the rebuild, so the wider wing
    draws wider.  The scenario zooms out until both wingtip fins show.
    The distance between the fins on the canvas then grows by the span
    ratio, and the propeller hub stays where it was.  A click on another
    catalog craft re-fits the camera to that craft.
    """

    state = _open(lab)
    assert state["airframe"] == "flyingWingSingle", state
    assert "airframe.wingSpan" in state["knobs"], state
    pane = lab.page.locator(".longeron-viewer3d").first
    scroll_into_view(pane)
    pane.screenshot(path=str(EVIDENCE / "grand_span_default.png"))
    _wheel(lab, pane, _ZOOM_OUT)  # both wingtip fins in view
    before = _landmarks(lab, pane, "grand_span_default_zoomed_out.png")
    span = lab.page.locator(".widget-hslider").filter(has_text="wingSpan").first
    default = float(span.locator(".widget-readout").first.text_content() or "nan")
    _arm_rebuilds(lab)
    _drag_slider(lab, "wingSpan", 1.0)
    after = _poll_checker(lab, lambda s: s["overrides"].get("airframe.wingSpan", 0) >= 2.8)
    assert after["mesh"] != state["mesh"], after  # the subject mesh follows the what-if
    assert after["czml"] != state["czml"], after  # ... and so does the Cesium glTF
    _wait_rebuilt(lab, "the 3D pane rebuilt the wider wing")
    scroll_into_view(pane)
    wide = _landmarks(lab, pane, "grand_span_max_zoomed_out.png")
    _wheel(lab, pane, -_ZOOM_OUT)  # back to the framing of the default wing
    pane.screenshot(path=str(EVIDENCE / "grand_span_max.png"))
    ratio = after["overrides"]["airframe.wingSpan"] / default
    record: dict[str, Any] = {"span_ratio": ratio, "default": before, "max": wide}
    assert before["hub"] and wide["hub"], record
    assert all(before["fins"]) and all(wide["fins"]), record  # both fins in view
    record["fin_ratio"] = math.dist(*wide["fins"]) / math.dist(*before["fins"])
    # the camera stays: the hub holds its pixels, and the wing grows with the span
    assert math.dist(wide["hub"], before["hub"]) < 2.0, record
    assert record["fin_ratio"] == pytest.approx(ratio, abs=0.03), record

    # -- a catalog craft click re-fits the camera to the new craft ----------
    _arm_rebuilds(lab)
    search = lab.page.locator(".lgx-tree-search").first
    scroll_into_view(search)
    search.fill("teardropQuad")
    row = lab.page.locator(f'.lgx-row[data-id="{TEARDROP_VARIANT}"]')
    row.first.wait_for(state="visible", timeout=60_000)
    row.first.click()
    _poll_checker(lab, lambda s: s["airframe"] == "teardropQuad")
    _wait_rebuilt(lab, "the 3D pane rebuilt the teardrop quad")
    scroll_into_view(pane)
    pane.screenshot(path=str(EVIDENCE / "grand_span_then_teardrop.png"))
    quad = _landmarks(lab, pane, "grand_span_then_teardrop_canvas.png")
    record["teardrop"] = quad
    (EVIDENCE / "grand_span_framing.json").write_text(json.dumps(record, indent=1), "utf-8")
    # re-fitted, the quad's solid parts span about 40 % of the canvas
    # height; with the camera of the flying wing they would span about 13 %
    assert (quad["dark"]["y1"] - quad["dark"]["y0"]) / quad["height"] > 0.25, record

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
    _tab(lab, "Sizing")
    scroll_into_view(absence.first)
    lab.page.screenshot(path=str(EVIDENCE / "grand_mission_logistics.png"), full_page=True)

    lab.assert_no_errors()


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

#: the dashboard's fit at the current tab selection: the dashboard, the
#: header, the tree column, the notebook panel and each tab body with its
#: shown pane (and the canvas or the SVG inside it); every element that
#: scrolls (its content is taller than its box) except the tree's own rows
#: and Cesium's internals; and every visible control that is not inside
#: the dashboard and inside its tab body
_FIT_JS = """() => {
    const dash = document.querySelector('.jp-OutputArea-output .lgn-grand-tour');
    if (!dash) return null;
    const box = (el) => {
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {x: r.x, y: r.y, width: r.width, height: r.height, bottom: r.bottom, right: r.right};
    };
    const outer = dash.getBoundingClientRect();
    const bodies = [...dash.querySelectorAll('.lgn-grand-tabs > .widget-tab-contents')];
    const shown = (body) => [...body.children].find((c) => c.offsetParent !== null) || null;
    const scrolls = [...dash.querySelectorAll('*')].filter((el) => {
        if (el.closest('.lgx-tree') || el.closest('[class*="cesium"]')) return false;
        const overflow = getComputedStyle(el).overflowY;
        return el.clientHeight > 0 && el.scrollHeight > el.clientHeight + 1
            && /(auto|scroll|hidden)/.test(overflow);
    }).map((el) => ({cls: String(el.className).slice(0, 80),
                     client: el.clientHeight, scroll: el.scrollHeight}));
    const clipped = [...dash.querySelectorAll('button, select, input, .widget-hslider')]
        .filter((el) => el.offsetParent !== null && !el.closest('.lgx-tree')
                && !el.closest('.longeron-mission3d-stage'))
        .filter((el) => {
            const r = el.getBoundingClientRect();
            const body = el.closest('.widget-tab-contents');
            const frame = body ? body.getBoundingClientRect() : outer;
            return r.top < frame.top - 1 || r.bottom > frame.bottom + 1
                || r.left < frame.left - 1 || r.right > frame.right + 1;
        }).map((el) => (el.textContent || el.className).trim().slice(0, 40));
    const panel = document.querySelector('.jp-NotebookPanel .jp-WindowedPanel-outer');
    return {
        viewport: {width: window.innerWidth, height: window.innerHeight},
        notebook: box(panel),
        dash: box(dash), header: box(dash.children[1]),
        tree: box(dash.querySelector('.lgn-grand-strip')),
        centre: box(dash.children[2].children[1]),
        tabs: bodies.map((body) => {
            const pane = shown(body);
            return {body: box(body), pane: box(pane),
                    canvas: box(pane && pane.querySelector('canvas')),
                    svg: box(pane && pane.querySelector('.lgn-sb-wrap svg'))};
        }),
        scrolls, clipped,
    };
}"""

#: the luma spread of a PNG, decoded by the page: a blank (one-colour)
#: render has none
_SPREAD_JS = """async (b64) => {
    const img = new Image();
    img.src = 'data:image/png;base64,' + b64;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = img.width; c.height = img.height;
    const ctx = c.getContext('2d');
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height).data;
    let n = 0, sum = 0, sq = 0;
    for (let i = 0; i < d.length; i += 16) {
        const luma = 0.299 * d[i] + 0.587 * d[i + 1] + 0.114 * d[i + 2];
        n++; sum += luma; sq += luma * luma;
    }
    return Math.sqrt(Math.max(0, sq / n - (sum / n) ** 2));
}"""

#: the visible output height at a 1920x1080 browser WINDOW: the screen
#: minus the browser chrome (about 100 px) and the JupyterLab chrome
#: (menu, tab bar, notebook toolbar and status bar, about 120 px)
_OUTPUT_PX = 860
#: the smallest tab body side that shows a pane at a readable size
_TAB_MIN_PX = 500


@pytest.fixture()
def lab1080(browser: Any, lab_server: Any, request: pytest.FixtureRequest) -> Any:
    """A 1920x1080 page: the fit contract is stated at 1080p."""

    yield from _lab_page(browser, lab_server, request, {"width": 1920, "height": 1080})


def _fit(lab: Any, label: str) -> dict[str, Any]:
    return dict(lab.evaluate(_FIT_JS, label=f"the dashboard fit ({label})"))


def _assert_fits(fit: dict[str, Any], label: str) -> None:
    """One screen holds the dashboard: no scroll bar, no clipped control."""

    dash, header, tree = fit["dash"], fit["header"], fit["tree"]
    assert dash["height"] <= _OUTPUT_PX, (label, fit)
    assert dash["bottom"] <= fit["notebook"]["bottom"] + 1, (label, fit)  # on screen
    # the tree column spans the dashboard below the header
    assert tree["y"] - header["bottom"] <= 4 and dash["bottom"] - tree["bottom"] <= 6, (label, fit)
    assert fit["scrolls"] == [], (label, fit)
    assert fit["clipped"] == [], (label, fit)


def _spread(lab: Any, locator: Any, name: str) -> float:
    png = locator.screenshot(path=str(EVIDENCE / name))
    return float(lab.evaluate(_SPREAD_JS, base64.b64encode(png).decode(), label=name))


def test_the_dashboard_fits_a_1080p_screen(lab1080: Any) -> None:
    """Header, tree column, diagram and two tab groups on one screen (scenario 5).

    At 1920x1080 with the left sidebar collapsed, the whole dashboard is
    no taller than the visible output area of a 1080p browser window.  No
    element scrolls and no control is clipped, at every tab of the Views
    and Analysis tab groups and with the logistics knob card.  Each Views
    tab shows its pane at least 500 px on each side, and the Cesium globe
    renders at its full size after a tab switch.  The tree column
    collapses to a strip, and the diagram takes the width with one refit.
    A click on the scaled scoreboard SVG selects the clicked requirement.
    The measurements go to ``build/evidence/grand_tour_1080p_fit.json``.
    """

    lab = lab1080
    _open(lab)
    output = lab.page.locator(".jp-OutputArea-output", has=lab.page.locator(".lgn-grand-tour"))
    output.first.evaluate("(el) => el.scrollIntoView({block: 'start'})")
    record: dict[str, Any] = {}

    # -- the Analysis tabs over the 3D pane, then the logistics knob card ---
    for title in ("Camera what-if", "Sizing", "Z3", "Subject & knobs"):
        _tab(lab, title)
        record[title] = fit = _fit(lab, title)
        _assert_fits(fit, title)
    toggle = lab.page.locator('button.widget-toggle-button:text-is("logistics")').first
    toggle.click()
    _poll_checker(lab, lambda s: s["mission"] == "logistics")
    lab.wait_until(
        lambda _s: _dropdown(lab, "cargo").count() == 1,
        timeout=60,
        label="the logistics knob card",
    )
    record["logistics"] = fit = _fit(lab, "logistics")
    _assert_fits(fit, "logistics")
    assert lab.page.locator(".lgn-grand-card .widget-hslider").count() >= 4, "knob sliders"
    lab.page.screenshot(path=str(EVIDENCE / "grand_1080p_logistics.png"))
    lab.page.locator('button.widget-toggle-button:text-is("ISR")').first.click()
    _poll_checker(lab, lambda s: s["mission"] == "ISR")

    # -- each Views tab shows its pane at a readable size -------------------
    for title, inner in (("3D", "canvas"), ("Requirements", "svg"), ("Mission", "canvas")):
        _tab(lab, title)
        lab.wait_until(
            lambda _s, title=title, inner=inner: (
                (_fit(lab, title)["tabs"][1][inner] or {}).get("height", 0) >= _TAB_MIN_PX
            ),
            timeout=60,
            label=f"the {title} tab fills its body",
        )
        record[title] = fit = _fit(lab, title)
        _assert_fits(fit, title)
        views = fit["tabs"][1]
        assert min(views["body"]["width"], views["body"]["height"]) >= _TAB_MIN_PX, fit
        assert views[inner]["width"] >= _TAB_MIN_PX and views[inner]["height"] >= _TAB_MIN_PX, fit
        lab.page.screenshot(path=str(EVIDENCE / f"grand_1080p_{title.lower()}.png"))
        if title == "Requirements":
            # a cell click on the scaled SVG still selects that requirement
            point = lab.evaluate(_CELL_POINT_JS, ISR_TASKING, label="IsrTasking cell point")
            assert point and point["inside"] and point["hit"], point
            lab.page.mouse.click(point["x"], point["y"])
            state = _poll_checker(lab, lambda s: s["board"] == [ISR_TASKING])
            assert state["diagram"] == [ISR_TASKING], state
    _tab(lab, "3D")

    # -- the tree column collapses: the diagram takes the width, one refit --
    refits = _poll_checker(lab, lambda _s: True)["refits"]
    open_centre = record["3D"]["centre"]["width"]
    strip = lab.page.locator(".lgn-grand-strip button").first
    strip.click()
    lab.wait_until(
        lambda _s: _fit(lab, "collapsed")["centre"]["width"] > open_centre + 200,
        timeout=60,
        label="the centre column takes the tree's width",
    )
    record["collapsed"] = fit = _fit(lab, "collapsed")
    _assert_fits(fit, "collapsed")
    assert fit["tree"]["width"] <= 30, fit
    after = _poll_checker(lab, lambda s: s["refits"] > refits, timeout=30)["refits"]
    time.sleep(3.0)
    assert _poll_checker(lab, lambda _s: True)["refits"] == after == refits + 1
    lab.page.screenshot(path=str(EVIDENCE / "grand_1080p_tree_collapsed.png"))
    strip.click()
    lab.wait_until(
        lambda _s: _fit(lab, "expanded")["tree"]["width"] >= 239,
        timeout=60,
        label="the tree column expands again",
    )
    (EVIDENCE / "grand_tour_1080p_fit.json").write_text(json.dumps(record, indent=1))

    # -- the Cesium globe renders after its first reveal (last: CDN skip) ---
    _tab(lab, "Mission")
    _wait_for_cesium(lab)
    stage = lab.page.locator(".longeron-mission3d-stage").first
    lab.wait_until(
        lambda _s: _spread(lab, stage, "grand_1080p_mission_stage.png") > 8.0,
        timeout=60,
        label="the Cesium stage draws the globe",
    )
    sized = lab.evaluate(
        """() => {
            const stage = document.querySelector('.longeron-mission3d-stage');
            const canvas = stage.longeronViewer.canvas;
            return {stage: stage.clientWidth, canvas: canvas.clientWidth,
                    buffer: canvas.width / devicePixelRatio};
        }""",
        label="the Cesium canvas size",
    )
    assert abs(sized["canvas"] - sized["stage"]) <= 2, sized
    assert abs(sized["buffer"] - sized["canvas"]) <= 2, sized  # the drawing buffer follows
    # a satellite tile that the imagery server refuses (seen on the Mission
    # tab visits) is a network condition: the globe draws the tiles that
    # load.  Every other console error counts
    errors = [
        message
        for message in lab.console_errors()
        if "arcgisonline.com" not in message and "net::ERR_FAILED" not in message
    ]
    assert errors == [], errors
    assert lab.page_errors == [], lab.page_errors


#: a wider font on the dashboard and larger font sizes on the page.  The
#: font is Verdana, or DejaVu Sans where Verdana is absent.  DejaVu Sans
#: is the Linux CI default font, whose wider glyphs wrapped the sizing
#: renderings to a second line.  The body and JupyterLab's font-size
#: variables go to ``scale``.  Returns the width of one sizing label in
#: the dashboard's font and in Helvetica, so the record shows that the
#: font took effect
_FONT_STRESS_JS = """(scale) => {
    document.body.style.fontSize = `${100 * scale}%`;
    const root = document.documentElement;
    const names = ['--jp-ui-font-size0', '--jp-ui-font-size1', '--jp-ui-font-size2',
                   '--jp-ui-font-size3', '--jp-content-font-size1', '--jp-code-font-size',
                   '--jp-widgets-font-size'];
    root.lgnFontBase = root.lgnFontBase || Object.fromEntries(names.map(
        (name) => [name, parseFloat(getComputedStyle(root).getPropertyValue(name))]));
    for (const name of names) {
        if (root.lgnFontBase[name]) {
            root.style.setProperty(name, `${root.lgnFontBase[name] * scale}px`);
        }
    }
    let face = document.getElementById('lgn-font-stress');
    if (!face) {
        face = document.createElement('style');
        face.id = 'lgn-font-stress';
        face.textContent = '.lgn-grand-tour, .lgn-grand-tour *:not(i) '  // i: the icon font
            + '{ font-family: Verdana, "DejaVu Sans", sans-serif !important; }';
        document.head.appendChild(face);
    }
    const width = (parent, family) => {
        const probe = document.createElement('span');
        probe.textContent = 'stationMinutes 200.4 min';
        probe.style.cssText = `position:absolute; visibility:hidden; font-size:12px; ${family}`;
        parent.appendChild(probe);
        const px = probe.getBoundingClientRect().width;
        probe.remove();
        return px;
    };
    return {dashboard: width(document.querySelector('.lgn-grand-tour'), ''),
            helvetica: width(document.body, 'font-family:Helvetica,Arial,sans-serif')};
}"""

#: the Analysis and the Views tab titles, and the element each Views pane draws in
_ANALYSIS_TABS = ("Camera what-if", "Sizing", "Z3", "Subject & knobs")
_VIEWS_TABS = (("3D", "canvas"), ("Requirements", "svg"), ("Mission", "canvas"))


def test_the_dashboard_fits_in_a_wider_larger_font(lab1080: Any) -> None:
    """The 1080p fit holds in a wider font at 100 % and at 115 % (scenario 5b).

    Linux Chromium draws the dashboard in DejaVu Sans, which is wider than
    the macOS font.  In the wider font (Verdana, or DejaVu Sans where
    Verdana is absent), at 100 % and with the body and JupyterLab's font
    sizes at 115 %, no element scrolls and no control is clipped at any
    Analysis or Views tab, before and after a *maximize* run fills the
    sizing renderings.  The measurements go to
    ``build/evidence/grand_tour_font_fit.json``.
    """

    lab = lab1080
    _open(lab)
    output = lab.page.locator(".jp-OutputArea-output", has=lab.page.locator(".lgn-grand-tour"))
    output.first.evaluate("(el) => el.scrollIntoView({block: 'start'})")
    record: dict[str, Any] = {}

    def _check(scale: float, tabs: tuple[str, ...]) -> None:
        probe = lab.evaluate(_FONT_STRESS_JS, scale, label=f"the font at {scale:.0%}")
        record[f"probe width {scale:.0%}"] = probe
        for title in tabs:
            _tab(lab, title)
            label = f"{title} at {scale:.0%}"
            record[label] = fit = _fit(lab, label)
            _assert_fits(fit, label)
            if title == "Sizing":
                card = lab.page.locator(".lgn-grand-card", has_text="OpenMDAO sizing").first
                card.screenshot(path=str(EVIDENCE / f"grand_font_sizing_{scale * 100:.0f}.png"))

    for scale in (1.0, 1.15):
        _check(scale, _ANALYSIS_TABS)
        for title, inner in _VIEWS_TABS:
            _tab(lab, title)
            lab.wait_until(
                lambda _s, title=title, inner=inner: (
                    (_fit(lab, title)["tabs"][1][inner] or {}).get("height", 0) >= _TAB_MIN_PX
                ),
                timeout=60,
                label=f"the {title} tab fills its body",
            )
            label = f"{title} at {scale:.0%}"
            record[label] = fit = _fit(lab, label)
            _assert_fits(fit, label)
        lab.page.screenshot(path=str(EVIDENCE / f"grand_font_{scale * 100:.0f}.png"))

    # -- maximize fills the history plot and the active flags ----------------
    _tab(lab, "Sizing")
    lab.page.locator('button:text-is("maximize station time")').first.click()
    _poll_checker(lab, lambda s: s["loiter"] == 11.0)  # the stall floor binds
    lab.page.locator(_RENDERINGS["history"]).first.wait_for(state="attached", timeout=60_000)
    for scale in (1.15, 1.0):
        lab.evaluate(_FONT_STRESS_JS, scale, label=f"the font at {scale:.0%}")
        label = f"Sizing after maximize at {scale:.0%}"
        record[label] = fit = _fit(lab, label)
        card = lab.page.locator(".lgn-grand-card", has_text="OpenMDAO sizing").first
        card.screenshot(path=str(EVIDENCE / f"grand_font_maximized_{scale * 100:.0f}.png"))
        _assert_fits(fit, label)
    (EVIDENCE / "grand_tour_font_fit.json").write_text(json.dumps(record, indent=1))
    errors = [
        message
        for message in lab.console_errors()
        if "arcgisonline.com" not in message and "net::ERR_FAILED" not in message
    ]
    assert errors == [], errors
    assert lab.page_errors == [], lab.page_errors


def test_the_mission_starts_and_ends_on_the_drawn_surface(lab: Any) -> None:
    """Takeoff and landing sit on the globe, not in the air (scenario 6)."""

    _open(lab)
    _tab(lab, "Mission")
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
    _tab(lab, "Mission")
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
    _tab(lab, "Sizing")
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
    assert undocked == {"panels": [], "children": 3}, undocked
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
