# Release notes

## 0.8.0

- **Spec-exact SysML v2 graphical notation**, grounded in the OMG 2.0
  spec's figures and clause 8.2.3 BNF (a rendered notation atlas of all
  205 element rows drove the work; every glyph family ships with an
  implementation-vs-spec evidence sheet):
  - specialization family: solid lines, closed hollow triangle heads,
    shaft adornments mirroring the textual characters -- typing `:`
    colon dots, redefinition `:>>` bar tick, reference subsetting `::>`
    2x2 dots; keyword edge labels dropped
  - membership: filled (composite) / hollow (`ref`) diamonds with role
    + end multiplicities via `structure_diagram(composition=)`; owned
    membership as the spec's p.26 edge presentation via
    `membership="edges"` (true circled-plus); alias members draw a
    hollow circle + name
  - connector-end multiplicities render at both ends (the builder now
    captures what the grammar always parsed)
  - flow connections: border pins, filled head at the target pin,
    payload labels; satisfy draws the p.133 form exactly; dependency
    (incl. n-ary junction) and binding `=` edges; portion membership's
    notched ball; `individual`/`timeslice`/`snapshot` keywords
  - behavior views: done bullseye, terminate circle-X, fork/join bars,
    decision/merge rhombi with single in/out convergence anchors,
    accept/send as boxes with spec-form top-left badges, dashed action
    successions, `action_diagram(lanes=)` performer swim lanes,
    actor/stakeholder keyword boxes
  - all arrowheads re-derived from single-source ~27-degree slender
    geometry in both pipelines
- **State diagrams expand typed submachines** (`submachine_depth`),
  cycle-protected; replay keys became instance-qualified -- two
  expansions of one submachine no longer cross-highlight
- **Compact diagram toolbar**: icon buttons with tooltips plus a
  search box that highlights every matching element (never touches the
  selection -- `on_select` provably cannot fire); collapse-stub ports
  take their node kind's palette color
- **Diagrams meet CAD** (`longeron.analysis.link`): bidirectional
  linked selection between structure diagrams and the three.js viewer
  -- M1 selections fan out to M0 individual meshes, 3D picks project
  back (with the picked individual surfaced); tutorial 10 teaches the
  M1/M0 distinction through it; `drone_geometry(split_instances=True)`
- Diagnostic-location test made Windows-safe (the only red CI leg)
- Design docs: the OCL stance (ratified) and the notation plan +
  spec-grounded errata live in the repo's session notes

## 0.7.1

- The five 0.7.0 known issues are fixed: bare `individual`/`snapshot`/
  `timeslice` usages reprint without doubling the keyword, variant
  references keep their specializations, state entry/do/exit inline
  action bodies survive reprint, KerML case result expressions emit as
  valid owned expression features, and `satisfy <Def> by x` projects
  to ecore/API records without crashing (FeatureTyping, not a
  Subsetting to a Classifier)

## 0.7.0

- **Lossless JSON omission**: `to_dict` dropped every falsy field
  unconditionally while import hid omissions behind dataclass defaults
  -- a True-valued flag could vanish silently, including through the
  model cache. Omission is now default-aware; all 36 boolean fields on
  all element types round-trip exactly (old JSON still imports; output
  is byte-identical for well-formed models)
- **Coverage 87% -> 93%** with meaningful tests: the audit's surviving
  mutation probes killed, 20 new round-trip sources over the previously
  untested builder surface (case bodies, exhibit states, inline
  performs, event occurrences, individual/portion usages, variant
  references, metaclassification, ...), CLI/server/analysis suites
  deepened
- Diagrams: compartment rows left-align (UML convention) in both the
  browser and headless pipelines; the palette is single-sourced;
  exported SVGs carry a `<title>`
- Parse errors humanized: ANTLR `expecting {...}` soups become compact
  messages with the offending line and a caret (verbatim text kept on
  `SyntaxIssue.raw_message`)
- Every optional-extra guard raises `MissingExtraError` with a uniform
  `pip install longeron[extra]` message
- `Client.validate` forwards `strict_imports`; the README pip-route
  first run works in a fresh clone (vendored ipyelk install step)
- Perf: succession edges indexed once per plan; the cache fingerprint
  includes the serialization layer (one-time cache invalidation);
  `scripts/bench_cache.py` regenerates the warm-load numbers
- `merge_models` no longer mutates its inputs;
  `spec_from_api_json`/`spec_from_api_records` are the canonical names
  for the spec-metamodel importers (aliases kept)
