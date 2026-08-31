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
    private import DeepScout::StabilityControl::*;

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
        attribute podLength : Real = 0.09;       // m, pusher motor pod
        attribute podDiameter : Real = 0.05;     // m
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
                                            diameter = podDiameter)));
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
        // the derived S&C figures the requirement family checks
        attribute rootChord : Real = 2.0 * wingChord / (1.0 + taper);
        attribute mac : Real =
            MeanAeroChord(rootChord = rootChord, taper = taper);
        attribute staticMargin : Real = StaticMargin(
            rootChord = rootChord, taper = taper, span = wingSpan,
            sweepDeg = sweepDeg, cgMac = cgMac);
        attribute elevonPitchVolume : Real = ElevonPitchVolume(
            rootChord = rootChord, taper = taper, span = wingSpan,
            sweepDeg = sweepDeg, cgMac = cgMac,
            spanFrac = elevonSpanFrac, chordFrac = elevonChordFrac);
        attribute elevonRollVolume : Real = ElevonRollVolume(
            span = wingSpan, spanFrac = elevonSpanFrac,
            chordFrac = elevonChordFrac);
        attribute wingletYawVolume : Real = WingletYawVolume(
            wingletArea = wingletArea, rootChord = rootChord,
            taper = taper, span = wingSpan, sweepDeg = sweepDeg,
            cgMac = cgMac, wingArea = wingArea);
    }

    part def FlyingWingSingle :> FlyingWing {
        doc /* The single-pusher ISR wing: one motor station on the
               trailing edge at the root.  Reference pairing from the
               heavy catalog: a SunnySky X4112S-class pusher swinging
               an APC 11x5.5E (the mission studies cross it with every
               motor/prop/pack mix and let the constraints decide).
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
        // the pack rides the aft rail of the root bay: the CG lands at
        // 0.82 MAC aft of the root leading edge, 0.088 MAC ahead of
        // this planform's neutral point (0.908 MAC) -- inside the
        // tailless static-margin band
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
    }
}
