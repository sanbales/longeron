"""The vendored SysML v2 standard library (Stage D).

A curated subset of the official
`SysML-v2-Release <https://github.com/Systems-Modeling/SysML-v2-Release>`_
model library ships with this package (see ``sysml2/_stdlib/README.md``):
the complete Systems Library plus the core Quantities-and-Units files, and a
small shim for the KerML kernel names (``ScalarValues::Real``, ...).

Loading the library cold takes minutes with the ANTLR Python runtime, so a
prebuilt pickle is bundled and the content-addressed workspace cache backs
it up: after the first build, loads take milliseconds.

    model = sysml2.loads("...user model...")
    sysml2.add_standard_library(model)
    interp = sysml2.Interpreter(model)
    interp.resolve("Parts::Part")
    interp.evaluate("ISQ::mass")   # resolvable now
"""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path

from . import model as M
from .workspace import load_dir

_STDLIB_DIR = Path(__file__).parent / "_stdlib"
_PREBUILT = _STDLIB_DIR / "prebuilt.pkl"

_raw_prebuilt: bytes | None = None
_fingerprint_cache: str | None = None


def _stdlib_fingerprint() -> str:
    """Hash of everything that affects the prebuilt pickle's validity:
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
    """A fresh :class:`~sysml2.model.Model` of the vendored library.

    Each call returns independent objects (safe to merge into user models).
    """

    global _raw_prebuilt
    if _raw_prebuilt is None:
        _raw_prebuilt = _load_prebuilt_bytes()
    if _raw_prebuilt:
        model = pickle.loads(_raw_prebuilt)
        if isinstance(model, M.Model):
            return model
    model = load_dir(_STDLIB_DIR, cache=cache)
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


def _load_prebuilt_bytes() -> bytes:
    """Return pickled model bytes when the bundled prebuilt is usable."""

    try:
        with _PREBUILT.open("rb") as handle:
            header = pickle.load(handle)
            if header == _stdlib_fingerprint():
                return handle.read()
    except Exception:  # missing, corrupt, or stale
        pass
    return b""


def _store_prebuilt(model: M.Model) -> None:
    """Best-effort refresh of the bundled prebuilt pickle."""

    global _raw_prebuilt
    payload = pickle.dumps(model, protocol=pickle.HIGHEST_PROTOCOL)
    _raw_prebuilt = payload
    try:
        with _PREBUILT.open("wb") as handle:
            pickle.dump(_stdlib_fingerprint(), handle,
                        protocol=pickle.HIGHEST_PROTOCOL)
            handle.write(payload)
    except OSError:  # read-only installation: the workspace cache still helps
        pass
