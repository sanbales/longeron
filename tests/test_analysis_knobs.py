"""Knob derivation: the PLAN section 3 table on DeepScout, and the edges."""

from pathlib import Path

import pytest

import longeron
from longeron.analysis import AnalysisError, trades
from longeron.analysis.dashboard import DEFAULT_MISSIONS
from longeron.analysis.knobs import Dropdown, KnobSet, Skipped, Slider, derive_knobs
from longeron.interpreter import Interpreter

EXAMPLES = Path(__file__).parent.parent / "examples"

#: mission -> (sliders as (name, low, high, value), dropdown points), the
#: bounds from the c0-model range asserts of ScoutMissions
TABLE = {
    "ISR": (
        [("minStationMinutes", 25.0, 240.0, 25.0)],
        ["sensor", "motors", "props", "battery", "material"],
    ),
    "logistics": (
        [("minDeliveryRadiusKm", 4.0, 16.0, 8.0), ("minPayloadKg", 0.5, 2.0, 1.0)],
        ["cargo", "motors", "props", "battery", "material"],
    ),
    "intercept": (
        [("targetSpeed", 25.0, 75.0, 25.0), ("targetDistance", 1500.0, 6000.0, 3000.0)],
        ["motors", "props", "battery", "material"],
    ),
}


#: airframe -> {attribute: (low, high)}, the shell range asserts of the
#: knobs-model commit; the dart, the teardrop and the hex lifter have none
_WING = {"wingSpan": (2.0, 3.0), "loiterSpeed": (11.5, 22.0), "cruiseSpeed": (14.0, 25.0)}
AIRFRAME_TABLE = {
    "boxQuad": {"cruiseSpeed": (7.0, 24.0)},
    "openTri": {"cruiseSpeed": (6.0, 11.0)},
    "coaxOcto": {"cruiseSpeed": (8.0, 28.0)},
    "ringOcto": {"cruiseSpeed": (8.0, 21.0)},
    "vtolWing": {
        "fuselageDiameter": (0.10, 0.16),
        "wingSpan": (2.0, 3.0),
        "wingChord": (0.20, 0.30),
        "loiterSpeed": (13.0, 21.0),
        "cruiseSpeed": (17.5, 25.0),
    },
    "flyingWingSingle": {
        "wingSpan": (1.6, 2.8),
        "wingChord": (0.26, 0.40),
        "loiterSpeed": (11.5, 19.0),
    },
    "flyingWingTwin": {**_WING, "wingChord": (0.26, 0.40)},
    "flyingWingTwinTip": {**_WING, "wingChord": (0.26, 0.40)},
    "tiltTriWing": {
        "fuselageDiameter": (0.12, 0.18),
        "wingSpan": (2.0, 3.0),
        "wingChord": (0.24, 0.36),
        "loiterSpeed": (12.5, 20.0),
        "cruiseSpeed": (15.0, 25.0),
    },
}


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout")


@pytest.fixture(scope="module")
def studies(model):
    return {name: trades.TradeStudy(model, qname) for name, (qname, _) in DEFAULT_MISSIONS.items()}


def _rows(knobs: KnobSet) -> list[tuple[str, float, float, float]]:
    return [(s.name, s.low, s.high, s.value) for s in knobs.sliders]


