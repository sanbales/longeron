"""Execution-trace replay tests (longeron.replay)."""

import json
import shutil

import pytest

import longeron
from longeron import replay
from longeron.errors import ExecutionError
from longeron.interpreter import StateMachine

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

# the submachine's states live under the DEFINITION's qualified name
# (P::Inner::a), not under the using state's (P::Outer::x) -- the case
# "::"-prefix branch detection cannot see
TYPED_SUBMACHINE_MODEL = """
package P {
    state def Inner {
        entry; then a;
        state a;
        transition first a accept go then b;
        state b;
    }
    state def Outer {
        entry; then x;
        state x : Inner;
        transition first x accept quit then off;
        state off;
    }
}
"""

ENV_MODEL = """
package P {
    state def Tally {
        attribute count : Integer := 0;
        attribute ratio : Real := 0.0;
        entry; then idle;
        state idle;
        transition first idle accept tick
            do assign count := count + 1 then busy;
        state busy;
        transition first busy accept tock
            do assign ratio := count / 3.0 then idle;
    }
}
"""

ACTION_MODEL = """
package Ops {
    action def Deploy {
        in tested : Boolean;
        out log : String;
        assign log := "";
        action build { assign log := log + "build>"; }
        action inspect { assign log := log + "inspect>"; }
        action ship { assign log := log + "ship"; }
        action abort { assign log := log + "ABORT"; }
        first start then build;
        first build then d1;
        decide d1;
        if tested then inspect;
        else abort;
        first inspect then ship;
        first ship then done;
        first abort then done;
    }
    action def Nested {
        out total : Integer;
        assign total := 0;
        action stage1 {
            action inner1 { assign total := total + 1; }
            action inner2 { assign total := total + 10; }
        }
        action stage2 { assign total := total * 2; }
        first start then stage1;
        first stage1 then stage2;
        first stage2 then done;
    }
}
"""


@pytest.fixture(scope="module")
def flat_interp():
    return longeron.Interpreter(longeron.loads(FLAT_MODEL))


@pytest.fixture(scope="module")
def timed_interp():
    return longeron.Interpreter(longeron.loads(TIMED_MODEL))


@pytest.fixture(scope="module")
def parallel_interp():
    return longeron.Interpreter(longeron.loads(PARALLEL_MODEL))


@pytest.fixture(scope="module")
def action_interp():
    return longeron.Interpreter(longeron.loads(ACTION_MODEL))


# -- timeline recording -------------------------------------------------------


def test_flat_events_only_is_step_mode(flat_interp):
    timeline = replay.record_timeline(
        flat_interp, "Machines::TrafficLight", ["go", "caution", "stop"]
    )
    assert timeline.step_mode is True
    assert timeline.t_start == timeline.t_end == 0.0
    assert timeline.n_steps == 4  # initial entry + three firings
    # step-index keyframes with left/step semantics
    assert timeline.tracks["Machines::TrafficLight::red"] == [
        (0.0, True),
        (1.0, False),
        (3.0, True),
    ]
    assert timeline.tracks["Machines::TrafficLight::green"] == [(1.0, True), (2.0, False)]
    assert [(f.t, f.event) for f in timeline.fired] == [
        (1.0, "go"),
        (2.0, "caution"),
        (3.0, "stop"),
    ]
    assert timeline.final_state == "red"


def test_hierarchical_time_triggers(timed_interp):
    timeline = replay.record_timeline(timed_interp, "P::Toaster", ["start", 10.0])
    assert timeline.step_mode is False
    assert timeline.t_end == 10.0
    # activation intervals in sim time
    assert timeline.tracks["P::Toaster::idle"] == [(0.0, True), (0.0, False), (5.0, True)]
    assert timeline.tracks["P::Toaster::heating"] == [(0.0, True), (5.0, False)]
    assert timeline.tracks["P::Toaster::heating::warming"] == [(0.0, True), (2.0, False)]
    assert timeline.tracks["P::Toaster::heating::hot"] == [(2.0, True), (5.0, False)]
    # fired transitions carry sim times and qualified names
    assert [(f.t, f.source, f.target) for f in timeline.fired] == [
        (0.0, "P::Toaster::idle", "P::Toaster::heating"),
        (2.0, "P::Toaster::heating::warming", "P::Toaster::heating::hot"),
        (5.0, "P::Toaster::heating", "P::Toaster::idle"),
    ]
    assert timeline.final_state == "idle"


def test_parallel_regions(parallel_interp):
    timeline = replay.record_timeline(parallel_interp, "P::Radio", ["mute", "power_off"])
    # both regions were active from the start
    assert timeline.tracks["P::Radio::on::volume::normal"][0] == (0.0, True)
    assert timeline.tracks["P::Radio::on::band::fm"][0] == (0.0, True)
    # the outer transition exits every region
    exit_key = timeline.fired[-1].t
    for qname in ("P::Radio::on", "P::Radio::on::volume::muted", "P::Radio::on::band::fm"):
        assert timeline.tracks[qname][-1] == (exit_key, False)
    assert timeline.tracks["P::Radio::off"] == [(exit_key, True)]
    assert timeline.active_states == ["off"]


