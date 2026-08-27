# Conformance methodology (design)

> **Status: proposed.** Drafted 2026-08-27 alongside the first
> implementation slice (`tests/test_rejection.py`, the rejection
> suite). Every empirical claim about longeron below was measured at
> commit `2296290` with the vendored standard library attached; every
> claim about opensysml.org was read from the site and its repository
> documents on 2026-08-27. Open questions at the end carry
> recommendations; none block the phase-1 slice.

The maintainer's question, verbatim: *"are we checking that we raise
errors when bad models are provided? or are we just letting everything
pass?"* This document measures the answer (§ "Where longeron stands"),
studies how the most methodologically careful open SysML v2
implementation answers it (§ "The reference point"), and designs what
longeron should adopt (§ "The design"). The short version:

- The **parse layer is genuinely strict**: token garbage, keyword
  misuse, wrong-position clauses, and pseudostate dialect notation are
  all rejected with located, humanized errors.
- The **semantic layer is wide open**: kind-typing violations
  (`part p : SomeAttributeDef;`), wrong-kind nesting (a composite
  `state` inside an `attribute def`), non-natural multiplicity bounds
  (`[1.5]`, `["two"]`), unresolvable feature chains (`d.nope`),
  undefined enum literals, and every variation-modeling rule are
  **accepted silently**.
- The badge claims only acceptance. Nothing today counts, gates, or
  even lists what longeron fails to reject — that is what this design
  adds, cheapest slice first.

## What the 309/309 badge does and does not claim

