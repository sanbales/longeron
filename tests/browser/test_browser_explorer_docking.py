"""Scenario 6: the docked explorer is a well-behaved JupyterLab citizen.

Two browser-truth requirements (the 0.10.0 tranche-1 bugs):

1. NO PILE-UP -- restart-kernel + run-all leaves exactly ONE live explorer
   panel: the fresh kernel's :class:`~longeron.explorer._DockSweeper`
   closes the dead kernel's orphaned panel through lumino's own tab-close
   path (the Python-side registry cannot reach it -- its comm is dead);
2. NO SQUEEZE -- the default ``mode="tab-after"`` docks the explorer as a
   background main-area tab, so running the notebook never narrows its
   cells (``split-right`` used to steal half the width at dock time);
3. FULL PANE -- once the tab is opened, the diagram FILLS the pane
   vertically (the layout chain flex-grows the diagram box) instead of
   rendering as a ~400px strip above dead space.

The restart is driven through the real command registry
(``notebook:restart-run-all`` -- the id JupyterLab 4.6 registers, verified
against the live registry below), including ACCEPTING the restart
confirmation dialog exactly like a user would.

Evidence screenshots land in ``build/evidence/``.
"""

import time
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

#: the docked pane must FILL the tab: the sprotty svg's rendered height
#: against the panel's content height (the pre-0.10.0 bug rendered a
#: ~400px strip -- the diagram box did not flex-grow, so the widget's
#: min-height floor acted as its height)
_PANEL_FILL_JS = """() => {
    const panel = document.querySelector('.lgx-explorer.lgx-explorer-dock-demo');
    if (!panel) return null;
    const svg = panel.querySelector('.sprotty svg.sprotty-graph');
    if (!svg) return null;
    return {
        panel: panel.getBoundingClientRect().height,
        svg: svg.getBoundingClientRect().height,
    };
}"""


def _tab_stamps(page) -> list[str]:
    return list(page.eval_on_selector_all(TAB, "tabs => tabs.map(t => t.dataset.lgxstamp)"))


def _swept_checker(lab, *, timeout: float = 90.0) -> dict:
    """The checker JSON once ``swept >= 1`` has propagated (or the last state).

    The sweep happens BROWSER-side and reaches the kernel as a trait
    sync; under CI load the checker cell can execute before that comm
    message lands and read a stale 0. Re-running the (print-only,
    idempotent) checker keeps the assertion about WHETHER the sweep
    fired, not about how fast comm messages travel on a 2-core runner.

    The checker read itself goes over a FRESH kernel connection
    (:meth:`LabPage.run_cell`), so a broken shared connection cannot
    swallow it; a ``TimeoutError`` here means the kernel side truly
    did not answer, which is worth one more attempt within the budget.
    """

    deadline = time.monotonic() + timeout
    while True:
        try:
            checker = lab.run_cell_json(index=-1)
        except TimeoutError:
            # one hosed attempt (execute requests lost in a re-wiring
            # session) is retryable within the same deadline
            if time.monotonic() >= deadline:
                raise
            continue
        if checker.get("swept", 0) >= 1 or time.monotonic() >= deadline:
            return checker
        time.sleep(2)


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
    checker = _swept_checker(lab)
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
    # restore the conftest belt: any LATER dialog (e.g. a file-changed
    # prompt racing an autosave) blocks every pointer interaction below
    page.add_locator_handler(
        page.locator(".jp-Dialog .jp-mod-reject"),
        lambda button: button.click(),
    )

    # gate on PROOF the execute channel survived the restart before
    # waiting for its effects: the indicator says Idle even while the
    # restarted session swallows every execute (the CI artifacts), so
    # only a completed execute round trip may open this phase
    lab.wait_execute_channel_ready(timeout=120)

    # the run has re-docked when a tab with a NEWER stamp appears; requiring
    # EXACTLY one tab + one panel (two stable polls) proves replacement --
    # a pile-up would hold two tabs, a sweep failure the old stamp.
    # restart-run-all's run-all half can be LOST outright on a loaded
    # runner (cells pinned at [*] with an idle kernel: the execute requests
    # went into the dying session; seen on CI and under local load), so
    # between bounded waits RE-FIRE run-all -- safe by the feature's own
    # contract (docking is idempotent per model: REPLACE, never stack)
    deadline = time.monotonic() + 240
    while True:
        try:
            lab.wait_until(
                lambda s: (
                    page.locator(PANEL).count() == 1
                    and _tab_stamps(page) != first_stamps
                    and len(_tab_stamps(page)) == 1
                ),
                timeout=max(min(80.0, deadline - time.monotonic()), 10.0),
                label="exactly one live explorer panel after restart + run-all",
            )
            break
        except TimeoutError:
            if time.monotonic() >= deadline:
                raise
            page.evaluate(
                "() => { void (window.jupyterapp || window.jupyterlab)"
                ".commands.execute('notebook:run-all-cells'); return true; }"
            )
    lab.wait_settled(timeout=180)
    second_stamps = _tab_stamps(page)
    assert len(second_stamps) == 1 and second_stamps != first_stamps

    checker = _swept_checker(lab)
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
    # the diagram must FILL the pane vertically (>= 80% of the panel's
    # content height), not render as a ~400px strip above dead space
    fill = page.evaluate(_PANEL_FILL_JS)
    assert fill is not None and fill["panel"] > 300, fill
    assert fill["svg"] >= 0.8 * fill["panel"], (
        f"the diagram must fill the docked pane, not a ~400px strip: {fill}"
    )
    page.screenshot(path=str(EVIDENCE / "explorer-dock-panel-open.png"))

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)
