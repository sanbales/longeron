# Surfaces

Requires the `viz` extra for the widgets (`pip install "longeron[viz]"`);
the measure runners reach their engines lazily (the `mdao` extra for the
sizing what-if, the mesh engine ships with the core).

Design: [Model-defined analysis surfaces](../../design/surfaces.md).
The declaration the engine derives from is model content: see
`examples/deepscout/surfaces.sysml` (the `ScoutSurfaces` package) and the
`LongeronSurfaces` rendering vocabulary shipped beside the vendored
standard library.

```{eval-rst}
.. automodule:: longeron.analysis.surfaces
```
