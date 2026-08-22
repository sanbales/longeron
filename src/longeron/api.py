"""OMG Systems Modeling API JSON interchange (Stage E prototype).

SysML v2 tools exchange models through the "Systems Modeling API &
Services" JSON: one flat record per element, ``@type`` naming the spec
metaclass, ``@id``/``elementId`` UUIDs, and every reference expressed as
``{"@id": ...}``.  This module rides on the :mod:`longeron.ecore` projection
(so it inherits its scope and its ``pyecore`` requirement):

    records = longeron.api.to_api_json(model)           # model -> API JSON
    clone = longeron.api.model_from_api_json(records)   # API JSON -> Model (inverse)
    spec = longeron.api.spec_from_api_json(records)     # API JSON -> spec instances

The export is a structural prototype: element skeletons, names, flags,
memberships, and specialization/typing relationships -- not expression
trees.  See :mod:`longeron.ecore` for what is and is not projected.
Relationship records carry the derived ``source``/``target`` endpoint
arrays by default (``derived=True``), matching what the OMG pilot-
implementation API servers serialize -- see :func:`to_api_records`.
"""

from __future__ import annotations

import json
import uuid
from functools import cache
from typing import Any

from . import model as M
from .ecore import (
    _CONTROL_CLASSES,
    _DEF_CLASSES,
    _USAGE_CLASSES,
    _UUID_NAMESPACE,
    SpecModel,
    spec_class,
    spec_metamodel,
    to_spec,
)
from .errors import SysMLError
from .interpreter import Resolver

#: structural features that never appear in API records
_SKIP_FEATURES = frozenset({"elementId"})

#: the derived relationship endpoints (emitted via ``derived=True`` only)
_ENDPOINT_NAMES = ("source", "target")


def to_api_records(
    model: M.Model | SpecModel, *, implied: bool = False, derived: bool = True
) -> list[dict[str, Any]]:
    """Flat API-style records for a model (or an existing projection).

    With ``derived=True`` (the default), every relationship record also
    carries the spec-derived ``source`` and ``target`` endpoint arrays
    (``[{"@id": ...}, ...]``), computed from the relationship's role
    features: ``subclassifier``/``superclassifier`` for a
    Subclassification, ``typedFeature``/``type`` for a FeatureTyping,
    the owning namespace / owned member for memberships, and so on
    (the role-to-endpoint mapping is read from the ``redefines`` /
    ``subsets`` annotation chains in the vendored spec Ecore, not
    hard-coded).  The OMG pilot-implementation API servers always
    serialize these derived properties, and pilot-ecosystem consumers
    (e.g. pymbe) rely on them both to *recognize* relationship records
    and to navigate the model graph -- without them an export loads but
    is unnavigable.  Records whose endpoints are not derivable (an
    import whose target never resolved, a bare Dependency) simply omit
    the fields.  Pass ``derived=False`` for minimal records restricted
    to stored features.  Round-trips are lossless either way:
    :func:`spec_from_api_records` accepts records with or without the
    endpoint fields, and a re-export reproduces them.

    With ``implied=True`` (requires a :class:`~longeron.model.Model`), the
    implied standard-library specializations
    (``Resolver.implied_generals``: a plain ``part def`` specializes
    ``Parts::Part``, a plain ``part`` usage subsets ``Parts::parts``, ...)
    are emitted too, as additional ``Subclassification``/``Subsetting``
    records flagged ``"isImplied": true``.  Off by default: the extra
    records reference library elements that are not part of the export
    (their ``@id`` is a deterministic UUID of the library element's
    qualified name), which would break lossless round-trips.
    """

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
            if feature.derived or feature.transient or name in _SKIP_FEATURES:
                continue
            if name in _ENDPOINT_NAMES:
                continue  # emitted via the derived endpoint pass below
            value = obj.eGet(name)
            encoded = _encode(feature, value)
            if encoded is not None:
                record[name] = encoded
        if derived and _is_relationship_class(obj.eClass.name):
            record.update(_derived_endpoints(obj))
        records.append(record)
    if implied:
        if not isinstance(model, M.Model):
            raise SysMLError(
                "implied=True needs a longeron Model (an "
                "existing SpecModel no longer knows its "
                "source elements)"
            )
        records.extend(_implied_records(model, spec, derived=derived))
    return records


