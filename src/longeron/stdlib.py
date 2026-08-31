"""The vendored SysML v2 standard library (Stage D).

A curated subset of the official
`SysML-v2-Release <https://github.com/Systems-Modeling/SysML-v2-Release>`_
model library ships with this package (see ``longeron/_stdlib/README.md``):
the complete Systems Library, the core Quantities-and-Units files, the
Analysis domain-library files (``AnalysisTooling``, ``TradeStudies``), and
a small shim for the KerML kernel names (``ScalarValues::Real``, ...).
Longeron-authored extension libraries (``LongeronSurfaces``) ship beside
the vendored content in ``_stdlib/extensions/`` -- self-declaring, and
never labeled standard.

Loading the library cold takes minutes with the ANTLR Python runtime, so a
prebuilt serialization ships alongside the sources and the content-addressed
workspace cache backs it up: after the first build, loads take milliseconds.
The prebuilt is plain JSON in the same lossless schema as
:func:`longeron.to_json` -- inspectable text, no pickles.

    model = longeron.loads("...user model...")
    longeron.add_standard_library(model)
    interp = longeron.Interpreter(model)
    interp.resolve("Parts::Part")
    interp.evaluate("ISQ::mass")   # resolvable now
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import model as M
from .workspace import load_dir

_STDLIB_DIR = Path(__file__).parent / "_stdlib"
_PREBUILT = _STDLIB_DIR / "prebuilt.json"

_prebuilt_data: dict | None = None
_fingerprint_cache: str | None = None


def _stdlib_fingerprint() -> str:
    """Hash of everything that affects the prebuilt JSON's validity:
    the model/AST class definitions and the vendored library sources.
    (Builder changes require ``make stdlib`` to refresh the prebuilt.)
    """

    global _fingerprint_cache
    if _fingerprint_cache is None:
        from . import ast as ast_module
        from . import model as model_module

        digest = hashlib.sha256()
        for module in (model_module, ast_module):
            module_file = getattr(module, "__file__", None)
            if module_file:
                digest.update(Path(module_file).read_bytes())
        for source in sorted(_STDLIB_DIR.rglob("*.sysml")):
            digest.update(source.read_bytes())
        _fingerprint_cache = digest.hexdigest()[:16]
    return _fingerprint_cache


def standard_library_dir() -> Path:
    return _STDLIB_DIR


def standard_library_model(*, cache: bool = True) -> M.Model:
    """A fresh :class:`~longeron.model.Model` of the vendored library.

    Each call returns independent objects (safe to merge into user models).
    """

    from .importer import from_dict

    global _prebuilt_data
    if _prebuilt_data is None:
        _prebuilt_data = _load_prebuilt_data()
    if _prebuilt_data:
        model = from_dict(_prebuilt_data)
        if isinstance(model, M.Model):
            return model
    model = load_dir(_STDLIB_DIR, cache=cache)
    # Stable symbolic name (house convention for non-disk sources): the
    # loading machine's absolute _stdlib path must not ship in prebuilt.json.
    model.source_name = "<stdlib>"
    _store_prebuilt(model)
    return model


def add_standard_library(model: M.Model, *, cache: bool = True) -> M.Model:
    """Add the standard-library packages to ``model`` (idempotent)."""

    existing = {m.name for m in model.members if m.name}
    library = standard_library_model(cache=cache)
    for package in list(library.members):
        if package.name not in existing:
            model.add(package)
    return model


def _load_prebuilt_data() -> dict:
    """The prebuilt's model dict, when the bundled JSON is usable."""

    try:
        with _PREBUILT.open(encoding="utf-8") as handle:
            payload = json.load(handle)
        if payload.get("fingerprint") == _stdlib_fingerprint():
            model_data = payload["model"]
            if isinstance(model_data, dict):
                return model_data
    except Exception:  # missing, corrupt, or stale
        pass
    return {}


def _store_prebuilt(model: M.Model) -> None:
    """Best-effort refresh of the bundled prebuilt JSON."""

    from .export import to_dict

    global _prebuilt_data
    data = to_dict(model)
    _prebuilt_data = data
    try:
        with _PREBUILT.open("w", encoding="utf-8") as handle:
            json.dump({"fingerprint": _stdlib_fingerprint(), "model": data}, handle, indent=1)
    except OSError:  # read-only installation: the workspace cache still helps
        pass
