"""M0 interpretations: populations, identities, roll-ups, occurrences."""

from pathlib import Path
from typing import ClassVar

import pytest

import longeron
from longeron import m0
from longeron.analysis.trades import TradeStudy
from longeron.errors import EvaluationError
from longeron.replay import record_timeline

EXAMPLES = Path(__file__).parent.parent / "examples"

RANGE_MODEL = """
package Fleet {
    enum def Livery { plain; racing; stealth; }
    part def Rotor {
        attribute mass : Real = 0.06;
        attribute livery : Livery;
        attribute armed : Boolean;
    }
    part def Quad {
        part rotors : Rotor[2..6];
        part spares : Rotor[0..*];
    }
}
"""


@pytest.fixture(scope="module")
def drone():
    return longeron.load(EXAMPLES / "drone.sysml", cache=False)


@pytest.fixture(scope="module")
def catalog():
    return longeron.load(EXAMPLES / "drone_catalog.sysml", cache=False)


@pytest.fixture(scope="module")
def fleet():
    return longeron.loads(RANGE_MODEL)


class TestNominalPopulation:
    def test_multiplicity_expands_with_identities(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        motors = it.root.slots["motors"]
        assert [r.id for r in motors] == [f"Drone::QuadCopter#0.motors#{i}" for i in range(4)]
        assert len({id(r) for r in motors}) == 4  # distinct objects, not copies

    def test_singleton_features_omit_the_index(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        assert it.root.id == "Drone::QuadCopter#0"
        assert it.root.slots["chassis"].id == "Drone::QuadCopter#0.chassis"

    def test_attributes_evaluated_per_individual(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        assert all(r.slots["mass"] == 0.055 for r in it.root.slots["motors"])
        assert all(r.slots["mass"] == 0.015 for r in it.root.slots["propellers"])
        assert it.root.slots["totalMass"] == 1.41  # same value instantiate computes

    def test_individuals_filter_by_classifier(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        # quad + chassis + battery + esc + flight controller + gps
        # + receiver + telemetry + landing gear + camera
        # + 4 motors + 4 propellers
        assert len(it.individuals()) == 18
        assert len(it.individuals("Drone::Motor")) == 4
        assert len(it.individuals("Drone::Propeller")) == 4

    def test_bindings_override_root_features(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter", bindings={"payloadMass": 0.5})
        assert it.root.slots["payloadMass"] == 0.5

    def test_element_alone_finds_its_model(self, drone):
        defn = drone.find("Drone::QuadCopter")
        it = m0.interpret(defn)
        assert it.source == "Drone::QuadCopter"

    def test_unknown_strategy_rejected(self, drone):
        with pytest.raises(EvaluationError, match="unknown strategy"):
            m0.interpret(drone, "Drone::QuadCopter", strategy="exhaustive")

    def test_nominal_range_multiplicity_takes_lower_bound(self, fleet):
        # the documented deterministic contract: ranges populate their
        # *lower* bound (upper would make [0..*] compositions explode)
        it = m0.interpret(fleet, "Fleet::Quad")  # default strategy: nominal
        assert len(it.root.slots["rotors"]) == 2  # [2..6] -> 2, not 6
        assert it.root.slots["spares"] == []  # [0..*] -> 0

    def test_nominal_unbounded_range_takes_lower_bound(self):
        model = longeron.loads(
            """
            package Boat {
                part def Sailor;
                part def Ship { part crew : Sailor[3..*]; }
            }
            """
        )
        it = m0.interpret(model, "Boat::Ship")
        assert len(it.root.slots["crew"]) == 3


class TestSequences:
    def test_part_feature_sequences(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        seqs = it.sequences("motors")
        assert len(seqs) == 4
        assert all(seq[0] is it.root and len(seq) == 2 for seq in seqs)

    def test_nested_features_are_longer_sequences(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        seqs = it.sequences("motors.mass")
        assert len(seqs) == 4
        assert all(len(seq) == 3 and seq[2] == 0.055 for seq in seqs)
        assert {seq[1].id for seq in seqs} == {r.id for r in it.root.slots["motors"]}


class TestRollup:
    def test_aggregates_over_actual_individuals(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        # drone.sysml hardcodes '4.0 * 0.055 + 4.0 * 0.015' at M1; M0 sums
        # the real motor and propeller individuals
        assert it.rollup("sum(motors.mass)") == pytest.approx(0.22, rel=1e-12)
        assert it.rollup("sum(propellers.mass)") == pytest.approx(0.06, rel=1e-12)

    def test_feature_name_evaluates_its_declared_expression(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        assert it.rollup("totalMass") == pytest.approx(1.41, rel=1e-12)


class TestTriCopterPopulation:
    """The three-rotor sub-architecture: the M1 multiplicities differ
    ([2] front pair + a singleton tail vs the quad's homogeneous [4]),
    so the M0 fan-out differs -- three motor individuals, not four."""

    def test_population_fans_out_three_rotors(self, drone):
        it = m0.interpret(drone, "Drone::TriCopter")
        assert [r.id for r in it.root.slots["frontMotors"]] == [
            f"Drone::TriCopter#0.frontMotors#{i}" for i in range(2)
        ]
        assert it.root.slots["tailMotor"].id == "Drone::TriCopter#0.tailMotor"
        assert len(it.individuals("Drone::Motor")) == 3
        assert len(it.individuals("Drone::Propeller")) == 3

    def test_rotor_mass_rolls_up_over_three_individuals(self, drone):
        it = m0.interpret(drone, "Drone::TriCopter")
        rotor_mass = it.rollup("sum(frontMotors.mass) + tailMotor.mass")
        assert rotor_mass == pytest.approx(3 * 0.055, rel=1e-12)

    def test_tricopter_is_lighter_but_hovers(self, drone):
        it = m0.interpret(drone, "Drone::TriCopter")
        assert it.root.slots["totalMass"] == pytest.approx(1.31, rel=1e-12)
        assert it.root.slots["totalMass"] < 1.41  # lighter than the quad
        # canHover holds, with LESS margin than the quad's ~2.4
        thrust = 3.0 * it.root.slots["thrustPerRotor"]
        weight = it.root.slots["totalMass"] * 9.81
        assert thrust > weight
        assert 1.8 < thrust / weight < 2.1


class TestRandomStrategy:
    def test_counts_stay_within_bounds(self, fleet):
        counts = {
            len(m0.interpret(fleet, "Fleet::Quad", strategy="random", seed=s).root.slots["rotors"])
            for s in range(20)
        }
        assert counts <= {2, 3, 4, 5, 6}
        assert len(counts) > 1  # actually samples the range

    def test_unbounded_upper_is_capped(self, fleet):
        counts = {
            len(m0.interpret(fleet, "Fleet::Quad", strategy="random", seed=s).root.slots["spares"])
            for s in range(20)
        }
        assert counts <= {0, 1, 2, 3}

    def test_seed_reproducibility(self, fleet):
        a = m0.interpret(fleet, "Fleet::Quad", strategy="random", seed=42)
        b = m0.interpret(fleet, "Fleet::Quad", strategy="random", seed=42)
        assert a.to_dict() == b.to_dict()

    def test_unvalued_enum_and_boolean_attributes_sampled(self, fleet):
        it = m0.interpret(fleet, "Fleet::Quad", strategy="random", seed=7)
        rotor = it.root.slots["rotors"][0]
        assert rotor.slots["livery"].name in {"plain", "racing", "stealth"}
        assert rotor.slots["armed"] in (True, False)
        # nominal leaves them unbound
        nom = m0.interpret(fleet, "Fleet::Quad")
        assert nom.root.slots["rotors"][0].slots["livery"] is None

    def test_sample_draws_fresh_interpretations(self, fleet):
        it = m0.interpret(fleet, "Fleet::Quad", strategy="random", seed=1)
        samples = it.sample(3)
        assert len(samples) == 3
        again = it.sample(3)
        assert [s.to_dict() for s in samples] == [s.to_dict() for s in again]

    def test_sample_requires_random_strategy(self, drone):
        with pytest.raises(EvaluationError, match="strategy='random'"):
            m0.interpret(drone, "Drone::QuadCopter").sample(2)


class TestVariations:
    SELECTION: ClassVar[dict[str, str]] = {
        "motors": "emax2306",
        "props": "hq5x43",
        "battery": "lipo4s1500",
        "esc": "esc45",
    }

    def test_selection_pins_variants(self, catalog):
        it = m0.interpret(catalog, "DroneCatalog::TradeQuad", selection=self.SELECTION)
        motors = it.root.slots["motors"]
        assert len(motors) == 4
        assert all(mtr.type_name == "DroneCatalog::Emax2306" for mtr in motors)
        assert it.selection == self.SELECTION

    def test_variants_never_materialize_as_slots(self, catalog):
        it = m0.interpret(catalog, "DroneCatalog::TradeQuad", selection=self.SELECTION)
        assert "emax2306" not in it.root.slots["motors"][0].slots

    def test_nominal_defaults_to_first_variant(self, catalog):
        it = m0.interpret(catalog, "DroneCatalog::TradeQuad")
        assert it.selection["motors"] == "emax2306"
        assert it.selection["battery"] == "lipo4s1500"

    def test_unknown_variant_rejected(self, catalog):
        with pytest.raises(EvaluationError, match="unknown variant"):
            m0.interpret(
                catalog, "DroneCatalog::TradeQuad", selection={**self.SELECTION, "esc": "nope"}
            )

    def test_homogeneous_convention_reported_as_gaps(self, catalog):
        # TradeQuad's M1 metrics use '4.0 * motors.mass' (per-unit trades
        # convention); over the real 4-individual population that is an
        # honest hole, not a crash
        it = m0.interpret(catalog, "DroneCatalog::TradeQuad", selection=self.SELECTION)
        assert it.root.slots["totalMass"] is None
        assert any(gap.startswith("totalMass:") for gap in it.gaps)

    def test_random_variant_choice_is_heterogeneous(self, catalog):
        types = set()
        for seed in range(8):
            it = m0.interpret(catalog, "DroneCatalog::TradeQuad", strategy="random", seed=seed)
            types |= {mtr.type_name for mtr in it.root.slots["motors"]}
            assert set(it.selection) >= {f"motors#{i}" for i in range(4)}
        assert len(types) > 1


class TestTradesRegression:
    """THE regression: M0 roll-ups agree with the M1 trades metrics.

    ``all_architectures`` evaluates every mix with the homogeneous
    ``4.0 * x`` convention; the M0 interpretation of the same architecture
    sums the *actual* individuals.  Both must report the same numbers.
    """

    #: metric name -> the M0 roll-up over the actual population.  Thrust
    #: is per-station motor x prop (kt * thrustTerm * d^4); the roll-up
    #: mini-language aggregates one feature path per sum(), so the
    #: per-unit factors read as population means (sum / 4) -- exact for
    #: the homogeneous populations from_architecture builds.
    ROLLUPS: ClassVar[dict[str, str]] = {
        "totalMass": "frameMass + payloadMass + battery.mass + esc.mass"
        " + sum(motors.mass) + sum(props.mass)",
        "totalCost": "battery.cost + esc.cost + sum(motors.cost) + sum(props.cost)",
        "totalThrust": "0.25 * sum(motors.thrustTerm) * sum(props.kt)"
        " * (0.25 * sum(props.diameterIn)) ** 4.0",
        "hoverMinutes": "battery.capacity / sum(motors.hoverCurrent) * 60.0",
    }

    def test_every_architecture_rolls_up_to_the_trades_metrics(self, catalog):
        study = TradeStudy(catalog, "DroneCatalog::TradeQuad")
        architectures = study.all_architectures()
        assert len(architectures) == 54  # 3 * 3 * 3 * 2
        for arch in architectures:
            it = m0.from_architecture(study, arch)
            for metric, expr in self.ROLLUPS.items():
                assert it.rollup(expr) == pytest.approx(arch.metrics[metric], rel=1e-12), (
                    f"{metric} diverged for {arch.selection}"
                )

    def test_architecture_population_shape(self, catalog):
        study = TradeStudy(catalog, "DroneCatalog::TradeQuad")
        arch = study.evaluate(TestVariations.SELECTION)
        it = m0.from_architecture(study, arch)
        assert it.selection == arch.selection
        motors = it.individuals("DroneCatalog::Emax2306")
        assert [mtr.id for mtr in motors] == [
            f"DroneCatalog::TradeQuad#0.motors#{i}" for i in range(4)
        ]
        # conformance filtering sees variants through their supers
        assert len(it.individuals("DroneCatalog::Motor")) == 4


class TestOccurrencesFromTimeline:
    EVENTS: ClassVar[list] = ["launch", 2.0, "airborne", 10.0, "low_battery", 1.0, "touchdown"]

    @pytest.fixture()
    def timeline(self, drone):
        interp = longeron.Interpreter(drone)
        return record_timeline(interp, "Drone::FlightStates", self.EVENTS)

    def test_activations_become_occurrence_individuals(self, timeline):
        it = m0.from_timeline(timeline)
        flying = it.individuals("Drone::FlightStates::flying")
        assert len(flying) == 1
        assert flying[0].id == "Drone::FlightStates::flying@0"
        assert flying[0].slots["start"] == 2.0
        assert flying[0].slots["end"] == 12.0
        assert flying[0].slots["duration"] == 10.0

    def test_reentry_gets_a_fresh_identity(self, timeline):
        it = m0.from_timeline(timeline)
        idles = it.individuals("Drone::FlightStates::idle")
        assert [ind.id for ind in idles] == [
            "Drone::FlightStates::idle@0",
            "Drone::FlightStates::idle@1",
        ]

    def test_rollups_work_over_lifetimes(self, timeline):
        it = m0.from_timeline(timeline)
        # sequential leaf machine: activations partition the recording
        assert it.rollup("sum(occurrences.duration)") == pytest.approx(13.0)
        assert it.root.slots["duration"] == pytest.approx(13.0)

    def test_sequences_over_occurrences(self, timeline):
        it = m0.from_timeline(timeline)
        seqs = it.sequences("occurrences.duration")
        assert len(seqs) == 5
        assert all(len(seq) == 3 for seq in seqs)


class TestToDict:
    def test_round_trippable_projection(self, drone):
        it = m0.interpret(drone, "Drone::QuadCopter")
        data = it.to_dict()
        assert data["source"] == "Drone::QuadCopter"
        assert data["root"]["@id"] == "Drone::QuadCopter#0"
        assert data["root"]["motors"][2]["@id"] == "Drone::QuadCopter#0.motors#2"
        import json

        json.dumps(data)  # JSON-able all the way down


class TestInterpretArguments:
    def test_individual_repr_is_id_and_type(self, fleet):
        it = m0.interpret(fleet, "Fleet::Quad")
        assert repr(it.root.slots["rotors"][0]) == "<Fleet::Quad#0.rotors#0: Fleet::Rotor>"

    def test_model_without_element_rejected(self, fleet):
        with pytest.raises(EvaluationError, match="needs an element to interpret"):
            m0.interpret(fleet)

    def test_element_plus_name_rejected(self, fleet):
        with pytest.raises(EvaluationError, match=r"pass either \(model, element\)"):
            m0.interpret(fleet.find("Fleet::Quad"), "Fleet::Quad")

    def test_non_element_rejected(self, fleet):
        with pytest.raises(EvaluationError, match="cannot interpret 42"):
            m0.interpret(fleet, 42)

    def test_detached_element_rejected(self):
        from longeron import model as M

        with pytest.raises(EvaluationError, match="Loose is not owned by a Model"):
            m0.interpret(M.Definition(kind="part", name="Loose"))
