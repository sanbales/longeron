"""Scenario: the time seam's flagship -- the go-around sortie.

One clock links three views of one recording: the state-diagram replay
player, the scrubber, and the Cesium mission globe (bound to the
model-stated waypoints and epoch of ``DeepScout::goAroundSortie``).
The test proves the adopted contract in a real browser:

* **the scrub** -- the pre-display seek to t=100 (mid second go-around)
  renders every view mid-flight, and a later slider scrub moves every
  playhead, keeps ``airborne`` lit on the state diagram, and seeks the
  Cesium clock to the same instant;
* **play from the scrubber** -- both the scrubber and the Cesium clock
  advance together, and pausing converges every playhead exactly;
* **the Cesium-dial drive** -- driving ``clockViewModel.shouldAnimate``
  (the property the dial's play button writes) makes the scrubber
  follow: it advances monotonically (no oscillation, no backward
  snaps) with the drift bound held while both sides integrate locally;
* **the replay subscription** -- a scrub while the replay player's own
  playback runs stops that playback (the kernel seek lands on its
  ``time`` trait), and the seam's trait traffic stays at the ~4 Hz
  throttle.

Cesium loads from the pinned CDN; a front-end that cannot reach it
degrades to the printed offline notice, and the test SKIPS honestly
(the flake policy forbids failing on network truth).  On success the
flagship evidence lands in ``build/test-artifacts/timeseam/``: the
synchronized pair mid-goAround, the play, the dial drive with the
measured drift samples.
"""

import json
import time
from itertools import pairwise

import pytest

from .conftest import ARTIFACTS

pytestmark = pytest.mark.browser

NOTEBOOK = "timeseam_scenario.ipynb"
EVIDENCE = ARTIFACTS / "timeseam"

_STATE_JS = """() => {
    const stage = document.querySelector('.longeron-mission3d-stage');
    const viewer = stage && stage.longeronViewer;
    const scrub = document.querySelector('.lgn-scrub .lgw-slider');
    const readout = document.querySelector('.lgn-scrub-clock');
    const player = document.querySelector('.longeron-replay');
    const active = player
      ? [...player.querySelectorAll('.longeron-active')]
          .map((n) => n.getAttribute('data-qname'))
      : [];
    return {
        cesium: Boolean(viewer),
        offline: Boolean(document.querySelector('.longeron-mission3d-offline')),
        seconds: viewer ? window.Cesium.JulianDate.secondsDifference(
            viewer.clock.currentTime, viewer.clock.startTime) : null,
        animating: viewer ? viewer.clock.shouldAnimate : null,
        multiplier: viewer ? viewer.clock.multiplier : null,
        scrub: scrub ? parseFloat(scrub.value) : null,
        readout: readout ? parseFloat(readout.textContent) : null,
        active,
        playerButton: player
          ? player.querySelector('.longeron-replay-bar button').textContent
          : null,
    };
}"""

_SCRUB_JS = """(t) => {
    const scrub = document.querySelector('.lgn-scrub .lgw-slider');
    scrub.value = String(t);
    scrub.dispatchEvent(new Event('input', {bubbles: true}));
}"""

#: sample the scrubber readout (2-decimal truth) against the live Cesium
#: clock every ~200 ms; the two reads share one evaluate, so sampling
#: skew between them is microseconds
_SAMPLE_JS = """async (ms) => {
    const stage = document.querySelector('.longeron-mission3d-stage');
    const viewer = stage.longeronViewer;
    const readout = document.querySelector('.lgn-scrub-clock');
    const samples = [];
    const t0 = performance.now();
    while (performance.now() - t0 < ms) {
        samples.push({
            wall: Math.round(performance.now() - t0),
            scrub: parseFloat(readout.textContent),
            cesium: window.Cesium.JulianDate.secondsDifference(
                viewer.clock.currentTime, viewer.clock.startTime),
        });
        await new Promise((resolve) => setTimeout(resolve, 200));
    }
    return samples;
}"""

#: drive the Cesium dial: clockViewModel.shouldAnimate is the exact
#: property the animation widget's play/pause buttons write
_DIAL_JS = """(value) => {
    const stage = document.querySelector('.longeron-mission3d-stage');
    stage.longeronViewer.clockViewModel.shouldAnimate = value;
    stage.longeronViewer.scene.requestRender();
}"""


def _wait_for_cesium(lab, timeout: float = 120.0) -> dict:
    """The globe either boots (canvas + viewer handle) or reports the
    offline notice; a CDN miss is a SKIP, not a failure."""

    deadline = time.monotonic() + timeout
    state: dict = {}
    while time.monotonic() < deadline:
        state = dict(lab.page.evaluate(_STATE_JS))
        if state["cesium"]:
            return state
        if state["offline"]:
            pytest.skip("CesiumJS CDN unreachable: the globe degraded to the offline notice")
        time.sleep(1.0)
    raise TimeoutError(f"Cesium viewer never appeared: {state}")


