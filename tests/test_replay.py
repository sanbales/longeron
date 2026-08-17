"""Execution-trace replay tests (sysml2.replay)."""

import json
import shutil

import pytest

import sysml2
from sysml2 import replay
from sysml2.errors import ExecutionError
from sysml2.interpreter import StateMachine

FLAT_MODEL = """
package Machines {
    state def TrafficLight {
        entry; then red;
        state red;
        transition first red accept go then green;
        state green;
        transition first green accept caution then yellow;
        state yellow;
        transition first yellow accept stop then red;
    }
}
"""

TIMED_MODEL = """
package P {
    state def Toaster {
        entry; then idle;
        state idle;
        transition first idle accept start then heating;
        state heating {
            entry; then warming;
            state warming;
            transition first warming accept after 2.0 then hot;
            state hot;
        }
        transition first heating accept after 5.0 then idle;
    }
}
"""

PARALLEL_MODEL = """
package P {
    state def Radio {
        entry; then on;
        state on parallel {
            state volume {
                entry; then normal;
                state normal;
                transition first normal accept mute then muted;
                state muted;
            }
            state band {
                entry; then fm;
                state fm;
                transition first fm accept toggle then am;
                state am;
            }
        }
        transition first on accept power_off then off;
        state off;
    }
}
"""


@pytest.fixture(scope="module")
def flat_interp():
    return sysml2.Interpreter(sysml2.loads(FLAT_MODEL))


@pytest.fixture(scope="module")
def timed_interp():
    return sysml2.Interpreter(sysml2.loads(TIMED_MODEL))


@pytest.fixture(scope="module")
def parallel_interp():
    return sysml2.Interpreter(sysml2.loads(PARALLEL_MODEL))


# -- timeline recording -------------------------------------------------------


def test_flat_events_only_is_step_mode(flat_interp):
    timeline = replay.record_timeline(flat_interp, "Machines::TrafficLight",
                                      ["go", "caution", "stop"])
    assert timeline.step_mode is True
    assert timeline.t_start == timeline.t_end == 0.0
    assert timeline.n_steps == 4  # initial entry + three firings
    # step-index keyframes with left/step semantics
    assert timeline.tracks["Machines::TrafficLight::red"] == [
        (0.0, True), (1.0, False), (3.0, True)]
    assert timeline.tracks["Machines::TrafficLight::green"] == [
        (1.0, True), (2.0, False)]
    assert [(f.t, f.event) for f in timeline.fired] == [
        (1.0, "go"), (2.0, "caution"), (3.0, "stop")]
    assert timeline.final_state == "red"


def test_hierarchical_time_triggers(timed_interp):
    timeline = replay.record_timeline(timed_interp, "P::Toaster",
                                      ["start", 10.0])
    assert timeline.step_mode is False
    assert timeline.t_end == 10.0
    # activation intervals in sim time
    assert timeline.tracks["P::Toaster::idle"] == [
        (0.0, True), (0.0, False), (5.0, True)]
    assert timeline.tracks["P::Toaster::heating"] == [(0.0, True),
                                                      (5.0, False)]
    assert timeline.tracks["P::Toaster::heating::warming"] == [(0.0, True),
                                                               (2.0, False)]
    assert timeline.tracks["P::Toaster::heating::hot"] == [(2.0, True),
                                                           (5.0, False)]
    # fired transitions carry sim times and qualified names
    assert [(f.t, f.source, f.target) for f in timeline.fired] == [
        (0.0, "P::Toaster::idle", "P::Toaster::heating"),
        (2.0, "P::Toaster::heating::warming", "P::Toaster::heating::hot"),
        (5.0, "P::Toaster::heating", "P::Toaster::idle"),
    ]
    assert timeline.final_state == "idle"


def test_parallel_regions(parallel_interp):
    timeline = replay.record_timeline(parallel_interp, "P::Radio",
                                      ["mute", "power_off"])
    # both regions were active from the start
    assert timeline.tracks["P::Radio::on::volume::normal"][0] == (0.0, True)
    assert timeline.tracks["P::Radio::on::band::fm"][0] == (0.0, True)
    # the outer transition exits every region
    exit_key = timeline.fired[-1].t
    for qname in ("P::Radio::on", "P::Radio::on::volume::muted",
                  "P::Radio::on::band::fm"):
        assert timeline.tracks[qname][-1] == (exit_key, False)
    assert timeline.tracks["P::Radio::off"] == [(exit_key, True)]
    assert timeline.active_states == ["off"]


