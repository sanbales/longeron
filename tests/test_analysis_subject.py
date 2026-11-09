"""The grand-tour subject: mission presets, craft clicks, requirement sets."""

from pathlib import Path
from typing import get_args

import pytest

import longeron
from longeron.analysis import AnalysisError, subject, trades
from longeron.analysis.dashboard import DEFAULT_MISSIONS

EXAMPLES = Path(__file__).parent.parent / "examples"

#: mission -> (winning airframe, declared reference of its metric)
WINNERS = {
    "ISR": ("flyingWingSingle", 274.6),
    "logistics": ("flyingWingTwinTip", 187.0),
    "intercept": ("dartInterceptor", 66.8),
}


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout")


@pytest.fixture(scope="module")
def studies(model):
    return {name: trades.TradeStudy(model, qname) for name, (qname, _) in DEFAULT_MISSIONS.items()}


@pytest.fixture(scope="module")
def presets(studies):
    """Every airframe's preset in every mission (the full crossing, ~5 s)."""

    return {
        mission: {
            airframe: subject.preset(studies[mission], airframe, DEFAULT_MISSIONS[mission][1])
            for airframe in studies[mission].points["airframe"].variants
        }
        for mission in DEFAULT_MISSIONS
    }


def mission_instance(study, mix):
    # c4-trades: study.instance(mix) replaces the private _bindings call
    return study.interp.instantiate(study.assembly, study._bindings(mix))


class TestSubject:
    def test_mission_vocabulary_is_the_dashboard_table(self):
        assert set(get_args(subject.MissionName)) == set(DEFAULT_MISSIONS)

    def test_unknown_mission_is_refused(self):
        with pytest.raises(AnalysisError, match="unknown mission"):
            subject.Subject("isr", "boxQuad", {})

    def test_mix_puts_the_airframe_back(self):
        subj = subject.Subject("intercept", "dartInterceptor", {"motors": "at4120"})
        assert subj.mix() == {"airframe": "dartInterceptor", "motors": "at4120"}
        assert subj.overrides == {}


class TestPreset:
    @pytest.mark.parametrize("mission", sorted(WINNERS))
    def test_presets_reproduce_the_winners(self, presets, studies, mission):
        metric = DEFAULT_MISSIONS[mission][1]
        winner, reference = WINNERS[mission]
        verified = {a: p for a, p in presets[mission].items() if p.basis == "verified"}
        best = max(verified, key=lambda a: verified[a].architecture.metrics[metric])
        assert best == winner
        achieved = verified[winner].architecture.metrics[metric]
        assert achieved == pytest.approx(reference, abs=0.05)
        # the model's declared reference is the same number
        declared = studies[mission].interp.evaluate(f"ScoutMissions::{metric}")
        assert declared == reference

    def test_preset_is_a_subject(self, presets, studies):
        chosen = presets["ISR"]["flyingWingSingle"]
        subj = chosen.subject("ISR")
        assert subj.airframe == "flyingWingSingle"
        assert "airframe" not in subj.selection
        assert studies["ISR"].evaluate(subj.mix()) == chosen.architecture

    @pytest.mark.parametrize(
        ("mission", "airframe"),
        [("ISR", "teardropQuad"), ("logistics", "hexLifter"), ("intercept", "boxQuad")],
    )
    def test_infeasible_pair_falls_back(self, presets, studies, mission, airframe):
        metric = DEFAULT_MISSIONS[mission][1]
        chosen = presets[mission][airframe]
        assert chosen.basis == "fewest_violations"
        assert chosen.architecture.violations
        assert chosen.architecture.selection["airframe"] == airframe
        # independent check: no pinned mix breaks fewer constraints, and
        # the metric breaks the tie among the fewest
        pinned = [
            a for a in studies[mission].all_architectures() if a.selection["airframe"] == airframe
        ]
        fewest = min(len(a.violations) for a in pinned)
        assert len(chosen.architecture.violations) == fewest
        tied = [a.metrics[metric] for a in pinned if len(a.violations) == fewest]
        assert chosen.architecture.metrics[metric] == max(tied)

    def test_feasible_counts_match_finding_three(self, presets):
        infeasible = {
            mission: {a for a, p in by_airframe.items() if p.basis == "fewest_violations"}
            for mission, by_airframe in presets.items()
        }
        rotors = {"boxQuad", "openTri", "hexLifter", "coaxOcto", "ringOcto"}
        assert infeasible["ISR"] == {"teardropQuad", "dartInterceptor"}
        assert infeasible["logistics"] == {
            "teardropQuad",
            "hexLifter",
            "dartInterceptor",
            "flyingWingSingle",
        }
        assert infeasible["intercept"] == rotors

    def test_bad_arguments_are_refused(self, studies):
        study = studies["ISR"]
        with pytest.raises(AnalysisError, match="unknown variant"):
            subject.preset(study, "QuadCopter", "stationMinutes")
        with pytest.raises(AnalysisError, match="not a derived attribute"):
            subject.preset(study, "boxQuad", "minStationMinutes")
        with pytest.raises(AnalysisError, match="unknown variation point"):
            subject.preset(study, "boxQuad", "stationMinutes", point="frame")