def _wait_state(lab, predicate, *, timeout: float = 15.0, label: str = "state") -> dict:
    """Poll the DOM state until ``predicate`` holds (trait writes ride a
    kernel round trip, so DOM truth follows a browser action by a
    comm-latency beat)."""

    deadline = time.monotonic() + timeout
    state: dict = {}
    while time.monotonic() < deadline:
        state = dict(lab.page.evaluate(_STATE_JS))
        if predicate(state):
            return state
        time.sleep(0.25)
    raise TimeoutError(f"{label} not reached within {timeout}s; last: {state}")


def _evidence(lab, name: str) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    lab.page.screenshot(path=str(EVIDENCE / name), full_page=True)


def test_one_clock_scrubs_the_diagram_the_globe_and_the_scrubber(lab):
    lab.open_notebook(NOTEBOOK)
    lab.run_all()
    lab.wait_settled(timeout=240)
    lab.page.wait_for_selector(".longeron-replay svg", state="attached", timeout=60_000)
    lab.page.wait_for_selector(".lgn-scrub .lgw-slider", state="attached", timeout=60_000)
    _wait_for_cesium(lab)

    # ---- render-time adoption: the clock seeked to t=100 BEFORE the
    # views displayed, so every view must render mid second go-around
    state = _wait_state(
        lab,
        lambda s: (
            s["seconds"] is not None
            and abs(s["seconds"] - 100.0) <= 2e-3
            and s["readout"] is not None
            and abs(s["readout"] - 100.0) <= 0.01
        ),
        label="every view rendering at the pre-display seek",
    )
    assert state["active"] == ["DeepScout::SortieStates::airborne"], state
    checker = lab.run_cell_json(index=-1)
    assert checker["clock_t"] == pytest.approx(100.0, abs=1e-3)
    assert checker["phase"] == "route"
    assert checker["battery"] == 10
    _evidence(lab, "01-scrub-mid-goaround.png")

    # ---- the scrub: t=60 is mid FIRST go-around (battery at 40) ------
    lab.page.evaluate(_SCRUB_JS, 60.0)
    # the seek rides scrubber -> clock -> globe/player traits: poll the
    # DOM until the Cesium clock lands on the scrubbed instant (the
    # slider quantizes to span/500, so compare against ITS value)
    state = _wait_state(
        lab,
        lambda s: (
            s["seconds"] is not None
            and abs(s["scrub"] - 60.0) <= 0.5
            and abs(s["seconds"] - s["scrub"]) <= 2e-3
        ),
        label="the Cesium clock following the scrub",
    )
    assert state["active"] == ["DeepScout::SortieStates::airborne"], state
    scrubbed = state["scrub"]
    checker = lab.run_cell_json(index=-1)
    assert checker["clock_t"] == pytest.approx(scrubbed, abs=1e-3)
    assert checker["player_time"] == pytest.approx(scrubbed, abs=1e-3)
    assert checker["globe_time"] == pytest.approx(scrubbed, abs=1e-3)
    assert checker["phase"] == "route"
    assert checker["battery"] == 40

    # ---- play from the scrubber: both sides advance together ---------
    lab.page.click(".lgn-scrub-btn")
    time.sleep(2.5)
    state = dict(lab.page.evaluate(_STATE_JS))
    assert state["animating"] is True, state  # the bridge started the Cesium clock
    assert state["seconds"] > scrubbed + 0.5, state
    assert state["scrub"] > scrubbed + 0.5, state
    checker = lab.run_cell_json(index=-1)
    assert checker["playing"] is True
    assert checker["globe_playing"] is True
    _evidence(lab, "02-play-from-the-scrubber.png")

    # ---- pause from the scrubber: exact convergence -------------------
    lab.page.click(".lgn-scrub-btn")
    time.sleep(1.0)
    state = dict(lab.page.evaluate(_STATE_JS))
    assert state["animating"] is False, state
    checker = lab.run_cell_json(index=-1)
    assert checker["playing"] is False
    assert checker["scrub_time"] == pytest.approx(checker["clock_t"], abs=1e-3)
    assert checker["globe_time"] == pytest.approx(checker["clock_t"], abs=1e-3)
    assert abs(state["seconds"] - checker["clock_t"]) <= 2e-3, (state, checker)

    # ---- the Cesium-dial drive: the scrubber follows, no fighting ----
    before = dict(lab.page.evaluate(_STATE_JS))
    lab.page.evaluate(_DIAL_JS, True)
    # a starved 2-core runner integrates Cesium's own clock well below
    # wall rate (the 770117c CI run: ~0.6x, only ~1.46s of sim time in a
    # 3200ms window -- while the scrubber tracked it faithfully), so the
    # contract below is stated against CESIUM'S OBSERVED advance, never
    # wall time.  When the dial has not yet advanced enough to measure
    # against, sample LONGER (bounded) instead of asserting on noise.
    samples: list[dict] = []
    wall_offset = 0
    for _round in range(3):
        batch = [dict(s) for s in lab.page.evaluate(_SAMPLE_JS, 3200)]
        for sample in batch:
            sample["wall"] += wall_offset
        samples.extend(batch)
        wall_offset = samples[-1]["wall"] + 200
        if samples[-1]["cesium"] - before["seconds"] >= 1.5:
            break
    lab.page.evaluate(_DIAL_JS, False)
    assert samples, "no drift samples collected"
    cesium_delta = samples[-1]["cesium"] - before["seconds"]
    scrub_delta = samples[-1]["scrub"] - before["scrub"]
    # below this floor the dial drive itself never took (or the runner is
    # too starved to measure anything): that IS a failure, not noise
    assert cesium_delta >= 0.5, (
        f"the Cesium clock itself barely advanced ({cesium_delta:.2f}s over "
        f"{samples[-1]['wall']}ms of sampling): the dial drive never engaged "
        f"the clock; samples: {samples}"
    )
    # the scrubber engaged and TRACKED the dial-driven clock: its advance
    # is proportional to Cesium's observed advance.  On a fast box
    # cesium_delta ~= wall time (rate 1.0), so this is exactly as strong
    # as the old wall-clock check; on a starved runner it asserts the
    # seam's contract (tracking) instead of the runner's speed.
    assert scrub_delta >= 0.7 * cesium_delta, (
        f"the scrubber did not track the dial-driven clock: scrub advanced "
        f"{scrub_delta:.2f}s against cesium's {cesium_delta:.2f}s; samples: {samples}"
    )
    # no oscillation: the scrubber never snaps backwards (readout shows
    # 2-decimal truth; 0.05 absorbs its rounding)
    backward = [(a, b) for a, b in pairwise(samples) if b["scrub"] < a["scrub"] - 0.05]
    assert backward == [], f"the scrubber snapped backwards: {backward}"
    # the drift bound holds once the follower engaged (the first ~1.2 s
    # covers the 250 ms dial watcher + comm latency): 0.25 axis units
    # at rate 1, plus reporting latency slack
    engaged = [s for s in samples if s["wall"] > 1200]
    drift = [abs(s["scrub"] - s["cesium"]) for s in engaged]
    assert drift and max(drift) <= 0.8, f"drift bound violated: {samples}"
    # the dial pause rides the 250 ms watcher + a comm hop: poll for it
    deadline = time.monotonic() + 10.0
    checker = lab.run_cell_json(index=-1)
    while checker["playing"] and time.monotonic() < deadline:
        time.sleep(0.5)
        checker = lab.run_cell_json(index=-1)
    assert checker["playing"] is False, checker  # the dial pause reached the clock
    _evidence(lab, "03-cesium-dial-drive.png")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "drift-samples.json").write_text(
        json.dumps({"samples": samples, "max_drift_engaged": max(drift)}, indent=1),
        encoding="utf-8",
    )

    # dial pause converged exactly (the watcher reports the final t)
    time.sleep(0.6)
    state = dict(lab.page.evaluate(_STATE_JS))
    checker = lab.run_cell_json(index=-1)
    assert checker["scrub_time"] == pytest.approx(checker["clock_t"], abs=1e-3)
    assert abs(state["seconds"] - checker["clock_t"]) <= 2e-3, (state, checker)

    # ---- the replay subscription: a seam seek stops its playback -----
    lab.page.click(".longeron-replay-bar button")  # the player's own play
    time.sleep(0.6)
    state = dict(lab.page.evaluate(_STATE_JS))
    assert state["playerButton"] == "\u275a\u275a", state  # playing
    # the throttle survives the seam: ~4 Hz of clock fan-out, not a storm
    events_before = lab.run_cell_json(index=-1)["events"]
    time.sleep(2.0)
    events_after = lab.run_cell_json(index=-1)["events"]
    assert 1 <= events_after - events_before <= 14, (events_before, events_after)
    lab.page.evaluate(_SCRUB_JS, 20.0)  # a scrub while the player runs
    time.sleep(0.6)
    state = dict(lab.page.evaluate(_STATE_JS))
    assert state["playerButton"] == "\u25b6", state  # the kernel seek stopped it
    checker = lab.run_cell_json(index=-1)
    assert checker["player_time"] == pytest.approx(20.0, abs=0.5)  # slider step quantum
    assert checker["clock_t"] == pytest.approx(checker["player_time"], abs=1e-3)

    lab.assert_no_errors()