class TestDeepScoutTable:
    @pytest.mark.parametrize("mission", sorted(TABLE))
    def test_mission_row(self, studies, mission):
        study = studies[mission]
        knobs = derive_knobs(study.interp, study.assembly, study=study)
        sliders, points = TABLE[mission]
        assert _rows(knobs) == sliders
        assert sorted(d.point for d in knobs.dropdowns) == sorted(points)
        assert knobs.skipped == ()
        for drop in knobs.dropdowns:
            assert drop.variants == tuple(study.points[drop.point].variants)
            assert drop.selected == drop.variants[0]

    @pytest.mark.parametrize("mission", sorted(TABLE))
    def test_defaults_sit_inside_their_intervals(self, studies, mission):
        study = studies[mission]
        for s in derive_knobs(study.interp, study.assembly, study=study).sliders:
            assert s.low <= s.value <= s.high
            # the literal value lands on the slider's step grid
            assert (s.value - s.low) / s.step == pytest.approx(round((s.value - s.low) / s.step))
            assert 100 <= (s.high - s.low) / s.step <= 1000

    def test_every_airframe_row(self, studies):
        study = studies["ISR"]
        variants = list(study.points["airframe"].variants)
        assert len(variants) == 12
        for name in variants:
            usage = study._variant_usage("airframe", name)
            definition = study.interp.resolver.resolve(usage.types[0], usage.owner)
            for element in (usage, definition):
                knobs = derive_knobs(study.interp, element)
                rows = {s.name: (s.low, s.high) for s in knobs.sliders}
                assert rows == AIRFRAME_TABLE.get(name, {}), name
                assert knobs.skipped == () and knobs.dropdowns == ()

    def test_airframe_defaults_sit_inside_their_ranges(self, studies):
        study = studies["ISR"]
        for name in AIRFRAME_TABLE:
            knobs = derive_knobs(study.interp, study._variant_usage("airframe", name))
            for s in knobs.sliders:
                assert s.low <= s.value <= s.high, (name, s.name)
                assert s.value == study.points["airframe"].variants[name][s.name]
                assert (s.value - s.low) / s.step == pytest.approx(
                    round((s.value - s.low) / s.step)
                )
                assert 100 <= round((s.high - s.low) / s.step) <= 1000

    def test_selected_airframe_adds_its_sliders(self, studies):
        # the airframe point is never a dropdown; its bounded inputs join
        # as override keys
        study = studies["ISR"]
        mix = {"airframe": "flyingWingSingle", "battery": "liion6s6p"}
        knobs = derive_knobs(study.interp, study.assembly, study=study, selection=mix)
        assert _rows(knobs) == [
            *TABLE["ISR"][0],
            ("airframe.wingSpan", 1.6, 2.8, 2.2),
            ("airframe.wingChord", 0.26, 0.4, 0.32),
            ("airframe.loiterSpeed", 11.5, 19.0, 14.0),
        ]
        assert "airframe" not in {d.point for d in knobs.dropdowns}
        assert {d.point: d.selected for d in knobs.dropdowns}["battery"] == "liion6s6p"

    def test_sizing_context_gives_the_loiter_slider(self, model):
        interp = Interpreter(model)
        knobs = derive_knobs(interp, interp.resolve("ScoutSizing::IsrPrime"))
        # aboveStall / belowCruise bound it; IsrStation's assume does not
        assert knobs == KnobSet((Slider("loiterSpeed", 11.0, 24.0, 0.1, 15.0),), (), ())


EDGES = """
package Knobs {
    part def Base {
        attribute inherited : Real = 3.0;
        assert constraint inheritedRange { inherited >= 1.0 and inherited <= 5.0 }
    }
    part def Rig :> Base {
        attribute both : Real = 2.0;
        attribute flipped : Real = -1.0;
        attribute lowOnly : Real = 4.0;
        attribute highOnly : Real = 4.0;
        attribute outside : Real = 9.0;
        attribute twice : Real = both * 2.0;
        attribute assumed : Real = 1.0;
        attribute required : Real = 6.0;
        attribute negated : Real = 0.5;
        attribute unbounded : Real = 7.0;
        assert constraint bothRange { both >= 0.0 and both <= 10.0 }
        assert constraint flippedLow { -2.0 <= flipped }
        assert constraint flippedHigh { 0.0 >= flipped }
        assert constraint lowOnlyFloor { lowOnly >= 1.0 }
        assert constraint highOnlyCap { highOnly <= 8.0 }
        assert constraint outsideRange { outside >= 0.0 and outside <= 5.0 }
        assert constraint twiceRange { twice >= 0.0 and twice <= 40.0 }
        assert constraint negatedRange { negated <= 1.0 }
        assert not constraint negatedFloor { negated >= 0.2 }
        assert constraint linked { unbounded >= both }
    }
    part def Other { attribute both : Real = 2.0; }
    requirement def AssumeOnly {
        subject r : Rig;
        assume constraint { r.assumed >= 0.0 and r.assumed <= 2.0 }
        require constraint { r.assumed >= r.both }
    }
    requirement def RequireRange {
        subject r : Base;
        require constraint { r.required >= 5.0 }
        require constraint { 10.0 >= r.required }
    }
    requirement def NotMine {
        subject o : Other;
        require constraint { o.unbounded >= 0.0 and o.unbounded <= 9.0 }
    }
}
"""


@pytest.fixture(scope="module")
def knobs():
    interp = Interpreter(longeron.loads(EDGES))
    return derive_knobs(interp, interp.resolve("Knobs::Rig"))