class TestCraftVariant:
    def test_build_configuration_is_not_a_catalog_airframe(self, model, studies):
        quad = model.find("Rotorcraft::QuadCopter")
        assert quad is not None
        assert subject.craft_variant(studies["ISR"], quad) is None

    def test_definition_maps_to_its_variant(self, model, studies):
        twin = model.find("FlyingWings::FlyingWingTwin")
        tip = model.find("FlyingWings::FlyingWingTwinTip")
        assert subject.craft_variant(studies["ISR"], twin) == "flyingWingTwin"
        # the tip twin specializes the twin, yet maps to its own variant
        assert subject.craft_variant(studies["ISR"], tip) == "flyingWingTwinTip"

    def test_variant_usage_maps_to_itself(self, model, studies):
        usage = model.find("ScoutMissions::Catalog::AirframeChoice::flyingWingTwin")
        assert subject.craft_variant(studies["logistics"], usage) == "flyingWingTwin"

    def test_other_points_do_not_leak(self, model, studies):
        motor = model.find("ScoutMissions::Catalog::MotorChoice::mt2213")
        assert subject.craft_variant(studies["ISR"], motor) is None
        assert subject.craft_variant(studies["ISR"], motor, point="motors") == "mt2213"


class TestRequirementSet:
    def pairs(self, presets, studies, mission, airframe):
        study = studies[mission]
        inst = mission_instance(study, presets[mission][airframe].architecture.selection)
        air = inst.get("airframe")
        found = subject.requirement_set(inst, air, interp=study.interp)
        return {name: ("mission" if i is inst else "airframe") for name, i in found.items()}, air

    def test_isr_flying_wing(self, presets, studies):
        pairs, _ = self.pairs(presets, studies, "ISR", "flyingWingSingle")
        # c0-model: IsrTasking joins as "mission" once its hover assumption is deleted
        assert pairs == {
            "ScoutMissions::MissionRequirements::PayloadBayFit": "mission",
            "ScoutMissions::StabilityRequirements::PitchStability": "airframe",
            "ScoutMissions::StabilityRequirements::PitchRollAuthority": "airframe",
            "ScoutMissions::StabilityRequirements::YawStability": "airframe",
        }

    def test_tip_twin_scores_engine_out_on_its_airframe(self, presets, studies):
        pairs, air = self.pairs(presets, studies, "logistics", "flyingWingTwinTip")
        assert pairs == {
            "ScoutMissions::MissionRequirements::LogisticsTasking": "mission",
            "ScoutMissions::MissionRequirements::PayloadBayFit": "mission",
            "ScoutMissions::StabilityRequirements::PitchStability": "airframe",
            "ScoutMissions::StabilityRequirements::PitchRollAuthority": "airframe",
            "ScoutMissions::StabilityRequirements::YawStability": "airframe",
            "ScoutMissions::StabilityRequirements::EngineOutYaw": "airframe",
        }
        verdict = studies["logistics"].interp.check_requirement(
            "ScoutMissions::StabilityRequirements::EngineOutYaw", air
        )
        assert verdict.satisfied is False  # the tip twin's known bust

    def test_tilt_tri_scores_cruise_engine_out(self, presets, studies):
        pairs, _ = self.pairs(presets, studies, "ISR", "tiltTriWing")
        assert pairs["TiltRotors::CruiseEngineOut"] == "airframe"
        assert "ScoutMissions::StabilityRequirements::PitchStability" not in pairs
