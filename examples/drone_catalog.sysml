// An architecture trade-study model for the sysml2.analysis spikes:
// a quad-copter component catalog captured with variation/variant,
// assembly-level derived attributes, compatibility rules, and system
// requirements.  Each variation point selects ONE variant (homogeneous
// across a multiplicity: all 4 motors are the same type).
package DroneCatalog {
    doc /* Component catalog + assembly for discrete architecture trades. */

    // ----- component families -------------------------------------------

    part def Motor {
        attribute mass : Real;          // kg, per motor
        attribute cost : Real;          // USD, per motor
        attribute maxThrust : Real;     // N, per motor (with matched prop)
        attribute hoverCurrent : Real;  // mA at hover, per motor
        attribute maxCurrent : Real;    // A burst, per motor
        attribute cells : Integer;      // required battery cell count
        attribute maxPropIn : Real;     // largest compatible prop, inches
    }

    part def Propeller {
        attribute mass : Real;
        attribute cost : Real;
        attribute diameterIn : Real;
    }

    part def Battery {
        attribute mass : Real;
        attribute cost : Real;
        attribute capacity : Real;      // mAh
        attribute cells : Integer;
    }

    part def Controller {               // 4-in-1 ESC
        attribute mass : Real;
        attribute cost : Real;
        attribute maxCurrent : Real;    // A, total
        attribute maxCells : Integer;
    }

    // ----- catalog entries ------------------------------------------------

    part def Emax2306 :> Motor {
        attribute mass : Real = 0.033;   attribute cost : Real = 20.0;
        attribute maxThrust : Real = 13.0;
        attribute hoverCurrent : Real = 3200.0;
        attribute maxCurrent : Real = 32.0;
        attribute cells : Integer = 4;   attribute maxPropIn : Real = 5.1;
    }
    part def TMotorF60 :> Motor {
        attribute mass : Real = 0.034;   attribute cost : Real = 28.0;
        attribute maxThrust : Real = 16.0;
        attribute hoverCurrent : Real = 4000.0;
        attribute maxCurrent : Real = 38.0;
        attribute cells : Integer = 6;   attribute maxPropIn : Real = 5.1;
    }
    part def SunnySky2212 :> Motor {
        attribute mass : Real = 0.056;   attribute cost : Real = 17.0;
        attribute maxThrust : Real = 8.0;
        attribute hoverCurrent : Real = 2200.0;
        attribute maxCurrent : Real = 20.0;
        attribute cells : Integer = 3;   attribute maxPropIn : Real = 10.0;
    }

    part def Hq5x43 :> Propeller {
        attribute mass : Real = 0.004;   attribute cost : Real = 3.0;
        attribute diameterIn : Real = 5.0;
    }
    part def Tri5x35 :> Propeller {
        attribute mass : Real = 0.005;   attribute cost : Real = 4.0;
        attribute diameterIn : Real = 5.0;
    }
    part def Apc1045 :> Propeller {
        attribute mass : Real = 0.014;   attribute cost : Real = 4.0;
        attribute diameterIn : Real = 10.0;
    }

    part def Lipo4s1500 :> Battery {
        attribute mass : Real = 0.190;   attribute cost : Real = 32.0;
        attribute capacity : Real = 1500.0; attribute cells : Integer = 4;
    }
    part def Lipo6s1300 :> Battery {
        attribute mass : Real = 0.230;   attribute cost : Real = 45.0;
        attribute capacity : Real = 1300.0; attribute cells : Integer = 6;
    }
    part def Lipo3s2200 :> Battery {
        attribute mass : Real = 0.180;   attribute cost : Real = 20.0;
        attribute capacity : Real = 2200.0; attribute cells : Integer = 3;
    }

    part def Esc45 :> Controller {
        attribute mass : Real = 0.012;   attribute cost : Real = 35.0;
        attribute maxCurrent : Real = 45.0; attribute maxCells : Integer = 6;
    }
    part def Esc20 :> Controller {
        attribute mass : Real = 0.009;   attribute cost : Real = 18.0;
        attribute maxCurrent : Real = 20.0; attribute maxCells : Integer = 4;
    }

    // ----- variation points -----------------------------------------------

    variation part def MotorChoice :> Motor {
        variant part emax2306 : Emax2306;
        variant part tmotorF60 : TMotorF60;
        variant part sunnySky2212 : SunnySky2212;
    }
    variation part def PropChoice :> Propeller {
        variant part hq5x43 : Hq5x43;
        variant part tri5x35 : Tri5x35;
        variant part apc1045 : Apc1045;
    }
    variation part def BatteryChoice :> Battery {
        variant part lipo4s1500 : Lipo4s1500;
        variant part lipo6s1300 : Lipo6s1300;
        variant part lipo3s2200 : Lipo3s2200;
    }
    variation part def ControllerChoice :> Controller {
        variant part esc45 : Esc45;
        variant part esc20 : Esc20;
    }

    // ----- the assembly under trade ---------------------------------------

    part def TradeQuad {
        attribute payloadMass : Real = 0.25;   // kg
        attribute frameMass : Real = 0.30;     // kg, incl. FC + wiring

        part motors : MotorChoice[4];
        part props : PropChoice[4];
        part battery : BatteryChoice;
        part esc : ControllerChoice;

        // references to a homogeneous [4] variation point read the
        // per-unit value; the multiplicity appears explicitly (4.0 * ...)
        attribute totalMass : Real = frameMass + payloadMass + battery.mass
            + esc.mass + 4.0 * motors.mass + 4.0 * props.mass;
        attribute totalCost : Real = battery.cost + esc.cost
            + 4.0 * motors.cost + 4.0 * props.cost;
        attribute totalThrust : Real = 4.0 * motors.maxThrust;
        attribute hoverMinutes : Real =
            battery.capacity / (4.0 * motors.hoverCurrent) * 60.0;

        // compatibility rules
        assert constraint cellMatch { battery.cells == motors.cells }
        assert constraint escCells { battery.cells <= esc.maxCells }
        assert constraint propFit { props.diameterIn <= motors.maxPropIn }
        assert constraint escCurrent {
            esc.maxCurrent >= 2.0 * 4.0 * motors.hoverCurrent / 1000.0
        }

        // system requirements
        assert constraint thrustMargin { totalThrust >= 2.0 * totalMass * 9.81 }
        assert constraint massBudget { totalMass <= 1.6 }
        assert constraint costBudget { totalCost <= 320.0 }
        assert constraint enduranceReq { hoverMinutes >= 6.0 }
    }

    // deliberately over-constrained: no catalog mix can satisfy this
    part def PicnicQuad :> TradeQuad {
        assert constraint longEndurance { hoverMinutes >= 25.0 }
        assert constraint cheap { totalCost <= 130.0 }
    }
}