class TestEdges:
    def test_sliders(self, knobs):
        assert {s.name: (s.low, s.high, s.value) for s in knobs.sliders} == {
            "inherited": (1.0, 5.0, 3.0),  # an inherited input and assert
            "both": (0.0, 10.0, 2.0),  # an 'and' conjunction
            "flipped": (-2.0, 0.0, -1.0),  # literal on the left, unary minus
            "required": (5.0, 10.0, 6.0),  # a require constraint, prefix removed
        }

    def test_skipped_carry_the_reason(self, knobs):
        assert set(knobs.skipped) == {
            Skipped("lowOnly", "lower_only", 1.0, None),
            Skipped("highOnly", "upper_only", None, 8.0),
            Skipped("outside", "default_outside", 0.0, 5.0),
            # 'assert not' is no bound source: only the cap remains
            Skipped("negated", "upper_only", None, 1.0),
        }

    def test_no_knob_without_literal_bounds(self, knobs):
        # twice: a derived expression, not an input; assumed: assume only; unbounded: a non-literal
        # bound and the require of a requirement with another subject type
        named = {s.name for s in knobs.sliders} | {s.name for s in knobs.skipped}
        assert named.isdisjoint({"twice", "assumed", "unbounded"})
        assert knobs.dropdowns == ()

    def test_require_applies_by_conformance(self):
        interp = Interpreter(longeron.loads(EDGES))
        base = derive_knobs(interp, interp.resolve("Knobs::Base"))
        assert [s.name for s in base.sliders] == ["inherited"]  # Base has no 'required'
        assert derive_knobs(interp, interp.resolve("Knobs::Other")) == KnobSet((), (), ())


CATALOG = """
package Craft {
    part def Frame { attribute span : Real; }
    part def Small :> Frame {
        attribute span : Real = 1.0;
        assert constraint spanRange { span >= 0.5 and span <= 2.0 }
    }
    part def Large :> Frame { attribute span : Real = 3.0; }
    part def Pack { attribute wh : Real; }
    part def PackA :> Pack { attribute wh : Real = 10.0; }
    part def PackB :> Pack { attribute wh : Real = 20.0; }
    variation part def FrameChoice :> Frame {
        variant part small : Small;
        variant part large : Large;
    }
    variation part def PackChoice :> Pack {
        variant part packA : PackA;
        variant part packB : PackB;
    }
    part def Uav {
        part airframe : FrameChoice;
        part pack : PackChoice;
        attribute floor : Real = 4.0;
        attribute energy : Real = pack.wh * airframe.span;
        assert constraint floorRange { floor >= 1.0 and floor <= 8.0 }
        assert constraint enough { energy >= floor }
    }
}
"""


@pytest.fixture(scope="module")
def study():
    return trades.TradeStudy(longeron.loads(CATALOG), "Craft::Uav")


class TestSubjectComposition:
    def test_airframe_sliders_join_as_override_keys(self, study):
        knobs = derive_knobs(
            study.interp, study.assembly, study=study, selection={"airframe": "small"}
        )
        assert [s.name for s in knobs.sliders] == ["floor", "airframe.span"]
        assert knobs.dropdowns == (Dropdown("pack", ("packA", "packB"), "packA"),)
        # the slider name is the override key of TradeStudy.evaluate
        mix = {"airframe": "small", "pack": "packB"}
        arch = study.evaluate(mix, {s.name: s.high for s in knobs.sliders})
        assert arch.metrics["energy"] == pytest.approx(40.0)

    def test_other_airframe_has_none(self, study):
        knobs = derive_knobs(
            study.interp, study.assembly, study=study, selection={"airframe": "large"}
        )
        assert [s.name for s in knobs.sliders] == ["floor"]

    def test_refusals(self, study):
        with pytest.raises(AnalysisError, match="needs the trade study"):
            derive_knobs(study.interp, study.assembly, selection={"pack": "packA"})
        with pytest.raises(AnalysisError, match="not Small"):
            derive_knobs(study.interp, study.interp.resolve("Craft::Small"), study=study)
        with pytest.raises(AnalysisError, match="unknown variation point"):
            derive_knobs(study.interp, study.assembly, study=study, selection={"cargo": "x"})
        with pytest.raises(AnalysisError, match="unknown variant"):
            derive_knobs(study.interp, study.assembly, study=study, selection={"pack": "packC"})


