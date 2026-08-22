"""Every boolean flag on every model dataclass must round-trip through the
package's own JSON format (`to_dict`/`from_dict`) exactly.

This format backs the workspace model cache, so a dropped True flag would
silently corrupt models on cache hits (audit probe P16).  The sweep is
programmatic -- dataclass introspection over ``longeron.model`` -- so a new
element type or flag field is covered automatically.
"""

from __future__ import annotations

import dataclasses

import pytest

import longeron
from longeron import model as M
from longeron.export import to_dict
from longeron.importer import from_dict


def _model_dataclasses() -> list[type]:
    return [
        obj for obj in vars(M).values() if isinstance(obj, type) and dataclasses.is_dataclass(obj)
    ]


def _bool_fields(cls: type) -> list[dataclasses.Field]:
    return [
        f
        for f in dataclasses.fields(cls)
        if f.type in ("bool", bool) or isinstance(f.default, bool)
    ]


def _element_host(cls: type) -> tuple[M.Element, str, bool]:
    """An Element carrying an instance of non-Element dataclass ``cls``.

    Found by introspection: the first Element field whose annotation names
    ``cls``.  Returns (host, field name on host, wrapped-in-list?).
    """

    for host_cls in _model_dataclasses():
        if not issubclass(host_cls, M.Element):
            continue
        for f in dataclasses.fields(host_cls):
            annotation = str(f.type)
            if cls.__name__ not in annotation:
                continue
            host = host_cls()
            wrapped = annotation.startswith("list[")
            return host, f.name, wrapped
    raise AssertionError(f"no Element field hosts {cls.__name__}")


def _roundtrip_with_flag(cls: type, flag: str, value: bool) -> tuple[dict, object]:
    """to_dict -> from_dict an instance of ``cls`` with ``flag`` set; returns
    (serialized dict, reconstructed carrier of the flag)."""

    instance = cls()
    setattr(instance, flag, value)
    if issubclass(cls, M.Element):
        data = to_dict(instance)
        return data, from_dict(data)
    host, field_name, wrapped = _element_host(cls)
    setattr(host, field_name, [instance] if wrapped else instance)
    clone_host = from_dict(to_dict(host))
    carrier = getattr(clone_host, field_name)
    return to_dict(instance), carrier[0] if wrapped else carrier


ALL_FLAGS = sorted(
    ((cls, f) for cls in _model_dataclasses() for f in _bool_fields(cls)),
    key=lambda pair: (pair[0].__name__, pair[1].name),
)


def test_sweep_is_not_degenerate():
    # the introspection must keep finding the flag population; if this
    # shrinks below the 0.6.0 count, the sweep itself has regressed
    assert len(ALL_FLAGS) >= 30
    names = {f"{cls.__name__}.{f.name}" for cls, f in ALL_FLAGS}
    assert {"Definition.is_abstract", "Usage.is_variation", "Import.is_namespace"} <= names


@pytest.mark.parametrize(
    "cls,flag",
    [(cls, f.name) for cls, f in ALL_FLAGS],
    ids=[f"{cls.__name__}.{f.name}" for cls, f in ALL_FLAGS],
)
def test_true_flag_roundtrips(cls, flag):
    data, clone = _roundtrip_with_flag(cls, flag, True)
    assert data[flag] is True, f"{cls.__name__}.{flag}=True must be serialized"
    assert getattr(clone, flag) is True
    assert to_dict(clone)[flag] is True  # stable across a second pass


@pytest.mark.parametrize(
    "cls,flag",
    [(cls, f.name) for cls, f in ALL_FLAGS],
    ids=[f"{cls.__name__}.{f.name}" for cls, f in ALL_FLAGS],
)
def test_false_flag_roundtrips(cls, flag):
    field = next(f for f in dataclasses.fields(cls) if f.name == flag)
    data, clone = _roundtrip_with_flag(cls, flag, False)
    if field.default is False:
        assert flag not in data, "False with a False default stays compact"
    assert getattr(clone, flag) is False


@pytest.mark.parametrize(
    "cls,flag",
    [(cls, f.name) for cls, f in ALL_FLAGS if issubclass(cls, M.Element)],
    ids=[f"{cls.__name__}.{f.name}" for cls, f in ALL_FLAGS if issubclass(cls, M.Element)],
)
def test_missing_flag_key_imports_as_default(cls, flag):
    # back-compat: cached/exported JSON written before a flag existed (or by
    # older code that omitted it) must import with the dataclass default
    field = next(f for f in dataclasses.fields(cls) if f.name == flag)
    data = to_dict(cls())
    data.pop(flag, None)
    clone = from_dict(data)
    assert getattr(clone, flag) is field.default


FLAG_SOURCE = """
package Flags {
    abstract part def A;
    variation part def V { variant part v1; }
    individual part def I;
    state def S parallel { state a; state b; }
    part p : A {
        constant attribute k : Real = 1.0;
        derived attribute d : Real = 2.0;
    }
    import all Flags::*;
}
"""


def test_flag_bearing_source_survives_cache_hit(tmp_path, monkeypatch):
    # end-to-end guard for the bug class: flags parsed from source must be
    # identical when the model comes back from the content-addressed cache
    monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "flags.sysml"
    source.write_text(FLAG_SOURCE, encoding="utf-8")
    parsed = longeron.load_file(source, cache=True)  # parses, stores entry
    cached = longeron.load_file(source, cache=True)  # cache hit
    assert to_dict(cached) == to_dict(parsed)
    pkg = cached.find("Flags")
    assert pkg.find("A").is_abstract is True
    assert pkg.find("V").is_variation is True
    assert pkg.find("V::v1").is_variant is True
    assert pkg.find("I").is_individual is True
    assert pkg.find("S").is_parallel is True
    assert pkg.find("p::k").is_readonly is True
    assert pkg.find("p::d").is_derived is True
    imports = [m for m in pkg.members if isinstance(m, M.Import)]
    assert imports and imports[0].is_import_all is True and imports[0].is_namespace is True
