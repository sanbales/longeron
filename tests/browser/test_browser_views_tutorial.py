"""Scenario 10: tutorial 3 VERBATIM (the maintainer's live-session flow).

The QA-3 findings were reported from live tutorial sessions, and the
paraphrased ``app_scenario.ipynb`` (scenario 8/9) never reproduced them
-- because it drives the panels by CLICK after the run settles, while
the tutorial launches its tabs from CELLS mid-run.  So this scenario
runs the real ``notebooks/03_views_for_review.ipynb`` (synced into the
lab root by conftest, with ``examples/deepscout`` beside it for the
notebook's relative path) and asserts the maintainer findings stay
fixed:

* **the inspector survives the tutorial's own flow** (finding 3): the
  app section's ``explore_model`` seeds the seam, whose first element
  reveals the right-sidebar inspector once -- and the notebook's later
  in-cell selections, renames of the SELECTED element, and refused
  edits must leave it revealed with the final selection
  (``Rotorcraft::QuadCopter``, re-selected by the relationship-sheet
  cell and renamed away and back by the editing cells).  A real tree
  click in the explorer tab then updates the docked sheet;
* **the console stays clean** (finding 1): the kernel-side selections
  the tutorial fires before the first diagram layout used to throw the
  vendored ``getById`` TypeError (vendor patch 11 queues them instead);
  this scenario asserts NO page or console errors, with no allowances.
  Tutorial 3 lays out MORE diagrams than the retired model-app tutorial
  (the inline explorer, the standalone views, the toolbar), so the
  guard bites harder here.

The retired model-app tutorial also asserted score COLORS on a launched
scoreboard tab; tutorial 3 launches no Score tab (the scoreboard is
tutorial 6's), so that assertion lives on in scenario 8
(``test_browser_app.py``, rendered scoreboard) and the dashboard
scenario (colored cells).
"""

import sys
from pathlib import Path

import pytest

from .conftest import _shutdown_sessions

pytestmark = pytest.mark.browser

NOTEBOOK = "notebooks/03_views_for_review.ipynb"
REPO = Path(__file__).resolve().parents[2]
EVIDENCE = REPO / "build" / "evidence"

EXPLORER_TAB = '#jp-main-dock-panel .lm-TabBar-tab[data-lgxkey="deepscout"]'
INSPECTOR_TAB = '.jp-SideBar.jp-mod-right .lm-TabBar-tab[data-lgxkey="longeron-inspector"]'

#: the DOCKED inspector's truth (scoped to the right sidebar's stack: an
#: inline widget view would also carry .lgx-insp-host)
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


def _inspector_follows_the_tutorial(lab, page) -> None:
    """The post-run inspector contract (finding 3), one attempt.

    Any raise (a wait never held, the sheet shows the wrong element, a
    selector never attached) lets the caller retry from a fresh session:
    one widget comm message lost during the run-all burst (the
    parked-pipeline class, see conftest.wait_until) can leave a viewer,
    the seam-selection relay, or the docked sheet itself on a dead comm
    -- symptoms that surface HERE, long after the run itself settled.
    """

    # the app section's explore_model seeded the seam, and the editing
    # cells (rename away and back, refused unit writes, save) must not
    # have collapsed it or left it on a stale element
    page.wait_for_selector(EXPLORER_TAB, state="attached", timeout=120_000)
    page.wait_for_selector(INSPECTOR_TAB, state="attached", timeout=60_000)
    lab.wait_until(
        lambda s: page.evaluate(_DOCKED_INSPECTOR_JS)["visible"],
        timeout=60,
        label="the right-sidebar inspector stays revealed after the tutorial's run",
    )
    sheet = page.evaluate(_DOCKED_INSPECTOR_JS)
    # the relationship-sheet cell's endpoint click selected
    # Rotorcraft::QuadCopter; the editing cells renamed it away and back
    assert sheet["name"] == "QuadCopter", sheet

    # -- a real tree click in the explorer tab updates the docked sheet
    page.locator(EXPLORER_TAB).first.click()  # background tab: reveal it
    page.wait_for_selector(".lgx-explorer .lgx-row", state="attached", timeout=60_000)
    # the Battery def lives in the parts catalog: expand down to it
    # (exact-name spans: import rows like 'import ScoutParts::F450Kit::*'
    # substring-match the package names and carry no twist).  Expansion is
    # conditional so a retry on a re-collapsed tree never toggles an
    # already-open row shut.
    for parent, child in (("ScoutParts", "F450Kit"), ("F450Kit", "Battery")):
        child_row = f'.lgx-explorer .lgx-row:has(.lgx-name:text-is("{child}"))'
        parent_row = f'.lgx-explorer .lgx-row:has(.lgx-name:text-is("{parent}"))'
        if not page.locator(child_row).count():
            page.locator(parent_row).first.locator(".lgx-twist").click()
            page.wait_for_selector(child_row, state="attached", timeout=30_000)
    page.locator('.lgx-explorer .lgx-row:has(.lgx-name:text-is("Battery"))').first.click()
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


def test_nb03_verbatim_inspector_reveal_clean_console(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=240)
    page = lab.page

    # -- finding 3: the docked inspector is REVEALED after the whole run --
    # self-healing, and loudly: the conftest refire ladder already recovers
    # parked pipelines DURING each settle, but a comm that died in the
    # run-all burst can wedge widgets a soft re-run REUSES (live-observed:
    # the docked sheet's relay stayed dead through three run-all rebuilds,
    # and a wedged kernel answered no probe even after reconnect+interrupt).
    # Nothing browser-side heals a dead comm, so each retry starts CLEAN --
    # fresh kernel session, fresh workspace, fresh widgets -- with a stderr
    # breadcrumb keeping every heal a counted flake, not a silent absorb.
    for attempt in (1, 2, 3):
        try:
            if attempt > 1:
                _shutdown_sessions(lab.server)
                lab.open_notebook(NOTEBOOK)
                # rerun semantics for the console contract too: the aborted
                # attempt's own noise and the session teardown's are harness-
                # induced; finding 1 is asserted against the attempt that
                # delivers the verdict
                lab.console.clear()
                lab.page_errors.clear()
                lab.run_all()
                lab.wait_settled(timeout=240)
            _inspector_follows_the_tutorial(lab, page)
            break
        except Exception as err:  # rerun semantics: ANY failure retries fresh
            if attempt == 3:
                raise
            sys.stderr.write(
                f"nb03: inspector contract failed on attempt {attempt} ({err}); "
                "retrying from a fresh kernel session and workspace\n"
            )
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(EVIDENCE / "nb03-inspector-revealed.png"))

    # -- finding 1: a CLEAN console, no allowances -- the vendored getById
    # race (patch 11) fired on exactly this launch-tabs-from-cells flow
    assert not [e for e in lab.page_errors if "getById" in e], lab.page_errors
    lab.assert_no_errors()
    (EVIDENCE / "nb03-console.txt").write_text(
        "\n".join(["== page errors ==", *lab.page_errors, "== console ==", *lab.console]),
        encoding="utf-8",
    )
