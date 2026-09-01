// DeepScout program -- sizing.sysml: the structural-sizing contexts.
//
// Two sizing views of the program, one discrete and one continuous:
//
//   * TradeQuad -- a quad-copter component catalog restated in
//     fixed-point-friendly arithmetic (thrust split into a per-motor
//     term and a per-propeller kt), so the CP-SAT mapper of
//     longeron.analysis.trades can enumerate, optimize, and EXPLAIN it
//     exactly.  PicnicQuad is its deliberately over-constrained sibling
//     (no catalog mix satisfies it -- the UNSAT-explanation demo).
//   * IsrPrime -- the ISR trade winner frozen as a concrete continuous
//     sizing context for the OpenMDAO / Z3 bridges, spelled out
//     discipline by discipline with the shared calc defs of DeepScout.
package ScoutSizing {
    doc /* Discrete and continuous sizing contexts for the DeepScout
           program.  The TradeQuad catalog is a fixed-point RESTATEMENT
           of small racing-class parts (real motors, props, and packs;
           thrustTerm and kt precomputed to catalog precision) because
           CP-SAT's exact arithmetic needs short decimals; IsrPrime
           freezes the fleet's ISR winner with the loiter speed left
           continuous.  Nominal figures throughout. */

    private import DeepScout::Aerodynamics::*;
    private import DeepScout::Propulsion::*;
    private import DeepScout::Structures::*;
    private import DeepScout::Performance::*;

    // ----- the discrete catalog (CP-SAT's subject) -------------------------
    // Thrust is a genuine function of the motor AND propeller choices --
    // per rotor T = kt * motors.thrustTerm * diameterIn^4, the standard
    // propeller relation T = Ct * rho * n^2 * d^4 split into a per-motor
    // factor and a per-propeller factor so CP-SAT's fixed-point
    // arithmetic stays exact (see the attribute doc comments).  Mixes
    // that per-motor thrust ratings would gloss over assess honestly: a
    // 920 rpm/V cruiser motor swinging a 5-inch racing prop produces
    // about one newton and cannot lift anything.

    part def Motor {
        attribute mass : Real;          // kg, per motor
        attribute cost : Real;          // USD, per motor
        attribute kv : Real;            // rpm/V (velocity constant)
        attribute cells : Integer;      // required battery cell count
        attribute voltage : Real = 3.7 * cells;   // V, nominal pack voltage
        // per-motor thrust factor: rho * (0.75 * kv * voltage / 60)^2 *
        // 0.0254^4, i.e. T = kt * thrustTerm * diameterIn^4 [N] with the
        // propeller's kt and diameter in inches.  Precomputed to catalog
        // precision (4 significant digits) because CP-SAT's fixed-point
        // encoding needs short decimals; the formula is PropThrust in
        // DeepScout::Propulsion with Ct factored out to the propeller.
        attribute thrustTerm : Real;    // N per (kt * in^4)
        attribute hoverCurrent : Real;  // mA at hover, per motor
        attribute maxCurrent : Real;    // A burst, per motor
        attribute maxPropIn : Real;     // largest compatible prop, inches
    }

    part def Propeller {
        attribute mass : Real;
        attribute cost : Real;
        attribute diameterIn : Real;    // inches
        attribute pitchIn : Real;       // inches per revolution
        // effective static-thrust coefficient, referenced to the shared
        // 75%-of-unloaded rev-rate convention of thrustTerm: it absorbs
        // the load-dependent rpm sag (a lightly loaded racing prop runs
        // near unloaded speed, a big slow-fly prop drags a small motor
        // well below it), calibrated per prop against bench ratings.
        attribute kt : Real;
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
        attribute kv : Real = 2400.0;    attribute cells : Integer = 4;
        attribute thrustTerm : Real = 0.1005;   // rho*(0.75*2400*14.8/60)^2*0.0254^4
        attribute hoverCurrent : Real = 3200.0;
        attribute maxCurrent : Real = 32.0;
        attribute maxPropIn : Real = 5.1;
    }
    part def TMotorF60 :> Motor {
        attribute mass : Real = 0.034;   attribute cost : Real = 28.0;
        attribute kv : Real = 1750.0;    attribute cells : Integer = 6;
        attribute thrustTerm : Real = 0.1202;   // rho*(0.75*1750*22.2/60)^2*0.0254^4
        attribute hoverCurrent : Real = 4000.0;
        attribute maxCurrent : Real = 38.0;
        attribute maxPropIn : Real = 5.1;
    }
    part def SunnySky2212 :> Motor {
        attribute mass : Real = 0.056;   attribute cost : Real = 17.0;
        attribute kv : Real = 920.0;     attribute cells : Integer = 3;
        attribute thrustTerm : Real = 0.0083;   // rho*(0.75*920*11.1/60)^2*0.0254^4
        attribute hoverCurrent : Real = 2200.0;
        attribute maxCurrent : Real = 20.0;
        attribute maxPropIn : Real = 10.0;
    }

    part def Hq5x43 :> Propeller {
        attribute mass : Real = 0.004;   attribute cost : Real = 3.0;
        attribute diameterIn : Real = 5.0;  attribute pitchIn : Real = 4.3;
        attribute kt : Real = 0.21;
    }
    part def Tri5x35 :> Propeller {
        attribute mass : Real = 0.005;   attribute cost : Real = 4.0;
        attribute diameterIn : Real = 5.0;  attribute pitchIn : Real = 3.5;
        attribute kt : Real = 0.22;      // tri-blade: more blade area
    }
    part def Apc1045 :> Propeller {
        attribute mass : Real = 0.014;   attribute cost : Real = 4.0;
        attribute diameterIn : Real = 10.0; attribute pitchIn : Real = 4.5;
        attribute kt : Real = 0.1;       // slow-fly: heavy load sags the rpm
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
        // thrust is motor x propeller: T = kt * thrustTerm * d^4 per rotor
        attribute totalThrust : Real =
            4.0 * props.kt * motors.thrustTerm * props.diameterIn ** 4.0;
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

    // ----- continuous sizing context (OpenMDAO / Z3) ------------------------------------

    part def IsrPrime {
        doc /* The ISR trade winner frozen as a concrete sizing context:
               the component mix is baked in (vtolWing + mn4006
               Antigravity motors + apc11x55 props + the liion6s6p energy
               pack + zenmuseH20 gimbal + carbonFiber spar), the loiter
               speed stays continuous -- and the chain from configuration
               to time-on-station is spelled out discipline by discipline
               with the shared calc defs, so the generated OpenMDAO
               problem tells the classic MDO story: Aerodynamics builds
               the drag, Structures sizes the spar and its mass,
               Propulsion turns mass and drag into power and usable
               energy, Performance turns power into minutes on station. */

        attribute loiterSpeed : Real = 15.0;    // m/s -- the design variable

        // frozen winner configuration (catalog values of the mix above)
        attribute emptyMassKg : Real = 5.28;    // shell+avionics+pack+motors/props+sensor
                                                // (+0.29 kg: the tip-prop spar doublers)
        attribute fuselageLength : Real = 0.95;
        attribute fuselageDiameter : Real = 0.12;
        attribute span : Real = 2.6;
        attribute wingArea : Real = 0.624;
        attribute secondaryWingArea : Real = 0.387;
        attribute spanEff : Real = 0.9962;      // 0.82 Oswald x 1.2149 derived tip recovery
        attribute propEff : Real = 0.697;       // APC 11x5.5E x Antigravity motor
        attribute sensorPowerW : Real = 18.0;   // Zenmuse H20
        attribute batteryWh : Real = 447.0;     // liion6s6p
        attribute hoverOpsSec : Real = 120.0;   // takeoff + landing budget
        attribute diskArea : Real =             // 3.3 disks x 11 in prop
            3.3 * 3.141592653589793 * 0.2794 * 0.2794 / 4.0;
        attribute designGrossKg : Real = 6.0;
        attribute sparRadius : Real = 0.012;
        attribute minWallM : Real = 0.0005;     // manufacturing gauge floor
        attribute sparDensity : Real = 1600.0;  // carbon fiber tube
        attribute sparYieldPa : Real = 6.0e8;

        // Aerodynamics: the same wetted-area buildup the catalog uses
        attribute dragArea : Real = 1.15 * (
            SkinFrictionDrag(
                wettedArea = BodyWettedArea(length = fuselageLength,
                                            diameter = fuselageDiameter),
                formFactor = BodyFormFactor(length = fuselageLength,
                                            diameter = fuselageDiameter))
            + SkinFrictionDrag(          // main pair, NACA 2412
                wettedArea = WingWettedArea(planformArea = wingArea),
                formFactor = WingFormFactor(thicknessRatio = 0.12))
            + SkinFrictionDrag(          // secondary pair, NACA 0009
                wettedArea = WingWettedArea(planformArea = secondaryWingArea),
                formFactor = WingFormFactor(thicknessRatio = 0.09))
            + 4.0 * SkinFrictionDrag(    // wingtip motor pods
                wettedArea = BodyWettedArea(length = 0.12, diameter = 0.045),
                formFactor = BodyFormFactor(length = 0.12, diameter = 0.045)));

        // Structures: spar sized by the root bending moment, mass rolled up
        attribute sparWall : Real = max(minWallM,
            TubeWallForStress(
                momentNm = SparRootMoment(grossKg = designGrossKg,
                                          span = span),
                radius = sparRadius,
                yieldPa = sparYieldPa));
        attribute sparMassKg : Real =
            TubeMass(radius = sparRadius, wall = sparWall,
                     length = span, density = sparDensity);
        attribute massKg : Real = emptyMassKg + sparMassKg;

        // Propulsion: hover sets the energy reserve, cruise sets the burn
        attribute hoverPowerW : Real =
            HoverPower(massKg = massKg, diskArea = diskArea);
        attribute usableEnergyJ : Real =
            UsableEnergy(batteryWh = batteryWh, hoverPowerW = hoverPowerW,
                         hoverOpsSec = hoverOpsSec);
        attribute loiterPowerW : Real = CruisePower(
            massKg = massKg, speed = loiterSpeed, dragArea = dragArea,
            span = span, wingArea = wingArea, spanEff = spanEff,
            propEff = propEff);

        // Performance: usable energy over the loiter burn
        attribute stationMinutes : Real =
            StationTime(usableEnergyJ = usableEnergyJ,
                        loiterPowerW = loiterPowerW,
                        sensorPowerW = sensorPowerW);

        assert constraint aboveStall { loiterSpeed >= 11.0 }
        assert constraint belowCruise { loiterSpeed <= 24.0 }
    }

    requirement def IsrStation {
        doc /* The ISR bird shall hold station for at least 90 minutes. */
        subject uav : IsrPrime;
        assume constraint { uav.loiterSpeed > 0.0 }
        require constraint stationFloor { uav.stationMinutes >= 90.0 }
    }
}
