// DeepScout program -- tilttri.sysml: the tilt-rotor branch.
//
// The fleet's convertible airframe: a tri-rotor tilt-wing-borne VTOL
// that hovers on three tilted rotors and cruises as a conventional
// airplane.  A sibling specialization of the same abstract Aircraft as
// the multirotor, winged-VTOL, and flying-wing branches -- the
// open-closed proof again, and this time it is the very concept the
// program root names ("a future concept (a tilt-rotor, say) adds a
// sibling branch FILE without touching this one"): one new file, and
// the only edits elsewhere are the mission catalog's enumeration lines.
package TiltRotors {
    doc /* The tilt-rotor branch of the DeepScout program.  One
           airframe: the TiltTriWing, whose three motor stations TILT
           -- two wingtip pushers pivot down for hover and level for
           cruise, and a nose tractor pivots up for hover and forward
           for cruise -- so the same three rotors are lift rotors on
           departure and wing-relieved propellers on station.  The
           shell is fictional and flies real catalog parts (normal
           drone practice); every figure is NOMINAL -- teaching
           examples, not engineering data.

           DECLARED FIDELITY CEILING: the TRANSITION is not modeled.
           Conversion aerodynamics and kinematics (partial wing lift on
           the way through, rotor inflow at skewed angles, conversion-
           corridor scheduling) are derivative-and-time-domain work the
           closed forms here cannot see -- the same honesty line the
           intercept mission draws above ~25 m/s.  This branch prices
           the two ENDPOINT states only: the static three-rotor hover
           (with its wing-shadow download tax) and the wing-borne
           cruise (with its tip-recovery prize).  The tilt sweep
           between them is checked as GEOMETRY -- the discs must clear
           the airframe through the whole conversion arc, and the
           fleet interference gate samples that arc -- but no
           transition performance is claimed anywhere. */

    private import DeepScout::*;
    private import DeepScout::Aerodynamics::*;
    private import DeepScout::Packaging::*;
    private import DeepScout::Propulsion::*;
    private import DeepScout::StabilityControl::*;
    private import DeepScout::Structures::*;

    // ----- the wing-shadow closed forms ---------------------------------
    // A tilted-down tip rotor hangs its disc under the wing it just
    // left: the disc's vertical projection lands partly on the planform,
    // and the planform sits in the disc's induced flow.  Tiltrotor
    // practice prices what the shadowed area costs as DOWNLOAD -- the
    // XV-15 / V-22 class figure runs near 10% of thrust for a wing
    // fully immersed in the wake ("Tilt Rotor Download", Felker &
    // Light, J. AHS 1988; McVeigh, AIAA-86-2824) -- so the branch
    // charges downloadFactor of the thrust that the SHADOWED DISC
    // FRACTION carries, and the fraction itself is computed from the
    // declared planform geometry, not quoted.

    calc def UnitDiscAftFraction {
        doc /* Area fraction of a unit disc lying at abscissa >= m of
               the radius (the circular-segment closed form): (acos(m)
               - m sqrt(1 - m^2)) / pi, clamped at m = 1 where the
               segment empties. */
        in m : Real;
        return : Real = (acos(min(1.0, m))
            - min(1.0, m) * sqrt(1.0 - min(1.0, m) * min(1.0, m))) / pi;
    }

    calc def TipDiscShadowFraction {
        doc /* The shadowed fraction of one wingtip disc, tilted down at
               the tip station.  In plan view the tilted disc's centre
               lands AT the pivot (the disc rides tiltArm below it, and
               rotation about the spanwise pivot axis drops it straight
               down), so the disc sits pivotSetback aft of the local
               trailing edge; the wing covers the chordwise band from
               the trailing edge forward through the local chord, and
               only the INBOARD half-disc overlaps the planform at all.
               The fraction is the circular segment between those two
               chordwise stations, halved -- first order on purpose:
               the sweep's small plan-view relief inboard of the tip is
               ignored, and the local chord is read at the tip station
               itself. */
        in discRadius : Real;
        in pivotSetback : Real;    // m, pivot aft of the local trailing edge
        in chord : Real;           // m, local chord at the tip station
        return : Real = 0.5 * (
            UnitDiscAftFraction(m = pivotSetback / discRadius)
            - UnitDiscAftFraction(m = min(1.0,
                (pivotSetback + chord) / discRadius)));
    }

    part def TiltTriWing :> Airframe {
        doc /* The tilt-rotor tri-wing: a conventional monoplane --
               lathed fuselage, one swept tapered wing, cruciform-free
               conventional tail -- whose three motor stations pivot.
               The two WINGTIP stations are Arc B's tip-pusher
               arrangement (the FlyingWingTwinTip installation: disc
               behind the tip trailing edge, the clearance-derived pod
               chain priced below), swung DOWN 90 deg for hover so the
               discs hang level under the tips; the NOSE station is a
               tractor, swung UP 90 deg so its disc rides level over
               the nose.  What the branch buys and pays, each derived
               or cited:

               THE PRICES.  (1) Tilt mechanism mass, per pivot: an
               actuator, a bearing, and pivot structure at each of the
               three stations, priced at a NOMINAL 1% of design gross
               PER PIVOT -- the three-pivot total (3%) sits inside the
               2..4% conversion-system weight-fraction band of tiltrotor
               design practice (NASA XV-15 weight statements; Raymer's
               V/STOL weights chapter).  (2) The hover is a THREE-rotor
               hover: tri geometry keeps no torque-balanced set after
               any single failure (the openTri precedent), so motor-out
               hover is NOT survivable and no FailSafeHover story
               exists here -- an honest absence, stated instead of
               hidden.  The steady differential-tilt yaw trim a tri
               needs (the nose rotor's torque has no twin) costs a
               nominal 0.1-disc haircut, the openTri's tail-vector
               convention.  (3) The WING-SHADOW download: the tilted
               tip discs project onto the planform they serve, and the
               hover pays downloadFactor of the shadowed disc fraction
               (TipDiscShadowFraction above -- computed from the
               declared planform, with the XV-15 / V-22 class 10%
               download figure as the NOMINAL price).  The tax reaches
               the lift ledger through hoverThrustFactor (thrust must
               cover weight over the download) and the energy ledger
               through the effective disk area: momentum hover power
               scales as T^1.5 / sqrt(A) at T = W / liftFraction, so
               diskAreaFactor carries liftFraction^3 exactly.

               THE PRIZES.  (1) Wing-borne cruise with the DERIVED tip
               recovery: the tips carry the props in cruise, so the
               same TipPropRecovery closed form the tip twin and the
               tail-sitter earn their uplift from applies here --
               root-station shells earn nothing.  (2) The VTOL
               missions the pure wings cannot fly: hoverThrustFactor >
               0 subjects this shell to every hover demand the
               tail-sitter answers, with no catapult rail anywhere.
               (3) CENTERLINE CRUISE REDUNDANCY: after a tip engine
               dies in cruise the mixer shuts the mirror tip and the
               NOSE puller flies home on the centerline -- zero
               asymmetric arm, no yaw case at all -- so this shell
               PASSES the cruise engine-out check (CruiseEngineOut
               below, the Arc B verdict pattern) that the tip twin
               busts by an order of magnitude in EngineOutYaw.  The
               same honesty cuts the other way: in HOVER an engine out
               is fatal (price 2), and no requirement pretends
               otherwise.  It never cruises asymmetric (the tips fly
               paired or not at all), so it subjects no EngineOutYaw
               case -- the recovery is shutdown-and-centerline, not
               rudder authority. */

        // ----- the airframe: one wing, one hull, one tail ---------------
        attribute fuselageLength : Real = 1.05;
        attribute fuselageDiameter : Real = 0.14;
        attribute wingSpan : Real = 2.4;  attribute wingChord : Real = 0.30;
        attribute taper : Real = 0.5;     attribute wingArea : Real = 0.72;
        attribute tailArea : Real = 0.14;   // m^2, tailplane + fin together
        // modest quarter-chord sweep: it carries the tip pivots aft of
        // the spar box, so the pivot bearing sits behind the structure
        // it swings around (and the pod chain below prices the station
        // exactly the way Arc B's does)
        attribute sweepDeg : Real = 10.0;
        attribute wingSection : String = "2412";   // drawn section (NACA)
        attribute rootChord : Real = 2.0 * wingChord / (1.0 + taper);
        attribute tipChord : Real = taper * rootChord;

        // ----- the tilt-pod chain: Arc B's clearance geometry, pivoted --
        // The tip stations reuse the flying-wing branch's pusher pod
        // chain -- base motor housing plus a declared disc-plane
        // clearance -- with ONE new member: the pivot bearing's
        // setback.  The pod nose fairs into the local trailing edge,
        // the PIVOT sits tiltPivotSetback aft of it (inside the pod,
        // never inside the wing), and the disc rides tiltArm further
        // aft.  At a wingletless TIP the local trailing edge is the
        // aftmost point the disc spans (the swept TE recedes going
        // inboard), so Arc B's TE-rise term is zero BY GEOMETRY here
        // and the chain needs no extrapolation up a winglet.  The
        // pivot-aft-of-TE arrangement is also the conversion-clearance
        // guarantee: every disc point stays at least tiltArm from the
        // pivot through the whole 90-deg sweep, and the chord-plane
        // crossing sits tiltArm / cos(tilt) BEHIND the pivot at every
        // tilt angle -- aft of the trailing edge always.  The fleet
        // interference gate samples the arc and holds the meshes to it.
        attribute propDiameterRef : Real = 0.2794;  // m, APC 11x5.5E disc
        attribute podStation : Real = 0.5 * wingSpan;   // the tips
        attribute podBaseLength : Real = 0.06;   // m, motor + mount housing
        attribute discClearance : Real = 0.03;   // m, disc plane aft of the pod
        attribute tiltPivotSetback : Real = 0.04;   // m, pivot aft of the local TE
        attribute tiltArm : Real = podBaseLength + discClearance;   // pivot -> disc
        attribute podLength : Real = tiltPivotSetback + tiltArm;    // m, derived
        attribute podDiameter : Real = 0.05;     // m
        // the nose station: pivot at the fuselage apex, disc noseArm
        // ahead in cruise and noseArm above it in hover -- ahead of
        // (and above) every fuselage point by construction
        attribute noseArm : Real = 0.10;         // m, nose pivot -> disc

        // ----- price 1: the tilt mechanism, per pivot --------------------
        attribute tiltPivotCount : Integer = 3;
        // NOMINAL: 1% of design gross PER PIVOT (actuator + bearing +
        // pivot structure); the 3-pivot total sits inside the 2..4%
        // conversion-system band of tiltrotor weight practice (NASA
        // XV-15 weight statements; Raymer, V/STOL aircraft weights)
        attribute tiltMechFractionPerPivot : Real = 0.01;
        attribute tiltMechMass : Real =
            tiltPivotCount * tiltMechFractionPerPivot * designGrossKg;

        // ----- tip structure: the spar carries the swinging stations ----
        // The Arc B doubler chain, with the pivot hardware's share in
        // the tip unit: a motor pod AND its bearing at a wingtip is a
        // point load the spar must carry at the design load factor.
        attribute tipUnitKg : Real = 0.30;   // motor + pod + pivot bearing share
        attribute tipLoadN : Real = 2.5 * tipUnitKg * 9.81;
        attribute tipReinforceWall : Real = max(
            TubeWallForStress(momentNm = tipLoadN * 0.5 * wingSpan,
                              radius = sparRadius, yieldPa = 2.4e8),
            TubeWallForStiffness(tipLoadN = tipLoadN,
                                 length = 0.5 * wingSpan,
                                 radius = sparRadius, modulusPa = 6.9e10));
        attribute tipStructMass : Real = 2.0 * TubeMass(
            radius = sparRadius, wall = tipReinforceWall,
            length = 0.5 * wingSpan, density = 2700.0);
        attribute mass : Real = 1.95 + tipStructMass + tiltMechMass;
        // the tilt hardware is the expensive part: three HV actuators,
        // three machined pivots, conversion interlocks (nominal street)
        attribute cost : Real = 1350.0;

        // ----- price 3: the wing-shadow download -------------------------
        attribute downloadFactor : Real = 0.10;   // XV-15 / V-22 class, NOMINAL
        attribute tipShadowFraction : Real = TipDiscShadowFraction(
            discRadius = 0.5 * propDiameterRef,
            pivotSetback = tiltPivotSetback, chord = tipChord);
        // two of three discs shadow the wing; the nose disc rides clear
        // ahead of the hull (equal disc loading assumed)
        attribute hoverShadowFraction : Real = 2.0 / 3.0 * tipShadowFraction;
        attribute hoverLiftFraction : Real =
            1.0 - downloadFactor * hoverShadowFraction;
        // pure rotor-borne hover (a converting tiltrotor hangs on its
        // rotors near the ground: no wing assist, unlike the
        // tail-sitter's 1.35), with vectoring nacelles buying a notch
        // of control margin back from the box quad's 1.6 (NOMINAL)...
        attribute hoverThrustFactorClean : Real = 1.45;
        // ...and the download tax on top: thrust covers weight over the
        // shadowed lift fraction
        attribute hoverThrustFactor : Real =
            hoverThrustFactorClean / hoverLiftFraction;
        // price 2's yaw-trim haircut (openTri convention), then the
        // download reaches the ENERGY ledger exactly: momentum hover
        // power scales T^1.5 / sqrt(A) at T = W / liftFraction, so an
        // effective disk area of liftFraction^3 makes the shared
        // HoverPower call carry the tax with no new physics
        attribute yawTrimDiscLoss : Real = 0.1;
        attribute diskAreaFactor : Real =
            (3.0 - yawTrimDiscLoss) * pow(hoverLiftFraction, 3.0);

        // ----- the drag buildup: one wing pays skin, not two -------------
        // The tiltrotor's cruise case against the cruciform tail-sitter,
        // earned in the wetted-area ledger: one lifting wing, a hull, a
        // conventional tail, and two tip pods -- the nose station rides
        // inside the hull's own nose, no third pod
        attribute dragArea : Real = 1.15 * (     // interference/excrescence
            SkinFrictionDrag(
                wettedArea = BodyWettedArea(length = fuselageLength,
                                            diameter = fuselageDiameter),
                formFactor = BodyFormFactor(length = fuselageLength,
                                            diameter = fuselageDiameter))
            + SkinFrictionDrag(                  // the wing, NACA 2412-class
                wettedArea = WingWettedArea(planformArea = wingArea),
                formFactor = WingFormFactor(thicknessRatio = 0.12))
            + SkinFrictionDrag(                  // tailplane + fin, NACA 0009
                wettedArea = WingWettedArea(planformArea = tailArea),
                formFactor = WingFormFactor(thicknessRatio = 0.09))
            + 2.0 * SkinFrictionDrag(            // the two tilt pods
                wettedArea = BodyWettedArea(length = podLength,
                                            diameter = podDiameter),
                formFactor = BodyFormFactor(length = podLength,
                                            diameter = podDiameter)));
        // the tips carry the props in cruise: the same derived recovery
        // the tip twin and the tail-sitter earn, nothing quoted
        attribute tipPropBonus : Real = TipPropRecovery(
            diskDiameter = propDiameterRef, span = wingSpan);
        // the counter-rotating tips cancel each other; the nose puller's
        // torque rides a small standing aileron trim -- a notch off the
        // twin's 0.80, above the single's 0.78
        attribute oswald : Real = 0.79;
        attribute loiterSpeed : Real = 14.0;
        attribute cruiseSpeed : Real = 20.0;
        attribute motorCount : Integer = 3;
        // hover climb-out on three rotors: the rotor families' sustained
        // fraction, not the wings' full-throttle catapult convention
        attribute climbDrawFraction : Real = 0.7;
        attribute payloadCapacity : Real = 3.2;
        attribute hoverOpsSec : Real = 120.0;
        attribute armCount : Integer = 0;      // rotors ride the tips + nose
        attribute sparRadius : Real = 0.013;   // fits the 12% root section
        attribute designGrossKg : Real = 6.6;  // shell + heavy pack + parcel

        // ----- prize 3: the centerline cruise engine-out story -----------
        // One tip engine dead in cruise: the mixer shuts the mirror tip
        // (the multirotor idiom -- keep the balanced set) and the nose
        // puller carries the cruise home alone on the centerline.  The
        // check is a POWER check, not a yaw check: level cruise at
        // design gross must fit inside one station's continuous rating.
        // Reference station figures are the same NOMINAL X4112S-class
        // numbers the twin's redundancy story quotes (800 W continuous)
        // at the catalog's nominal cruise efficiencies; the shut tips
        // surrender the tip recovery, so the engine-out polar reads the
        // bare Oswald factor -- the derived bonus dies with the motors
        // that earn it.
        attribute referenceStationW : Real = 800.0;   // X4112S continuous, NOMINAL
        attribute referencePropEff : Real = 0.82;     // APC 11x5.5E, catalog nominal
        attribute referenceMotorEff : Real = 0.83;    // X4112S, catalog nominal
        attribute engineOutCruisePowerW : Real = CruisePower(
            massKg = designGrossKg, speed = cruiseSpeed,
            dragArea = dragArea, span = wingSpan, wingArea = wingArea,
            spanEff = oswald,   // tips shut: no recovery
            propEff = referencePropEff * referenceMotorEff);
        attribute engineOutStationW : Real = referenceStationW;

        // ----- the payload bay: the hull interior ------------------------
        // The full mid-body holds its diameter over most of the length
        // (the tail-sitter's prismatic convention); pack, avionics, and
        // payload share the hull.  The mid-size parcel cradle fits; the
        // assembled survey gimbal honestly does not.
        attribute bayShape : String = "hull";
        attribute bayLength : Real = fuselageLength;
        attribute bayWidth : Real = fuselageDiameter;
        attribute bayHeight : Real = fuselageDiameter;
        attribute grossVolume : Real = RevolvedVolume(
            length = fuselageLength, diameter = fuselageDiameter,
            prismaticCoeff = 0.72);                         // 11.6 L
        attribute usableVolumeFraction : Real = 0.65;
        attribute equipmentBayFactor : Real = 1.0;

        // the clickable internals: the equipment every variant carries
        part battery : ScoutParts::Battery;
        part flightController : ScoutParts::F450Kit::FlightController;
        part camera : ScoutParts::F450Kit::Camera;
    }

    requirement def CruiseEngineOut {
        doc /* After any single cruise engine failure, a torque-balanced
               surviving motor set shall still sustain level cruise at
               design gross: the surviving set's continuous electric
               rating must cover the level-cruise draw.  Subjects are
               the shells whose mixer keeps a CENTERLINE station after
               the shutdown -- the tilt-tri's nose puller.  The tip
               twin keeps NOTHING once its mirror station is shut (both
               stations are tips), so it has no subject here and busts
               EngineOutYaw instead; the honest absences point both
               ways.  HOVER engine-out stays fatal for the tri
               geometry, and no requirement here or anywhere pretends
               otherwise. */
        subject craft : Aircraft;
        assume constraint { craft.engineOutCruisePowerW > 0.0 }
        require constraint cruiseHome {
            craft.engineOutCruisePowerW <= craft.engineOutStationW }
    }

    // the verdict backs the edge: level cruise at design gross costs a
    // fraction of one station's continuous rating (the interpreter
    // evaluates ~165 W against 800), so the centerline recovery HOLDS
    // -- the redundancy the coming attrition ledger prices low
    satisfy CruiseEngineOut by TiltTriWing;
}
