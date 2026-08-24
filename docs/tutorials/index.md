# Tutorials

Ten executable notebooks live in
[`notebooks/`](https://github.com/sanbales/longeron/tree/main/notebooks).
Together they walk every capability of the package, in order: each
notebook builds on ideas from the ones before it, but each also states
its own prerequisites, so you can start at the topic you need.

**Every output on these pages is real.** The committed notebooks are
output-free by repo convention (the test suite executes them, and git
hooks strip outputs), and the documentation build re-executes them, so
the outputs you see here always match the code.

:::{note}
**Interactive widgets require JupyterLab.** The diagram and analysis
widgets (ipyelk diagrams in tutorial 6; the parallel-coordinates plot,
N2 map, 3D viewer, and dashboard in tutorial 7; the replay player in
tutorial 6; the linked diagram + 3D pair in tutorial 10) are live
browser applications and cannot run on a
static site, so those cells show a textual placeholder here. Run the
notebooks in JupyterLab (`pixi run lab`) for the full experience. Static
SVG/PNG exports ({mod}`longeron.render`) and matplotlib figures render
normally below.
:::

:::{note}
Tutorial 7's final cell demonstrates CAD export behind the `cad` extra.
cadquery is deliberately absent from the docs build (its OCC kernel is
~1 GB), so that cell degrades, as designed, to a printed pointer at the
extra.
:::

| Tutorial | Covers |
|---|---|
| {doc}`1. Define and explore <01_define_and_explore>` | parsing, the object model, programmatic authoring, workspaces |
| {doc}`2. Export and interchange <02_export_and_interchange>` | SysML/JSON round-trips, save/load, KerML, spec metamodel, API JSON |
| {doc}`3. Calculations and constraints <03_calculations_and_constraints>` | expressions, calcs, instantiation, constraints, requirements, the full loop |
| {doc}`4. Actions and states <04_actions_and_states>` | action graphs, hierarchical/parallel state machines, time |
| {doc}`5. Stdlib and validation <05_stdlib_and_validation>` | the vendored standard library, `longeron lint` |
| {doc}`6. Interactive diagrams <06_interactive_diagrams>` | ipyelk structure/state/action diagrams, click-selection, headless SVG/PNG |
| {doc}`7. Analysis and trades <07_analysis_and_trades>` | multi-mission UAV trade studies, OpenMDAO sizing, Z3 consistency, 3D views |
| {doc}`8. Semantic web and RAG <08_semantic_web_and_rag>` | RDF projection + SPARQL, retrieval chunks, neighborhoods, keyword search, the agent loop |
| {doc}`9. M0 interpretations <09_m0_interpretations>` | populations of identified individuals, Annex A sequences, roll-ups over actual instances, random sampling, occurrences from executions, the trade-study bridge |
| {doc}`10. Diagrams meet CAD: M1 and M0 <10_diagram_3d_link>` | linked selection between a structure diagram and the 3D viewer, per-instance geometry keyed by M0 individual ids, the M1 -> M0 fan-out and the M0 -> M1 projection |
| {doc}`11. The notation gallery <11_notation_gallery>` | every implemented SysML v2 glyph beside its spec figure -- specialization adornments, membership diamonds and circles, flows, ports, behavior glyphs, swim lanes, actors -- with self-verifying asserts |
| {doc}`12. The model explorer <12_model_explorer>` | tree navigation over the owning structure, per-selection diagram kinds, two-way selection linkage, JupyterLab docking |

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
08_semantic_web_and_rag
09_m0_interpretations
10_diagram_3d_link
11_notation_gallery
12_model_explorer
```
