"""Browser-truth: the grand tour's selection hub (``grand.grand_dashboard``).

The kernel-side tests (tests/test_grand_tour.py) prove the subject
wiring headless: the tree, the diagram, the knobs and the mission
selector each write the subject, and every pane follows it.  What only a
browser can prove is the seam end to end through the REAL rendered
surfaces: a genuine click on a containment-tree row, on a sprotty
diagram label, on a dropdown, a slider and a toggle button, each
repainting the panes beside it.

Four scenarios, each on a fresh kernel:

1. a tree row click changes the subject: the diagram repaints its
   selection and the 3D pane rebuilds its scene for the new craft;
2. a diagram click on a catalog craft reveals its tree row and changes
   the subject, while a build configuration only visits;
3. a knob change repaints the 3D pane (the battery dropdown) and
   re-scores the scoreboard (the station-time slider);
4. the mission toggle to logistics shows the honest-absence card in the
   sizing strip and swaps the knob card.

The tests collapse JupyterLab's left sidebar first.  At the harness
viewport (1500 px) the open file browser leaves the output area about
1070 px wide, and the three fixed panes of row 1 (tree 240 px, 3D and
scoreboard 400 px each) then squeeze the diagram to about 30 px: no label
to click.  Scenarios 3 and 4 also record the layout (row-1 pane widths,
and whether a row-2 card's content is taller than the card) in
``build/evidence/grand_tour_layout_<state>.json``.  The values are a
record, not an assertion (the tier asserts no geometry).  Each stage
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