REACH = """
package Reach {
    part def Frame { attribute span : Real; attribute speed : Real; attribute trim : Real; }
    part def Wing :> Frame {
        attribute span : Real = 2.0;
        attribute speed : Real = 10.0;
        attribute trim : Real = 1.0;
        attribute area : Real = span * 0.3;     // a variant attribute that reads span
        attribute trimmed : Real = trim * 2.0;  // read by no mission feature
        assert constraint spanLow { span >= 1.0 }
        assert constraint spanHigh { span <= 3.0 }
        assert constraint speedLow { speed >= 5.0 }
        assert constraint speedHigh { speed <= 20.0 }
        assert constraint trimLow { trim >= 0.0 }
        assert constraint trimHigh { trim <= 2.0 }
    }
    part def Pack { attribute wh : Real; }
    part def PackA :> Pack { attribute wh : Real = 10.0; }
    variation part def FrameChoice :> Frame { variant part wing : Wing; }
    variation part def PackChoice :> Pack { variant part packA : PackA; }
    part def Mission {
        part airframe : FrameChoice;
        part pack : PackChoice;
        attribute floor : Real = 4.0;     // read by its range and by 'enough'
        attribute spare : Real = 1.0;     // read by its range only
        attribute endurance : Real = pack.wh / airframe.area;   // the metric
        attribute dash : Real = airframe.speed * 2.0;
        assert constraint floorRange { floor >= 1.0 and floor <= 8.0 }
        assert constraint spareRange { spare >= 0.0 and spare <= 2.0 }
        assert constraint enough { pack.wh >= floor }
        assert constraint fast { dash >= 0.0 }
    }
}
"""


@pytest.fixture(scope="module")
def reach():
    return trades.TradeStudy(longeron.loads(REACH), "Reach::Mission")


class TestReachability:
    """Rule 8: a slider is kept only if its input reaches the mission."""

    def test_the_rule_on_a_synthetic_mission(self, reach):
        knobs = derive_knobs(
            reach.interp,
            reach.assembly,
            study=reach,
            selection={"airframe": "wing"},
            metric="endurance",
        )
        # span reaches the metric through the variant's area; speed reaches
        # the 'fast' constraint through dash; floor reaches 'enough'
        assert [s.name for s in knobs.sliders] == ["floor", "airframe.span", "airframe.speed"]
        # spare: only its own range reads it; trim: only a variant attribute
        # that no mission feature reads
        assert set(knobs.skipped) == {
            Skipped("spare", "unreachable", 0.0, 2.0),
            Skipped("airframe.trim", "unreachable", 0.0, 2.0),
        }

    def test_dependents_follow_whole_paths(self, reach):
        assert reach.dependents("airframe.span", "wing") == {"endurance"}
        assert reach.dependents("airframe.speed", "wing") == {"dash", "fast"}
        assert reach.dependents("airframe.trim", "wing") == set()
        assert reach.dependents("floor") == {"floorRange", "enough"}
        with pytest.raises(AnalysisError, match="needs a variant"):
            reach.dependents("airframe.span")

    def test_without_the_metric_only_constraints_count(self, reach):
        knobs = derive_knobs(
            reach.interp, reach.assembly, study=reach, selection={"airframe": "wing"}
        )
        assert "airframe.span" in {s.name for s in knobs.skipped}

    @pytest.mark.parametrize(
        ("mission", "airframe", "listed", "unreachable"),
        [
            ("ISR", "vtolWing", "airframe.loiterSpeed", "airframe.cruiseSpeed"),
            ("logistics", "vtolWing", "airframe.cruiseSpeed", "airframe.loiterSpeed"),
            ("ISR", "tiltTriWing", "airframe.loiterSpeed", "airframe.cruiseSpeed"),
            ("intercept", "boxQuad", "targetSpeed", "airframe.cruiseSpeed"),
        ],
    )
    def test_the_rule_on_deepscout(self, studies, mission, airframe, listed, unreachable):
        study = studies[mission]
        knobs = derive_knobs(
            study.interp,
            study.assembly,
            study=study,
            selection={"airframe": airframe},
            metric=DEFAULT_MISSIONS[mission][1],
        )
        assert listed in {s.name for s in knobs.sliders}
        skipped = {s.name: s.reason for s in knobs.skipped}
        assert skipped[unreachable] == "unreachable"
