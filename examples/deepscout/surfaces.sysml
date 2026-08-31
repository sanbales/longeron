// DeepScout program -- surfaces.sysml: the declared analysis surface.
//
// Phase 1 of the surfaces design (docs/design/surfaces.md): the dashboard
// is model content.  A view usage selects the content (a subject plus
// analysis and verification cases) and names each panel's presentation
// with a LongeronSurfaces rendering; longeron.analysis.surfaces derives
// the composed widget from this declaration.  The proof of the idea is
// polymorphism: the ONE declaration below serves the QuadCopter and the
// HexaCopter (any MultiRotor), and the sizing case -- whose subject is
// the fleet's continuous sizing context, not a rotorcraft -- renders as
// honest absence instead of pretending to apply.
package ScoutSurfaces {
    doc /* The DeepScout analysis surface, declared as model content.
           Cases carry the what-ifs and the requirement checks; the view
           usage composes them into panels; slider bounds are mined from
           the model's own constraints; results reach verdict panels only
           through the explicit bindings on installationCheck. */

    private import Views::*;
    private import VerificationCases::*;
    private import AnalysisTooling::*;
    private import LongeronSurfaces::*;
    private import DeepScout::*;
    private import ScoutSizing::*;

    // ----- the what-if cases ----------------------------------------------

    analysis def CameraWhatIf {
        doc /* Re-measure camera occlusion as the boresight moves.  The in
               parameters become the surface's sliders; their bounds are
               this objective's assume constraints (the authoring idiom
               for bounds the subject itself does not state).  The
               engine named by @ToolExecution re-runs the CAD-native
               occlusion measure on every move. */
        subject drone : MultiRotor;
        in attribute elevation : Real = drone.camera.elevation;
        in attribute azimuth : Real = drone.camera.azimuth;
        out attribute discOverlapVolume : Real;   // measured beside the cone: prop-disc overlap
        objective {
            assume constraint elevationRange {
                elevation >= -90.0 and elevation <= 90.0 }
            assume constraint azimuthRange {
                azimuth >= -180.0 and azimuth <= 180.0 }
        }
        @ToolExecution { toolName = "longeron.analysis.geometry";
                         uri = "occlusion_report"; }
        return occludedFraction : Real;
    }

    analysis def LoiterWhatIf {
        doc /* Trade loiter speed against time on station.  The slider's
               bounds are the subject's own aboveStall / belowCruise
               constraints -- the model states 11..24 once, and the
               surface mines it.  Applies to the ISR sizing context
               only: on a rotorcraft subject this panel is honestly
               absent. */
        subject uav : IsrPrime;
        in attribute loiterSpeed : Real = uav.loiterSpeed;
        @ToolExecution { toolName = "longeron.analysis.mdao";
                         uri = "build_problem"; }
        return stationMinutes : Real = uav.stationMinutes;
    }

    // ----- the requirement check ------------------------------------------

    verification def InstallationCheck {
        doc /* The geometric installation envelope, as a verdict panel:
               verify the installation requirement (clearView +
               propClearance) for the craft under study.  The measured
               channels below are unvalued here; a usage binds them to
               an analysis case's results -- the explicit-only coupling
               spelling of the surfaces design. */
        subject drone : MultiRotor;
        objective { verify installation; }
        @VerificationMethod { kind = VerificationMethodKind::analyze; }
        attribute occludedFraction : Real;
        attribute discOverlapVolume : Real;
    }

    // ----- the case usages (the surface's content) --------------------------

    analysis cameraWhatIf : CameraWhatIf;

    verification installationCheck : InstallationCheck {
        // the ONE coupling spelling: explicit result bindings.  The camera
        // what-if's measured occlusion and disc overlap feed the verdict
        // panel; without a binding a measured channel stays honestly
        // unmeasured, and the case's results land in the wiring map's
        // unbound-result diagnostic.
        attribute :>> occludedFraction = cameraWhatIf.occludedFraction;
        attribute :>> discOverlapVolume = cameraWhatIf.discOverlapVolume;
    }

    analysis loiterWhatIf : LoiterWhatIf;

    // ----- the surface -------------------------------------------------------

    view def ScoutSurface {
        doc /* The two-subject proof surface: one what-if card, one
               verdict panel, one honestly absent sizing case -- derived
               for any craft the cases admit. */
    }

    view scoutSurface : ScoutSurface {
        expose Rotorcraft::QuadCopter;    // the home subject

        view cameraPane {
            expose ScoutSurfaces::cameraWhatIf;
            render asWhatIfCard;
        }
        view installationPane {
            expose ScoutSurfaces::installationCheck;
            render asVerdictCards;
        }
        view loiterPane {
            expose ScoutSurfaces::loiterWhatIf;
            render asWhatIfCard;
        }
    }
}
