# The OCL stance (design)

Goal: state, once, what longeron does with the OCL constraints that the
KerML/SysML v2 specifications embed in their metamodels — so that
"validation" claims stay precise and the next person asking "should we
run the spec's OCL?" finds the reasoning instead of re-deriving it.

## (a) Where OCL appears in the SysML v2 ecosystem

The OMG specs define semantic well-formedness as OCL invariants and
derivation rules attached to the metamodel. The vendored spec metamodel
(`src/longeron/_spec/SysML.ecore`) carries that OCL verbatim — inside
`documentation` annotations, next to the prose. It is reference
material: longeron never parses, type-checks, or evaluates it, and no
OCL engine appears anywhere in the dependency tree.

Separately, *user-facing* constraints in SysML v2 models (`constraint`,
`require`, calc bodies) are written in KerML expressions, not OCL —
longeron evaluates those natively in the interpreter. The OCL question
is only about the *spec's own* well-formedness rules.

## (b) What longeron validates instead

`longeron.validate` implements a curated, hand-written set of diagnostic
codes (documented exhaustively in the [validation guide](../guides/validation.md)):
duplicate names, specialization cycles, unresolved references/names with
stdlib-aware resolution and implied specializations, state-machine
sanity, calc-result checks, and the strict modes. Each check earns its
place by catching mistakes users actually make, with an actionable
message.

This is *not* spec-constraint conformance, and nothing in the docs
claims it is: the 309/309 corpus badge is **parsing** conformance
(every OMG training model parses without loss). The two axes are
independent and must not be conflated.

## (c) Options considered

1. **Evaluate the spec OCL directly** (an OCL engine over the pyecore
   projection). Rejected. The embedded OCL text is not mechanically
   reliable — the vendored ecore contains literal errors as shipped by
   the spec: `oclisKindOf` (casing, `SysML.ecore:879`),
   `AssigmentAction` (spelling, `:310`), `isEnd implied direction =
   null` (`implied` for `implies`, `:1685`). The OMG pilot
   implementation itself hand-codes constraint checks in Java rather
   than executing the OCL. An engine dependency would buy a large
   maintenance surface to evaluate rules that need per-rule human
   review anyway.
2. **Transcribe the spec constraints wholesale** into native checks.
   Rejected as a goal in itself: most spec invariants police metamodel
   shapes that longeron's typed builder cannot produce in the first
   place; transcribing them all would flood users with diagnostics
   about impossibilities.
3. **Curated native checks, spec OCL as reference** — the implemented
   behavior. Adopted below.

## (d) Consequences and future path

- New diagnostics continue to be judged by user value, not by spec
  coverage. When a spec invariant *does* motivate a check, the
  vendored OCL is the reference text and the check is implemented
  natively, in the existing `Diagnostic` machinery.
- If demand for deeper semantic checking materializes, the path is a
  **coverage table** (spec constraint → native check / deliberately
  skipped / spec-text defect), not an OCL engine. That table would
  live in this document.
- Docs discipline: conformance claims name their axis — "parsing
  conformance" for the corpus badge, "validation" only for the
  documented diagnostic codes.

## Decisions (adopted 2026-08-22)

1. **Longeron does not evaluate OCL** — the spec's OCL invariants stay
   reference material in the vendored ecore; no OCL engine, no OCL
   dependency.
2. **Validation is a curated native diagnostic set** — checks exist
   because they catch real modeling mistakes, each with an actionable
   message; the spec OCL informs but does not enumerate them.
3. **Conformance claims stay axis-precise** — corpus 309/309 is parsing
   conformance; semantic validation coverage is whatever the validation
   guide's table says, nothing more.
