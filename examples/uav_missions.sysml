// A multi-mission UAV catalog for the longeron.analysis trade machinery.
//
// One component catalog (airframes, motors, props, batteries, mission
// equipment) is evaluated against THREE mission contexts, each a part
// definition specializing the shared assembly with its own equipment,
// metrics, and requirements:
//
//   IsrUav       -- loiter on station with a sensor package (max station time)
//   LogisticsUav -- carry a parcel out, return empty (max payload x radius)
//   InterceptUav -- one-way dash to catch a crossing target (max target speed)
//
// All physics lives in `calc def`s the interpreter evaluates directly --
// momentum-theory hover, a wetted-area parasite-drag buildup feeding
// parasite+induced-drag cruise, drag-limited dash, and load-based
// structural sizing (rotor arms and wing spars as bending-sized tubes in
// a selectable material) -- so the model itself carries the analysis.  These formulas (sqrt/pow,
// conditionals, calc invocations) are beyond the CP-SAT mapper's linear
// arithmetic; the intended workflow is TradeStudy.all_architectures() /
// evaluate(): enumerate the Cartesian candidate space and let the
// interpreter score every mix exactly (see notebook 07).
package UavMissions {
    doc /* Multi-mission UAV catalog: four airframe families, tiered
           components, a structural-material trade, and three mission
           contexts with executable physics (drag buildup + tube sizing
           included).  The calc defs are organized into DISCIPLINE
           packages (Aerodynamics, Propulsion, Structures, Performance)
           and the variation points into a Catalog package -- the model's
           own structure is what groups the generated OpenMDAO problem
           into the classic discipline blocks of an N2 diagram. */

    private import Aerodynamics::*;
    private import Propulsion::*;
    private import Structures::*;
    private import Performance::*;
    private import Catalog::*;

    // ----- external-analysis annotation ------------------------------------
    // Declares that a calc def's in/out parameters are the I/O contract of
    // a higher-fidelity tool wrapped as an OpenMDAO component.  `component`
    // is an entry-point path 'module:attr' (a Component subclass or a
    // factory callable).  longeron.analysis.mdao.build_problem validates the
    // declared parameters against the component's actual I/O and can swap
    // fidelity per calc (candidate for a shared library package later).

    metadata def ExternalAnalysis {
        doc /* Marks a calc def as bindable to an external analysis
               component; the calc's parameters declare the contract. */
        attribute component : String;
    }

    // ----- discipline packages ----------------------------------------------
    // The physics calc defs live in one package per discipline.  This is
    // not cosmetic: longeron.analysis.mdao reads an attribute's calc
    // invocations and groups the generated OpenMDAO components by the
    // owning package, so the N2 diagram shows Aerodynamics / Propulsion /
    // Structures / Performance blocks because the MODEL says so.

    package Propulsion {
        doc /* Hover and cruise power, and the energy ledger they draw
               against. */

        calc def HoverPower {
            doc /* Momentum-theory hover power: ideal induced power from disk
                   loading, over an overall hover system efficiency (rotor
                   figure of merit x motor/ESC losses). */
            in massKg : Real;
            in diskArea : Real;         // total rotor disk area, m^2
            in systemEff : Real = 0.55;
            return : Real = pow(massKg * 9.81, 1.5)
                / sqrt(2.0 * 1.225 * diskArea) / systemEff;
        }

        calc def CruisePower {
            @ExternalAnalysis { component = "uav_aero:CruisePowerPolar"; }
            doc /* First-order wing-borne cruise power: parasite drag (CdA) plus
                   induced drag at speed V, over the propulsive efficiency.
                   `spanEff` is the Oswald factor TIMES the wingtip-prop bonus:
                   props mounted on wingtip nacelles rotate against the tip
                   vortices and recover part of the induced loss, raising the
                   wing's effective L/D.  `wingArea` is declared for the
                   external component (examples/uav_aero.py), whose
                   Reynolds-scaled drag polar with a stall-adjacent drag rise
                   needs the reference area; this first-order body does not. */
            in massKg : Real;
            in speed : Real;            // m/s
            in dragArea : Real;         // parasite drag area CdA, m^2
            in span : Real;             // wing span, m
            in wingArea : Real;         // reference area, m^2 (external polar)
            in spanEff : Real;          // Oswald e x wingtip-prop bonus
            in propEff : Real;          // prop x motor efficiency
            return : Real = (0.5 * 1.225 * dragArea * speed * speed * speed
                + 2.0 * (massKg * 9.81) * (massKg * 9.81)
                  / (1.225 * speed * 3.141592653589793 * spanEff * span * span))
                / propEff;
        }

        calc def RotorCruisePower {
            doc /* Rotor-borne translation (no wing): induced power stays at
                   the hover level while parasite drag power grows with V^3. */
            in massKg : Real;
            in speed : Real;
            in diskArea : Real;
            in dragArea : Real;
            in propEff : Real;
            return : Real = HoverPower(massKg = massKg, diskArea = diskArea)
                + 0.5 * 1.225 * dragArea * speed * speed * speed / propEff;
        }

        calc def UsableEnergy {
            doc /* The battery joules a mission may actually plan on:
                   pack energy at a usable depth-of-discharge fraction,
                   less the hover budget (takeoff + landing) at hover
                   power. */
            in batteryWh : Real;
            in hoverPowerW : Real;
            in hoverOpsSec : Real;
            in usableFraction : Real = 0.8;
            return : Real = batteryWh * 3600.0 * usableFraction
                - hoverPowerW * hoverOpsSec;
        }
    }

    package Aerodynamics {
        doc /* The parasite-drag buildup.  Each airframe's CdA is a
               wetted-area buildup, not a quoted number: CdA = sum over
               surfaces of Cf x S_wet x form factor (flat-plate skin
               friction at a fixed representative Cf), plus a bluff-body
               term for open frames and exposed rotor gear.  The teardrop
               shell earns its slender-body advantage from these terms;
               bigger wings really do pay for their extra skin. */

        calc def SkinFrictionDrag {
            doc /* One streamlined surface's parasite drag area: flat-plate
                   skin-friction coefficient x wetted area x form factor.
                   Cf = 0.0055 is a fixed representative value for small-UAV
                   Reynolds numbers (~3e5..1e6, mostly turbulent). */
            in wettedArea : Real;       // m^2
            in formFactor : Real;       // >= 1, pressure-drag multiplier
            in frictionCoeff : Real = 0.0055;
            return : Real = frictionCoeff * wettedArea * formFactor;
        }

        calc def BodyWettedArea {
            doc /* Lathed-body wetted area: ~0.75 x the enclosing cylinder
                   (teardrop/ogive bodies of revolution). */
            in length : Real;
            in diameter : Real;
            return : Real = 0.75 * 3.141592653589793 * diameter * length;
        }

        calc def BodyFormFactor {
            doc /* Slender-body form factor by fineness ratio l/d: ~1.24 at
                   l/d 5 falling toward ~1.13 at l/d 11 (Hoerner-style). */
            in length : Real;
            in diameter : Real;
            return : Real = 1.05 + 0.9 * diameter / length;
        }

        calc def WingWettedArea {
            doc /* Both faces plus section curvature: 2.05 x exposed
                   planform (a cruciform counts both pairs). */
            in planformArea : Real;
            return : Real = 2.05 * planformArea;
        }

        calc def WingFormFactor {
            doc /* Hoerner wing form factor by thickness ratio:
                   1 + 2.7 t/c + 100 (t/c)^4 -- ~1.25 at 9%, ~1.34 at 12%. */
            in thicknessRatio : Real;
            return : Real = 1.0 + 2.7 * thicknessRatio
                + 100.0 * pow(thicknessRatio, 4.0);
        }

        calc def BluffFrameDrag {
            doc /* Open-frame / exposed-gear drag area: frontal area x a
                   bluff-body Cd (~1.1 for plates, arms, and motor cans). */
            in frontalArea : Real;      // m^2
            in dragCoeff : Real = 1.1;
            return : Real = frontalArea * dragCoeff;
        }
    }

    package Structures {
        doc /* Load-based sizing.  Quad arms and wing spars are round
               tubes sized by the loads they carry -- bending stress with
               a safety factor AND a tip-deflection stiffness floor -- in
               the selected structural material, so material density,
               stiffness, strength, and $/kg all reach the mission
               metrics through the mass and cost build-ups. */

        calc def TubeWallForStress {
            doc /* Thin-walled round tube in bending: sigma = M r / I with
                   I = pi r^3 t  =>  wall t = M x SF / (pi r^2 sigma_y). */
            in momentNm : Real;
            in radius : Real;
            in yieldPa : Real;
            in safetyFactor : Real = 2.0;
            return : Real = momentNm * safetyFactor
                / (3.141592653589793 * radius * radius * yieldPa);
        }

        calc def TubeWallForStiffness {
            doc /* Cantilever tip deflection delta = F L^3 / (3 E I) with
                   I = pi r^3 t, capped at deflectionRatio x L  =>
                   t = F L^2 / (3 E pi r^3 x deflectionRatio). */
            in tipLoadN : Real;
            in length : Real;
            in radius : Real;
            in modulusPa : Real;
            in deflectionRatio : Real = 0.02;
            return : Real = tipLoadN * length * length
                / (3.0 * modulusPa * 3.141592653589793
                   * pow(radius, 3.0) * deflectionRatio);
        }

        calc def TubeMass {
            doc /* Thin-walled tube mass: A = 2 pi r t, m = A L rho. */
            in radius : Real;
            in wall : Real;
            in length : Real;
            in density : Real;
            return : Real = 2.0 * 3.141592653589793 * radius * wall
                * length * density;
        }

        calc def SparRootMoment {
            doc /* Root bending moment of one wing panel under an
                   elliptic-ish lift distribution at load factor n: half the
                   lift acts at the elliptic centroid 4/(3 pi) of the
                   half-span  =>  M = n W b / (3 pi) ~ 0.106 n W b. */
            in grossKg : Real;
            in span : Real;
            in loadFactor : Real = 2.5;
            return : Real = loadFactor * grossKg * 9.81 * span
                / (3.0 * 3.141592653589793);
        }
    }

    package Performance {
        doc /* Mission performance: what the sized, powered aircraft is
               worth in mission units -- top speed, time on station. */

        calc def DashSpeed {
            doc /* Parasite-drag-limited level top speed: available propulsive
                   power = 0.5 rho CdA V^3 (induced drag is negligible at dash
                   speeds). */
            in powerW : Real;           // propulsive power, W (elec x eta)
            in dragArea : Real;
            return : Real = pow(2.0 * powerW / (1.225 * dragArea), 1.0 / 3.0);
        }

        calc def StationTime {
            doc /* Time on station in minutes: usable energy over the
                   loiter burn (aircraft + sensor draw). */
            in usableEnergyJ : Real;
            in loiterPowerW : Real;
            in sensorPowerW : Real;
            return : Real = usableEnergyJ
                / (loiterPowerW + sensorPowerW) / 60.0;
        }
    }

    // ----- component families -----------------------------------------------

    part def Airframe {
        attribute mass : Real;              // kg, shell/frame less arms+spar
        attribute cost : Real;              // USD
        attribute dragArea : Real;          // parasite CdA, m^2 (buildup)
        attribute wingSpan : Real;          // m; 0 = rotor-borne only
        attribute wingChord : Real;         // m, mean
        attribute taper : Real;             // tip/root chord ratio
        attribute wingArea : Real;          // m^2
        attribute oswald : Real;            // span efficiency e
        attribute tipPropBonus : Real;      // induced-drag recovery, >= 1
        attribute loiterSpeed : Real;       // m/s, on-station speed
        attribute cruiseSpeed : Real;       // m/s, transit speed
        attribute motorCount : Integer;     // populated motor stations
        attribute diskAreaFactor : Real;    // total disk area / one prop disk
        attribute hoverThrustFactor : Real; // req. thrust/weight (0 = rail)
        attribute payloadCapacity : Real;   // kg
        attribute hoverOpsSec : Real;       // hover budget per sortie, s
        attribute fuselageLength : Real;    // m (geometry)
        attribute armCount : Integer;       // cantilever rotor arms to size
        attribute sparRadius : Real;        // m, wing-spar tube radius
        attribute designGrossKg : Real;     // spar design gross mass (0 = no wing)
    }

    part def StructuralMaterial {
        doc /* A tube-stock structural material: the arm/spar sizing
               calcs read strength and stiffness, the build-ups read
               density and finished-tube cost. */
        attribute density : Real;           // kg/m^3
        attribute modulusPa : Real;         // Pa, Young's modulus
        attribute yieldPa : Real;           // Pa, usable bending strength
        attribute costPerKg : Real;         // USD/kg, finished tube
    }

    part def Motor {
        attribute mass : Real;              // kg, per motor
        attribute cost : Real;
        attribute maxThrust : Real;         // N static, matched prop
        attribute maxPowerW : Real;         // W electrical, continuous
        attribute efficiency : Real;        // electrical -> shaft
        attribute maxPropDiameter : Real;   // m
    }

    part def Propeller {
        attribute mass : Real;
        attribute cost : Real;
        attribute diameter : Real;          // m
        attribute cruiseEff : Real;         // shaft -> propulsive
    }

    part def Battery {
        attribute mass : Real;
        attribute cost : Real;
        attribute energyWh : Real;
        attribute maxPowerW : Real;         // continuous discharge
    }

    part def SensorPackage {
        attribute mass : Real;
        attribute cost : Real;
        attribute powerW : Real;
        attribute grade : Integer;          // 1 fixed EO .. 3 long-range
    }

    part def CargoBay {
        attribute bayMass : Real;           // kg, bay/box structure
        attribute bayCost : Real;
        attribute payloadKg : Real;         // parcel delivered
    }

    // ----- catalog entries ----------------------------------------------------

    // Airframes: a cheap rotor-only quad, a streamlined teardrop-body
    // quad (same rotor-borne physics, a fraction of the box frame's CdA,
    // but a slim payload bay; the bullet body stands through the rotor
    // plane), a cruciform tail-sitter VTOL (one long wing pair, one
    // shorter pair, a wingtip prop on each of the four tips with thrust
    // along the chords/body axis: it hovers nose-up on its props and
    // pitches over to cruise wing-borne), and a rail-launched
    // streamlined interceptor (hoverThrustFactor 0: no hover
    // requirement, no hover budget).  Every dragArea is a wetted-area /
    // bluff-body BUILDUP from the family's own geometry (the calc defs
    // above); `mass` excludes the rotor arms and wing spar, which the
    // assembly sizes from loads in the selected material.
    part def BoxQuad :> Airframe {
        // open 450-class frame: no skin to speak of -- the whole CdA is
        // bluff (tilted plates, battery brick, motor cans in the wind)
        attribute frameFrontalArea : Real = 0.050;  // m^2, forward flight
        attribute dragArea : Real =
            BluffFrameDrag(frontalArea = frameFrontalArea);
        attribute mass : Real = 0.78;   attribute cost : Real = 95.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 14.0;
        attribute motorCount : Integer = 4;
        attribute diskAreaFactor : Real = 4.0;
        attribute hoverThrustFactor : Real = 1.6;
        attribute payloadCapacity : Real = 6.0;
        attribute hoverOpsSec : Real = 90.0;
        attribute fuselageLength : Real = 0.0;
        attribute armCount : Integer = 4;
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size
    }
    part def TeardropQuad :> Airframe {
        // The "do wings matter?" probe: a wingless quad wrapped in a
        // lathed teardrop shell.  Its CdA advantage over the box quad is
        // EARNED by the buildup -- the skinned body is skin friction on
        // a slender lathe, only the arms and motors stay bluff -- and
        // the shell costs money and mass and squeezes the payload bay;
        // the missions decide the rest.
        attribute fuselageLength : Real = 0.62;
        attribute fuselageDiameter : Real = 0.13;
        attribute rotorGearArea : Real = 0.010;  // arms + motor cans, m^2
        attribute dragArea : Real =
            BluffFrameDrag(frontalArea = rotorGearArea)
            + 1.15 * SkinFrictionDrag(   // 1.15: interference/excrescence
                wettedArea = BodyWettedArea(length = fuselageLength,
                                            diameter = fuselageDiameter),
                formFactor = BodyFormFactor(length = fuselageLength,
                                            diameter = fuselageDiameter));
        attribute mass : Real = 0.98;   attribute cost : Real = 200.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 18.0;
        attribute motorCount : Integer = 4;
        attribute diskAreaFactor : Real = 4.0;
        attribute hoverThrustFactor : Real = 1.5;
        attribute payloadCapacity : Real = 1.0;
        attribute hoverOpsSec : Real = 60.0;
        attribute armCount : Integer = 4;
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size
    }
    part def VtolWing :> Airframe {
        // fuselage + BOTH cruciform wing pairs + four wingtip pods: the
        // big wing that buys the loiter also pays for its skin here
        attribute fuselageLength : Real = 0.95;
        attribute fuselageDiameter : Real = 0.12;
        attribute wingSpan : Real = 2.6;  attribute wingChord : Real = 0.24;
        attribute taper : Real = 0.6;     attribute wingArea : Real = 0.624;
        attribute secondaryWingArea : Real = 0.387;  // 0.62-span pair, same chord
        attribute dragArea : Real = 1.15 * (  // interference/excrescence
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
        attribute mass : Real = 1.90;   attribute cost : Real = 480.0;
        attribute oswald : Real = 0.82;   attribute tipPropBonus : Real = 1.28;
        attribute loiterSpeed : Real = 15.0;
        attribute cruiseSpeed : Real = 21.0;
        attribute motorCount : Integer = 4;
        attribute diskAreaFactor : Real = 3.3;  // 2 main + 2 smaller tips
        attribute hoverThrustFactor : Real = 1.45;
        attribute payloadCapacity : Real = 5.5;
        attribute hoverOpsSec : Real = 120.0;
        attribute armCount : Integer = 0;      // rotors ride the wingtips
        attribute sparRadius : Real = 0.012;   // fits the 12% root section
        attribute designGrossKg : Real = 6.0;  // packMax + heavy payload
    }
    part def DartInterceptor :> Airframe {
        // slender lathed body + thin wing + cruciform fins, all skin
        attribute fuselageLength : Real = 1.25;
        attribute fuselageDiameter : Real = 0.11;
        attribute wingSpan : Real = 1.05; attribute wingChord : Real = 0.17;
        attribute taper : Real = 0.5;     attribute wingArea : Real = 0.179;
        attribute tailArea : Real = 0.045;  // cruciform fin planform
        attribute dragArea : Real = 1.15 * (  // interference/excrescence
            SkinFrictionDrag(
                wettedArea = BodyWettedArea(length = fuselageLength,
                                            diameter = fuselageDiameter),
                formFactor = BodyFormFactor(length = fuselageLength,
                                            diameter = fuselageDiameter))
            + SkinFrictionDrag(          // thin NACA 0009 wing
                wettedArea = WingWettedArea(planformArea = wingArea),
                formFactor = WingFormFactor(thicknessRatio = 0.09))
            + SkinFrictionDrag(          // cruciform tail fins
                wettedArea = WingWettedArea(planformArea = tailArea),
                formFactor = WingFormFactor(thicknessRatio = 0.09)));
        attribute mass : Real = 1.08;   attribute cost : Real = 300.0;
        attribute oswald : Real = 0.72;   attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 24.0;
        attribute cruiseSpeed : Real = 30.0;
        attribute motorCount : Integer = 1;   // single pusher
        attribute diskAreaFactor : Real = 1.0;
        attribute hoverThrustFactor : Real = 0.0;  // rail-launched
        attribute payloadCapacity : Real = 0.9;
        attribute hoverOpsSec : Real = 0.0;
        attribute armCount : Integer = 0;      // no rotor arms
        attribute sparRadius : Real = 0.008;   // thin 9% section
        attribute designGrossKg : Real = 2.2;  // launch mass + margin
    }

    part def EcoMotor :> Motor {
        attribute mass : Real = 0.058;  attribute cost : Real = 26.0;
        attribute maxThrust : Real = 17.0;
        attribute maxPowerW : Real = 260.0;
        attribute efficiency : Real = 0.80;
        attribute maxPropDiameter : Real = 0.33;
    }
    part def StdMotor :> Motor {
        attribute mass : Real = 0.092;  attribute cost : Real = 52.0;
        attribute maxThrust : Real = 30.0;
        attribute maxPowerW : Real = 480.0;
        attribute efficiency : Real = 0.85;
        attribute maxPropDiameter : Real = 0.55;
    }
    part def SprintMotor :> Motor {
        attribute mass : Real = 0.150;  attribute cost : Real = 110.0;
        attribute maxThrust : Real = 42.0;
        attribute maxPowerW : Real = 950.0;
        attribute efficiency : Real = 0.88;
        attribute maxPropDiameter : Real = 0.55;
    }

    part def SlimProp :> Propeller {
        attribute mass : Real = 0.012;  attribute cost : Real = 11.0;
        attribute diameter : Real = 0.24;
        attribute cruiseEff : Real = 0.82;
    }
    part def CruiseProp :> Propeller {
        attribute mass : Real = 0.018;  attribute cost : Real = 14.0;
        attribute diameter : Real = 0.33;
        attribute cruiseEff : Real = 0.74;
    }
    part def LifterProp :> Propeller {
        attribute mass : Real = 0.042;  attribute cost : Real = 32.0;
        attribute diameter : Real = 0.51;
        attribute cruiseEff : Real = 0.66;
    }

    part def PackLite :> Battery {
        attribute mass : Real = 0.50;   attribute cost : Real = 70.0;
        attribute energyWh : Real = 90.0;
        attribute maxPowerW : Real = 1100.0;
    }
    part def PackMid :> Battery {
        attribute mass : Real = 0.98;   attribute cost : Real = 130.0;
        attribute energyWh : Real = 180.0;
        attribute maxPowerW : Real = 2000.0;
    }
    part def PackMax :> Battery {
        attribute mass : Real = 1.95;   attribute cost : Real = 250.0;
        attribute energyWh : Real = 360.0;
        attribute maxPowerW : Real = 3200.0;
    }

    part def PathfinderEO :> SensorPackage {
        attribute mass : Real = 0.20;   attribute cost : Real = 90.0;
        attribute powerW : Real = 7.0;  attribute grade : Integer = 1;
    }
    part def StareEoIr :> SensorPackage {
        attribute mass : Real = 0.95;   attribute cost : Real = 420.0;
        attribute powerW : Real = 22.0; attribute grade : Integer = 2;
    }
    part def HawkeyeGimbal :> SensorPackage {
        attribute mass : Real = 1.90;   attribute cost : Real = 1100.0;
        attribute powerW : Real = 55.0; attribute grade : Integer = 3;
    }

    part def ParcelBayS :> CargoBay {
        attribute bayMass : Real = 0.12;  attribute bayCost : Real = 15.0;
        attribute payloadKg : Real = 1.0;
    }
    part def ParcelBayM :> CargoBay {
        attribute bayMass : Real = 0.25;  attribute bayCost : Real = 30.0;
        attribute payloadKg : Real = 2.5;
    }
    part def ParcelBayL :> CargoBay {
        attribute bayMass : Real = 0.45;  attribute bayCost : Real = 55.0;
        attribute payloadKg : Real = 4.0;
    }

    // Structural tube stock: aluminum is cheap and heavy, carbon buys
    // grams (and stiffness) at real money -- the arm/spar sizing turns
    // these four numbers into mission mass and cost.
    part def Aluminum6061 :> StructuralMaterial {
        attribute density : Real = 2700.0;
        attribute modulusPa : Real = 6.9e10;    // 69 GPa
        attribute yieldPa : Real = 2.4e8;       // 240 MPa
        attribute costPerKg : Real = 15.0;      // finished tube
    }
    part def CarbonFiberTube :> StructuralMaterial {
        attribute density : Real = 1600.0;
        attribute modulusPa : Real = 1.1e11;    // ~110 GPa tube layup
        attribute yieldPa : Real = 6.0e8;       // ~600 MPa bending
        attribute costPerKg : Real = 90.0;      // finished tube
    }

    // ----- variation points ---------------------------------------------------

    package Catalog {
        doc /* The variation points under trade: one choice per shared
               subsystem plus the per-mission equipment.  These seven
               points ARE the columns of every parallel-coordinates view
               and the decision variables of every trade study below. */

        variation part def AirframeChoice :> Airframe {
            variant part boxQuad : BoxQuad;
            variant part teardropQuad : TeardropQuad;
            variant part vtolWing : VtolWing;
            variant part dartInterceptor : DartInterceptor;
        }
        variation part def MotorChoice :> Motor {
            variant part ecoMotor : EcoMotor;
            variant part stdMotor : StdMotor;
            variant part sprintMotor : SprintMotor;
        }
        variation part def PropChoice :> Propeller {
            variant part slimProp : SlimProp;
            variant part cruiseProp : CruiseProp;
            variant part lifterProp : LifterProp;
        }
        variation part def BatteryChoice :> Battery {
            variant part packLite : PackLite;
            variant part packMid : PackMid;
            variant part packMax : PackMax;
        }
        variation part def SensorChoice :> SensorPackage {
            variant part pathfinderEO : PathfinderEO;
            variant part stareEoIr : StareEoIr;
            variant part hawkeyeGimbal : HawkeyeGimbal;
        }
        variation part def CargoChoice :> CargoBay {
            variant part parcelBayS : ParcelBayS;
            variant part parcelBayM : ParcelBayM;
            variant part parcelBayL : ParcelBayL;
        }
        variation part def MaterialChoice :> StructuralMaterial {
            variant part aluminum : Aluminum6061;
            variant part carbonFiber : CarbonFiberTube;
        }
    }

    // ----- the shared assembly under trade --------------------------------------

    part def MissionUAV {
        doc /* Airframe + propulsion + battery + structural material,
               common to every mission.  Motor/prop stations are
               homogeneous ([4] selects one type for all); airframe.
               motorCount says how many stations the family populates
               (4, 4, 1), and the mass/cost/thrust build-ups scale by
               it.  Rotor arms and the wing spar are round tubes sized
               HERE from loads (per-rotor thrust bending the arm, the
               elliptic root moment bending the spar) in the selected
               material, so the material choice is a real mass-vs-cost
               trade axis. */

        attribute avionicsMass : Real = 0.18;   // kg: FC, GPS, radios
        attribute avionicsCost : Real = 140.0;
        attribute armTubeRadius : Real = 0.008; // m, rotor-arm tube
        attribute minWallM : Real = 0.0005;     // manufacturing gauge floor

        part airframe : AirframeChoice;
        part motors : MotorChoice[4];
        part props : PropChoice[4];
        part battery : BatteryChoice;
        part material : MaterialChoice;

        // structural sizing: arm length follows the prop disk + tip
        // clearance (the geometry module's spacing rule), tip load is
        // one rotor's max thrust; the spar carries the design gross
        // weight at n = 2.5 on an elliptic-ish distribution
        attribute armLength : Real =
            0.70710678 * (props.diameter + 0.02);
        attribute armWall : Real = max(minWallM, max(
            TubeWallForStress(momentNm = motors.maxThrust * armLength,
                              radius = armTubeRadius,
                              yieldPa = material.yieldPa),
            TubeWallForStiffness(tipLoadN = motors.maxThrust,
                                 length = armLength,
                                 radius = armTubeRadius,
                                 modulusPa = material.modulusPa)));
        attribute armOuterDiameter : Real =
            2.0 * (armTubeRadius + armWall);
        attribute armStructMass : Real = airframe.armCount
            * TubeMass(radius = armTubeRadius, wall = armWall,
                       length = armLength, density = material.density);
        attribute sparWall : Real = max(minWallM,
            TubeWallForStress(
                momentNm = SparRootMoment(grossKg = airframe.designGrossKg,
                                          span = airframe.wingSpan),
                radius = airframe.sparRadius,
                yieldPa = material.yieldPa));
        attribute sparStructMass : Real =
            TubeMass(radius = airframe.sparRadius, wall = sparWall,
                     length = airframe.wingSpan,
                     density = material.density);
        attribute structureMass : Real = armStructMass + sparStructMass;
        attribute structureCost : Real =
            structureMass * material.costPerKg;

        attribute baseMass : Real = airframe.mass + avionicsMass
            + battery.mass + structureMass
            + airframe.motorCount * (motors.mass + props.mass);
        attribute baseCost : Real = airframe.cost + avionicsCost
            + battery.cost + structureCost
            + airframe.motorCount * (motors.cost + props.cost);
        attribute diskArea : Real = airframe.diskAreaFactor
            * 3.141592653589793 * props.diameter * props.diameter / 4.0;
        attribute maxThrust : Real = airframe.motorCount * motors.maxThrust;
        attribute usableEnergyJ : Real = battery.energyWh * 3600.0 * 0.8;

        // selection compatibility
        assert constraint propFit {
            props.diameter <= motors.maxPropDiameter }
        assert constraint packPower {
            battery.maxPowerW >= airframe.motorCount * motors.maxPowerW }
    }

    // ----- mission 1: ISR ---------------------------------------------------------

    part def IsrUav :> MissionUAV {
        doc /* Loiter on station as long as possible carrying a stabilized
               sensor.  Wing-borne families loiter at loiterSpeed on
               cruise power; the rotor-only quad station-keeps on hover
               power.  A fixed hover budget (takeoff + landing) comes off
               the battery first. */

        part sensor : SensorChoice;

        attribute minStationMinutes : Real = 25.0;  // the tasking floor
        attribute missionMass : Real = baseMass + sensor.mass;
        attribute missionCost : Real = baseCost + sensor.cost;
        attribute hoverPowerW : Real =
            HoverPower(massKg = missionMass, diskArea = diskArea);
        attribute loiterPowerW : Real = if airframe.wingSpan > 0.0
            ? CruisePower(massKg = missionMass,
                          speed = airframe.loiterSpeed,
                          dragArea = airframe.dragArea,
                          span = airframe.wingSpan,
                          wingArea = airframe.wingArea,
                          spanEff = airframe.oswald * airframe.tipPropBonus,
                          propEff = props.cruiseEff * motors.efficiency)
            else hoverPowerW;
        attribute stationMinutes : Real =
            (usableEnergyJ - hoverPowerW * airframe.hoverOpsSec)
            / (loiterPowerW + sensor.powerW) / 60.0;

        assert constraint sensorFits {
            sensor.mass <= airframe.payloadCapacity }
        assert constraint sensorGrade { sensor.grade >= 2 }
        assert constraint isrLift {
            maxThrust >= airframe.hoverThrustFactor * missionMass * 9.81 }
        assert constraint stationReq { stationMinutes >= minStationMinutes }
    }

    // ----- mission 2: logistics -----------------------------------------------------

    part def LogisticsUav :> MissionUAV {
        doc /* Fly a parcel OUT to a delivery point and return EMPTY: the
               outbound leg carries bay + parcel, the return leg only the
               bay, so the two legs cost different power.  The radius is
               what the battery sustains for out + back at cruise speed
               after the hover (takeoff, drop, landing) budget. */

        part cargo : CargoChoice;

        attribute minDeliveryRadiusKm : Real = 8.0;  // the tasking floor
        attribute minPayloadKg : Real = 1.0;         // smallest useful parcel
        attribute outboundMass : Real = baseMass + cargo.bayMass
            + cargo.payloadKg;
        attribute returnMass : Real = baseMass + cargo.bayMass;
        attribute missionCost : Real = baseCost + cargo.bayCost;
        attribute outboundPowerW : Real = if airframe.wingSpan > 0.0
            ? CruisePower(massKg = outboundMass,
                          speed = airframe.cruiseSpeed,
                          dragArea = airframe.dragArea,
                          span = airframe.wingSpan,
                          wingArea = airframe.wingArea,
                          spanEff = airframe.oswald * airframe.tipPropBonus,
                          propEff = props.cruiseEff * motors.efficiency)
            else RotorCruisePower(massKg = outboundMass,
                                  speed = airframe.cruiseSpeed,
                                  diskArea = diskArea,
                                  dragArea = airframe.dragArea,
                                  propEff = props.cruiseEff
                                      * motors.efficiency);
        attribute returnPowerW : Real = if airframe.wingSpan > 0.0
            ? CruisePower(massKg = returnMass,
                          speed = airframe.cruiseSpeed,
                          dragArea = airframe.dragArea,
                          span = airframe.wingSpan,
                          wingArea = airframe.wingArea,
                          spanEff = airframe.oswald * airframe.tipPropBonus,
                          propEff = props.cruiseEff * motors.efficiency)
            else RotorCruisePower(massKg = returnMass,
                                  speed = airframe.cruiseSpeed,
                                  diskArea = diskArea,
                                  dragArea = airframe.dragArea,
                                  propEff = props.cruiseEff
                                      * motors.efficiency);
        attribute hoverEnergyJ : Real =
            HoverPower(massKg = outboundMass, diskArea = diskArea)
            * airframe.hoverOpsSec;
        attribute deliveryRadiusKm : Real = (usableEnergyJ - hoverEnergyJ)
            / ((outboundPowerW + returnPowerW) / airframe.cruiseSpeed)
            / 1000.0;
        attribute payloadRangeKgKm : Real =
            cargo.payloadKg * deliveryRadiusKm;

        assert constraint cargoFits {
            cargo.bayMass + cargo.payloadKg <= airframe.payloadCapacity }
        assert constraint logLift {
            maxThrust >= airframe.hoverThrustFactor * outboundMass * 9.81 }
        assert constraint payloadReq { cargo.payloadKg >= minPayloadKg }
        assert constraint radiusReq { deliveryRadiusKm >= minDeliveryRadiusKm }
    }

    // ----- mission 3: high-speed intercept ---------------------------------------------

    part def InterceptUav :> MissionUAV {
        doc /* One-way dash against a target crossing the line of sight at
               targetSpeed, first seen at targetDistance.  Lead-collision
               triangle: intercept time D0 / sqrt(Vd^2 - Vt^2), feasible
               while the dash speed exceeds the target's AND the battery
               sustains full power that long.  maxTargetSpeed inverts the
               triangle at the battery-limited dash duration.  No return
               leg is required. */

        attribute seekerMass : Real = 0.12;
        attribute seekerCost : Real = 260.0;
        attribute targetSpeed : Real = 25.0;      // m/s
        attribute targetDistance : Real = 3000.0; // m at first detection

        attribute missionMass : Real = baseMass + seekerMass;
        attribute missionCost : Real = baseCost + seekerCost;
        attribute dashDrawW : Real = airframe.motorCount * motors.maxPowerW;
        attribute dashSpeed : Real =
            DashSpeed(powerW = dashDrawW * motors.efficiency
                          * props.cruiseEff,
                      dragArea = airframe.dragArea);
        attribute dashSeconds : Real = usableEnergyJ / dashDrawW;
        attribute maxTargetSpeed : Real = sqrt(max(0.0,
            dashSpeed * dashSpeed
            - (targetDistance / dashSeconds)
              * (targetDistance / dashSeconds)));
        attribute interceptSeconds : Real = targetDistance
            / sqrt(max(0.01,
                       dashSpeed * dashSpeed - targetSpeed * targetSpeed));

        assert constraint launchLift {
            maxThrust >= airframe.hoverThrustFactor * missionMass * 9.81 }
        assert constraint canCatch { maxTargetSpeed >= targetSpeed }
    }

    // ----- continuous sizing context (OpenMDAO / Z3) ------------------------------------

    part def IsrPrime {
        doc /* The ISR trade winner frozen as a concrete sizing context:
               the component mix is baked in (vtolWing + stdMotor +
               slimProp + packMax + stareEoIr + carbonFiber), the loiter
               speed stays continuous -- and the chain from configuration
               to time-on-station is spelled out discipline by discipline
               with the shared calc defs, so the generated OpenMDAO
               problem tells the classic MDO story: Aerodynamics builds
               the drag, Structures sizes the spar and its mass,
               Propulsion turns mass and drag into power and usable
               energy, Performance turns power into minutes on station. */

        attribute loiterSpeed : Real = 15.0;    // m/s -- the design variable

        // frozen winner configuration (catalog values of the mix above)
        attribute emptyMassKg : Real = 5.396;   // shell+avionics+pack+motors/props+sensor
        attribute fuselageLength : Real = 0.95;
        attribute fuselageDiameter : Real = 0.12;
        attribute span : Real = 2.6;
        attribute wingArea : Real = 0.624;
        attribute secondaryWingArea : Real = 0.387;
        attribute spanEff : Real = 1.0496;      // 0.82 Oswald x 1.28 tip props
        attribute propEff : Real = 0.697;       // slim prop x std motor
        attribute sensorPowerW : Real = 22.0;
        attribute batteryWh : Real = 360.0;     // packMax
        attribute hoverOpsSec : Real = 120.0;   // takeoff + landing budget
        attribute diskArea : Real =             // 3.3 disks x slim prop
            3.3 * 3.141592653589793 * 0.24 * 0.24 / 4.0;
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

    // ----- mission requirements (the dashboard's threshold anchors) ---------

    package MissionRequirements {
        doc /* One requirement def per mission tasking, formalizing the
               floors the mission contexts assert: the numeric thresholds
               live as ATTRIBUTES of the subjects (minStationMinutes,
               minPayloadKg, minDeliveryRadiusKm, targetSpeed), so a
               dashboard can read its slider defaults straight from the
               model and re-evaluate feasibility as they move. */

        requirement def IsrTasking {
            doc /* Hold station with a stabilized grade-2+ sensor at
                   least minStationMinutes. */
            subject uav : IsrUav;
            assume constraint { uav.airframe.hoverThrustFactor > 0.0 }
            require constraint stationFloor {
                uav.stationMinutes >= uav.minStationMinutes }
        }

        requirement def LogisticsTasking {
            doc /* Deliver at least minPayloadKg out to at least
                   minDeliveryRadiusKm and return empty. */
            subject uav : LogisticsUav;
            assume constraint { uav.cargo.payloadKg > 0.0 }
            require constraint payloadFloor {
                uav.cargo.payloadKg >= uav.minPayloadKg }
            require constraint radiusFloor {
                uav.deliveryRadiusKm >= uav.minDeliveryRadiusKm }
        }

        requirement def InterceptTasking {
            doc /* Catch a target crossing at targetSpeed, first seen at
                   targetDistance. */
            subject uav : InterceptUav;
            assume constraint { uav.dashSpeed > uav.targetSpeed }
            require constraint catchFloor {
                uav.maxTargetSpeed >= uav.targetSpeed }
        }
    }
}
