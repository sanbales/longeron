"""The generative conformance tier: property-based testing of the toolchain.

Design: ``docs/design/conformance.md``, "Generative tier".  Where
``tests/test_rejection.py`` pins hand-written negative cases, this file
*generates* models with Hypothesis and asserts toolchain-wide invariants
over them.  Three property families:

- **A -- never crash.**  Valid-by-construction generated text must parse,
  build, and validate clean (the guard property -- a failure here is a
  strategy bug or a real toolchain bug, both actionable).  Adversarial
  text (valid text pushed through character/token-level corruption) must
  produce ``ParseError``/``BuildError`` or diagnostics -- never an
  unhandled traceback.
- **B -- round-trip invariants.**  ``to_sysml -> loads -> to_sysml`` is a
  fixpoint; ``to_json``/``from_json`` is lossless; ``validate()`` yields
  no new diagnostics after a round-trip; element counts and qualified
  names are stable.  The suite previously pinned these only on hand
  examples.
- **C -- mutation invalidity.**  A catalog of invalidating mutations
  (``tests/_model_strategies.py:MUTATIONS``), each tied to one spec/pilot
  rule: mutants longeron enforces must stay rejected, diagnosed ones must
  stay diagnosed, and known-gap mutants (accepted silently although the
  reference rejects them) are pinned as strict xfails in the rejection
  suite -- here they are only required not to crash.

CI posture: hypothesis is NOT a project dependency -- without it this
file skips cleanly.  With it, properties run derandomized at
``max_examples <= 100``.  The deep-sweep posture (exploratory, high
example counts, fresh seeds) is selected with
``LONGERON_GENERATIVE_PROFILE=deep``.
"""

import copy
import os

import pytest

pytest.importorskip("hypothesis")

from _model_strategies import (
    MUTATIONS,
    adversarial_texts,
    model_trees,
    render_model,
)
from hypothesis import HealthCheck, assume, given, settings

import longeron
from longeron import BuildError, ParseError, validate

# ---------------------------------------------------------------------------
# profiles: derandomized CI runs by default; deep sweeps opt in via env
# ---------------------------------------------------------------------------

_DEEP = os.environ.get("LONGERON_GENERATIVE_PROFILE", "ci") == "deep"
_HEALTH = [HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much]

settings.register_profile(
    "generative-ci", derandomize=True, deadline=None, suppress_health_check=_HEALTH
)
settings.register_profile(
    "generative-deep",
    derandomize=False,
    deadline=None,
    print_blob=True,  # reproduction blobs replace the example database ...
    database=None,  # ... which would otherwise litter .hypothesis/ in the repo
    suppress_health_check=_HEALTH,
)
settings.load_profile("generative-deep" if _DEEP else "generative-ci")


def _examples(ci_count: int, deep_factor: int = 20) -> int:
    assert ci_count <= 100  # the CI-time discipline; deep sweeps scale it
    return ci_count * deep_factor if _DEEP else ci_count


def _diag_keys(diags) -> list[tuple[str, str, str]]:
    return sorted((d.severity, d.code, d.element) for d in diags)


# ---------------------------------------------------------------------------
# family A: never crash
# ---------------------------------------------------------------------------


@given(tree=model_trees())
@settings(max_examples=_examples(100))
def test_generated_models_are_valid_by_construction(tree):
    """The guard: generated text parses, builds, and validates clean.

    Every reference the strategies emit points at a declared name, so any
    diagnostic here is either a strategy bug (ours) or a toolchain bug
    (a finding) -- both must fail the suite.
    """

    text = render_model(tree)
    model = longeron.loads(text)  # must not raise
    diags = validate(model)
    assert not diags, f"generated-valid model diagnosed: {[str(d) for d in diags]}\n{text}"


@given(text=adversarial_texts())
@settings(max_examples=_examples(100, deep_factor=40))
def test_adversarial_text_never_crashes(text):
    """Corrupted text is rejected cleanly or survives the full pipeline.

    The only acceptable outcomes are ``ParseError``/``BuildError`` or a
    successful build (the corruption may keep the text valid) -- in which
    case validation and both exporters must also not raise.  Any other
    exception is an unhandled-crash finding; hypothesis shrinks the
    corrupted text to a minimal reproducer.
    """

    try:
        model = longeron.loads(text)
    except (ParseError, BuildError):
        return  # clean rejection
    validate(model)
    longeron.to_sysml(model)
    longeron.to_dict(model)


# ---------------------------------------------------------------------------
# family B: round-trip invariants on generated valid models
# ---------------------------------------------------------------------------


