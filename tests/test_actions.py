"""Action execution tests."""

import pytest

import sysml2
from sysml2.errors import ExecutionError


class TestBasics:
    def test_assignment_and_outputs(self, action_interp):
        result = action_interp.run_action("Behaviors::ComputeFuel",
                                          inputs={"distance": 100.0})
        assert result.outputs == {"fuelUsed": pytest.approx(8.0)}

    def test_default_input(self, action_interp):
        result = action_interp.run_action(
            "Behaviors::ComputeFuel", inputs={"distance": 50.0, "rate": 0.1})
        assert result.outputs["fuelUsed"] == pytest.approx(5.0)

    def test_if_branch(self, action_interp):
        result = action_interp.run_action("Behaviors::ComputeFuel",
                                          inputs={"distance": 10000.0})
        assert result.outputs["fuelUsed"] == 100.0  # capped by the if

    def test_missing_input(self, action_interp):
        with pytest.raises(ExecutionError, match="missing input"):
            action_interp.run_action("Behaviors::ComputeFuel")

    def test_unknown_input(self, action_interp):
        with pytest.raises(ExecutionError, match="unknown input"):
            action_interp.run_action("Behaviors::ComputeFuel",
                                     inputs={"distance": 1.0, "bogus": 2})

    def test_for_loop(self, action_interp):
        result = action_interp.run_action("Behaviors::CountDown",
                                          inputs={"start": 5})
        assert result.outputs["total"] == 15

    def test_trace(self, action_interp):
        result = action_interp.run_action("Behaviors::ComputeFuel",
                                          inputs={"distance": 100.0})
        assert any(t.startswith("assign fuelUsed") for t in result.trace)


class TestEvents:
    def test_send_and_accept(self, action_interp):
        result = action_interp.run_action("Behaviors::Radio",
                                          inputs={"code": 21},
                                          events=["Ping"])
        assert [s.payload for s in result.sends] == [42]

    def test_accept_blocks_without_event(self, action_interp):
        with pytest.raises(ExecutionError, match="no more events"):
            action_interp.run_action("Behaviors::Radio", inputs={"code": 1})

    def test_accept_wrong_event(self, action_interp):
        with pytest.raises(ExecutionError, match="expected one of"):
            action_interp.run_action("Behaviors::Radio", inputs={"code": 1},
                                     events=["Pong"])


@pytest.fixture(scope="module")
def control_flow_interp():
    return sysml2.Interpreter(sysml2.loads("""
            package P {
                action def Loops {
                    in n : Integer;
                    out doublings : Integer;
                    assign doublings := 0;
                    attribute value : Integer := 1;
                    while value < n {
                        assign value := value * 2;
                        assign doublings := doublings + 1;
                    }
                }
                action def UntilLoop {
                    out count : Integer;
                    assign count := 0;
                    loop {
                        assign count := count + 1;
                    } until count >= 3;
                }
                action def Chained {
                    in x : Real;
                    out y : Real;
                    perform step1;
                    perform step2;
                }
                action def IfElseChain {
                    in x : Integer;
                    out label : String;
                    if x < 0 {
                        assign label := "negative";
                    } else if x == 0 {
                        assign label := "zero";
                    } else {
                        assign label := "positive";
                    }
                }
                action step1 { assign y := x * 2.0; }
                action step2 { assign y := y + 1.0; }
                action def Terminates {
                    out reached : Boolean;
                    assign reached := false;
                    terminate;
                    assign reached := true;
                }
            }
        """))


class TestControlFlow:
    def test_while_loop(self, control_flow_interp):
        result = control_flow_interp.run_action("P::Loops", inputs={"n": 100})
        assert result.outputs["doublings"] == 7  # 2^7 = 128 >= 100

    def test_until_loop(self, control_flow_interp):
        result = control_flow_interp.run_action("P::UntilLoop")
        assert result.outputs["count"] == 3

    def test_if_else_chain(self, control_flow_interp):
        run = lambda x: control_flow_interp.run_action(  # noqa: E731
            "P::IfElseChain", inputs={"x": x}).outputs["label"]
        assert run(-5) == "negative"
        assert run(0) == "zero"
        assert run(9) == "positive"

    def test_terminate_stops_execution(self, control_flow_interp):
        result = control_flow_interp.run_action("P::Terminates")
        assert result.terminated
        assert result.outputs["reached"] is False

    def test_perform_shares_parameters(self, control_flow_interp):
        result = control_flow_interp.run_action("P::Chained", inputs={"x": 5.0})
        assert result.outputs["y"] == 11.0


def test_infinite_loop_guard():
    interp = sysml2.Interpreter(sysml2.loads("""
        package P {
            action def Forever { loop { assign x := 1; } }
        }
    """))
    with pytest.raises(ExecutionError, match="iteration limit"):
        interp.run_action("P::Forever")
