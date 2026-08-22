# Release notes

## 0.5.0 (unreleased)

- Tutorial 09: M0 interpretations (populations, gaps, sequences, the
  trades bridge) + `longeron.m0` reference page

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
