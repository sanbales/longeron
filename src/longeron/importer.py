"""Rebuild models from their JSON export (:func:`longeron.export.to_dict`).

The JSON produced by ``to_dict``/``to_json`` is lossless for the model layer:
``from_dict``/``from_json`` reconstruct the same element tree, so JSON is a
first-class interchange format alongside the textual notation::

    model = longeron.loads("package P { part def X; }")
    clone = longeron.from_json(longeron.to_json(model))
    assert longeron.to_dict(clone) == longeron.to_dict(model)
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from typing import Any

from . import model as M
from .ast import expr_from_dict
from .errors import BuildError

#: every dataclass in the model module, keyed by its ``@type`` name
_ELEMENT_TYPES: dict[str, type] = {
    name: obj for name, obj in vars(M).items() if isinstance(obj, type) and is_dataclass(obj)
}


def from_dict(data: dict[str, Any]) -> M.Element:
    """Reconstruct a model element from :func:`longeron.export.to_dict` data."""

    obj = _construct(data)
    if not isinstance(obj, M.Element):
        raise BuildError(f"{data.get('@type')!r} is not a model element")
    return obj


def _construct(data: dict[str, Any]) -> Any:
    if not isinstance(data, dict) or "@type" not in data:
        raise BuildError(f"not a serialized element (missing '@type'): {str(data)[:80]!r}")
    type_name = data["@type"]
    cls = _ELEMENT_TYPES.get(type_name)
    if cls is None:
        raise BuildError(f"unknown element type {type_name!r}")
    obj = cls()
    valid = {f.name for f in fields(cls)}
    for key, raw in data.items():
        if key.startswith("@") or key == "owner" or key not in valid:
            continue
        setattr(obj, key, _decode(raw))
    if isinstance(obj, M.Namespace):
        for member in obj.members:
            member.owner = obj
    return obj


def _decode(value: Any) -> Any:
    if isinstance(value, dict):
        if "@expr" in value:
            return expr_from_dict(value)
        if "@type" in value:
            return _construct(value)
        return value
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def from_json(text: str) -> M.Model:
    """Parse ``to_json`` output back into a model.

    A non-``Model`` root element (e.g. a serialized package) is wrapped in a
    fresh :class:`~longeron.model.Model` so the result is always executable.
    """

    element = from_dict(json.loads(text))
    if isinstance(element, M.Model):
        return element
    model = M.Model()
    model.add(element)
    return model
