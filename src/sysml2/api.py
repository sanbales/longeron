"""OMG Systems Modeling API JSON interchange (Stage E prototype).

SysML v2 tools exchange models through the "Systems Modeling API &
Services" JSON: one flat record per element, ``@type`` naming the spec
metaclass, ``@id``/``elementId`` UUIDs, and every reference expressed as
``{"@id": ...}``.  This module rides on the :mod:`sysml2.ecore` projection
(so it inherits its scope and its ``pyecore`` requirement):

    records = sysml2.api.to_api_json(model)      # model -> API JSON
    spec = sysml2.api.from_api_json(records)     # API JSON -> spec instances

The export is a structural prototype: element skeletons, names, flags,
memberships, and specialization/typing relationships -- not expression
trees.  See :mod:`sysml2.ecore` for what is and is not projected.
"""

from __future__ import annotations

import json
from typing import Any

from . import model as M
from .ecore import SpecModel, spec_metamodel, to_spec
from .errors import SysMLError

#: structural features that never appear in API records
_SKIP_FEATURES = frozenset({"elementId"})


def to_api_records(model: M.Model | SpecModel) -> list[dict[str, Any]]:
    """Flat API-style records for a model (or an existing projection)."""

    spec = model if isinstance(model, SpecModel) else to_spec(model)
    records = []
    for obj in spec.all_instances():
        record: dict[str, Any] = {
            "@type": obj.eClass.name,
            "@id": obj.elementId,
            "elementId": obj.elementId,
        }
        for feature in obj.eClass.eAllStructuralFeatures():
            name = feature.name
            if feature.derived or feature.transient or \
                    name in _SKIP_FEATURES:
                continue
            value = obj.eGet(name)
            encoded = _encode(feature, value)
            if encoded is not None:
                record[name] = encoded
        records.append(record)
    return records


def _encode(feature: Any, value: Any) -> Any:
    is_reference = feature.eClass.name == "EReference"
    if feature.many:
        items = list(value)
        if not items:
            return None
        if is_reference:
            return [{"@id": item.elementId} for item in items]
        return [_scalar(item) for item in items]
    if value is None:
        return None
    if is_reference:
        return {"@id": value.elementId}
    if value == feature.get_default_value():
        return None  # omit defaults for compact records
    return _scalar(value)


def _scalar(value: Any) -> Any:
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)  # enum literals and other EDataTypes


def to_api_json(model: M.Model | SpecModel, indent: int = 2) -> str:
    return json.dumps(to_api_records(model), indent=indent)


def from_api_records(records: list[dict[str, Any]]) -> SpecModel:
    """Rebuild spec (pyecore) instances from API records."""

    from .ecore import SpecReport

    package = spec_metamodel()
    instances: dict[str, Any] = {}
    # pass 1: instantiate by @type
    for record in records:
        cls = package.getEClassifier(record["@type"])
        if cls is None or cls.abstract:
            raise SysMLError(f"unknown or abstract @type {record['@type']!r}")
        obj = cls()
        obj.elementId = record["@id"]
        instances[record["@id"]] = obj
    # pass 2: set attributes and wire references
    for record in records:
        obj = instances[record["@id"]]
        for name, value in record.items():
            if name.startswith("@") or name == "elementId":
                continue
            feature = obj.eClass.findEStructuralFeature(name)
            if feature is None or feature.derived:
                continue
            _apply(obj, feature, value, instances)
    roots = [obj for obj in instances.values() if obj.eContainer() is None]
    report = SpecReport(elements=len(instances))
    if len(roots) == 1:
        return SpecModel(roots[0], report)
    # wrap forests in a namespace so there is always a single root
    namespace = package.getEClassifier("Namespace")()
    membership_class = package.getEClassifier("OwningMembership")
    for root in roots:
        membership = membership_class()
        namespace.ownedRelationship.append(membership)
        membership.ownedRelatedElement.append(root)
    return SpecModel(namespace, report)


def _apply(obj: Any, feature: Any, value: Any,
           instances: dict[str, Any]) -> None:
    is_reference = feature.eClass.name == "EReference"
    if feature.many:
        target = obj.eGet(feature.name)
        for item in value:
            if is_reference:
                resolved = instances.get(item["@id"])
                if resolved is not None:
                    target.append(resolved)
            else:
                target.append(item)
        return
    if is_reference:
        resolved = instances.get(value["@id"])
        if resolved is not None:
            obj.eSet(feature.name, resolved)
        return
    enum_type = getattr(feature, "eType", None)
    if enum_type is not None and enum_type.eClass.name == "EEnum":
        literal = enum_type.getEEnumLiteral(str(value))
        if literal is not None:
            obj.eSet(feature.name, literal)
        return
    obj.eSet(feature.name, value)


def from_api_json(text: str) -> SpecModel:
    return from_api_records(json.loads(text))