`scripts/check_corpus.py` sweeps every `.sysml` file of the pinned
[SysML-v2-Release](https://github.com/Systems-Modeling/SysML-v2-Release)
corpus through `parse` + `build_model` and the badge states the result:
309 of 309 files parse and build. That is a **positive-only acceptance
claim** about files written to *demonstrate* the notation — almost all
of them valid by construction. It says nothing about:

- **Rejection.** A parser that accepted every byte string would score
  309/309. The corpus cannot distinguish a conformant parser from a
  permissive one.
- **Semantic conformance.** "Builds into the object model" does not
  mean the model means what the spec says it means.
- **Diagnostic quality.** A tool that rejects bad input with a useless
  message at the wrong location technically rejects it.

The existing negative surface, counted: 12 `pytest.raises(ParseError)`
sites and 5 `pytest.raises(BuildError)` sites repo-wide, plus
`tests/test_validation.py` (79 tests). The validation tests are real
and useful, but they are organized *per diagnostic code* — they prove
the checks longeron **has** fire correctly. Nothing is organized *per
spec rule* — nothing asks which rules the spec **requires** longeron to
enforce and measures the shortfall. The permissiveness table below is
exactly that measurement.

## The reference point: opensysml.org's methodology

[OpenSysML](https://opensysml.org) (Open-MBEE, a SysML v2/KerML
implementation in Go) publishes the most complete conformance
methodology of any open implementation. It has five instruments; the
value is less in any one of them than in the reporting discipline that
connects them.

### 1. Positive corpora gates

All 95 bundled standard-library files "must parse with zero
diagnostics" (a CI gate), 100 OMG training files are snapshot-tested,
and 107 golden AST fixtures plus 109 golden execution traces pin
behavior. They are explicit that the snapshot gate "answers 'did we
change?'; it cannot answer 'are we right?'". This is the instrument
longeron already has (the corpus sweep + grammar-patch regression
tests).

### 2. The pilot rejection oracle — the negative corpus

`cmd/pilot-reject` validates a hand-written negative corpus (120 cases)
with **both** their implementation and the pinned OMG pilot
implementation, and buckets every case:

| Bucket | Meaning |
|---|---|
| both-reject | agreement; the case is settled |
| pilot-only-rejects | **a permissiveness gap** — the finding the oracle exists to surface |
| ours-only-rejects | over-strictness; "already the differential's business" |
| both-accept | the case itself is wrong; "a corpus revision, not a finding" |

Three details are worth copying verbatim:

- **Every case names the one rule it violates.** "Every file's first
  line is a mandatory header — `// Invalid: <rule> (<citation>).` —
  naming the one rule the case violates and where that rule comes from;
  the harness refuses a corpus file without it."
- **Cases are derived systematically**, one subdirectory per source:
  *grammar mutation* (for each production the corpus exercises, "the
  minimal violation: a required keyword removed, a mandatory element
  omitted, a clause in a position the production forbids, a token from
  a sibling production, and unterminated bodies and comments"); *their
  own extensions* (notation they invented, tested strictly); and the
  *pilot's own negative expectations* (Xpect suites) re-derived as
  standalone models.
- **The denominator honesty.** "We authored all 120 cases ourselves, so
  the denominator measures our coverage of the rejection surface, not
  our conformance: it is a sample, not a proof — a clean bucket here
  does not mean OpenSysML rejects everything the reference rejects."

Warnings do not count as rejection in their harness, and extensions
they accept on purpose are judged under an opt-in strict mode — "a
case that agrees only because it was asked strictly is listed
separately, so a strict agreement never reads as a default one."

### 3. The pilot differential — diagnostics compared over shared corpora

`cmd/pilot-diff` runs the pinned pilot implementation (release 2026-05,
`jupyter-sysml-kernel 0.60.1`) and their own tool over the same 355
files and compares diagnostics. The oracle is two ~150-line Java
bridges over the pilot's *own* Xtext validators (provisioned through
the DeciSym `sysmlv2-validator` build; Java 21 + Maven), deliberately
thin: "a hand-written bridge into the pilot's Xtext internals would be
our interpretation of the reference rather than the reference."

Comparison granularity: each diagnostic is normalized to a tuple
`(file, line, severity, coarse category)` — categories are few (syntax,
unresolved-reference, kind-mismatch, multiplicity, units, unmapped) —
and compared as multisets. "Message wording will never match between
two implementations, so message text is never compared." A category
called `unmapped` is "load-bearing": a message that fits nothing stays
visible rather than being mapped to something adjacent "to make the
report look tidy". Files bucket into fully-agreeing / only-ours
(candidate false positives) / only-pilot (candidate gaps) /
severity-only. Crucially: "not every difference is our bug" — each
disagreement is *adjudicated* by hand against the pinned grammars, and
some verdicts are recorded as deliberate divergence.

### 4. Grammar production coverage — with unusual honesty

`cmd/grammar-coverage` parses the three pinned OMG Xtext grammars (727
productions, refined to 807 literal-bearing "forms") and asks, for each,
whether any corpus file contains the literals a path through it needs.
They label the result precisely: "**The number below is an
over-approximation, and it is not a coverage figure.** What it measures
is *input presence* … it does not prove our parser took that path, and
it does not prove we handled it correctly. The honest reading is the
negative one: where there is no evidence, no input has ever put us in a
position to be right." Their recommended follow-up — true execution
coverage — would require instrumenting every hand-written parse
function, which they deliberately did not do. (Longeron, with generated
ANTLR parsers, can get true coverage almost for free; see design part
(b).)

### 5. The conformance audit — per-construct adjudication

`conformance-audit.md` records "with file:line citations at the pinned
grammars, which words and constructs OpenSysML accepts are standard
(silent), which are our own extensions (warned), and which are
KerML-only in a `.sysml` file (warned)". Every judgment call is
recorded "so a reviewer can disagree with them". Their extension
notation stays accepted by default but an opt-in strict mode turns the
warnings into errors — and they are honest that "an opt-in check is
weaker evidence than a default one".

### The reporting discipline

Five habits recur across all instruments, and they are the real
methodology:

1. **Committed baselines, byte-identical runs.** Every oracle writes a
   deterministic JSON committed to the repo, so a later run diffs
   against it and doc counts are re-derived from it by a guard test.
2. **Advisory oracles, gating corpora.** The stdlib gate blocks CI; the
   differential, rejection and coverage oracles are explicitly
   advisory — "a coverage number that failed a build would be
   re-baselined into meaninglessness."
3. **Denominators are named.** Every percentage states what it is out
   of, and whether the denominator is externally derived or self-chosen.
4. **Severity is part of the claim.** Warnings never count as
   rejection; severity-only disagreements get their own bucket.
5. **Adjudication is recorded, not implied.** Divergences they keep are
   written down with the reason and the test that pins the refusal.

## Where longeron stands (measured)

All probes run at commit `2296290`: `parse_sysml_text` →
`build_model` → `validate()` (stdlib attached), verdict = the first
layer that objects. "ACCEPTED" means no exception and zero diagnostics
of either severity.

### The parse layer is strict

Everything below is correctly rejected today with a located,
humanized message — this is the part of the answer to the maintainer's
question that is already "yes":

| Probe | Verdict |
|---|---|
| token garbage, unclosed bodies, stray `}`, malformed literals (`1.2.3`) | ParseError |
| keyword as a name: `part def part;`, `alias part for Q;` | ParseError |
| wrong-position clause: `entry;` outside a state body, `assume` in a part def, control node (`fork f;`) at package level, multiplicity on a definition (`part def D [3];`) | ParseError |
| KerML-only notation in `.sysml`: `class C;`, `specialization S subtype …` | ParseError |
| mandatory element omitted: `alias X;` (no `for`), `flow from a;` (no `to`), `transition first a;` (no target), `attribute x = ;`, `#;` | ParseError |
| pseudostate dialect notation the spec has no production for: `initial s0;`, `region r;`, `transition a to b;` | ParseError |
| negative multiplicity bound `[-1]`, three-bound `[1..2..3]`, doubled visibility `private private import` | ParseError |
| non-usage member in an enum body: `enum def E { part p; }` | ParseError |

Notably, longeron *already* rejects the state-machine dialect notation
(`initial`, `region`, `transition <src> to <tgt>`) that opensysml had
invented, shipped, warned about, and eventually removed. The ANTLR
grammar's tight production set is doing real conformance work here.

### The semantic layer accepts what the spec rejects

The centerpiece. Every row below **parses, builds, and validates
clean** (zero diagnostics) today, yet violates a named rule of the
SysML v2 spec — the citations are the spec's own validation-rule names
(OMG *Systems Modeling Language v2.0*, clause 8.3.x abstract-syntax
constraints) and, where the spec text is thin, the pilot
implementation's validator rule (`SysMLValidator.xtend` /
`KerMLValidator.xtend` constants, whose messages are quoted):

