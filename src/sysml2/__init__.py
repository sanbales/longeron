"""Compatibility alias: ``import sysml2`` is :mod:`longeron`.

The package was renamed to ``longeron`` in 0.3.0.  This shim keeps every
historical ``sysml2`` import working -- ``import sysml2``,
``import sysml2.analysis.trades``, ``from sysml2 import diagrams`` -- by
handing back longeron's *own* module objects (never copies), so module
state and ``isinstance`` checks agree across both names.  Silent (no
DeprecationWarning) for now; the ``sysml2`` name is documented as an alias.
"""

import importlib
import importlib.abc
import importlib.util
import sys

import longeron
from longeron import *  # the whole public surface (F403 ignored for this shim)

__all__ = list(longeron.__all__)
__version__ = longeron.__version__
__path__: list = []  # a "package", but submodules resolve via the finder below


class _AliasLoader(importlib.abc.Loader):
    """Hand the import machinery the real longeron module itself."""

    def __init__(self, real):
        self._real, self._spec = real, real.__spec__

    def create_module(self, spec):
        return self._real  # identity, not a copy

    def exec_module(self, module):
        module.__spec__ = self._spec  # undo machinery's spec clobber


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Resolve ``sysml2.x[.y]`` to the already/lazily imported ``longeron.x[.y]``."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname != __name__ and fullname.startswith(__name__ + "."):
            try:
                real = importlib.import_module("longeron" + fullname[len(__name__) :])
            except ModuleNotFoundError:
                return None  # let the normal error surface under the sysml2 name
            return importlib.util.spec_from_loader(fullname, _AliasLoader(real))
        return None


# Must sit in FRONT of PathFinder: sysml2.analysis IS longeron.analysis, whose
# __path__ would otherwise let PathFinder import sysml2.analysis.* as duplicates.
sys.meta_path.insert(0, _AliasFinder())


def __getattr__(name):  # ``from sysml2 import rdf`` without a prior submodule import
    try:
        module = importlib.import_module(f"longeron.{name}")
    except ModuleNotFoundError as exc:  # AttributeError keeps hasattr()/inspect sane
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    sys.modules[f"{__name__}.{name}"] = module
    return module
