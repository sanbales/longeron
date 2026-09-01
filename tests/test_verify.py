"""longeron.analysis.verify: four tiers over the interpreter oracle.

The Hypothesis-driven tiers (`hunt`, `sequences`, the generator property
tests) skip cleanly when the ``verify`` extra is absent -- CI runs without
hypothesis and must stay green; the full suite is exercised from a scratch
venv with ``pip install "longeron[verify]"``.  The IPOG generator, its
independent coverage checker, `cover`, and `prove` need no hypothesis.
"""

import importlib.util
from itertools import product
from pathlib import Path
from typing import ClassVar

import pytest

import longeron
from longeron.analysis import _ipog, verify
from longeron.analysis._expr import AnalysisError

EXAMPLES = Path(__file__).parent.parent / "examples"

HAS_HYPOTHESIS = importlib.util.find_spec("hypothesis") is not None
HAS_Z3 = importlib.util.find_spec("z3") is not None
needs_hypothesis = pytest.mark.skipif(
    not HAS_HYPOTHESIS, reason="needs the verify extra (pip install 'longeron[verify]')"
)
needs_z3 = pytest.mark.skipif(
    not HAS_Z3, reason="needs the smt extra (pip install 'longeron[smt]')"
)


@pytest.fixture(scope="module")
def drone():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def catalog():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def uav():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


DOMAIN_MODEL = """
package Modes {
    enum def Mode { eco; cruise; sport; }
    part def Prop {
        attribute mode : Mode;
        attribute count : Natural = 2;
        attribute armed : Boolean = false;
        attribute speed : Real = 12.0;
        assert constraint speedBand { speed >= 11.0 and speed <= 24.0 }
        assert constraint noSport { mode != Mode::sport }
    }
}
"""

CASE_BOUNDS_MODEL = """
package Cases {
    analysis def Sweep {
        subject probe : Anything;
        in attribute elevation : Real = 0.0;
        in attribute azimuth : Real = 0.0;
        objective {
            assume constraint elevationRange {
                elevation >= -90.0 and elevation <= 90.0 }
            assume constraint azimuthRange {
                azimuth >= -180.0 and azimuth <= 180.0 }
        }
        return quality : Real;
    }
}
"""


# ---------------------------------------------------------------------------
# the domain ladder (no extras needed below the Z3 rung)
# ---------------------------------------------------------------------------


