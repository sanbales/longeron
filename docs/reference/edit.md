# Model editing

Small, verified mutations for UI inspectors: rename with a full
reference cascade (or an honest refusal), value edits that validate
unit semantics before mutating (a fake or wrong-dimension unit is
refused, never stored), documentation edits, and a change-tracking
seam -- every operation keeps the textual export parseable and at a
fixpoint.

```{eval-rst}
.. automodule:: longeron.edit
```
