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
* :mod:`longeron.analysis.viz` -- figures and a parallel-coordinates widget
  over trade-study results (``pip install "longeron[viz]"``).
* :mod:`longeron.analysis.geometry` / :mod:`longeron.analysis.viewer3d` --
  parametric to-scale meshes for architecture mixes (stdlib only) and a
  small three.js anywidget that renders them (``viz`` extra; CAD-solid
  export needs ``pip install "longeron[cad]"``).
* :mod:`longeron.analysis.dashboard` -- the linked mission-compromise
  dashboard composing the widgets above with ipywidgets (``viz`` extra).
* :mod:`longeron.analysis.link` -- linked selection between the
  interactive diagrams and the 3D viewer: diagram clicks highlight the
  matching meshes, mesh picks select the diagram node (``viz`` extra
  plus the vendored ipyelk for the diagram side).
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
    "link",
    "mdao",
    "smt",
    "structure",
    "trades",
    "viewer3d",
    "viz",
]
