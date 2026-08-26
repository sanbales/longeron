"""Scenarios 8 + 9: the sidebar model app and its item inspector.

Scenario 8 is one bounded end-to-end pass over the maintainer's spec
(including the four QA findings against the first shipped app):
``open()`` puts an ICON-ONLY longeron tab in the LEFT sidebar --
an svg glyph sized like the builtin tabs, NO visible text label
(finding 1) -- idempotently (the notebook re-opens and the tab count
must stay one); the ``longeron:open-app`` palette command reveals the
live panel (finding 2's honest launcher alternative); the path field +
Load button load ``examples/drone.sysml`` through the kernel; the Score
button splits honestly -- disabled with a tooltip for drone.sysml
(requirement def, no usages) and LIVE for the notebook's ScoutMini
model, whose launched tab must actually RENDER its hatched treemap
cells (finding 3: the pre-activated dock left the panel 0x0, an empty
tab); and the row's Explore button docks a real explorer tab.  The
checker cell closes the browser -> kernel loop.

Scenario 9 drives the ITEM INSPECTOR (RIGHT sidebar, same idempotence
contract): launching an explorer feeds the app's selection seam, whose
FIRST element now auto-reveals the inspector tab once (finding 4 -- the
collapsed-by-design docking failed discoverability); clicking a tree
row fills the sheet (screenshotted with the right sidebar EXPANDED);
a unit-bearing attribute shows its bracket unit in the value field;
typing a new name + Enter commits through ``longeron.edit.rename`` --
the explorer tree relabels and the models-list row grows its dirty dot
-- and a colliding rename surfaces the honest-refusal error strip with
the field reverted.
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
SCOREBOARD_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="scoreboard-scout-mini"]'
DRONE_ROW = '.lgx-app-row:has-text("drone.sysml")'
SCOUT_ROW = '.lgx-app-row:has-text("scout mini")'

#: same known vendored-frontend page error the explorer scenarios allow:
#: kernel-initiated selection can trip setSelectedNodes before the sprotty
#: index exists (see test_browser_explorer.py); the app launches explorers,
#: so it inherits the allowance
KNOWN_VENDOR_PAGE_ERRORS = ("Cannot read properties of undefined (reading 'getById')",)

#: one measurement of both sidebar tabs against a builtin one: the svg
#: identity, rendered svg size, and the label's text/height (icon-only
#: means EMPTY label text -- JupyterLab renders sidebar labels rotated,
#: it never hides them, so any text would show; maintainer finding 1)
_TAB_ANATOMY_JS = """() => {
  const grab = (tab) => {
    if (!tab) return null;
    const svg = tab.querySelector('.lm-TabBar-tabIcon svg');
    const label = tab.querySelector('.lm-TabBar-tabLabel');
    return {
      icon: svg ? svg.getAttribute('data-icon') : null,
      svgW: svg ? svg.getBoundingClientRect().width : 0,
      svgH: svg ? svg.getBoundingClientRect().height : 0,
      labelText: label ? label.textContent : '',
      title: tab.getAttribute('title') || '',
    };
  };
  const builtin = [...document.querySelectorAll(
    '.jp-SideBar.jp-mod-left .lm-TabBar-tab')].find((t) => !t.dataset.lgxkey);
  return {
    app: grab(document.querySelector(
      '.jp-SideBar.jp-mod-left .lm-TabBar-tab[data-lgxkey="longeron-app"]')),
    inspector: grab(document.querySelector(
      '.jp-SideBar.jp-mod-right .lm-TabBar-tab[data-lgxkey="longeron-inspector"]')),
    builtin: grab(builtin),
  };
}"""

#: the scoreboard tab's rendered truth: the host's real geometry (the
#: maintainer's EMPTY tab was a 0x0 panel with fully-built cells inside)
#: and the treemap cell count
_SCOREBOARD_STATE_JS = """() => {
  const host = document.querySelector('.lgn-sb-host');
  const rect = host ? host.getBoundingClientRect() : {width: 0, height: 0};
  return {
    hostW: rect.width,
    hostH: rect.height,
    cells: document.querySelectorAll('.lgn-sb-cell').length,
  };
}"""


def _reveal_app_panel(lab):
    """The app panel visible, whether or not the sweeper's reveal won."""

    page = lab.page
    try:
        page.wait_for_selector(".lgx-app-host", state="visible", timeout=30_000)
    except Exception:
        page.locator(APP_TAB).first.click()
        page.wait_for_selector(".lgx-app-host", state="visible", timeout=30_000)


