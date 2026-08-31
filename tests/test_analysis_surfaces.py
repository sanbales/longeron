"""longeron.analysis.surfaces: the declared surface, derived.

The two-subject proof (surfaces design, phase 1): the ONE declaration in
``examples/deepscout/surfaces.sysml`` derives for the QuadCopter AND the
HexaCopter through the shared abstract MultiRotor, the loiter case is
honestly absent on both, slider bounds equal the model's own constraint
bounds exactly, verdict panels track ``check_requirement``, results flow
only through the explicit bindings, and the wiring map says all of it.
Everything runs kernel-side (the house headless-widget discipline).
"""

from pathlib import Path

import pytest

import longeron
from longeron.analysis import surfaces
from longeron.analysis._expr import AnalysisError
from longeron.analysis.surfaces import (
    RANGE_FALLBACK,
    RANGE_OVERRIDDEN,
    RENDERINGS,
    surface,
)

pytest.importorskip("ipywidgets")

EXAMPLES = Path(__file__).parent.parent / "examples"

VIEW = "ScoutSurfaces::scoutSurface"


@pytest.fixture(scope="module")
def drone():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture()
def quad(drone):
    return surface(drone, VIEW)


def _panel(box, name):
    return next(p for p in box.panels if p.name == name)


MINI = """
package Mini {
    private import LongeronSurfaces::*;

    part def Thing { attribute a : Real = 1.0; }

    analysis def CaseA {
        subject s : Thing;
        in attribute x : Real = 1.0;
        return y : Real = x;
    }
    analysis def CaseB {
        subject s : Thing;
        in attribute x : Real = 2.0;
        return y : Real = x;
    }
    analysis caseA : CaseA;
    analysis caseB : CaseB;

    rendering def HouseRendering;
    rendering asCustom : HouseRendering;

    view def V;
    view v : V {
        expose Mini::Thing;
        view paneA { expose Mini::caseA; render asWhatIfCard; }
        view paneB { expose Mini::caseB; render asWhatIfCard; }
        view paneCustom { expose Mini::caseA; render asCustom; }
        view paneGlobe { expose Mini::caseA; render asMissionGlobe; }
        view paneBare { expose Mini::caseA; }
    }
}
"""


@pytest.fixture(scope="module")
def mini():
    return longeron.loads(MINI)


# ---------------------------------------------------------------------------
# the two-subject proof
# ---------------------------------------------------------------------------


class TestTwoSubjectProof:
    def test_quad_derives_the_declared_panels(self, quad):
        assert quad.subject == "Rotorcraft::QuadCopter"
        camera = _panel(quad, "cameraPane")
        installation = _panel(quad, "installationPane")
        loiter = _panel(quad, "loiterPane")
        assert not camera.absent and sorted(camera.sliders) == ["azimuth", "elevation"]
        assert not installation.absent and installation.verdict == "pass"
        assert loiter.absent

    def test_slider_ranges_equal_the_models_constraint_bounds_exactly(self, quad):
        camera = _panel(quad, "cameraPane")
        elevation = camera.sliders["elevation"]
        azimuth = camera.sliders["azimuth"]
        assert (elevation.min, elevation.max) == (-90.0, 90.0)
        assert (azimuth.min, azimuth.max) == (-180.0, 180.0)
        assert (
            camera.ranges["elevation"].source
            == "mined-from-constraint ScoutSurfaces::CameraWhatIf::elevationRange"
        )
        assert (
            camera.ranges["azimuth"].source
            == "mined-from-constraint ScoutSurfaces::CameraWhatIf::azimuthRange"
        )

    def test_slider_defaults_come_from_the_subjects_camera(self, quad):
        camera = _panel(quad, "cameraPane")
        assert camera.sliders["elevation"].value == -15.0
        assert camera.sliders["azimuth"].value == 0.0

    def test_tool_execution_names_the_engine(self, quad):
        camera = _panel(quad, "cameraPane")
        assert camera.tool == ("longeron.analysis.geometry", "occlusion_report")
        assert camera.results["occludedFraction"] == 0.0  # stock camera: clear

    def test_hexa_derives_from_the_same_declaration(self, drone):
        box = surface(drone, VIEW, subject="Rotorcraft::HexaCopter")
        assert box.subject == "Rotorcraft::HexaCopter"
        camera = _panel(box, "cameraPane")
        installation = _panel(box, "installationPane")
        assert not camera.absent and camera.results["occludedFraction"] == 0.0
        assert installation.verdict == "pass"
        assert _panel(box, "loiterPane").absent

    def test_non_fitting_case_is_honestly_absent_with_its_reason(self, quad):
        loiter = _panel(quad, "loiterPane")
        assert loiter.absent
        assert loiter.reason == "LoiterWhatIf applies to ScoutSizing::IsrPrime"
        assert any("loiterPane" in entry for entry in quad.wiring.absences)
        # absent, never silent: the panel still renders (as the absence card)
        assert "not derived for this subject" in loiter.widget.value
        assert "ScoutSizing::IsrPrime" in loiter.widget.value


