# Reference

The import name is `longeron`.
The most common entry points are re-exported
at the top level ({mod}`longeron` — `loads`, `load`, `validate`, `to_json`,
`Interpreter`, ...); the pages below document each module where its
objects are defined.

## Core pipeline

| Page | Modules | What lives there |
|---|---|---|
| [Package API & errors](longeron.md) | `longeron`, `longeron.errors` | the re-exported convenience API, exception types |
| [Object model](model.md) | `longeron.model`, `longeron.ast` | element dataclasses, expression AST |
| [Parsing & building](parsing.md) | `longeron.parser`, `longeron.builder` | text → parse tree → model (`loads`) |
| [Workspaces & caching](workspace.md) | `longeron.workspace` | `load`, multi-file merges, the model cache |
| [Interpreter](interpreter.md) | `longeron.interpreter` | evaluation, instantiation, actions, states |
| [Validation](validation.md) | `longeron.validation` | `validate()` / `longeron lint` diagnostics |
| [Units](units.md) | `longeron.units` | derived unit table, dimensional-lint substrate, `[units]` conversion facade |
| [Model editing](edit.md) | `longeron.edit` | rename/value/doc/metadata mutations with round-trip guarantees, change tracking |
| [Evidence](evidence.md) | `longeron.evidence` | SourceEvidence citations: attach, verify, coverage |
| [Standard library](stdlib.md) | `longeron.stdlib` | the vendored OMG model library |
| [M0 interpretations](m0.md) | `longeron.m0` | populations, sequences, roll-ups, trace occurrences |
| [Interchange](interchange.md) | `longeron.export`, `longeron.importer`, `longeron.kerml`, `longeron.ecore`, `longeron.api`, `longeron.rdf`, `longeron.rag` | JSON/SysML/KerML exports, spec metamodel, API JSON, RDF/SPARQL, LLM retrieval substrate |
| [API server & client](api-server.md) | `longeron.server`, `longeron.client` | git-backed Systems Modeling API server, REST client |
| [Command line](cli.md) | `longeron.cli` | the `longeron` console command |

## Visualization

| Page | Modules | What lives there |
|---|---|---|
| [Diagrams](diagrams.md) | `longeron.diagrams`, `longeron.toolbar` | interactive ELK diagrams (ipyelk) and their compact search toolbar |
| [Model explorer](explorer.md) | `longeron.explorer` | the tree + diagram-pane explorer widget |
| [View persistence](views.md) | `longeron.views` | saving diagrams as SysML v2 views, sidecar presentation, restore |
| [Rendering](render.md) | `longeron.render` | headless SVG/PNG export (elkjs via node) |
| [Replay](replay.md) | `longeron.replay` | animated simulation/action replays |

The {doc}`notation gallery <notation_gallery>` belongs here too: an
executable notebook that shows every implemented SysML v2 glyph beside
its spec figure, with self-verifying asserts. The
[notation coverage guide](../guides/notation-coverage.md) tabulates the
same ground.

## Analysis

| Page | Module | What lives there |
|---|---|---|
| [Overview](analysis/index.md) | `longeron.analysis` | the solver-bridge package |
| [MDAO](analysis/mdao.md) | `longeron.analysis.mdao` | OpenMDAO sizing/optimization |
| [Trade studies](analysis/trades.md) | `longeron.analysis.trades` | CP-SAT architecture trades |
| [SMT](analysis/smt.md) | `longeron.analysis.smt` | Z3 requirement consistency |
| [Visualization](analysis/viz.md) | `longeron.analysis.viz` | figures, parallel coordinates |
| [Geometry](analysis/geometry.md) | `longeron.analysis.geometry` | parametric to-scale meshes, CAD export |
| [3D viewer](analysis/viewer3d.md) | `longeron.analysis.viewer3d` | three.js mesh viewer |
| [Structure views](analysis/structure.md) | `longeron.analysis.structure` | N2 matrix, connection networks |
| [Dashboard](analysis/dashboard.md) | `longeron.analysis.dashboard` | linked mission-compromise dashboard |
| [Grand tour](analysis/grand.md) | `longeron.analysis.grand` | the all-seams demo dashboard |

## Widgets

| Page | Module | What lives there |
|---|---|---|
| [Overview](widgets/index.md) | `longeron.widgets` | THE catalog: every house widget behind one lazy import; the authors' toolkit; the home for new widgets |
| [RDF graph in 3D](widgets/graph3d.md) | `longeron.widgets.graph3d` | force-directed RDF projection explorer |

```{toctree}
:hidden:
:maxdepth: 1

longeron
model
parsing
workspace
interpreter
validation
units
edit
evidence
stdlib
interchange
m0
api-server
cli
diagrams
explorer
views
render
replay
analysis/index
widgets/index
notation_gallery
```
