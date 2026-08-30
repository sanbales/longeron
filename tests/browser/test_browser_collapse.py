"""Scenario: per-node collapse levels + per-compartment folds, in the
real browser.

The maintainer's finding: 'when I collapse a part def I would expect the
node parts to become text and be under a header parts'.  The toolbar's
collapse button (the affordance they clicked -- select a node, click the
sitemap icon) now CYCLES the selected structure box through the three
legal renditions: nested child boxes -> selectable ``name : Type`` rows
under the 'parts' compartment header (spec printed p.60) -> the name
compartment alone -> back to boxes.  Connector edges that anchored on
undrawn children re-anchor as proxy dots on the box itself (printed
p.67).  Selection survives every step -- a selected child box becomes
its selected row and back -- because rows carry the same qualified-name
id the boxes carried (plus the vendored LOCAL PATCH 14: relayouts
re-apply the kernel's live selection).

Independently, every compartment header carries a fold twist: clicking
the header row folds that ONE compartment while the node keeps its
level, and the click must NEVER enter the model-selection seam (headers
are presentation artifacts; the fit sentinel consumes the click before
sprotty sees it).

The scenario runs on REAL DeepScout content (MultiRotor + QuadCopter,
whose phaseLeads connection crosses into QuadCopter's motors child) and
drives BOTH affordances plus the level() kernel API (notebook driver
cells).  Evidence screenshots land in build/evidence/.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "collapse_scenario.ipynb"
EVIDENCE = Path(__file__).resolve().parents[2] / "build" / "evidence"

#: the collapsed child's row text (multiplicity included) -- identical to
#: the expanded box's title, told apart by the sysml-row class
MOTORS = "motors : Motor [4]"
COLLAPSE_BUTTON = "button[title^='Collapse or expand']"


def _rows(page, text=MOTORS):
    return page.locator(".sprotty svg text.sysml-row", has_text=text)


def test_collapse_levels_and_compartment_folds(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=180)
    page = lab.page
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- expanded birth state: nested boxes, no parts rows -----------------
    page.wait_for_selector(".sprotty svg .elknode", state="attached", timeout=60_000)
    assert _rows(page).count() == 0  # motors is a drawn BOX, not a row
    assert page.locator(".sprotty svg text.elklabel", has_text=MOTORS).first.is_visible()
    nodes_before = lab.snapshot()["elknodes"]

    # -- the affordance: select the node, click the toolbar's collapse ----
    page.locator(".sprotty svg text.elklabel", has_text="QuadCopter").first.click()
    lab.wait_until(
        lambda s: page.locator(".sprotty svg .elknode.selected").count() >= 1,
        timeout=60,
        label="QuadCopter selected",
    )
    page.hover(".jp-ElkApp")  # the toolbar is hover-revealed
    page.screenshot(path=str(EVIDENCE / "collapse-affordance.png"))

    # -- click 1: PARTIAL -- rows under 'parts', proxy dot, selection kept --
    page.click(COLLAPSE_BUTTON)
    page.wait_for_selector(".sprotty svg text.sysml-row", state="attached", timeout=60_000)
    lab.wait_settled(min_widgets=1, timeout=120)
    assert _rows(page).count() >= 1, "motors did not become a 'name : Type' row"
    assert page.locator(".sprotty svg text.sysml-comp-label", has_text="parts").count() >= 1
    assert page.locator(".sprotty svg .sysml-port-proxy").count() >= 1, (
        "phaseLeads did not re-anchor as a proxy dot on the shrunken box"
    )
    # the selection survived the relayout (same node id, still selected)
    assert page.locator(".sprotty svg .elknode.selected").count() >= 1
    checker = lab.run_cell_json(index=-1)
    assert checker["levels"] == {"Rotorcraft::QuadCopter": "partial"}, checker
    assert checker["selection"] == ["Rotorcraft::QuadCopter"], checker
    assert checker["pipe_error"] is None, checker
    page.locator(".lgx-diagram").first.screenshot(path=str(EVIDENCE / "collapse-partial.png"))

    # -- click 2: COLLAPSED -- the name compartment alone -------------------
    page.hover(".jp-ElkApp")
    page.click(COLLAPSE_BUTTON)
    lab.wait_until(
        lambda s: _rows(page).count() == 0,
        timeout=120,
        label="the rows left with the compartment stack",
    )
    lab.wait_settled(min_widgets=1, timeout=120)
    # no compartment stack at all: QuadCopter's attribute rows and its
    # 'parts' header are gone (MultiRotor's own rows stay -- only the
    # SELECTED node shrank; 'rotorCount : Real = 4.0' is QuadCopter's row,
    # the abstract MultiRotor declares rotorCount without a value)
    assert (
        page.locator(".sprotty svg text.elklabel", has_text="rotorCount : Real = 4.0").count() == 0
    )
    assert page.locator(".sprotty svg text.sysml-comp-label", has_text="parts").count() == 0
    assert page.locator(".sprotty svg text.elklabel", has_text="QuadCopter").count() >= 1
    assert page.locator(".sprotty svg .sysml-port-proxy").count() >= 1  # edges stay re-anchored
    assert page.locator(".sprotty svg .elknode.selected").count() >= 1
    checker = lab.run_cell_json(index=-1)
    assert checker["levels"] == {"Rotorcraft::QuadCopter": "collapsed"}, checker
    assert checker["selection"] == ["Rotorcraft::QuadCopter"], checker
    page.locator(".lgx-diagram").first.screenshot(path=str(EVIDENCE / "collapse-name-only.png"))

    # -- click 3: back to EXPANDED, exactly ---------------------------------
    page.hover(".jp-ElkApp")
    page.click(COLLAPSE_BUTTON)
    lab.wait_until(
        lambda s: (
            page.locator(".sprotty svg text.elklabel", has_text=MOTORS).count() >= 1
            and _rows(page).count() == 0
        ),
        timeout=120,
        label="boxes restored",
    )
    state = lab.wait_settled(min_widgets=1, timeout=120)
    assert state["elknodes"] == nodes_before, state
    checker = lab.run_cell_json(index=-1)
    assert checker["levels"] == {}, checker
    page.locator(".lgx-diagram").first.screenshot(path=str(EVIDENCE / "collapse-reexpanded.png"))

    # -- child selection survives: a selected BOX becomes its selected ROW --
    page.locator(".sprotty svg text.elklabel", has_text=MOTORS).first.click()
    lab.wait_until(
        lambda s: "Rotorcraft::QuadCopter::motors" in lab.run_cell_json(index=-1)["selection"],
        timeout=60,
        label="motors box selected",
    )
    assert "partial" in lab.run_cell(index=1)  # the kernel API mirror
    lab.wait_settled(min_widgets=1, timeout=120)
    lab.wait_until(
        lambda s: (
            page.locator(".sprotty svg text.sysml-row.selected", has_text=MOTORS).count() >= 1
        ),
        timeout=60,
        label="the selected box became its selected row",
    )
    page.locator(".lgx-diagram").first.screenshot(path=str(EVIDENCE / "collapse-row-selection.png"))
    assert "expanded" in lab.run_cell(index=2)
    lab.wait_settled(min_widgets=1, timeout=120)
    lab.wait_until(
        lambda s: (
            page.locator(
                ".sprotty svg text.elklabel.selected:not(.sysml-row)", has_text=MOTORS
            ).count()
            >= 1
        ),
        timeout=60,
        label="the selected row became its selected box again",
    )
    checker = lab.run_cell_json(index=-1)
    assert checker["selection"] == ["Rotorcraft::QuadCopter::motors"], checker
    assert checker["levels"] == {}, checker

    # -- per-compartment fold: the header twist, OUTSIDE the selection seam --
    events_before = checker["select_events"]
    header = page.locator(".sprotty svg text.sysml-comp-label", has_text="attributes").first
    assert header.evaluate("el => getComputedStyle(el).cursor") == "pointer"
    rows_before = page.locator(".sprotty svg text.sysml-row").count()
    header.click()
    lab.wait_until(
        lambda s: (
            page.locator(".sprotty svg text.sysml-comp-label", has_text="\u25b8 attributes").count()
            >= 1
        ),
        timeout=120,
        label="the attributes compartment folded to its header",
    )
    lab.wait_settled(min_widgets=1, timeout=120)
    assert page.locator(".sprotty svg text.sysml-row").count() < rows_before
    # other compartments stay open (MultiRotor's constraints keep their rows)
    assert page.locator(".sprotty svg text.sysml-comp-label", has_text="\u25be").count() >= 1, (
        "every other compartment should keep its open twist"
    )
    checker = lab.run_cell_json(index=-1)
    folded = checker["folded"]
    assert list(folded.values()) == [["attributes"]], checker
    # seam discipline: the header click never touched the selection
    assert checker["selection"] == ["Rotorcraft::QuadCopter::motors"], checker
    assert checker["select_events"] == events_before, checker
    page.locator(".lgx-diagram").first.screenshot(path=str(EVIDENCE / "collapse-fold.png"))

    # a second click on the same (now folded) header unfolds it
    page.locator(".sprotty svg text.sysml-comp-label", has_text="\u25b8 attributes").first.click()
    lab.wait_until(
        lambda s: (
            page.locator(".sprotty svg text.sysml-comp-label", has_text="\u25b8 attributes").count()
            == 0
        ),
        timeout=120,
        label="the compartment unfolded",
    )
    checker = lab.run_cell_json(index=-1)
    assert checker["folded"] == {}, checker
    assert checker["selection"] == ["Rotorcraft::QuadCopter::motors"], checker

    lab.assert_no_errors()
