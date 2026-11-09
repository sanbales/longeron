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
| row 2 | Z3 verdict strip | `.verdict_title`, `.smt_sat`, `.smt_what_if`, `.verdicts` |
| bottom | Cesium pane | `.mission`, `.track` |

The subject state is `.subject`, `.architecture` (the trade-study
result with the overrides applied), `.craft` (the qualified name of the
airframe definition) and `.studies` (one trade study per visited
mission). `.sizing_contexts` holds the mission-to-context map, and `.values` the
injected scoreboard values. The
sizing and Z3 attributes are `None` for a mission without a sizing
context.

## API

```{eval-rst}
.. automodule:: longeron.analysis.grand
```
