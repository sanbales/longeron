"""Scenario 10: tutorial 14 VERBATIM (the maintainer's live-session flow).

Every QA-3 finding was reported from a live NB14 session, and the
paraphrased ``app_scenario.ipynb`` (scenario 8/9) never reproduced them
-- because it drives the panels by CLICK after the run settles, while
NB14 launches its tabs from CELLS mid-run and then displays
``application.inspector`` INLINE (cell 12).  So this scenario runs the
real ``notebooks/14_model_app.ipynb`` (synced into the lab root by
conftest, with ``examples/drone.sysml`` beside it for cell 3's relative
path) and asserts the three maintainer findings stay fixed:

* **the ScoutMini Score tab renders COLORS**: NB14's scout model now
  carries ``measure`` attributes (finding 2's demo half), so the
  scoreboard cells are real utility colors, not an all-hatched gray
  blob; the legend footer stays hidden (nothing is unmeasured);
* **the inspector survives NB14's own flow** (finding 3): cell 5's
  ``explore_model`` seeds the seam, whose first element reveals the
  right-sidebar inspector once -- and cell 12's INLINE display of the
  same widget must NOT collapse it again (the second sweeper view's
  synthetic clicks on the CURRENT tab were lumino's collapse gesture;
  the anti-toggle guards pin that).  A tree click in the explorer tab
  then updates the docked sheet;
* **the console stays clean** (finding 1): the kernel-side selections
  NB14 fires before the first diagram layout used to throw the vendored
  ``getById`` TypeError (vendor patch 11 queues them instead); this
  scenario asserts NO page or console errors, with no allowances.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "notebooks/14_model_app.ipynb"
REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "build" / "evidence"

EXPLORER_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="drone-sysml"]'
SCOREBOARD_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="scoreboard-scout-mini"]'
INSPECTOR_TAB = '.jp-SideBar.jp-mod-right .lm-TabBar-tab[data-lgxkey="longeron-inspector"]'

#: the scoreboard's rendered truth: host geometry, every cell's fill
#: (colors are ``rgb(...)``; the unmeasured hatch is ``url(#...-hatch)``),
#: and whether the honest-unmeasured legend footer shows
_SCOREBOARD_STATE_JS = """() => {
  const host = document.querySelector('.lgn-sb-host');
  const rect = host ? host.getBoundingClientRect() : {width: 0, height: 0};
  const fills = [...document.querySelectorAll('.lgn-sb-cell')].map(
    (cell) => cell.getAttribute('fill') || '');
  const legend = document.querySelector('.lgn-sb-legend');
  return {
    hostW: rect.width,
    hostH: rect.height,
    fills,
    legendVisible: Boolean(legend && getComputedStyle(legend).display !== 'none'),
  };
}"""

#: the DOCKED inspector's truth (scoped to the right sidebar's stack: the
#: inline copy in cell 12's output also carries .lgx-insp-host)
_DOCKED_INSPECTOR_JS = """() => {
  const stack = document.querySelector('#jp-right-stack');
  const host = stack ? stack.querySelector('.lgx-insp-host') : null;
  const rect = host ? host.getBoundingClientRect() : {width: 0, height: 0};
  const name = host ? host.querySelector('.lgx-insp-name input') : null;
  return {
    docked: Boolean(host),
    visible: rect.width > 0 && rect.height > 0,
    name: name ? name.value : null,
  };
}"""


def test_nb14_verbatim_score_colors_inspector_reveal_clean_console(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=240)
    page = lab.page

    # -- finding 2: the Score tab NB14 launches from cell 5 renders real
    # utility COLORS (its scout model measures both leaves now), at real
    # size (the sweeper's reveal click handed the panel its geometry)
    page.wait_for_selector(SCOREBOARD_TAB, state="attached", timeout=120_000)
    lab.wait_until(
        lambda s: (lambda sb: len(sb["fills"]) == 2 and sb["hostW"] > 300 and sb["hostH"] > 150)(
            page.evaluate(_SCOREBOARD_STATE_JS)
        ),
        timeout=120,
        label="the NB14 scoreboard tab renders both cells at real size",
    )
    board = page.evaluate(_SCOREBOARD_STATE_JS)
    assert all(fill.startswith("rgb(") for fill in board["fills"]), board  # COLORS, not hatch
    assert board["legendVisible"] is False, board  # nothing unmeasured: no footer
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.locator(".lgn-sb-host").screenshot(path=str(EVIDENCE / "nb14-scoreboard-colors.png"))

    # -- finding 3: the docked inspector is REVEALED after the whole run --
    # cell 5's seed revealed it once, and cell 12's inline display (a
    # second view of the same widget) must not have toggled it shut
    page.wait_for_selector(INSPECTOR_TAB, state="attached", timeout=60_000)
    lab.wait_until(
        lambda s: page.evaluate(_DOCKED_INSPECTOR_JS)["visible"],
        timeout=60,
        label="the right-sidebar inspector stays revealed after NB14's run",
    )
    sheet = page.evaluate(_DOCKED_INSPECTOR_JS)
    # cells 7/12 selected Drone::QuadCopter through the seam
    assert sheet["name"] == "QuadCopter", sheet

    # -- a real tree click in the explorer tab updates the docked sheet
    page.locator(EXPLORER_TAB).first.click()  # background tab: reveal it
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)
    page.locator('.lgx-explorer .lgx-row:has-text("Battery")').first.click()
    lab.wait_until(
        lambda s: (
            page.evaluate(_DOCKED_INSPECTOR_JS)
            == {
                "docked": True,
                "visible": True,
                "name": "Battery",
            }
        ),
        timeout=60,
        label="the docked sheet follows a tree click, sidebar still revealed",
    )
    page.screenshot(path=str(EVIDENCE / "nb14-inspector-revealed.png"))

    # -- finding 1: a CLEAN console, no allowances -- the vendored getById
    # race (patch 11) fired on exactly this flow before the fix
    assert not [e for e in lab.page_errors if "getById" in e], lab.page_errors
    lab.assert_no_errors()
    (EVIDENCE / "nb14-console.txt").write_text(
        "\n".join(["== page errors ==", *lab.page_errors, "== console ==", *lab.console]),
        encoding="utf-8",
    )
