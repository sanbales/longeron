// DeepScout program -- multirotor.sysml: the MultiRotor branch.
//
// Two views of the same architecture family live here:
//
//   * the BUILD FAMILY -- five concrete configurations of the abstract
//     MultiRotor (aircraft.sysml), every one an F450Kit build at bench
//     fidelity: the stock QuadCopter, the TriCopter, the HexaCopter,
//     the CoaxX8, and the flat-8 OctoCopter.  The configurations differ
//     by the redefined rotor populations and sizing knobs; the physics
//     chain, equipment, and constraints are shared.  No configuration
//     wins everything: the family trades cost, mass, endurance,
//     footprint, motor-out tolerance, and the payload it carries
//     through a failure.
//   * the FLEET AIRFRAMES -- the rotor-borne airframe-shell entries the
//     mission studies trade (missions.sysml), from the mass-market box
//     quad to an S1000-class heavy hexa.  These cross with BOTH part
//     classes of the catalog; the assembly constraints keep dishonest
//     mixes infeasible instead of absent.
package Rotorcraft {
    doc /* The multirotor branch of the DeepScout program: the F450Kit
           build family (five configurations of the abstract MultiRotor)
           and the rotor-borne fleet airframes the missions trade.  Every
           component spec is a NOMINAL manufacturer figure; the fleet
           airframes are fictional shells over real parts -- normal drone
           practice.  Teaching examples, not engineering data. */

    private import ScoutParts::F450Kit::*;
    private import DeepScout::*;
    private import DeepScout::Aerodynamics::*;
    private import DeepScout::Packaging::*;
    private import DeepScout::Propulsion::*;
    private import DeepScout::Performance::*;

    // ----- the build family: five configurations -------------------------

    part def QuadCopter :> MultiRotor {
        doc /* The stock four-rotor configuration: a DJI F450 frame with
               one EMAX MT2213 and one APC 10x4.5MR per corner.  Meets
               every requirement at stock EXCEPT motor-out tolerance --
               after one failure the mixer must also shut the opposite
               motor to keep torque balance, and the remaining pair
               cannot lift the craft -- so the family's redundancy story
               starts here.  The reference airframe of the tutorials. */
        attribute rotorCount : Real :>> rotorCount = 4.0;
        // one failure shuts the opposite motor too: two rotors remain
        attribute failsafeRotorCount : Real :>> failsafeRotorCount = 2.0;
        // motor/prop per-unit masses restated as catalog literals (0.055
        // and 0.015 kg) so the roll-up stays a flat arithmetic chain
        attribute totalMass : Real :>> totalMass =
            chassis.mass + bayMass + 4.0 * 0.055 + 4.0 * 0.015 + payloadMass;
        // the ledger price, same flat-chain convention (17 USD motors,
        // 4 USD props)
        attribute totalCost : Real :>> totalCost =
            chassis.cost + bayCost + 4.0 * (17.0 + 4.0);
        // per-rotor static thrust from the calibrated motor + propeller
        // fit (all four stations are the same variant, so ->head() reads
        // the per-unit value off the homogeneous [4] populations)
        attribute thrustPerRotor : Real :>> thrustPerRotor = PropThrust(
            kV = motors.kV->head(),
            voltage = battery.voltage,
            diameter = propellers.diameter->head()
        );
        attribute motorMaxCurrent : Real :>> motorMaxCurrent =
            motors.maxCurrent->head();
        // parasite drag area CdA, built up bluff-body style (the
        // BluffFrameDrag idiom of DeepScout::Aerodynamics): ~0.024 m^2
        // of frontal area (body + battery stack + four arms + motor cans
        // + props in edgewise flow) times Cd ~1.1 for an open frame
        attribute frontalArea : Real :>> frontalArea = 0.024;   // m^2
        attribute maxCruiseSpeed : Real :>> maxCruiseSpeed = MaxCruiseSpeed(
            tiltDeg = cruiseTilt, massKg = totalMass, dragArea = dragArea
        );                                                   // 20.0 m/s

        part motors : Motor[4];
        part propellers : Propeller[4] :>> propellers;

        // one phase-lead bundle per corner: the [4] population fans out
        connection phaseLeads connect esc to motors;
    }

    part def TriCopter :> MultiRotor {
        doc /* The three-rotor configuration: two front arms plus a rear
               boom whose motor tilts on a yaw servo.  One motor, one
               propeller, and one arm lighter than the quad -- but yaw
               authority now comes from vectoring the tail rotor, and the
               12 g ES08MA II runs out of torque against the drag load
               beyond ~11 deg of commanded pitch, so the FC caps commanded
               attitude there.  The classic tricopter tradeoff, visible in
               the numbers: it hovers with margin (canHover holds,
               thrust/weight ~1.9) yet cruises so slowly that the demo
               sortie busts the 6-minute mission budget the quad meets
               with room to spare. */
        attribute rotorCount : Real :>> rotorCount = 3.0;
        // no torque-balanced hovering subset survives any single failure:
        // the tail out leaves an unmanageable pitch moment, a front out
        // leaves nothing the tilt servo can balance
        attribute failsafeRotorCount : Real :>> failsafeRotorCount = 0.0;
        // same catalog motors and props as the quad, one fewer of each,
        // plus the tail servo; the lighter TriFrame carries the boom
        attribute totalMass : Real :>> totalMass =
            chassis.mass + bayMass + 3.0 * 0.055 + 3.0 * 0.015
            + yawServo.mass + payloadMass;
        attribute totalCost : Real :>> totalCost =
            chassis.cost + bayCost + 3.0 * (17.0 + 4.0) + yawServo.cost;
        attribute thrustPerRotor : Real :>> thrustPerRotor = PropThrust(
            kV = frontMotors.kV->head(),
            voltage = battery.voltage,
            diameter = propellers.diameter->head()
        );
        attribute motorMaxCurrent : Real :>> motorMaxCurrent =
            frontMotors.maxCurrent->head();
        // three arms instead of four, but the long boom, the exposed tilt
        // mechanism, and the skids give the whole saving back
        attribute frontalArea : Real :>> frontalArea = 0.024;   // m^2
        // the yaw-authority cap (see the doc comment above)
        attribute maxOperationalTilt : Real :>> maxOperationalTilt = 11.0 [SI::'°'];
        attribute maxCruiseSpeed : Real :>> maxCruiseSpeed = MaxCruiseSpeed(
            tiltDeg = cruiseTilt, massKg = totalMass, dragArea = dragArea
        );                                                   // 12.4 m/s

        part chassis : TriFrame :>> chassis;
        part frontMotors : Motor[2];
        part tailMotor : Motor;
        part propellers : Propeller[3] :>> propellers;
        part yawServo : YawServo;

        connection frontLeads connect esc to frontMotors;
        connection tailLead connect esc to tailMotor;
        // the yaw mechanism: the servo vectors the tail rotor
        connection tiltLinkage connect yawServo to tailMotor;
    }

    part def HexaCopter :> MultiRotor {
        doc /* The six-rotor configuration: a DJI Flame Wheel F550 frame
               with the same EMAX MT2213 + APC 10x4.5MR stack on each of
               six arms, 60 degrees apart.  The classic redundancy buy:
               after any single motor failure the mixer shuts the failed
               motor's opposite and flies on the balanced four, so
               FailSafeHover holds with margin (motor-out usable thrust
               ~19.6 N against ~17.3 N of weight).  The price is real --
               wider and heavier than the quad, a thirstier hover, and a
               bigger ledger price -- though the flat octo below now
               takes the endurance and price crowns of shame.  The
               F550's 2.4 kg book takeoff ceiling replaces the F450
               default. */
        attribute rotorCount : Real :>> rotorCount = 6.0;
        // one failure shuts the opposite motor too: four rotors remain
        attribute failsafeRotorCount : Real :>> failsafeRotorCount = 4.0;
        attribute maxTakeoffMass : Real :>> maxTakeoffMass = 2.4 [SI::kg];
        // six motor/prop stations plus the second 4-in-1 ESC board
        // (0.012 kg, 40 USD) the extra channels need
        attribute totalMass : Real :>> totalMass =
            chassis.mass + bayMass + 6.0 * 0.055 + 6.0 * 0.015
            + 0.012 + payloadMass;
        attribute totalCost : Real :>> totalCost =
            chassis.cost + bayCost + 6.0 * (17.0 + 4.0) + 40.0;
        attribute thrustPerRotor : Real :>> thrustPerRotor = PropThrust(
            kV = motors.kV->head(),
            voltage = battery.voltage,
            diameter = propellers.diameter->head()
        );
        attribute motorMaxCurrent : Real :>> motorMaxCurrent =
            motors.maxCurrent->head();
        // the wider F550 plates, two extra arms, and two extra motor
        // cans grow the bluff frontal area past the quad's 0.024 m^2
        attribute frontalArea : Real :>> frontalArea = 0.030;   // m^2
        attribute maxCruiseSpeed : Real :>> maxCruiseSpeed = MaxCruiseSpeed(
            tiltDeg = cruiseTilt, massKg = totalMass, dragArea = dragArea
        );                                                   // 19.9 m/s

        part chassis : HexFrame :>> chassis;
        part motors : Motor[6];
        part propellers : Propeller[6] :>> propellers;

        // one phase-lead bundle per arm: the [6] population fans out
        connection phaseLeads connect esc to motors;
    }

    part def OctoCopter :> MultiRotor {
        doc /* The flat eight-rotor configuration: the custom OctoRing
               plate pair with the same EMAX MT2213 + APC 10x4.5MR stack
               on each of eight arms, 45 degrees apart.  A CUSTOM-BUILD
               convention, disclaimed on the frame def: real flat
               octocopters are heavy-lift machines, and this small-class
               ring exists so architecture is the ONLY variable against
               the hexa and the coax X8.  The redundancy buy is the
               family's richest: after any single failure the mixer
               shuts the opposite and flies on the balanced SIX, so
               FailSafeHover holds with the whole payload envelope
               intact (motor-out usable thrust ~29.5 N against ~20.0 N
               of weight, failsafePayload past maxPayload).  The price
               is every efficiency axis at once: the heaviest and widest
               airframe of the family, the worst hover endurance, and
               the biggest ledger price -- eight motors lifting a ring
               that six or four lift nearly as well.  The 2.6 kg takeoff
               ceiling is the builder's structural allowance for the
               wider plate span, not a book rating. */
        attribute rotorCount : Real :>> rotorCount = 8.0;
        // one failure shuts the opposite motor too: six rotors remain
        attribute failsafeRotorCount : Real :>> failsafeRotorCount = 6.0;
        attribute maxTakeoffMass : Real :>> maxTakeoffMass = 2.6 [SI::kg];
        // eight motor/prop stations plus the second 4-in-1 ESC board
        // (0.012 kg, 40 USD) the extra channels need
        attribute totalMass : Real :>> totalMass =
            chassis.mass + bayMass + 8.0 * 0.055 + 8.0 * 0.015
            + 0.012 + payloadMass;
        attribute totalCost : Real :>> totalCost =
            chassis.cost + bayCost + 8.0 * (17.0 + 4.0) + 40.0;
        attribute thrustPerRotor : Real :>> thrustPerRotor = PropThrust(
            kV = motors.kV->head(),
            voltage = battery.voltage,
            diameter = propellers.diameter->head()
        );
        attribute motorMaxCurrent : Real :>> motorMaxCurrent =
            motors.maxCurrent->head();
        // the widest ring of the family: eight arms, eight motor cans,
        // and the spanning plate pair in the wind
        attribute frontalArea : Real :>> frontalArea = 0.034;   // m^2
        attribute maxCruiseSpeed : Real :>> maxCruiseSpeed = MaxCruiseSpeed(
            tiltDeg = cruiseTilt, massKg = totalMass, dragArea = dragArea
        );                                                   // 20.2 m/s

        part chassis : OctoRing :>> chassis;
        part motors : Motor[8];
        part propellers : Propeller[8] :>> propellers;

        // one phase-lead bundle per arm: the [8] population fans out
        connection phaseLeads connect esc to motors;
    }

    part def CoaxX8 :> MultiRotor {
        doc /* The counter-rotating coaxial X8: the F450-size frame with
               TWO MT2213 stations per arm -- an upper motor on top of
               each arm and a lower motor hung beneath it on standoffs,
               each pair spinning opposite ways.  Eight rotors in the
               quad's footprint buy near-octo lift and one-failure
               tolerance (the pair's survivor keeps the station), but the
               lower rotor works in the upper's wake: coaxEfficiency
               carries the nominal wind-tunnel rule of thumb that it
               delivers only ~85% of its isolated thrust, and every
               thrust roll-up above scales by the lift-equivalent
               effectiveRotorCount instead of the motor count.  The
               penalty is visible in the numbers -- the family's worst
               hover efficiency per rotor and a bigger hover draw than
               the quad it outlifts.  The 2.0 kg takeoff ceiling is the
               builder's structural allowance for the doubled arm load,
               not a DJI rating. */
        attribute rotorCount : Real :>> rotorCount = 8.0;
        // the coax penalty, as a catalog figure: thrust delivered by a
        // lower rotor in the upper's wake over its isolated thrust
        // (nominal wind-tunnel rule of thumb for matched coax pairs)
        attribute coaxEfficiency : Real = 0.85;
        // four full-thrust uppers plus four wake-running lowers
        attribute effectiveRotorCount : Real :>> effectiveRotorCount =
            4.0 * (1.0 + coaxEfficiency);
        // worst single failure kills a pair member; the survivor keeps
        // the station: three full pairs plus one wake-running lower
        attribute failsafeRotorCount : Real :>> failsafeRotorCount =
            3.0 * (1.0 + coaxEfficiency) + coaxEfficiency;
        attribute maxTakeoffMass : Real :>> maxTakeoffMass = 2.0 [SI::kg];
        // eight motor/prop stations plus the second 4-in-1 ESC board
        attribute totalMass : Real :>> totalMass =
            chassis.mass + bayMass + 8.0 * 0.055 + 8.0 * 0.015
            + 0.012 + payloadMass;
        attribute totalCost : Real :>> totalCost =
            chassis.cost + bayCost + 8.0 * (17.0 + 4.0) + 40.0;
        attribute thrustPerRotor : Real :>> thrustPerRotor = PropThrust(
            kV = upperMotors.kV->head(),
            voltage = battery.voltage,
            diameter = propellers.diameter->head()
        );
        attribute motorMaxCurrent : Real :>> motorMaxCurrent =
            upperMotors.maxCurrent->head();
        // the quad's footprint plus the hung lower cans and standoffs
        attribute frontalArea : Real :>> frontalArea = 0.026;   // m^2
        attribute maxCruiseSpeed : Real :>> maxCruiseSpeed = MaxCruiseSpeed(
            tiltDeg = cruiseTilt, massKg = totalMass, dragArea = dragArea
        );                                                   // 21.0 m/s

        part upperMotors : Motor[4];
        part lowerMotors : Motor[4];
        part propellers : Propeller[8] :>> propellers;

        // one phase-lead bundle per pair member: upper and lower fan out
        connection upperLeads connect esc to upperMotors;
        connection lowerLeads connect esc to lowerMotors;
    }

    // ----- architecture wiring: who satisfies what -----------------------
    // The quad meets every requirement at stock EXCEPT motor-out
    // tolerance: tutorial 7 measures the installation numbers on its CAD
    // build and the mission legs at its 20.0 m/s cruise, but a single
    // failure leaves it two balanced rotors that cannot lift it.  The
    // tricopter holds the flight envelope with margin (thrust/weight
    // ~1.9), but its 11-deg yaw-authority tilt cap drops cruise to
    // 12.4 m/s and the demo sortie takes ~6.2 min -- past the 6-minute
    // budget -- so it earns NO mission satisfy edge, and no failure
    // leaves it any balanced rotor set at all.  The hexa, the flat octo,
    // and the coax X8 buy the FailSafeHover edge the flat quad and the
    // tri cannot have -- the hexa on the balanced four, the octo on the
    // balanced six (with the whole payload envelope surviving), the X8
    // through the pair's wake-running survivor.  The missing edges are
    // the point: no configuration collects them all.
    satisfy FlightEnvelope by QuadCopter;
    satisfy FlightEnvelope by TriCopter;
    satisfy FlightEnvelope by HexaCopter;
    satisfy FlightEnvelope by OctoCopter;
    satisfy FlightEnvelope by CoaxX8;
    satisfy mission by QuadCopter;
    satisfy mission by HexaCopter;
    satisfy mission by OctoCopter;
    satisfy mission by CoaxX8;
    satisfy installation by QuadCopter;
    satisfy FailSafeHover by HexaCopter;
    satisfy FailSafeHover by OctoCopter;
    satisfy FailSafeHover by CoaxX8;

    // ----- the fleet's rotor-borne airframes -------------------------------
    // Airframe-shell entries in the mission catalog's convention: every
    // dragArea is a bluff-body BUILDUP from the family's own geometry
    // (BluffFrameDrag), `mass` excludes the rotor arms the assembly
    // sizes from loads.  These entries CROSS with both part classes:
    // the assembly's propFit / packPower / cellMatch constraints and the
    // missions' lift and endurance floors decide which mixes fly.

    part def BoxQuad :> Airframe {
        // open 450-class frame: no skin to speak of -- the whole CdA is
        // bluff (tilted plates, battery brick, motor cans in the wind).
        // The payload box slung under the hub owns its share of the
        // bluff frontal area explicitly (the plates and the pack shadow
        // the rest of its face at cruise tilt); the buildup total is
        // the same open-frame figure as ever.
        attribute frameFrontalArea : Real = 0.036;  // m^2, plates/pack/cans
        attribute bayFrontalArea : Real = 0.014;    // m^2, the box's exposed share
        attribute dragArea : Real =
            BluffFrameDrag(frontalArea = frameFrontalArea + bayFrontalArea);
        attribute mass : Real = 0.78;   attribute cost : Real = 120.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 14.0;
        attribute motorCount : Integer = 4;
        attribute diskAreaFactor : Real = 4.0;
        attribute hoverThrustFactor : Real = 1.6;
        attribute climbDrawFraction : Real = 0.7;
        attribute payloadCapacity : Real = 6.0;
        attribute hoverOpsSec : Real = 90.0;
        attribute fuselageLength : Real = 0.0;
        attribute armCount : Integer = 4;
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size

        // the payload bay: an open box slung under the hub plates --
        // cheap volume, but its face pays bluff drag above and the
        // battery rides the hub stack, not the box
        attribute bayShape : String = "box";
        attribute bayLength : Real = 0.26;
        attribute bayWidth : Real = 0.20;
        attribute bayHeight : Real = 0.14;
        attribute grossVolume : Real = BoxVolume(length = bayLength,
            width = bayWidth, height = bayHeight);          // 7.3 L
        attribute usableVolumeFraction : Real = 0.75;   // straps + rails
        attribute equipmentBayFactor : Real = 0.0;      // pack on the hub stack

        // the clickable internals: the equipment every variant carries
        part battery : ScoutParts::Battery;
        part flightController : FlightController;
        part camera : Camera;
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
        attribute mass : Real = 0.98;   attribute cost : Real = 320.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 18.0;
        attribute motorCount : Integer = 4;
        attribute diskAreaFactor : Real = 4.0;
        attribute hoverThrustFactor : Real = 1.5;
        attribute climbDrawFraction : Real = 0.7;
        attribute payloadCapacity : Real = 1.0;
        attribute hoverOpsSec : Real = 60.0;
        attribute armCount : Integer = 4;
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size

        // the payload bay rides INSIDE the lathed hull -- the drag
        // ledger already prices the shell's skin, so the bay adds no
        // drag of its own, but the hull's displacement is ALL there is:
        // pack, avionics, and payload share it, and the frames, arm
        // carry-throughs, and taper ends impede the fluid volume hard
        attribute bayShape : String = "hull";
        attribute bayLength : Real = fuselageLength;
        attribute bayWidth : Real = fuselageDiameter;
        attribute bayHeight : Real = fuselageDiameter;
        attribute grossVolume : Real = RevolvedVolume(
            length = fuselageLength, diameter = fuselageDiameter);  // 4.5 L
        attribute usableVolumeFraction : Real = 0.60;
        attribute equipmentBayFactor : Real = 1.0;      // everything shares the hull

        // the clickable internals: the equipment every variant carries
        part battery : ScoutParts::Battery;
        part flightController : FlightController;
        part camera : Camera;
    }

    part def OpenTri :> Airframe {
        // The tricopter conversion as a fleet shell: two arms, a tail
        // boom, and a tilt mechanism.  One motor station fewer than the
        // box quad, but low-volume conversion plates and the CNC tilt
        // hardware cost real money -- the mass-market box quad undercuts
        // it.  The tail servo's yaw authority caps transit speed (the
        // build family's TriCopter tells the same story at bench
        // fidelity), and the tilted tail rotor wastes lift: the
        // diskAreaFactor carries the vectoring loss as a nominal
        // 0.2-disc haircut.  The narrow plate pair takes a narrow box:
        // its exposed face owns its share of the bluff buildup below.
        attribute frameFrontalArea : Real = 0.032;  // m^2, plates/boom/tilt gear
        attribute bayFrontalArea : Real = 0.010;    // m^2, the box's exposed share
        attribute dragArea : Real =
            BluffFrameDrag(frontalArea = frameFrontalArea + bayFrontalArea);
        attribute mass : Real = 0.62;   attribute cost : Real = 260.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 11.0;      // the yaw-authority cap
        attribute motorCount : Integer = 3;
        attribute diskAreaFactor : Real = 2.8;    // 3 discs less the tail-tilt loss
        attribute hoverThrustFactor : Real = 1.7; // tail-vector control reserve
        attribute climbDrawFraction : Real = 0.7;
        attribute payloadCapacity : Real = 1.2;
        attribute hoverOpsSec : Real = 60.0;
        attribute fuselageLength : Real = 0.0;
        attribute armCount : Integer = 3;
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size

        attribute bayShape : String = "box";
        attribute bayLength : Real = 0.20;
        attribute bayWidth : Real = 0.16;
        attribute bayHeight : Real = 0.13;
        attribute grossVolume : Real = BoxVolume(length = bayLength,
            width = bayWidth, height = bayHeight);          // 4.2 L
        attribute usableVolumeFraction : Real = 0.75;
        attribute equipmentBayFactor : Real = 0.0;      // pack on the hub stack

        part battery : ScoutParts::Battery;
        part flightController : FlightController;
        part camera : Camera;
    }

    part def HexLifter :> Airframe {
        // An S1000-class spreading-arms hexa: the heavy-lift camera
        // platform, and the crossing's headline row.  Six long arms want
        // big slow props and 6S packs -- the small class cannot lift the
        // shell (isrLift and logLift refuse those mixes), and the 2 kW
        // AT4120s want more watts than any pack feeds (packPower).  A
        // camera platform climbs gently, so the sustained climb-out
        // fraction is lower than the sport frames': that is what lets
        // the li-ion endurance pack feed six Antigravity motors.  The
        // gimbal bay under the hub is the widest box of the rotor
        // fleet -- the survey kit needs it -- and its exposed face owns
        // its share of the bluff buildup.
        attribute frameFrontalArea : Real = 0.108;  // m^2: plates, six arms, gear
        attribute bayFrontalArea : Real = 0.022;    // m^2, the box's exposed share
        attribute dragArea : Real =
            BluffFrameDrag(frontalArea = frameFrontalArea + bayFrontalArea);
        attribute mass : Real = 3.1;    attribute cost : Real = 1450.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 15.0;
        attribute motorCount : Integer = 6;
        attribute diskAreaFactor : Real = 6.0;
        attribute hoverThrustFactor : Real = 1.5;
        attribute climbDrawFraction : Real = 0.5;  // camera platform: gentle climbs
        attribute payloadCapacity : Real = 9.0;
        attribute hoverOpsSec : Real = 120.0;
        attribute fuselageLength : Real = 0.0;
        attribute armCount : Integer = 6;
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size

        attribute bayShape : String = "box";
        attribute bayLength : Real = 0.30;
        attribute bayWidth : Real = 0.24;
        attribute bayHeight : Real = 0.18;
        attribute grossVolume : Real = BoxVolume(length = bayLength,
            width = bayWidth, height = bayHeight);          // 13.0 L
        attribute usableVolumeFraction : Real = 0.75;
        attribute equipmentBayFactor : Real = 0.0;      // pack on the hub stack

        part battery : ScoutParts::Battery;
        part flightController : FlightController;
        part camera : Camera;
    }

    part def CoaxOcto :> Airframe {
        // The coax X8 as a fleet shell: eight stations on four booms, a
        // heavy-lift footprint no wider than the box quad.  The coax
        // wake penalty rides in the diskAreaFactor: each shared disc
        // counts ~1.26 isolated discs for hover power (the kappa ~ 1.26
        // interference rule of thumb), so eight rotors buy five discs'
        // worth of hover efficiency.  Dense power in a small frame --
        // the dash studies notice -- and the dense frame keeps the bay
        // honest: the box between the booms is quad-sized, no bigger.
        attribute frameFrontalArea : Real = 0.041;  // m^2: quad footprint + lower cans
        attribute bayFrontalArea : Real = 0.014;    // m^2, the box's exposed share
        attribute dragArea : Real =
            BluffFrameDrag(frontalArea = frameFrontalArea + bayFrontalArea);
        attribute mass : Real = 1.05;   attribute cost : Real = 380.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 16.0;
        attribute motorCount : Integer = 8;
        attribute diskAreaFactor : Real = 5.0;    // 4 shared discs x kappa penalty
        attribute hoverThrustFactor : Real = 1.6;
        attribute climbDrawFraction : Real = 0.7;
        attribute payloadCapacity : Real = 5.0;
        attribute hoverOpsSec : Real = 90.0;
        attribute fuselageLength : Real = 0.0;
        attribute armCount : Integer = 4;      // four booms, two stations each
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size

        attribute bayShape : String = "box";
        attribute bayLength : Real = 0.26;
        attribute bayWidth : Real = 0.20;
        attribute bayHeight : Real = 0.15;
        attribute grossVolume : Real = BoxVolume(length = bayLength,
            width = bayWidth, height = bayHeight);          // 7.8 L
        attribute usableVolumeFraction : Real = 0.75;
        attribute equipmentBayFactor : Real = 0.0;      // pack on the hub stack

        part battery : ScoutParts::Battery;
        part flightController : FlightController;
        part camera : Camera;
    }

    part def RingOcto :> Airframe {
        // The flat-8 ring as a fleet shell: eight arms, eight isolated
        // discs, no wake penalty -- the build family's OctoCopter scaled
        // to the fleet convention.  Motor-out tolerance is why anyone
        // builds one; the mission studies price what eight stations cost
        // in frame, drag, and invoice against what the hexa's six buy.
        // The wide ring hangs the second-widest box of the rotor fleet:
        // its exposed face owns its share of the bluff buildup.
        attribute frameFrontalArea : Real = 0.065;  // m^2: the wide ring in the wind
        attribute bayFrontalArea : Real = 0.020;    // m^2, the box's exposed share
        attribute dragArea : Real =
            BluffFrameDrag(frontalArea = frameFrontalArea + bayFrontalArea);
        attribute mass : Real = 1.5;    attribute cost : Real = 520.0;
        attribute wingSpan : Real = 0.0;  attribute wingChord : Real = 0.0;
        attribute taper : Real = 1.0;     attribute wingArea : Real = 0.0;
        attribute oswald : Real = 0.0;    attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 0.0;
        attribute cruiseSpeed : Real = 15.0;
        attribute motorCount : Integer = 8;
        attribute diskAreaFactor : Real = 8.0;
        attribute hoverThrustFactor : Real = 1.5;
        attribute climbDrawFraction : Real = 0.7;
        attribute payloadCapacity : Real = 6.0;
        attribute hoverOpsSec : Real = 90.0;
        attribute fuselageLength : Real = 0.0;
        attribute armCount : Integer = 8;
        attribute sparRadius : Real = 0.008;   // unused: no wing
        attribute designGrossKg : Real = 0.0;  // no spar to size

        attribute bayShape : String = "box";
        attribute bayLength : Real = 0.30;
        attribute bayWidth : Real = 0.24;
        attribute bayHeight : Real = 0.17;
        attribute grossVolume : Real = BoxVolume(length = bayLength,
            width = bayWidth, height = bayHeight);          // 12.2 L
        attribute usableVolumeFraction : Real = 0.75;
        attribute equipmentBayFactor : Real = 0.0;      // pack on the hub stack

        part battery : ScoutParts::Battery;
        part flightController : FlightController;
        part camera : Camera;
    }
}