class TestDomains:
    def test_types_and_mined_bounds(self):
        model = longeron.loads(DOMAIN_MODEL)
        interp = longeron.Interpreter(model)
        domains = verify.attribute_domains(
            interp, interp.resolve("Modes::Prop"), ("mode", "count", "armed", "speed")
        )
        speed = domains["speed"]
        assert (speed.lo, speed.hi) == (11.0, 24.0)
        assert any("speedBand" in note for note in speed.mined_from)
        assert domains["count"].lo == 0.0  # Natural floor
        assert domains["armed"].kind == "Boolean"
        mode = domains["mode"]
        assert [lit.name for lit in mode.literals] == ["eco", "cruise", "sport"]

    def test_uav_loiter_speed_mined_with_zero_hand_mapping(self, uav):
        interp = longeron.Interpreter(uav)
        domains = verify.attribute_domains(
            interp, interp.resolve("ScoutSizing::IsrPrime"), ("loiterSpeed",)
        )
        assert (domains["loiterSpeed"].lo, domains["loiterSpeed"].hi) == (11.0, 24.0)

    def test_objective_nested_assume_bounds_mined(self):
        # the spec's home for a case's assumptions: constraints inside the
        # objective are rung 2 material (surfaces design, miner gap 1)
        model = longeron.loads(CASE_BOUNDS_MODEL)
        interp = longeron.Interpreter(model)
        domains = verify.attribute_domains(
            interp, interp.resolve("Cases::Sweep"), ("elevation", "azimuth")
        )
        assert (domains["elevation"].lo, domains["elevation"].hi) == (-90.0, 90.0)
        assert (domains["azimuth"].lo, domains["azimuth"].hi) == (-180.0, 180.0)
        # provenance cites the constraint's qualified name
        assert any(
            "Cases::Sweep::elevationRange" in note for note in domains["elevation"].mined_from
        )

    def test_negative_literal_bounds_folded(self):
        # a unary-minus literal is a bound too (surfaces design, miner gap 2)
        model = longeron.loads(
            """
            package Depths {
                part def Probe {
                    attribute depth : Real = -1.0;
                    assert constraint band { depth >= -5.0 and depth <= -0.5 }
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        domains = verify.attribute_domains(interp, interp.resolve("Depths::Probe"), ("depth",))
        assert (domains["depth"].lo, domains["depth"].hi) == (-5.0, -0.5)

    def test_unit_annotation_recorded_informationally(self, drone):
        interp = longeron.Interpreter(drone)
        domains = verify.attribute_domains(
            interp, interp.resolve("Rotorcraft::QuadCopter"), ("payloadMass",)
        )
        assert domains["payloadMass"].unit == "kg"

    def test_unknown_attribute_refused(self, drone):
        interp = longeron.Interpreter(drone)
        with pytest.raises(AnalysisError, match="no attribute"):
            verify.attribute_domains(interp, interp.resolve("Rotorcraft::QuadCopter"), ("nope",))

    @needs_z3
    def test_z3_rung_reaches_through_derived_attributes(self, drone):
        # payloadMass is bounded nowhere directly; the assumption
        # totalMass > 0 reaches it through the derivation chain
        interp = longeron.Interpreter(drone)
        domains = verify.attribute_domains(
            interp,
            interp.resolve("Rotorcraft::QuadCopter"),
            ("payloadMass",),
            requirements=("DeepScout::FlightEnvelope",),
        )
        dom = domains["payloadMass"]
        assert dom.lo == pytest.approx(-1.21)
        assert dom.hi is None  # honestly unbounded above under assumptions
        assert any("unbounded" in note for note in dom.mined_from)


# ---------------------------------------------------------------------------
# the universal property (vacuous-pass semantics, normative)
# ---------------------------------------------------------------------------


class TestVerdict:
    def test_violation_when_assumptions_hold(self, drone):
        interp = longeron.Interpreter(drone)
        v = verify.verdict(
            interp, "Rotorcraft::QuadCopter", ("DeepScout::FlightEnvelope",), {"payloadMass": 3.0}
        )
        assert not v.ok
        assert "takeoffMassLimit [assert]" in v.violated
        assert "canHover [assert]" in v.violated
        assert "FlightEnvelope::hoverMargin" in v.violated
        assert v.vacuous == []

    def test_violated_assumption_is_vacuous_never_failed(self):
        model = longeron.loads(
            """
            package Fence {
                part def Thing {
                    attribute x : Real = 4.0;
                    attribute y : Real = 1.0;
                }
                requirement def Guarded {
                    subject t : Thing;
                    assume constraint { t.y > 0.0 }
                    require constraint sq { t.x * t.x >= 0.0 }
                }
            }
            """
        )
        interp = longeron.Interpreter(model)
        v = verify.verdict(interp, "Fence::Thing", ("Fence::Guarded",), {"y": 0.0})
        assert v.vacuous == ["Guarded"]
        assert v.violated == [] and v.ok  # vacuous is a pass, never a failure

    def test_unevaluable_physics_is_an_error_not_a_verdict(self, drone):
        # a negative total mass reaches the model's real sqrt: the oracle
        # cannot evaluate, and verdict says so instead of guessing
        interp = longeron.Interpreter(drone)
        v = verify.verdict(
            interp, "Rotorcraft::QuadCopter", ("DeepScout::FlightEnvelope",), {"payloadMass": -2.0}
        )
        assert v.error is not None and "domain error" in v.error
        assert v.violated == [] and v.vacuous == []

    def test_default_configuration_is_clean(self, drone):
        interp = longeron.Interpreter(drone)
        v = verify.verdict(interp, "Rotorcraft::QuadCopter", ("DeepScout::FlightEnvelope",), {})
        assert v.ok and v.vacuous == []


# ---------------------------------------------------------------------------
# IPOG-F generator + the independent coverage checker (stdlib only)
# ---------------------------------------------------------------------------


def _brute_force_engine(factors, forbidden):
    """Exact existential extendability from the enumerated allowed rows."""

    names = [name for name, _ in factors]
    allowed = [
        dict(zip(names, combo, strict=True))
        for combo in product(*(levels for _, levels in factors))
        if not any(all(combo[names.index(n)] == v for n, v in pair.items()) for pair in forbidden)
    ]

    def extendable(assignment):
        return any(all(row[n] == v for n, v in assignment.items()) for row in allowed)

    return extendable, allowed


class TestIpog:
    FACTORS: ClassVar[list] = [("a", ("1", "2", "3")), ("b", ("x", "y", "z")), ("c", ("l", "r"))]

    def test_pairwise_covers_everything(self):
        rows = _ipog.generate(self.FACTORS, 2)
        missing, invalid = _ipog.check_cover(self.FACTORS, rows, 2)
        assert missing == [] and invalid == []
        assert 9 <= len(rows) <= 12  # 3x3 pairs bound the size below

    def test_full_strength_is_the_cartesian_product(self):
        rows = _ipog.generate(self.FACTORS, 3)
        missing, invalid = _ipog.check_cover(self.FACTORS, rows, 3)
        assert missing == [] and invalid == []
        assert len(rows) == 18

    def test_deterministic(self):
        assert _ipog.generate(self.FACTORS, 2) == _ipog.generate(self.FACTORS, 2)

    def test_rows_keep_declared_factor_order(self):
        for row in _ipog.generate(self.FACTORS, 2):
            assert list(row) == ["a", "b", "c"]

    def test_constraints_exclude_invalid_tuples_and_rows(self):
        forbidden = [{"a": "1", "b": "x"}, {"b": "z", "c": "r"}]
        ext, _allowed = _brute_force_engine(self.FACTORS, forbidden)
        rows = _ipog.generate(self.FACTORS, 2, ext)
        missing, invalid = _ipog.check_cover(self.FACTORS, rows, 2, ext)
        assert missing == [] and invalid == []
        for row in rows:  # no forbidden pair sneaks into any row
            for pair in forbidden:
                assert not all(row[n] == v for n, v in pair.items())

    def test_unsatisfiable_constraints_yield_an_empty_array(self):
        rows = _ipog.generate(self.FACTORS, 2, lambda a: False)
        assert rows == []

    def test_ceilings_refuse_loudly(self):
        with pytest.raises(AnalysisError, match=r"2\.\.6"):
            _ipog.generate(self.FACTORS, 1)
        with pytest.raises(AnalysisError, match="IPOG-D"):
            _ipog.generate(self.FACTORS, 7)
        with pytest.raises(AnalysisError, match="exceeds the 3 available factors"):
            _ipog.generate(self.FACTORS, 4)
        wide = [(f"f{i}", ("0", "1")) for i in range(65)]
        with pytest.raises(AnalysisError, match="64-factor ceiling"):
            _ipog.generate(wide, 2)
        with pytest.raises(AnalysisError, match="no levels"):
            _ipog.generate([("a", ("1",)), ("b", ())], 2)
        with pytest.raises(AnalysisError, match="duplicate factor"):
            _ipog.generate([("a", ("1", "2")), ("a", ("1", "2"))], 2)

    def test_checker_is_not_fooled(self):
        # the checker must catch a deliberately broken array: drop a row
        # (coverage hole) and corrupt a cell (invalid row)
        rows = _ipog.generate(self.FACTORS, 2)
        missing, _ = _ipog.check_cover(self.FACTORS, rows[:-1], 2)
        assert missing  # the dropped row covered something unique
        broken = [dict(rows[0], a="bogus"), *rows[1:]]
        _, invalid = _ipog.check_cover(self.FACTORS, broken, 2)
        assert invalid == [0]


@needs_hypothesis
class TestIpogProperties:
    """The verify machinery testing itself: random catalogs, random
    constraint densities -- coverage holds, rows validate, ceilings refuse."""

    def test_generator_holds_its_guarantee_on_random_catalogs(self):
        from hypothesis import HealthCheck, given, settings
        from hypothesis import strategies as st

        @st.composite
        def catalogs(draw):
            k = draw(st.integers(min_value=2, max_value=5))
            factors = [
                (
                    f"f{i}",
                    tuple(f"v{j}" for j in range(draw(st.integers(min_value=2, max_value=4)))),
                )
                for i in range(k)
            ]
            t = draw(st.integers(min_value=2, max_value=min(3, k)))
            pairs = draw(
                st.lists(
                    st.tuples(
                        st.integers(min_value=0, max_value=k - 1),
                        st.integers(min_value=0, max_value=k - 1),
                    ).filter(lambda ij: ij[0] != ij[1]),
                    max_size=3,
                )
            )
            forbidden = []
            for i, j in pairs:
                forbidden.append({factors[i][0]: factors[i][1][0], factors[j][0]: factors[j][1][0]})
            return factors, t, forbidden

        @settings(
            max_examples=60,
            derandomize=True,
            database=None,
            deadline=None,
            suppress_health_check=list(HealthCheck),
        )
        @given(catalogs())
        def holds(catalog):
            factors, t, forbidden = catalog
            ext, _ = _brute_force_engine(factors, forbidden)
            rows = _ipog.generate(factors, t, ext)
            missing, invalid = _ipog.check_cover(factors, rows, t, ext)
            assert missing == [] and invalid == []

        holds()


# ---------------------------------------------------------------------------
# hunt
# ---------------------------------------------------------------------------


@needs_hypothesis
class TestHunt:
    def test_drone_catch_shrinks_and_bisects(self, drone):
        report = verify.hunt(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
            seed=0,
        )
        assert report.status == "violated"
        assert report.seed == 0
        assert "takeoffMassLimit [assert]" in report.violations
        ce = report.counterexamples[0]
        assert ce.source == "hunt"
        assert ce.bindings["payloadMass"] > 0.29
        edges = {b.violated: b.value for b in report.boundaries}
        # the exact interpreter-bisected edges (closed forms: 0.29 kg from
        # the takeoff budget; ~2.1841 kg where four rotors stop out-lifting)
        assert edges["takeoffMassLimit [assert]"] == pytest.approx(0.29, abs=1e-6)
        if "canHover [assert]" in edges:  # found whenever sampling reached it
            assert edges["canHover [assert]"] == pytest.approx(2.184086, abs=1e-4)

    def test_catch_materializes_as_identified_individuals(self, drone):
        report = verify.hunt(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
            seed=0,
        )
        individual = report.counterexamples[0].materialize()
        assert individual.root.id == "Rotorcraft::QuadCopter#0"
        assert (
            individual.root.slots["payloadMass"]
            == report.counterexamples[0].bindings["payloadMass"]
        )
        values = verify.counterexample_values(report.counterexamples[0])
        assert values["totalMass"] > 1.5  # the measured violation, ready for the scoreboard

    def test_enum_strategy_participates_in_constraints(self):
        model = longeron.loads(DOMAIN_MODEL)
        report = verify.hunt(model, "Modes::Prop", free=("mode",), seed=0)
        assert report.status == "violated"
        assert report.violations == ["noSport [assert]"]
        assert report.counterexamples[0].bindings["mode"].name == "sport"

    def test_vacuous_ground_is_recorded_not_failed(self):
        model = longeron.loads(
            """
            package Fence {
                part def Thing {
                    attribute x : Real = 4.0;
                    attribute y : Real = 1.0;
                }
                requirement def Guarded {
                    subject t : Thing;
                    assume constraint { t.y > 0.0 }
                    require constraint sq { t.x * t.x >= 0.0 }
                }
            }
            """
        )
        report = verify.hunt(
            model, "Fence::Thing", ("Fence::Guarded",), free=("x", "y"), seed=0, max_examples=60
        )
        assert report.status == "clean"
        assert report.vacuous == ["Guarded"]  # y = 0.0 was sampled: vacuous, never failed
        assert any("vacuous" in gap for gap in report.gaps)

    def test_no_free_attributes_is_a_gap(self, drone):
        report = verify.hunt(drone, "Rotorcraft::QuadCopter")
        assert report.status == "clean"
        assert any("free=" in gap for gap in report.gaps)

    def test_fallback_domains_are_flagged(self):
        model = longeron.loads("package P { part def T { attribute x : Real = 0.0; } }")
        report = verify.hunt(model, "P::T", free=("x",), seed=0, max_examples=10)
        assert report.domains["x"].fallback
        assert any("fallback" in note for note in report.domains["x"].mined_from)


# ---------------------------------------------------------------------------
# sequences
# ---------------------------------------------------------------------------


@needs_hypothesis
class TestSequences:
    def test_minimal_sortie_on_the_shipped_drone(self, drone):
        report = verify.sequences(
            drone, "DeepScout::SortieStates", requirements=("DeepScout::SafeSortie",), seed=0
        )
        assert report.status == "violated"
        assert report.violations == ["SafeSortie::noDeepDischarge"]
        ce = report.counterexamples[0]
        assert ce.source == "sequences"
        # the go-around trap, shrunk to the 4-event minimal sortie
        assert ce.events == ("launch", "goAround", "goAround", "goAround")

    def test_sequence_catch_materializes_as_occurrences(self, drone):
        report = verify.sequences(
            drone, "DeepScout::SortieStates", requirements=("DeepScout::SafeSortie",), seed=0
        )
        interpretation = report.counterexamples[0].materialize()
        ids = [occ.id for occ in interpretation.root.slots["occurrences"]]
        assert any(occurrence.startswith("DeepScout::SortieStates::airborne") for occurrence in ids)

    def test_stock_flight_states_stay_clean(self, drone):
        # FlightStates only counts launches monotonically: nothing to catch
        report = verify.sequences(
            drone,
            "DeepScout::FlightStates",
            requirements=("DeepScout::SafeSortie",),
            max_examples=25,
        )
        assert report.status == "clean"
        assert report.counterexamples == []

    def test_eventless_machine_is_a_gap(self):
        model = longeron.loads(
            """
            package Still {
                state def Frozen {
                    entry; then only;
                    state only;
                }
            }
            """
        )
        report = verify.sequences(model, "Still::Frozen", requirements=())
        assert report.status == "clean"
        assert any("no event triggers" in gap for gap in report.gaps)


# ---------------------------------------------------------------------------
# cover
# ---------------------------------------------------------------------------


class TestCover:
    def test_pairwise_recall_measured_against_exhaustive(self, catalog):
        report = verify.cover(catalog, "ScoutSizing::TradeQuad", t=2)
        assert report.status == "violated"
        coverage = report.coverage
        assert coverage.t == 2
        assert coverage.exhaustive == 54
        assert coverage.recall == 1.0  # measured, interpreter-exact
        assert len(coverage.rows) < 54
        missing, invalid = _ipog.check_cover(
            [(n, tuple(sorted({row[n] for row in coverage.rows}))) for n in coverage.rows[0]],
            coverage.rows,
            2,
        )
        assert missing == [] and invalid == []

    def test_rows_are_interpreter_settled_selection_dicts(self, catalog):
        report = verify.cover(catalog, "ScoutSizing::TradeQuad", t=2)
        from longeron.analysis.trades import TradeStudy

        study = TradeStudy(catalog, "ScoutSizing::TradeQuad")
        for ce in report.counterexamples:
            arch = study.evaluate(ce.selection)
            assert tuple(arch.violations) == ce.violated

    @needs_z3
    def test_assumed_build_rules_are_enforced_by_z3(self, catalog):
        assume = ("cellMatch", "escCells", "propFit", "escCurrent")
        report = verify.cover(catalog, "ScoutSizing::TradeQuad", t=2, assume=assume)
        # every generated row satisfies the assumed compatibility rules;
        # the system requirements stay under test and are still caught
        for ce in report.counterexamples:
            assert not set(ce.violated) & set(assume)
        assert set(report.violations) == {"thrustMargin", "enduranceReq"}
        assert report.coverage.recall == 1.0

    def test_unknown_assume_name_is_refused(self, catalog):
        with pytest.raises(AnalysisError, match="assume="):
            verify.cover(catalog, "ScoutSizing::TradeQuad", assume=("noSuchRule",))

    def test_nonlinear_catalog_recall_still_measured(self, uav):
        # the 4800-mix space outgrew the default 4096 census cap when
        # the flying wings joined, and the tip-prop variant grew it to
        # 5280; the explicit cap keeps ground truth measured (and the
        # default-cap behavior -- recall honestly unmeasured -- is
        # pinned just below)
        report = verify.cover(uav, "ScoutMissions::IsrUav", t=2, exhaustive_cap=5280)
        assert report.coverage.exhaustive == 5280
        # the crossed catalog makes every violation class pairwise-
        # visible (a small motor on a heavy shell trips isrLift in one
        # pair), so the measured recall reports full coverage -- against
        # the 5280-mix exhaustive census, from a ~50-row array
        assert report.coverage.recall == 1.0
        assert "isrLift" in report.violations
        assert "cellMatch" in report.violations  # the class axis, caught
        assert len(report.coverage.rows) < 60
        assert report.status == "violated"

    def test_recall_honestly_unmeasured_past_the_census_cap(self, uav):
        report = verify.cover(uav, "ScoutMissions::IsrUav", t=2)
        assert report.coverage.exhaustive is None
        assert report.coverage.recall is None
        assert report.status == "violated"  # the catches are still real

    def test_cover_catch_materializes_via_from_architecture(self, catalog):
        report = verify.cover(catalog, "ScoutSizing::TradeQuad", t=2)
        ce = report.counterexamples[0]
        interpretation = ce.materialize()
        assert interpretation.selection  # variant pins recorded per point
        assert interpretation.root.slots["motors"]  # populated individuals


# ---------------------------------------------------------------------------
# prove
# ---------------------------------------------------------------------------


@needs_z3
class TestProve:
    def test_absence_proofs_and_exact_bounds(self, drone):
        report = verify.prove(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
        )
        by_name = {p.requirement: p for p in report.proofs}
        # inside the takeoff-mass budget, hoverMargin violations are
        # IMPOSSIBLE -- a proof no amount of sampling can deliver
        assert by_name["FlightEnvelope::hoverMargin [require]"].status == "proven-safe"
        assert by_name["QuadCopter::canHover"].status == "proven-safe"
        # nothing in the model forbids overloading past the budget itself
        assert by_name["QuadCopter::takeoffMassLimit"].status == "violation"
        assert report.status == "violated"
        proof = report.proofs[0]
        assert proof.bound == "29/100"  # exact rational: max payload, 0.29 kg
        assert proof.binding_constraint == "QuadCopter::takeoffMassLimit"

    def test_witnesses_are_interpreter_confirmed(self, drone):
        report = verify.prove(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
        )
        ce = report.counterexamples[0]
        assert ce.source == "prove"
        assert "takeoffMassLimit [assert]" in ce.violated
        individual = ce.materialize()
        assert individual.root.slots["totalMass"] > 1.5

    def test_fully_proven_requirement_reports_proven(self):
        model = longeron.loads(
            """
            package Safe {
                part def Box { attribute x : Real = 1.0; }
                requirement def Bounded {
                    subject b : Box;
                    assume constraint { b.x >= 0.0 and b.x <= 5.0 }
                    require constraint headroom { b.x <= 10.0 }
                }
            }
            """
        )
        report = verify.prove(model, "Safe::Box", ("Safe::Bounded",), free=("x",))
        assert report.status == "proven"
        assert report.proofs[0].status == "proven-safe"

    def test_anonymous_assume_reaches_the_solver(self):
        # regression for the encoder gap: an unnamed assume used to be
        # dropped silently, turning this proof into a spurious witness
        model = longeron.loads(
            """
            package Anon {
                part def Box { attribute x : Real = 1.0; }
                requirement def Shifted {
                    subject b : Box;
                    assume constraint { b.x >= 0.0 }
                    require constraint pos { b.x + 1.0 >= 1.0 }
                }
            }
            """
        )
        report = verify.prove(model, "Anon::Box", ("Anon::Shifted",), free=("x",))
        assert report.proofs[0].status == "proven-safe"
        assert report.status == "proven"

    def test_smt_labels_carry_the_anonymous_assume(self, drone):
        from longeron.analysis import smt

        system = smt.to_smt(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
        )
        labels = [label for label, _ in system.assertions]
        assert "FlightEnvelope::<assume> [assume]" in labels

    def test_encoder_refusals_are_recorded(self, uav):
        # freeing emptyMassKg makes the hover-power pow chain symbolic:
        # the honest refusal lands in gaps, the signal to fall back to hunt
        report = verify.prove(
            uav,
            "ScoutSizing::IsrPrime",
            requirements=("ScoutSizing::IsrStation",),
            free=("emptyMassKg",),
        )
        assert any("not encodable" in gap for gap in report.gaps)
        # any witness Z3 proposed from the degraded encoding must NOT have
        # been believed: no violation without interpreter confirmation
        assert all(
            proof.status in ("proven-safe", "unknown") or report.counterexamples
            for proof in report.proofs
        )


# ---------------------------------------------------------------------------
# the umbrella + CI posture
# ---------------------------------------------------------------------------


class TestVerifyUmbrella:
    def test_state_machine_scope_dispatches_to_sequences(self, drone):
        if not HAS_HYPOTHESIS:
            pytest.skip("needs the verify extra (pip install 'longeron[verify]')")
        report = verify.verify(
            drone, "DeepScout::SortieStates", requirements=("DeepScout::SafeSortie",), seed=0
        )
        assert report.counterexamples[0].events == (
            "launch",
            "goAround",
            "goAround",
            "goAround",
        )

    def test_variation_scope_dispatches_to_cover(self, catalog):
        report = verify.verify(catalog, "ScoutSizing::TradeQuad", seed=0)
        assert report.coverage is not None
        assert report.status == "violated"

    @needs_z3
    def test_part_scope_merges_hunt_and_prove(self, drone):
        report = verify.verify(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
            seed=0,
        )
        assert report.status == "violated"
        assert report.proofs  # prove ran and contributed
        if HAS_HYPOTHESIS:
            assert report.counterexamples[0].source == "hunt"
            assert report.boundaries
        else:
            assert any("hunt skipped" in gap for gap in report.gaps)

    def test_non_part_scope_is_refused(self, drone):
        with pytest.raises(AnalysisError, match="not verifiable"):
            verify.verify(drone, "DeepScout::FlightMode")

    @pytest.mark.skipif(HAS_HYPOTHESIS, reason="exercises the CI posture: no hypothesis installed")
    def test_missing_extra_degrades_to_a_gap(self, drone):
        from longeron.errors import MissingExtraError

        with pytest.raises(MissingExtraError, match="longeron\\[verify\\]"):
            verify.hunt(drone, "Rotorcraft::QuadCopter", free=("payloadMass",))
        report = verify.verify(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            free=("payloadMass",),
        )
        assert any("hunt skipped" in gap for gap in report.gaps)


class TestCounterexample:
    def test_materialize_without_context_is_refused(self):
        with pytest.raises(AnalysisError, match="materialization context"):
            verify.Counterexample().materialize()