def test_event_payload_tuples(flat_interp):
    timeline = replay.record_timeline(flat_interp, "Machines::TrafficLight", [("go", 42)])
    assert [f.event for f in timeline.fired] == ["go"]


def test_max_steps_guard(flat_interp):
    with pytest.raises(ExecutionError, match="max_steps"):
        replay.record_timeline(
            flat_interp, "Machines::TrafficLight", ["go", "caution", "stop"] * 10, max_steps=5
        )


def test_not_a_state_machine(flat_interp):
    with pytest.raises(ExecutionError, match="not a state machine"):
        replay.record_timeline(flat_interp, 3.14)  # type: ignore[arg-type]


def test_parents_map_hierarchical(timed_interp):
    timeline = replay.record_timeline(timed_interp, "P::Toaster", ["start", 10.0])
    assert timeline.parents == {
        "P::Toaster::heating::warming": "P::Toaster::heating",
        "P::Toaster::heating::hot": "P::Toaster::heating",
    }  # roots (idle, heating) have no parent entry


def test_parents_map_typed_submachine():
    """Typed submachines descend into the *definition's* states, whose
    qualified names are not prefixed by the using state's -- the recorded
    parents map is the only correct branch/leaf signal there."""

    interp = longeron.Interpreter(longeron.loads(TYPED_SUBMACHINE_MODEL))
    timeline = replay.record_timeline(interp, "P::Outer", ["go", "quit"])
    assert timeline.tracks["P::Outer::x"] == [(0.0, True), (2.0, False)]
    assert timeline.tracks["P::Inner::a"] == [(0.0, True), (1.0, False)]
    assert timeline.parents == {"P::Inner::a": "P::Outer::x", "P::Inner::b": "P::Outer::x"}
    # the "::"-prefix fallback would misclassify x as a leaf here
    assert not "P::Inner::a".startswith("P::Outer::x::")


# -- env readout --------------------------------------------------------------


def test_env_steps_follow_assignments():
    interp = longeron.Interpreter(longeron.loads(ENV_MODEL))
    timeline = replay.record_timeline(interp, "P::Tally", ["tick", "tock", "tick"])
    assert [values for _, values in timeline.env_steps] == [
        {"count": 0, "ratio": 0.0},
        {"count": 1, "ratio": 0.0},
        {"count": 1, "ratio": 1 / 3},
        {"count": 2, "ratio": 1 / 3},
    ]
    # step-mode keys, matching the tracks
    assert [key for key, _ in timeline.env_steps] == [0.0, 1.0, 2.0, 3.0]


def test_env_steps_scalars_only_and_rounded():
    interp = longeron.Interpreter(longeron.loads(ENV_MODEL))
    timeline = replay.record_timeline(interp, "P::Tally", ["tick", "tock"])
    data = json.loads(timeline.to_json())
    assert data["env_steps"][-1][1] == {"count": 1, "ratio": 0.333}
    for _, values in data["env_steps"]:
        for value in values.values():
            assert isinstance(value, (str, int, float, bool))


# -- JSON payload -------------------------------------------------------------


def test_timeline_json_schema(timed_interp):
    timeline = replay.record_timeline(timed_interp, "P::Toaster", ["start", 10.0])
    data = json.loads(timeline.to_json())
    assert set(data) == {
        "t_start",
        "t_end",
        "step_mode",
        "n_steps",
        "final_state",
        "tracks",
        "fired",
        "parents",
        "env_steps",
    }
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
    assert isinstance(data["parents"], dict)
    assert isinstance(data["env_steps"], list)


# -- action timelines ----------------------------------------------------------


def test_action_timeline_sequential_steps(action_interp):
    timeline = replay.record_action_timeline(action_interp, "Ops::Deploy", inputs={"tested": True})
    assert timeline.step_mode is True
    assert timeline.n_steps == 4  # 3 executed steps + the all-done instant
    assert timeline.tracks == {
        "Ops::Deploy::build": [(0.0, True), (1.0, False)],
        "Ops::Deploy::inspect": [(1.0, True), (2.0, False)],
        "Ops::Deploy::ship": [(2.0, True), (3.0, False)],
    }
    assert timeline.env["log"] == "build>inspect>ship"
    assert timeline.final_state is None


def test_action_fired_routes_through_control_nodes(action_interp):
    timeline = replay.record_action_timeline(action_interp, "Ops::Deploy", inputs={"tested": True})
    # build->inspect traverses the decide node: both drawn edges pulse
    assert [(f.t, f.source, f.target) for f in timeline.fired] == [
        (1.0, "Ops::Deploy::build", "Ops::Deploy::d1"),
        (1.0, "Ops::Deploy::d1", "Ops::Deploy::inspect"),
        (2.0, "Ops::Deploy::inspect", "Ops::Deploy::ship"),
    ]


def test_action_timeline_takes_else_branch(action_interp):
    timeline = replay.record_action_timeline(action_interp, "Ops::Deploy", inputs={"tested": False})
    assert sorted(timeline.tracks) == ["Ops::Deploy::abort", "Ops::Deploy::build"]
    assert timeline.fired[-1].target == "Ops::Deploy::abort"
    assert timeline.env["log"] == "build>ABORT"