def test_event_payload_tuples(flat_interp):
    timeline = replay.record_timeline(flat_interp, "Machines::TrafficLight",
                                      [("go", 42)])
    assert [f.event for f in timeline.fired] == ["go"]


def test_max_steps_guard(flat_interp):
    with pytest.raises(ExecutionError, match="max_steps"):
        replay.record_timeline(flat_interp, "Machines::TrafficLight",
                               ["go", "caution", "stop"] * 10, max_steps=5)


def test_not_a_state_machine(flat_interp):
    with pytest.raises(ExecutionError, match="not a state machine"):
        replay.record_timeline(flat_interp, 3.14)  # type: ignore[arg-type]


# -- JSON payload -------------------------------------------------------------


def test_timeline_json_schema(timed_interp):
    timeline = replay.record_timeline(timed_interp, "P::Toaster",
                                      ["start", 10.0])
    data = json.loads(timeline.to_json())
    assert set(data) == {"t_start", "t_end", "step_mode", "n_steps",
                         "final_state", "tracks", "fired"}
    assert data["step_mode"] is False
    assert data["t_end"] == 10.0
    assert data["n_steps"] == timeline.n_steps
    for keyframes in data["tracks"].values():
        for t, active in keyframes:
            assert isinstance(t, (int, float))
            assert isinstance(active, bool)
            assert round(t, 3) == t  # times rounded to 3 decimals
    for fired in data["fired"]:
        assert set(fired) == {"t", "source", "target", "event"}
        assert "::" in fired["source"] and "::" in fired["target"]


# -- interpreter instrumentation ----------------------------------------------


def test_transition_fired_time_stamping(timed_interp):
    result = timed_interp.simulate("P::Toaster", events=["start", 10.0])
    assert [step.time for step in result.trace] == [0.0, 2.0, 5.0]
    # repr stays unchanged (no time in it)
    assert repr(result.trace[1]) == "heating.warming --auto--> heating.hot"


def test_on_step_hook_invocation_counts(flat_interp):
    machine = StateMachine(flat_interp,
                           flat_interp.resolve("Machines::TrafficLight"), {})
    calls = []
    machine.on_step = lambda now, fired: calls.append((now, fired))
    machine.start()
    assert len(calls) == 1 and calls[0] == (0.0, None)  # initial entry
    machine.send("go")
    machine.send("caution")
    assert len(calls) == 3  # one per fired transition
    assert calls[1][1] is machine.trace[0]
    machine.send("nonsense")  # ignored events do not step
    assert len(calls) == 3


# -- SVG addressability & widget ----------------------------------------------


def _needs_diagrams():
    pytest.importorskip("ipyelk")
    if shutil.which("node") is None:
        pytest.skip("node executable not available")


def test_state_svg_addressable(flat_interp):
    _needs_diagrams()
    from sysml2 import diagrams, render

    svg = render.to_svg(diagrams.state_diagram(
        flat_interp.resolve("Machines::TrafficLight")))
    assert 'data-qname="Machines::TrafficLight::red"' in svg
    assert ('data-edge="Machines::TrafficLight::red-&gt;'
            'Machines::TrafficLight::green"') in svg
    assert 'data-event="go"' in svg


def test_replay_widget_smoke(timed_interp):
    pytest.importorskip("anywidget")
    _needs_diagrams()
    widget = replay.replay_widget(timed_interp, "P::Toaster",
                                  ["start", 10.0], width_px=640)
    assert widget.width_px == 640
    assert widget.time == 0.0
    assert widget.svg.startswith("<svg")
    assert 'data-qname="P::Toaster::heating::hot"' in widget.svg
    data = json.loads(widget.timeline_json)
    assert data["t_end"] == 10.0 and data["step_mode"] is False
    widget.time = 3.0  # python-side seek is just a traitlet write
    assert widget.time == 3.0


def test_replay_widget_missing_extra(monkeypatch, flat_interp):
    import builtins

    monkeypatch.setattr(replay, "_WIDGET_CLS", None)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anywidget":
            raise ImportError("No module named 'anywidget'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"sysml2\[replay\]"):
        replay.replay_widget(flat_interp, "Machines::TrafficLight", ["go"])
