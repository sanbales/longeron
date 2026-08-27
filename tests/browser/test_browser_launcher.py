"""Browser truth for the launcher tile: click -> sidebar, NO notebook.

The maintainer's requirement, verbatim: *"so we don't have to run a
notebook to get the sysml interface to display"*.  So this tier opens a
BARE JupyterLab workspace (nothing but the launcher), finds the Longeron
tile among the builtins, clicks it, and requires the app's sidebar panel
to appear while ``.jp-Notebook`` stays at zero.  The click's machinery
(the dedicated ``longeron-app`` console session, the in-progress ->
success toast, second-click reuse) is asserted along the way; the
evidence screenshots land in ``build/evidence/``.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from .conftest import ARTIFACTS, REPO

if TYPE_CHECKING:
    from .conftest import LabPage, LabServer

EVIDENCE = REPO / "build" / "evidence"

#: the sidebar tab the kernel-side app stamps onto its panel
_APP_TAB = '.jp-SideBar.jp-mod-left .lm-TabBar-tab[data-lgxkey="longeron-app"]'

#: the launcher card whose label is exactly "Longeron"
_TILE = '.jp-LauncherCard[data-category="Other"] >> text="Longeron"'

_SESSIONS_JS = """() => {
    const app = window.jupyterapp || window.jupyterlab;
    return [...app.serviceManager.sessions.running()].map(
        (s) => ({path: s.path, name: s.name, type: s.type}));
}"""


def _open_bare_lab(lab: LabPage, workspace: str, timeout: float = 120.0) -> None:
    """A workspace with NOTHING in it: just the launcher tab."""

    lab.page.goto(
        f"{lab.server.base_url}/lab/workspaces/{workspace}?token={lab.server.token}&reset",
        wait_until="domcontentloaded",
    )
    lab.page.wait_for_selector(".jp-Launcher", state="visible", timeout=timeout * 1000)
    # same modal guard as open_notebook: a visible dialog blocks every click
    lab.page.add_locator_handler(
        lab.page.locator(".jp-Dialog .jp-mod-reject"),
        lambda button: button.click(),
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lab.page.evaluate("() => !!(window.jupyterapp || window.jupyterlab)"):
            return
        time.sleep(1)
    raise TimeoutError("JupyterLab app handle never appeared for the bare workspace")


def test_launcher_tile_opens_the_sidebar_without_a_notebook(
    lab: LabPage, lab_server: LabServer
) -> None:
    page = lab.page
    _open_bare_lab(lab, "launcher-proof")
    EVIDENCE.mkdir(parents=True, exist_ok=True)

    # -- the tile sits in the launcher grid, next to the builtins ----------
    tile = page.locator(_TILE)
    tile.wait_for(state="visible", timeout=60_000)
    assert page.locator(".jp-LauncherCard").count() >= 3, "expected builtin tiles around ours"
    assert page.locator(".jp-Notebook").count() == 0
    assert page.locator(_APP_TAB).count() == 0
    page.screenshot(path=str(EVIDENCE / "launcher-tile.png"))

    # -- click: kernel starts, app docks, toast reports success ------------
    tile.click()
    page.wait_for_selector(
        '.Toastify__toast:has-text("Longeron is ready")', state="attached", timeout=120_000
    )
    page.wait_for_selector(_APP_TAB, state="attached", timeout=60_000)
    # the sweeper REVEALS the panel (JupyterLab does not activate left-area
    # additions itself): the app's own widget must become visible
    page.wait_for_selector(".lgx-app", state="visible", timeout=60_000)

    # the money proof: the sysml interface is up and NO notebook ever opened
    assert page.locator(".jp-Notebook").count() == 0
    # the engine room is one dedicated console session on the constant path
    sessions = [s for s in page.evaluate(_SESSIONS_JS) if s["path"] == "longeron-app"]
    assert len(sessions) == 1, f"expected the one longeron-app session, got {sessions}"
    assert page.locator(".jp-CodeConsole").count() == 1
    page.screenshot(path=str(EVIDENCE / "launcher-sidebar-open.png"))

    # -- second click: reuse, not duplication -------------------------------
    # the launcher tab is still current (the console opened unfocused)
    tile.click()
    page.wait_for_selector(
        '.Toastify__toast:has-text("Longeron is ready")', state="attached", timeout=60_000
    )
    # the kernel-side open() is idempotent: it REPLACES its one panel, so
    # give the swap a beat, then require exactly one tab / one session again
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if page.locator(_APP_TAB).count() == 1:
            break
        time.sleep(0.5)
    assert page.locator(_APP_TAB).count() == 1
    sessions = [s for s in page.evaluate(_SESSIONS_JS) if s["path"] == "longeron-app"]
    assert len(sessions) == 1, f"second click duplicated the session: {sessions}"
    assert page.locator(".jp-CodeConsole").count() == 1, "second click duplicated the console"
    assert page.locator(".jp-Notebook").count() == 0

    try:
        lab.assert_no_errors()
    except AssertionError:
        lab.save_artifacts(ARTIFACTS, "launcher-tile-errors")
        raise
    sys.stderr.write("launcher tile: sidebar opened with zero notebooks, one session\n")
