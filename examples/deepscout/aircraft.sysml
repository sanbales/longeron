// DeepScout program -- aircraft.sysml: the generic aircraft concepts.
//
// The open-closed root of the program: one abstract Aircraft, the
// component-family Airframe def the fleet branches specialize, the
// shared physics chain (discipline packages Aerodynamics / Propulsion /
// Structures / Performance), the abstract MultiRotor with its bench-
// calibrated build physics, and the program-level requirement defs and
// usages.  A future concept (a tilt-rotor, say) adds a sibling branch
// FILE without touching this one.
package DeepScout {
    doc /* The DeepScout UAV program root.  Two branches specialize the
           abstract Aircraft: the MultiRotor build family
           (multirotor.sysml -- one bird you build, at bench fidelity)
           and the fleet airframes (multirotor.sysml + vtolwing.sysml --
           the airframe families the three missions trade).  All physics
           lives in calc defs the interpreter evaluates directly, and
           the calc defs are organized into DISCIPLINE packages
           (Aerodynamics, Propulsion, Structures, Performance) -- the
           model's own structure is what groups the generated OpenMDAO
           problem into the classic discipline blocks of an N2
           diagram. */

    private import ScoutParts::F450Kit::*;
    private import Aerodynamics::*;
    private import Propulsion::*;
    private import Structures::*;
    private import Performance::*;

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

    // ----- the program root --------------------------------------------------

    abstract part def Aircraft {
        doc /* The root of every DeepScout air vehicle.  The MultiRotor
               build family and the fleet Airframe families are sibling
               specializations of this one abstraction, so program-wide
               views and requirement defs can name a single subject
               type.  Deliberately attribute-free: each branch owns its
               own mass, cost, and performance chains. */
    }

    part def Airframe :> Aircraft {
        doc /* The fleet's airframe-shell family: the sizing knobs every
               mission study reads.  Concrete airframes (the multirotor
               rings of the Rotorcraft branch, the winged shapes of the
               WingedVtol branch) specialize this def; the MissionUAV
               assembly (missions.sysml) equips a selected airframe with
               motors, props, a pack, and structure. */
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
        // the commanded-tilt translation cap of the bench family
        // (MultiRotor.maxOperationalTilt), stated on the fleet shells the
        // missions dash: rotor-borne craft translate by tilting, so their
        // dash may never outrun MaxCruiseSpeed at this tilt.  Only the
        // rotor-borne shells value it; the wing-borne dash rides the gust
        // placard instead and never reads it.
        attribute maxTiltDeg : Real;        // deg, rotor-borne dash tilt cap
        attribute climbDrawFraction : Real; // sustained climb-out draw / full power
        attribute payloadCapacity : Real;   // kg
        attribute hoverOpsSec : Real;       // hover budget per sortie, s
        attribute fuselageLength : Real;    // m (geometry)
        attribute armCount : Integer;       // cantilever rotor arms to size
        attribute sparRadius : Real;        // m, wing-spar tube radius
        attribute designGrossKg : Real;     // spar design gross mass (0 = no wing)

        // ----- the payload bay -------------------------------------------
        // Every airframe declares ONE payload bay: a shape (the closed
        // vocabulary of Packaging -- "box" slung under a rotor hub,
        // "hull" inside a lathed fuselage, "ogive" blended at a flying
        // wing's root), its envelope dimensions, and the packaging
        // honesty knob: internal structure, wiring, and access hardware
        // impede the fluid volume, so a mission may plan on only
        // usableVolumeFraction of the gross envelope (a NOMINAL
        // packaging factor, ~0.6 for a framed hull to ~0.75 for an open
        // box).  equipmentBayFactor states WHO shares the bay: 1 where
        // the pack and the avionics stow inside it (every skinned
        // airframe), 0 where they ride their own hub stack (the open
        // multirotor frames).  The missions' bayFit constraint reads
        // usableVolume against each mix's stowage demand.
        attribute bayShape : String;        // Packaging vocabulary: box | hull | ogive
        attribute bayLength : Real;         // m, envelope length
        attribute bayWidth : Real;          // m, envelope width (revolved: diameter)
        attribute bayHeight : Real;         // m, envelope height (revolved: diameter)
        attribute grossVolume : Real;       // m^3, from the declared dimensions
        attribute usableVolumeFraction : Real;   // packaging factor, nominal
        attribute usableVolume : Real = grossVolume * usableVolumeFraction;
        attribute equipmentBayFactor : Real;     // 1 = pack + avionics stow in the bay
    }

    // ----- discipline packages ----------------------------------------------
    // The physics calc defs live in one package per discipline.  This is
    // not cosmetic: longeron.analysis.mdao reads an attribute's calc
    // invocations and groups the generated OpenMDAO components by the
    // owning package, so the N2 diagram shows Aerodynamics / Propulsion /
    // Structures / Performance blocks because the MODEL says so.

    package Packaging {
        doc /* The volume ledger: how a declared bay envelope becomes
               cubic metres.  A BOX bay is its rectangular envelope; a
               revolved bay (a lathed HULL or a blended OGIVE pod) is
               its enclosing cylinder times a prismatic coefficient --
               the standard slender-body volume convention (~0.55 for a
               teardrop/ogive lathe; a fuller mid-body declares its own
               higher figure).  Gross envelope only: the packaging
               honesty (internal structure impeding the fluid volume)
               lives in the airframe's usableVolumeFraction. */

        calc def BoxVolume {
            doc /* A rectangular bay envelope. */
            in length : Real;
            in width : Real;
            in height : Real;
            return : Real = length * width * height;
        }

        calc def RevolvedVolume {
            doc /* A body-of-revolution bay envelope: enclosing-cylinder
                   volume times the prismatic coefficient (nose and tail
                   taper give the volume back). */
            in length : Real;
            in diameter : Real;
            in prismaticCoeff : Real = 0.55;
            return : Real = prismaticCoeff * pi * diameter * diameter / 4.0
                * length;
        }
    }

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

        calc def TipPropRecovery {
            doc /* Span-efficiency uplift of a wingtip-mounted propeller:
                   a disc turning against the tip vortex recovers part of
                   the induced loss, and the recovered share grows with
                   the disc-to-span ratio (Snyder & Zumwalt, J. Aircraft
                   6(5) 1969; Miranda & Brennan, AIAA-86-1802; the NASA
                   wingtip pusher test, Patterson & Bartlett).  The
                   linear slope is a NOMINAL teaching value: at the
                   catalog's reference disc it puts the uplift near 1.21,
                   inside the 1.1..1.28 family conceptual practice
                   quotes.  Multiplies the Oswald factor (spanEff in
                   CruisePower); root- and mid-span stations earn no
                   uplift. */
            in diskDiameter : Real;     // m, the tip station's disc
            in span : Real;             // m
            in recoveryPerDiskSpan : Real = 2.0;   // NOMINAL slope
            return : Real = 1.0 + recoveryPerDiskSpan * diskDiameter / span;
        }
    }

    package Structures {
        doc /* Load-based sizing.  Rotor arms and wing spars are round
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
        doc /* Fleet mission performance: what the sized, powered
               aircraft is worth in mission units -- top speed, time on
               station. */

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

        calc def GustPlacardSpeed {
            doc /* FAR 23.341-style alleviated sharp-edged gust placard:
                   the speed at which the gust load reaches the DESIGN
                   load factor.  n(V) = 1 + Kg rho U V a / (2 W/S),
                   solved for n = nDesign (Raymer ch. 14; FAR 23.341;
                   Pratt alleviation Kg = 0.88 mu / (5.3 + mu) with
                   mu = 2 (W/S) / (rho c a g)).  nDesign = 2.5 is the
                   same design point the spar chain cites, ON PURPOSE
                   material-independent: carbon bending headroom must
                   not buy past a placard flutter would never honor.
                   gustU = 2.0 m/s is a light-turbulence dash gust
                   (MIL-HDBK-1797 light class; NOMINAL -- at the 7.6 m/s
                   FAR-23 rough-air figure nothing in the catalog
                   catches the crossing target). */
            in wingLoading : Real;          // N/m^2 at mission mass
            in liftSlope : Real;            // 2 pi AR / (AR + 2), per rad
            in gustAlleviation : Real;      // Kg, Pratt
            in nDesign : Real = 2.5;        // the spar chain's design point
            in gustU : Real = 2.0;          // m/s, light-gust dash placard
            return : Real = (nDesign - 1.0) * 2.0 * wingLoading
                / (gustAlleviation * 1.225 * gustU * liftSlope);
        }
    }

    package StabilityControl {
        doc /* Classical closed-form stability-and-control proxies for
               wing-borne airframes: the mean aerodynamic chord and its
               spanwise station, the swept-wing neutral point, the
               static margin, and the volume coefficients of elevons
               and winglets.  Every formula is the standard
               conceptual-design estimate (Raymer, 'Aircraft Design: A
               Conceptual Approach'; Nickel & Wohlfahrt, 'Tailless
               Aircraft in Theory and Practice') at NOMINAL teaching
               fidelity: enough to CHECK a declared planform, and no
               substitute for computed stability derivatives -- the
               loft framework's derivative fidelity re-verifies the
               same requirements later.  Conventions, used by every
               calc here: chordwise stations are measured AFT of the
               ROOT-CHORD LEADING EDGE, sweep is the QUARTER-CHORD
               sweep in degrees, and taper is the tip/root chord
               ratio. */

        calc def MeanAeroChord {
            doc /* Mean aerodynamic chord of a linearly tapered panel:
                   MAC = (2/3) c_root (1 + t + t^2) / (1 + t) with
                   t = taper (Raymer's planform relation). */
            in rootChord : Real;
            in taper : Real;
            return : Real = 2.0 / 3.0 * rootChord
                * (1.0 + taper + taper * taper) / (1.0 + taper);
        }

        calc def MacSpanStation {
            doc /* Spanwise station of the MAC on a linearly tapered
                   panel, from the centerline: y = (b/6)(1 + 2t)/(1 + t)
                   (Raymer). */
            in span : Real;
            in taper : Real;
            return : Real = span / 6.0
                * (1.0 + 2.0 * taper) / (1.0 + taper);
        }

        calc def LocalChord {
            doc /* Chord at spanwise station y of a linearly tapered
                   panel: c(y) = c_root (1 - (1 - t) y / (b/2)). */
            in rootChord : Real;
            in taper : Real;
            in span : Real;
            in y : Real;
            return : Real = rootChord
                * (1.0 - (1.0 - taper) * 2.0 * y / span);
        }

        calc def QuarterChordAft {
            doc /* The quarter-chord line at spanwise station y, aft of
                   the root-chord leading edge: x = 0.25 c_root +
                   y tan(sweep).  On a straight-tapered wing every
                   local quarter-chord point lies on this one straight
                   line -- the sweep reference line of the whole
                   package. */
            in rootChord : Real;
            in sweepDeg : Real;      // quarter-chord sweep, deg aft
            in y : Real;
            return : Real = 0.25 * rootChord
                + y * tan(sweepDeg * pi / 180.0);
        }

        calc def LeadingEdgeAft {
            doc /* The leading edge at spanwise station y, aft of the
                   root-chord leading edge: the quarter-chord line less
                   a quarter of the local chord.  On a straight-tapered
                   panel this is a straight line through 0 at the
                   root. */
            in rootChord : Real;
            in taper : Real;
            in span : Real;
            in sweepDeg : Real;
            in y : Real;
            return : Real = QuarterChordAft(rootChord = rootChord,
                    sweepDeg = sweepDeg, y = y)
                - 0.25 * LocalChord(rootChord = rootChord, taper = taper,
                    span = span, y = y);
        }

        calc def TrailingEdgeAft {
            doc /* The trailing edge at spanwise station y, aft of the
                   root-chord leading edge: the quarter-chord line plus
                   three quarters of the local chord.  On an aft-swept
                   tapered wing this line slopes AFT going outboard
                   whenever tan(sweep) exceeds the taper's forward pull
                   -- the slope a trailing-edge pusher installation
                   must clear (see the FlyingWings pod chain). */
            in rootChord : Real;
            in taper : Real;
            in span : Real;
            in sweepDeg : Real;
            in y : Real;
            return : Real = QuarterChordAft(rootChord = rootChord,
                    sweepDeg = sweepDeg, y = y)
                + 0.75 * LocalChord(rootChord = rootChord, taper = taper,
                    span = span, y = y);
        }

        calc def AreaWeighted {
            doc /* Raymer's multi-panel composition kernel: the
                   area-weighted mean of one planform figure over two
                   panels.  Feed it panel MACs for the composite MAC,
                   or panel aerodynamic-centre stations for the
                   composite neutral point (Raymer's multi-panel MAC
                   method).  Panel areas only weight the mean, so
                   one-side areas compose exactly like full-planform
                   areas. */
            in areaA : Real;
            in valueA : Real;
            in areaB : Real;
            in valueB : Real;
            return : Real = (areaA * valueA + areaB * valueB)
                / (areaA + areaB);
        }

        calc def NeutralPointAft {
            doc /* Wing-alone neutral point of a swept tapered wing, aft
                   of the root-chord leading edge: the quarter-chord
                   point of the MAC, i.e. the quarter-chord line
                   evaluated at the MAC's spanwise station -- 0.25
                   c_root plus the classic y_mac tan(sweep) term
                   (Raymer).  First order, sweep does NOT move the
                   neutral point as a fraction of the MAC (~0.25 MAC);
                   it moves the MAC itself aft of the root bay, and
                   that absolute shift is what a tailless design
                   spends to put its bay-loaded CG AHEAD of the
                   neutral point (Nickel & Wohlfahrt).  A CRANKED
                   planform composes this per panel instead:
                   AreaWeighted over the panels' own quarter-chord-of-
                   MAC stations (the FlyingWingSingle's composite). */
            in rootChord : Real;
            in taper : Real;
            in span : Real;
            in sweepDeg : Real;
            return : Real = QuarterChordAft(rootChord = rootChord,
                sweepDeg = sweepDeg,
                y = MacSpanStation(span = span, taper = taper));
        }

        calc def StaticMargin {
            doc /* Static margin in MAC units: (x_np - x_cg) / MAC,
                   both stations in metres aft of the root-chord
                   leading edge.  Positive means the CG rides ahead of
                   the neutral point: statically stable in pitch.
                   Taking the composed stations as inputs (instead of
                   recomputing them from one trapezoid) lets the same
                   margin serve the single-panel twin and the cranked
                   single's multi-panel composition. */
            in neutralPointAft : Real;   // m aft of the root LE
            in mac : Real;               // m, the planform's MAC
            in cgAft : Real;             // m aft of the root LE
            return : Real = (neutralPointAft - cgAft) / mac;
        }

        calc def ControlArm {
            doc /* Pitch moment arm of a trailing-edge surface at
                   spanwise station y: the local trailing edge less the
                   CG station, both in metres aft of the root-chord
                   leading edge.  The same sweep that buys the static
                   margin carries the outboard trailing edge aft --
                   sweep pays a tailless elevon's arm too. */
            in rootChord : Real;
            in taper : Real;
            in span : Real;
            in sweepDeg : Real;
            in cgAft : Real;         // m aft of the root LE
            in y : Real;
            return : Real = TrailingEdgeAft(rootChord = rootChord,
                    taper = taper, span = span, sweepDeg = sweepDeg,
                    y = y)
                - cgAft;
        }

        calc def ElevonPitchVolume {
            doc /* Elevon pitch-control volume coefficient: S_e l_e /
                   (S MAC), the tail-volume analog for the elevon band
                   (Raymer's volume-coefficient sizing).  The band runs
                   the OUTER spanFrac of each panel at chordFrac of the
                   local chord; the NOMINAL band proxy prices its area
                   at chordFrac x spanFrac x S, so the area ratio
                   cancels S and the coefficient reduces to chordFrac x
                   spanFrac x arm / MAC with the arm taken at the
                   band's mid station.  The CG station and the
                   normalizing MAC come in composed (cgAft, mac), so a
                   cranked planform's composite figures price the same
                   band. */
            in rootChord : Real;
            in taper : Real;
            in span : Real;
            in sweepDeg : Real;
            in cgAft : Real;         // m aft of the root LE
            in mac : Real;           // m, the planform's MAC
            in spanFrac : Real;      // band span / half-span, tip-anchored
            in chordFrac : Real;     // elevon chord / local chord
            return : Real = chordFrac * spanFrac
                * ControlArm(rootChord = rootChord, taper = taper,
                    span = span, sweepDeg = sweepDeg, cgAft = cgAft,
                    y = (1.0 - 0.5 * spanFrac) * 0.5 * span)
                / mac;
        }

        calc def ElevonRollVolume {
            doc /* Elevon roll-control volume coefficient: S_e y_e /
                   (S b), the aileron-volume analog (Raymer).  Under
                   the same band proxy as ElevonPitchVolume the area
                   ratio is chordFrac x spanFrac and the arm is the
                   band's mid station over the span. */
            in span : Real;
            in spanFrac : Real;
            in chordFrac : Real;
            return : Real = chordFrac * spanFrac
                * ((1.0 - 0.5 * spanFrac) * 0.5 * span) / span;
        }

        calc def WingletYawVolume {
            doc /* Winglet yaw volume coefficient: S_v l_v / (S b) --
                   the vertical-tail volume coefficient of conventional
                   practice (Raymer) with S_v both winglets and l_v the
                   arm from the CG to the swept tip's quarter-chord,
                   where the winglets ride.  The CG station comes in
                   composed (cgAft, metres aft of the root LE), the
                   same convention as ControlArm.  Winglet-stabilized
                   tailless aircraft fly on far smaller volumes than
                   tailed airframes (Nickel & Wohlfahrt): a floor
                   checked against this calc must be a tailless
                   figure, not a tailed one. */
            in wingletArea : Real;   // m^2, EACH of the two winglets
            in rootChord : Real;
            in taper : Real;
            in span : Real;
            in sweepDeg : Real;
            in cgAft : Real;         // m aft of the root LE
            in wingArea : Real;
            return : Real = 2.0 * wingletArea
                * (QuarterChordAft(rootChord = rootChord,
                       sweepDeg = sweepDeg, y = 0.5 * span)
                   - cgAft)
                / (wingArea * span);
        }
    }

    // ----- the bench-calibrated build chain ----------------------------------
    // The MultiRotor family's physics, flat in the program root beside the
    // abstract def whose attributes call them.  The attitude chain: a
    // multirotor holds altitude with its thrust vector tilted by theta:
    //   vertical    T cos(theta) = m g          (altitude hold)
    //   horizontal  T sin(theta) = 0.5 rho CdA v^2   (parasite drag)
    // so theta_max = arccos(m g / T) at the usable thrust T, and the
    // drag balance gives tan(theta) = 0.5 rho CdA v^2 / (m g) -- invert
    // for the fastest level cruise a commanded tilt sustains.  At the
    // quad's stock point (T/W ~ 2.4) the full-throttle ceiling would be
    // ~65 deg and even the continuous-thrust (59%) ceiling is ~45 deg --
    // unrealistically sporty, so the COMMANDED tilt is the min() of the
    // physics cap and the operational comfort cap, both visible as
    // MultiRotor attributes.  First-order honest: sea-level rho, rotor
    // induced effects and frame lift ignored, drag purely parasitic.
    // Stock numbers: the quad cruises at its 25-deg comfort cap ->
    // 20.0 m/s, mission time over the tutorials' 3.9 km Atlanta loop
    // ~4.2 min; the tricopter's 11-deg yaw-authority cap -> 12.4 m/s
    // and ~6.2 min, past the 6-minute budget.

    calc def PropThrust {
        doc /* Static thrust of a fixed-pitch propeller on a brushless
               motor: the standard propeller relation T = Ct * rho * n^2 *
               d^4 (momentum / blade-element theory), with rho = 1.225
               kg/m^3 sea-level air and the loaded rev rate n = 0.75 * kV
               * V / 60 rev/s (a loaded motor holds roughly three quarters
               of its unloaded kV * V speed).  Ct = 0.097 is CALIBRATED to
               the MT2213 bench table: at the stock design point (935
               rpm/V, 11.1 V, 10 in) the fit gives 8.32 N = 848 g, on the
               table's 850 g full-throttle point. */
        in kV : Real;         // rpm/V
        in voltage : Real;    // V
        in diameter : Real;   // m
        return : Real =
            0.097 * 1.225 * (0.75 * kV * voltage / 60.0) ** 2.0 * diameter ** 4.0;
    }

    calc def MotorCurrent {
        doc /* Motor current at partial thrust, constant voltage: shaft
               power follows T^1.5 (momentum theory), so I = Imax *
               (T / Tmax)^1.5.  Anchored at the bench table's full-throttle
               point, the fit reproduces the table's current column within
               a few percent: it predicts 3.3 A at 360 g, 5.5 A at 505 g,
               7.5 A at 620 g, and 9.3 A at 715 g. */
        in thrustN : Real;     // commanded thrust, N
        in maxThrustN : Real;  // full-throttle thrust, N
        in maxCurrentA : Real; // full-throttle current, A
        return : Real = maxCurrentA * pow(thrustN / maxThrustN, 1.5);
    }

    calc def HoverTime {
        doc /* Pack endurance at a constant draw, minutes.  The default
               current is the QuadCopter's computed hover draw (hoverCurrent,
               ~13.4 A = 13400 mA), rounded up. */
        in capacity : Real;             // mAh
        in current : Real = 13400.0;    // mA at hover
        return : Real = capacity / current * 60.0;   // minutes
    }

    calc def ThrustToWeight {
        in thrust : Real;
        in mass : Real;
        return : Real = thrust / (mass * 9.81);
    }

    calc def MaxTilt {
        doc /* The altitude-hold tilt ceiling, degrees: arccos(m g / T)
               at the usable (continuous) total thrust T.  The ratio is
               clamped at 1 so an overloaded airframe reads 0 deg (it
               cannot hold altitude tilted at all) instead of a domain
               error. */
        in massKg : Real;
        in thrustN : Real;      // usable TOTAL thrust, N (all rotors)
        return : Real = acos(min(1.0, massKg * 9.81 / thrustN)) * 180.0 / pi;
    }

    calc def TiltForSpeed {
        doc /* The level-cruise tilt that holds speed v, degrees:
               tan(theta) = 0.5 rho CdA v^2 / (m g). */
        in speed : Real;        // m/s
        in massKg : Real;
        in dragArea : Real;     // parasite CdA, m^2
        return : Real = atan(
            0.5 * 1.225 * dragArea * speed * speed / (massKg * 9.81)
        ) * 180.0 / pi;
    }

    calc def CruiseTilt {
        doc /* The commanded cruise tilt: the physics ceiling capped by
               the operational comfort limit. */
        in massKg : Real;
        in thrustN : Real;
        in opsCapDeg : Real;
        return : Real = min(
            MaxTilt(massKg = massKg, thrustN = thrustN), opsCapDeg
        );
    }

    calc def MaxCruiseSpeed {
        doc /* TiltForSpeed inverted at the commanded tilt: the fastest
               level cruise it sustains, v = sqrt(m g tan(theta) /
               (0.5 rho CdA)). */
        in tiltDeg : Real;
        in massKg : Real;
        in dragArea : Real;
        return : Real = sqrt(
            massKg * 9.81 * tan(tiltDeg * pi / 180.0) / (0.5 * 1.225 * dragArea)
        );
    }

    calc def MissionTime {
        doc /* Route time at the achievable per-phase speeds, minutes:
               the horizontal legs at cruiseSpeed, the climb to route
               altitude and the descent home at the operational vertical
               rates.  The distances are geometry, measured off the
               mission's waypoint legs by
               longeron.analysis.mission3d.mission_values and passed in
               (the same kernel-measures seam as the installation
               requirement). */
        in routeM : Real;               // horizontal route length, m
        in climbM : Real;               // takeoff climb, m
        in descentM : Real;             // landing descent, m
        in cruiseSpeed : Real;          // m/s
        in climbRate : Real = 2.0;      // m/s, ops climb rate
        in descentRate : Real = 1.5;    // m/s, ops descent rate
        return : Real = (routeM / cruiseSpeed + climbM / climbRate
            + descentM / descentRate) / 60.0;
    }

    // ----- the MultiRotor abstraction: the shared build-physics chain -------

    abstract part def MultiRotor :> Aircraft {
        doc /* Everything the build-family configurations share: the
               equipment bay (pack, ESC, flight controller, GPS, RC and
               telemetry links, landing gear, camera), the parasite-drag
               and attitude physics, the current budget, the electrical
               wiring, and the hover/takeoff constraints.  Concrete
               configurations (multirotor.sysml) redefine the sizing
               knobs (rotorCount, frontalArea, thrustPerRotor,
               motorMaxCurrent, totalMass) and the rotor populations --
               the redefined multiplicities ARE the architecture
               difference. */
        attribute payloadMass : Real = 0.2 [SI::kg];
        attribute rotorCount : Real;         // redefined per configuration
        // lift-equivalent rotors: rotorCount, except where a rotor works
        // in another's wake (the CoaxX8 redefines this -- its lower
        // rotors deliver only coaxEfficiency of their isolated thrust)
        attribute effectiveRotorCount : Real = rotorCount;
        attribute totalMass : Real;          // redefined per configuration, kg
        attribute maxTakeoffMass : Real = 1.5 [SI::kg];
        attribute thrustPerRotor : Real;     // redefined per configuration, N
        attribute motorMaxCurrent : Real;    // redefined per configuration, A
        attribute frontalArea : Real;        // redefined per configuration, m^2
        attribute dragArea : Real = frontalArea * 1.1;      // parasite CdA, m^2
        // wiring, straps, camera and mounts: the build allowance that no
        // single catalog part owns
        attribute harnessMass : Real = 0.05 [SI::kg];
        // the equipment bay, summed once for every configuration
        attribute bayMass : Real = battery.mass + esc.mass
            + flightController.mass + gps.mass + receiver.mass
            + telemetry.mass + landingGear.mass + harnessMass;
        // the equipment bay's ledger price, summed once (nominal street
        // prices; the camera and harness ride in a build allowance)
        attribute bayCost : Real = battery.cost + esc.cost
            + flightController.cost + gps.cost + receiver.cost
            + telemetry.cost + landingGear.cost;
        attribute totalCost : Real;          // redefined per configuration, USD
        // FC + GPS + RC receiver + telemetry: ~6 W at 11.1 V
        attribute avionicsCurrent : Real = 0.5 [SI::A];

        // ----- the continuous-thrust ceiling ----------------------------
        // Sustained flight runs partial throttle.  The autonomy stack
        // plans cruise-long collective at no more than 65% throttle --
        // gust response and climb authority must stay in hand -- and the
        // MT2213 bench table puts 65% throttle at 505 g of the 850 g
        // static point: a 0.59 thrust fraction.
        attribute sustainedThrustFraction : Real = 0.59;
        // The electrical ceilings, expressed as thrust fractions through
        // the propeller law I ~ T^1.5 (so T/Tmax = (I/Imax)^(2/3)): the
        // ESC channel rating and the pack's C-rating each cap the current
        // a motor may draw continuously.  On this build both ratios
        // exceed 1 and clamp to 1 -- the throttle cap binds, and the doc
        // on each part says which rating would bind first on a leaner
        // build.
        attribute escThrustFraction : Real =
            pow(min(1.0, esc.maxCurrentPerMotor / motorMaxCurrent), 2.0 / 3.0);
        attribute packThrustFraction : Real =
            pow(min(1.0, battery.capacity / 1000.0 * battery.cRating
                / (rotorCount * motorMaxCurrent)), 2.0 / 3.0);
        attribute continuousThrustFraction : Real = min(
            sustainedThrustFraction, min(escThrustFraction, packThrustFraction));
        attribute usableThrust : Real =
            effectiveRotorCount * thrustPerRotor * continuousThrustFraction;    // N, continuous

        // ----- motor-out tolerance --------------------------------------
        // The largest torque-balanced rotor set the mixer can still fly
        // after the WORST single motor failure, in lift-equivalent rotors
        // (redefined per configuration): a quad must also shut the failed
        // motor's opposite to keep torque balance (2 remain), a tricopter
        // keeps no balanced hovering set at all (0), a hexa flies on the
        // balanced four (4), a flat octo flies on the balanced six (6),
        // and a coax pair's survivor keeps its station (6.4
        // lift-equivalents).  FailSafeHover below tests the usable
        // thrust of that set against the weight.
        attribute failsafeRotorCount : Real;     // redefined per configuration
        attribute motorOutUsableThrust : Real =
            failsafeRotorCount * thrustPerRotor * continuousThrustFraction;    // N, continuous

        // ----- the payload envelope -------------------------------------
        // Two ceilings cap the payload, and WHICH one binds is a family
        // axis of its own: the airframe's book takeoff-weight limit, or
        // the thrust needed to keep FlightEnvelope's hover margin.
        // emptyMass backs the payload out of the mass roll-up, so every
        // ceiling below reads directly in kg of payload.
        attribute emptyMass : Real = totalMass - payloadMass;       // kg
        // FlightEnvelope's hover-margin floor lives here so the
        // requirement and the inversion below share ONE figure
        attribute hoverMarginFloor : Real = 1.8;
        // ceiling (a): the book maximum-takeoff-weight limit
        attribute mtowPayload : Real = maxTakeoffMass - emptyMass;  // kg
        // ceiling (b): FlightEnvelope inverted for payload.  The margin
        // is linear in totalMass and thrustPerRotor does not depend on
        // payload, so the inversion is exact algebra:
        //   effN * T / (m * g) >= floor  <=>
        //   payload <= effN * T / (floor * g) - emptyMass
        attribute thrustLimitPayload : Real = effectiveRotorCount
            * thrustPerRotor / (hoverMarginFloor * 9.81) - emptyMass;   // kg
        attribute maxPayload : Real =
            min(mtowPayload, thrustLimitPayload);                   // kg
        // the same inversion for FailSafeHover: the payload at which
        // motor-out hover stops holding.  Negative means the craft
        // cannot keep motor-out hover even EMPTY (the quad and the
        // tri); a value past maxPayload means every payload the
        // envelope admits survives a failure (the X8, whose 0.498 kg
        // ceiling the takeoff limit closes first -- the exact envelope
        // bound verify.prove attributes to takeoffMassLimit -- and the
        // flat octo, whose six survivors clear the whole envelope).
        attribute failsafePayload : Real =
            motorOutUsableThrust / 9.81 - emptyMass;                // kg

        // the flight controller's commanded-attitude cap: comfort and
        // controllability, far below the physics ceiling
        attribute maxOperationalTilt : Real = 25.0 [SI::'°'];
        attribute maxTilt : Real = MaxTilt(
            massKg = totalMass, thrustN = usableThrust
        );                                                   // deg, physics cap
        attribute cruiseTilt : Real = CruiseTilt(
            massKg = totalMass,
            thrustN = usableThrust,
            opsCapDeg = maxOperationalTilt
        );                                                   // deg, commanded
        // the headline performance number is computed per configuration
        // (one line off this shared chain): MaxCruiseSpeed at cruiseTilt
        attribute maxCruiseSpeed : Real;     // redefined per configuration, m/s

        // ----- the current budget ---------------------------------------
        // MotorCurrent rolls the bench table up to the airframe: total
        // draw at hover (thrust = weight) and at max cruise (thrust =
        // weight / cos(tilt)), plus the avionics rail.  The pack's
        // C-rating x capacity and the ESC board rating bound both.
        attribute hoverCurrent : Real = rotorCount * MotorCurrent(
            thrustN = totalMass * 9.81 / effectiveRotorCount,
            maxThrustN = thrustPerRotor,
            maxCurrentA = motorMaxCurrent
        ) + avionicsCurrent;                                 // A, at hover
        attribute cruiseCurrent : Real = rotorCount * MotorCurrent(
            thrustN = totalMass * 9.81
                / cos(cruiseTilt * pi / 180.0) / effectiveRotorCount,
            maxThrustN = thrustPerRotor,
            maxCurrentA = motorMaxCurrent
        ) + avionicsCurrent;                                 // A, at max cruise
        attribute packMaxCurrent : Real =
            battery.capacity / 1000.0 * battery.cRating;     // A, continuous
        // pack endurance at the hover draw: the family's efficiency axis
        attribute hoverMinutes : Real = HoverTime(
            capacity = battery.capacity, current = hoverCurrent * 1000.0);

        // ----- cruise endurance and range -------------------------------
        // Sortie practice holds a landing reserve: the flight plan may
        // spend only part of the pack, and the rest stays in hand for
        // the approach, the landing, and LiPo health.  0.2 is a nominal
        // planning figure, not a measured one.
        attribute reserveFraction : Real = 0.2;
        attribute cruiseMinutes : Real = HoverTime(
            capacity = battery.capacity * (1.0 - reserveFraction),
            current = cruiseCurrent * 1000.0);                   // min
        // still-air range at max cruise, km: speed times the reserved
        // pack's cruise endurance.  Both factors move with payloadMass:
        // speed rises slowly with mass at the capped tilt, the draw
        // rises faster, so range falls as the payload grows -- the
        // payload-range diagram of tutorial T4.
        attribute cruiseRange : Real =
            maxCruiseSpeed * cruiseMinutes * 60.0 / 1000.0;      // km
        // the carrying-work figure, in the fleet's kg-km convention.
        // the missions' payloadRangeKgKm prices delivery RADIUS (out
        // and back); this one prices one-way still-air range -- same
        // units, compare with care.
        attribute payloadRangeKgKm : Real = payloadMass * cruiseRange;

        part chassis : Frame;
        part battery : Battery;
        part esc : SpeedController;
        part flightController : FlightController;
        part gps : GpsModule;
        part receiver : Receiver;
        part telemetry : TelemetryRadio;
        part landingGear : LandingGear;
        part propellers : Propeller[*];      // redefined per configuration
        part camera : Camera;

        // ----- electrical & control wiring -----------------------------
        // the pack's main lead feeds the ESC's DC bus...
        connection powerHarness connect battery to esc;
        flow dcBus from battery.voltage to esc.busVoltage;
        // ...and the FC commands every drive channel (DShot signals)
        connection controlLink connect flightController to esc;

        assert constraint takeoffMassLimit { totalMass <= maxTakeoffMass }
        assert constraint canHover {
            effectiveRotorCount * thrustPerRotor > totalMass * 9.81
        }
        // the current budget holds at hover and at max cruise: the pack's
        // continuous discharge clears both draws, and the ESC board
        // rating clears the cruise draw (stock quad: 13.4 A hover /
        // 15.4 A cruise against 182 A pack and 160 A ESC)
        assert constraint hoverCurrentBudget {
            hoverCurrent <= packMaxCurrent
        }
        assert constraint cruiseCurrentBudget {
            cruiseCurrent <= packMaxCurrent
        }
        assert constraint escCurrentBudget {
            cruiseCurrent <= esc.maxCurrent
        }
    }

    enum def FlightMode { manual; altitudeHold; autonomous; }

    // ----- program requirements -----------------------------------------------

    requirement def FlightEnvelope {
        doc /* The drone shall hover with a comfortable thrust margin --
               any configuration: the subject is the abstract airframe,
               and effectiveRotorCount scales the per-rotor thrust (so a
               coax pair's wake-running lower rotor counts at its
               delivered thrust, not its catalog thrust). */
        subject drone : MultiRotor;
        assume constraint { drone.totalMass > 0.0 }
        require constraint hoverMargin {
            ThrustToWeight(
                thrust = drone.effectiveRotorCount * drone.thrustPerRotor,
                mass = drone.totalMass
            ) >= drone.hoverMarginFloor
        }
    }

    requirement def FailSafeHover {
        doc /* Motor-out tolerance: the craft shall keep hovering after
               any single motor failure.  The measure is the continuous
               usable thrust of the largest torque-balanced rotor set
               that survives the worst-case failure (failsafeRotorCount
               -- a coax pair loses one member, a flat quad also gives up
               the failed motor's opposite), tested against the weight.
               The quad and the tricopter fail it; the hexa, the flat
               octo, and the coax X8 pass -- the classic redundancy
               trade. */
        subject drone : MultiRotor;
        assume constraint { drone.totalMass > 0.0 }
        require constraint motorOutHover {
            drone.motorOutUsableThrust > drone.totalMass * 9.81
        }
    }

    requirement installation {
        doc /* The geometric installation envelope.  Both measures are
               computed kernel-side by longeron.analysis.geometry
               (camera_occlusion / disc_overlap): CAD boolean
               intersections against the same parametric solids
               to_cadquery builds (with the cad extra installed;
               a deterministic volume-quadrature estimate of the same
               measures otherwise), injected into the scoreboard as
               values= bindings for the unvalued attributes below --
               see tutorial 7.  The subject is the abstract MultiRotor
               so any configuration can be measured; the reference CAD
               build the tutorials measure is the QuadCopter's (the
               satisfy edge in multirotor.sysml). */
        subject drone : MultiRotor;
        attribute occludedFraction : Real;    // measured: airframe volume inside the view cone / cone volume
        attribute discOverlapVolume : Real;   // measured: m^3 of prop-disc overlap with other components

        requirement clearView {
            doc /* The camera's view cone -- apex at the lens, axis along
                   the boresight, half-angle fieldOfView / 2, reaching one
                   airframe bounding-box diagonal -- shall contain no part
                   of the drone's own airframe. */
            attribute weight : Real = 2.0;
            attribute utility : String = "smaller-is-better";
            attribute ramp0 : Real = 0.001;
            attribute ramp1 : Real = 0.0;
            attribute measure : Real = occludedFraction;
            attribute unit : String = "fraction";
            require constraint viewBudget { occludedFraction <= 0.0 }
        }

        requirement propClearance {
            doc /* No propeller disc shall overlap any other component
                   (zero intersection volume between each disc's thin
                   cylinder and the rest of the assembly). */
            attribute weight : Real = 1.0;
            attribute utility : String = "smaller-is-better";
            attribute ramp0 : Real = 0.00002;
            attribute ramp1 : Real = 0.0;
            attribute measure : Real = discOverlapVolume;
            attribute unit : String = "m^3";
            require constraint noOverlap { discOverlapVolume <= 0.0 }
        }
    }

    requirement mission {
        doc /* The mission-time budget.  missionMinutes is measured
               kernel-side by longeron.analysis.mission3d.mission_values:
               the demo route's waypoint legs at the model's own
               achievable speeds (MissionTime over maxCruiseSpeed at
               cruiseTilt), injected into the scoreboard as a values=
               binding for the unvalued attribute below -- see
               tutorial 7.  The subject is the abstract airframe: pass
               any configuration as the assembly to score it. */
        subject drone : MultiRotor;
        attribute missionMinutes : Real;   // measured: MissionTime over the route legs

        requirement missionTime {
            doc /* The demo sortie shall finish inside the mission-time
                   budget (battery comfort and airspace-slot discipline). */
            attribute weight : Real = 1.5;
            attribute utility : String = "smaller-is-better";
            attribute ramp0 : Real = 6.0;      // at the budget: utility 0
            attribute ramp1 : Real = 4.0;      // comfortable: utility 1
            attribute measure : Real = missionMinutes;
            attribute unit : String = "min";
            attribute budget : Real = 6.0 [SI::min];
            require constraint timeBudget { missionMinutes <= budget }
        }
    }

    // The flight-state protocol runs on the flight controller; sortie
    // battery planning leans on the endurance calc it calls.  (The
    // dependency stays anonymous: it is a statement about PlanBattery,
    // not a nameable thing of its own.)
    allocate FlightStates to FlightController;
    dependency from PlanBattery to HoverTime;

    // ----- behavior -----------------------------------------------------

    action def PlanBattery {
        in distanceKm : Real;
        in speedKmh : Real = 30.0;
        out flightMinutes : Real;
        out feasible : Boolean;

        assign flightMinutes := distanceKm / speedKmh * 60.0;
        if flightMinutes > HoverTime(capacity = 5200.0) {
            assign feasible := false;
        } else {
            assign feasible := true;
        }
    }

    state def FlightStates {
        attribute launches : Integer := 0;

        entry; then idle;

        state idle;
        transition first idle accept launch then takingOff;

        state takingOff {
            entry assign launches := launches + 1;
        }
        transition first takingOff accept airborne then flying;

        state flying;
        transition first flying accept low_battery do send "RTL" then landing;
        transition first flying accept land then landing;

        state landing;
        transition first landing accept touchdown then idle;
    }

    // ----- sortie planning (sequence-sensitive safety) -------------------

    state def SortieStates {
        doc /* The sortie-level energy protocol: a launch is only cleared
               above the 30% battery floor, each climb-out to airborne
               burns 30%, and a recharge on the ground restores the pack.
               The go-around path deliberately re-enters airborne WITHOUT
               passing the launch guard -- the kind of sequence-sensitive
               trap longeron.analysis.verify.sequences exists to catch
               (minimal sortie: launch, goAround, goAround, goAround). */
        attribute battery : Integer := 100;   // % state of charge

        entry; then idle;

        state idle;
        transition first idle accept launch if battery >= 30 then airborne;
        transition first idle accept recharge do assign battery := 100 then idle;

        state airborne {
            entry assign battery := battery - 30;   // each climb-out burns 30%
        }
        transition first airborne accept land then idle;
        // the trap: a go-around re-enters airborne past the launch guard
        transition first airborne accept goAround then airborne;
    }

    requirement def SafeSortie {
        doc /* No sortie event sequence may drive the pack below zero.
               battery is bound at check time to the live simulation
               environment (the scoreboard's measured-attribute idiom). */
        attribute battery : Integer;    // measured: the machine's live charge
        require constraint noDeepDischarge { battery >= 0 }
    }

    part goAroundSortie {
        doc /* The go-around sortie's physical binding, stated in the
               model: the Piedmont Park loop as waypoint parts
               (analysis reads lat/lon/alt off the children through
               model_waypoints) and the mission epoch as an attribute
               typed Time::Iso8601DateTime -- the standard's own ISO
               8601 form, so the model states WHEN the sortie flies
               (model_epoch reads it; see the time-seam design). */
        attribute epoch : Time::Iso8601DateTime = "2026-06-21T14:30:00Z";
        part wp0 { attribute lat : Real = 33.7813; attribute lon : Real = -84.3833;
                   attribute alt : Real = 350.0; }
        part wp1 { attribute lat : Real = 33.7885; attribute lon : Real = -84.3785;
                   attribute alt : Real = 390.0; }
        part wp2 { attribute lat : Real = 33.7900; attribute lon : Real = -84.3695;
                   attribute alt : Real = 380.0; }
        part wp3 { attribute lat : Real = 33.7838; attribute lon : Real = -84.3690;
                   attribute alt : Real = 360.0; }
        part wp4 { attribute lat : Real = 33.7770; attribute lon : Real = -84.3825;
                   attribute alt : Real = 350.0; }
    }
}