def test_app_sidebar_loads_a_model_and_launches_tabs(lab):
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

    # -- finding 1: ICON-ONLY tabs, sized like the builtins ----------------
    # the ipylab Icon lands asynchronously (a comm round trip); poll until
    # the svg carries our icon name, then judge size parity and label text
    lab.wait_until(
        lambda s: (page.evaluate(_TAB_ANATOMY_JS)["app"] or {}).get("icon") == "longeron:app",
        timeout=60,
        label="the app tab renders the longeron:app svg icon",
    )
    anatomy = page.evaluate(_TAB_ANATOMY_JS)
    assert anatomy["app"]["labelText"] == "", anatomy  # NO visible text
    assert anatomy["app"]["title"].startswith("Longeron")  # hover caption
    assert anatomy["inspector"]["icon"] == "longeron:inspector", anatomy
    assert anatomy["inspector"]["labelText"] == "", anatomy
    # size parity with the builtin sidebar icons (20px, maintainer spec)
    assert 18 <= anatomy["app"]["svgW"] <= 22, anatomy
    assert abs(anatomy["app"]["svgW"] - anatomy["builtin"]["svgW"]) <= 2, anatomy
    assert 18 <= anatomy["inspector"]["svgW"] <= 22, anatomy
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.locator(".jp-SideBar.jp-mod-left").screenshot(
        path=str(EVIDENCE / "app-sidebar-tabstrip.png")
    )

    # -- the panel reveals itself (the sweeper clicks its own tab) ---------
    _reveal_app_panel(lab)
    # cell 3 added ScoutMini: one models-list row, no empty hint
    assert page.locator(".lgx-app-empty").count() == 0
    assert page.locator(SCOUT_ROW).count() == 1
    # maintainer QA chrome: NO wordmark row (the tab icon is the identity)
    assert page.locator(".lgx-app-brand").count() == 0

    # -- load examples/drone.sysml through the path field ------------------
    page.fill(".lgx-app-path input", str(DRONE))
    page.click("button.lgx-app-load")
    page.wait_for_selector(DRONE_ROW, state="attached", timeout=60_000)
    # drone.sysml carries a requirement DEF but no usages: Score disabled
    # WITH the honest tooltip; ScoutMini's requirement usages keep its live
    drone_score = page.locator(f"{DRONE_ROW} button.lgx-app-score")
    assert drone_score.is_disabled()
    assert drone_score.get_attribute("title") == "No requirement usages in this model"
    scout_score = page.locator(f"{SCOUT_ROW} button.lgx-app-score")
    assert not scout_score.is_disabled()
    # Save is dirty-gated -- a freshly loaded model has nothing to save
    assert page.locator(f"{DRONE_ROW} button.lgx-app-save").is_disabled()

    page.locator(".lgx-app-host").screenshot(path=str(EVIDENCE / "app-sidebar-model-loaded.png"))

    # -- maintainer QA chrome: the loaded rows, the opened browse listing,
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

    # -- finding 3: a launched scoreboard tab actually RENDERS -------------
    # (the old pre-activated dock left the panel 0x0: cells existed in the
    # DOM but the tab showed nothing; the sweeper's real synthetic tab
    # click must now hand the panel its geometry)
    scout_score.click()
    page.wait_for_selector(SCOREBOARD_TAB, state="attached", timeout=120_000)
    lab.wait_until(
        lambda s: (lambda st: st["cells"] == 2 and st["hostW"] > 300 and st["hostH"] > 150)(
            page.evaluate(_SCOREBOARD_STATE_JS)
        ),
        timeout=120,
        label="the scoreboard tab renders its hatched cells at real size",
    )
    page.locator(".lgn-sb-host").screenshot(path=str(EVIDENCE / "app-scoreboard-rendered.png"))

    # -- launch an explorer tab from the drone row -------------------------
    page.click(f"{DRONE_ROW} button.lgx-app-explore")
    page.wait_for_selector(EXPLORER_TAB, state="attached", timeout=120_000)
    page.locator(EXPLORER_TAB).first.click()  # background tab: reveal it
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)
    page.screenshot(path=str(EVIDENCE / "app-explorer-launched.png"))

    # -- the kernel-side truth (entries, current model, inspector seam) ----
    checker = lab.run_cell_json(index=-1)
    assert checker["models"] == ["inline demo text", "drone.sysml"], checker
    assert checker["origins"] == ["text", "file"], checker
    assert checker["current"] == "drone.sysml", checker
    assert checker["explorers"] == 1, checker
    # the explorer's initial selection (the flattened root package) already
    # flowed through the inspector seam
    assert checker["element"] == "Drone", checker
    assert checker["dirty"] is False, checker  # no edits: the row stays clean

    # -- finding 2: the palette command reveals the live panel -------------
    # (the honest launcher alternative: ipylab 1.1 exposes no ILauncher
    # surface, so `longeron:open-app` in the registry/palette is the
    # kernel-reachable entry point). Collapse the sidebar first: a click
    # on the CURRENT sidebar tab collapses it, then the command -- a full
    # frontend -> kernel -> sweeper-poke round trip -- must re-reveal.
    assert page.evaluate(
        "() => (window.jupyterapp || window.jupyterlab).commands.hasCommand('longeron:open-app')"
    )
    page.locator(APP_TAB).first.click()  # collapse
    page.wait_for_selector(".lgx-app-host", state="hidden", timeout=30_000)
    page.evaluate(
        "() => { void (window.jupyterapp || window.jupyterlab)"
        ".commands.execute('longeron:open-app'); return true; }"
    )
    page.wait_for_selector(".lgx-app-host", state="visible", timeout=60_000)

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)


