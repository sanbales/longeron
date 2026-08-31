"""Multi-file workspaces and a content-addressed model cache.

Loading
=======
``load`` is the universal entry point:

* a ``.sysml`` file -> parsed and built,
* a ``.json`` file -> imported via :mod:`longeron.importer`,
* a directory -> every ``*.sysml`` file beneath it (sorted, recursive),
  merged into one :class:`~longeron.model.Model` so cross-file imports and
  qualified references resolve.

Caching
=======
Built models are cached as JSON in a content-addressed cache
(``$LONGERON_CACHE_DIR``, ``$XDG_CACHE_HOME/longeron``, or ``~/.cache/longeron``).
Cache entries use the same lossless schema as :func:`longeron.to_json` -- no
pickles, so entries are inspectable text and never execute code on load.
An entry's key is the SHA-256 of the source text plus a fingerprint of the
generated parser, builder, model, and AST code -- editing a source file,
regenerating the grammar, or upgrading the package all invalidate cleanly.
Caching defaults to on -- for single files as well as directories, since
the dominant cold-load cost (ANTLR ATN warmup) is paid per process either
way; pass ``cache=False`` to opt out.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from . import model as M
from .builder import build_model
from .errors import BuildError
from .parser import parse_sysml_text

_FINGERPRINT: str | None = None


def _fingerprint() -> str:
    """Hash of the code that determines a built model's shape.

    Any change to the generated parser, the builder, the model classes, the
    expression AST, the JSON serialization layer (exporter/importer -- the
    schema cache entries are written and read in), or the package version
    invalidates all cached models.
    """

    global _FINGERPRINT
    if _FINGERPRINT is None:
        from . import __version__, ast, builder, export, importer, model, parser
        from ._gen.sysml import SysMLParser

        digest = hashlib.sha256(__version__.encode())
        for module in (ast, builder, export, importer, model, parser, SysMLParser):
            module_file = getattr(module, "__file__", None)
            if module_file:
                digest.update(Path(module_file).read_bytes())
        _FINGERPRINT = digest.hexdigest()[:16]
    return _FINGERPRINT


def cache_dir() -> Path:
    """The directory used for cached models (created on demand)."""

    override = os.environ.get("LONGERON_CACHE_DIR")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "longeron"


def clear_cache() -> int:
    """Delete all cached models; returns the number of entries removed."""

    root = cache_dir()
    if not root.is_dir():
        return 0
    removed = 0
    for entry in root.glob("*.json"):
        entry.unlink(missing_ok=True)
        removed += 1
    for entry in root.glob("*.pkl"):  # entries from pre-JSON versions
        entry.unlink(missing_ok=True)
        removed += 1
    return removed


def _cache_path(text: str) -> Path:
    key = hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]
    return cache_dir() / f"{key}-{_fingerprint()}.json"


def _cache_load(path: Path) -> M.Model | None:
    from .importer import from_dict

    try:
        with path.open(encoding="utf-8") as handle:
            cached = from_dict(json.load(handle))
    except Exception:  # missing, corrupt, or stale-format entry
        return None
    return cached if isinstance(cached, M.Model) else None


def _cache_store(path: Path, model: M.Model) -> None:
    from .export import to_dict

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(to_dict(model), handle, separators=(",", ":"))
        os.replace(handle.name, path)  # atomic under concurrent writers
    except OSError:
        pass  # caching is best-effort


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_file(path: str | Path, *, cache: bool = True) -> M.Model:
    """Parse and build a single ``.sysml`` file (optionally cached)."""

    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if cache:
        entry = _cache_path(text)
        cached = _cache_load(entry)
        if cached is not None:
            cached.source_name = str(source)
            return cached
    model = build_model(parse_sysml_text(text, str(source)))
    if cache:
        _cache_store(entry, model)
    return model


def load_many(paths: Iterable, *, cache: bool = True) -> M.Model:
    """Load several ``.sysml``/``.json`` files into one merged model."""

    sources = [Path(p) for p in paths]
    if not sources:
        raise BuildError("no files to load")
    models = [_load_single(p, cache=cache) for p in sources]
    return _merge_models_move(models, source_name=", ".join(str(p) for p in sources))


def load_dir(root: str | Path, *, recursive: bool = True, cache: bool = True) -> M.Model:
    """Load every ``*.sysml`` file under a directory into one model.

    Files are loaded in sorted path order for determinism.  ``.kerml``
    files are ignored (KerML is parse/validate-only in this package).
    Every top-level member of the merged model records the file it came
    from (``member.source_file``), which is what
    :func:`longeron.export.save_workspace` writes edits back to.
    """

    base = Path(root)
    pattern = "**/*.sysml" if recursive else "*.sysml"
    files = sorted(base.glob(pattern))
    if not files:
        raise BuildError(f"no .sysml files found under {base}")
    models = []
    for path in files:
        model = load_file(path, cache=cache)
        for member in model.members:
            # the per-file provenance breadcrumb save-back needs
            # (:func:`longeron.export.save_workspace`): a plain attribute,
            # like ``source_location``, so cache entries and JSON exports
            # are unaffected.  Stamped here -- after ``load_file`` -- so
            # cache hits carry it too.
            member.source_file = str(path)  # type: ignore[assignment]
        models.append(model)
    return _merge_models_move(models, source_name=str(base))


def merge_models(models: Iterable[M.Model], source_name: str = "<merged>") -> M.Model:
    """Combine the top-level members of several models under one root.

    The inputs are left untouched: each model is deep-copied and the copies'
    members are re-owned by the merged root, so mutating the result never
    aliases the sources (and vice versa).
    """

    return _merge_models_move([copy.deepcopy(m) for m in models], source_name)


def _merge_models_move(models: Iterable[M.Model], source_name: str) -> M.Model:
    """Merge by *moving* members (rebinds ``member.owner``; internal use
    only, for freshly loaded per-file models that have no other owner)."""

    combined = M.Model(source_name=source_name)
    for model in models:
        for member in model.members:
            combined.add(member)
    return combined


def _load_single(path: Path, *, cache: bool) -> M.Model:
    if path.suffix.lower() == ".json":
        from .importer import from_json

        return from_json(path.read_text(encoding="utf-8"))
    return load_file(path, cache=cache)


def load(path: str | Path, *, cache: bool | None = None) -> M.Model:
    """Load a model from a ``.sysml`` file, a ``.json`` export, or a
    directory of ``.sysml`` files.

    ``cache=None`` (the default) enables the model cache; pass
    ``cache=False`` to parse from source unconditionally.
    """

    source = Path(path)
    enabled = True if cache is None else cache
    if source.is_dir():
        return load_dir(source, cache=enabled)
    return _load_single(source, cache=enabled)
