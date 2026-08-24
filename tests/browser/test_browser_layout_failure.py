"""Scenario 5: a broken layout must fail LOUDLY -- the F10 canary.

The notebook poisons ``elk.algorithm`` so the browser-side elkjs layout
throws.  Under the F10 semantics (vendored ipyelk patch 9), the error
stops the resend loop immediately, surfaces on ``pipe.status.exception``,
and the progress bar fills as a persistent visible warning -- instead of
the old behavior, a forever-spinning sliver starving the notebook.

Console errors are NOT asserted absent here: the frontend legitimately
logs the layout failure.  Page errors (uncaught exceptions) must still be
zero -- the failure is channeled, not crashing.
"""

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "layout_failure_scenario.ipynb"


def _warned(state):
    """A visible, FULL, warning-styled progress bar (the F10 presentation)."""

    return any(bar["warning"] and bar["width"] == "100%" for bar in state["bars"])


def test_broken_layout_surfaces_visible_error(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()

    # the bar must land full-and-visible... and STAY that way (stable_polls
    # guards against reading a mid-flight bar that then resumes spinning)
    state = lab.wait_until(_warned, timeout=120, stable_polls=3, label="warning bar")
    assert state["elknodes"] == 0, f"the broken diagram somehow rendered: {state}"

    # kernel-side truth: the pipe recorded the exception, the bar warned
    checker = lab.run_cell_json(index=-1)
    assert checker["exception"], f"pipe.status.exception is empty: {checker}"
    assert checker["bar_style"] == "warning", checker
    assert checker["bar_full"] is True, checker

    # channeled, not crashing: no uncaught page errors
    assert lab.page_errors == [], lab.page_errors
