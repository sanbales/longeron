# Tutorials

Seven executable notebooks live in
[`notebooks/`](https://github.com/sanbales/longeron/tree/main/notebooks).
The committed notebooks are output-free by repo convention (the test suite
executes them; git hooks strip outputs) — **every output you see on these
pages was produced by executing the notebooks during the documentation
build**, so they are always current with the code.

:::{note}
**Interactive widgets require JupyterLab.** The diagram and analysis
widgets (ipyelk diagrams in tutorial 6; the parallel-coordinates plot, N2
map, 3D viewer, and dashboard in tutorial 7; the replay player in
tutorial 4) are live browser applications and cannot run on a static
site — those cells show a textual placeholder here. Run the notebooks in
JupyterLab (`pixi run lab`) for the full experience. Static SVG/PNG
exports ({mod}`sysml2.render`) and matplotlib figures render normally
below.
:::

:::{note}
Tutorial 7's final cell demonstrates CAD export behind the `cad` extra;
cadquery is deliberately absent from the docs build (~1 GB OCC kernel),
so that cell degrades — as designed — to a printed pointer at the extra.
:::

| Tutorial | Covers |
|---|---|
| {doc}`1. Define and explore <01_define_and_explore>` | parsing, the object model, programmatic authoring, workspaces |
| {doc}`2. Export and interchange <02_export_and_interchange>` | SysML/JSON round-trips, save/load, KerML, spec metamodel, API JSON |
| {doc}`3. Calculations and constraints <03_calculations_and_constraints>` | expressions, calcs, instantiation, constraints, requirements, the full loop |
| {doc}`4. Actions and states <04_actions_and_states>` | action graphs, hierarchical/parallel state machines, time |
| {doc}`5. Stdlib and validation <05_stdlib_and_validation>` | the vendored standard library, `sysml2 lint` |
| {doc}`6. Interactive diagrams <06_interactive_diagrams>` | ipyelk structure/state/action diagrams, click-selection, headless SVG/PNG |
| {doc}`7. Analysis and trades <07_analysis_and_trades>` | multi-mission UAV trade studies, OpenMDAO sizing, Z3 consistency, 3D views |

```{toctree}
:hidden:
:maxdepth: 1

01_define_and_explore
02_export_and_interchange
03_calculations_and_constraints
04_actions_and_states
05_stdlib_and_validation
06_interactive_diagrams
07_analysis_and_trades
```