# ---------------------------------------------------------------------------
# verdicts: the interpreter is the oracle
# ---------------------------------------------------------------------------


class TestVerdicts:
    def test_verdict_matches_check_requirement(self, drone, quad):
        camera = _panel(quad, "cameraPane")
        installation = _panel(quad, "installationPane")
        interp = longeron.Interpreter(drone)
        instance = interp.instantiate("Rotorcraft::QuadCopter")
        result = interp.check_requirement(
            "DeepScout::installation::clearView",
            subject=instance,
            bindings={"occludedFraction": camera.results["occludedFraction"]},
        )
        assert result.satisfied is True
        assert installation.verdict == "pass"

    def test_slider_move_flips_the_verdict_through_the_coupling(self, quad):
        camera = _panel(quad, "cameraPane")
        installation = _panel(quad, "installationPane")
        camera.sliders["azimuth"].value = 180.0
        camera.sliders["elevation"].value = -20.0  # the battery enters the cone
        assert camera.results["occludedFraction"] > 0.0
        assert installation.verdict == "fail"
        assert "FAIL" in installation.readout.value
        camera.sliders["azimuth"].value = 0.0
        camera.sliders["elevation"].value = -15.0
        assert camera.results["occludedFraction"] == 0.0
        assert installation.verdict == "pass"

    def test_unmeasured_channel_is_inconclusive_not_a_pass(self):
        # a verification case whose measured channel nothing binds must not
        # fabricate a verdict
        model = longeron.loads(
            """
            package Mini {
                private import LongeronSurfaces::*;
                part def Thing { attribute a : Real = 1.0; }
                requirement def Snug {
                    subject s : Thing;
                    attribute margin : Real;
                    require constraint tight { margin <= 0.5 }
                }
                verification def Check {
                    subject s : Thing;
                    objective { verify Snug; }
                    attribute margin : Real;
                }
                verification check : Check;
                view def V;
                view v : V {
                    expose Mini::Thing;
                    view paneCheck { expose Mini::check; render asVerdictCards; }
                }
            }
            """
        )
        box = surface(model, "Mini::v")
        check = _panel(box, "paneCheck")
        assert check.verdict == "inconclusive"
        assert "unmeasured (no binding)" in check.readout.value


# ---------------------------------------------------------------------------
# subject swap: re-derive, never patch
# ---------------------------------------------------------------------------


