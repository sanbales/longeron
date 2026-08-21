// A multi-mission UAV catalog for the sysml2.analysis trade machinery.
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
// momentum-theory hover, parasite+induced-drag cruise, drag-limited dash --
// so the model itself carries the analysis.  These formulas (sqrt/pow,
// conditionals, calc invocations) are beyond the CP-SAT mapper's linear
// arithmetic; the intended workflow is TradeStudy.all_architectures() /
// evaluate(): enumerate the Cartesian candidate space and let the
// interpreter score every mix exactly (see notebook 07).
package UavMissions {
    doc /* Multi-mission UAV catalog: four airframe families, tiered
           components, and three mission contexts with executable physics. */

    // ----- external-analysis annotation ------------------------------------
    // Declares that a calc def's in/out parameters are the I/O contract of
    // a higher-fidelity tool wrapped as an OpenMDAO component.  `component`
    // is an entry-point path 'module:attr' (a Component subclass or a
    // factory callable).  sysml2.analysis.mdao.build_problem validates the
    // declared parameters against the component's actual I/O and can swap
    // fidelity per calc (candidate for a shared library package later).

    metadata def ExternalAnalysis {
        doc /* Marks a calc def as bindable to an external analysis
               component; the calc's parameters declare the contract. */
        attribute component : String;
    }

    // ----- physics ----------------------------------------------------------

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

    calc def DashSpeed {
        doc /* Parasite-drag-limited level top speed: available propulsive
               power = 0.5 rho CdA V^3 (induced drag is negligible at dash
               speeds). */
        in powerW : Real;           // propulsive power, W (elec x eta)
        in dragArea : Real;
        return : Real = pow(2.0 * powerW / (1.225 * dragArea), 1.0 / 3.0);
    }

    // ----- component families -----------------------------------------------

    part def Airframe {
        attribute mass : Real;              // kg, structure + wiring
        attribute cost : Real;              // USD
        attribute dragArea : Real;          // parasite CdA, m^2
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
    // requirement, no hover budget).
    part def BoxQuad :> Airframe {
        attribute mass : Real = 0.85;   attribute cost : Real = 95.0;
        attribute dragArea : Real = 0.055;
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
    }
    part def TeardropQuad :> Airframe {
        // The "do wings matter?" probe: a wingless quad wrapped in a
        // lathed teardrop shell.  CdA sits between the box quad (0.055)
        // and the winged dart (0.009); the shell costs money and mass
        // and squeezes the payload bay -- the missions decide the rest.
        attribute mass : Real = 1.05;   attribute cost : Real = 200.0;
        attribute dragArea : Real = 0.021;
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
        attribute fuselageLength : Real = 0.62;
    }
    part def VtolWing :> Airframe {
        attribute mass : Real = 2.30;   attribute cost : Real = 480.0;
        attribute dragArea : Real = 0.028;
        attribute wingSpan : Real = 2.6;  attribute wingChord : Real = 0.24;
        attribute taper : Real = 0.6;     attribute wingArea : Real = 0.624;
        attribute oswald : Real = 0.82;   attribute tipPropBonus : Real = 1.28;
        attribute loiterSpeed : Real = 15.0;
        attribute cruiseSpeed : Real = 21.0;
        attribute motorCount : Integer = 4;
        attribute diskAreaFactor : Real = 3.3;  // 2 main + 2 smaller tips
        attribute hoverThrustFactor : Real = 1.45;
        attribute payloadCapacity : Real = 5.5;
        attribute hoverOpsSec : Real = 120.0;
        attribute fuselageLength : Real = 0.95;
    }
    part def DartInterceptor :> Airframe {
        attribute mass : Real = 1.15;   attribute cost : Real = 300.0;
        attribute dragArea : Real = 0.009;
        attribute wingSpan : Real = 1.05; attribute wingChord : Real = 0.17;
        attribute taper : Real = 0.5;     attribute wingArea : Real = 0.179;
        attribute oswald : Real = 0.72;   attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 24.0;
        attribute cruiseSpeed : Real = 30.0;
        attribute motorCount : Integer = 1;   // single pusher
        attribute diskAreaFactor : Real = 1.0;
        attribute hoverThrustFactor : Real = 0.0;  // rail-launched
        attribute payloadCapacity : Real = 0.9;
        attribute hoverOpsSec : Real = 0.0;
        attribute fuselageLength : Real = 1.25;
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

    // ----- variation points ---------------------------------------------------

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

    // ----- the shared assembly under trade --------------------------------------

    part def MissionUAV {
        doc /* Airframe + propulsion + battery, common to every mission.
               Motor/prop stations are homogeneous ([4] selects one type
               for all); airframe.motorCount says how many stations the
               family populates (4, 4, 1), and the mass/cost/thrust
               build-ups scale by it. */

        attribute avionicsMass : Real = 0.18;   // kg: FC, GPS, radios
        attribute avionicsCost : Real = 140.0;

        part airframe : AirframeChoice;
        part motors : MotorChoice[4];
        part props : PropChoice[4];
        part battery : BatteryChoice;

        attribute baseMass : Real = airframe.mass + avionicsMass
            + battery.mass
            + airframe.motorCount * (motors.mass + props.mass);
        attribute baseCost : Real = airframe.cost + avionicsCost
            + battery.cost
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
        assert constraint stationReq { stationMinutes >= 25.0 }
    }

    // ----- mission 2: logistics -----------------------------------------------------

    part def LogisticsUav :> MissionUAV {
        doc /* Fly a parcel OUT to a delivery point and return EMPTY: the
               outbound leg carries bay + parcel, the return leg only the
               bay, so the two legs cost different power.  The radius is
               what the battery sustains for out + back at cruise speed
               after the hover (takeoff, drop, landing) budget. */

        part cargo : CargoChoice;

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
        assert constraint radiusReq { deliveryRadiusKm >= 8.0 }
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
               component masses and efficiencies are baked in, the loiter
               speed stays continuous.  Attribute values mirror the
               vtolWing + stdMotor + slimProp + packMax + stareEoIr mix. */

        attribute loiterSpeed : Real = 15.0;    // m/s -- the design variable
        attribute massKg : Real = 5.796;        // missionMass of the winner
        attribute dragArea : Real = 0.028;
        attribute span : Real = 2.6;
        attribute wingArea : Real = 0.624;
        attribute spanEff : Real = 1.0496;      // 0.82 Oswald x 1.28 tip props
        attribute propEff : Real = 0.697;       // slim prop x std motor
        attribute sensorPowerW : Real = 22.0;
        attribute usableEnergyJ : Real = 882126.0; // packMax x 80% - hover ops

        attribute loiterPowerW : Real = CruisePower(
            massKg = massKg, speed = loiterSpeed, dragArea = dragArea,
            span = span, wingArea = wingArea, spanEff = spanEff,
            propEff = propEff);
        attribute stationMinutes : Real =
            usableEnergyJ / (loiterPowerW + sensorPowerW) / 60.0;

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
