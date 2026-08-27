# Units

The two Python-side tiers of the [units design](../design/units.md):
the in-house derived unit table that powers the
[dimensional lint](../guides/validation.md#the-dimensional-lint), and
the typed conversion facade behind the `[units]` extra:

```bash
pip install "longeron[units]"   # pint + pint-pandas
```

The core tier needs **no** extra: dimension vectors, SI factors, and
scale tags are derived from the vendored quantities library's own
definitional algebra (`newton = kg*m/s^2` survives in the model), and
user packages shaped like the standard library derive the same way.
The facade wraps pint so its `Quantity` never appears in a public
signature -- floats and unit strings in, floats out:

```python
from longeron import units

units.convert(25.0, "°C", "K")  # 298.15
units.convert(3.0, "dBm", "mW")  # ~1.995
units.si_value(30.0, "min")  # 1800.0
units.si_unit("dBm")  # 'W'
units.format_quantity(0.254, "m")  # '0.254 m'  (no pint needed)
units.om_unit("min")  # 'min'      (no pint needed)
units.with_units(df, {"mass": "kg", "flightTime": "min"})
```

Unit strings are the *model's* vocabulary -- `"SI::kg"`, `"kg"`,
`"°C"`, `"dBm"` -- resolved through the derived table first and mapped
to pint spellings automatically (table-derived definitions cover units
pint does not know). {func}`~longeron.units.register_unit` overrides or
extends the table; {func}`~longeron.units.define` passes a raw pint
definition through for boundary-side spellings.

## Conversion seams reserved for 0.11

Per the ratified design, the conversion *hooks* into the analysis
bridges are seams this release -- documented here, wired next:

- **Declaration-boundary normalization.** With the extra installed,
  evaluating a `QuantityOp` will multiply the declared magnitude
  through to canonical SI ({func}`~longeron.units.si_value`), so
  instance slots hold SI floats and mixed same-dimension arithmetic
  becomes correct automatically. Until it lands, the `mixed-units`
  lint gate ({func}`~longeron.units.units_extra_available`) marks the
  spot, and declared magnitudes pass through unchanged exactly as
  today.
- **OpenMDAO bridge.** `add_input` / `add_output` calls in
  {mod}`longeron.analysis.mdao` gain `units=om_unit(...)` -- values
  crossing the bridge are canonical SI after normalization, so the
  kwarg is the SI unit's OM spelling (`"kg"`, `"m/s"`, `"degK"`).
  {func}`~longeron.units.om_unit` is ready today and returns `None`
  where OM has no spelling (the dB family), leaving those variables
  unitless exactly as now.
- **Scoreboard.** Tooltips render through
  {func}`~longeron.units.format_quantity` in the declared display
  unit; ramp anchors declared in one unit score measures computed in
  another through one {func}`~longeron.units.convert` at *build* time.
  Until then the `anchor-dimension-mismatch` lint flags the disagreement
  statically.

The interpreter invariant survives all three: evaluation, instance
slots, M0 populations, and `compute()` bodies see only plain floats.

```{eval-rst}
.. automodule:: longeron.units
```