| # | Source (abbreviated) | Violated rule | Reference behavior |
|---|---|---|---|
| 1 | `attribute def A { state s; }` | `validateAttributeDefinitionFeatures` — "All features of an AttributeDefinition must be non-composite" (spec p. 278) | error |
| 2 | `attribute def A { part p; }` | same rule (a composite part in a datatype) | error |
| 3 | `attribute a : Real { state s; }` | `validateAttributeUsageFeatures` — same for usages (spec p. 279) | error |
| 4 | `part p : D[1.5];` / `part p : D["two"];` | KerML `validateMultiplicityRangeResultTypes` — "Must have a Natural value" | error |
| 5 | `attribute def A; part p : A;` | `validatePartUsagePartDefinition` — "At least one of the itemDefinitions of a PartUsage must be a PartDefinition" (spec p. 291); pilot: "A part must be typed by item definitions" | error |
| 6 | `part def D; attribute a : D;` | pilot `validateAttributeUsageType_` — "An attribute must be typed by attribute definitions"; spec `checkAttributeUsageDataTypeSpecialization` (p. 404) | error |
| 7 | `part def D; action a : D;` | pilot `validateActionUsageType_` — "An action must be typed by action definitions" | error |
| 8 | `part p : P;` (P a package) | typing must reference a Type; pilot `validateUsageType_` — "A usage must be typed by definitions" | error |
| 9 | `part def Meta; #Meta part p;` | pilot `validateMetadataUsageType_` — metadata must be typed by metadata definitions | error |
| 10 | `attribute t = d.nope;` (no such member) | unresolved feature-chain reference | error |
| 11 | `enum def E { a; b; } … = E::c;` | unresolved reference to a nonexistent enum literal | error |
| 12 | `part p subsets P;` (P a package) | a Subsetting's `subsettedFeature` must be a Feature (KerML 8.3) | error |
| 13 | `part def D { variant part v; }` | `validateVariantMembershipOwningNamespace` — "The membershipOwningNamespace of a VariantMembership must be a variation-point Definition or Usage" (spec p. 277) | error |
| 14 | `variation part def V { part notvariant; }` | pilot `validateDefinitionVariationMembership` — "An owned usage of a variation must be a variant" | error |
| 15 | two `entry;` transitions in one state body | `validateStateDefinitionStateSubactionKind` — "must not have more than one owned StateSubactionMembership of each kind" (spec p. 336); pilot: "A state may have at most one entry action" | error |
| 16 | `interface def I { end w1 : W; end w2 : W; }` (W a part def) | pilot `validateInterfaceDefinitionEnd_` — "An interface definition end must be a port" | error |
| 17 | `port def Q { part p : D; }` | `validatePortDefinitionOwnedUsagesNotComposite` — "Owned usages of a port definition (other than ports) must be referential" | error |
| 18 | `part a; exhibit a;` | `validateExhibitStateUsageReference` — "Must reference a state" (spec p. 333) | error |
| 19 | `attribute b : Real; perform b;` | `validatePerformActionUsageReference` — "Must reference an action" | error |
| 20 | `action def A { send; }` | `validateSendActionUsagePayloadArgument` — "A send action must have a payload" | error |
| 21 | `individual part p : I1, I2;` | `validateOccurrenceUsageIndividualDefinition` — "At most one individual definition is allowed" (spec p. 285) | error |
| 22 | `attribute e : E, E;` (E an enum def) | pilot `validateAttributeUsageEnumerationType_` — "An enumeration attribute cannot have more than one type" | error |

