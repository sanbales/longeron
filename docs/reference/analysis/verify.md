# Verify

Requires the `verify` extra (`pip install "longeron[verify]"`) for the
Hypothesis-driven tiers; `cover` and `prove` reach Z3 through the bundled
`smt` extra, and every tier degrades to recorded `gaps` where an engine
is missing.

```{eval-rst}
.. automodule:: longeron.analysis.verify
```
