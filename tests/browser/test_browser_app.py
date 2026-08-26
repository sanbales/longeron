"""Scenarios 8 + 9: the sidebar model app and its item inspector.

Scenario 8 is one bounded end-to-end pass over the maintainer's spec:
``open()`` puts a longeron panel in the LEFT sidebar (idempotently -- the
notebook re-opens and the tab count must stay one), the path field + Load
button load ``examples/drone.sysml`` through the kernel, the model row
appears in the list (Score disabled: drone has a requirement def but no
usages; Save disabled: a fresh load has no unsaved edits), and the row's
Explore button docks a real explorer tab in the main area.  The checker
cell closes the browser -> kernel loop: the entries list, the current
model, and the inspector-seam element the launched explorer delivered on
its initial selection.

Scenario 9 drives the ITEM INSPECTOR (RIGHT sidebar, same idempotence
contract): clicking a tree row fills the sheet; typing a new name +
Enter commits through ``longeron.edit.rename`` -- the explorer tree
relabels and the models-list row grows its dirty dot -- and a colliding
rename surfaces the honest-refusal error strip with the field reverted.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "app_scenario.ipynb"
REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "build" / "evidence"
DRONE = REPO / "examples" / "drone.sysml"

APP_TAB = '.jp-SideBar.jp-mod-left .lm-TabBar-tab[data-lgxkey="longeron-app"]'
INSPECTOR_TAB = '.jp-SideBar.jp-mod-right .lm-TabBar-tab[data-lgxkey="longeron-inspector"]'
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
    # maintainer QA chrome: NO wordmark row (the tab icon is the identity)
    assert page.locator(".lgx-app-brand").count() == 0

    # -- load examples/drone.sysml through the path field ------------------
    page.fill(".lgx-app-path input", str(DRONE))
    page.click("button.lgx-app-load")
    page.wait_for_selector(".lgx-app-row", state="attached", timeout=60_000)
    row = page.locator(".lgx-app-row").first
    assert "drone.sysml" in (row.text_content() or "")
    # drone.sysml carries a requirement DEF but no usages: Score disabled;
    # Save is dirty-gated -- a freshly loaded model has nothing to save
    assert page.locator("button.lgx-app-score").first.is_disabled()
    assert page.locator("button.lgx-app-save").first.is_disabled()

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.locator(".lgx-app-host").screenshot(path=str(EVIDENCE / "app-sidebar-model-loaded.png"))

    # -- maintainer QA chrome: the loaded row, the opened browse listing,
    # and the API fold must NOT widen the panel into a horizontal
    # scrollbar (long paths ellipsize with a title tooltip instead)
    page.click("button.lgx-app-browse-toggle")
    page.wait_for_selector(".lgx-app-browser", state="visible", timeout=30_000)
    page.locator(".lgx-app-api").get_by_text("Connect to API").first.click()
    page.wait_for_selector(".lgx-app-api-url input", state="visible", timeout=30_000)
    overflow = page.evaluate(
        "() => { const el = document.querySelector('.lgx-app-host');"
        " return el.scrollWidth - el.clientWidth; }"
    )
    assert overflow <= 1, f"sidebar overflows horizontally by {overflow}px"
    page.locator(".lgx-app-host").screenshot(path=str(EVIDENCE / "app-sidebar-no-overflow.png"))
    page.click("button.lgx-app-browse-toggle")  # fold the listing back up

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
    assert checker["dirty"] is False, checker  # no edits: the row stays clean

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)


def test_inspector_edits_rename_and_shows_honest_refusals(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=180)
    page = lab.page

    # -- both sidebar panels present, idempotently (cell 2 re-opened the
    # app, which rebuilds the inspector too: the sweepers must have closed
    # the first pair; closed tabs leave the DOM asynchronously -- poll)
    page.wait_for_selector(APP_TAB, state="attached", timeout=60_000)
    page.wait_for_selector(INSPECTOR_TAB, state="attached", timeout=60_000)
    lab.wait_until(
        lambda s: page.locator(APP_TAB).count() == 1 and page.locator(INSPECTOR_TAB).count() == 1,
        timeout=60,
        label="exactly one app tab and one inspector tab",
    )

    # -- reveal the app panel and load examples/drone.sysml ----------------
    try:
        page.wait_for_selector(".lgx-app-host", state="visible", timeout=30_000)
    except Exception:
        page.locator(APP_TAB).first.click()
        page.wait_for_selector(".lgx-app-host", state="visible", timeout=30_000)
    page.fill(".lgx-app-path input", str(DRONE))
    page.click("button.lgx-app-load")
    page.wait_for_selector(".lgx-app-row", state="attached", timeout=60_000)

    # -- launch the explorer tab and reveal it ------------------------------
    page.click("button.lgx-app-explore")
    page.wait_for_selector(EXPLORER_TAB, state="attached", timeout=120_000)
    page.locator(EXPLORER_TAB).first.click()
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)

    # -- reveal the inspector (docked collapsed: one click on its tab) ------
    page.locator(INSPECTOR_TAB).first.click()
    page.wait_for_selector(".lgx-insp-host", state="visible", timeout=30_000)

    # -- click a tree row; the sheet follows the selection ------------------
    page.locator('.lgx-explorer .lgx-row:has-text("QuadCopter")').first.click()
    name_input = page.locator(".lgx-insp-host .lgx-insp-name input")
    lab.wait_until(
        lambda s: name_input.input_value() == "QuadCopter",
        timeout=60,
        label="inspector shows the clicked element's name",
    )
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.locator(".lgx-insp-host").screenshot(path=str(EVIDENCE / "inspector-selected.png"))

    # -- rename: type + Enter commits through edit.rename -------------------
    name_input.fill("HexaCopter")
    page.locator(".lgx-insp-host").screenshot(path=str(EVIDENCE / "inspector-rename-inflight.png"))
    name_input.press("Enter")
    # the explorer's tree payload rebuilt with the new label...
    lab.wait_until(
        lambda s: page.locator('.lgx-explorer .lgx-row:has-text("HexaCopter")').count() >= 1,
        timeout=120,
        label="explorer tree relabels after the rename",
    )
    # ...and the models-list row shows the dirty dot (Save enabled)
    lab.wait_until(
        lambda s: page.locator(".lgx-app-name.lgx-app-dirty").count() == 1,
        timeout=60,
        label="models row shows the dirty dot",
    )
    assert not page.locator("button.lgx-app-save").first.is_disabled()
    page.locator(".lgx-app-host").screenshot(path=str(EVIDENCE / "app-models-dirty.png"))

    # -- a colliding rename is honestly refused: strip + revert -------------
    name_input.fill("Battery")  # a sibling of HexaCopter in package Drone
    name_input.press("Enter")
    page.wait_for_selector(".lgx-insp-host .lgx-insp-error", state="visible", timeout=60_000)
    refusal = page.locator(".lgx-insp-host .lgx-insp-error").text_content() or ""
    assert "already used by another member" in refusal, refusal
    lab.wait_until(
        lambda s: name_input.input_value() == "HexaCopter",
        timeout=60,
        label="refused rename reverts the name field",
    )
    page.locator(".lgx-insp-host").screenshot(path=str(EVIDENCE / "inspector-honest-refusal.png"))

    # -- the kernel-side truth: the rename landed, the tracker is dirty -----
    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Drone::HexaCopter", checker
    assert checker["dirty"] is True, checker

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)