def test_inspector_reveals_follows_selection_and_edits(lab):
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
    _reveal_app_panel(lab)
    # the inspector starts COLLAPSED: docked without reveal, one click away
    assert not page.locator(".lgx-insp-host").is_visible()
    page.fill(".lgx-app-path input", str(DRONE))
    page.click("button.lgx-app-load")
    page.wait_for_selector(DRONE_ROW, state="attached", timeout=60_000)
    # loading alone selects no ELEMENT: still collapsed (finding 4 -- the
    # reveal is selection-driven, not load-driven)
    assert not page.locator(".lgx-insp-host").is_visible()

    # -- launch the explorer tab: its initial root selection feeds the seam
    # and the FIRST seam element auto-reveals the inspector ONCE ----------
    page.click(f"{DRONE_ROW} button.lgx-app-explore")
    page.wait_for_selector(EXPLORER_TAB, state="attached", timeout=120_000)
    page.wait_for_selector(".lgx-insp-host", state="visible", timeout=60_000)
    page.locator(EXPLORER_TAB).first.click()  # background tab: reveal it
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)

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
    # the maintainer-requested proof: the WHOLE window, right sidebar
    # EXPANDED, sheet showing the element selected in the explorer tab
    page.screenshot(path=str(EVIDENCE / "inspector-selection-from-explorer.png"))

    # -- finding 5: a quantity-valued attribute shows its bracket unit ------
    # (attribute rows render lazily: expand QuadCopter's subtree first --
    # the twist toggles expansion without touching the selection)
    page.locator('.lgx-explorer .lgx-row:has-text("QuadCopter") .lgx-twist').first.click()
    page.wait_for_selector(
        '.lgx-explorer .lgx-row:has-text("maxTakeoffMass")', state="attached", timeout=30_000
    )
    page.locator('.lgx-explorer .lgx-row:has-text("maxTakeoffMass")').first.click()
    value_input = page.locator(".lgx-insp-host .lgx-insp-valuefield input")
    lab.wait_until(
        lambda s: value_input.input_value() == "1.5 [SI::kg]",
        timeout=60,
        label="inspector value field renders the SI::kg bracket unit",
    )
    page.locator(".lgx-insp-host").screenshot(path=str(EVIDENCE / "inspector-value-units.png"))

    # -- rename: type + Enter commits through edit.rename -------------------
    page.locator('.lgx-explorer .lgx-row:has-text("QuadCopter")').first.click()
    lab.wait_until(
        lambda s: name_input.input_value() == "QuadCopter",
        timeout=60,
        label="inspector back on QuadCopter",
    )
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
    assert not page.locator(f"{DRONE_ROW} button.lgx-app-save").is_disabled()
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

    # -- the kernel-side truth: the rename landed, the tracker is dirty,
    # and the INSPECTOR itself holds the selected element (finding 4's
    # end-to-end wiring, asserted at the kernel too) ------------------------
    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Drone::HexaCopter", checker
    assert checker["inspector_element"] == "Drone::HexaCopter", checker
    assert checker["dirty"] is True, checker

    lab.assert_no_errors(allow_page_errors=KNOWN_VENDOR_PAGE_ERRORS)
