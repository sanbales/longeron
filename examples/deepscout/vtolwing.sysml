// DeepScout program -- vtolwing.sysml: the winged VTOL branch.
//
// The fleet's winged airframes: a cruciform tail-sitter that hovers on
// its wingtip props and cruises wing-borne, and a rail-launched
// interceptor that never hovers at all.  Sibling specializations of the
// same abstract Aircraft as the multirotor branch -- a future winged
// concept adds an entry here without touching any other file.
package WingedVtol {
    doc /* The winged branch of the DeepScout program.  Both airframes
           are fictional shells over real parts, and both earn their
           drag numbers from the wetted-area buildup of
           DeepScout::Aerodynamics: the big wing that buys the loiter
           also pays for its skin, and the dart's slender body undercuts
           everything else in the catalog. */

    private import DeepScout::*;
    private import DeepScout::Aerodynamics::*;

    part def VtolWing :> Airframe {
        // fuselage + BOTH cruciform wing pairs + four wingtip pods: the
        // big wing that buys the loiter also pays for its skin here.
        // A cruciform tail-sitter: one long wing pair, one shorter pair,
        // a wingtip prop on each of the four tips with thrust along the
        // chords/body axis -- it hovers nose-up on its props and pitches
        // over to cruise wing-borne.
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
        attribute mass : Real = 1.90;   attribute cost : Real = 950.0;
        attribute oswald : Real = 0.82;   attribute tipPropBonus : Real = 1.28;
        attribute loiterSpeed : Real = 15.0;
        attribute cruiseSpeed : Real = 21.0;
        attribute motorCount : Integer = 4;
        attribute diskAreaFactor : Real = 3.3;  // 2 main + 2 smaller tips
        attribute hoverThrustFactor : Real = 1.35;  // wing-assisted climb-out
        attribute climbDrawFraction : Real = 0.7;
        attribute payloadCapacity : Real = 5.5;
        attribute hoverOpsSec : Real = 120.0;
        attribute armCount : Integer = 0;      // rotors ride the wingtips
        attribute sparRadius : Real = 0.012;   // fits the 12% root section
        attribute designGrossKg : Real = 6.0;  // big pack + heavy payload
    }

    part def DartInterceptor :> Airframe {
        // slender lathed body + thin wing + cruciform fins, all skin.
        // Rail-launched (hoverThrustFactor 0: no hover requirement, no
        // hover budget); the dash IS the sustained draw.
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
        attribute mass : Real = 1.08;   attribute cost : Real = 680.0;
        attribute oswald : Real = 0.72;   attribute tipPropBonus : Real = 1.0;
        attribute loiterSpeed : Real = 24.0;
        attribute cruiseSpeed : Real = 30.0;
        attribute motorCount : Integer = 1;   // single pusher
        attribute diskAreaFactor : Real = 1.0;
        attribute hoverThrustFactor : Real = 0.0;  // rail-launched
        attribute climbDrawFraction : Real = 1.0;  // the dash IS the sustained draw
        attribute payloadCapacity : Real = 0.6;
        attribute hoverOpsSec : Real = 0.0;
        attribute armCount : Integer = 0;      // no rotor arms
        attribute sparRadius : Real = 0.008;   // thin 9% section
        attribute designGrossKg : Real = 2.2;  // launch mass + margin
    }
}