- Breaking (0.x): `save(format=)` -> `save(fmt=)`; `to_dict`/`to_json`
  first parameter is `element`; `bindings` is reserved on
  `evaluate`/`instantiate`/`check_requirement` (a feature named
  `bindings` must use the mapping form); `Instance.set` raises
  `EvaluationError` (was `KeyError`/`AttributeError`)
- Known issues (found by the new tests, documented as skips; **fixed
  in 0.7.1**): four
  exporter reprint defects (doubled `individual` keyword on bare
  usages, variant-reference types dropped, inline state-action bodies
  dropped, bare case result expressions in KerML behavior bodies) and
  an ecore projection crash on `satisfy <Def> by ...`

## 0.6.0

- Validation diagnostics carry `file:line:column` (positions stamped by
  the builder; models rebuilt from JSON -- including warm cache hits --
  omit the prefix; `--no-cache` restores it)
- CLI failures print one-line actionable errors (`--traceback` opts
  back in); `longeron parse <dir>` reports every file instead of
  aborting at the first failure
- Structure diagrams pack disconnected members toward a ~1.6 aspect
  ratio instead of one tall column; packing grids escape the global
  layer spacing entirely (drone structure: 2.2:1 tall -> 1.14:1,
  -22% canvas area)
- `attribute x : Real :>> x` no longer reports a false
  `specialization-cycle` error (redefinition edges left the cycle walk)
- API server: working-tree model + record projection memoized behind a
  stat-only fingerprint -- paginated listings parse once; per-ref memos
  bounded
- `Env.assign` validates dotted paths before mutating the frame
- `longeron.*` no longer leaks `typing.Literal`, `dataclasses.field`
  et al.: `model.__all__` is explicit, guarded by `tests/test_public_api.py`
- One instantiation engine: `m0._Populator` shares the interpreter's
  `_PopulationEngine` core (identity, variant filtering, gap recording,
  and random defaults stay M0-specific)
- `scripts/check_corpus.py` reproduces the 309/309 corpus sweep from a
  pinned upstream commit; grammar-guide wording aligned with what the
  test suite actually re-checks

## 0.5.1

- Single-file loads use the content-addressed model cache by default
  (`cache=False` opts out) -- repeat CLI invocations on one file drop
  from ~9 s to ~0.1 s
- Interpreter: package-level attribute values that depend on the
  instance in scope are no longer memoized across instances, which could
  silently flip a constraint verdict (a failing check reported
  `passed=True`)
- `validate()` / `longeron lint` treat `library` packages as resolution
  context only, so `lint --stdlib` no longer floods diagnostics about
  library internals on a clean model
- Docs honesty: `builder`/`model` docstrings now describe the
  no-lossy-fallback coverage; stale test/coverage counts dropped from
  the README

## 0.5.0

- Tutorial 09: M0 interpretations (populations, gaps, sequences, the
  trades bridge) + `longeron.m0` reference page
- `POST /x/interpret/{qname}` extension endpoint wraps `longeron.m0.
  interpret()` (strategy/seed/bindings/selection in the body, the
  `Interpretation.to_dict()` JSON out), mirrored by `Client.interpret()`
  -- seeded random populations reproduce exactly over HTTP.

## 0.4.0

- **Systems Modeling API layer**: `longeron serve` exposes any workspace as an
  OMG Systems Modeling API server (FastAPI/uvicorn, `[server]` extra) with
  git-backed commits -- an API commit *is* a git commit -- plus `/x/`
  extension endpoints (`validate`, `instantiate`, `simulate`, `render.svg`);
  `longeron.client` (`[client]` extra) fetches any project/commit into a
  `Model` and pushes changes back. Verified end-to-end by a pilot-ecosystem
  client (pymbe).
- **API JSON navigability**: relationship records emit derived
  `source`/`target` endpoints by default (pilot-API schema; `--no-derived`
  restores the previous format).
- **M0 interpretations** (`longeron.m0`, stdlib-only): populations of
  individuals with stable identities from multiplicities (nominal/seeded-
  random), per-individual attribute evaluation, Annex-A sequences, roll-ups
  over the actual population, `from_architecture` and `from_timeline` --
  execution traces and static populations share one representation. Design
  doc with ratified decisions under *Architecture > Design documents*.
- **CI platform triangle**: Windows and macOS legs join the ubuntu matrix;
  `win-64` added to the pixi lock; git is a pinned conda dependency of every
  environment; workflows on Node24-native action majors.
