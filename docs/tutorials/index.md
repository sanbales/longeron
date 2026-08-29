# Tutorials

The executable tutorial notebooks live in
[`notebooks/`](https://github.com/sanbales/longeron/tree/main/notebooks).
The nine tutorials form one curriculum with one thesis: the SysML v2
model is the single source of truth, and every perspective is a view of
that same data. The arc runs *data → execution → reading → trading →
individuals → judging → geometry → knowledge → everything at once*.
Each tutorial opens with an engineering question and closes with the
model answering it. Each tutorial states its own prerequisites, so you
can start at the topic you need.

The subject everywhere is the DeepScout UAV program
(`examples/deepscout`): one workspace holding the parts catalog, the
aircraft family, the missions, and the requirements.

**Every output on these pages is real.** The committed notebooks are
output-free by repo convention (the test suite executes them, and git
hooks strip outputs), and the documentation build re-executes them, so
the outputs you see here always match the code.

:::{note}
**Interactive widgets appear as static snapshots.** The diagram and
analysis widgets (the state diagram in tutorial 2; the explorer,
diagrams, and toolbar in tutorial 3; the trade dashboard,
parallel-coordinates plot, and 3D viewers in tutorial 4; the
requirements scoreboards in tutorial 6; the 3D scenes and the mission
globe in tutorial 7; the grand-tour dashboard in tutorial 9) are live
browser applications and cannot run on a static site. On these pages
each one is shown as a real PNG snapshot, captured from the executed
notebook in a headless JupyterLab (`pixi run capture-widgets`); run the
notebooks in JupyterLab (`pixi run lab`) for the full interactive
experience. Static SVG/PNG exports ({mod}`longeron.render`) and
matplotlib figures render normally below.
:::

:::{note}
Tutorial 7 measures geometry with `engine='auto'`: the CAD engine when
cadquery is installed, the mesh engine otherwise. cadquery is
deliberately absent from the docs build (its OCC kernel is ~1 GB), so
the occlusion numbers on that page are the mesh engine's, as the
notebook itself explains.
:::

| Tutorial | Covers |
|---|---|
| {doc}`1. The model is data <01_the_model_is_data>` | what a parsed model IS: the dataclass tree, programmatic authoring, lossless JSON round-trips, save/load, the KerML projection, `validate()` and `longeron lint` |
| {doc}`2. The model executes <02_the_model_executes>` | the datasheet's claimed max speed, computed: expression evaluation, the drone's own calcs, instantiation, constraint what-ifs, requirement verdicts, the mission action graph, the flight state machine |
| {doc}`3. Views for review <03_views_for_review>` | reading the model without reading text: the explorer tree with relationship rows, four diagram views from one dispatcher, the app sidebar and item inspector, the canonical selection seam, edits with honest refusals, saved views as review artifacts |
| {doc}`4. Trades: sizing the fleet <04_trades_sizing_the_fleet>` | three missions, one airframe family: the catalog, the mission studies and their physics lessons, brushing the mission space, shapes to scale in 3D, the compromise dashboard, OpenMDAO sizing with the N2 map, results saved back into the model |
| {doc}`5. Individuals: populations, not possibilities <05_individuals_populations>` | M0 interpretations: features read as sequences, roll-ups over the individuals that exist, nominal vs random populations, Monte-Carlo over the catalog, traces as interpretations, entities across the OpenMDAO bridge |
| {doc}`6. Requirements: score, hunt, prove <06_requirements_score_hunt_prove>` | how good is the fleet, and where does it break: the MAUT scoreboard with model-declared weights and utility shapes, what-if injection, the trade-study bridge, `verify` hunting violations (hunt, sequences, cover, prove), Z3 requirement consistency |
| {doc}`7. Geometry and the mission <07_geometry_and_the_mission>` | who measured the geometry claims: the 3D scene as a rendering of the M0 population, per-configuration geometry in the linked views, view-cone occlusion and disc clearance, the violating variant painted where it hurts, the mission on the globe |
| {doc}`8. The knowledge graph <08_the_knowledge_graph>` | three questions grep cannot answer: SPARQL over the model's RDF projection, the retrieval substrate, how an agent consumes the model, answers verified against tutorial 4's dashboard |
| {doc}`9. The grand tour <09_grand_tour>` | one dashboard, every seam: structure diagram, linked 3D CAD with a live camera-occlusion what-if, the requirements scoreboard recoloring live, an OpenMDAO sizing strip, Z3 consistency verdicts, and the Cesium mission replay -- one `grand_dashboard` call |

The notation gallery is reference material, not a tutorial. It lives in
the reference section: {doc}`../reference/notation_gallery`.

```{toctree}
:hidden:
:maxdepth: 1

01_the_model_is_data
02_the_model_executes
03_views_for_review
04_trades_sizing_the_fleet
05_individuals_populations
06_requirements_score_hunt_prove
07_geometry_and_the_mission
08_the_knowledge_graph
09_grand_tour
```
