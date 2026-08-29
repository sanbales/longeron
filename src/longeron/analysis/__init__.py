"""Analytical bridges from SysML v2 models onto external solvers.

Submodules (each imports its solver lazily; the package itself has no
third-party dependencies):

* :mod:`longeron.analysis.mdao` -- continuous sizing/optimization on OpenMDAO
  (``pip install "longeron[mdao]"``).
* :mod:`longeron.analysis.trades` -- discrete architecture trade studies over
  variation/variant catalogs on OR-Tools CP-SAT
  (``pip install "longeron[trades]"``).
* :mod:`longeron.analysis.smt` -- requirement consistency, conflict cores, and
  design-space bounds over the reals on Z3
  (``pip install "longeron[smt]"``).
* :mod:`longeron.analysis.verify` -- model-driven requirement-violation
  hunting: Hypothesis strategies derived from the model's own types and
  constraints (sampling + shrinking), adversarial event sequences against
  the real state machines, in-house IPOG-F t-way covering arrays with Z3
  as the constraint engine, Z3 absence proofs with exact bounds, and
  every catch materialized as re-checkable M0 individuals
  (``pip install "longeron[verify]"``).
* :mod:`longeron.analysis.scoreboard` -- a MAUT (multi-attribute utility)
  scoreboard over the requirements hierarchy: model-declared weights and
  utility shapes, pluggable aggregation, and an interactive
  treemap/Voronoi widget where area is importance and color is utility
  (the widget needs the ``viz`` extra; scoring runs on the interpreter
  alone).
* :mod:`longeron.analysis.viz` -- figures and a parallel-coordinates widget
  over trade-study results (``pip install "longeron[viz]"``).
* :mod:`longeron.analysis.geometry` / :mod:`longeron.analysis.viewer3d` --
  parametric to-scale meshes for architecture mixes (stdlib only) and a
  small three.js anywidget that renders them (``viz`` extra; CAD-solid
  export needs ``pip install "longeron[cad]"``).
* :mod:`longeron.analysis.mission3d` -- mission flight replay on a
  CesiumJS globe: waypoint- or state-machine-timeline-driven track
  synthesis and an anywidget that flies the drone -- its own to-scale
  mesh, exported to binary glTF in-house -- over satellite imagery
  with Cesium's native timeline as the playback UI (``viz`` extra; no
  Cesium ion token required).
* :mod:`longeron.analysis.dashboard` -- the linked mission-compromise
  dashboard composing the widgets above with ipywidgets (``viz`` extra).
* :mod:`longeron.analysis.grand` -- the grand-tour dashboard: structure
  diagram, linked 3D CAD with a live occlusion what-if, the requirements
  scoreboard, an OpenMDAO sizing strip, Z3 consistency verdicts, and the
  Cesium mission replay on ONE reactive surface (``viz`` extra plus
  ``mdao``/``smt`` for the solver strips).
* :mod:`longeron.analysis.link` -- linked selection between the
  interactive diagrams and the 3D viewer: diagram clicks highlight the
  matching meshes, mesh picks select the diagram node, and
  ``bind_config_view`` keys WHICH craft the viewer shows to the
  selection (``viz`` extra plus the vendored ipyelk for the diagram
  side).
* :mod:`longeron.analysis.structure` -- interactive views of the analysis
  problems' *shape*: an N2 matrix over a built OpenMDAO problem and a
  bipartite constraint-participation network over a trade study
  (``viz`` extra for the widgets).
"""

from ._expr import AnalysisError

__all__ = [
    "AnalysisError",
    "dashboard",
    "geometry",
    "grand",
    "link",
    "mdao",
    "mission3d",
    "scoreboard",
    "smt",
    "structure",
    "trades",
    "verify",
    "viewer3d",
    "viz",
]
