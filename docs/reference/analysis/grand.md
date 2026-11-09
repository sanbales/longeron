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

The returned `VBox` exposes each pane as an attribute, for scripts and
tests:

| Place | Pane | Attributes |
|---|---|---|
| top | header | `.header` |
| row 1 | containment tree | `.tree` (a {class}`~longeron.widgets.explorer.ModelTree`) |
| row 1 | structure diagram | `.diagram` |
| row 1 | 3D pane | `.viewer`, `.config_view`, `.unlink`, `.mesh`, `.part_map`, `.camera` |
| row 1 | requirements scoreboard | `.board`, `.scoreboard`, `.requirements` |
| row 2 | subject card | `.mission_toggle`, `.subject_card`, `.knobs`, `.knob_set` |
| row 2 | camera what-if | `.elevation`, `.azimuth`, `.readout`, `.report` |
| row 2 | OpenMDAO sizing strip | `.sizing_title`, `.loiter`, `.optimize`, `.problem`, `.optimum`, `.sizing_card` |
| row 2 | driver history (in the sizing strip) | `.sizing_history` |
| row 2 | design variable and constraint table (in the sizing strip) | `.sizing_table` |
| row 2 | N2 matrix (in the sizing strip) | `.sizing_n2` |
| row 2 | Z3 verdict strip | `.verdict_title`, `.smt_sat`, `.smt_what_if`, `.verdicts` |
| bottom | Cesium pane | `.mission`, `.track` |

The subject state is `.subject`, `.architecture` (the trade-study
result with the overrides applied), `.craft` (the qualified name of the
airframe definition) and `.studies` (one trade study per visited
mission). `.sizing_contexts` holds the mission-to-context map, and `.values` the
injected scoreboard values. The
sizing and Z3 attributes are `None` for a mission without a sizing
context.

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
