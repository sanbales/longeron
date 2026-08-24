"""Scenario 1: the notation gallery renders end to end in a real browser.

The strongest single signal the tier has: 96 cells build ~23 diagram
widgets exercising every implemented SysML v2 glyph, the browser lays all
of them out (elkjs + text sizing run client-side), and the AutoFitTool
moves each viewport off the identity transform.  Anything stuck busy, any
progress bar left visible, or any console/page error fails the sweep.
"""

import pytest

pytestmark = pytest.mark.browser

GALLERY = "11_notation_gallery.ipynb"
#: the notebook renders 23 diagram widgets today; thresholds keep slack
#: (see tests/browser/README.md -- never assert exact counts)
MIN_DIAGRAMS = 20
#: 21 of them auto-fit today (tiny diagrams may fit at the identity)
MIN_FITTED = 15


def test_gallery_runs_all_and_settles(lab):
    lab.open_notebook(GALLERY)
    lab.run_all()
    state = lab.wait_settled(min_widgets=MIN_DIAGRAMS, min_fitted=MIN_FITTED, timeout=480)
    assert state["busy"] == 0, state
    assert state["bars"] == [], state
    assert state["rendered"] >= MIN_DIAGRAMS, state
    assert state["fitted"] >= MIN_FITTED, state
    lab.assert_no_errors()