def test_action_timeline_nested_steps(action_interp):
    timeline = replay.record_action_timeline(action_interp, "Ops::Nested")
    # the composite stage stays active while its inner steps run
    assert timeline.tracks["Ops::Nested::stage1"] == [(0.0, True), (3.0, False)]
    assert timeline.tracks["Ops::Nested::stage1::inner1"] == [(1.0, True), (2.0, False)]
    assert timeline.parents == {
        "Ops::Nested::stage1::inner1": "Ops::Nested::stage1",
        "Ops::Nested::stage1::inner2": "Ops::Nested::stage1",
    }
    assert timeline.env["total"] == 22


def test_action_env_steps(action_interp):
    timeline = replay.record_action_timeline(action_interp, "Ops::Deploy", inputs={"tested": True})
    assert [values["log"] for _, values in timeline.env_steps] == [
        "",
        "build>",
        "build>inspect>",
        "build>inspect>ship",
    ]


def test_action_timeline_not_an_action(action_interp):
    with pytest.raises(ExecutionError, match="not an action"):
        replay.record_action_timeline(action_interp, [])  # type: ignore[arg-type]


def test_action_on_step_hook_pairing(action_interp):
    """The executor observer fires enter/complete pairs with step ordinals."""

    from collections import deque

    from longeron.interpreter import _ActionExecutor

    executor = _ActionExecutor(
        action_interp, action_interp.resolve("Ops::Deploy"), {"tested": True}, deque()
    )
    calls = []
    executor.on_step = lambda i, el, phase: calls.append((i, el.name, phase))
    executor.run()
    assert calls == [
        (0, "build", "enter"),
        (1, "build", "complete"),
        (1, "inspect", "enter"),
        (2, "inspect", "complete"),
        (2, "ship", "enter"),
        (3, "ship", "complete"),
    ]


# -- interpreter instrumentation ----------------------------------------------


def test_transition_fired_time_stamping(timed_interp):
    result = timed_interp.simulate("P::Toaster", events=["start", 10.0])
    assert [step.time for step in result.trace] == [0.0, 2.0, 5.0]
    # repr stays unchanged (no time in it)
    assert repr(result.trace[1]) == "heating.warming --auto--> heating.hot"


def test_on_step_hook_invocation_counts(flat_interp):
    machine = StateMachine(flat_interp, flat_interp.resolve("Machines::TrafficLight"), {})
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
    from longeron import diagrams, render

    svg = render.to_svg(diagrams.state_diagram(flat_interp.resolve("Machines::TrafficLight")))
    assert 'data-qname="Machines::TrafficLight::red"' in svg
    assert ('data-edge="Machines::TrafficLight::red-&gt;Machines::TrafficLight::green"') in svg
    assert 'data-event="go"' in svg


def test_replay_widget_smoke(timed_interp):
    pytest.importorskip("anywidget")
    _needs_diagrams()
    widget = replay.replay_widget(timed_interp, "P::Toaster", ["start", 10.0], width_px=640)
    assert widget.width_px == 640
    assert widget.time == 0.0
    assert widget.svg.startswith("<svg")
    assert 'data-qname="P::Toaster::heating::hot"' in widget.svg
    data = json.loads(widget.timeline_json)
    assert data["t_end"] == 10.0 and data["step_mode"] is False
    widget.time = 3.0  # python-side seek is just a traitlet write
    assert widget.time == 3.0


def test_action_svg_addressable(action_interp):
    _needs_diagrams()
    from longeron import diagrams, render

    svg = render.to_svg(diagrams.action_diagram(action_interp.resolve("Ops::Deploy")))
    assert 'data-qname="Ops::Deploy::build"' in svg
    assert 'data-qname="Ops::Deploy::d1"' in svg  # control nodes too
    assert ('data-edge="Ops::Deploy::build-&gt;Ops::Deploy::d1"') in svg


def test_replay_widget_action_autodetect(action_interp):
    pytest.importorskip("anywidget")
    _needs_diagrams()
    widget = replay.replay_widget(
        action_interp, "Ops::Deploy", inputs={"tested": True}
    )  # kind inferred
    assert 'data-qname="Ops::Deploy::inspect"' in widget.svg
    data = json.loads(widget.timeline_json)
    assert data["step_mode"] is True and data["n_steps"] == 4
    assert data["env_steps"][-1][1]["log"] == "build>inspect>ship"


def test_replay_widget_unknown_kind(flat_interp):
    pytest.importorskip("anywidget")
    with pytest.raises(ExecutionError, match="unknown replay kind"):
        replay.replay_widget(flat_interp, "Machines::TrafficLight", ["go"], kind="nope")


def test_replay_widget_missing_extra(monkeypatch, flat_interp):
    import builtins

    monkeypatch.setattr(replay, "_WIDGET_CLS", None)
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "anywidget":
            raise ImportError("No module named 'anywidget'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ImportError, match=r"longeron\[replay\]"):
        replay.replay_widget(flat_interp, "Machines::TrafficLight", ["go"])
