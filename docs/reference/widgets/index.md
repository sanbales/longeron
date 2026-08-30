# Widgets

`longeron.widgets` is the way into the house widgets. The catalog
below re-exports the canonical entry point of every interactive
front-end, so one import surface covers them all:

```python
from longeron.widgets import explore, mission_dashboard
```

The catalog is lazy (PEP 562). `import longeron.widgets` loads no
widget toolkit, and each entry imports its home module on first
access. If an entry's extra is missing, the entry raises
{class}`~longeron.errors.MissingExtraError` with the exact install
command when you reach for it.

The package is also the shared toolkit for widget authors and the
mandatory home for every new widget. New widgets land here as
submodules, as {mod}`longeron.widgets.graph3d` does.

## The catalog

| Entry | What it is | Extras | Taught in |
|---|---|---|---|
| `explore` | The model explorer: a tree navigator beside a diagram pane. | `replay` (`explorer` for Lab docking) | {doc}`Tutorial 3 </tutorials/03_views_for_review>` |
| `Explorer` | The explorer widget class that `explore` builds. | `replay` | {doc}`Tutorial 3 </tutorials/03_views_for_review>` |
| `ModelTree` | The explorer's tree engine: disclosure rows, kind badges, live filter. | `replay` | {doc}`Tutorial 3 </tutorials/03_views_for_review>` |
| `ModelApp` | The review workbench class that `open` builds. | `replay` | {doc}`Tutorial 3 </tutorials/03_views_for_review>` |
| `open` | The review workbench: model list, explorer tabs, item inspector. | `replay` (`explorer` for Lab docking) | {doc}`Tutorial 3 </tutorials/03_views_for_review>` |
| `Inspector` | The property sheet; `open` builds one as `app.inspector`. | `replay` | {doc}`Tutorial 3 </tutorials/03_views_for_review>` |
| `diagram` | The diagram dispatcher: picks the view from the element's kind. | vendored ipyelk | {doc}`Tutorial 3 </tutorials/03_views_for_review>` |
| `structure_diagram` | Parts, ports, and connections as an interactive ELK diagram. | vendored ipyelk | {doc}`Tutorial 4 </tutorials/04_trades_sizing_the_fleet>` |
| `state_diagram` | A state machine as an interactive ELK diagram. | vendored ipyelk | {doc}`Tutorial 2 </tutorials/02_the_model_executes>` |
| `action_diagram` | An action's control flow as an interactive ELK diagram. | vendored ipyelk | {doc}`Tutorial 3 </tutorials/03_views_for_review>` (via `diagram`) |
| `replay_widget` | Simulate an element and replay the run over its diagram. | `replay`, vendored ipyelk, node | [Replay reference](../replay.md) |
| `scoreboard` | The MAUT requirements scoreboard: area is importance, color is utility. | `viz` (the widget; scoring needs none) | {doc}`Tutorial 6 </tutorials/06_requirements_score_hunt_prove>` |
| `mission_dashboard` | The linked mission-compromise dashboard. | `viz` | {doc}`Tutorial 4 </tutorials/04_trades_sizing_the_fleet>` |
| `grand_dashboard` | The grand tour: diagram, CAD, scoreboard, sizing, consistency, and the mission globe on one surface. | `viz`, `mdao`, `smt`, vendored ipyelk | {doc}`Tutorial 9 </tutorials/09_grand_tour>` |
| `mesh_viewer` | Baked geometry meshes in a three.js canvas, at true scale. | `viz` | {doc}`Tutorial 4 </tutorials/04_trades_sizing_the_fleet>` |
| `mission_viewer` | Fly a mission track on a Cesium globe. | `viz` | {doc}`Tutorial 7 </tutorials/07_geometry_and_the_mission>` |
| `graph_viewer` | The RDF projection as an interactive 3D force graph. | `rdf`, `viz` | {doc}`Tutorial 8 </tutorials/08_the_knowledge_graph>` |
| `Clock` | The shared playhead for one linked group of time-aware views. | none | [Time seam reference](time.md) |
| `Timebase` | One recording, many views: a trace plus its optional mission binding. | none | [Time seam reference](time.md) |
| `link_time` | Wire time-aware views to one clock: the temporal `link_selection`. | none | [Time seam reference](time.md) |
| `time_scrubber` | The standalone transport bar: play/pause, rate, the shared time axis. | `replay` | [Time seam reference](time.md) |

The pip extras install as `pip install "longeron[replay,viz]"` (or any
subset). The vendored ipyelk installs as `pip install -e vendor/ipyelk`
from a repo checkout. `replay_widget` also needs a `node` executable on
`PATH` for the baked SVG.

```{eval-rst}
.. automodule:: longeron.widgets
```

```{toctree}
:maxdepth: 1

graph3d
time
```
