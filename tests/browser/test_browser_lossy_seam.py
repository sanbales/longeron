"""Scenario: the time seam under INJECTED comm-message loss.

The widget protocol has no retransmit, so a dropped comm message used
to leave the kernel and a front-end permanently split.  The flagship
casualty was the timeseam scenario's state split (two CI runs): a
scrub-to-20 while the replay player ran correctly STOPPED the playback,
but the kernel kept reporting ``player_time`` ~74.7 forever -- part of
the seek's effect arrived, part never did.  These tests recreate that
class DETERMINISTICALLY: kernel-side injectors (armed by dormant
notebook cells) swallow a counted number of comm messages in one
direction, and the seam must converge anyway through the
reconciliation protocol (:mod:`longeron.widgets._seam`): generation
stamps, acknowledged reports, rejection re-pushes, and the
trailing-edge verify.

* **the dropped seek push** (the acceptance scenario): with the next
  THREE kernel->player state updates swallowed, a scrub during the
  player's own playback must still stop the player and land every
  playhead on the scrubbed time -- the player's stale ~4 Hz reports are
  rejected and each rejection re-asserts full truth until one re-push
  survives.  Without the fix the drop erases the seek: the player keeps
  playing and its reports drag the kernel clock along past the scrub.
* **the dropped report**: with the next player->kernel update
  swallowed, a scrub of the player's own slider vanishes in flight.
  The kernel is the source of truth, so the seam heals by REVERTING:
  the front-end's trailing-edge verify asks the kernel to re-state
  truth and the player's slider returns to the kernel time (the user
  sees the revert and retries -- visible, convergent, never a silent
  split).  Without the fix the player shows the scrub and the kernel
  never learns of it, forever.

The checker also reports each injector's drop count, so the tests
prove the loss actually happened AND healed (a zero count would mean
the scenario tested nothing).
"""

import time

import pytest

pytestmark = pytest.mark.browser

NOTEBOOK = "lossy_seam_scenario.ipynb"

_STATE_JS = """() => {
    const player = document.querySelector('.longeron-replay');
    const pscrub = player.querySelector('input[type=range]');
    const button = player.querySelector('.longeron-replay-bar button');
    const scrub = document.querySelector('.lgn-scrub .lgw-slider');
    return {
        playerButton: button.textContent,
        playerScrub: parseFloat(pscrub.value),
        scrub: parseFloat(scrub.value),
    };
}"""

#: scrub a slider (the scrubber's, or the player's own) like a user
_SCRUB_JS = """([selector, t]) => {
    const scrub = document.querySelector(selector);
    scrub.value = String(t);
    scrub.dispatchEvent(new Event('input', {bubbles: true}));
}"""

SCRUBBER = ".lgn-scrub .lgw-slider"
PLAYER_SCRUB = ".longeron-replay input[type=range]"


def _wait(lab, predicate, *, timeout: float = 15.0, label: str = "state") -> dict:
    deadline = time.monotonic() + timeout
    state: dict = {}
    while time.monotonic() < deadline:
        state = dict(lab.page.evaluate(_STATE_JS))
        if predicate(state):
            return state
        time.sleep(0.25)
    raise TimeoutError(f"{label} not reached within {timeout}s; last: {state}")


def _checker(lab, predicate, *, timeout: float = 15.0, label: str = "checker") -> dict:
    deadline = time.monotonic() + timeout
    checker: dict = {}
    while time.monotonic() < deadline:
        checker = lab.run_cell_json(index=-1)
        if predicate(checker):
            return checker
        time.sleep(0.5)
    raise TimeoutError(f"{label} not reached within {timeout}s; last: {checker}")


def _boot(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=240)
    lab.page.wait_for_selector(".longeron-replay svg", state="attached", timeout=60_000)
    lab.page.wait_for_selector(SCRUBBER, state="attached", timeout=60_000)
    lab.run_cell(index=3)  # arm: the injector cells were dormant in run-all


def test_a_dropped_seek_push_heals_and_the_scrub_wins(lab):
    _boot(lab)

    # the player's own playback runs and reports at ~4 Hz
    lab.page.click(".longeron-replay-bar button")
    _wait(
        lab,
        lambda s: s["playerButton"] == "\u275a\u275a" and s["playerScrub"] > 2.0,
        label="the player playing past t=2",
    )
    checker = _checker(
        lab,
        lambda c: c["player_time"] > 1.0,
        label="the kernel clock following the playback",
    )

    # swallow the next THREE kernel->player state updates, then scrub
    lab.run_cell(index=1)
    lab.page.evaluate(_SCRUB_JS, [SCRUBBER, 20.0])

    # the seek push is dropped, but the player's stale reports are
    # rejected and every rejection re-asserts full truth: one re-push
    # survives the budget, the player stops and adopts the scrub
    state = _wait(
        lab,
        lambda s: s["playerButton"] == "\u25b6" and abs(s["playerScrub"] - 20.0) <= 1.0,
        label="the player stopped on the scrubbed time despite the drops",
    )
    assert abs(state["scrub"] - 20.0) <= 1.0, state  # no backward snap
    checker = _checker(
        lab,
        lambda c: abs(c["player_time"] - 20.0) <= 0.5 and c["playing"] is False,
        label="the kernel seam converged on the scrub",
    )
    assert checker["clock_t"] == pytest.approx(checker["player_time"], abs=1e-3)
    assert checker["scrub_time"] == pytest.approx(checker["clock_t"], abs=0.5)
    assert checker["drops"]["push"]["dropped"] >= 1, checker  # the loss was real
    lab.assert_no_errors()


def test_a_dropped_report_reverts_to_kernel_truth(lab):
    _boot(lab)

    # settle the seam mid-span with a healthy scrub first
    lab.page.evaluate(_SCRUB_JS, [SCRUBBER, 40.0])
    _checker(
        lab,
        lambda c: abs(c["clock_t"] - 40.0) <= 0.5,
        label="the healthy scrub landing on the clock",
    )

    # swallow the next player->kernel update, then scrub the PLAYER
    lab.run_cell(index=2)
    lab.page.evaluate(_SCRUB_JS, [PLAYER_SCRUB, 120.0])
    state = dict(lab.page.evaluate(_STATE_JS))
    assert state["playerScrub"] == pytest.approx(120.0, abs=1.0), state

    # the report vanished: the kernel never saw 120.  The trailing-edge
    # verify (~1.5s) asks for truth and the player REVERTS to it --
    # visible and convergent, never a silent permanent split.
    state = _wait(
        lab,
        lambda s: abs(s["playerScrub"] - 40.0) <= 1.0,
        timeout=20.0,
        label="the player reverting to kernel truth",
    )
    checker = lab.run_cell_json(index=-1)
    assert checker["clock_t"] == pytest.approx(40.0, abs=0.5)
    assert checker["player_time"] == pytest.approx(checker["clock_t"], abs=1e-3)
    assert checker["drops"]["report"]["dropped"] == 1, checker  # the loss was real
    assert abs(state["scrub"] - 40.0) <= 1.0, state  # the scrubber never moved
    lab.assert_no_errors()