@cache
def _is_relationship_class(class_name: str) -> bool:
    cls = spec_class(class_name)
    return class_name == "Relationship" or any(
        c.name == "Relationship" for c in cls.eAllSuperTypes()
    )


def _redefined_endpoints(feature: Any) -> frozenset[str]:
    """Which of ``Relationship::source``/``target`` a role feature
    (transitively) redefines, walking the Ecore ``redefines`` chain
    (e.g. ``subclassifier`` -> ``specific`` -> ``source``)."""

    roots: set[str] = set()
    stack = [feature]
    seen: set[tuple[str, str]] = set()
    while stack:
        current = stack.pop()
        key = (current.eContainingClass.name, current.name)
        if key in seen:
            continue
        seen.add(key)
        if current.eContainingClass.name == "Relationship" and current.name in _ENDPOINT_NAMES:
            roots.add(current.name)
            continue
        for annotation in current.eAnnotations:
            if annotation.source == "redefines":
                stack.extend(annotation.references)
    return frozenset(roots)


@cache
def _endpoint_candidates(class_name: str) -> dict[str, tuple[str, ...]]:
    """Ordered stored-feature names that can supply each derived endpoint
    of a relationship metaclass.  Per endpoint: the stored role features
    that redefine it (most specific first), the endpoint feature itself
    (explicit values, e.g. on reimported records), then the stored
    containers subset by *derived* roles that redefine it
    (``membershipOwningNamespace`` is derived but subsets
    ``owningRelatedElement``, so a Membership's source falls back to its
    owning element; likewise ``ownedMemberElement`` ->
    ``ownedRelatedElement`` for the target)."""

    references = [
        f for f in spec_class(class_name).eAllStructuralFeatures() if f.eClass.name == "EReference"
    ]

    def specificity(feature: Any) -> int:
        return len(feature.eContainingClass.eAllSuperTypes())

    candidates: dict[str, tuple[str, ...]] = {}
    for endpoint in _ENDPOINT_NAMES:
        stored: list[Any] = []
        fallbacks: list[Any] = []
        for feature in references:
            if endpoint not in _redefined_endpoints(feature):
                continue
            if not feature.derived:
                stored.append(feature)
                continue
            for annotation in feature.eAnnotations:
                if annotation.source == "subsets":
                    fallbacks.extend(r for r in annotation.references if not r.derived)
        names = [f.name for f in sorted(stored, key=specificity, reverse=True)]
        names.append(endpoint)
        names.extend(f.name for f in sorted(fallbacks, key=specificity, reverse=True))
        deduped: list[str] = []
        for name in names:
            if name not in deduped:
                deduped.append(name)
        candidates[endpoint] = tuple(deduped)
    return candidates


def _derived_endpoints(obj: Any) -> dict[str, list[dict[str, str]]]:
    """``{"source": [{"@id": ...}], "target": [...]}`` for a relationship
    instance; underivable endpoints are omitted."""

    endpoints: dict[str, list[dict[str, str]]] = {}
    for endpoint, names in _endpoint_candidates(obj.eClass.name).items():
        for name in names:
            feature = obj.eClass.findEStructuralFeature(name)
            if feature is None:
                continue
            value = obj.eGet(name)
            items = list(value) if feature.many else [value] if value is not None else []
            if items:
                endpoints[endpoint] = [{"@id": item.elementId} for item in items]
                break
    return endpoints


