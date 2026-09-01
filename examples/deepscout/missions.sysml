// DeepScout program -- missions.sysml: the missions and the trade space.
//
// One component catalog is evaluated against THREE mission contexts,
// each a part definition specializing the shared MissionUAV assembly
// with its own equipment, metrics, and requirements:
//
//   IsrUav       -- loiter on station with a sensor package (max station time)
//   LogisticsUav -- carry a parcel out, return empty (max payload x radius)
//   InterceptUav -- one-way dash to catch a crossing target (max target speed)
//
// The catalog CROSSES architecture with part class: eleven airframes
// (six rotor-borne, two winged VTOL, three flying wings -- the twin
// courier crosses its root pusher stations against a wingtip variant)
// against four
// motors, four props, and five packs spanning the small F450 class and
// the heavy 6S class.
// Dishonest mixes stay in the space and fail honestly -- propFit keeps
// big props off small motors, packPower keeps 2 kW motors off starved
// packs, cellMatch keeps 3S motors off 6S packs, and the mission floors
// refuse the shells the small class cannot lift.
//
// All physics lives in the calc defs of DeepScout's discipline packages
// (momentum-theory hover, wetted-area drag buildup, drag-limited dash,
// load-based tube sizing), which the interpreter evaluates directly.
// These formulas (sqrt/pow, conditionals, calc invocations) are beyond
// the CP-SAT mapper's arithmetic in the MISSION layers; the platform
// assembly itself (MissionUAV) encodes, and the honest workflow for the
// missions is TradeStudy.all_architectures() / evaluate(): enumerate
// the Cartesian candidate space and let the interpreter score every mix
// exactly (see tutorial T4).
package ScoutMissions {
    doc /* The DeepScout trade space: eleven airframe entries across three
           branches, real COTS propulsion and payload options in two
           part classes, a battery-chemistry trade, a structural-material
           trade, and three mission contexts with executable physics.
           The airframes are fictional; the motors, propellers, packs,
           and payloads are real commercial parts -- normal drone
           practice.  Every component spec is a NOMINAL manufacturer
           figure; teaching examples, not engineering data. */

    private import ScoutParts::*;
    private import Rotorcraft::*;
    private import WingedVtol::*;
    private import FlyingWings::*;
    private import DeepScout::*;
    private import DeepScout::Aerodynamics::*;
    private import DeepScout::Propulsion::*;
    private import DeepScout::Structures::*;
    private import DeepScout::Performance::*;
    // the tailless branch's pod chain reads the trailing-edge closed
    // forms (TrailingEdgeAft) inside its dragArea buildup, so the
    // catalog's variant re-evaluation needs the S&C discipline in
    // scope like the other four
    private import DeepScout::StabilityControl::*;
    // ... and the bay declarations read the volume kernels
    private import DeepScout::Packaging::*;

    // ----- variation points ---------------------------------------------------

    package Catalog {
        doc /* The variation points under trade: one choice per shared
               subsystem plus the per-mission equipment.  These seven
               points ARE the columns of every parallel-coordinates view
               and the decision variables of every trade study below.
               The airframe point spans both branches; the motor, prop,
               and battery points span both part classes. */

        variation part def AirframeChoice :> Airframe {
            variant part boxQuad : BoxQuad;
            variant part teardropQuad : TeardropQuad;
            variant part openTri : OpenTri;
            variant part hexLifter : HexLifter;
            variant part coaxOcto : CoaxOcto;
            variant part ringOcto : RingOcto;
            variant part vtolWing : VtolWing;
            variant part dartInterceptor : DartInterceptor;
            variant part flyingWingSingle : FlyingWingSingle;
            variant part flyingWingTwin : FlyingWingTwin;
            variant part flyingWingTwinTip : FlyingWingTwinTip;
        }
        variation part def MotorChoice :> Motor {
            variant part mt2213 : EmaxMt2213;
            variant part mn4006 : TMotorMn4006;
            variant part x4112s : SunnySkyX4112s;
            variant part at4120 : TMotorAt4120;
        }
        variation part def PropChoice :> Propeller {
            variant part apc1045 : Apc10x45mr;
            variant part apc11x55 : Apc11x55e;
            variant part apc13x65 : Apc13x65e;
            variant part tm15x5 : TMotor15x5cf;
        }
        variation part def BatteryChoice :> Battery {
            variant part tattu3s : Tattu3s5200;
            variant part tattu5200 : Tattu6s5200;
            variant part tattu10000 : Tattu6s10000;
            variant part tattu16000 : Tattu6s16000;
            variant part liion6s6p : LiIon6s6p;
        }
        variation part def SensorChoice :> SensorPackage {
            variant part runcamSplit : RuncamSplit4;
            variant part zenmuseH20 : ZenmuseH20;
            variant part gremsyT3 : GremsyT3A7r;
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

    private import Catalog::*;

    // ----- the shared assembly under trade --------------------------------------

    part def MissionUAV :> Aircraft {
        doc /* Airframe + propulsion + battery + structural material,
               common to every mission.  Motor/prop stations are
               homogeneous ([4] selects one type for all); airframe.
               motorCount says how many stations the family populates
               (3 to 8 across the catalog), and the mass/cost/thrust
               build-ups scale by it.  Rotor arms and the wing spar are
               round tubes sized HERE from loads (per-rotor thrust
               bending the arm, the elliptic root moment bending the
               spar) in the selected material, so the material choice is
               a real mass-vs-cost trade axis.  Three compatibility
               constraints keep the crossed catalog honest: propFit,
               packPower, and the voltage-class cellMatch -- and a
               fourth, bayFit, keeps the VOLUME ledger honest: whatever
               a mission stows (its payload, plus the pack and avionics
               where the airframe's bay houses them) must fit the
               airframe's usable bay volume. */

        attribute avionicsMass : Real = 0.16;   // kg: Pixhawk-class FC, GPS, radios
        attribute avionicsCost : Real = 420.0;  // USD, street
        // the avionics' bay demand (nominal): the FC case, the GPS puck,
        // both radios, and their wiring service loops
        attribute avionicsVolume : Real = 0.0003;   // m^3
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
        // the arm-root bending check: one rotor's full thrust at the
        // arm length is the root moment the tube wall (and the root
        // gusset below) must carry
        attribute armRootMomentNm : Real = motors.maxThrust * armLength;
        attribute armWall : Real = max(minWallM, max(
            TubeWallForStress(momentNm = armRootMomentNm,
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
        // the arm-root gussets: hub structure grows OUT of the main
        // body to meet the arms -- a doubler sleeve over the root 15%
        // of each arm, one wall thickness proud of the sized tube,
        // carrying the root moment's shear into the centre plates.
        // Same thin-wall convention as the arm itself; the plates the
        // gussets land on ride in the airframe shell mass.
        attribute gussetLength : Real = 0.15 * armLength;
        attribute gussetMass : Real = airframe.armCount
            * TubeMass(radius = armTubeRadius + armWall, wall = armWall,
                       length = gussetLength, density = material.density);
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
        attribute structureMass : Real =
            armStructMass + gussetMass + sparStructMass;
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

        // ----- the volume ledger --------------------------------------
        // What the mission stows in the airframe's payload bay: the
        // mission's own payload demand (the bare platform stows nothing;
        // each mission redefines it), plus the pack and the avionics
        // where the bay houses the equipment (equipmentBayFactor 1 --
        // every skinned airframe; the open rotor frames stack their
        // equipment on the hub instead).
        attribute payloadVolume : Real = 0.0;   // m^3, redefined per mission
        attribute equipmentBayVolume : Real = airframe.equipmentBayFactor
            * (battery.volumeM3 + avionicsVolume);
        attribute bayDemandVolume : Real = payloadVolume + equipmentBayVolume;

        // selection compatibility
        assert constraint propFit {
            props.diameter <= motors.maxPropDiameter }
        // the pack must sustain the climb-out draw: the airframe's
        // sustained fraction of full power on every motor.  This is the
        // constraint the li-ion pack's 10 A cells feel: plenty of
        // watt-hours, a tenth of the LiPo discharge ceiling.
        assert constraint packPower {
            battery.maxPowerW >= airframe.climbDrawFraction
                * airframe.motorCount * motors.maxPowerW }
        // the voltage-class match of the crossing: a 3S motor on a 6S
        // pack burns, a 6S motor on a 3S pack starves -- the small and
        // heavy part classes may not mix inside one power train.
        assert constraint cellMatch {
            battery.cells == motors.cells }
        // the volume ledger must close: what the mission stows fits the
        // usable bay volume.  This is the FIT axis of the trade space --
        // a mix that carries the mass but cannot FIND THE ROOM busts
        // here instead of flying on paper.
        assert constraint bayFit {
            bayDemandVolume <= airframe.usableVolume }
    }

    // ----- mission 1: ISR ---------------------------------------------------------

    part def IsrUav :> MissionUAV {
        doc /* Loiter on station as long as possible carrying a stabilized
               sensor.  Wing-borne families loiter at loiterSpeed on
               cruise power; the rotor-borne families station-keep on
               hover power.  A fixed hover budget (takeoff + landing)
               comes off the battery first. */

        part sensor : SensorChoice;

        attribute minStationMinutes : Real = 25.0;  // the tasking floor
        attribute missionMass : Real = baseMass + sensor.mass;
        attribute missionCost : Real = baseCost + sensor.cost;
        attribute payloadVolume : Real :>> payloadVolume = sensor.volumeM3;
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
        attribute payloadVolume : Real :>> payloadVolume = cargo.stowedVolume;
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
               while the USABLE dash speed exceeds the target's AND the
               battery sustains full power that long.  What is usable is
               less than what the drag balance gives: a wing-borne dash
               is placarded by the alleviated gust load at the spar
               chain's design point (GustPlacardSpeed), and a rotor-borne
               dash never outruns the commanded-tilt cap (MaxCruiseSpeed
               at maxTiltDeg).  maxTargetSpeed inverts the triangle at
               the battery-limited dash duration.  No return leg is
               required.  DECLARED FIDELITY LIMIT: props.cruiseEff is a
               constant, so no advance-ratio ceiling exists -- the
               catalog's whole 40-73 m/s dash band is propeller-
               impossible on these fixed-pitch props (pitch speeds run
               13-25 m/s).  The limit is symmetric across every family:
               nominal teaching physics above ~25 m/s. */

        attribute seekerMass : Real = 0.12;
        attribute seekerCost : Real = 260.0;
        attribute seekerVolume : Real = 0.00025;  // m^3, nose seeker + processor
        attribute targetSpeed : Real = 25.0;      // m/s
        attribute targetDistance : Real = 3000.0; // m at first detection

        attribute missionMass : Real = baseMass + seekerMass;
        attribute missionCost : Real = baseCost + seekerCost;
        attribute payloadVolume : Real :>> payloadVolume = seekerVolume;
        attribute dashDrawW : Real = airframe.motorCount * motors.maxPowerW;
        attribute dashSpeed : Real =
            DashSpeed(powerW = dashDrawW * motors.efficiency
                          * props.cruiseEff,
                      dragArea = airframe.dragArea);
        attribute dashSeconds : Real = usableEnergyJ / dashDrawW;

        // ----- the dash envelope: what the airframe may USE ------------
        // The drag balance says what the watts buy; the envelope says
        // what the airframe survives using.  Wing-borne: the FAR
        // 23.341-style gust placard at the spar chain's design load
        // factor -- linear in wing loading, so the dense dart placards
        // high and the limber couriers placard low (the axis where a
        // real interceptor is stubby).  Rotor-borne: the bench family's
        // commanded-tilt idiom, MaxCruiseSpeed at the shell's maxTiltDeg.
        // Each cap reads dashSpeed where it does not apply, so min()
        // composes them without a special case.
        attribute dashAspectRatio : Real = if airframe.wingSpan > 0.0
            ? airframe.wingSpan * airframe.wingSpan / airframe.wingArea
            else 0.0;
        attribute dashWingLoading : Real = if airframe.wingSpan > 0.0
            ? missionMass * 9.81 / airframe.wingArea
            else 0.0;                       // N/m^2 at mission mass
        attribute dashLiftSlope : Real =    // 2 pi AR / (AR + 2), per rad
            2.0 * pi * dashAspectRatio / (dashAspectRatio + 2.0);
        attribute gustMassRatio : Real = if airframe.wingSpan > 0.0
            ? 2.0 * dashWingLoading
              / (1.225 * airframe.wingChord * dashLiftSlope * 9.81)
            else 0.0;                       // mu (Pratt)
        attribute gustAlleviation : Real =  // Kg (Pratt)
            0.88 * gustMassRatio / (5.3 + gustMassRatio);
        attribute dashPlacard : Real = if airframe.wingSpan > 0.0
            ? GustPlacardSpeed(wingLoading = dashWingLoading,
                               liftSlope = dashLiftSlope,
                               gustAlleviation = gustAlleviation)
            else dashSpeed;                 // no wing: no gust placard
        attribute tiltDashCap : Real = if airframe.wingSpan > 0.0
            ? dashSpeed                     // wing-borne: the placard governs
            else MaxCruiseSpeed(tiltDeg = airframe.maxTiltDeg,
                                massKg = missionMass,
                                dragArea = airframe.dragArea);
        attribute usableDashSpeed : Real =
            min(dashSpeed, min(dashPlacard, tiltDashCap));

        attribute maxTargetSpeed : Real = sqrt(max(0.0,
            usableDashSpeed * usableDashSpeed
            - (targetDistance / dashSeconds)
              * (targetDistance / dashSeconds)));
        attribute interceptSeconds : Real = targetDistance
            / sqrt(max(0.01,
                       usableDashSpeed * usableDashSpeed
                       - targetSpeed * targetSpeed));
        // DO NOT "fix" this mission with a turn-rate/corner-speed floor
        // or by scoring interceptSeconds: at a shared structural load
        // factor both reward LOW wing loading, so both PROMOTE the
        // courier wings (the intercept audit's key negative result).
        // The gust placard above is the one maneuver-adjacent axis that
        // demotes them for the honest reason.

        assert constraint launchLift {
            maxThrust >= airframe.hoverThrustFactor * missionMass * 9.81 }
        assert constraint canCatch { maxTargetSpeed >= targetSpeed }
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
                   targetDistance.  HONEST ABSENCE: readiness time (rail
                   rigging, spin-up, launch clearance) exists nowhere in
                   the model, for any family -- the tasking starts every
                   candidate already airborne at detection. */
            subject uav : InterceptUav;
            assume constraint { uav.dashSpeed > uav.targetSpeed }
            require constraint catchFloor {
                uav.maxTargetSpeed >= uav.targetSpeed }
        }

        requirement def PayloadBayFit {
            doc /* The stowage shall fit: the mission's payload demand,
                   plus the pack and the avionics where the airframe's
                   bay houses the equipment, shall not exceed the bay's
                   usable volume (the gross envelope times the packaging
                   factor -- internal structure impedes the fluid
                   volume).  The subject is the shared assembly, so one
                   requirement covers every mission context; no
                   configuration earns a satisfy edge, because the
                   verdict belongs to the MIX -- the same shell fits a
                   seeker and refuses a survey gimbal.  Every mission
                   asserts it (the bayFit constraint), so a mix that
                   does not fit busts its study honestly. */
            subject uav : MissionUAV;
            assume constraint { uav.airframe.usableVolume > 0.0 }
            require constraint volumeFit {
                uav.bayDemandVolume <= uav.airframe.usableVolume }
        }
    }

    // ----- tailless stability & control (the flying wings' airworthiness) ---

    package StabilityRequirements {
        doc /* What a flying wing must carry INSTEAD of a tail: one
               requirement per stability-and-control axis, checked
               against the subject's own derived S&C figures (the
               StabilityControl closed forms).  The numeric bands live
               HERE as requirement attributes -- the same slider-anchor
               idiom as MissionRequirements -- and every figure is a
               NOMINAL teaching value with its source named.  Subjects
               of the three tailless checks are the tailless shells
               only: the multirotors hover on their mixers, the dart
               and the tail-sitter fly on real tail surfaces, so none
               of them subjects a tailless check (honest absence).
               EngineOutYaw is the family's fourth axis and reaches
               wider: its subjects are the tip-station configurations
               of BOTH winged branches, because the dead-engine yaw arm
               is what the tip stations buy their bonus with.  Because
               each constraint reads a
               derived attribute of the subject, a higher-fidelity
               re-derivation of that attribute -- the loft framework's
               computed derivatives -- re-verifies the SAME
               requirements: same checks, rising fidelity. */

        requirement def PitchStability {
            doc /* The CG shall ride ahead of the neutral point by a
                   static margin inside the tailless band.  Below the
                   floor the wing is neutrally stable or unstable;
                   above the ceiling the washout-and-reflex trim must
                   carry a nose-down moment that spends the cruise
                   L/D.  0.05..0.15 MAC is a NOMINAL teaching band
                   (Nickel & Wohlfahrt, 'Tailless Aircraft in Theory
                   and Practice'; Raymer).  An UNSWEPT variant of
                   either shell busts the floor: with the quarter-chord
                   sweep zeroed, the neutral point stays at the root
                   quarter-chord, roughly half a MAC AHEAD of the
                   bay-loaded CG -- sweep is the trim mechanism, not
                   styling. */
            subject wing : FlyingWing;
            attribute marginFloor : Real = 0.05;
            attribute marginCeiling : Real = 0.15;
            assume constraint { wing.wingSpan > 0.0 }
            require constraint stableMargin {
                wing.staticMargin >= marginFloor and
                wing.staticMargin <= marginCeiling }
        }

        requirement def PitchRollAuthority {
            doc /* The elevons shall carry both axes they serve: the
                   pitch volume coefficient (S_e l_e / S MAC) and the
                   roll volume coefficient (S_e y_e / S b) each clear a
                   NOMINAL floor (Raymer's volume-coefficient sizing;
                   Nickel & Wohlfahrt on elevon practice).  Tailed
                   aircraft size tails near 0.5; an elevon band rides
                   the wing itself on a fraction of the arm, so its
                   honest scale is a tenth of that. */
            subject wing : FlyingWing;
            attribute pitchVolumeFloor : Real = 0.05;
            attribute rollVolumeFloor : Real = 0.02;
            assume constraint { wing.wingSpan > 0.0 }
            require constraint pitchAuthority {
                wing.elevonPitchVolume >= pitchVolumeFloor }
            require constraint rollAuthority {
                wing.elevonRollVolume >= rollVolumeFloor }
        }

        requirement def YawStability {
            doc /* The winglets shall provide the weathercock stability
                   the wing has no fin for: the winglet volume
                   coefficient (S_v l_v / S b, both winglets riding the
                   swept tips) clears a NOMINAL tailless floor.
                   Conventional tails fly near 0.02..0.04; winglet-
                   stabilized flying wings fly far lower (Nickel &
                   Wohlfahrt), so 0.008 is a tailless figure, not a
                   tailed one. */
            subject wing : FlyingWing;
            attribute yawVolumeFloor : Real = 0.008;
            assume constraint { wing.wingSpan > 0.0 }
            require constraint yawAuthority {
                wing.wingletYawVolume >= yawVolumeFloor }
        }

        requirement def EngineOutYaw {
            doc /* A multi-station craft shall hold the dead-engine
                   asymmetric-thrust yaw moment at the climb condition
                   with its yaw surfaces: the live station's full static
                   thrust at its spanwise arm, as a yawing-moment
                   coefficient, within the yaw volume's authority (the
                   volume coefficient times a nominal side-force
                   ceiling -- Raymer's engine-out fin-sizing case).
                   Subjects are the TIP-STATION configurations, where
                   the asymmetric arm is the half-span itself: the check
                   is the honest price of the tip-prop bonus.  The
                   root-station twin keeps its inboard arms inside the
                   differential-elevon-and-throttle story its own doc
                   tells, and the single-pusher shells have no
                   asymmetric case at all (honest absences).  NO
                   satisfy edge exists: at full climb-out thrust
                   neither the tip twin's winglets nor the tail-
                   sitter's co-located cruciform rudders hold the
                   moment -- the verdicts pin the busts, and the
                   fleet's only honest engine-out recovery stays the
                   multirotor one (shut the mirror station: the
                   four-station tail-sitter keeps a balanced pair, the
                   twin keeps nothing). */
            subject craft : Aircraft;
            assume constraint { craft.engineOutYawCn > 0.0 }
            require constraint yawHold {
                craft.engineOutYawCn <= craft.engineOutAuthorityCn }
        }

        // who satisfies what: all three tailless shells clear the three
        // tailless checks at their declared geometry (22 deg quarter-
        // chord sweep, bay-tuned CG -- the tip twin shares the twin's
        // planform and CG); the interpreter's verdicts back every edge,
        // and the unswept counterexample that would earn NO
        // PitchStability edge is pinned by the branch tests.  EngineOutYaw
        // earns no edge anywhere: both tip-station subjects bust it.
        satisfy PitchStability by FlyingWingSingle;
        satisfy PitchStability by FlyingWingTwin;
        satisfy PitchStability by FlyingWingTwinTip;
        satisfy PitchRollAuthority by FlyingWingSingle;
        satisfy PitchRollAuthority by FlyingWingTwin;
        satisfy PitchRollAuthority by FlyingWingTwinTip;
        satisfy YawStability by FlyingWingSingle;
        satisfy YawStability by FlyingWingTwin;
        satisfy YawStability by FlyingWingTwinTip;
    }

    // ----- the program scoreboard (MAUT) -------------------------------------
    // How good is the fleet, really?  The weights, utility shapes, and
    // ramps live IN THE MODEL, so the scoreboard widget and the trade
    // studies score the same truth.  The default measures below describe
    // the fleet's reference design point: the three T4 mission winners
    // and their combined invoice.  Tutorial T6 injects per-candidate
    // values over these defaults through the trade-study bridge.

    attribute stationMinutes : Real = 274.6 [SI::min];  // the ISR winner's loiter
                                                        // (the wings pay their ogive-bay skin)
    attribute payloadRangeKgKm : Real = 187.0;          // the logistics winner, kg km
                                                        // (the tip twin's recovered span, engine-out honestly busted)
                                                        // (the twin pays its derived-pod drag)
    attribute maxTargetSpeed : Real = 66.8;             // the dart's catchable crossing, m/s
                                                        // (riding its own gust placard)
    attribute fleetCost : Real = 9706.5;                // USD: the three winners' invoices
    attribute heaviestBirdKg : Real = 6.89;             // kg: the loaded courier at launch

    requirement scoring {
        doc /* The fleet-level MAUT hierarchy: mission effectiveness
               against affordability and operability, three levels deep.
               Weights are importance shares among siblings; each leaf
               declares its utility shape and ramp in mission units. */

        requirement effectiveness {
            attribute weight : Real = 3.0;
            requirement isrStation {
                attribute weight : Real = 2.0;
                attribute utility : String = "larger-is-better";
                attribute ramp0 : Real = 25.0;      // the tasking floor
                attribute ramp1 : Real = 240.0;     // a four-hour watch
                attribute measure : Real = stationMinutes;
                attribute unit : String = "min";
            }
            requirement logisticsWork {
                attribute weight : Real = 2.0;
                attribute utility : String = "larger-is-better";
                attribute ramp0 : Real = 8.0;       // 1 kg to the 8 km floor
                attribute ramp1 : Real = 180.0;
                attribute measure : Real = payloadRangeKgKm;
                attribute unit : String = "kg km";
            }
            requirement interceptCatch {
                attribute utility : String = "larger-is-better";
                attribute ramp0 : Real = 25.0;      // the crossing target
                attribute ramp1 : Real = 75.0;
                attribute measure : Real = maxTargetSpeed;
                attribute unit : String = "m/s";
            }
        }
        requirement affordability {
            attribute weight : Real = 2.0;
            requirement fleetPrice {
                attribute utility : String = "smaller-is-better";
                attribute ramp0 : Real = 16000.0;
                attribute ramp1 : Real = 6000.0;
                attribute measure : Real = fleetCost;
                attribute unit : String = "USD";
            }
        }
        requirement operability {
            attribute weight : Real = 2.0;
            requirement crewPortable {
                attribute weight : Real = 2.0;
                attribute utility : String = "smaller-is-better";
                attribute ramp0 : Real = 12.0;      // two-person lift
                attribute ramp1 : Real = 4.0;       // one-person launch
                attribute measure : Real = heaviestBirdKg;
                attribute unit : String = "kg";
            }
            requirement regulatory {
                doc /* Every fleet member stays under the 25 kg small-UAS
                       certification line. */
                require constraint { heaviestBirdKg <= 25.0 }
            }
            requirement autonomyRoadmap;  // deliberately unmeasured
        }
    }
}
