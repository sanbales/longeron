"""Scenario 8: the sidebar model app, in a real JupyterLab.

One bounded end-to-end pass over the maintainer's spec: ``open()`` puts
a longeron panel in the LEFT sidebar (idempotently -- the notebook
re-opens and the tab count must stay one), the path field + Load button
load ``examples/drone.sysml`` through the kernel, the model row appears
in the list (Score disabled: drone has a requirement def but no usages),
and the row's Explore button docks a real explorer tab in the main area.
The checker cell closes the browser -> kernel loop: the entries list,
the current model, and the inspector-seam element the launched explorer
delivered on its initial selection.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "app_scenario.ipynb"
REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "build" / "evidence"
DRONE = REPO / "examples" / "drone.sysml"

APP_TAB = '.jp-SideBar.jp-mod-left .lm-TabBar-tab[data-lgxkey="longeron-app"]'
EXPLORER_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="drone-sysml"]'

#: same known vendored-frontend page error the explorer scenarios allow:
#: kernel-initiated selection can trip setSelectedNodes before the sprotty
#: index exists (see test_browser_explorer.py); the app launches explorers,
#: so it inherits the allowance
KNOWN_VENDOR_PAGE_ERRORS = ("Cannot read properties of undefined (reading 'getById')",)


def test_app_sidebar_loads_a_model_and_launches_an_explorer(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=180)
    page = lab.page

    # -- the sidebar presence, idempotent: exactly ONE longeron-app tab
    # (cell 2 re-opened the app; the registry must have replaced cell 1's
    # panel, and closed tabs leave the DOM asynchronously -- poll)
    page.wait_for_selector(APP_TAB, state="attached", timeout=60_000)
    lab.wait_until(
        lambda s: page.locator(APP_TAB).count() == 1,
        timeout=60,
        label="exactly one longeron-app sidebar tab",
    )

    # -- the panel reveals itself (the sweeper clicks its own tab); if the
    # reveal lost a race, one real tab click recovers it
    try:
        page.wait_for_selector(".lgx-app-host", state="visible", timeout=30_000)
    except Exception:
        page.locator(APP_TAB).first.click()
        page.wait_for_selector(".lgx-app-host", state="visible", timeout=30_000)
    assert page.locator(".lgx-app-empty").count() == 1  # no models yet

    # -- load examples/drone.sysml through the path field ------------------
    page.fill(".lgx-app-path input", str(DRONE))
    page.click("button.lgx-app-load")
    page.wait_for_selector(".lgx-app-row", state="attached", timeout=60_000)
    row = page.locator(".lgx-app-row").first
    assert "drone.sysml" in (row.text_content() or "")
    # drone.sysml carries a requirement DEF but no usages: Score disabled
    assert page.locator("button.lgx-app-score").first.is_disabled()
    assert not page.locator("button.lgx-app-save").first.is_disabled()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.locator(".lgx-app-host").screenshot(path=str(EVIDENCE / "app-sidebar-model-loaded.png"))

    # -- launch an explorer tab from the row -------------------------------
    page.click("button.lgx-app-explore")
    page.wait_for_selector(EXPLORER_TAB, state="attached", timeout=120_000)
    page.locator(EXPLORER_TAB).first.click()  # background tab: reveal it
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)
    page.screenshot(path=str(EVIDENCE / "app-explorer-launched.png"))

    # -- the kernel-side truth (entries, current model, inspector seam) ----
    checker = lab.run_cell_json(index=-1)
    assert checker["models"] == ["drone.sysml"], checker
    assert checker["origins"] == ["file"], checker
    assert checker["current"] == "drone.sysml", checker
    assert checker["explorers"] == 1, checker
    # the explorer's initial selection (the flattened root package) already
    # flowed through the inspector seam
    assert checker["element"] == "Drone", checker

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)
