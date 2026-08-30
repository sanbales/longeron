"""Scenario: compartment rows are first-class selectable elements.

A compartment row is the textual projection of a model element (an
attribute usage, a part usage...), so clicking it must ride the SAME
selection seam as a node click: the browser's select tool reports the
row's id (the element's qualified name), the kernel resolves it, the
explorer's tree selects + reveals the ATTRIBUTE itself, and the adopted
app's item inspector shows that attribute's sheet.  Kernel-initiated
selection (the tree -> row direction) must light the row back up.

The scenario also proves the compartment PRESENTATION browser-truth:
the 'attributes' header renders with its full-width separator rule
(the vendored view's LOCAL PATCH 13), rows carry the pointer-cursor
hover affordance, and everything stays visible under the dark theme
(evidence screenshots land in build/evidence/).
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "row_selection_scenario.ipynb"
EVIDENCE = Path(__file__).resolve().parents[2] / "build" / "evidence"

#: the torque attribute row's rendered text (value included)
ROW_TEXT = "torque : Real = 42.0"


def _row(page, text=ROW_TEXT):
    return page.locator(".sprotty svg text.sysml-row", has_text=text).first


def test_row_click_and_tree_round_trip(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(min_widgets=1, timeout=180)
    page = lab.page

    # -- presentation: header + separator rule + hover affordance ---------
    page.wait_for_selector(".sprotty svg text.sysml-comp-label", state="attached", timeout=60_000)
    header = page.locator(".sprotty svg text.sysml-comp-label", has_text="attributes").first
    assert header.text_content() == "attributes"
    rules = page.locator(".sprotty svg path.sysml-comp-rule")
    assert rules.count() >= 1, "no compartment separator rule rendered (LOCAL PATCH 13)"
    row = _row(page)
    assert row.evaluate("el => getComputedStyle(el).cursor") == "pointer"

    # -- diagram row click -> tree + inspector (the full linked-views path)
    row.click()
    lab.wait_until(
        lambda s: "torque" in (page.locator(".lgx-row.lgx-selected").first.text_content() or ""),
        timeout=60,
        label="tree reveal after row click",
    )
    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Gear::Winch::torque", checker
    assert checker["selected"] == ["Gear::Winch::torque"], checker
    assert checker["inspector"] == "Gear::Winch::torque", checker
    # the row itself carries the selection styling class
    assert page.locator(".sprotty svg text.sysml-row.selected", has_text="torque").count() >= 1

    # -- evidence: the clicked row + the inspector sheet ------------------
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.wait_for_selector(".lgx-insp-host", state="visible", timeout=60_000)
    name_input = page.locator(".lgx-insp-host .lgx-insp-name input")
    lab.wait_until(
        lambda s: name_input.input_value() == "torque",
        timeout=60,
        label="inspector shows the clicked row's element",
    )
    page.screenshot(path=str(EVIDENCE / "compartments-row-clicked-inspector.png"))
    page.locator(".lgx-diagram").first.screenshot(
        path=str(EVIDENCE / "compartments-row-selected.png")
    )

    # -- tree -> row: kernel-initiated selection lights the row -----------
    page.locator(".lgx-row", has_text="inertia").first.click()
    lab.wait_until(
        lambda s: (
            page.locator(".sprotty svg text.sysml-row.selected", has_text="inertia").count() >= 1
        ),
        timeout=60,
        label="row highlight after tree click",
    )
    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Gear::Winch::inertia", checker
    assert checker["diagram_selection"] == ["Gear::Winch::inertia"], checker

    # -- dark mode sanity --------------------------------------------------
    page.evaluate(
        "() => (window.jupyterapp || window.jupyterlab).commands.execute("
        "'apputils:change-theme', { theme: 'JupyterLab Dark' })"
    )
    lab.wait_until(
        lambda s: page.evaluate(
            "() => document.body.getAttribute('data-jp-theme-light') === 'false'"
        ),
        timeout=60,
        label="dark theme applied",
    )
    assert _row(page, "inertia").is_visible()
    assert page.locator(".sprotty svg path.sysml-comp-rule").count() >= 1
    page.locator(".lgx-diagram").first.screenshot(path=str(EVIDENCE / "compartments-dark-mode.png"))
    page.evaluate(
        "() => (window.jupyterapp || window.jupyterlab).commands.execute("
        "'apputils:change-theme', { theme: 'JupyterLab Light' })"
    )

    lab.assert_no_errors()
