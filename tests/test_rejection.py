"""The rejection suite: invalid SysML v2 that longeron must NOT accept.

The corpus half of ``docs/design/conformance.md``.  The 309/309 corpus
badge is a positive-only acceptance claim; this suite is the negative
direction: every case here violates a named rule of the SysML v2 spec
(or, where the spec text is thin, a named validation rule of the OMG
pilot implementation), and longeron must reject it -- with a
``ParseError``, a ``BuildError``, or an error-severity diagnostic from
``validate()``.  Warnings do not count as rejection.

Four buckets (see the design doc for the rationale):

- ``PARSE_REJECTIONS``   -- must raise ``ParseError`` with a usable
  location.  All pass today.
- ``SEMANTIC_REJECTIONS`` -- must produce an error-severity diagnostic
  with the expected code.  All pass today.
- ``WARNING_DIAGNOSED``  -- the reference implementation errors here;
  longeron diagnoses but as a warning (a deliberate stance, held as an
  open question in the design doc).  The test asserts the diagnostic
  exists; severity is documented, not asserted.
- ``KNOWN_GAPS``         -- longeron currently ACCEPTS these silently
  although the spec rejects them.  Each is ``xfail(strict=True)``: the
  suite is green today, the gaps are visible and counted, and the
  moment a check lands for one of them the xpass fails the suite until
  the case is promoted to ``SEMANTIC_REJECTIONS``.  No papering over.

Every case carries ``rule``: the spec clause / validation-rule name it
violates (``validate*``/``check*`` names are the spec's own clause-8.3
constraint names; ``pilot:`` prefixes name the pilot implementation's
validator rules where the spec text is thin).
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

import longeron
from longeron import BuildError, ParseError, validate


@dataclass(frozen=True)
class Case:
    id: str
    source: str
    rule: str  # the one rule this case violates, with its citation
    code: str | None = None  # expected longeron diagnostic code, where one exists

    def __str__(self) -> str:  # pragma: no cover - pytest ids
        return self.id


# ---------------------------------------------------------------------------
# Bucket 1: must raise ParseError (all pass today)
# ---------------------------------------------------------------------------

PARSE_REJECTIONS = [
    # -- token garbage and unterminated constructs
    Case("syntax-garbage", "part def )( garbage", "no production derives these tokens"),
    Case(
        "def-without-declaration",
        "package P { part def }",
        "spec 8.2.2.6 Definition requires DefinitionDeclaration",
    ),
    Case(
        "unclosed-body",
        "package P { part def X;",
        "spec 8.2.2.5 PackageBody requires the closing '}'",
    ),
    Case(
        "stray-close-brace", "package P; }", "no production derives a '}' after a completed member"
    ),
    Case(
        "typing-without-type",
        "package P { part p : ; }",
        "spec 8.2.2.6 FeatureTyping requires a Type reference",
    ),
    Case(
        "malformed-real-literal",
        "package P { attribute x = 1.2.3; }",
        "KerML 8.2.2 LiteralReal: one decimal point",
    ),
    Case(
        "unterminated-quoted-name",
        "package P { part def 'Unterminated; }",
        "KerML 8.2.2 unrestricted name must close its quote",
    ),
    Case(
        "comment-without-body",
        "package P { comment /* unclosed }",
        "KerML 8.2.2 Comment requires a terminated body",
    ),
    # -- keyword misuse
    Case("keyword-as-def-name", "part def part;", "KerML 7.2.4: a reserved word is not a Name"),
    Case(
        "keyword-as-alias-name",
        "package P { alias part for Q; }",
        "KerML 7.2.4: a reserved word is not a Name",
    ),
    Case(
        "kerml-class-in-sysml",
        "package P { class C; }",
        "'class' is a KerML production; SysML 8.2.2 has none",
    ),
    Case(
        "kerml-specialization-element-in-sysml",
        "package P { specialization S subtype A specializes B; }",
        "KerML 8.2.2 Specialization element; SysML 8.2.2 has no such production",
    ),
    # -- mandatory element omitted
    Case(
        "alias-without-for",
        "package P { alias X; }",
        "spec 8.2.2.5 AliasMember requires 'for' QualifiedName",
    ),
    Case(
        "value-without-expression",
        "package P { attribute x = ; }",
        "spec 8.2.2.6 FeatureValue requires an expression",
    ),
    Case(
        "prefix-metadata-without-name",
        "package P { #; part p; }",
        "spec 8.2.2.24 PrefixMetadataMember requires a reference",
    ),
    Case(
        "flow-without-target",
        "package P { action def A { flow from a; } }",
        "spec 8.2.2.15 FlowConnectionUsage requires both ends",
    ),
    Case(
        "transition-without-target",
        "state def S { state a; transition first a; }",
        "spec 8.2.2.17 TransitionUsage requires 'then' TransitionSuccessionMember",
    ),
    # -- clause in a position the production forbids
    Case(
        "entry-outside-state",
        "package P { part def X { entry; } }",
        "spec 8.2.2.17: EntryActionMember only in a state body",
    ),
    Case(
        "requirement-clause-outside-requirement",
        "part def D { assume constraint c; }",
        "spec 8.2.2.19: RequirementConstraintMember only in requirement-style bodies",
    ),
    Case(
        "control-node-at-package-level",
        "package P { fork f; }",
        "validateControlNodeOwningType (spec p. 317): control nodes live in actions",
    ),
    Case(
        "multiplicity-on-definition",
        "package P { part def D [3]; }",
        "spec 8.2.2.6 Definition takes no OwnedMultiplicity",
    ),
    Case(
        "part-usage-in-enum-body",
        "package P { enum def E { part p; } }",
        "spec 8.2.2.8 EnumerationBody admits only enumerated values",
    ),
    # -- multiplicity notation
    Case(
        "negative-multiplicity",
        "package P { part def D; part p : D[-1]; }",
        "spec 8.2.2.6 MultiplicityRange over literal/name bounds",
    ),
    Case(
        "three-bound-multiplicity",
        "package P { part p[1..2..3]; }",
        "spec 8.2.2.6 MultiplicityRange: at most two bounds",
    ),
    # -- import notation
    Case(
        "doubled-import-visibility",
        "package P { private private import Q::*; }",
        "spec 8.2.2.5.2 Import: one VisibilityIndicator",
    ),
    # -- dialect notation with no spec production (opensysml shipped, warned, then removed these)
    Case(
        "initial-state-marker",
        "state def S { initial s0; state s0; }",
        "no production; spec spells it 'entry; then s0;'",
    ),
    Case(
        "transition-src-to-tgt",
        "state def S { state a; state b; transition a to b; }",
        "no production; spec 8.2.2.17 spells it 'first a then b'",
    ),
    Case(
        "region-member",
        "package P { part def D { region r; } }",
        "no production; spec spells concurrency 'state ... parallel'",
    ),
]

# ---------------------------------------------------------------------------
# Bucket 2: must produce an error-severity diagnostic (all pass today)
# ---------------------------------------------------------------------------

SEMANTIC_REJECTIONS = [
    Case(
        "duplicate-member-names",
        "package P { part def X; part def X; }",
        "KerML validateNamespaceDistinguishability: owned member names must be distinct",
        code="duplicate-name",
    ),
    Case(
        "duplicate-across-kinds",
        "package P { attribute a : Real; attribute a : Integer; }",
        "KerML validateNamespaceDistinguishability",
        code="duplicate-name",
    ),
    Case(
        "alias-clashes-with-member",
        "package P { part def X; alias X for X2; }",
        "KerML validateNamespaceDistinguishability: aliases share the namespace",
        code="duplicate-name",
    ),
    Case(
        "duplicate-short-names",
        "package P { part def <X> Long1; part def <X> Long2; }",
        "KerML validateNamespaceDistinguishability: short names count",
        code="duplicate-name",
    ),
    Case(
        "specialization-cycle",
        "package P { part def A :> B; part def B :> A; }",
        "KerML: specialization must be acyclic (Type::supertypes partial order)",
        code="specialization-cycle",
    ),
    Case(
        "self-specialization",
        "package P { part def D :> D; }",
        "KerML: specialization must be acyclic",
        code="specialization-cycle",
    ),
    Case(
        "transition-to-undeclared-state",
        "state def S { entry; then ghost; state on; }",
        "a transition's target must be a vertex of its own machine",
        code="unknown-state",
    ),
]

# ---------------------------------------------------------------------------
# Bucket 3: reference errors, longeron warns (severity stance: design doc)
# ---------------------------------------------------------------------------

WARNING_DIAGNOSED = [
    Case(
        "typed-by-undefined",
        "package P { part p : NoSuchDef; }",
        "unresolved FeatureTyping target; the pilot reports an error",
        code="unresolved-reference",
    ),
    Case(
        "specializes-undefined",
        "package P { part def D :> Absent; }",
        "unresolved Specialization target; the pilot reports an error",
        code="unresolved-reference",
    ),
    Case(
        "import-of-nothing",
        "package P { private import Missing::*; }",
        "unresolved Import target; the pilot reports an error",
        code="unresolved-reference",
    ),
    Case(
        "redefines-nothing",
        "package P { part def B; part def C :> B { attribute :>> nope = 3; } }",
        "unresolved Redefinition target; the pilot reports an error",
        code="unresolved-reference",
    ),
    Case(
        "connector-ends-unresolved",
        "package P { part def D { connect a to b; } }",
        "unresolved connector ends; the pilot reports an error",
        code="unresolved-reference",
    ),
]

# ---------------------------------------------------------------------------
# Bucket 4: KNOWN GAPS -- accepted silently today, spec-invalid.
# xfail(strict=True): when a check lands, promote the case to bucket 2.
# ---------------------------------------------------------------------------

KNOWN_GAPS = [
    # kind-nesting / compositeness
    Case(
        "state-in-attribute-def",
        "package P { attribute def A { state s; } }",
        "validateAttributeDefinitionFeatures (spec p. 278): all features of an "
        "AttributeDefinition must be non-composite",
    ),
    Case(
        "part-in-attribute-def",
        "package P { attribute def A { part p; } }",
        "validateAttributeDefinitionFeatures (spec p. 278)",
    ),
    Case(
        "state-in-attribute-usage",
        "package P { attribute a : Real { state s; } }",
        "validateAttributeUsageFeatures (spec p. 279): all features of an "
        "AttributeUsage must be non-composite",
    ),
    Case(
        "composite-part-in-port-def",
        "package P { part def D; port def Q { part p : D; } }",
        "pilot:validatePortDefinitionOwnedUsagesNotComposite: 'Owned usages of a "
        "port definition (other than ports) must be referential'",
    ),
    Case(
        "non-port-interface-ends",
        "package P { part def W; interface def I { end w1 : W; end w2 : W; } }",
        "pilot:validateInterfaceDefinitionEnd_: 'An interface definition end must be a port'",
    ),
    # kind-typing
    Case(
        "part-typed-by-attribute-def",
        "package P { attribute def A; part p : A; }",
        "validatePartUsagePartDefinition (spec p. 291): at least one itemDefinition "
        "of a PartUsage must be a PartDefinition",
    ),
    Case(
        "attribute-typed-by-part-def",
        "package P { part def D; attribute a : D; }",
        "checkAttributeUsageDataTypeSpecialization (spec p. 404); "
        "pilot:validateAttributeUsageType_: 'An attribute must be typed by attribute definitions'",
    ),
    Case(
        "action-typed-by-part-def",
        "package P { part def D; action a : D; }",
        "pilot:validateActionUsageType_: 'An action must be typed by action definitions'",
    ),
    Case(
        "part-typed-by-package",
        "package P { part p : P; }",
        "KerML: FeatureTyping::type must be a Type; a Package is not; "
        "pilot:validateUsageType_: 'A usage must be typed by definitions'",
    ),
    Case(
        "metadata-typed-by-part-def",
        "package P { part def Meta; #Meta part p; }",
        "pilot:validateMetadataUsageType_: metadata must be typed by metadata definitions",
    ),
    # reference-kind and deep-reference resolution
    Case(
        "feature-chain-to-nothing",
        "package P { part def D { attribute m : Real; } part d : D; attribute t = d.nope; }",
        "a feature chain must resolve through each step; 'nope' is not a member of D",
    ),
    Case(
        "qualified-reference-to-nothing",
        "package P { part def D { attribute m : Real; } attribute t = P::D::nope; }",
        "a qualified name must resolve; 'nope' is not a member of P::D",
    ),
    Case(
        "undefined-enum-literal",
        "package P { enum def E { a; b; } attribute e : E = E::c; }",
        "a reference to an enumerated value must resolve; E has no literal 'c'",
    ),
    Case(
        "subsetting-a-package",
        "package P { part def D; part p subsets P; }",
        "KerML 8.3: Subsetting::subsettedFeature must be a Feature; a Package is not",
    ),
    Case(
        "exhibit-of-a-non-state",
        "package P { part def D { part a; exhibit a; } }",
        "validateExhibitStateUsageReference (spec p. 333): 'Must reference a state'",
    ),
    Case(
        "perform-of-a-non-action",
        "package P { attribute b : Real; part def D { perform b; } }",
        "pilot:validatePerformActionUsageReference: 'Must reference an action'",
    ),
    # multiplicity bound types
    Case(
        "real-multiplicity-bound",
        "package P { part def D; part p : D[1.5]; }",
        "KerML pilot:validateMultiplicityRangeResultTypes: 'Must have a Natural value'",
    ),
    Case(
        "string-multiplicity-bound",
        'package P { part def D; part p : D["two"]; }',
        "KerML pilot:validateMultiplicityRangeResultTypes: 'Must have a Natural value'",
    ),
    # variation modeling
    Case(
        "variant-outside-variation",
        "package P { part def D { variant part v; } }",
        "validateVariantMembershipOwningNamespace (spec p. 277): a variant's owning "
        "namespace must be a variation-point Definition or Usage",
    ),
    Case(
        "non-variant-in-variation",
        "package P { variation part def V { part notvariant; } }",
        "pilot:validateDefinitionVariationMembership: 'An owned usage of a "
        "variation must be a variant'",
    ),
    # cardinality of owned members
    Case(
        "two-entry-transitions",
        "state def S { entry; then a; entry; then b; state a; state b; }",
        "validateStateDefinitionStateSubactionKind (spec p. 336): at most one "
        "StateSubactionMembership of each kind",
    ),
    Case(
        "two-individual-definitions",
        "package P { individual part def I1; individual part def I2; individual part p : I1, I2; }",
        "validateOccurrenceUsageIndividualDefinition (spec p. 285): 'At most one "
        "individual definition is allowed'",
    ),
    Case(
        "enum-attribute-with-two-types",
        "package P { enum def E { a; } attribute e : E, E; }",
        "pilot:validateAttributeUsageEnumerationType_: 'An enumeration attribute "
        "cannot have more than one type'",
    ),
    # mandatory semantic arguments
    Case(
        "send-without-payload",
        "package P { action def A { send; } }",
        "pilot:validateSendActionUsagePayloadArgument: 'A send action must have a payload'",
    ),
]

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _diagnostics(source: str):
    model = longeron.loads(source)
    return validate(model)


def _rejects(source: str) -> bool:
    """True when longeron rejects ``source``: ParseError, BuildError, or an
    error-severity diagnostic.  Warnings do NOT count as rejection."""

    try:
        diags = _diagnostics(source)
    except (ParseError, BuildError):
        return True
    return any(d.severity == "error" for d in diags)


def _case_ids(cases: list[Case]) -> list[str]:
    return [case.id for case in cases]


# ---------------------------------------------------------------------------
# the tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", PARSE_REJECTIONS, ids=_case_ids(PARSE_REJECTIONS))
def test_parse_rejection(case: Case):
    with pytest.raises(ParseError) as exc:
        longeron.parse_sysml_text(case.source)
    # diagnostic quality: a located, non-empty message
    assert exc.value.issues, case.rule
    issue = exc.value.issues[0]
    assert issue.line >= 1 and issue.column >= 0, case.rule
    assert issue.message.strip(), case.rule


@pytest.mark.parametrize("case", SEMANTIC_REJECTIONS, ids=_case_ids(SEMANTIC_REJECTIONS))
def test_semantic_rejection(case: Case):
    diags = _diagnostics(case.source)
    errors = [d for d in diags if d.severity == "error"]
    assert any(d.code == case.code for d in errors), (
        f"expected an error-severity [{case.code}] diagnostic; rule: {case.rule}; "
        f"got: {[str(d) for d in diags]}"
    )


@pytest.mark.parametrize("case", WARNING_DIAGNOSED, ids=_case_ids(WARNING_DIAGNOSED))
def test_reference_problems_are_at_least_diagnosed(case: Case):
    # The pilot implementation errors on these; longeron's deliberate stance
    # is warning-severity (see the design doc's open question 1).  This test
    # pins detection only, so a future severity promotion does not break it.
    diags = _diagnostics(case.source)
    assert any(d.code == case.code for d in diags), (
        f"expected a [{case.code}] diagnostic; rule: {case.rule}; got: {[str(d) for d in diags]}"
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            case,
            marks=pytest.mark.xfail(
                strict=True,
                reason=f"KNOWN GAP -- accepted today, spec-invalid: {case.rule}",
            ),
        )
        for case in KNOWN_GAPS
    ],
    ids=_case_ids(KNOWN_GAPS),
)
def test_known_gap(case: Case):
    # Currently xfail: longeron accepts these silently.  strict=True means
    # the moment a check lands for one, this xpasses -> FAILS, forcing the
    # case's promotion to SEMANTIC_REJECTIONS in the same change.
    assert _rejects(case.source), case.rule


def test_no_duplicate_case_ids():
    all_cases = PARSE_REJECTIONS + SEMANTIC_REJECTIONS + WARNING_DIAGNOSED + KNOWN_GAPS
    ids = [case.id for case in all_cases]
    assert len(ids) == len(set(ids))


def test_counts_match_the_design_doc():
    # docs/design/conformance.md and the README state these numbers; keep
    # them honest (the cheap analog of opensysml's committed-baseline count
    # guards).  Update the docs when you update these.
    assert len(PARSE_REJECTIONS) == 28
    assert len(SEMANTIC_REJECTIONS) == 7
    assert len(WARNING_DIAGNOSED) == 5
    assert len(KNOWN_GAPS) == 24


def test_every_case_names_its_rule():
    # The opensysml corpus-header discipline: a case without the rule it
    # violates is not reviewable.  The harness refuses one.
    for case in PARSE_REJECTIONS + SEMANTIC_REJECTIONS + WARNING_DIAGNOSED + KNOWN_GAPS:
        assert case.rule.strip(), f"case {case.id} names no violated rule"
