// DeepScout program -- parts.sysml: the shared real-parts catalog.
//
// One file owns every commercial part the program builds from, in two
// part CLASSES and two spec conventions:
//
//   * the SMALL class -- F450-scale build parts (EMAX MT2213, APC
//     10x4.5MR, Tattu 3S...), spec'd at bench-sheet fidelity inside
//     the nested F450Kit package.  The MultiRotor branch composes
//     these part defs directly.
//   * the HEAVY class -- the fleet's 6S-scale propulsion (T-Motor
//     Antigravity MN4006, SunnySky X4112S, T-Motor AT4120, big props,
//     6S packs), spec'd in the family-attribute convention the trade
//     studies select over.
//
// Three shelf parts appear in BOTH conventions -- the MT2213, the APC
// 10x4.5MR, and the Tattu 3S pack.  Same physical part, two spec
// sheets: the bench sheet feeds the build family's calibrated physics,
// the catalog entry feeds the fleet's trade space.  Payload sensors,
// cargo bays, and structural tube stock close the catalog.
package ScoutParts {
    doc /* The DeepScout parts catalog: real commercial parts in two
           classes (small F450-scale, heavy 6S-scale) plus payloads,
           cargo bays, and structural materials.  Every spec below is a
           NOMINAL manufacturer figure (catalog masses, bench-table
           thrust points, C-ratings, street prices).  Where a
           manufacturer page for the exact part is fetchable, the figure
           carries an Evidence::SourceEvidence citation (URL + sha256 +
           quote -- longeron.evidence wrote and verified it; see
           docs/guides/evidence.md).  These are teaching
           examples, not engineering data: real builds vary unit to
           unit, and no number here was measured on these airframes. */

    // ----- the small class: the F450-scale build kit ---------------------
    // Bench-sheet spec convention: each part def IS one shelf part, with
    // the attributes the MultiRotor branch's calibrated physics reads.

    package F450Kit {
        doc /* The F450-class build kit: one part def per shelf part, at
               bench-sheet fidelity.  The MultiRotor branch composes
               these defs directly -- its calibrated thrust and current
               fits are anchored to the MT2213 bench table below. */

        part def Battery {
            doc /* Tattu 5200 mAh 3S1P 35C LiPo -- the classic F450-class pack.
                   capacity and cRating are the label figures; together they
                   bound the pack's continuous discharge (35 C x 5.2 Ah =
                   182 A), one input to the current budget of the MultiRotor
                   branch. */
            attribute capacity : Real = 5200.0;      // mAh (no ampere-hour unit in the vendored SI)
            attribute cRating : Real = 35.0;         // C, continuous discharge (label figure)
            attribute voltage : Real = 11.1 [SI::V]; // 3S LiPo nominal
            attribute mass : Real = 0.39 [SI::kg];
            attribute cost : Real = 45.0;            // USD, nominal street price
            // label-sheet brick dimensions (NOMINAL): the volume the
            // equipment bay must find for the pack
            attribute length : Real = 0.155 [SI::m];
            attribute width : Real = 0.047 [SI::m];
            attribute height : Real = 0.026 [SI::m];
            attribute volumeM3 : Real = length * width * height;   // ~0.19 L
        }

        part def Motor {
            doc /* EMAX MT2213-935KV, a 2212-class brushless outrunner.  kV is
                   the motor velocity constant in rpm per volt (no such unit in
                   the vendored SI).  Nominal bench table with the matched
                   10x4.5 propeller at 11.1 V (thrust / current by throttle):

                        50%   360 g    3.3 A
                        65%   505 g    5.5 A
                        75%   620 g    7.5 A
                        85%   715 g    9.3 A
                       100%   850 g   12.0 A

                   PropThrust is calibrated to the 100% point; MotorCurrent
                   reproduces the current column within a few percent. */
            attribute kV : Real = 935.0 {            // rpm/V
                @Evidence::SourceEvidence {
                    document = "https://shop.emax-usa.com/products/emx-mt-1534-emax-multicopter-motor-mt2213-with-prop1045-combo-935kv";
                    sha256 = "5d3d4f09a84de1d3b0685383f01472ab65f10ac5482f1407cde69b5177a49685";
                    quote = "at 935KV it pairs perfectly with 10x4.5 inch propellers on 3S LiPo";
                    retrieved = "2026-08-29";
                }
            }
            attribute maxCurrent : Real = 12.0 [SI::A];  // full throttle, 10x4.5 prop, 11.1 V
            attribute mass : Real = 0.055 [SI::kg];
            attribute cost : Real = 17.0;            // USD, nominal street price
        }

        part def Propeller {
            doc /* APC 10x4.5MR, the multi-rotor slow-fly workhorse; discArea
                   is the swept disc. */
            attribute diameter : Real = 0.254 [SI::m] {   // 10 in
                @Evidence::SourceEvidence {
                    document = "https://www.apcprop.com/product/10x4-5mr/";
                    sha256 = "dcb33746a711fa105695d760db95d3d9e33e4d02bea6af07a386e3f0bb496ada";
                    quote = "Propeller Diameter (in.) 10";
                    retrieved = "2026-08-29";
                }
            }
            attribute pitch : Real = 0.1143 [SI::m] {     // 4.5 in
                @Evidence::SourceEvidence {
                    document = "https://www.apcprop.com/product/10x4-5mr/";
                    sha256 = "dcb33746a711fa105695d760db95d3d9e33e4d02bea6af07a386e3f0bb496ada";
                    quote = "Pitch (inches) 4.5";
                    retrieved = "2026-08-29";
                }
            }
            attribute mass : Real = 0.015 [SI::kg] {      // 0.53 oz
                @Evidence::SourceEvidence {
                    document = "https://www.apcprop.com/product/10x4-5mr/";
                    sha256 = "dcb33746a711fa105695d760db95d3d9e33e4d02bea6af07a386e3f0bb496ada";
                    quote = "Product Weight 0.53 oz.";
                    retrieved = "2026-08-29";
                }
            }
            attribute cost : Real = 4.0;                 // USD, nominal street price
            attribute discArea : Real = pi * (diameter / 2.0) ** 2.0;   // m^2
        }

        part def Frame {
            doc /* DJI Flame Wheel F450: molded arms on plates with an
                   integrated power-distribution board.  Bare frame kit mass;
                   the equipment bay parts and the harness allowance carry
                   everything else. */
            attribute mass : Real = 0.282 [SI::kg];
            attribute cost : Real = 39.0;    // USD, nominal kit price
        }

        part def TriFrame :> Frame {
            doc /* The tricopter plate: two front arms and one long rear boom,
                   an RCExplorer-style conversion cut from the same plate
                   stock.  One arm fewer than the quad and less plate area,
                   but the boom carries the tilt-mount hardpoint.  Bare frame
                   mass, same convention as Frame. */
            attribute mass : Real = 0.24 [SI::kg];
            attribute cost : Real = 29.0;    // USD, nominal plate-stock conversion
        }

        part def HexFrame :> Frame {
            doc /* DJI Flame Wheel F550: the F450's six-arm sibling -- same
                   molded-arm construction on a wider pair of plates, arms
                   every 60 degrees.  Bare frame kit mass, same convention as
                   Frame; the 2.4 kg book takeoff-weight ceiling rides on the
                   HexaCopter configuration in the MultiRotor branch. */
            attribute mass : Real = 0.478 [SI::kg];
            attribute cost : Real = 59.0;    // USD, nominal kit price
        }

        part def OctoRing :> Frame {
            doc /* The flat-8 ring: eight arms every 45 degrees on a wider
                   custom plate pair, cut from the same plate stock as the
                   tricopter conversion.  A CUSTOM-BUILD convention, not a
                   catalog frame: real flat octocopters are heavy-lift
                   machines, and this small-class ring exists so the
                   OctoCopter configuration varies ONLY the architecture
                   against its hexa and X8 siblings.  Bare frame mass, same
                   convention as Frame; the builder's 2.6 kg structural
                   takeoff allowance rides on the OctoCopter configuration. */
            attribute mass : Real = 0.62 [SI::kg];
            attribute cost : Real = 79.0;    // USD, nominal plate-stock custom cut
        }

        part def Camera {
            doc /* The forward-looking mission camera (a small EO board camera;
                   its mass rides in the harness allowance).  Placement offsets
                   are metres from the airframe origin (the top-plate centre)
                   in the geometry frame (+x forward, +y up); azimuth yaws the
                   boresight left of +x, elevation pitches it above the
                   horizon. */
            attribute x : Real = 0.06 [SI::m];
            attribute y : Real = 0.0 [SI::m];
            attribute z : Real = 0.0 [SI::m];
            attribute azimuth : Real = 0.0 [SI::'°'];
            attribute elevation : Real = -15.0 [SI::'°'];
            attribute fieldOfView : Real = 50.0 [SI::'°'];
        }

        part def SpeedController {
            doc /* Hobbywing XRotor Micro 40A 4-in-1 BLHeli_32: one board, one
                   drive channel per rotor (the tricopter leaves the fourth
                   channel spare).  A modern 4-in-1 standing in for the classic
                   four separate 30 A ESCs of an F450 build.  Its per-channel
                   and board ratings are two of the ceilings in the MultiRotor
                   branch's current budget.  The six- and eight-rotor
                   configurations stack a second board for the extra channels;
                   their mass and cost roll-ups carry it as a literal, and the
                   single board's ratings stay the (conservative) budget
                   ceilings. */
            attribute busVoltage : Real = 11.1 [SI::V];   // pack input (rated 3-6S)
            attribute maxCurrentPerMotor : Real = 40.0 [SI::A];  // continuous, per channel
            attribute maxCurrent : Real = 160.0 [SI::A]; // continuous, all channels
            attribute mass : Real = 0.012 [SI::kg];
            attribute cost : Real = 40.0;    // USD, nominal street price
        }

        part def FlightController {
            doc /* Holybro Pixhawk 6C Mini running ArduPilot: the attitude
                   loops and the FlightStates protocol.  loopRate is the
                   ArduPilot main-loop default.  The case dimensions are
                   NOMINAL catalog-class figures: the electronics volume
                   every bay ledger accounts for. */
            attribute loopRate : Real = 400.0 [SI::Hz];
            attribute mass : Real = 0.039 [SI::kg];
            attribute cost : Real = 210.0;   // USD, nominal street price
            attribute length : Real = 0.052 [SI::m];
            attribute width : Real = 0.040 [SI::m];
            attribute height : Real = 0.023 [SI::m];
            attribute volumeM3 : Real = length * width * height;   // ~0.05 L
        }

        part def GpsModule {
            doc /* Holybro M9N GPS/compass puck on its mast. */
            attribute mass : Real = 0.032 [SI::kg];
            attribute cost : Real = 50.0;    // USD, nominal street price
        }

        part def Receiver {
            doc /* FrSky X8R RC receiver. */
            attribute mass : Real = 0.017 [SI::kg];
            attribute cost : Real = 40.0;    // USD, nominal street price
        }

        part def TelemetryRadio {
            doc /* Holybro SiK telemetry radio V3 (915 MHz, 100 mW) with
                   antenna: the ground-station link. */
            attribute mass : Real = 0.028 [SI::kg];
            attribute cost : Real = 50.0;    // USD, nominal street price
        }

        part def LandingGear {
            doc /* F450 tall landing skid set: keeps the camera and the pack
                   clear of the ground. */
            attribute mass : Real = 0.08 [SI::kg];
            attribute cost : Real = 10.0;    // USD, nominal street price
        }

        part def YawServo {
            doc /* The rear-boom tilt servo of a tricopter: yaw torque comes
                   from vectoring the tail rotor, not from rotor-pair torque
                   balance as on a quad.  An EMAX ES08MA II metal-gear micro
                   servo plus its linkage. */
            attribute mass : Real = 0.012 [SI::kg];
            attribute cost : Real = 9.0;     // USD, nominal street price
            attribute travel : Real = 20.0 [SI::'°'];    // tilt each side of vertical
        }
    }

    // ----- the fleet's component families ---------------------------------
    // Family-attribute spec convention: one part def per family, one
    // specialization per catalog entry.  The trade studies' variation
    // points (missions.sysml) select over these entries.

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
        attribute cells : Integer;          // series cell count (voltage class)
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
        attribute cells : Integer;          // series cell count (voltage class)
        attribute volumeM3 : Real;          // m^3, pack brick (label dims, nominal)
    }

    part def SensorPackage {
        attribute mass : Real;
        attribute cost : Real;
        attribute powerW : Real;
        attribute grade : Integer;          // 1 fixed EO .. 3 long-range
        attribute volumeM3 : Real;          // m^3, stowed envelope (nominal)
    }

    part def CargoBay {
        attribute bayMass : Real;           // kg, bay/box structure
        attribute bayCost : Real;
        attribute payloadKg : Real;         // parcel delivered
        // m^3 the drop hardware and its parcel demand FROM the airframe's
        // payload bay (nominal): a cradle stows frame + parcel envelope; the
        // winch stows only its mechanism -- the parcel hangs on the line
        attribute stowedVolume : Real;
    }

    // ----- heavy-class motors ----------------------------------------------
    // Three real tiers.  The Antigravity is the efficiency play (68 g,
    // big slow props, gentle power); the X4112S is the all-round lifter
    // but tops out at a 14 in prop; the AT4120 is a 2 kW fixed-wing
    // power plant whose watts no li-ion pack can feed.  maxThrust is the
    // matched-prop static figure at 6S, nominal.
    part def TMotorMn4006 :> Motor {
        doc /* T-Motor Antigravity MN4006 KV380 (nominal). */
        attribute mass : Real = 0.068;  attribute cost : Real = 96.0;
        attribute maxThrust : Real = 20.0;
        attribute maxPowerW : Real = 420.0;
        attribute efficiency : Real = 0.85;
        attribute maxPropDiameter : Real = 0.46;
        attribute cells : Integer = 6;
    }
    part def SunnySkyX4112s :> Motor {
        doc /* SunnySky X4112S KV485 (nominal). */
        attribute mass : Real = 0.183;  attribute cost : Real = 88.0;
        attribute maxThrust : Real = 33.0;
        attribute maxPowerW : Real = 800.0;
        attribute efficiency : Real = 0.83;
        attribute maxPropDiameter : Real = 0.36;   // 14 in: the 15 in lifter needs mn4006/at4120
        attribute cells : Integer = 6;
    }
    part def TMotorAt4120 :> Motor {
        doc /* T-Motor AT4120 KV250, a fixed-wing power plant (nominal). */
        attribute mass : Real = 0.320;  attribute cost : Real = 158.0;
        attribute maxThrust : Real = 45.0;
        attribute maxPowerW : Real = 2000.0;
        attribute efficiency : Real = 0.87;
        attribute maxPropDiameter : Real = 0.42;
        attribute cells : Integer = 6;
    }

    // ----- the small class, restated in the family convention --------------
    // The same MT2213 / 10x4.5MR / Tattu 3S shelf parts as F450Kit, as
    // fleet catalog entries: the CROSSING's part-class axis.  maxThrust
    // and maxPowerW restate the bench table's 100% point (850 g, 12 A
    // at 11.1 V); the 3-cell voltage class keeps the small motor off the
    // 6S packs (the cellMatch constraint in missions.sysml).
    part def EmaxMt2213 :> Motor {
        doc /* EMAX MT2213-935KV, the F450Kit bench motor as a fleet
               entry (nominal). */
        attribute mass : Real = 0.055;  attribute cost : Real = 17.0;
        attribute maxThrust : Real = 8.3;
        attribute maxPowerW : Real = 135.0;
        attribute efficiency : Real = 0.75;
        attribute maxPropDiameter : Real = 0.254;  // the 10 in bench match
        attribute cells : Integer = 3;
    }
    part def Apc10x45mr :> Propeller {
        doc /* APC 10x4.5MR, the F450Kit bench propeller as a fleet
               entry (nominal). */
        attribute mass : Real = 0.015;  attribute cost : Real = 4.0;
        attribute diameter : Real = 0.254;
        attribute cruiseEff : Real = 0.70;
    }
    part def Tattu3s5200 :> Battery {
        doc /* Tattu 5.2 Ah 3S 35C LiPo, the F450Kit bench pack as a
               fleet entry (nominal): 57.7 Wh at 182 A continuous. */
        attribute mass : Real = 0.39;   attribute cost : Real = 45.0;
        attribute energyWh : Real = 57.7;
        attribute maxPowerW : Real = 2020.0;
        attribute cells : Integer = 3;
        attribute volumeM3 : Real = 0.00019;   // 155 x 47 x 26 mm label brick
    }

    // ----- heavy-class props -----------------------------------------------
    // Real APC electrics plus a T-Motor carbon lifter.  Pitch buys
    // cruise efficiency; diameter buys disk area (cheap hover).
    part def Apc11x55e :> Propeller {
        doc /* APC 11x5.5E thin electric (nominal). */
        attribute mass : Real = 0.022;  attribute cost : Real = 6.0;
        attribute diameter : Real = 0.2794;
        attribute cruiseEff : Real = 0.82;
    }
    part def Apc13x65e :> Propeller {
        doc /* APC 13x6.5E thin electric (nominal). */
        attribute mass : Real = 0.028;  attribute cost : Real = 9.0;
        attribute diameter : Real = 0.3302;
        attribute cruiseEff : Real = 0.74;
    }
    part def TMotor15x5cf :> Propeller {
        doc /* T-Motor P15x5 carbon-fiber lifter (nominal). */
        attribute mass : Real = 0.031;  attribute cost : Real = 46.0;
        attribute diameter : Real = 0.381;
        attribute cruiseEff : Real = 0.66;
    }

    // ----- heavy-class batteries --------------------------------------------
    // The chemistry axis.  Three Tattu 6S LiPos trade energy for punch
    // (35C down to 15C as capacity grows), and the li-ion pack
    // (energy-cell 18650s, NCR18650GA class) carries ~25% more energy
    // per kilogram at a TENTH of the discharge ceiling: endurance vs
    // punch, resolved differently by each mission.  maxPowerW is
    // C-rating x capacity x nominal voltage, rounded.
    part def Tattu6s5200 :> Battery {
        doc /* Tattu 5.2 Ah 6S 35C LiPo (nominal). */
        attribute mass : Real = 0.78;   attribute cost : Real = 95.0;
        attribute energyWh : Real = 115.0;
        attribute maxPowerW : Real = 4000.0;
        attribute cells : Integer = 6;
        attribute volumeM3 : Real = 0.00048;   // 158 x 65 x 47 mm label brick
    }
    part def Tattu6s10000 :> Battery {
        doc /* Tattu 10 Ah 6S 25C LiPo (nominal). */
        attribute mass : Real = 1.32;   attribute cost : Real = 185.0;
        attribute energyWh : Real = 222.0;
        attribute maxPowerW : Real = 5550.0;
        attribute cells : Integer = 6;
        attribute volumeM3 : Real = 0.00072;   // 170 x 69 x 61 mm label brick
    }
    part def Tattu6s16000 :> Battery {
        doc /* Tattu 16 Ah 6S 15C LiPo (nominal). */
        attribute mass : Real = 1.92;   attribute cost : Real = 265.0;
        attribute energyWh : Real = 355.0;
        attribute maxPowerW : Real = 5300.0;
        attribute cells : Integer = 6;
        attribute volumeM3 : Real = 0.00104;   // 193 x 77 x 70 mm label brick
    }
    part def LiIon6s6p :> Battery {
        doc /* 6S6P li-ion pack of NCR18650GA-class energy cells
               (nominal): 447 Wh at 1.89 kg, but the 10 A cell ceiling
               caps the pack near 1.3 kW. */
        attribute mass : Real = 1.89;   attribute cost : Real = 310.0;
        attribute energyWh : Real = 447.0;
        attribute maxPowerW : Real = 1300.0;
        attribute cells : Integer = 6;
        // 36 cells in holders plus the BMS board: a boxier brick than
        // the LiPos at the same class of mass (nominal)
        attribute volumeM3 : Real = 0.00108;   // ~134 x 112 x 72 mm pack
    }

    // ----- payloads ----------------------------------------------------------
    // The ISR payload ladder, street-priced -- the optic, not the
    // airframe, dominates an ISR bird's invoice.
    part def RuncamSplit4 :> SensorPackage {
        doc /* RunCam Split 4 fixed nose camera with mount and DVR
               (nominal). */
        attribute mass : Real = 0.10;   attribute cost : Real = 85.0;
        attribute powerW : Real = 4.0;  attribute grade : Integer = 1;
        attribute volumeM3 : Real = 0.00006;   // board camera + DVR + mount
    }
    part def ZenmuseH20 :> SensorPackage {
        doc /* DJI Zenmuse H20 stabilized EO zoom gimbal (nominal). */
        attribute mass : Real = 0.68;   attribute cost : Real = 4600.0;
        attribute powerW : Real = 18.0; attribute grade : Integer = 2;
        attribute volumeM3 : Real = 0.00276;   // 150 x 115 x 160 mm gimbal ball + yoke
    }
    part def GremsyT3A7r :> SensorPackage {
        doc /* Gremsy T3V3 gimbal + Sony a7R survey camera kit
               (nominal).  The stowed envelope is the assembled gimbal
               with the camera hung: the volume figure that keeps this
               kit off every bay but the widest. */
        attribute mass : Real = 1.90;   attribute cost : Real = 6800.0;
        attribute powerW : Real = 30.0; attribute grade : Integer = 3;
        attribute volumeM3 : Real = 0.0088;    // 220 x 200 x 200 mm assembled kit
    }

    // ----- cargo bays ----------------------------------------------------------
    // Real drop hardware -- servo release cradles in two sizes and a
    // powered winch bay for the big parcels.
    part def ParcelBayS :> CargoBay {
        doc /* Gannet-style servo release + 1 kg cradle (nominal).  The
               stowed volume is the release frame plus the parcel
               envelope the cradle admits (~160 x 120 x 100 mm). */
        attribute bayMass : Real = 0.12;  attribute bayCost : Real = 90.0;
        attribute payloadKg : Real = 1.0;
        attribute stowedVolume : Real = 0.0022;
    }
    part def ParcelBayM :> CargoBay {
        doc /* Dual-servo release frame + 2.5 kg cradle (nominal).  The
               stowed volume is the frame plus the parcel envelope the
               cradle admits (~240 x 160 x 130 mm). */
        attribute bayMass : Real = 0.25;  attribute bayCost : Real = 180.0;
        attribute payloadKg : Real = 2.5;
        attribute stowedVolume : Real = 0.0055;
    }
    part def ParcelBayL :> CargoBay {
        doc /* Powered winch bay, 4 kg line rating (nominal).  Only the
               winch mechanism stows: the parcel rides the LINE beneath
               the airframe, so the heaviest lift makes the smallest
               bay demand -- the honest shape of slung cargo. */
        attribute bayMass : Real = 0.45;  attribute bayCost : Real = 320.0;
        attribute payloadKg : Real = 4.0;
        attribute stowedVolume : Real = 0.0020;
    }

    // ----- structural tube stock -------------------------------------------------
    // Aluminum is cheap and heavy, carbon buys grams (and stiffness) at
    // real money -- the arm/spar sizing turns these four numbers into
    // mission mass and cost.
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
}
