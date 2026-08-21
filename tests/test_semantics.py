"""Richer execution semantics: succession-driven actions, hierarchical and
parallel states, and time triggers."""

import pytest

import longeron
from longeron.errors import ExecutionError


@pytest.fixture(scope="module")
def succession_interp():
    return longeron.Interpreter(
        longeron.loads("""
            package P {
                action def OutOfOrder {
                    out log : String;
                    assign log := "";
                    // declared out of order; successions define the flow
                    action c { assign log := log + "c"; }
                    action a { assign log := log + "a"; }
                    action b { assign log := log + "b"; }
                    first start then a;
                    first a then b;
                    first b then c;
                    first c then done;
                }
                action def Unreachable {
                    out log : String;
                    assign log := "";
                    action a { assign log := log + "a"; }
                    action zombie { assign log := log + "Z"; }
                    first start then a;
                    first a then done;
                }
                action def Decision {
                    in x : Integer;
                    out label : String;
                    action big { assign label := "big"; }
                    action small { assign label := "small"; }
                    action zero { assign label := "zero"; }
                    first start then d1;
                    decide d1;
                    if x > 100 then big;
                    if x > 0 then small;
                    else zero;
                    first big then done;
                    first small then done;
                    first zero then done;
                }
                action def ForkJoin {
                    out log : String;
                    assign log := "";
                    fork f1;
                    action left { assign log := log + "L"; }
                    action right { assign log := log + "R"; }
                    join j1;
                    action finish { assign log := log + "!"; }
                    first start then f1;
                    first f1 then left;
                    first f1 then right;
                    first left then j1;
                    first right then j1;
                    first j1 then finish;
                    first finish then done;
                }
                action def LoopBack {
                    out n : Integer;
                    assign n := 0;
                    action bump { assign n := n + 1; }
                    if n < 3 then bump;
                    else done;
                    first start then bump;
                }
            }
        """)
    )


class TestSuccessionFlow:
    def test_successions_define_order(self, succession_interp):
        result = succession_interp.run_action("P::OutOfOrder")
        assert result.outputs["log"] == "abc"
        steps = [t for t in result.trace if t.startswith("step ")]
        assert steps == ["step a", "step b", "step c"]

    def test_unreachable_steps_do_not_run(self, succession_interp):
        result = succession_interp.run_action("P::Unreachable")
        assert result.outputs["log"] == "a"

    def test_decision_guards(self, succession_interp):
        run = lambda x: succession_interp.run_action(  # noqa: E731
            "P::Decision", inputs={"x": x}
        ).outputs["label"]
        assert run(500) == "big"
        assert run(5) == "small"
        assert run(-1) == "zero"

    def test_fork_join(self, succession_interp):
        result = succession_interp.run_action("P::ForkJoin")
        assert result.outputs["log"] == "LR!"
        assert "fork f1" in result.trace
        assert "join j1" in result.trace

    def test_guarded_loop_back(self, succession_interp):
        result = succession_interp.run_action("P::LoopBack")
        assert result.outputs["n"] == 3

    def test_declaration_order_without_successions(self, action_interp):
        # regression: bodies without successions keep declaration order
        result = action_interp.run_action("Behaviors::CountDown", inputs={"start": 4})
        assert result.outputs["total"] == 10


@pytest.fixture(scope="module")
def action_time_interp():
    return longeron.Interpreter(
        longeron.loads("""
            package P {
                action def Timed {
                    out elapsed : Real;
                    accept after 2.5;
                    accept after 1.5;
                    accept at 10.0;
                    assign elapsed := 0.0;
                }
                action def WhenOk {
                    in ready : Boolean;
                    accept when ready;
                }
            }
        """)
    )


class TestActionTime:
    def test_after_and_at_advance_clock(self, action_time_interp):
        result = action_time_interp.run_action("P::Timed")
        assert result.time == 10.0  # 2.5 + 1.5 then wait-until 10

    def test_when_true_passes(self, action_time_interp):
        action_time_interp.run_action("P::WhenOk", inputs={"ready": True})

    def test_when_false_deadlocks(self, action_time_interp):
        with pytest.raises(ExecutionError, match="deadlock"):
            action_time_interp.run_action("P::WhenOk", inputs={"ready": False})


@pytest.fixture(scope="module")
def hier_interp():
    return longeron.Interpreter(
        longeron.loads("""
            package P {
                state def Machine {
                    attribute log : String := "";
                    entry; then off;

                    state off;
                    transition first off accept power_on then operating;

                    state operating {
                        entry assign log := log + "[op";
                        exit assign log := log + "op]";

                        entry; then idle;
                        state idle {
                            entry assign log := log + "(i";
                            exit assign log := log + "i)";
                        }
                        transition first idle accept work then busy;
                        state busy {
                            entry assign log := log + "(b";
                            exit assign log := log + "b)";
                        }
                        transition first busy accept rest then idle;
                    }
                    transition first operating accept power_off then off;
                }
            }
        """)
    )