def _implied_records(
    model: M.Model, spec: SpecModel, *, derived: bool = True
) -> list[dict[str, Any]]:
    """``isImplied`` Subclassification/Subsetting records (see
    :func:`to_api_records`).  Bases are resolved against the vendored
    standard library; unresolvable bases are skipped silently (mirroring
    ``Resolver.implied_generals``)."""

    from . import stdlib as stdlib_module

    try:
        library = stdlib_module.standard_library_model(cache=True)
    except Exception:
        library = None
    resolver = Resolver(model, library=library)
    instances = spec.instances or {}
    records: list[dict[str, Any]] = []
    for element in model.iter_tree():
        if not isinstance(element, (M.Definition, M.Usage)):
            continue
        instance = instances.get(id(element))
        if instance is None:
            continue  # element was not projected
        if isinstance(element, M.Definition):
            class_name = "Subclassification"
            source_role, target_role = "subclassifier", "superclassifier"
        else:
            class_name = "Subsetting"
            source_role, target_role = ("subsettingFeature", "subsettedFeature")
        for base in resolver.implied_generals(element):
            base_qname = base.qualified_name or base.label
            base_instance = instances.get(id(base))
            base_id = (
                base_instance.elementId
                if base_instance is not None
                else str(uuid.uuid5(_UUID_NAMESPACE, f"$library/{base_qname}"))
            )
            record_id = str(
                uuid.uuid5(
                    _UUID_NAMESPACE, f"{instance.elementId}#Implied{class_name}/{base_qname}"
                )
            )
            record: dict[str, Any] = {
                "@type": class_name,
                "@id": record_id,
                "elementId": record_id,
                "isImplied": True,
                source_role: {"@id": instance.elementId},
                target_role: {"@id": base_id},
            }
            if derived:
                record["source"] = [{"@id": instance.elementId}]
                record["target"] = [{"@id": base_id}]
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


def to_api_json(
    model: M.Model | SpecModel, indent: int = 2, *, implied: bool = False, derived: bool = True
) -> str:
    return json.dumps(to_api_records(model, implied=implied, derived=derived), indent=indent)


def spec_from_api_records(records: list[dict[str, Any]]) -> SpecModel:
    """Rebuild spec (pyecore) instances from API records.

    This is the *spec-level* import: the result mirrors the metamodel
    instances the records serialize.  It is **not** the inverse of
    :func:`to_api_records` -- for API records back to a
    :class:`longeron.model.Model`, use :func:`model_from_api_records`.
    """

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


def _apply(obj: Any, feature: Any, value: Any, instances: dict[str, Any]) -> None:
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


def spec_from_api_json(text: str) -> SpecModel:
    """Parse API JSON into spec (pyecore) instances (see
    :func:`spec_from_api_records`).  **Not** the inverse of
    :func:`to_api_json` -- that is :func:`model_from_api_json`."""

    return spec_from_api_records(json.loads(text))


#: back-compat aliases; prefer the explicit ``spec_from_api_*`` names (or
#: ``model_from_api_*`` for the model-layer inverse of ``to_api_*``)
from_api_records = spec_from_api_records
from_api_json = spec_from_api_json


# ---------------------------------------------------------------------------
# API records -> longeron model (reverse structural import)
# ---------------------------------------------------------------------------


def _invert_kinds(mapping: dict[str, str]) -> dict[str, str]:
    """Spec metaclass -> model kind; the *first* kind listed for a
    metaclass wins (``PartUsage`` -> ``part``, not ``actor``)."""

    inverse: dict[str, str] = {}
    for kind, class_name in mapping.items():
        inverse.setdefault(class_name, kind)
    return inverse


_DEF_KIND_BY_CLASS = _invert_kinds(_DEF_CLASSES)
_USAGE_KIND_BY_CLASS = _invert_kinds(_USAGE_CLASSES)
_CONTROL_KIND_BY_CLASS = {class_name: kind for kind, class_name in _CONTROL_CLASSES.items()}

#: API record boolean -> model dataclass field (both directions structural)
_FLAG_FIELDS = {
    "isAbstract": "is_abstract",
    "isVariation": "is_variation",
    "isIndividual": "is_individual",
    "isParallel": "is_parallel",
    "isEnd": "is_end",
    "isDerived": "is_derived",
    "isReadOnly": "is_readonly",
}

#: membership metaclass -> usage kind forced on the owned member
_MEMBERSHIP_USAGE_KINDS = {
    "SubjectMembership": "subject",
    "ActorMembership": "actor",
    "StakeholderMembership": "stakeholder",
    "ObjectiveMembership": "objective",
}

