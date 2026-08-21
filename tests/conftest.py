"""Shared fixtures for the longeron test suite."""

import pytest

import longeron

VEHICLE_MODEL = """
package Vehicles {
    doc /* A small demonstration model. */

    part def Wheel {
        attribute diameter : Real = 0.66;
    }

    part def Engine {
        attribute power : Real = 150.0;
        attribute mass : Real = 180.0;
    }

    abstract part def Machine {
        attribute mass : Real = 0.0;
    }

    part def Vehicle :> Machine {
        attribute mass : Real :> Machine::mass = 1200.0;
        attribute maxMass : Real = 2000.0;
        attribute dryMass : Real = mass - 100.0;
        part engine : Engine;
        part wheels : Wheel[4];
        assert constraint massLimit { mass <= maxMass }
    }

    enum def Color { red; green; blue; }

    calc def TotalMass {
        in vehicleMass : Real;
        in cargoMass : Real = 0.0;
        return : Real = vehicleMass + cargoMass;
    }

    calc def KineticEnergy {
        in m : Real;
        in v : Real;
        attribute vSquared : Real = v ** 2;
        return : Real = 0.5 * m * vSquared;
    }

    requirement def MassRequirement {
        subject vehicle : Vehicle;
        assume constraint { vehicle.mass > 0.0 }
        require constraint underLimit { vehicle.mass <= vehicle.maxMass }
    }
}
"""

ACTION_MODEL = """
package Behaviors {
    action def ComputeFuel {
        in distance : Real;
        in rate : Real = 0.08;
        out fuelUsed : Real;
        assign fuelUsed := distance * rate;
        if fuelUsed > 100.0 {
            assign fuelUsed := 100.0;
        }
    }

    action def CountDown {
        in start : Integer;
        out total : Integer;
        assign total := 0;
        for i in 1..start {
            assign total := total + i;
        }
    }

    action def Radio {
        in code : Integer;
        accept ping : Ping;
        send code * 2;
    }

    item def Ping;
}
"""

STATE_MODEL = """
package Machines {
    state def TrafficLight {
        attribute cycles : Integer := 0;

        entry; then red;

        state red;
        transition first red accept go then green;

        state green {
            entry assign cycles := cycles + 1;
        }
        transition first green accept caution then yellow;

        state yellow;
        transition first yellow accept stop then red;
    }
}
"""


@pytest.fixture(scope="session")
def vehicle_model():
    return longeron.loads(VEHICLE_MODEL)


@pytest.fixture(scope="session")
def action_model():
    return longeron.loads(ACTION_MODEL)


@pytest.fixture(scope="session")
def state_model():
    return longeron.loads(STATE_MODEL)


@pytest.fixture()
def vehicle_interp(vehicle_model):
    return longeron.Interpreter(vehicle_model)


@pytest.fixture()
def action_interp(action_model):
    return longeron.Interpreter(action_model)


@pytest.fixture()
def state_interp(state_model):
    return longeron.Interpreter(state_model)