class TestHierarchicalStates:
    def test_composite_entry_descends(self, hier_interp):
        result = hier_interp.simulate("P::Machine", events=["power_on"])
        assert result.final_state == "operating.idle"
        assert result.env["log"] == "[op(i"

    def test_inner_transition(self, hier_interp):
        result = hier_interp.simulate("P::Machine", events=["power_on", "work"])
        assert result.final_state == "operating.busy"
        assert result.env["log"] == "[op(ii)(b"

    def test_inner_handles_before_outer(self, hier_interp):
        result = hier_interp.simulate("P::Machine", events=["power_on", "work", "rest"])
        assert result.final_state == "operating.idle"

    def test_exit_cascades_innermost_first(self, hier_interp):
        result = hier_interp.simulate("P::Machine", events=["power_on", "work", "power_off"])
        assert result.final_state == "off"
        assert result.env["log"] == "[op(ii)(bb)op]"

    def test_trace_uses_dotted_paths(self, hier_interp):
        result = hier_interp.simulate("P::Machine", events=["power_on", "work"])
        assert (result.trace[1].source, result.trace[1].target) == (
            "operating.idle",
            "operating.busy",
        )


@pytest.fixture(scope="module")
def parallel_interp():
    return longeron.Interpreter(
        longeron.loads("""
            package P {
                state def Radio {
                    entry; then on;
                    state on parallel {
                        state volume {
                            entry; then normal;
                            state normal;
                            transition first normal accept mute then muted;
                            state muted;
                            transition first muted accept mute then normal;
                        }
                        state band {
                            entry; then fm;
                            state fm;
                            transition first fm accept toggle then am;
                            state am;
                            transition first am accept toggle then fm;
                        }
                    }
                    transition first on accept power_off then off;
                    state off;
                }
            }
        """)
    )


class TestParallelStates:
    def test_all_regions_active(self, parallel_interp):
        result = parallel_interp.simulate("P::Radio")
        assert result.active_states == ["on.volume.normal", "on.band.fm"]

    def test_regions_independent(self, parallel_interp):
        result = parallel_interp.simulate("P::Radio", events=["mute", "toggle"])
        assert result.active_states == ["on.volume.muted", "on.band.am"]

    def test_outer_transition_exits_all_regions(self, parallel_interp):
        result = parallel_interp.simulate("P::Radio", events=["mute", "power_off"])
        assert result.final_state == "off"
        assert result.active_states == ["off"]


@pytest.fixture(scope="module")
def state_time_interp():
    return longeron.Interpreter(
        longeron.loads("""
            package P {
                item def Tick;
                state def Toaster {
                    attribute pops : Integer := 0;
                    entry; then idle;
                    state idle;
                    transition first idle accept press then toasting;
                    state toasting;
                    transition first toasting accept after 30.0
                        do assign pops := pops + 1
                        then idle;
                }
                state def Alarm {
                    entry; then waiting;
                    state waiting;
                    transition first waiting accept at 100.0 then ringing;
                    state ringing;
                }
                state def Watchdog {
                    attribute armed : Boolean := false;
                    entry; then watching;
                    state watching;
                    transition first watching accept when armed then tripped;
                    state tripped;
                }
            }
        """)
    )


class TestStateTime:
    def test_after_fires_when_time_advances(self, state_time_interp):
        result = state_time_interp.simulate("P::Toaster", events=["press", 31.0])
        assert result.final_state == "idle"
        assert result.env["pops"] == 1
        assert result.time == 31.0

    def test_after_does_not_fire_early(self, state_time_interp):
        result = state_time_interp.simulate("P::Toaster", events=["press", 10.0])
        assert result.final_state == "toasting"

    def test_after_measures_from_state_entry(self, state_time_interp):
        # enter toasting at t=50; 30s later is t=80
        result = state_time_interp.simulate("P::Toaster", events=[50.0, "press", 29.0, 2.0])
        assert result.final_state == "idle"

    def test_at_fires_at_absolute_time(self, state_time_interp):
        result = state_time_interp.simulate("P::Alarm", events=[99.0])
        assert result.final_state == "waiting"
        result = state_time_interp.simulate("P::Alarm", events=[101.0])
        assert result.final_state == "ringing"

    def test_when_trigger(self, state_time_interp):
        result = state_time_interp.simulate("P::Watchdog", inputs={"armed": True})
        assert result.final_state == "tripped"
        result = state_time_interp.simulate("P::Watchdog")
        assert result.final_state == "watching"
