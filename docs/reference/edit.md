# Model editing

Small, verified mutations for UI inspectors: rename with a full
reference cascade (or an honest refusal), value edits that validate
unit semantics before mutating (a fake or wrong-dimension unit is
refused, never stored) and accept the compact quantity form the
inspector displays (``17 g``, and prefix-composed symbols like
``17 mg`` -- resolved through the model's own unit vocabulary and
stored as the canonical bracket expression), documentation edits, and
a change-tracking seam -- every operation keeps the textual export
parseable and at a fixpoint.

```{eval-rst}
.. automodule:: longeron.edit
```
