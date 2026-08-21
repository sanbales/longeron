# API reference

The import name is `sysml2`. The most common entry points are re-exported
at the top level ({mod}`sysml2` — `loads`, `load`, `validate`, `to_json`,
`Interpreter`, ...); the pages below document each module where its
objects are defined.

## Core pipeline

| Page | Modules | What lives there |
|---|---|---|
| [Package API & errors](sysml2.md) | `sysml2`, `sysml2.errors` | the re-exported convenience API, exception types |
| [Object model](model.md) | `sysml2.model`, `sysml2.ast` | element dataclasses, expression AST |
| [Parsing & building](parsing.md) | `sysml2.parser`, `sysml2.builder` | text → parse tree → model (`loads`) |
| [Workspaces & caching](workspace.md) | `sysml2.workspace` | `load`, multi-file merges, the model cache |
| [Interpreter](interpreter.md) | `sysml2.interpreter` | evaluation, instantiation, actions, states |
| [Validation](validation.md) | `sysml2.validation` | `validate()` / `sysml2 lint` diagnostics |
| [Standard library](stdlib.md) | `sysml2.stdlib` | the vendored OMG model library |
| [Interchange](interchange.md) | `sysml2.export`, `sysml2.importer`, `sysml2.kerml`, `sysml2.ecore`, `sysml2.api` | JSON/SysML/KerML exports, spec metamodel, API JSON |
| [Command line](cli.md) | `sysml2.cli` | the `sysml2` console command |

## Visualization

| Page | Modules | What lives there |
|---|---|---|
| [Diagrams](diagrams.md) | `sysml2.diagrams` | interactive ELK diagrams (ipyelk) |
| [Rendering](render.md) | `sysml2.render` | headless SVG/PNG export (elkjs via node) |
| [Replay](replay.md) | `sysml2.replay` | animated simulation/action replays |

## Analysis

| Page | Module | What lives there |
|---|---|---|
| [Overview](analysis/index.md) | `sysml2.analysis` | the solver-bridge package |
| [MDAO](analysis/mdao.md) | `sysml2.analysis.mdao` | OpenMDAO sizing/optimization |
| [Trade studies](analysis/trades.md) | `sysml2.analysis.trades` | CP-SAT architecture trades |
| [SMT](analysis/smt.md) | `sysml2.analysis.smt` | Z3 requirement consistency |
| [Visualization](analysis/viz.md) | `sysml2.analysis.viz` | figures, parallel coordinates |
| [Geometry](analysis/geometry.md) | `sysml2.analysis.geometry` | parametric to-scale meshes, CAD export |
| [3D viewer](analysis/viewer3d.md) | `sysml2.analysis.viewer3d` | three.js mesh viewer |
| [Structure views](analysis/structure.md) | `sysml2.analysis.structure` | N2 matrix, connection networks |
| [Dashboard](analysis/dashboard.md) | `sysml2.analysis.dashboard` | linked mission-compromise dashboard |

```{toctree}
:hidden:
:maxdepth: 1

sysml2
model
parsing
workspace
interpreter
validation
stdlib
interchange
cli
diagrams
render
replay
analysis/index
```