@given(tree=model_trees())
@settings(max_examples=_examples(60))
def test_textual_round_trip_reaches_fixpoint(tree):
    """``to_sysml -> loads -> to_sysml`` is a fixpoint, structure intact."""

    model1 = longeron.loads(render_model(tree))
    text1 = longeron.to_sysml(model1)
    model2 = longeron.loads(text1, source_name="<reprint>")
    assert longeron.to_sysml(model2) == text1
    d1, d2 = longeron.to_dict(model1), longeron.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2


@given(tree=model_trees())
@settings(max_examples=_examples(60))
def test_json_round_trip_is_lossless(tree):
    """``to_json -> from_json`` preserves structure, counts, and names."""

    model1 = longeron.loads(render_model(tree))
    model2 = longeron.from_json(longeron.to_json(model1))
    d1, d2 = longeron.to_dict(model1), longeron.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2
    tree1, tree2 = list(model1.iter_tree()), list(model2.iter_tree())
    assert len(tree1) == len(tree2)
    qnames1 = sorted(e.qualified_name for e in tree1 if e.qualified_name)
    qnames2 = sorted(e.qualified_name for e in tree2 if e.qualified_name)
    assert qnames1 == qnames2


@given(tree=model_trees())
@settings(max_examples=_examples(40))
def test_validation_is_stable_across_round_trips(tree):
    """Round-tripping (text and JSON) must not mint new diagnostics."""

    model1 = longeron.loads(render_model(tree))
    baseline = _diag_keys(validate(model1))
    reprinted = longeron.loads(longeron.to_sysml(model1), source_name="<reprint>")
    assert _diag_keys(validate(reprinted)) == baseline
    rehydrated = longeron.from_json(longeron.to_json(model1))
    assert _diag_keys(validate(rehydrated)) == baseline


# ---------------------------------------------------------------------------
# family C: the invalidating-mutation catalog
# ---------------------------------------------------------------------------


def _verdict(text: str) -> str:
    """First-objecting-layer verdict; crashes propagate to the test."""

    try:
        model = longeron.loads(text)
    except ParseError:
        return "parse-error"
    except BuildError:
        return "build-error"
    diags = validate(model)
    if any(d.severity == "error" for d in diags):
        return "error-diagnostic"
    if diags:
        return "warning-only"
    return "accepted-silent"


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m.id for m in MUTATIONS])
def test_mutation_catalog(mutation):
    """Each invalidating mutation lands on its expected verdict class."""

    @given(tree=model_trees(include=mutation.requires))
    @settings(max_examples=_examples(15))
    def property_(tree):
        mutant = copy.deepcopy(tree)
        assume(mutation.apply(mutant))
        verdict = _verdict(render_model(mutant))
        if mutation.expectation == "error":
            assert verdict in {"parse-error", "build-error", "error-diagnostic"}, (
                f"[{mutation.id}] must be rejected (rule: {mutation.rule}); got {verdict}:\n"
                f"{render_model(mutant)}"
            )
        elif mutation.expectation == "diagnosed":
            assert verdict != "accepted-silent", (
                f"[{mutation.id}] must at least be diagnosed (rule: {mutation.rule}):\n"
                f"{render_model(mutant)}"
            )
        # "gap": accepted silently today; the strict xfail in
        # tests/test_rejection.py owns the promotion pressure.  Reaching
        # this line at all proves the mutant did not crash the toolchain.

    property_()


# ---------------------------------------------------------------------------
# catalog hygiene
# ---------------------------------------------------------------------------


def test_every_mutation_names_its_rule():
    for mutation in MUTATIONS:
        assert mutation.rule.strip(), f"mutation {mutation.id} names no violated rule"
    ids = [m.id for m in MUTATIONS]
    assert len(ids) == len(set(ids))


def test_gap_mutations_are_pinned_in_the_rejection_suite():
    """Every catalog gap references a strict-xfail case in test_rejection.py.

    This is the wiring that keeps the two suites honest together: a gap
    found here must be pinned there, and a check landing there (xpass ->
    failure -> case promotion) leaves the catalog entry pointing at a
    promoted case, which this test then flags for re-classification.
    """

    from test_rejection import KNOWN_GAPS

    known_gap_ids = {case.id for case in KNOWN_GAPS}
    for mutation in MUTATIONS:
        if mutation.expectation == "gap":
            assert mutation.pinned_case in known_gap_ids, (
                f"catalog gap [{mutation.id}] pins case [{mutation.pinned_case}], which is "
                "not (or no longer) a KNOWN_GAPS case in tests/test_rejection.py -- "
                "add the pin, or re-classify the mutation if the check landed"
            )
        else:
            assert mutation.pinned_case is None, (
                f"non-gap mutation [{mutation.id}] must not pin a rejection case"
            )
