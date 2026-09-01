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
    private import DeepScout::Packaging::*;
    private import DeepScout::Structures::*;

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
        attribute mass : Real = 1.90 + tipStructMass;
        attribute cost : Real = 950.0;   // the tip doublers' tube stock is invoice noise
        attribute oswald : Real = 0.82;
        // the wingtip stations earn their induced-drag recovery the same
        // way they cost structure: DERIVED, not quoted.  The reference
        // disc follows the flying-wing branch's convention (the heavy
        // catalog's APC 11x5.5E); the uplift applies to the MAIN pair's
        // span, the one the cruise chain reads -- the secondary pair's
        // own recovery is inside the same nominal slope.
        attribute propDiameterRef : Real = 0.2794;   // m, APC 11x5.5E disc
        attribute tipPropBonus : Real = TipPropRecovery(
            diskDiameter = propDiameterRef, span = wingSpan);
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

        // ----- tip structure: the spars carry the four stations --------
        // A motor pod at a wingtip is a point load the spar must carry:
        // the arm-sizing pattern (stress AND stiffness walls) prices a
        // doubler over each half-span for the tip unit's inertial load at
        // the spar chain's design load factor.  The doubler bonds into
        // the molded shell, so it rides the SHELL mass at the nominal
        // 6061 tube figures of the materials catalog -- not the material
        // trade axis.
        attribute tipUnitKg : Real = 0.24;      // reference X4112S-class motor + pod + mount
        attribute tipLoadN : Real = 2.5 * tipUnitKg * 9.81;
        attribute secondarySpan : Real = 0.62 * wingSpan;   // the declared 0.62-span pair
        attribute mainTipWall : Real = max(
            TubeWallForStress(momentNm = tipLoadN * 0.5 * wingSpan,
                              radius = sparRadius, yieldPa = 2.4e8),
            TubeWallForStiffness(tipLoadN = tipLoadN, length = 0.5 * wingSpan,
                                 radius = sparRadius, modulusPa = 6.9e10));
        attribute secondaryTipWall : Real = max(
            TubeWallForStress(momentNm = tipLoadN * 0.5 * secondarySpan,
                              radius = sparRadius, yieldPa = 2.4e8),
            TubeWallForStiffness(tipLoadN = tipLoadN, length = 0.5 * secondarySpan,
                                 radius = sparRadius, modulusPa = 6.9e10));
        attribute tipStructMass : Real =
            2.0 * TubeMass(radius = sparRadius, wall = mainTipWall,
                           length = 0.5 * wingSpan, density = 2700.0)
            + 2.0 * TubeMass(radius = sparRadius, wall = secondaryTipWall,
                             length = 0.5 * secondarySpan, density = 2700.0);

        // ----- engine-out: the price of the tip stations ---------------
        // One main-tip motor dead at the wing-borne climb-out is the
        // engine-out fin-sizing case of conventional practice (Raymer):
        // the live mirror station's full static thrust at the half-span
        // arm, as a yawing-moment coefficient at the slowest wing-borne
        // point, against what the yaw surfaces hold.  The cruciform has
        // no tail boom -- the vertical pair shares the wing's own
        // quarter-chord station -- so its rudder authority rides only
        // the trailing-edge band's short chordwise arm.  Checked by
        // ScoutMissions::StabilityRequirements::EngineOutYaw.
        attribute engineOutThrustN : Real = 33.0;   // reference X4112S station, full throttle
        attribute rudderArm : Real = 0.75 * wingChord;   // m, TE band aft of the shared quarter-chord
        attribute sideForceCeiling : Real = 0.8;    // fin CLmax with full deflection (Raymer)
        attribute finYawVolume : Real =
            secondaryWingArea * rudderArm / (wingArea * wingSpan);
        attribute engineOutYawCn : Real = engineOutThrustN * 0.5 * wingSpan
            / (0.5 * 1.225 * loiterSpeed * loiterSpeed * wingArea * wingSpan);
        attribute engineOutAuthorityCn : Real = sideForceCeiling * finYawVolume;

        // the payload bay IS the fuselage interior: the skin is already
        // priced in the buildup above, and the full mid-body (the lathed
        // profile holds its diameter over most of the length) earns a
        // prismatic coefficient above the slender-body default.  Pack,
        // avionics, and payload all share the hull -- the mid-size
        // parcel cradle honestly does NOT fit a 0.12 m fuselage, and
        // the winch bay (whose parcel rides the line) honestly does.
        attribute bayShape : String = "hull";
        attribute bayLength : Real = fuselageLength;
        attribute bayWidth : Real = fuselageDiameter;
        attribute bayHeight : Real = fuselageDiameter;
        attribute grossVolume : Real = RevolvedVolume(
            length = fuselageLength, diameter = fuselageDiameter,
            prismaticCoeff = 0.72);                         // 7.7 L
        attribute usableVolumeFraction : Real = 0.65;
        attribute equipmentBayFactor : Real = 1.0;

        // the clickable internals: the equipment every variant carries
        part battery : ScoutParts::Battery;
        part flightController : ScoutParts::F450Kit::FlightController;
        part camera : ScoutParts::F450Kit::Camera;
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

        // the payload bay is the slender hull's nose section: the skin
        // is already priced, the seeker and the pack share what the
        // lathe encloses, and the boat tail and motor mount impede the
        // rest -- a dash bird's bay, not a courier's
        attribute bayShape : String = "hull";
        attribute bayLength : Real = fuselageLength;
        attribute bayWidth : Real = fuselageDiameter;
        attribute bayHeight : Real = fuselageDiameter;
        attribute grossVolume : Real = RevolvedVolume(
            length = fuselageLength, diameter = fuselageDiameter);  // 6.5 L
        attribute usableVolumeFraction : Real = 0.60;
        attribute equipmentBayFactor : Real = 1.0;

        // the clickable internals: the equipment every variant carries
        part battery : ScoutParts::Battery;
        part flightController : ScoutParts::F450Kit::FlightController;
        part camera : ScoutParts::F450Kit::Camera;
    }
}
