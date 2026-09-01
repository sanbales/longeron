// DeepScout program -- flyingwing.sysml: the flying-wing branch.
//
// The fleet's tailless airframes: a single-pusher ISR wing and a
// counter-rotating twin-pusher courier.  Sibling specializations of
// the same abstract Aircraft as the multirotor and winged-VTOL
// branches -- this file IS the open-closed proof of the program
// layout: a whole new concept family lands as one new file, and the
// only edits elsewhere are the mission catalog's enumeration lines
// (missions.sysml names what it trades; nothing else changes).
package FlyingWings {
    doc /* The flying-wing branch of the DeepScout program.  Neither
           airframe is a VTOL -- like the DartInterceptor they launch
           from a catapult rail and belly-land -- and neither carries a
           fuselage or a tail: the wing IS the fuselage, so the whole
           parasite-drag ledger is one wing's skin plus winglets and
           pusher pods.  That is the branch's engineering story, and
           the wetted-area buildup of DeepScout::Aerodynamics is where
           it must be earned, not quoted.  Both shells are fictional
           and fly real catalog parts (normal drone practice); every
           figure is NOMINAL -- teaching examples, not engineering
           data. */

    private import DeepScout::*;
    private import DeepScout::Aerodynamics::*;
    private import DeepScout::Packaging::*;
    private import DeepScout::StabilityControl::*;
    private import DeepScout::Structures::*;

    abstract part def FlyingWing :> Airframe {
        doc /* What every flying wing in the branch shares: tailless,
               wing-borne, non-VTOL.  hoverThrustFactor 0 states the
               honest absence of a hover requirement (rail-launched,
               like the dart -- there is no FailSafeHover story here
               because there is no hover to fail safe into), and the
               drag area is the branch buildup: one thick wing (the
               15% root section swallows the pack and payload that
               would otherwise need a fuselage), two winglets for yaw
               stability, and one pusher pod per motor station. */
        // the wing IS the fuselage: no body length, and the missing
        // fuselage is the branch's whole drag advantage
        attribute fuselageLength : Real = 0.0;
        // thick root section: the payload bay lives inside the wing
        attribute rootThickness : Real = 0.15;   // t/c, root
        attribute wingletArea : Real;            // m^2, each of two

        // ----- the pusher pod chain: clearance geometry, not a quote
        // A trailing-edge pusher's disc must sit AFT of every trailing-
        // edge point it spans, and on an aft-swept wing the local TE
        // recedes going outboard (TrailingEdgeAft): a disc of radius r
        // at spanwise station y sees the TE furthest aft at y + r.  The
        // pod bridges exactly that rise, plus a declared disc-plane
        // clearance, on top of the base housing a pusher needs anyway
        // -- so sweep honestly buys pod length, and the drag buildup
        // below charges the extra skin.  The rise is derived for the
        // branch's reference disc (the APC 11x5.5E of the heavy
        // catalog); every catalog prop the missions cross swings a
        // rise well inside the clearance cushion.
        attribute propDiameterRef : Real = 0.2794;  // m, APC 11x5.5E disc
        // where the pushers ride: the installation vocabulary of the
        // branch -- "root" stations flank the root bay, "tip" stations
        // ride the wingtips (the twin's trade axis; see FlyingWingTwinTip)
        attribute propStation : String = "root";    // root | tip
        attribute podStation : Real = 0.0;       // m, spanwise pusher station
        attribute podBaseLength : Real = 0.06;   // m, motor + mount housing
        attribute discClearance : Real = 0.03;   // m, disc plane behind the TE
        // the swept TE's rise across the disc's span extent (worst at
        // station + radius); a forward-raked teaching variant clamps to 0
        attribute podTeRise : Real = max(0.0,
            TrailingEdgeAft(rootChord = rootChord, taper = taper,
                span = wingSpan, sweepDeg = sweepDeg,
                y = podStation + 0.5 * propDiameterRef)
            - TrailingEdgeAft(rootChord = rootChord, taper = taper,
                span = wingSpan, sweepDeg = sweepDeg, y = podStation));
        attribute podLength : Real =
            podBaseLength + discClearance + podTeRise;   // m, derived
        attribute podDiameter : Real = 0.05;     // m

        // ----- the payload bay: a blended ogive pod on the root bay
        // The thick root section is the bay's heart, but a wing 15%
        // thick swallows only so much: a blended OGIVE pod rides the
        // root's belly (an ogive of revolution, half-buried -- its
        // crown lives inside the wing) and opens into the root bay, so
        // the declared envelope is the pod's lathe PLUS the root cell
        // between the spars.  Only the pod's exposed skin pays drag:
        // bayExposedFraction is the wetted share outside the wing, and
        // the buildup below charges it like every other body.  The
        // pack rides the bay's aft rail (the CG story above), so the
        // equipment shares the bay with the payload.
        attribute bayShape : String = "ogive";
        attribute bayLength : Real;              // m, pod lathe length
        attribute bayWidth : Real;               // m, pod diameter
        attribute bayHeight : Real = bayWidth;   // a lathe: height = diameter
        attribute rootBayVolume : Real;          // m^3, the in-wing root cell
        attribute bayExposedFraction : Real = 0.7;   // pod skin outside the wing
        attribute grossVolume : Real = RevolvedVolume(
            length = bayLength, diameter = bayWidth) + rootBayVolume;
        attribute usableVolumeFraction : Real = 0.70;
        attribute equipmentBayFactor : Real = 1.0;

        attribute dragArea : Real = 1.15 * (     // interference/excrescence
            SkinFrictionDrag(                    // the one lifting surface
                wettedArea = WingWettedArea(planformArea = wingArea),
                formFactor = WingFormFactor(thicknessRatio = rootThickness))
            + 2.0 * SkinFrictionDrag(            // wingtip winglets, NACA 0009
                wettedArea = WingWettedArea(planformArea = wingletArea),
                formFactor = WingFormFactor(thicknessRatio = 0.09))
            + motorCount * SkinFrictionDrag(     // trailing-edge pusher pods
                wettedArea = BodyWettedArea(length = podLength,
                                            diameter = podDiameter),
                formFactor = BodyFormFactor(length = podLength,
                                            diameter = podDiameter))
            + bayExposedFraction * SkinFrictionDrag(   // the blended bay pod
                wettedArea = BodyWettedArea(length = bayLength,
                                            diameter = bayWidth),
                formFactor = BodyFormFactor(length = bayLength,
                                            diameter = bayWidth)));
        attribute tipPropBonus : Real = 1.0;     // pushers ride the TE, not the tips
        attribute hoverThrustFactor : Real = 0.0;   // catapult-launched: no hover
        attribute hoverOpsSec : Real = 0.0;         // ... and no hover budget
        // the catapult climb-out runs full throttle until the wing is
        // at pattern altitude: the pack must feed every motor's rated
        // draw (the same convention as the dart's dash)
        attribute climbDrawFraction : Real = 1.0;
        attribute armCount : Integer = 0;        // no rotor arms to size

        // ----- stability & control: what the wing carries instead of a tail
        // A tailless wing has no tail arm, so the planform itself must
        // buy pitch trim and stability: the quarter-chord sweep carries
        // the MAC -- and with it the neutral point -- aft of the root
        // bay, so the bay-loaded CG sits AHEAD of the neutral point
        // (static margin); washout and the reflexed root section give
        // the swept wing the nose-up zero-lift moment it trims against.
        // The margin and the control volumes below are checked by the
        // tailless requirement family (ScoutMissions::
        // StabilityRequirements) through the StabilityControl calcs;
        // the trim moment itself stays declared, not computed -- that
        // is derivative-fidelity work the closed forms cannot see.
        attribute sweepDeg : Real = 22.0;   // quarter-chord sweep, deg aft
        attribute washoutDeg : Real = 3.0;  // tip twist below the root, deg
        // mesh section spec: the 15% root-bay thickness (rootThickness)
        // with the parametric reflexed camber line of
        // longeron.analysis.geometry -- a stand-in for a real reflexed
        // family, not a catalog airfoil
        attribute wingSection : String = "reflexed0015";
        // elevons: one trailing-edge band per side, the outer half of
        // each panel at a quarter of the local chord
        attribute elevonSpanFrac : Real = 0.5;   // band span / half-span
        attribute elevonChordFrac : Real = 0.25; // elevon chord / local chord
        attribute cgMac : Real;   // CG aft of the root LE, in MAC units
        // the derived S&C figures the requirement family checks.  The
        // stations compose: mac and neutralPointAft are the planform's
        // own figures (single-panel here; the cranked single redefines
        // both with the Raymer multi-panel composition), cgAft turns
        // the declared cgMac into metres aft of the root LE, and the
        // margin and volume calcs read the composed stations -- so one
        // CG feeds every check, whichever composition produced it.
        attribute rootChord : Real = 2.0 * wingChord / (1.0 + taper);
        attribute tipChord : Real = taper * rootChord;
        attribute mac : Real =
            MeanAeroChord(rootChord = rootChord, taper = taper);
        attribute neutralPointAft : Real = NeutralPointAft(
            rootChord = rootChord, taper = taper, span = wingSpan,
            sweepDeg = sweepDeg);
        attribute cgAft : Real = cgMac * mac;    // m aft of the root LE
        attribute staticMargin : Real = StaticMargin(
            neutralPointAft = neutralPointAft, mac = mac, cgAft = cgAft);
        attribute elevonPitchVolume : Real = ElevonPitchVolume(
            rootChord = rootChord, taper = taper, span = wingSpan,
            sweepDeg = sweepDeg, cgAft = cgAft, mac = mac,
            spanFrac = elevonSpanFrac, chordFrac = elevonChordFrac);
        attribute elevonRollVolume : Real = ElevonRollVolume(
            span = wingSpan, spanFrac = elevonSpanFrac,
            chordFrac = elevonChordFrac);
        attribute wingletYawVolume : Real = WingletYawVolume(
            wingletArea = wingletArea, rootChord = rootChord,
            taper = taper, span = wingSpan, sweepDeg = sweepDeg,
            cgAft = cgAft, wingArea = wingArea);
    }

    part def FlyingWingSingle :> FlyingWing {
        doc /* The single-pusher ISR wing: one motor station on the
               trailing edge at the root.  Reference pairing from the
               heavy catalog: a SunnySky X4112S-class pusher swinging
               an APC 11x5.5E (the mission studies cross it with every
               motor/prop/pack mix and let the constraints decide).
               The planform is CRANKED for that pusher -- the standard
               flying-wing installation: a flat-TE center section
               slightly wider than the prop disc (centerSectionSpan,
               derived from the reference disc plus a declared margin)
               holds the trailing edge level across the whole disc, so
               the disc tucks behind it on the base-length pod instead
               of chasing the swept TE outboard (podTeRise 0).  The
               outer panels sweep as before; the crank reshapes the
               DRAWN planform and the S&C composition only -- the
               declared performance closures (wingArea, wingSpan,
               oswald) are untouched.
               The price of one propeller: its torque has no twin to
               cancel against, so the elevons carry a standing trim
               deflection -- that ride is in the Oswald factor, a
               notch below the twin's.  The payload bay takes the
               stabilized Zenmuse-class gimbal and nothing heavier:
               an ISR specialist, honestly excluded from the parcel
               trade the way the teardrop is. */
        attribute wingSpan : Real = 2.2;  attribute wingChord : Real = 0.32;
        attribute taper : Real = 0.45;    attribute wingArea : Real = 0.704;
        attribute wingletArea : Real = 0.030;
        attribute mass : Real = 1.15;   attribute cost : Real = 520.0;

        // ----- the cranked center section (pusher bay) -------------
        // flat TE from -crankY to +crankY at the crank station's TE;
        // the disc (radius 0.1397 m) rides inside it with margin
        attribute centerMargin : Real = 0.03;    // m, disc tip to crank
        attribute centerSectionSpan : Real =
            propDiameterRef + 2.0 * centerMargin;   // 0.3394 m
        attribute crankY : Real = 0.5 * centerSectionSpan;
        // the disc spans the flat TE only: any reference disc that
        // outgrew the center section would price its overhang off the
        // outer panel's TE here, and today's clamps to exactly 0
        attribute podTeRise : Real = max(0.0,
            TrailingEdgeAft(rootChord = rootChord, taper = taper,
                span = wingSpan, sweepDeg = sweepDeg,
                y = max(crankY, podStation + 0.5 * propDiameterRef))
            - TrailingEdgeAft(rootChord = rootChord, taper = taper,
                span = wingSpan, sweepDeg = sweepDeg, y = crankY));

        // ----- the cranked planform's S&C composition ---------------
        // Two straight-tapered panels per side (Raymer's multi-panel
        // method): the center panel runs from the centerline to the
        // crank -- its TE flat at the crank station's TE, its LE the
        // planform's own swept leading edge -- and the outer panel is
        // the swept trapezoid as before.  Each panel contributes its
        // own MAC and its own quarter-chord-of-MAC station; the
        // composite is the area-weighted mean of each (one-side areas;
        // the weights normalize).  The flat-TE center carries chord
        // (and area) the straight taper did not have, so the composite
        // MAC grows and the neutral point slides a little forward in
        // MAC units: 0.892 against the trapezoid's 0.908.
        attribute crankTeAft : Real = TrailingEdgeAft(
            rootChord = rootChord, taper = taper, span = wingSpan,
            sweepDeg = sweepDeg, y = crankY);       // the flat TE station
        attribute crankChord : Real = LocalChord(rootChord = rootChord,
            taper = taper, span = wingSpan, y = crankY);
        // center panel: centerline chord = the flat TE station itself
        // (the LE passes through 0 at the root), crank chord outboard
        attribute centerPanelTaper : Real = crankChord / crankTeAft;
        attribute centerPanelArea : Real =
            crankY * (crankTeAft + crankChord) / 2.0;    // m^2, one side
        attribute centerPanelMac : Real = MeanAeroChord(
            rootChord = crankTeAft, taper = centerPanelTaper);
        // the center panel's quarter-chord line: 0.25 x the flat TE
        // plus 0.75 x the (unchanged) leading edge, read at the
        // panel's own MAC station
        attribute centerPanelAcAft : Real = 0.25 * crankTeAft
            + 0.75 * LeadingEdgeAft(rootChord = rootChord, taper = taper,
                span = wingSpan, sweepDeg = sweepDeg,
                y = MacSpanStation(span = 2.0 * crankY,
                    taper = centerPanelTaper));
        // outer panel: the swept trapezoid from the crank to the tip
        attribute outerPanelWidth : Real = 0.5 * wingSpan - crankY;
        attribute outerPanelTaper : Real = tipChord / crankChord;
        attribute outerPanelArea : Real =
            outerPanelWidth * (crankChord + tipChord) / 2.0;  // one side
        attribute outerPanelMac : Real = MeanAeroChord(
            rootChord = crankChord, taper = outerPanelTaper);
        attribute outerPanelAcAft : Real = QuarterChordAft(
            rootChord = rootChord, sweepDeg = sweepDeg,
            y = crankY + MacSpanStation(span = 2.0 * outerPanelWidth,
                taper = outerPanelTaper));
        // the composite figures every inherited check reads
        attribute mac : Real = AreaWeighted(
            areaA = centerPanelArea, valueA = centerPanelMac,
            areaB = outerPanelArea, valueB = outerPanelMac);
        attribute neutralPointAft : Real = AreaWeighted(
            areaA = centerPanelArea, valueA = centerPanelAcAft,
            areaB = outerPanelArea, valueB = outerPanelAcAft);

        // the pack rides the aft rail of the root bay: the CG lands at
        // 0.82 composite MAC aft of the root leading edge, 0.072 MAC
        // ahead of the cranked planform's neutral point (0.892 MAC) --
        // inside the tailless static-margin band
        attribute cgMac : Real = 0.82;
        // the standing elevon deflection that trims the single prop's
        // torque rides in the Oswald factor, a notch below the twin's
        attribute oswald : Real = 0.78;
        attribute loiterSpeed : Real = 14.0;
        attribute cruiseSpeed : Real = 19.0;
        attribute motorCount : Integer = 1;   // single pusher
        attribute diskAreaFactor : Real = 1.0;
        attribute payloadCapacity : Real = 1.0;
        attribute sparRadius : Real = 0.014;   // fits the 15% root section
        attribute designGrossKg : Real = 4.6;  // shell + big pack + gimbal

        // the ISR bay: a sensor-pod ogive under the root, sized so the
        // Zenmuse-class gimbal, the endurance pack, and the avionics
        // stow together; the root cell is the cranked center section's
        // mid-chord bay (0.34 m of flat-TE span at the 15% root)
        attribute bayLength : Real = 0.48;
        attribute bayWidth : Real = 0.15;
        attribute rootBayVolume : Real = 0.0036;

        // the clickable internals: the equipment every variant carries
        part battery : ScoutParts::Battery;
        part flightController : ScoutParts::F450Kit::FlightController;
        part camera : ScoutParts::F450Kit::Camera;
    }

    part def FlyingWingTwin :> FlyingWing {
        doc /* The twin-pusher courier: two counter-rotating trailing-
               edge pushers, one either side of the root bay.  Counter
               rotation is the twin's first engineering point: the
               props' torques cancel, so no rudder-or-elevon trim drag
               rides along -- its Oswald factor keeps what the single's
               torque trim spends.  Redundancy is the second, and it
               is honest through the numbers: level cruise at 22 m/s
               costs this shell a few hundred watts electric at gross,
               well inside ONE catalog motor's continuous rating
               (nominal: an X4112S holds 800 W, an Antigravity 420 W),
               so single-engine-out cruise home HOLDS with margin --
               what a twin buys a courier.  What it does not buy is a
               hover: FailSafeHover is a rotorcraft requirement and no
               flying wing subjects it.  The wider bay takes the
               mid-size parcel cradle; the winch bay is honestly past
               it. */
        attribute wingSpan : Real = 2.6;  attribute wingChord : Real = 0.327;
        attribute taper : Real = 0.45;    attribute wingArea : Real = 0.85;
        attribute wingletArea : Real = 0.040;
        attribute mass : Real = 1.55;   attribute cost : Real = 780.0;
        // the pushers ride the swept TE either side of the root bay,
        // at the same stations the mesh row places them -- and the pod
        // chain prices what the sweep costs there: the TE recedes
        // 36 mm across the reference disc, so each pod runs 0.126 m
        // against the flat-TE single's 0.09
        attribute podStation : Real = wingSpan / 6.0;   // m, either side
        // the wider bay spreads the pack and parcel further aft: the CG
        // lands at 0.91 MAC aft of the root leading edge, 0.089 MAC
        // ahead of this planform's neutral point (0.998 MAC)
        attribute cgMac : Real = 0.91;
        // counter-rotation cancels the torque trim the single pays for
        attribute oswald : Real = 0.80;
        attribute loiterSpeed : Real = 15.0;
        attribute cruiseSpeed : Real = 22.0;
        attribute motorCount : Integer = 2;   // counter-rotating pushers
        attribute diskAreaFactor : Real = 2.0;
        attribute payloadCapacity : Real = 2.8;
        attribute sparRadius : Real = 0.014;   // fits the 15% root section
        attribute designGrossKg : Real = 7.0;  // parcel + the heavy pack

        // the courier bay: the root cell does the carrying (0.72 m of
        // root span between the pushers, the mid-chord cell of the 15%
        // section), and a slimmer ogive pod fairs the doors and the
        // pack -- the mid-size parcel cradle stows with margin, the
        // survey kit's assembled envelope honestly does not
        attribute bayLength : Real = 0.44;
        attribute bayWidth : Real = 0.14;
        attribute rootBayVolume : Real = 0.0080;

        // the clickable internals: the equipment every variant carries
        part battery : ScoutParts::Battery;
        part flightController : ScoutParts::F450Kit::FlightController;
        part camera : ScoutParts::F450Kit::Camera;
    }

    part def FlyingWingTwinTip :> FlyingWingTwin {
        doc /* The twin courier with its pushers moved to the wingtips:
               the SAME shell, planform, bay, and counter-rotation --
               only the installation station moves, so the mission
               catalog crosses root against tip as a real trade axis.
               What the tip buys: each disc turns against its tip
               vortex and recovers part of the induced loss
               (tipPropBonus, DERIVED below -- the root stations earn
               no bonus).  What the tip costs, each priced here: the
               spar carries a motor pod at the tip (tipStructMass), and
               the dead-engine yaw arm becomes the whole half-span (the
               EngineOutYaw check).  The arrangement is the wingtip
               PUSHER of the NASA tip-prop tests (Patterson & Bartlett;
               Miranda & Brennan, AIAA-86-1802): the branch's whole
               installation chain -- mounts, clearance geometry, drag
               ledger -- is a pusher chain, and the vortex is recovered
               BEHIND the tip.  A tractor at the tip would hang its
               motor ahead of the swept tip's leading edge: a different
               installation family with no chain in this branch.  The
               pack slides forward on the bay rail to hold the declared
               CG against the aft-moved motor mass, so cgMac stays at
               the inherited 0.91 and every S&C check reads the same
               stations. */
        attribute propStation : String = "tip";
        // the disc rides centered on the tip, where the vortex it
        // recovers rolls up.  The inherited pod chain prices the
        // clearance at this station: past the tip the trailing-edge law
        // keeps rising up the WINGLET (the winglet rakes aft with the
        // wing), so the extrapolated rise is the honest clearance the
        // disc must still bridge -- tip pods pay pod length too.
        attribute podStation : Real = 0.5 * wingSpan;
        // the derived recovery, from the same reference disc the pod
        // chain already carries (NOMINAL; see TipPropRecovery)
        attribute tipPropBonus : Real = TipPropRecovery(
            diskDiameter = propDiameterRef, span = wingSpan);

        // ----- tip structure: the spar carries the stations ------------
        // A motor pod at a wingtip is a point load the spar must carry:
        // the arm-sizing pattern (stress AND stiffness walls) prices a
        // doubler over each half-span for the tip unit's inertial load
        // at the spar chain's design load factor.  The doubler bonds
        // into the molded shell, so it rides the SHELL mass at the
        // nominal 6061 tube figures of the materials catalog -- not the
        // material trade axis.  Its tube stock is invoice noise, so the
        // shell quote stays the twin's.
        attribute tipUnitKg : Real = 0.24;      // reference X4112S-class motor + pod + mount
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
        attribute mass : Real = 1.55 + tipStructMass;

        // ----- engine-out: the price of the tip arm --------------------
        // One pusher dead at the wing-borne climb-out is the engine-out
        // fin-sizing case of conventional practice (Raymer): the live
        // station's full static thrust at the half-span arm, as a
        // yawing-moment coefficient at the slowest wing-borne point,
        // against what the winglets hold.  Checked by ScoutMissions::
        // StabilityRequirements::EngineOutYaw.
        attribute engineOutThrustN : Real = 33.0;   // reference X4112S station, full throttle
        attribute sideForceCeiling : Real = 0.8;    // winglet CLmax with full deflection (Raymer)
        attribute engineOutYawCn : Real = engineOutThrustN * podStation
            / (0.5 * 1.225 * loiterSpeed * loiterSpeed * wingArea * wingSpan);
        attribute engineOutAuthorityCn : Real =
            sideForceCeiling * wingletYawVolume;
    }
}
