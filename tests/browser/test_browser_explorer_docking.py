"""Scenario 6: the docked explorer is a well-behaved JupyterLab citizen.

Two browser-truth requirements (the 0.10.0 tranche-1 bugs):

1. NO PILE-UP -- restart-kernel + run-all leaves exactly ONE live explorer
   panel: the fresh kernel's :class:`~longeron.explorer._DockSweeper`
   closes the dead kernel's orphaned panel through lumino's own tab-close
   path (the Python-side registry cannot reach it -- its comm is dead);
2. NO SQUEEZE -- the default ``mode="tab-after"`` docks the explorer as a
   background main-area tab, so running the notebook never narrows its
   cells (``split-right`` used to steal half the width at dock time).

The restart is driven through the real command registry
(``notebook:restart-run-all`` -- the id JupyterLab 4.6 registers, verified
against the live registry below), including ACCEPTING the restart
confirmation dialog exactly like a user would.

Evidence screenshots land in ``build/evidence/``.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "explorer_dock_scenario.ipynb"
EVIDENCE = Path(__file__).resolve().parents[2] / "build" / "evidence"

#: the docked panel node (tagged browser-side by the panel's sweeper)
PANEL = ".lgx-explorer.lgx-explorer-dock-demo"
#: the panel's dock TAB (lumino renders title.dataset as data-* attributes,
#: lowercased by setAttribute -- hence the flat spelling)
TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="dock-demo"]'

#: kernel-initiated selection trips setSelectedNodes in the vendored
#: jupyter-elk frontend before the sprotty model index exists -- same
#: known vendor issue tests/browser/test_browser_explorer.py documents
KNOWN_VENDOR_PAGE_ERRORS = ("Cannot read properties of undefined (reading 'getById')",)

_CELL_WIDTH_JS = """() => {
    const cell = document.querySelector('.jp-Notebook .jp-Cell');
    return cell ? cell.getBoundingClientRect().width : 0;
}"""

#: tab-width tolerance: a vertical scrollbar appearing after run-all may
#: shave ~15px off the cells; a forced split would halve them (~700px)
WIDTH_TOLERANCE_PX = 30

_PANEL_DIAGRAM_VISIBLE_JS = """() => {
    const node = document.querySelector('.lgx-explorer .sprotty svg .elknode');
    if (!node) return false;
    const rect = node.getBoundingClientRect();
    return rect.width > 10 && rect.height > 10;
}"""


def _tab_stamps(page) -> list[str]:
    return list(page.eval_on_selector_all(TAB, "tabs => tabs.map(t => t.dataset.lgxstamp)"))


def test_restart_run_all_keeps_one_panel_and_full_width_cells(lab):
    lab.open_notebook(NOTEBOOK)
    page = lab.page

    # the restart command's EXACT id, verified against the live registry
    assert page.evaluate(
        "() => (window.jupyterapp || window.jupyterlab)"
        ".commands.listCommands().includes('notebook:restart-run-all')"
    )

    width_before = page.evaluate(_CELL_WIDTH_JS)
    assert width_before > 0

    # -- first run-all: ONE panel docks, the notebook keeps its width ------
    lab.run_all()
    lab.wait_settled(timeout=180)
    lab.wait_until(
        lambda s: page.locator(PANEL).count() == 1 and len(_tab_stamps(page)) == 1,
        timeout=120,
        label="one docked explorer panel after run-all",
    )
    first_stamps = _tab_stamps(page)
    checker = lab.run_cell_json(index=-1)
    assert checker["strategy"] == "lab", checker
    assert checker["mode"] == "tab-after", checker
    assert checker["key"] == "dock-demo", checker
    # the manufactured orphan (scenario cell 2) was closed by the SWEEPER:
    # its kernel-side handle was wiped, so nothing else could have
    assert checker["swept"] >= 1, checker

    width_after_dock = page.evaluate(_CELL_WIDTH_JS)
    assert width_after_dock >= width_before - WIDTH_TOLERANCE_PX, (
        f"tab-after must not squeeze the notebook: {width_before} -> {width_after_dock}"
    )

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCE / "explorer-dock-first-run.png"))

    # -- restart + run-all: the fresh panel REPLACES the orphan ------------
    # the conftest auto-REJECTS any dialog (kernel-picker guard); the
    # restart confirmation must be ACCEPTED instead, so drop that handler
    # and click the dialog's warn/accept button ("Restart") ourselves
    page.remove_locator_handler(page.locator(".jp-Dialog .jp-mod-reject"))
    page.evaluate(
        # fire-and-forget: the promise resolves only when the whole
        # restarted run finishes (see LabPage.run_all for the rationale)
        "() => { void (window.jupyterapp || window.jupyterlab)"
        ".commands.execute('notebook:restart-run-all'); return true; }"
    )
    page.locator(".jp-Dialog .jp-mod-accept.jp-mod-warn").click(timeout=30_000)

    # the run has re-docked when a tab with a NEWER stamp appears; requiring
    # EXACTLY one tab + one panel (two stable polls) proves replacement --
    # a pile-up would hold two tabs, a sweep failure the old stamp
    lab.wait_until(
        lambda s: (
            page.locator(PANEL).count() == 1
            and _tab_stamps(page) != first_stamps
            and len(_tab_stamps(page)) == 1
        ),
        timeout=240,
        label="exactly one live explorer panel after restart + run-all",
    )
    lab.wait_settled(timeout=180)
    second_stamps = _tab_stamps(page)
    assert len(second_stamps) == 1 and second_stamps != first_stamps

    checker = lab.run_cell_json(index=-1)
    assert checker["strategy"] == "lab", checker
    assert checker["swept"] >= 1, checker  # the sweep fired again post-restart

    width_after_restart = page.evaluate(_CELL_WIDTH_JS)
    assert width_after_restart >= width_before - WIDTH_TOLERANCE_PX, (
        f"restart+run-all must not squeeze the notebook: {width_before} -> {width_after_restart}"
    )
    page.screenshot(path=str(EVIDENCE / "explorer-dock-after-restart-run-all.png"))

    # -- open the tab like a user would: the panel is alive ---------------
    page.locator(TAB).click()
    page.wait_for_selector(f"{PANEL} .lgx-row", state="visible", timeout=60_000)
    page.wait_for_selector(f"{PANEL} .sprotty svg .elknode", state="attached", timeout=60_000)
    # the first reveal triggers a kernel-side re-fit (the initial auto-fit
    # aimed at a hidden, zero-sized viewport): the diagram must actually
    # OCCUPY the pane, not merely exist in the DOM
    lab.wait_until(
        lambda s: page.evaluate(_PANEL_DIAGRAM_VISIBLE_JS),
        timeout=60,
        label="diagram re-fits on the panel's first reveal",
    )
    page.screenshot(path=str(EVIDENCE / "explorer-dock-panel-open.png"))

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)
