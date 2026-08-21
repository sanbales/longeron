// A demonstration SysML v2 model exercising the longeron package:
// structure, calculations, constraints, requirements, actions, and states.
package Drone {
    doc /* A small quad-copter drone, modeled for the longeron demo. */

    // ----- structure ---------------------------------------------------

    part def Battery {
        attribute capacity : Real = 5200.0;      // mAh
        attribute mass : Real = 0.38;            // kg
    }

    part def Rotor {
        attribute maxThrust : Real = 9.0;        // N
        attribute mass : Real = 0.06;
    }

    part def Frame {
        attribute mass : Real = 0.42;
    }

    part def QuadCopter {
        attribute payloadMass : Real = 0.2;
        attribute totalMass : Real =
            chassis.mass + battery.mass + 4.0 * 0.06 + payloadMass;
        attribute maxTakeoffMass : Real = 1.5;

        part chassis : Frame;
        part battery : Battery;
        part rotors : Rotor[4];

        assert constraint takeoffMassLimit { totalMass <= maxTakeoffMass }
        assert constraint canHover {
            4.0 * 9.0 > totalMass * 9.81
        }
    }

    enum def FlightMode { manual; altitudeHold; autonomous; }

    // ----- analysis -----------------------------------------------------

    calc def HoverTime {
        in capacity : Real;             // mAh
        in current : Real = 12000.0;    // mA at hover
        return : Real = capacity / current * 60.0;   // minutes
    }

    calc def ThrustToWeight {
        in thrust : Real;
        in mass : Real;
        return : Real = thrust / (mass * 9.81);
    }

    requirement def FlightEnvelope {
        doc /* The drone shall hover with a comfortable thrust margin. */
        subject drone : QuadCopter;
        assume constraint { drone.totalMass > 0.0 }
        require constraint hoverMargin {
            ThrustToWeight(thrust = 36.0, mass = drone.totalMass) >= 1.8
        }
    }

    // ----- behavior -----------------------------------------------------

    action def PlanBattery {
        in distanceKm : Real;
        in speedKmh : Real = 30.0;
        out flightMinutes : Real;
        out feasible : Boolean;

        assign flightMinutes := distanceKm / speedKmh * 60.0;
        if flightMinutes > HoverTime(capacity = 5200.0) {
            assign feasible := false;
        } else {
            assign feasible := true;
        }
    }

    state def FlightStates {
        attribute launches : Integer := 0;

        entry; then idle;

        state idle;
        transition first idle accept launch then takingOff;

        state takingOff {
            entry assign launches := launches + 1;
        }
        transition first takingOff accept airborne then flying;

        state flying;
        transition first flying accept low_battery do send "RTL" then landing;
        transition first flying accept land then landing;

        state landing;
        transition first landing accept touchdown then idle;
    }
}
