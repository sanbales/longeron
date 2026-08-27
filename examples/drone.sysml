// A demonstration SysML v2 model exercising the longeron package:
// structure, calculations, constraints, requirements, actions, and states.
package Drone {
    doc /* A small quad-copter drone, modeled for the longeron demo. */

    // ----- structure ---------------------------------------------------

    part def Battery {
        attribute capacity : Real = 5200.0;      // mAh (no ampere-hour unit in the vendored SI)
        attribute voltage : Real = 11.1 [SI::V]; // 3S LiPo nominal
        attribute mass : Real = 0.38 [SI::kg];
    }

    part def Motor {
        doc /* A 2212-class brushless outrunner.  kV is the motor velocity
               constant in rpm per volt (no such unit in the vendored SI). */
        attribute kV : Real = 920.0;             // rpm/V
        attribute maxCurrent : Real = 16.0 [SI::A];
        attribute mass : Real = 0.048 [SI::kg];
    }

    part def Propeller {
        doc /* A 10x4.5 slow-fly propeller; discArea is the swept disc. */
        attribute diameter : Real = 0.254 [SI::m];   // 10 in
        attribute pitch : Real = 0.1143 [SI::m];     // 4.5 in
        attribute mass : Real = 0.012 [SI::kg];
        attribute discArea : Real = pi * (diameter / 2.0) ** 2.0;   // m^2
    }

    part def Frame {
        attribute mass : Real = 0.42 [SI::kg];   // incl. FC, wiring, camera mount
    }

    part def Camera {
        doc /* The forward-looking mission camera.  Placement offsets are
               metres from the airframe origin (the top-plate centre) in
               the geometry frame (+x forward, +y up); azimuth yaws the
               boresight left of +x, elevation pitches it above the
               horizon.  Lens and mount mass ride in the Frame's build
               allowance. */
        attribute x : Real = 0.06 [SI::m];
        attribute y : Real = 0.0 [SI::m];
        attribute z : Real = 0.0 [SI::m];
        attribute azimuth : Real = 0.0 [SI::'°'];
        attribute elevation : Real = -15.0 [SI::'°'];
        attribute fieldOfView : Real = 50.0 [SI::'°'];
    }

    part def QuadCopter {
        attribute payloadMass : Real = 0.2 [SI::kg];
        attribute totalMass : Real =
            chassis.mass + battery.mass + 4.0 * 0.048 + 4.0 * 0.012 + payloadMass;
        attribute maxTakeoffMass : Real = 1.5 [SI::kg];
        // per-rotor static thrust from the fitted motor + propeller (all
        // four stations are the same variant, so ->head() reads the
        // per-unit value off the homogeneous [4] populations)
        attribute thrustPerRotor : Real = PropThrust(
            kV = motors.kV->head(),
            voltage = battery.voltage,
            diameter = propellers.diameter->head()
        );

        // ----- attitude / cruise performance (see the Attitude calc
        // defs below for the derivation) -------------------------------
        // parasite drag area CdA, built up bluff-body style (the
        // uav_missions.sysml BluffFrameDrag idiom): ~0.024 m^2 of frontal
        // area (body + battery stack + four arms + motor cans + props in
        // edgewise flow) times Cd ~1.1 for an open frame
        attribute frontalArea : Real = 0.024;               // m^2
        attribute dragArea : Real = frontalArea * 1.1;      // parasite CdA, m^2
        // sustained flight runs partial throttle: motor thermals and
        // control headroom hold CONTINUOUS thrust to ~55% of bench static
        attribute continuousThrustFraction : Real = 0.55;
        attribute usableThrust : Real =
            4.0 * thrustPerRotor * continuousThrustFraction;    // N, continuous
        // the flight controller's commanded-attitude cap: comfort and
        // controllability, far below the physics ceiling
        attribute maxOperationalTilt : Real = 25.0 [SI::'°'];
        attribute maxTilt : Real = MaxTilt(
            massKg = totalMass, thrustN = usableThrust
        );                                                   // deg, physics cap
        attribute cruiseTilt : Real = CruiseTilt(
            massKg = totalMass,
            thrustN = usableThrust,
            opsCapDeg = maxOperationalTilt
        );                                                   // deg, commanded
        attribute maxCruiseSpeed : Real = MaxCruiseSpeed(
            tiltDeg = cruiseTilt, massKg = totalMass, dragArea = dragArea
        );                                                   // m/s

        part chassis : Frame;
        part battery : Battery;
        part motors : Motor[4];
        part propellers : Propeller[4];
        part camera : Camera;

        assert constraint takeoffMassLimit { totalMass <= maxTakeoffMass }
        assert constraint canHover {
            4.0 * thrustPerRotor > totalMass * 9.81
        }
    }

    enum def FlightMode { manual; altitudeHold; autonomous; }

    // ----- analysis -----------------------------------------------------

    calc def PropThrust {
        doc /* Static thrust of a fixed-pitch propeller on a brushless
               motor: the standard propeller relation T = Ct * rho * n^2 *
               d^4 (momentum / blade-element theory), with rho = 1.225
               kg/m^3 sea-level air, Ct = 0.11 a typical static thrust
               coefficient for slow-fly props, and the loaded rev rate
               n = 0.75 * kV * V / 60 rev/s (a loaded motor holds roughly
               three quarters of its unloaded kV * V speed).  At the stock
               design point (920 rpm/V, 11.1 V, 10 in) this gives 9.14 N
               per rotor -- within 2% of the 9.0 N the pre-split model
               lumped onto its Rotor. */
        in kV : Real;         // rpm/V
        in voltage : Real;    // V
        in diameter : Real;   // m
        return : Real =
            0.11 * 1.225 * (0.75 * kV * voltage / 60.0) ** 2.0 * diameter ** 4.0;
    }

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

    // ----- attitude & mission time --------------------------------------
    // A multirotor holds altitude with its thrust vector tilted by theta:
    //   vertical    T cos(theta) = m g          (altitude hold)
    //   horizontal  T sin(theta) = 0.5 rho CdA v^2   (parasite drag)
    // so theta_max = arccos(m g / T) at the usable thrust T, and the
    // drag balance gives tan(theta) = 0.5 rho CdA v^2 / (m g) -- invert
    // for the fastest level cruise a commanded tilt sustains.  At the
    // stock point (T/W ~ 3.0) the full-throttle ceiling would be ~70 deg
    // and even the continuous-thrust (55%) ceiling is ~53 deg --
    // unrealistically sporty, so the COMMANDED tilt is the min() of the
    // physics cap and the operational comfort cap (25 deg), both visible
    // as QuadCopter attributes.  First-order honest: sea-level rho,
    // rotor induced effects and frame lift ignored, drag purely
    // parasitic.  Stock numbers: cruiseTilt 25 deg -> 18.7 m/s;
    // mission time over tutorial 10's 3.9 km Atlanta loop ~4.5 min.

    calc def MaxTilt {
        doc /* The altitude-hold tilt ceiling, degrees: arccos(m g / T)
               at the usable (continuous) total thrust T.  The ratio is
               clamped at 1 so an overloaded airframe reads 0 deg (it
               cannot hold altitude tilted at all) instead of a domain
               error. */
        in massKg : Real;
        in thrustN : Real;      // usable TOTAL thrust, N (all rotors)
        return : Real = acos(min(1.0, massKg * 9.81 / thrustN)) * 180.0 / pi;
    }

    calc def TiltForSpeed {
        doc /* The level-cruise tilt that holds speed v, degrees:
               tan(theta) = 0.5 rho CdA v^2 / (m g). */
        in speed : Real;        // m/s
        in massKg : Real;
        in dragArea : Real;     // parasite CdA, m^2
        return : Real = atan(
            0.5 * 1.225 * dragArea * speed * speed / (massKg * 9.81)
        ) * 180.0 / pi;
    }

    calc def CruiseTilt {
        doc /* The commanded cruise tilt: the physics ceiling capped by
               the operational comfort limit. */
        in massKg : Real;
        in thrustN : Real;
        in opsCapDeg : Real;
        return : Real = min(
            MaxTilt(massKg = massKg, thrustN = thrustN), opsCapDeg
        );
    }

    calc def MaxCruiseSpeed {
        doc /* TiltForSpeed inverted at the commanded tilt: the fastest
               level cruise it sustains, v = sqrt(m g tan(theta) /
               (0.5 rho CdA)). */
        in tiltDeg : Real;
        in massKg : Real;
        in dragArea : Real;
        return : Real = sqrt(
            massKg * 9.81 * tan(tiltDeg * pi / 180.0) / (0.5 * 1.225 * dragArea)
        );
    }

    calc def MissionTime {
        doc /* Route time at the achievable per-phase speeds, minutes:
               the horizontal legs at cruiseSpeed, the climb to route
               altitude and the descent home at the operational vertical
               rates.  The distances are geometry, measured off the
               mission's waypoint legs by
               longeron.analysis.mission3d.mission_values and passed in
               (the same kernel-measures seam as the installation
               requirement). */
        in routeM : Real;               // horizontal route length, m
        in climbM : Real;               // takeoff climb, m
        in descentM : Real;             // landing descent, m
        in cruiseSpeed : Real;          // m/s
        in climbRate : Real = 2.0;      // m/s, ops climb rate
        in descentRate : Real = 1.5;    // m/s, ops descent rate
        return : Real = (routeM / cruiseSpeed + climbM / climbRate
            + descentM / descentRate) / 60.0;
    }

    requirement def FlightEnvelope {
        doc /* The drone shall hover with a comfortable thrust margin. */
        subject drone : QuadCopter;
        assume constraint { drone.totalMass > 0.0 }
        require constraint hoverMargin {
            ThrustToWeight(thrust = 4.0 * drone.thrustPerRotor, mass = drone.totalMass) >= 1.8
        }
    }

    requirement installation {
        doc /* The geometric installation envelope.  Both measures are
               computed kernel-side by longeron.analysis.geometry
               (camera_occlusion / disc_overlap): CAD boolean
               intersections against the same parametric solids
               to_cadquery builds (with the cad extra installed;
               a deterministic volume-quadrature estimate of the same
               measures otherwise), injected into the scoreboard as
               values= bindings for the unvalued attributes below --
               see tutorial 10. */
        subject drone : QuadCopter;
        attribute occludedFraction : Real;    // measured: airframe volume inside the view cone / cone volume
        attribute discOverlapVolume : Real;   // measured: m^3 of prop-disc overlap with other components

        requirement clearView {
            doc /* The camera's view cone -- apex at the lens, axis along
                   the boresight, half-angle fieldOfView / 2, reaching one
                   airframe bounding-box diagonal -- shall contain no part
                   of the drone's own airframe. */
            attribute weight : Real = 2.0;
            attribute utility : String = "smaller-is-better";
            attribute ramp0 : Real = 0.001;
            attribute ramp1 : Real = 0.0;
            attribute measure : Real = occludedFraction;
            attribute unit : String = "fraction";
            require constraint viewBudget { occludedFraction <= 0.0 }
        }

        requirement propClearance {
            doc /* No propeller disc shall overlap any other component
                   (zero intersection volume between each disc's thin
                   cylinder and the rest of the assembly). */
            attribute weight : Real = 1.0;
            attribute utility : String = "smaller-is-better";
            attribute ramp0 : Real = 0.00002;
            attribute ramp1 : Real = 0.0;
            attribute measure : Real = discOverlapVolume;
            attribute unit : String = "m^3";
            require constraint noOverlap { discOverlapVolume <= 0.0 }
        }
    }

    requirement mission {
        doc /* The mission-time budget.  missionMinutes is measured
               kernel-side by longeron.analysis.mission3d.mission_values:
               the demo route's waypoint legs at the model's own
               achievable speeds (MissionTime over maxCruiseSpeed at
               cruiseTilt), injected into the scoreboard as a values=
               binding for the unvalued attribute below -- see
               tutorial 10. */
        subject drone : QuadCopter;
        attribute missionMinutes : Real;   // measured: MissionTime over the route legs

        requirement missionTime {
            doc /* The demo sortie shall finish inside the mission-time
                   budget (battery comfort and airspace-slot discipline). */
            attribute weight : Real = 1.5;
            attribute utility : String = "smaller-is-better";
            attribute ramp0 : Real = 6.0;      // at the budget: utility 0
            attribute ramp1 : Real = 4.0;      // comfortable: utility 1
            attribute measure : Real = missionMinutes;
            attribute unit : String = "min";
            attribute budget : Real = 6.0 [SI::min];
            require constraint timeBudget { missionMinutes <= budget }
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