class TestSubjectSwap:
    def test_swap_re_derives_every_panel(self, quad):
        before = list(quad.panels)
        quad.swap("Rotorcraft::HexaCopter")
        assert quad.subject == "Rotorcraft::HexaCopter"
        assert all(a is not b for a, b in zip(before, quad.panels, strict=True))
        assert quad.wiring.subject == "Rotorcraft::HexaCopter"
        assert quad.picker.value == "Rotorcraft::HexaCopter"

    def test_sizing_subject_inverts_the_absences(self, drone):
        pytest.importorskip("openmdao")
        box = surface(drone, VIEW, subject="ScoutSizing::IsrPrime")
        camera = _panel(box, "cameraPane")
        installation = _panel(box, "installationPane")
        loiter = _panel(box, "loiterPane")
        assert camera.absent and "MultiRotor" in camera.reason
        assert installation.absent and "MultiRotor" in installation.reason
        assert not loiter.absent

    def test_loiter_range_is_the_subjects_own_bounds_exactly(self, drone):
        pytest.importorskip("openmdao")
        box = surface(drone, VIEW, subject="ScoutSizing::IsrPrime")
        loiter = _panel(box, "loiterPane")
        slider = loiter.sliders["loiterSpeed"]
        assert (slider.min, slider.max) == (11.0, 24.0)
        assert loiter.ranges["loiterSpeed"].source == (
            "mined-from-constraint ScoutSizing::IsrPrime::aboveStall, "
            "ScoutSizing::IsrPrime::belowCruise"
        )

    def test_loiter_slider_reruns_the_mdao_engine(self, drone):
        pytest.importorskip("openmdao")
        box = surface(drone, VIEW, subject="ScoutSizing::IsrPrime")
        loiter = _panel(box, "loiterPane")
        assert loiter.tool == ("longeron.analysis.mdao", "build_problem")
        at_default = loiter.results["stationMinutes"]
        loiter.sliders["loiterSpeed"].value = 20.0
        assert loiter.results["stationMinutes"] < at_default

    def test_unbound_result_diagnostic_fires(self, drone):
        pytest.importorskip("openmdao")
        box = surface(drone, VIEW, subject="ScoutSizing::IsrPrime")
        assert "loiterWhatIf.stationMinutes" in box.wiring.unbound
        assert "unbound results" in str(box.wiring)

    def test_the_picker_lists_every_admissible_subject(self, quad):
        assert "Rotorcraft::QuadCopter" in quad.subjects
        assert "Rotorcraft::HexaCopter" in quad.subjects
        assert "ScoutSizing::IsrPrime" in quad.subjects


# ---------------------------------------------------------------------------
# ranges= overrides (maintainer addition: UI freedom, never a model edit)
# ---------------------------------------------------------------------------


class TestRangesOverride:
    def test_override_replaces_exactly_one_slider(self, drone):
        box = surface(drone, VIEW, ranges={"elevation": (-45.0, 45.0)})
        camera = _panel(box, "cameraPane")
        elevation = camera.sliders["elevation"]
        azimuth = camera.sliders["azimuth"]
        assert (elevation.min, elevation.max) == (-45.0, 45.0)
        assert (azimuth.min, azimuth.max) == (-180.0, 180.0)  # stays mined

    def test_override_source_recorded_and_mined_bounds_kept(self, drone):
        box = surface(drone, VIEW, ranges={"elevation": (-45.0, 45.0)})
        info = _panel(box, "cameraPane").ranges["elevation"]
        assert info.source == RANGE_OVERRIDDEN == "overridden-by-caller"
        assert (info.mined_lo, info.mined_hi) == (-90.0, 90.0)
        assert "overridden-by-caller" in str(box.wiring)
        assert "model constraints state [-90, 90]" in str(box.wiring)

    def test_override_is_visible_on_the_card(self, drone):
        box = surface(drone, VIEW, ranges={"elevation": (-45.0, 45.0)})
        camera = _panel(box, "cameraPane")
        assert "override" in camera.readout.value
        assert "model states [-90, 90]" in camera.readout.value

    def test_widening_override_lets_the_verdict_tell_the_truth(self, drone):
        # the override is UI freedom: the slider allows 30 m/s, and the
        # subject's own aboveStall/belowCruise constraints still judge it
        pytest.importorskip("openmdao")
        box = surface(
            drone, VIEW, subject="ScoutSizing::IsrPrime", ranges={"loiterSpeed": (8.0, 30.0)}
        )
        loiter = _panel(box, "loiterPane")
        slider = loiter.sliders["loiterSpeed"]
        assert (slider.min, slider.max) == (8.0, 30.0)
        info = loiter.ranges["loiterSpeed"]
        assert (info.mined_lo, info.mined_hi) == (11.0, 24.0)
        slider.value = 30.0  # past belowCruise: allowed by the UI ...
        interp = longeron.Interpreter(drone)
        instance = interp.instantiate("ScoutSizing::IsrPrime", loiterSpeed=30.0)
        checks = {c.name: c.passed for c in interp.check(instance)}
        assert checks["belowCruise"] is False  # ... and the model says no

    def test_ambiguous_key_refused(self, mini):
        with pytest.raises(AnalysisError, match="ambiguous"):
            surface(mini, "Mini::v", ranges={"x": (0.0, 1.0)})

    def test_qualified_key_disambiguates(self, mini):
        box = surface(mini, "Mini::v", ranges={"Mini::caseA::x": (0.0, 1.0)})
        pane_a = _panel(box, "paneA")
        pane_b = _panel(box, "paneB")
        assert (pane_a.sliders["x"].min, pane_a.sliders["x"].max) == (0.0, 1.0)
        assert pane_a.ranges["x"].source == RANGE_OVERRIDDEN
        assert pane_b.ranges["x"].source == RANGE_FALLBACK

    def test_lo_ge_hi_refused(self, drone):
        with pytest.raises(AnalysisError, match="lo must be < hi"):
            surface(drone, VIEW, ranges={"elevation": (10.0, 10.0)})

    def test_unknown_key_refused(self, drone):
        with pytest.raises(AnalysisError, match="names no case in-parameter"):
            surface(drone, VIEW, ranges={"nope": (0.0, 1.0)})


