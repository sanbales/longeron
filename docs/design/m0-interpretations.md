# M0 interpretations for longeron (design)

Goal: pymbe-inspired M0 semantics -- populations of identified individuals, sampled
interpretations, KerML Annex A sequence semantics, and expression roll-ups over actual
instances -- built on longeron's interpreter instead of beside it.

## (a) What `Interpreter.instantiate()` already gives
One deep `Instance` tree with full attribute evaluation (inheritance, redefinition,
caller bindings, lazy cross-references). Multiplicity `[4]` already yields 4 *distinct*
Python objects; ranges take their lower bound. What it lacks for M0: **identity** (no
stable ids; snapshots invent `name_1..n`), **strategy** (one deterministic population;
no sampling of legal population sizes/values), **variation semantics** (instantiating a
`variation` def materializes every variant as a slot -- `TradeQuad` fails outright on
`battery.mass`), **sequence semantics**, and **aggregation over the population** (models
hand-encode `4.0 * motors.mass`; `drone.sysml` even hardcodes `4.0 * 0.06`).

## (b) What pymbe adds conceptually (the reference)
pymbe's `interpretation/` (KerML Annex A draft executor + the older random interpreter):
an M1 type is interpreted as a set of M0 **atoms**; a feature as a set of **sequences**
`(owner..., value)` -- nested features are longer sequences; multiplicity lower bounds
drive atom counts (`execute_kerml_atoms.py` steps 1-2); values bind per atom via a
covering pattern (`working_maps.py`); calc roll-ups run over the actual atoms in
dependency order (`calc_dependencies.py`). Random interpretations sample the space of
legal populations. pymbe builds atoms as *new M1 elements*; longeron should not -- its
runtime `Instance` layer is the right home, keeping M1 models clean.

## (c) Key insight: traces ARE interpretations
pymbe never had execution. longeron already produces execution traces -- state
activations with `entered_at`/exit times (`_ActiveState`, `replay.Timeline.tracks`) and
action steps -- which are exactly M0 *occurrences with lifetimes* (Annex A's portions/
time-slices, minus the ceremony). The M0 layer therefore uses ONE representation,
`Individual` (an `Instance` with a stable id, optionally `start`/`end`/`duration`
slots), for both statically populated parts and dynamically recorded occurrences. A
simulation is an interpretation of a behavior; `rollup`/`sequences` work identically on
both. This marriage is the part pymbe could never reach.

## (d) API: `longeron.m0`
- `interpret(model, element=None, *, strategy="nominal"|"random", seed=None,
  bindings=None, selection=None) -> Interpretation`. Nominal: declared multiplicities
  (exact bounds expand, ranges take the lower bound -- same as `instantiate`),
  variations take `selection` or the first declared variant. Random: seeded
  `random.Random`; population sizes uniform in `[lower, upper]` (unbounded capped at
  lower+3), per-individual variant choice, unvalued enum/Boolean attributes sampled from
  their literal domain (numeric domains need bounds we don't have at M1 -- future:
  `analysis.smt` box bounds). Ids are `qname#index` paths: root `Pkg::Quad#0`, nested
  `Pkg::Quad#0.rotors#2` (singletons omit `#i`). Evaluation errors degrade to `None` +
  an entry in `Interpretation.gaps` (the trades-style honesty channel).
- `Interpretation`: `.root`, `.individuals(classifier=None)` (conformance-filtered),
  `.sequences("rotors.mass")` -> Annex A sequences as tuples `(quad, rotor_i, 0.06)`,
  `.rollup(expr_or_feature_name)` -> evaluate an expression with feature refs resolved
  against the *actual* population (`sum(rotors.mass)` flattens over the 4 individuals --
  the roll-up pymbe did with covering atoms), `.sample(n)` (random strategy: n fresh
  interpretations under derived seeds), `.to_dict()` (JSON-able, ids included).
- `from_architecture(study, architecture)` -- a trades `Architecture` IS a partial
  interpretation (variant selection fixed, population nominal). Regression contract:
  M0 roll-ups over the individuals equal the `all_architectures()` metrics.
- `from_timeline(timeline, interpreter=None, source=...)` -- each contiguous activation
  in `replay.Timeline.tracks` becomes an occurrence `Individual` (`qname@k`) with
  `start`/`end`/`duration`; roll-ups over lifetimes come free.
- Integration notes: **api-json** -- the OMG Systems Modeling API has *no* M0 story;
  `Interpretation.to_dict()` is a documented longeron extension (not emitted by
  `to_api_json`; a future `application/vnd.longeron.m0+json` sidecar). **rdf** --
  individuals are natural triples (`ind a <classifier>; :slot value`), a follow-up
  `m0.to_graph()` alongside `longeron.rdf`. **snapshot** -- `Interpreter.snapshot`
  already writes instances back to M1; ids give it stable names later.

## (e) Phased plan + tests
1. **Core (this round)**: `m0.py` (stdlib only): `Individual`, `Interpretation`,
   `interpret` (nominal+random), `rollup`, `sequences`, `sample`, `from_architecture`,
   `from_timeline`. Tests: population identity on `drone.sysml` (4 rotor individuals,
   stable ids), seeded-random reproducibility + bounds, variation selection, occurrence
   individuals from a recorded `FlightStates` timeline, and THE regression: for all 54
   `TradeQuad` mixes, M0 roll-ups == `all_architectures()` metrics (rel 1e-12; the M1
   expressions use the homogeneous `4.0 * x` convention, M0 sums actual individuals).
2. **Feedback round**: notebook + docs page; heterogeneous per-index selection feeding
   *back* into trades; `m0.to_graph()` RDF projection.
3. **Later**: connector-end pairing under multiplicity (pymbe's Annex A pass 3),
   `simulate`-driven nested occurrence trees (actions as subperformances), SMT-derived
   numeric domains for random attribute values, API sidecar endpoint.

Non-goals now: mutating M1 (pymbe's covering pattern), exhaustive enumeration strategy
(`all_architectures` already covers the discrete case; a general `exhaustive` strategy
explodes without domain bounds), per-individual physics re-sizing.

## Decisions (ratified 2026-08-22)

The three open choices were reviewed and the implemented behavior stands:

1. **Nominal ranged multiplicities take the lower bound** — conservative,
   deterministic, consistent with `instantiate()` and pymbe's atom counts;
   `strategy="random"` and explicit `bindings` cover everything else.
2. **M1/M0 divergence lands in `Interpretation.gaps`, never raises** — the
   trades-style honesty channel: values degrade to `None`, the gap records
   what and why, and strict callers assert `gaps == []`.
3. **M0 stays out of the OMG API projection** — `to_dict()` is a separate
   shape; if serving interpretations over HTTP becomes useful, it enters
   through the server's `/x/` extension namespace, keeping the standard
   record stream uncontaminated for pilot-ecosystem consumers.
