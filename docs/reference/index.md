# API reference

The import name is `longeron` (`sysml2` remains a compatibility alias;
see [Migrating from sysml2](../guides/compat.md)).
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
| [Standard library](stdlib.md) | `longeron.stdlib` | the vendored OMG model library |
| [Interchange](interchange.md) | `longeron.export`, `longeron.importer`, `longeron.kerml`, `longeron.ecore`, `longeron.api`, `longeron.rdf`, `longeron.rag` | JSON/SysML/KerML exports, spec metamodel, API JSON, RDF/SPARQL, LLM retrieval substrate |
| [API server & client](api-server.md) | `longeron.server`, `longeron.client` | git-backed Systems Modeling API server, REST client |
| [Command line](cli.md) | `longeron.cli` | the `longeron` console command |

## Visualization

| Page | Modules | What lives there |
|---|---|---|
| [Diagrams](diagrams.md) | `longeron.diagrams` | interactive ELK diagrams (ipyelk) |
| [Rendering](render.md) | `longeron.render` | headless SVG/PNG export (elkjs via node) |
| [Replay](replay.md) | `longeron.replay` | animated simulation/action replays |

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

```{toctree}
:hidden:
:maxdepth: 1

longeron
model
parsing
workspace
interpreter
validation
stdlib
interchange
api-server
cli
diagrams
render
replay
analysis/index
```