Two more findings are about **severity**, not detection — longeron
diagnoses these but as warnings, where the pilot reports errors:

- Unresolved references of every role (`part p : NoSuchDef;`,
  `:> Absent`, `import Missing::*;`, `:>> nope`, connector ends) are
  `unresolved-reference` **warnings**. This is a deliberate longeron
  stance (documented in `longeron/validation.py`: "Unresolved
  references are *warnings*; structural problems … are errors"), made
  safer than it sounds by stdlib-aware resolution — but a user who
  filters for errors ships a model full of typos. Held as an open
  question below rather than a gap.

And two findings are **deliberate dialect divergences** already
documented in the grammar-patch table (`docs/guides/grammar.md`),
recorded here because the reference *rejects* them:

- `import Q::*;` without a visibility prefix. The release BNF (spec
  8.2.2.5.2) makes `visibility = VisibilityIndicator` **mandatory** on
  `Import`; the pinned pilot rejects a bare `import` as a syntax error,
  and opensysml — after shipping the permissive form — made it an
  error in every mode. Longeron's patch 1 deliberately accepts it
  because the spec's *own examples* (and common usage) write it.
- `action publish send X() via p;` (patch 8) and `#Security enum …`
  (patch 10), where the release BNF contradicts the pilot corpus and
  longeron follows the corpus.

What longeron does *right* on the semantic side today, for fairness:
duplicate member names (including via alias and short names) are
errors, specialization cycles (including self-specialization) are
errors, transitions to undeclared states are errors, and the
dimensional lint catches unit/scale violations no other open
implementation checks at all.

## The design

Four parts, adopted from the opensysml methodology in order of value
per unit cost. Part (a) ships with this document; (b)–(d) are
recommendations with effort estimates.

### (a) The rejection corpus — `tests/test_rejection.py` (phase 1, this change)

A negative suite in the opensysml mold, adapted to pytest:

- **Inline sources, not a corpus directory.** Their cases are `.sysml`
  files with a mandatory header comment; ours are Python dataclasses
  with mandatory `rule` (the spec/pilot citation) and `note` fields —
  the same discipline, but grep-able, parametrized, and requiring no
  file-discovery harness. If the corpus outgrows the file (≳150 cases
  or KerML cases arrive), promote to `tests/rejection/*.sysml` with the
  header convention and a loader, without changing the buckets.
- **Four buckets, mirroring the measurement above:**
  1. `PARSE_REJECTIONS` — must raise `ParseError`, and the error must
     carry a usable location (asserted). All pass today.
  2. `SEMANTIC_REJECTIONS` — must produce an **error**-severity
     diagnostic with the expected code from `validate()`. All pass
     today.
  3. `WARNING_DIAGNOSED` — the reference errors, longeron warns; the
     test asserts the diagnostic exists (any severity), and the
     severity stance is recorded here and in the open questions, not
     hard-coded into an assertion that would fight a severity change.
  4. `KNOWN_GAPS` — the permissiveness table above, as
     `pytest.mark.xfail(strict=True)` cases asserting rejection. Green
     today *as xfails*: visible, counted, and un-regressable —
     `strict=True` means the moment a validation check lands for one of
     them, the xpass **fails the suite** until the case is promoted to
     bucket 2. No case is ever papered over with a bare skip.
- **Warnings do not count as rejection** (bucket 4's helper accepts
  only `ParseError`, `BuildError`, or an error diagnostic), exactly the
  opensysml rule, so the gap count cannot be gamed by softening.
- **The denominator honesty, restated for us:** we authored every case,
  so "N/N rejections" measures our coverage of the rejection surface,
  not conformance. At this commit the buckets hold 28 / 7 / 5 / 24
  cases (the generative tier below later raised the fourth bucket to
  36). The counts are stated by the suite itself (a summary test
  asserts the bucket sizes match the doc's claim, the cheap analog of
  opensysml's count guards).

### (b) Production-coverage accounting (phase 2, recommended)

Opensysml's input-presence instrument is a workaround for a
hand-written parser. Longeron's parsers are **generated by ANTLR from
`grammars/*.g4`** (438 SysML parser rules, 280 KerML at this commit,
regenerated and diff-gated in CI), which makes *true* production
coverage cheap: every `ParserRuleContext` in a parse tree carries its
rule index, so one tree-walk per corpus file yields exact entered-rule
counts — the measurement opensysml explicitly wished for and could not
afford ("it needs counters in the parse functions … which is why it
was deliberately left out").

Recommended shape: a `scripts/grammar_coverage.py` sibling of
`check_corpus.py` that sweeps the same pinned corpus (plus the vendored
stdlib and the rejection suite's sources), walks each tree once, and
reports per-grammar entered/total rule counts plus the never-entered
rule list. Two honesty notes carry over: (1) entered ≠ correct — a rule
can be exercised and mishandled; (2) the denominator is *our* grammar,
which is the hivecore-derived `.g4` with ten local patches, not the
spec's BNF. A rule-name mapping to the spec's 8.2.2 productions (names
mostly align, since the `.g4` descends from the release BNF) is the
follow-up that would let the report cite spec productions directly.
Advisory only — a committed baseline JSON to diff, no CI gate, for
opensysml's stated reason ("a coverage number that failed a build would
be re-baselined into meaninglessness").

### (c) Differential testing against the pilot (assessed; deferred)

What it would take, concretely: Java 21 + Maven to build the DeciSym
`sysmlv2-validator` (which downloads the pinned pilot release), then a
runner that feeds it our corpus and the rejection corpus and compares
verdicts. Longeron CI already provisions a JDK (ANTLR regen job), but
not Maven, and the pilot jar + stdlib load is a heavyweight, slow
oracle (~minutes per sweep) with a real maintenance surface (pin
management, bridge upkeep — opensysml wrote and maintains two custom
Java bridges because the stock CLI validated files in a state-carrying
sequential session that made verdicts order-dependent).

Recommended posture: **periodic manual sweep, not CI.** The rejection
corpus is *designed for it* — every case already cites the rule and
predicts the reference verdict, so a future
`scripts/pilot_referee.py` can bucket cases into
both-reject / pilot-only / ours-only / both-accept and adjudicate our
annotations against the actual pilot instead of our reading of it. Do
this once the known-gaps list stops moving (after the first
validation-rule wave lands), and re-run per pilot release. A standing
vendored-oracle CI job is not worth its cost at longeron's scale
today; revisit if the corpus grows a semantic-differential ambition
(comparing evaluation results, not just accept/reject).

### (d) Reporting: what the badge story becomes

- The 309/309 badge keeps its exact meaning (acceptance) and its
  link target (`guides/grammar.md`) — never restated as "conformance".
- The README badge line gains a companion sentence stating the
  rejection suite and its two numbers: rejections enforced and known
  gaps (the xfail count). Both numbers are asserted by the suite's
  summary test, so the README can only drift one release before a
  human notices; if drift proves real, add a doc-count check to CI
  (the full opensysml `make docs-counts` discipline).
- `guides/grammar.md` gains a short "Rejection" section: what is
  enforced at parse vs validate, the severity stance, and the
  known-gaps count with a pointer to this document.
- Production coverage (b) reports percentages only once the true-
  coverage instrument exists; no input-presence numbers, ever — we can
  afford the real measurement, so the proxy would only mislead.
- Any future strict/pedantic mode reports its results separately from
  default-mode results (the opensysml rule: "a strict agreement never
  reads as a default one").

## Open questions for the maintainer

1. **Should `unresolved-reference` stay a warning?** The pilot errors
   on every unresolved reference; longeron warns by design and the
   stdlib fallback keeps the false-positive rate low.
   *Recommendation:* keep the warning default (it matches the tool's
   exploratory-notebook posture), but add a `strict=True` flag on
   `validate()` that promotes `unresolved-reference` (and only
   resolution codes) to errors, and have `longeron check` (CLI) grow
   `--strict`. The rejection suite's bucket 3 becomes bucket 2 under
   that flag. This is validation.py work — deliberately **not** in
   phase 1 (that file is owned by concurrent workstreams).
2. **Who closes the known gaps, and in what order?** The 22 gap rows
   above (24 suite cases: row 4 contributes two, and row 10's
   qualified-name variant is its own case) cluster into four checks: kind-typing (rows 5–9, one resolver-aware
   check), kind-nesting/compositeness (rows 1–3, 16–17), reference-kind
   checks (rows 10–12, 18–19), and cardinality/variation rules (rows
   4, 13–15, 20–22). *Recommendation:* kind-typing first — it is the
   likeliest real-model typo (`part p : SomeAttrDef;` from a rename)
   and one check closes five rows. Each check lands with its bucket-2
   promotion in the same commit (the strict xfail forces this).
3. **Is `[3..1]` invalid?** Deliberately absent from the corpus: the
   pilot has no lower ≤ upper rule (checked against
   `KerMLValidator.xtend` at the pin — only bound-type rules exist),
   so a `[3..1]` range is unsatisfiable but well-formed.
   *Recommendation:* follow the pilot (accept); a `possibly-empty`
   *lint* warning would be a longeron extension, labeled as such.
4. **Does bare `import` (patch 1) ever get flagged?** The spec BNF
   mandates the visibility prefix; the spec's own examples omit it;
   the pilot and opensysml both reject it. *Recommendation:* keep
   accepting silently in default mode (the corpus needs it), record it
   in the dialect table (done, patch 1), and fold it into the same
   future strict mode as question 1 — as a warning, since unlike the
   pseudostate dialect it appears in OMG-authored text.
5. **KerML rejection cases?** The KerML grammar is the same ANTLR
   pipeline but `build_model` rejects KerML outright, so only
   parse-layer cases are testable. *Recommendation:* defer until the
   KerML build path exists; the corpus structure already accommodates
   a `language` field when it does.

## Generative tier (implemented)

> Added 2026-08-27, the second implementation slice:
> `tests/test_generative.py` + `tests/_model_strategies.py`. Everything
> below was measured at commit `8cc8a2c`.

The rejection corpus above is hand-authored, so its denominator is our
imagination. The generative tier turns the sampling over to
[Hypothesis](https://hypothesis.readthedocs.io): property-based testing
applied to the toolchain itself. A composite strategy generates
*valid-by-construction* models — as **text**, through a grammar-shaped
recursive generator, so the parser is exercised on every example —
covering packages (nested), part/attribute/port/action/calc/state/
requirement/item/enum definitions and usages, specializations,
subsettings, redefinitions, multiplicities, value expressions over a
small closed vocabulary, state machines (entry + transitions),
successions, connections, variations, aliases, quoted names, and doc
comments. Every reference targets a name declared in lexical scope and
every sibling name is unique, so a *guard property* can assert the
strong form of validity: parse + build + `validate()` with **zero
diagnostics of any severity**. A strategy bug is indistinguishable from
a toolchain bug at that bar, which is the point — both fail the suite.

Three property families run over the generated models:

- **A — never crash.** The guard, plus an adversarial property: valid
  text pushed through 1-3 character/token-level corruptions (deletions,
  swaps, keyword substitutions, brace imbalance, truncation, unicode
  noise) must produce `ParseError`/`BuildError` or diagnostics — never
  an unhandled traceback; whatever still builds must also survive
  `validate`, `to_sysml`, and `to_dict`. Hypothesis shrinks any crash
  to a minimal reproducer.
- **B — round-trip invariants.** `to_sysml -> loads -> to_sysml` is a
  fixpoint; `to_json`/`from_json` is lossless (`to_dict` equality,
  element counts, qualified names); `validate()` mints no new
  diagnostics after either round-trip. The suite previously pinned
  these invariants only on hand examples.
- **C — mutation invalidity.** A catalog
  (`tests/_model_strategies.py:MUTATIONS`, 29 entries: 6 enforced, 4
  diagnosed, 19 gaps) of invalidating
  mutations applied to generated models, each tied to the one spec/
  pilot rule it violates — the corpus-header discipline, ported.
  Expected verdicts are classed `error` (must stay rejected),
  `diagnosed` (must stay at least warned), or `gap` (accepted silently
  today; pinned as a strict xfail in the rejection corpus, which owns
  the promotion pressure — a hygiene test asserts every `gap` entry
  points at a live `KNOWN_GAPS` case). An accepted-silent mutant that
  is *not* already pinned is a finding: shrink it, dedupe it by rule,
  and append it to `tests/test_rejection.py`.

That findings pipeline is how the fourth bucket grew from 24 to 36:
twelve new permissiveness gaps, all verified against the pilot
validator sources (rule constants and messages read from
`SysMLValidator.xtend`/`KerMLValidator.xtend` at `master`, 2026-08-27)
— same-scope and package-level redefinition
(`validateRedefinitionFeaturingTypes`), connector ends resolving to
non-features, second subjects
(`validateRequirementDefinitionOnlyOneSubject`), second return
parameters (`validateFunctionResultParameterMembership`), kind-crossed
*definition* specialization (`validateDataTypeSpecialization`,
`validateBehaviorSpecialization`), directed parameters outside
behaviors (`validateParameterMembershipOwningType`), non-port
interface-usage ends (`validateInterfaceUsageEnd_`), and three resolver
holes (multiplicity bounds, succession ends, and `perform` targets are
never resolved — not even to the warning the rest of the resolver
would emit). Deliberately *not* added: `[3..1]` stays
adjudicated-accept (open question 3), and pilot-*warning* rules (e.g.
`validateBindingConnectorTypeConformance`) do not qualify — warnings
do not count as rejection in either direction.

CI posture versus deep sweeps: hypothesis is **not** a project
dependency — in the default environments the file skips cleanly. When
it is installed, the shipped properties run **derandomized** at
`max_examples <= 100` per property (the whole file is about a minute),
so CI stays deterministic and time-bounded.
`LONGERON_GENERATIVE_PROFILE=deep` switches to the exploratory posture
— fresh seeds, 20-40x the examples — for scratch-environment sweeps;
findings flow back as shrunk minimal cases in the rejection corpus,
never as new CI load. The denominator honesty carries over unchanged:
the generator samples the constructs *we taught it*; a clean sweep
bounds nothing but our own vocabulary. Constructs not yet generated
(imports, interface/flow/binding usages, metadata, views, individuals,
feature chains in expressions) are the tier's open frontier.

## References

- OpenSysML methodology pages, read 2026-08-27:
  [spec-compliance](https://opensysml.org/project/spec-compliance/),
  [pilot-differential](https://opensysml.org/project/pilot-differential/),
  [grammar reference](https://opensysml.org/reference/grammar/),
  [conformance-audit](https://opensysml.org/reference/grammar/conformance-audit/),
  and the repository documents `docs/project/pilot-rejection.md` and
  `docs/project/grammar-coverage.md`
  ([Open-MBEE/OpenSysML](https://github.com/Open-MBEE/OpenSysML)).
- OMG *Systems Modeling Language v2.0* (`sysml2-language.pdf`),
  clause 8.3 validation rules and clause 8.2.2 textual-notation BNF;
  page numbers above are the printed ones.
- SysML v2 Pilot Implementation validator sources
  (`SysMLValidator.xtend`, `KerMLValidator.xtend`,
  [Systems-Modeling/SysML-v2-Pilot-Implementation](https://github.com/Systems-Modeling/SysML-v2-Pilot-Implementation)),
  read at `master` on 2026-08-27 for rule names and messages.
- `scripts/check_corpus.py`, `docs/guides/grammar.md` (the acceptance
  story this design extends), `tests/test_rejection.py` (the phase-1
  implementation).
