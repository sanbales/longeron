"""Scenario 4: the explorer's tree <-> diagram round trip, in a browser.

Clicking a tree row must select and highlight the element in the diagram
pane; clicking a diagram node must select and reveal it back in the tree.
Both directions traverse the kernel (trait sync -> Explorer plumbing ->
trait sync), so this is the full comm path, not a JS-only echo.

The explorer is built inline in a generated notebook (notebooks/private
is gitignored, so no private notebook is used).

The second test drives the kind switcher (structure -> state ->
structure) over a deliberately WIDE state machine and proves every
switch lands FITTED to the container: the visible diagram's rendered
content must sit inside the pane's viewport (no horizontal overflow --
the maintainer-reported bug rendered the state kind wider than the pane
behind a horizontal scrollbar), and the re-shown cached structure
diagram is re-fitted rather than reappearing at a stale viewport.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "explorer_scenario.ipynb"
EVIDENCE = Path(__file__).resolve().parents[2] / "build" / "evidence"

#: kernel-initiated selection (Explorer -> diagram selection.ids) trips
#: setSelectedNodes in the vendored jupyter-elk frontend before the sprotty
#: model index exists (vendor/ipyelk/js/display_widget.ts, `source.index`
#: undefined). Harmless here -- the selection round trip demonstrably
#: completes both ways. Remove once the vendored frontend guards the index.
KNOWN_VENDOR_PAGE_ERRORS = ("Cannot read properties of undefined (reading 'getById')",)

#: the VISIBLE diagram's framing, browser-truth: built widgets persist in
#: the box as display-toggled children, so measure the one sprotty host
#: div with a real rect.  ``fitted`` is the conftest snapshot idiom (the
#: root <g> transform moved off identity); the overflow numbers measure
#: how far the rendered content spills outside the visible viewport
_VISIBLE_DIAGRAM_JS = r"""() => {
    const shown = [...document.querySelectorAll(
        '.lgx-diagram-box div.sprotty[id^="sprotty"]',
    )].filter((div) => div.getBoundingClientRect().width > 0);
    if (shown.length !== 1) return { shown: shown.length };
    const div = shown[0];
    const g = div.querySelector('svg.sprotty-graph > g');
    if (!g) return { shown: 1, rendered: false };
    const view = div.getBoundingClientRect();
    const content = g.getBoundingClientRect();
    const transform = g.getAttribute('transform') || '';
    const zoom = /scale\(([\d.eE+-]+)/.exec(transform);
    return {
        shown: 1,
        rendered: content.width > 0,
        text: g.textContent || '',
        fitted: transform !== '' && transform !== 'scale(1) translate(0,0)'
            && transform !== 'translate(0, 0) scale(1)',
        scale: zoom ? Number(zoom[1]) : 1,
        viewWidth: view.width,
        contentWidth: content.width,
        overflowX: Math.max(0, view.left - content.left, content.right - view.right),
        overflowY: Math.max(0, view.top - content.top, content.bottom - view.bottom),
    };
}"""

#: sub-pixel slack for getBoundingClientRect rounding
OVERFLOW_TOLERANCE_PX = 1.5


def _visible_diagram(page) -> dict:
    state = page.evaluate(_VISIBLE_DIAGRAM_JS)
    return dict(state) if state else {}


def _fits_container(state: dict, marker: str) -> bool:
    """The visible diagram shows ``marker`` and its content fits the pane."""

    return bool(
        state.get("rendered")
        and marker in state.get("text", "")
        and state.get("fitted")
        and state.get("overflowX", 1e9) <= OVERFLOW_TOLERANCE_PX
        and state.get("overflowY", 1e9) <= OVERFLOW_TOLERANCE_PX
    )


def test_tree_and_diagram_selection_round_trip(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=180)
    page = lab.page
    page.wait_for_selector(".lgx-row", state="attached", timeout=60_000)

    # single-package flattening (2736fb4): Rig IS the root row, and roots
    # start expanded -- axle is already in the DOM (clicking Rig's twist
    # would collapse it, the old pre-flattening idiom)
    page.wait_for_selector(".lgx-row:has-text('axle')", state="attached", timeout=30_000)

    # -- tree -> diagram: click the "axle" row --------------------------------
    page.locator(".lgx-row", has_text="axle").first.click()
    # the breadcrumb (a kernel-side HTML widget) is the browser-visible
    # echo of the selection round trip; kernel-initiated selection does
    # not repaint sprotty's .selected class, so the crumb is the signal
    lab.wait_until(
        lambda s: page.locator("text=Rig::axle").count() >= 1,
        timeout=60,
        label="breadcrumb after tree click",
    )
    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Rig::axle", checker
    assert checker["kind"] == "structure", checker

    # -- diagram -> tree: click the "hub" node --------------------------------
    page.locator(".sprotty svg text", has_text="hub").first.click()
    lab.wait_until(
        lambda s: "hub" in (page.locator(".lgx-row.lgx-selected").first.text_content() or ""),
        timeout=60,
        label="tree reveal after diagram click",
    )
    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Rig::hub", checker
    assert checker["selected"], checker

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)


def test_reshown_cached_diagram_is_refitted_after_kind_switch(lab):
    """structure -> state -> structure: every switch lands fitted."""

    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=180)
    page = lab.page
    page.wait_for_selector(".lgx-row", state="attached", timeout=60_000)

    # single-package flattening (2736fb4): Rig IS the root row and starts
    # EXPANDED -- the Spin row is already in the DOM (clicking Rig's twist
    # would collapse it, the old pre-flattening idiom)
    page.wait_for_selector(".lgx-row:has-text('Spin')", state="attached", timeout=30_000)
    page.locator(".lgx-row", has_text="Spin").first.click()
    switcher = page.locator(".widget-toggle-buttons").first
    switcher.locator("button", has_text="state").wait_for(state="visible", timeout=30_000)

    # -- switch AWAY: the WIDE state diagram builds and must land FITTED
    # to the container (not wider than the pane behind a scrollbar)
    switcher.locator("button", has_text="state").click()
    lab.wait_until(
        lambda s: _fits_container(_visible_diagram(page), "braking"),
        timeout=120,
        label="state diagram rendered AND fitted within the pane",
    )
    wide = _visible_diagram(page)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCE / "explorer-reshow-1-state-kind-fitted.png"))

    # -- switch BACK: the CACHED structure diagram re-enters the box and
    # is re-fitted against its current rendered size
    switcher.locator("button", has_text="structure").click()
    lab.wait_until(
        lambda s: _fits_container(_visible_diagram(page), "axle"),
        timeout=120,
        label="re-shown structure diagram is fitted within the pane",
    )
    page.screenshot(path=str(EVIDENCE / "explorer-reshow-2-structure-refitted.png"))

    # and back to the WIDE kind once more: the cached state diagram is
    # re-shown and re-fitted too (the re-show path, on a wide diagram)
    switcher.locator("button", has_text="state").click()
    lab.wait_until(
        lambda s: _fits_container(_visible_diagram(page), "braking"),
        timeout=120,
        label="re-shown state diagram is fitted within the pane",
    )
    page.screenshot(path=str(EVIDENCE / "explorer-reshow-3-state-refitted.png"))

    # the state machine really is the WIDE case: it only fits because the
    # auto-fit scaled it DOWN (max_zoom caps at 1, so scale < 1 means the
    # natural content is wider than the pane -- the reported repro)
    assert wide["scale"] < 1, wide
    assert wide["viewWidth"] > 300, wide

    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Rig::Spin", checker
    assert checker["kind"] == "state", checker

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)


def test_relationship_rows_toggle_and_edge_selection(lab):
    """Relationships are first-class tree rows: visible by default under
    their owner (dim italic + dashed chip), selectable -- a tree click on
    the anonymous satisfy selects its DRAWN edge through the widget's
    ``_lgn_rel_edges`` seam (the kernel truth is the diagram selection
    holding the edge's synthetic transport id) -- and the tree-toolbar
    toggle hides the rows and shrinks the ``matches/total`` counts."""

    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=180)
    page = lab.page
    page.wait_for_selector(".lgx-row", state="attached", timeout=60_000)

    # -- relationships are VISIBLE by default, under their owning package
    page.wait_for_selector(".lgx-row.lgx-rel", state="attached", timeout=30_000)
    assert page.locator(".lgx-row.lgx-rel").count() == 2  # satisfy + connect
    relbtn = page.locator(".lgx-tree-relbtn")
    assert relbtn.get_attribute("aria-pressed") == "true"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCE / "explorer-relationships-1-rows-visible.png"))

    # -- tree -> edge: click the satisfy row; the kernel maps it to the
    # drawn satisfy edge (a synthetic transport id, never a qname)
    page.locator(".lgx-row.lgx-rel", has_text="satisfy massBudget").first.click()
    # the breadcrumb (kernel-side HTML) is the round trip's browser echo;
    # anonymous relationships have no qname, so it shows the display label
    lab.wait_until(
        lambda s: page.locator(".widget-html", has_text="satisfy massBudget").count() >= 1,
        timeout=60,
        label="breadcrumb after relationship tree click",
    )
    # the kernel-initiated SelectAction repaints sprotty: the satisfy edge
    # carries .selected (bounded wait -- the repaint is a browser render)
    lab.wait_until(
        lambda s: page.locator(".sprotty .elkedge.selected").count() >= 1,
        timeout=60,
        label="the satisfy edge repainted as selected",
    )
    # evidence BEFORE the checker runs (running a cell scrolls the widget
    # out of the viewport); the pane is the screenshot's subject
    page.locator(".lgx-diagram-box").first.scroll_into_view_if_needed()
    page.screenshot(path=str(EVIDENCE / "explorer-relationships-2-edge-selected.png"))
    checker = lab.run_cell_json(index=-1)
    assert checker["element_type"] == "SatisfyUsage", checker
    assert any(i.startswith("__lgn__:") for i in checker["diagram_selection"]), checker

    # -- the toggle: rows vanish and the matches/total counts shrink
    search = page.locator(".lgx-tree-search")
    search.fill("massBudget")
    lab.wait_until(
        lambda s: page.locator(".lgx-tree-count").text_content() == "2/13",
        timeout=30,
        label="filter counts the requirement + the satisfy row",
    )
    relbtn.click()
    lab.wait_until(
        lambda s: page.locator(".lgx-row.lgx-rel").count() == 0,
        timeout=30,
        label="relationship rows vanish on toggle-off",
    )
    lab.wait_until(
        lambda s: page.locator(".lgx-tree-count").text_content() == "1/11",
        timeout=30,
        label="counts respect the toggle (relationships out of both numbers)",
    )
    assert relbtn.get_attribute("aria-pressed") == "false"
    page.screenshot(path=str(EVIDENCE / "explorer-relationships-3-toggled-off.png"))

    # the trait round-trips to the kernel (notebooks can drive the toggle)
    checker = lab.run_cell_json(index=-1)
    assert checker["show_relationships"] is False, checker
    assert checker["total_count"] == 11, checker
    assert checker["match_count"] == 1, checker
    assert checker["rel_edges"] >= 2, checker  # the seam rode the widget

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)
