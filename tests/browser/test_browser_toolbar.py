"""Scenario 3: the longeron toolbar, driven through the real DOM.

Search must highlight without ever touching the selection (the
``on_select`` contract), and the routing/direction toggles must relayout
cleanly.  The kernel-side truth (selection callback count, tool traits)
is read back by re-running the notebook's checker cell.
"""

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "toolbar_scenario.ipynb"
SEARCH_BOX = ".jp-ElkApp input[placeholder='search\u2026']"


def test_search_highlights_without_selecting_and_toggles_relayout(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=180)
    page = lab.page

    # -- search: hits + dims appear, the selection never fires ---------------
    page.hover(".jp-ElkApp")  # the toolbar is hover-revealed
    page.fill(SEARCH_BOX, "wheel")
    page.wait_for_selector(".sprotty .sysml-search-hit", state="attached", timeout=30_000)
    # the hit/dim fragments ride the styling <g> INSIDE each .elknode group
    hits = page.locator(".sprotty g.sysml-search-hit").count()
    dims = page.locator(".sprotty g.sysml-search-dim").count()
    assert hits >= 2, f"expected the wheel nodes highlighted, got {hits}"
    assert dims >= 1, "non-matches were not dimmed"
    assert page.locator(".sprotty .elknode.selected").count() == 0

    checker = lab.run_cell_json(index=-1)
    assert checker["selections"] == 0, f"search fired on_select: {checker}"
    assert checker["query"] == "wheel"
    assert checker["matches"] >= 2, checker  # wheel + spareWheel (at least)

    # clearing restores the diagram exactly
    page.fill(SEARCH_BOX, "")
    lab.wait_until(
        lambda s: page.locator(".sprotty .sysml-search-hit").count() == 0,
        timeout=30,
        label="search highlight cleared",
    )

    routing_before = checker["routing"]
    direction_before = checker["direction"]
    nodes_before = lab.snapshot()["elknodes"]

    # -- routing toggle: relayout, same nodes, no errors ----------------------
    page.hover(".jp-ElkApp")
    page.click("button[title^='Edge routing:']")
    lab.wait_settled(min_widgets=1, timeout=120)

    # -- direction toggle: relayout, same nodes, no errors --------------------
    page.hover(".jp-ElkApp")
    page.click("button[title^='Layout direction:']")
    state = lab.wait_settled(min_widgets=1, timeout=120)
    assert state["elknodes"] == nodes_before, state

    checker = lab.run_cell_json(index=-1)
    assert checker["routing"] != routing_before, checker
    assert checker["direction"] != direction_before, checker
    assert checker["nonempty_selections"] == 0, f"a relayout selected something: {checker}"

    lab.assert_no_errors()
