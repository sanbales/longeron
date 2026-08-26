# Requirements scoreboard

Scoring runs on the interpreter alone; the widget requires the `viz`
extra (`pip install "longeron[viz]"`).

The reserved attributes on a requirement (`weight`, `utility`,
`measure`, and the display-only `unit`) are documented in the module
docstring below; the `unit` attribute annotates the raw value in
tooltips and tables without any conversion (a units integration is
designed separately).

```{eval-rst}
.. automodule:: longeron.analysis.scoreboard
```