# ---------------------------------------------------------------------------
# the registry and honest absence for unregistered renderings
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_the_vocabulary_is_registered(self):
        assert RENDERINGS["LongeronSurfaces::asWhatIfCard"] == "what-if card"
        assert RENDERINGS["LongeronSurfaces::asVerdictCards"] == "verdict cards"
        assert "LongeronSurfaces::asMeshViewer" in RENDERINGS

    def test_unmined_parameter_falls_back_flagged(self, mini):
        box = surface(mini, "Mini::v")
        pane_a = _panel(box, "paneA")
        info = pane_a.ranges["x"]
        assert info.source == RANGE_FALLBACK == "fallback"
        assert (info.lo, info.hi) == surfaces._FALLBACK_BOUNDS
        assert "FALLBACK" in pane_a.readout.value

    def test_unknown_rendering_is_absent_with_a_note(self, mini):
        box = surface(mini, "Mini::v")
        custom = _panel(box, "paneCustom")
        assert custom.absent and "no registered builder" in custom.reason
        assert any("Mini::asCustom" in note for note in box.wiring.notes)

    def test_phase2_rendering_is_absent_naming_its_builder(self, mini):
        box = surface(mini, "Mini::v")
        globe = _panel(box, "paneGlobe")
        assert globe.absent and "phase 2" in globe.reason
        assert "mission_viewer" in globe.reason

    def test_renderless_panel_is_absent(self, mini):
        box = surface(mini, "Mini::v")
        bare = _panel(box, "paneBare")
        assert bare.absent and "no render reference" in bare.reason

    def test_interpreter_is_the_fallback_runner(self, mini):
        # caseA carries no @ToolExecution: the interpreter evaluates the
        # declared return from the slider bindings
        box = surface(mini, "Mini::v", ranges={"Mini::caseA::x": (0.0, 4.0)})
        pane_a = _panel(box, "paneA")
        pane_a.sliders["x"].value = 3.0
        assert pane_a.results["y"] == 3.0


# ---------------------------------------------------------------------------
# the wiring map is part of the returned object, and printable
# ---------------------------------------------------------------------------


class TestWiringMap:
    def test_coupling_records_the_explicit_binding(self, quad):
        sources = {c.source: c for c in quad.wiring.couplings}
        assert "cameraWhatIf.occludedFraction" in sources
        assert "cameraWhatIf.discOverlapVolume" in sources
        coupling = sources["cameraWhatIf.occludedFraction"]
        assert coupling.target == "installationCheck :>> occludedFraction"
        assert "explicit binding" in coupling.binding

    def test_printable_map_tells_the_whole_story(self, quad):
        text = str(quad.wiring)
        assert "surface ScoutSurfaces::scoutSurface" in text
        assert "subject Rotorcraft::QuadCopter" in text
        assert "mined-from-constraint ScoutSurfaces::CameraWhatIf::elevationRange" in text
        assert "cameraWhatIf.occludedFraction -> installationCheck :>> occludedFraction" in text
        assert "ABSENT: LoiterWhatIf applies to ScoutSizing::IsrPrime" in text

    def test_bound_results_are_not_reported_unbound(self, quad):
        assert quad.wiring.unbound == []