- Badges (self-hosted coverage endpoint, corpus 309/309), trove classifiers,
  stale "pickle" wording purged (the prebuilt stdlib is JSON).

## 0.3.0

Highlights on `main` since the 0.2.0 release:

### Project rename

- **The import package is now `longeron`** (matching the distribution
  name); the CLI gains a `longeron` command. The historical `sysml2` names
  keep working unchanged: longeron ships a built-in `sysml2` compatibility
  shim (same module objects, no deprecation warnings), the `sysml2` console
  command remains, and `$SYSML2_CACHE_DIR` is still honored behind the new
  `$LONGERON_CACHE_DIR`.

### The analysis stack

- **`longeron.analysis`** — analytical bridges from executable models onto
  external solvers, each behind its own extra:
  - {mod}`longeron.analysis.mdao`: part trees and calcs project onto OpenMDAO
    `Problem`s (derived attributes → components, free attributes → design
    variables, constraints → margin outputs), with `@ExternalAnalysis`
    annotations binding higher-fidelity components in place of calc bodies.
  - {mod}`longeron.analysis.trades`: discrete architecture trade studies over
    variation/variant catalogs on OR-Tools CP-SAT, scored interpreter-exact.
  - {mod}`longeron.analysis.smt`: requirement consistency, conflict cores, and
    design-space bounds on Z3.
- **Views over the analyses**: honest Pareto fronts with explicit senses,
  publication-quality figures, an interactive parallel-coordinates widget
  with editable brushes ({mod}`longeron.analysis.viz`), an N2 matrix in the
  NASA/OpenMDAO convention plus connection-network views
  ({mod}`longeron.analysis.structure`), and the linked mission-compromise
  dashboard ({mod}`longeron.analysis.dashboard`).
- **To-scale 3D**: parametric meshes for architecture mixes (box quad,
  teardrop quad, cruciform tail-sitter VTOL, interceptor) with a three.js
  viewer ({mod}`longeron.analysis.geometry`, {mod}`longeron.analysis.viewer3d`);
  cadquery solid/STEP export behind the `cad` extra.
- **Physics fidelity**: drag buildup, load-sized structure, and a
  multi-mission UAV catalog example (`examples/uav_missions.sysml`) driving
  tutorial 7.

### Language and validation

- **100% OMG-corpus conformance** — grammar patches 6–10 (transition clause
  order, optional `standard`, named send nodes, one-line multiline notes,
  metadata prefixes on enumerated values) plus matching builder fixes.
- **Strict-imports validation** and `isImplied` on the API export.

### Everything else

- Replay v2: action executions replay over the action diagram, step-mode
  scrubbing, scalar-env readouts.
- `sysml2` kept as a PyPI alias distribution of `longeron`.
- ruff format adopted for code *and* notebooks.
- The vendored ipyelk labextension is now built from the patched
  TypeScript sources, so every JS fix ships in the bundles.
- This documentation site (Sphinx + MyST + executed tutorial notebooks).

## 0.2.0 (2025)

The first tagged release. Cumulative capabilities:

- **Full-grammar SysML v2 front-end**: ANTLR-generated parsers (grammar
  patches 1–5), a builder with no lossy fallback, and a typed dataclass
  object model with compact expression ASTs.
- **Round-trip interchange**: JSON export/import (lossless), regenerated
  SysML text, KerML projection, OMG spec-metamodel projection (pyecore)
  and Systems Modeling API JSON records.
- **Execution**: expression evaluation, calcs, instantiation, constraint
  and requirement checking, succession-driven action control flow, and
  hierarchical/parallel state-machine simulation with a clock.
- **Validation** (`sysml2 lint` / {func}`sysml2.validate`) with
  stdlib-aware name resolution and implied specializations; the vendored
  standard library ships as inspectable JSON (no pickles anywhere).
- **Multi-file workspaces** with a content-addressed model cache
  (~1000x faster warm loads).
- **Interactive ELK diagrams** in JupyterLab (structure, states, actions;
  click-selection back to model elements) on a vendored, patched ipyelk;
  headless SVG/PNG rendering via elkjs in node; simulation replay over the
  state diagram.
- **Tooling**: Apache-2.0 license, pixi-locked CI (lint + mypy + coverage,
  a py310–py313 test matrix, grammar-regen drift check), PyPI trusted
  publishing on tag push, output-free committed notebooks enforced by
  git hooks.