#: relationship metaclass -> (source role, target role, model list attribute)
_RELATIONSHIP_ROLES: dict[str, tuple[str, str, str]] = {
    "FeatureTyping": ("typedFeature", "type", "types"),
    "Subclassification": ("subclassifier", "superclassifier", "supers"),
    "Subsetting": ("subsettingFeature", "subsettedFeature", "subsets"),
    "Redefinition": ("redefiningFeature", "redefinedFeature", "redefines"),
}

_USAGE_SPECIAL_CLASSES: dict[str, type] = {
    "ConnectionUsage": M.ConnectionUsage,
    "BindingConnectorAsUsage": M.BindingConnector,
    "SatisfyRequirementUsage": M.SatisfyUsage,
}

_DIRECTIONS = ("in", "out", "inout")


def _flat_api_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize records to the flat GET form.  Accepts both flat records
    (``{"@id": ..., "@type": ...}``) and the pilot POST change form
    (``{"identity": {"@id": ...}, "payload": {...}}``); entries whose
    payload is ``null`` (deletions) are dropped."""

    flat = []
    for entry in records:
        identity = entry.get("identity")
        if isinstance(identity, dict):
            payload = entry.get("payload")
            if payload is None:
                continue
            record = dict(payload)
            record.setdefault("@id", identity["@id"])
            flat.append(record)
        else:
            flat.append(entry)
    return flat


def _first_id(record: dict[str, Any], *keys: str) -> str | None:
    """The first ``@id`` found under ``keys`` (single ref or ref array)."""

    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            return value.get("@id")
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value[0].get("@id")
    return None


def _all_ids(record: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        value = record.get(key)
        if isinstance(value, dict):
            return [value["@id"]]
        if isinstance(value, list) and value:
            return [ref["@id"] for ref in value if isinstance(ref, dict)]
    return []


def _element_from_api_record(record: dict[str, Any]) -> M.Element | None:
    """A detached model element for one API record, or ``None`` for record
    kinds the reverse import does not reconstruct (memberships and
    specialization/typing relationships are applied structurally; imports,
    dependencies, and behavioral statement records are skipped -- their
    API records carry no reconstructable payload)."""

    type_name = str(record.get("@type", ""))
    element: M.Element
    if type_name in ("Package", "LibraryPackage"):
        element = M.Package(
            is_library=type_name == "LibraryPackage",
            is_standard=bool(record.get("isStandard")),
        )
    elif type_name == "EnumerationDefinition":
        element = M.EnumerationDefinition()
    elif type_name in _DEF_KIND_BY_CLASS:
        element = M.Definition(kind=_DEF_KIND_BY_CLASS[type_name])  # type: ignore[arg-type]
    elif type_name in _USAGE_SPECIAL_CLASSES:
        element = _USAGE_SPECIAL_CLASSES[type_name]()
    elif type_name in _USAGE_KIND_BY_CLASS:
        element = M.Usage(kind=_USAGE_KIND_BY_CLASS[type_name])  # type: ignore[arg-type]
    elif type_name in ("Documentation", "Comment"):
        body = str(record.get("body", ""))
        if not body.lstrip().startswith("/*"):
            body = f"/* {body} */"
        element = (
            M.Documentation(body=body) if type_name == "Documentation" else M.Comment(body=body)
        )
    elif type_name == "TextualRepresentation":
        element = M.TextualRepresentation(
            language=str(record.get("language", "")), body=str(record.get("body", ""))
        )
    elif type_name in _CONTROL_KIND_BY_CLASS:
        element = M.ControlNode(kind=_CONTROL_KIND_BY_CLASS[type_name])  # type: ignore[arg-type]
    else:
        return None
    if record.get("declaredName") is not None:
        element.name = record["declaredName"]
    if record.get("declaredShortName") is not None:
        element.short_name = record["declaredShortName"]
    for record_field, model_field in _FLAG_FIELDS.items():
        if record.get(record_field) and hasattr(element, model_field):
            setattr(element, model_field, True)
    if isinstance(element, M.Usage) and record.get("direction") in _DIRECTIONS:
        element.direction = record["direction"]
    return element


def _apply_membership_kind(membership: dict[str, Any], child: M.Element) -> None:
    """Adjust an owned member for what its membership record implies."""

    type_name = str(membership.get("@type", ""))
    if not isinstance(child, M.Usage):
        return
    forced = _MEMBERSHIP_USAGE_KINDS.get(type_name)
    if forced is not None:
        child.kind = forced  # type: ignore[assignment]
    if type_name == "VariantMembership":
        child.is_variant = True
    if type_name == "ReturnParameterMembership":
        child.direction = "return"
    elif type_name == "ParameterMembership" and child.direction is None:
        # the exporter omits direction when it equals the spec default
        # ("in"); the membership kind still pins the member as a parameter
        child.direction = "in"


def _reference_name(target: M.Element) -> str | None:
    return target.qualified_name or target.name or target.short_name


def model_from_api_records(records: list[dict[str, Any]]) -> M.Model:
    """Rebuild a :class:`~longeron.model.Model` from flat API records.

    This is the reverse of :func:`to_api_records` at the same structural
    fidelity: element kinds, names, flags, ownership (via the reified
    membership records), and the FeatureTyping / Subclassification /
    Subsetting / Redefinition relationships come back; expression trees,
    attribute values, multiplicities, and import/dependency targets are
    not part of API records and are therefore absent from the result.
    Relationship endpoints are read from the stored role features when
    present and from the derived ``source``/``target`` arrays otherwise,
    so both longeron exports and pilot-server payloads import.  Records
    are accepted in flat GET form or pilot POST ``identity``/``payload``
    form; unknown ``@type`` values are skipped, never fatal.  Unlike
    :func:`spec_from_api_records` this needs no pyecore.
    """

    flat = _flat_api_records(records)
    by_id: dict[str, dict[str, Any]] = {r["@id"]: r for r in flat if "@id" in r}
    elements: dict[str, M.Element] = {}
    for record_id, record in by_id.items():
        element = _element_from_api_record(record)
        if element is not None:
            elements[record_id] = element
    # ownership: walk the reified membership records
    owned: set[str] = set()
    root_order: list[str] = []
    for record in flat:
        if not str(record.get("@type", "")).endswith("Membership"):
            continue
        parent_id = _first_id(record, "owningRelatedElement", "membershipOwningNamespace", "source")
        parent = elements.get(parent_id) if parent_id else None
        parent_record = by_id.get(parent_id) if parent_id else None
        parent_is_root = (
            parent is None
            and parent_record is not None
            and parent_record.get("@type") == "Namespace"
            and not parent_record.get("declaredName")
        )
        for child_id in _all_ids(record, "ownedRelatedElement", "target"):
            child = elements.get(child_id)
            if child is None or child_id in owned:
                continue
            if isinstance(parent, M.Namespace):
                parent.add(child)
                owned.add(child_id)
                if isinstance(parent, M.EnumerationDefinition) and (
                    isinstance(child, M.Usage) and child.kind == "enum"
                ):
                    child.kind = "enum_literal"
            elif parent_is_root:
                root_order.append(child_id)
            _apply_membership_kind(record, child)
    # relationships: typing / specialization back onto name lists
    for record in flat:
        roles = _RELATIONSHIP_ROLES.get(str(record.get("@type", "")))
        if roles is None or record.get("isImplied"):
            continue
        source_role, target_role, attribute = roles
        source_id = _first_id(record, source_role, "source")
        target_id = _first_id(record, target_role, "target")
        source = elements.get(source_id) if source_id else None
        target = elements.get(target_id) if target_id else None
        if source is None or target is None:
            continue
        name = _reference_name(target)
        names = getattr(source, attribute, None)
        if name and isinstance(names, list) and name not in names:
            names.append(name)
    model = M.Model()
    for root_id in root_order:
        if root_id not in owned:
            model.add(elements[root_id])
            owned.add(root_id)
    for record_id, element in elements.items():  # unowned leftovers stay roots
        if record_id not in owned and record_id not in root_order:
            model.add(element)
    return model


def model_from_api_json(text: str) -> M.Model:
    """Parse API JSON (see :func:`model_from_api_records`)."""

    return model_from_api_records(json.loads(text))
