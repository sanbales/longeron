# Grand tour dashboard

Requires the `viz` extra for the widgets and the `mdao`/`smt` extras for
the sizing and verdict strips (`pip install "longeron[viz,mdao,smt]"`).

`grand_dashboard` shows one **subject**: one mission architecture
({class}`~longeron.analysis.subject.Subject`). A mission architecture is
a mission definition, one airframe variant, and one variant for each
other variation point. Every pane follows the subject. The
{doc}`grand tour tutorial </tutorials/09_grand_tour>` builds the
dashboard and proves each reaction headless.

```python
import longeron
from longeron.analysis.grand import grand_dashboard

program = longeron.load("examples/deepscout")
dash = grand_dashboard(program)  # the ISR winner
dash = grand_dashboard(program, mission="logistics", airframe="flyingWingTwinTip")
```

## Layout and exposed pieces

The layout fits one 1080p screen. A **tab group** is a set of panes that
share one place, and its tab bar shows one pane at a time. Below the
header, one row holds three columns:

- The **tree column** at the left is as tall as the row. Its button
  (`.tree_toggle`) collapses the column to a thin strip, and the structure
  diagram takes the width. A click on the strip expands the column again.
- The centre column holds the structure diagram over the **Analysis
  tabs** (`.analysis`), a tab group.
- The **Views tabs** (`.views`) at the right are a tab group.

Each pane of one tab group shows beside each pane of the other. For
example, the *Subject & knobs* tab shows the sliders beside the 3D pane
or the scoreboard that they repaint.

The returned `VBox` exposes each pane as an attribute, for scripts and
tests:

| Place | Pane | Attributes |
|---|---|---|
| top | header | `.header` |
| tree column | containment tree | `.tree` (a {class}`~longeron.widgets.explorer.ModelTree`), `.tree_toggle` |
| centre column | structure diagram | `.diagram` |
| Views tabs: *3D* | 3D pane | `.viewer`, `.config_view`, `.unlink`, `.mesh`, `.part_map`, `.camera` |
| Views tabs: *Requirements* | requirements scoreboard | `.board`, `.scoreboard`, `.requirements` |
| Views tabs: *Mission* | Cesium pane | `.mission`, `.track` |
| Analysis tabs: *Subject & knobs* | subject card | `.mission_toggle`, `.subject_card`, `.knobs`, `.knob_set` |
| Analysis tabs: *Camera what-if* | camera what-if | `.elevation`, `.azimuth`, `.readout`, `.report` |
| Analysis tabs: *Sizing* | OpenMDAO sizing strip | `.sizing_title`, `.loiter`, `.optimize`, `.problem`, `.optimum`, `.sizing_card` |
| Analysis tabs: *Sizing* | driver history | `.sizing_history` |
| Analysis tabs: *Sizing* | design variable and constraint table | `.sizing_table` |
| Analysis tabs: *Sizing* | N2 matrix | `.sizing_n2` |
| Analysis tabs: *Z3* | Z3 verdict strip | `.verdict_title`, `.smt_sat`, `.smt_what_if`, `.verdicts` |
| JupyterLab main area | docked panes | `.dock`, `.undock`, `.panels` |

The subject state is `.subject`, `.architecture` (the trade-study
result with the overrides applied), `.craft` (the qualified name of the
airframe definition) and `.studies` (one trade study per visited
mission). `.sizing_contexts` holds the mission-to-context map, and `.values` the
injected scoreboard values. The
sizing and Z3 attributes are `None` for a mission without a sizing
context.

## Dock the panes in JupyterLab

`dash.dock()` moves the panes into the JupyterLab **main area**, the part
of the window that shows the notebook and the other open documents. Each
pane group becomes a **docked pane**: an `ipylab.Panel` with a titled tab.
A **split bar** is the thin bar between two docked panes. A drag of a
split bar resizes the two panes, and a drag of a tab moves a pane.

| Tab | Widgets | Tab key (`data-lgxkey`) |
|---|---|---|
| Tree | `.tree` | `grand-tree` |
| Structure | `.diagram` | `grand-structure` |
| 3D | `.viewer` | `grand-3d` |
| Scoreboard | `.board` | `grand-scoreboard` |
| Subject | `.header` and the subject card | `grand-subject` |
| Camera what-if | the camera what-if card | `grand-camera` |
| Sizing | the OpenMDAO sizing strip | `grand-sizing` |
| Z3 | the Z3 verdict strip | `grand-z3` |
| Mission | `.mission` | `grand-mission` |

The first view shows each pane in its own panel. The first four tabs make
the top row, and the four cards make the next row. The inline tab groups
do not dock. `dash.undock()` puts each pane back into its tab group. The *Mission* tab is the
current tab of the notebook's tab area, at the bottom. `.panels` maps each
pane name to its panel while the tour is docked, and it is empty while
the tour is inline.

The docked panes hold the same widget instances as the inline layout, so
the selection links keep working. A closed tab does not close its
widgets. A second `dash.dock()` closes the open panels and docks all nine
panes again in the first view. `dash.undock()` closes the panels and shows
the inline layout again. `grand_dashboard(..., dock=True)` docks the
dashboard when it is built. If no JupyterLab front end hosts the kernel,
`dock()` prints a note and the layout stays inline.

## Driver renderings

The three driver renderings explain the OpenMDAO problem of the sizing
context. A **driver iteration** is one model evaluation that the
optimization driver records:

- `.sizing_history` plots the objective and each constraint margin for each
  driver iteration of the last *maximize* run. A margin is zero at the bound
  of its constraint. Before the first run, it says "run maximize to see the
  driver's path".
- `.sizing_table` lists the design variables and the constraints with their
  lower bound, current value and upper bound. A constraint value is its
  margin. The loiter slider updates the values. A *maximize* run sets the
  active flags. An **active** constraint is at a bound at the optimum.
- `.sizing_n2` is an N2 matrix of the problem: the components on the
  diagonal, and a mark where an output of the row component feeds an input
  of the column component. The hover title of a mark names the connected
  variables.

{func}`~longeron.analysis.mdao.run_optimization` returns the
{class}`~longeron.analysis.mdao.OptimizationHistory` of a run, and
{func}`~longeron.analysis.mdao.problem_structure` returns the
{class}`~longeron.analysis.mdao.ProblemStructure` behind the matrix.

## API

```{eval-rst}
.. automodule:: longeron.analysis.grand
```
