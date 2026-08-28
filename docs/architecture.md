# Architecture

The package is a pipeline. Generated ANTLR parsers turn SysML v2 text
into parse trees, and the builder turns parse trees into a typed object
model. Everything else consumes that model: the exporters, the
validator, the interpreter, the diagrams, and the analysis bridges.

## Package layout

```{include} ../README.md
:start-after: "## Project layout"
:end-before: "### How a model flows through the package"
```

## How a model flows through the package

```{include} ../README.md
:start-after: "### How a model flows through the package"
:end-before: "## Code quality"
```

## Execution semantics (and their limits)

```{include} ../README.md
:start-after: "## Execution semantics (and their limits)"
:end-before: "## Interactive diagrams"
```

## The analysis stack

{mod}`longeron.analysis` projects executable models onto external
solvers. Each submodule imports its solver lazily, so the package itself
adds no third-party dependencies:

- {mod}`longeron.analysis.mdao` — part trees and calcs become OpenMDAO
  `Problem`s: derived attributes turn into components, free attributes
  into design variables, and constraints into margin outputs.
  `@ExternalAnalysis` annotations swap higher-fidelity components in for
  calc bodies.
- {mod}`longeron.analysis.trades` — variation/variant catalogs become
  OR-Tools CP-SAT models for discrete architecture trade studies, scored
  exactly through the interpreter.
- {mod}`longeron.analysis.smt` — requirement sets become Z3 assertions:
  consistency checks, conflict cores, and design-space bounds over the
  reals.
- {mod}`longeron.analysis.viz`, {mod}`longeron.analysis.structure`,
  {mod}`longeron.analysis.dashboard` — figures, N2/network views of the
  generated problems, and the linked mission-compromise dashboard.
- {mod}`longeron.analysis.geometry` / {mod}`longeron.analysis.viewer3d` —
  parametric to-scale meshes for architecture mixes (stdlib-only math)
  and a small three.js viewer. Real CAD solids (STEP export) live behind
  the `cad` extra.

The guide [Choosing an analysis](guides/analysis.md) matches questions
to bridges, and tutorial
{doc}`7 <tutorials/07_analysis_and_trades>` drives the whole stack end
to end.

## Vendored ipyelk

The interactive diagrams ({mod}`longeron.diagrams`) are built on
[ipyelk](https://github.com/jupyrdf/ipyelk), which is **vendored** under
`vendor/ipyelk` (BSD-3-Clause, tag v2.1.1) and installed editable so it
can be patched as needed: headless-safe scheduling, resend-with-backoff
browser round-trips, error channels, and a prebuilt JupyterLab extension
rebuilt from the patched TypeScript sources. Every local patch is marked
`LOCAL PATCH` and catalogued in
[`vendor/ipyelk/README.vendor.md`](https://github.com/sanbales/longeron/blob/main/vendor/ipyelk/README.vendor.md);
the history is tracked by `git log -- vendor/ipyelk`.

Layout normally runs in the browser (elkjs). For tests, exports, and
this documentation build, {mod}`longeron.render` runs the same elkjs
(vendored as `longeron/_js/elk.bundled.js`, EPL-2.0) in a node
subprocess and draws styled SVG/PNG headlessly.

## Grammar patches

The grammars carry ten local patches against their upstream source, and
one known precedence deviation from the OMG specification remains. The
guide [Grammar conformance](guides/grammar.md) carries the patch table,
the corpus result, and the deviation. The full per-patch rationale lives
in the [README](https://github.com/sanbales/longeron#grammar-patches).

## Design documents

Deeper design rationale for major subsystems:

```{toctree}
:maxdepth: 1

design/conformance
design/geometry
design/m0-interpretations
design/mdao-objects
design/notebooks
design/ocl-stance
design/openmbee-integration
design/provenance
design/units
design/verify
design/view-persistence
```
