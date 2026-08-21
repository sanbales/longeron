"""State machine simulation tests."""

import pytest

import longeron
from longeron.errors import ExecutionError


class TestTrafficLight:
    def test_initial_state(self, state_interp):
        result = state_interp.simulate("Machines::TrafficLight")
        assert result.final_state == "red"

    def test_event_sequence(self, state_interp):
        result = state_interp.simulate(
            "Machines::TrafficLight", events=["go", "caution", "stop", "go"]
        )
        assert result.final_state == "green"
        assert [(t.source, t.event, t.target) for t in result.trace] == [
            ("red", "go", "green"),
            ("green", "caution", "yellow"),
            ("yellow", "stop", "red"),
            ("red", "go", "green"),
        ]

    def test_entry_action_mutates_env(self, state_interp):
        result = state_interp.simulate(
            "Machines::TrafficLight", events=["go", "caution", "stop", "go"]
        )
        assert result.env["cycles"] == 2  # entered green twice

    def test_unmatched_events_ignored(self, state_interp):
        result = state_interp.simulate("Machines::TrafficLight", events=["stop", "go"])
        assert result.ignored_events == ["stop"]
        assert result.final_state == "green"


@pytest.fixture(scope="module")
def thermostat_interp():
    return longeron.Interpreter(
        longeron.loads("""
            package P {
                item def Overheat;
                state def Thermostat {
                    attribute temp : Real := 20.0;
                    attribute alarms : Integer := 0;

                    entry; then idle;

                    state idle;
                    transition first idle accept setpoint : Overheat
                        if temp > 30.0
                        do assign alarms := alarms + 1
                        then cooling;
                    transition first idle accept warm then idle;

                    state cooling {
                        entry send temp;
                        exit assign temp := temp - 5.0;
                    }
                    transition first cooling accept ok then idle;
                }
            }
        """)
    )


class TestRichStateMachine:
    def test_guard_blocks_transition(self, thermostat_interp):
        result = thermostat_interp.simulate("P::Thermostat", events=["Overheat"])
        assert result.final_state == "idle"  # guard temp > 30 failed
        assert result.ignored_events == ["Overheat"]

    def test_guard_allows_with_inputs(self, thermostat_interp):
        result = thermostat_interp.simulate(
            "P::Thermostat", events=["Overheat"], inputs={"temp": 35.0}
        )
        assert result.final_state == "cooling"
        assert result.env["alarms"] == 1  # effect ran

    def test_state_actions_run(self, thermostat_interp):
        result = thermostat_interp.simulate(
            "P::Thermostat", events=["Overheat", "ok"], inputs={"temp": 40.0}
        )
        assert result.final_state == "idle"
        assert [s.payload for s in result.sends] == [40.0]  # entry send
        assert result.env["temp"] == 35.0  # exit action ran

    def test_self_transition(self, thermostat_interp):
        result = thermostat_interp.simulate("P::Thermostat", events=["warm", "warm"])
        assert result.final_state == "idle"
        assert len(result.trace) == 2


def test_eventless_transitions():
    interp = longeron.Interpreter(
        longeron.loads("""
        package P {
            state def AutoAdvance {
                attribute ready : Boolean := true;
                entry; then a;
                state a;
                transition first a if ready then b;
                state b;
            }
        }
    """)
    )
    result = interp.simulate("P::AutoAdvance")
    assert result.final_state == "b"
    assert result.trace[0].event is None


def test_missing_entry_transition():
    interp = longeron.Interpreter(
        longeron.loads("""
        package P { state def NoEntry { state a; } }
    """)
    )
    with pytest.raises(ExecutionError, match="no entry transition"):
        interp.simulate("P::NoEntry")
