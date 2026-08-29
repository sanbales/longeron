"""Scenarios 8 + 9: the sidebar model app and its item inspector.

Scenario 8 is one bounded end-to-end pass over the maintainer's spec
(including the four QA findings against the first shipped app):
``open()`` puts an ICON-ONLY longeron tab in the LEFT sidebar --
an svg glyph sized like the builtin tabs, NO visible text label
(finding 1) -- idempotently (the notebook re-opens and the tab count
must stay one); the ``longeron:open-app`` palette command reveals the
live panel (finding 2's honest launcher alternative); the path field +
Load button load ``examples/deepscout`` through the kernel; the Score
button splits honestly -- live for the deepscout program (its geometric
installation requirements are usages) and for the notebook's ScoutMini
model, disabled with a tooltip for the notebook's defs-only model
(requirement def, no usages); the ScoutMini scoreboard tab
must actually RENDER its hatched treemap
cells (finding 3: the pre-activated dock left the panel 0x0, an empty
tab); and the row's Explore button docks a real explorer tab.  The
checker cell closes the browser -> kernel loop.

Scenario 9 drives the ITEM INSPECTOR (RIGHT sidebar, same idempotence
contract): launching an explorer feeds the app's selection seam, whose
FIRST element now auto-reveals the inspector tab once (finding 4 -- the
collapsed-by-design docking failed discoverability); clicking a tree
row fills the sheet (screenshotted with the right sidebar EXPANDED);
a unit-bearing attribute shows its unit FIRST-CLASS (the compact
``1.5 kg`` value plus the dedicated ``kg \u2014 mass`` unit row);
clicking a relationship row renders the relationship sheet (clickable
endpoints + the full declaration -- the maintainer's 'I can't inspect
relationships' finding); typing a new name + Enter commits through
``longeron.edit.rename`` --
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
DRONE = REPO / "examples" / "deepscout"

APP_TAB = '.jp-SideBar.jp-mod-left .lm-TabBar-tab[data-lgxkey="longeron-app"]'
INSPECTOR_TAB = '.jp-SideBar.jp-mod-right .lm-TabBar-tab[data-lgxkey="longeron-inspector"]'
EXPLORER_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="deepscout"]'
SCOREBOARD_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="scoreboard-scout-mini"]'
DRONE_ROW = '.lgx-app-row:has-text("deepscout")'
SCOUT_ROW = '.lgx-app-row:has-text("scout mini")'
DEFS_ROW = '.lgx-app-row:has-text("bare defs")'
RELS_ROW = '.lgx-app-row:has-text("rels demo")'
RELS_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="rels-demo"]'

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
#: maintainer's EMPTY tab was a 0x0 panel with fully-built cells inside),
#: the treemap cell count, and the honest-unmeasured legend footer
_SCOREBOARD_STATE_JS = """() => {
  const host = document.querySelector('.lgn-sb-host');
  const rect = host ? host.getBoundingClientRect() : {width: 0, height: 0};
  const legend = document.querySelector('.lgn-sb-legend');
  return {
    hostW: rect.width,
    hostH: rect.height,
    cells: document.querySelectorAll('.lgn-sb-cell').length,
    legendVisible: Boolean(legend && getComputedStyle(legend).display !== 'none'),
    legendText: legend ? legend.textContent : '',
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
    # cell 3 added ScoutMini + the defs-only model: two models-list rows,
    # no empty hint
    assert page.locator(".lgx-app-empty").count() == 0
    assert page.locator(SCOUT_ROW).count() == 1
    assert page.locator(DEFS_ROW).count() == 1
    # maintainer QA chrome: NO wordmark row (the tab icon is the identity)
    assert page.locator(".lgx-app-brand").count() == 0

    # -- load examples/deepscout through the path field ------------------
    page.fill(".lgx-app-path input", str(DRONE))
    page.click("button.lgx-app-load")
    page.wait_for_selector(DRONE_ROW, state="attached", timeout=60_000)
    # the program's geometric installation requirements are USAGES: its
    # Score button is live, like ScoutMini's; the defs-only model (a
    # requirement def, no usages) keeps the honest disabled tooltip
    drone_score = page.locator(f"{DRONE_ROW} button.lgx-app-score")
    assert not drone_score.is_disabled()
    defs_score = page.locator(f"{DEFS_ROW} button.lgx-app-score")
    assert defs_score.is_disabled()
    assert defs_score.get_attribute("title") == "No requirement usages in this model"
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
    # the honest-unmeasured legend (maintainer QA: an all-hatched board
    # read as broken): ScoutMini's leaves are ALL unmeasured here, so the
    # one-line footer must name what the hatching means
    board = page.evaluate(_SCOREBOARD_STATE_JS)
    assert board["legendVisible"] is True, board
    assert "hatched = unmeasured (2 of 2" in board["legendText"], board
    page.locator(".lgn-sb-host").screenshot(path=str(EVIDENCE / "app-scoreboard-rendered.png"))
    page.locator(".lgn-sb-legend").screenshot(
        path=str(EVIDENCE / "app-scoreboard-unmeasured-legend.png")
    )

    # -- launch an explorer tab from the drone row -------------------------
    page.click(f"{DRONE_ROW} button.lgx-app-explore")
    page.wait_for_selector(EXPLORER_TAB, state="attached", timeout=120_000)
    page.locator(EXPLORER_TAB).first.click()  # background tab: reveal it
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)
    page.screenshot(path=str(EVIDENCE / "app-explorer-launched.png"))

    # -- the kernel-side truth (entries, current model, inspector seam) ----
    checker = lab.run_cell_json(index=-1)
    assert checker["models"] == [
        "inline demo text",
        "defs only text",
        "rels demo text",
        "deepscout",
    ], checker
    assert checker["origins"] == ["text", "text", "text", "dir"], checker
    assert checker["current"] == "deepscout", checker
    assert checker["explorers"] == 1, checker
    # the explorer's initial selection (the multi-package program's model
    # root, which carries no qualified name) already flowed through the
    # inspector seam
    assert checker["element"] is None, checker
    assert checker["element_type"] == "Model", checker
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

    lab.assert_no_errors()


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

    # -- reveal the app panel and load examples/deepscout ----------------
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
    # (the program tree opens on its six packages: expand the MultiRotor
    # branch first, then click the configuration)
    page.locator(
        '.lgx-explorer .lgx-row:has(.lgx-name:text-is("Rotorcraft")) .lgx-twist'
    ).first.click()
    page.wait_for_selector(
        '.lgx-explorer .lgx-row:has-text("QuadCopter")', state="attached", timeout=30_000
    )
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

    # -- finding 5: units are FIRST-CLASS -- the value field shows the
    # compact magnitude + symbol, and the dedicated unit row names the
    # symbol + dimension from the derived unit table
    # (attribute rows render lazily: maxTakeoffMass lives on the abstract
    # MultiRotor in the DeepScout package -- expand down to it first; the
    # twists toggle expansion without touching the selection)
    # (case-sensitive exact match on the name span: the workspace root row
    # is labeled 'deepscout' and Playwright's :has-text() is
    # case-INsensitive -- a substring selector collapses the whole tree)
    page.locator(
        '.lgx-explorer .lgx-row:has(.lgx-name:text-is("DeepScout")) .lgx-twist'
    ).first.click()
    page.wait_for_selector(
        '.lgx-explorer .lgx-row:has(.lgx-name:text-is("MultiRotor"))',
        state="attached",
        timeout=30_000,
    )
    page.locator(
        '.lgx-explorer .lgx-row:has(.lgx-name:text-is("MultiRotor")) .lgx-twist'
    ).first.click()
    page.wait_for_selector(
        '.lgx-explorer .lgx-row:has-text("maxTakeoffMass")', state="attached", timeout=30_000
    )
    page.locator('.lgx-explorer .lgx-row:has-text("maxTakeoffMass")').first.click()
    value_input = page.locator(".lgx-insp-host .lgx-insp-valuefield input")
    lab.wait_until(
        lambda s: value_input.input_value() == "1.5 kg",
        timeout=60,
        label="inspector value field renders the compact magnitude + unit",
    )
    unit_row = page.locator('.lgx-insp-host .lgx-insp-row:has-text("unit")')
    assert "kg \u2014 mass" in (unit_row.first.text_content() or "")
    typed_row = page.locator('.lgx-insp-host .lgx-insp-row:has-text("typed by")')
    assert "Real [kg]" in (typed_row.first.text_content() or "")
    page.locator(".lgx-insp-host").screenshot(path=str(EVIDENCE / "inspector-value-units.png"))

    # -- rename: type + Enter commits through edit.rename -------------------
    page.locator('.lgx-explorer .lgx-row:has-text("QuadCopter")').first.click()
    lab.wait_until(
        lambda s: name_input.input_value() == "QuadCopter",
        timeout=60,
        label="inspector back on QuadCopter",
    )
    name_input.fill("QuadCopterMk2")
    page.locator(".lgx-insp-host").screenshot(path=str(EVIDENCE / "inspector-rename-inflight.png"))
    name_input.press("Enter")
    # the explorer's tree payload rebuilt with the new label...
    lab.wait_until(
        lambda s: page.locator('.lgx-explorer .lgx-row:has-text("QuadCopterMk2")').count() >= 1,
        timeout=120,
        label="explorer tree relabels after the rename",
    )
    # ...and the models-list row shows the dirty dot. The entry's origin
    # is 'dir' (a workspace merge): Save now ENABLES, mapping the tracked
    # rename back to the file its package was loaded from -- the tooltip
    # names exactly what a click would write (only changed files are
    # ever rewritten). NOT clicked here: the load points at the real
    # examples/deepscout sources.
    lab.wait_until(
        lambda s: page.locator(".lgx-app-name.lgx-app-dirty").count() == 1,
        timeout=60,
        label="models row shows the dirty dot",
    )
    save_btn = page.locator(f"{DRONE_ROW} button.lgx-app-save")
    lab.wait_until(
        lambda s: not save_btn.is_disabled(),
        timeout=60,
        label="dir-origin Save enables once the tracked edit maps to its file",
    )
    save_title = save_btn.get_attribute("title") or ""
    assert "multirotor.sysml" in save_title, save_title  # QuadCopter's home file
    assert "changed file" in save_title, save_title
    page.locator(".lgx-app-host").screenshot(path=str(EVIDENCE / "app-models-dirty.png"))

    # -- a colliding rename is honestly refused: strip + revert -------------
    name_input.fill("TriCopter")  # a sibling in package Rotorcraft
    name_input.press("Enter")
    page.wait_for_selector(".lgx-insp-host .lgx-insp-error", state="visible", timeout=60_000)
    refusal = page.locator(".lgx-insp-host .lgx-insp-error").text_content() or ""
    assert "already used by another member" in refusal, refusal
    lab.wait_until(
        lambda s: name_input.input_value() == "QuadCopterMk2",
        timeout=60,
        label="refused rename reverts the name field",
    )
    page.locator(".lgx-insp-host").screenshot(path=str(EVIDENCE / "inspector-honest-refusal.png"))

    # -- the kernel-side truth: the rename landed, the tracker is dirty,
    # and the INSPECTOR itself holds the selected element (finding 4's
    # end-to-end wiring, asserted at the kernel too) ------------------------
    checker = lab.run_cell_json(index=-1)
    assert checker["element"] == "Rotorcraft::QuadCopterMk2", checker
    assert checker["inspector_element"] == "Rotorcraft::QuadCopterMk2", checker
    assert checker["dirty"] is True, checker

    lab.assert_no_errors()


def test_inspector_relationship_sheet(lab):
    """Relationship rows show in an app-launched tree (toggle ON by
    default) and clicking one renders the inspector's relationship
    sheet: clickable ENDPOINT rows that navigate the selection, plus
    the full declaration in a read-only block (the maintainer's 'I
    can't inspect relationships' finding)."""

    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=180)
    page = lab.page

    # -- launch the explorer for the notebook's RELATIONSHIPS model --------
    _reveal_app_panel(lab)
    page.click(f"{RELS_ROW} button.lgx-app-explore")
    page.wait_for_selector(RELS_TAB, state="attached", timeout=120_000)
    page.locator(RELS_TAB).first.click()  # background tab: reveal it
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)

    # -- the relationship rows are VISIBLE (toggle defaults ON) ------------
    page.wait_for_selector(".lgx-explorer .lgx-row.lgx-rel", state="attached", timeout=30_000)
    assert page.locator(".lgx-explorer .lgx-row.lgx-rel").count() == 2  # satisfy + connect
    relbtn = page.locator(".lgx-explorer .lgx-tree-relbtn")
    assert relbtn.get_attribute("aria-pressed") == "true"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.locator(".lgx-explorer").first.screenshot(
        path=str(EVIDENCE / "inspector-rels-1-tree-rows.png")
    )

    # -- click the connect row: the sheet shows both ends, clickable -------
    page.locator(".lgx-explorer .lgx-row.lgx-rel", has_text="connect axle to hub").first.click()
    page.wait_for_selector(".lgx-insp-host", state="visible", timeout=60_000)
    endpoints = page.locator(".lgx-insp-host .lgx-insp-endpoint button")
    lab.wait_until(
        lambda s: (
            endpoints.count() == 2
            and [(endpoints.nth(i).text_content() or "").strip() for i in range(2)]
            == ["axle", "hub"]
        ),
        timeout=60,
        label="connection sheet shows both endpoint rows",
    )
    declaration = page.locator(".lgx-insp-host .lgx-insp-decl")
    assert "connect axle to hub;" in (declaration.first.text_content() or "")
    page.locator(".lgx-insp-host").screenshot(
        path=str(EVIDENCE / "inspector-rels-2-connection-sheet.png")
    )

    # -- the satisfy: requirement + satisfier endpoints + declaration ------
    page.locator(".lgx-explorer .lgx-row.lgx-rel", has_text="satisfy massBudget").first.click()
    lab.wait_until(
        lambda s: (
            endpoints.count() == 2
            and [(endpoints.nth(i).text_content() or "").strip() for i in range(2)]
            == ["massBudget", "axle"]
        ),
        timeout=60,
        label="satisfy sheet shows the requirement + the satisfier",
    )
    assert "satisfy massBudget by axle;" in (declaration.first.text_content() or "")
    page.locator(".lgx-insp-host").screenshot(
        path=str(EVIDENCE / "inspector-rels-3-satisfy-sheet.png")
    )

    # -- an endpoint click NAVIGATES: the tree follows to the satisfier ----
    endpoints.nth(1).click()
    lab.wait_until(
        lambda s: (
            "axle"
            in (page.locator(".lgx-explorer .lgx-row.lgx-selected").first.text_content() or "")
        ),
        timeout=60,
        label="endpoint click reveals the target in the tree",
    )

    lab.assert_no_errors()
