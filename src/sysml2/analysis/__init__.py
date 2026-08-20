"""Analytical bridges from SysML v2 models onto external solvers.

Submodules (each imports its solver lazily; the package itself has no
third-party dependencies):

* :mod:`sysml2.analysis.mdao` -- continuous sizing/optimization on OpenMDAO
  (``pip install "longeron[mdao]"``).
* :mod:`sysml2.analysis.trades` -- discrete architecture trade studies over
  variation/variant catalogs on OR-Tools CP-SAT
  (``pip install "longeron[trades]"``).
* :mod:`sysml2.analysis.smt` -- requirement consistency, conflict cores, and
  design-space bounds over the reals on Z3
  (``pip install "longeron[smt]"``).
"""

from ._expr import AnalysisError

__all__ = ["AnalysisError", "mdao", "smt", "trades"]
