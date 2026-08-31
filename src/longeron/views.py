"""Persist diagrams as SysML v2 views (and restore them).

Design: :doc:`docs/design/view-persistence.md <../design/view-persistence>`
-- the ratified two-tier scheme.  The **standard tier** writes a
``ViewUsage`` into the model itself: typed by the matching
``StandardViewDefinitions`` view definition, exposing the shown elements
through ``expose`` relationships, and naming the spec rendering with a
``render`` reference.  That tier travels through ``.sysml`` text, the
Systems Modeling API, and every conformant tool.  The **sidecar tier** is
a small versioned JSON file (``.longeron/views.json`` next to the model
sources) carrying only what the standard cannot express: layout
direction, edge routing, collapse state, and the longeron diagram kind --
keyed by the view usage's *qualified name*, so a model without the
sidecar still restores correctly with default presentation.

::

    import longeron
    from longeron import views

    model = longeron.load("rig.sysml")
    widget = longeron.diagrams.structure_diagram(model.find("Rig"))
    views.save_view(model, widget, name="axle structure",
                    sidecar=views.sidecar_path(model))
    # ... later, or in another tool entirely ...
    views.restore_view(model, "Rig::axle structure")

Geometry is deliberately persisted nowhere: ELK re-derives layout from
the persisted *inputs* (exposed elements, direction, routing), so a
saved view never rots into stale pixel coordinates.

Restore resolves the expose closure through the resolver
(:func:`expose_closure` is the exact machinery, exposed for reuse):
membership exposes yield the named element (plus its subtree when
recursive), namespace exposes yield the target's members, and filter
conditions restrict the closure.  Metaclass filters (``@SysML::PartUsage``,
the dominant spec idiom) evaluate against longeron's kind vocabulary;
arbitrary model-level filter expressions are preserved and exported but
not applied to the closure (the design doc's scope fence).  A dangling
expose warns and is skipped -- never an exception -- and the same
condition surfaces in :func:`longeron.validate` as the ``dangling-expose``
diagnostic.

Saving is append-only and idempotent: a new view usage is *appended* to
the scope's owning package (keeping index-path element ids stable), and
saving under an existing view name replaces that view usage's recipe
(exposes, filters, render) and its sidecar entry in place.
"""

from __future__ import annotations

import json
import uuid
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast, get_args

from . import ast as A
from . import model as M
from .ecore import _DEF_CLASSES, _USAGE_CLASSES, _UUID_NAMESPACE
from .errors import ResolutionError, SysMLError
from .interpreter import Resolver

if TYPE_CHECKING:  # pragma: no cover - typing only (diagrams needs ipyelk)
    from .diagrams import CompartmentSection, NodeLevel
    from .toolbar import EdgeRouting, LayoutDirection

__all__ = [
    "SIDECAR_SCHEMA",
    "SIDECAR_VERSION",
    "VIEW_KINDS",
    "ViewInfo",
    "ViewKind",
    "capture_presentation",
    "expose_closure",
    "list_views",
    "load_sidecar",
    "restore_view",
    "save_sidecar",
    "save_view",
    "sidecar_path",
    "view_kind",
]

#: the longeron diagram kinds a view can persist (mirrors
#: ``explorer.DIAGRAM_KINDS``; asserted equal by the test suite)
ViewKind = Literal["structure", "state", "action", "requirements"]

#: the runtime table :data:`ViewKind` projects to (the model.py house
#: pattern: the Literal is the authority, so the two cannot drift)
VIEW_KINDS: tuple[ViewKind, ...] = get_args(ViewKind)

#: longeron diagram kind -> standard view definition (the typing that makes
#: a saved view legible to other tools; design doc mapping table)
VIEW_DEFINITIONS: dict[ViewKind, str] = {
    "structure": "StandardViewDefinitions::InterconnectionView",
    "state": "StandardViewDefinitions::StateTransitionView",
    "action": "StandardViewDefinitions::ActionFlowView",
    "requirements": "StandardViewDefinitions::GeneralView",
}

#: standard view definition (last name segment) -> longeron diagram kind
_KIND_BY_DEFINITION = {
    definition.rsplit("::", 1)[-1]: kind for kind, definition in VIEW_DEFINITIONS.items()
}

#: the rendering reference every longeron diagram kind writes (all four
#: kinds are interconnection-style diagrams; spec 9.2.19)
VIEW_RENDERING = "Views::asInterconnectionDiagram"

#: rendering-reference (last segment) -> diagram kind, for untyped views:
#: ``asInterconnectionDiagram`` is shared by all four longeron kinds, so it
#: cannot answer alone (``None`` falls through to the sidecar kind); the
#: tree/table/textual renderings restore through the structure fallback
#: with a warning (design doc scope fence)
_KIND_BY_RENDERING: dict[str, ViewKind | None] = {
    "asInterconnectionDiagram": None,
    "asTreeDiagram": "structure",
    "asElementTable": "structure",
    "asTextualNotation": "structure",
}

SIDECAR_SCHEMA = "longeron/views"
SIDECAR_VERSION = 1

#: sidecar entry keys that are NOT diagram-builder kwargs
_PRESENTATION_KEYS = ("direction", "routing", "collapsed", "levels", "folded")

#: metaclass names longeron's kind vocabulary cannot state more precisely
#: (matched by element CLASS, not kind; deliberate small courtesy set)
_ABSTRACT_METACLASSES: dict[str, tuple[type, ...]] = {
    "Element": (M.Element,),
    "Namespace": (M.Namespace,),
    "Package": (M.Package,),
    "Definition": (M.Definition,),
    "Classifier": (M.Definition,),
    "Usage": (M.Usage,),
    "Feature": (M.Usage,),
}


# ---------------------------------------------------------------------------
# view discovery + metadata
# ---------------------------------------------------------------------------


@dataclass
class ViewInfo:
    """One view usage and its persistence-relevant metadata."""

    element: M.Usage
    qualified_name: str | None
    kind: str | None  #: longeron diagram kind from the typing (None = unknown)
    exposes: list[M.Expose] = field(default_factory=list)


def view_kind(view: M.Usage) -> ViewKind | None:
    """The longeron diagram kind stated by a view usage's typing.

    Matches the last segment of each declared type against the
    ``StandardViewDefinitions`` mapping table (``InterconnectionView`` ->
    ``structure``, ``StateTransitionView`` -> ``state``, ...); ``None``
    when the view is untyped or typed by an unknown view definition.
    """

    for type_name in view.types:
        kind = _KIND_BY_DEFINITION.get(type_name.rsplit("::", 1)[-1])
        if kind is not None:
            return kind
    return None


def list_views(model: M.Model) -> list[ViewInfo]:
    """Every view usage in ``model``, with kind and expose metadata.

    The exposed closure of a view is computed on demand by
    :func:`expose_closure` (it needs a resolver walk); this listing stays
    cheap and never warns.
    """

    out: list[ViewInfo] = []
    for element in model.iter_tree():
        if isinstance(element, M.Usage) and element.kind == "view":
            exposes = [member for member in element.members if isinstance(member, M.Expose)]
            out.append(
                ViewInfo(
                    element=element,
                    qualified_name=element.qualified_name,
                    kind=view_kind(element),
                    exposes=exposes,
                )
            )
    return out


# ---------------------------------------------------------------------------
# the expose closure (restore step 2; design doc "Restore flow")
# ---------------------------------------------------------------------------


def expose_closure(
    model: M.Model, view: M.Usage, *, resolver: Resolver | None = None
) -> list[M.Element]:
    """The elements a view usage exposes (its ``exposedElement`` set).

    Each ``expose`` resolves through the resolver: a membership expose
    yields the named element (plus its whole subtree when recursive,
    ``X::**``), a namespace expose yields the target's members (``X::*``;
    all nested members when recursive).  Filter conditions -- the
    expose's own bracket filters, the view's ``filter`` members, and
    conditions inherited from an in-model view definition -- restrict the
    closure; metaclass filters evaluate, anything else is preserved but
    not applied (module docstring).  A dangling expose warns and is
    skipped, never raises.  Order is expose order, then tree order;
    duplicates are dropped.
    """

    if resolver is None:
        resolver = Resolver(model)
    conditions = _view_conditions(view, resolver)
    closure: dict[int, M.Element] = {}
    for expose in (m for m in view.members if isinstance(m, M.Expose)):
        try:
            target = resolver.resolve(expose.target, view)
        except ResolutionError:
            warnings.warn(
                f"dangling expose in view {view.qualified_name or view.label!r}: "
                f"target {expose.target!r} does not resolve; skipping it",
                stacklevel=2,
            )
            continue
        if expose.is_namespace:
            members = target.children() if isinstance(target, M.Namespace) else []
            exposed = (
                [el for member in members for el in member.iter_tree()]
                if expose.is_recursive
                else list(members)
            )
        else:
            exposed = list(target.iter_tree()) if expose.is_recursive else [target]
        for element in exposed:
            if not _passes(element, conditions + expose.filters):
                continue
            closure.setdefault(id(element), element)
    return list(closure.values())


def _view_conditions(view: M.Usage, resolver: Resolver) -> list[A.Expr]:
    """The view's own filter conditions plus those inherited from an
    in-model view definition (a usage inherits its definition's filters;
    spec 7.26.2).  Library definitions carry no filters, so only in-model
    typings are walked."""

    conditions = [m.condition for m in view.members if isinstance(m, M.ElementFilter)]
    for type_name in view.types:
        try:
            definition = resolver.resolve(type_name, view)
        except ResolutionError:
            continue
        if isinstance(definition, M.Definition) and definition.kind == "view":
            conditions.extend(
                m.condition for m in definition.members if isinstance(m, M.ElementFilter)
            )
    return conditions


def _passes(element: M.Element, conditions: list[A.Expr]) -> bool:
    for condition in conditions:
        if _evaluate_condition(element, condition) is False:
            return False
    return True


def _evaluate_condition(element: M.Element, expr: A.Expr) -> bool | None:
    """Evaluate a filter condition against one element.

    ``None`` means "cannot evaluate" (the element then stays in the
    closure -- an unapplied filter must not silently empty a view).
    Handled forms: metaclass tests (``@X``/``istype``/``hastype`` with the
    metaclass named by its spec name), ``not``, ``and``, ``or``.
    """

    if isinstance(expr, A.Unary) and expr.op == "not":
        inner = _evaluate_condition(element, expr.operand)
        return None if inner is None else not inner
    if isinstance(expr, A.Binary) and expr.op in ("and", "or", "&", "|"):
        left = _evaluate_condition(element, expr.left)
        right = _evaluate_condition(element, expr.right)
        if left is None or right is None:
            return None
        return (left and right) if expr.op in ("and", "&") else (left or right)
    if (
        isinstance(expr, A.Classification)
        and expr.operand is None
        and expr.op in ("@", "istype", "hastype")
    ):
        return _matches_metaclass(element, expr.type[-1])
    return None


def _matches_metaclass(element: M.Element, metaclass: str) -> bool:
    """Does ``element`` present as spec metaclass ``metaclass``?

    Evaluated against longeron's kind vocabulary through the same kind ->
    metaclass tables the API projection uses (``PartUsage`` matches a
    ``part`` usage, ``RequirementDefinition`` a ``requirement def``, ...),
    plus a small set of abstract supertypes.  Metaclass *hierarchy*
    conformance beyond that set is not modeled (scope fence)."""

    classes = _ABSTRACT_METACLASSES.get(metaclass)
    if classes is not None:
        return isinstance(element, classes)
    kind = getattr(element, "kind", None)
    if isinstance(element, M.Definition):
        return _DEF_CLASSES.get(str(kind)) == metaclass
    if isinstance(element, M.Usage):
        return _USAGE_CLASSES.get(str(kind)) == metaclass
    return False


# ---------------------------------------------------------------------------
# saving (design doc "Save flow", steps 1-2)
# ---------------------------------------------------------------------------


def save_view(
    model: M.Model,
    exposed: Any,
    *,
    name: str | None = None,
    kind: ViewKind | None = None,
    options: Mapping[str, Any] | None = None,
    sidecar: str | Path | None = None,
) -> M.Usage:
    """Write a diagram into ``model`` as a SysML v2 view usage.

    ``exposed`` names what the view shows: a longeron diagram widget (its
    root element, diagram kind, and non-default builder options are read
    off the widget -- including live toolbar direction/routing and
    collapse state), a model element, a qualified name, or a list of
    elements/names.  Each exposed element becomes one recursive
    membership expose (``expose X::**`` -- the element and its subtree).

    The view usage is typed by the matching ``StandardViewDefinitions``
    view definition and carries a ``render`` reference to
    ``Views::asInterconnectionDiagram`` (the design doc's mapping table);
    ``kind`` defaults to the widget's diagram kind, else it is inferred
    from the first exposed element (``state``/``action`` elements pick
    their machine views, everything else ``structure``).  ``name``
    defaults to ``"<element> <kind>"``.

    Append-only, idempotent semantics (ratified): a NEW view is appended
    to the scope's owning package -- appending keeps existing index-path
    element ids stable -- while saving under an existing view name
    REPLACES that view usage's recipe (typing, exposes, filters, render)
    in place.

    ``options`` seeds the sidecar entry: the presentation keys
    (``direction``, ``routing``, ``collapsed``) plus any diagram-builder
    kwargs (``membership``, ``submachine_depth``, ``lanes``, ...).  When
    ``sidecar`` is a path, the entry is written there under the view's
    qualified name (see :func:`save_sidecar`); with ``sidecar=None`` the
    model edit alone is performed and the caller owns any sidecar write.

    Returns the view usage element (freshly appended or replaced).
    """

    resolver = Resolver(model)
    elements, widget_kind, widget_options = _exposed_elements(model, exposed, resolver)
    if not elements:
        raise SysMLError("save_view needs at least one exposed element")
    for element in elements:
        qname = element.qualified_name
        if not qname or _resolve_or_none(resolver, qname) is not element:
            raise SysMLError(
                f"exposed element {element.label!r} is not addressable in this model "
                "(it needs a resolvable qualified name)"
            )
    kind = kind or cast("ViewKind | None", widget_kind) or _inferred_kind(elements[0])
    if kind not in VIEW_KINDS:
        choices = ", ".join(repr(k) for k in VIEW_KINDS)
        raise SysMLError(f"kind must be one of {choices}; not {kind!r}")
    if name is None:
        name = f"{elements[0].label} {kind}"

    owner = _owning_package(model, elements[0])
    view = _existing_view(owner, name)
    if view is None:
        view = M.Usage(kind="view", name=name)
        owner.add(view)  # APPEND, never insert (index-path id stability)
    else:  # replace the recipe in place -- save is idempotent
        view.members = [
            member
            for member in view.members
            if not isinstance(member, (M.Expose, M.ElementFilter))
            and not (isinstance(member, M.Usage) and member.kind == "render")
        ]
    view.types = [VIEW_DEFINITIONS[kind]]
    for element in elements:
        view.add(M.Expose(target=element.qualified_name or "", is_recursive=True))
    view.add(M.Usage(kind="render", subsets=[VIEW_RENDERING]))

    if sidecar is not None:
        merged = {**widget_options, **dict(options or {})}
        entries = load_sidecar(sidecar)
        entries[view.qualified_name or name] = _sidecar_entry(view, kind, merged)
        save_sidecar(sidecar, entries, model=model)
    return view


def _exposed_elements(
    model: M.Model, exposed: Any, resolver: Resolver
) -> tuple[list[M.Element], str | None, dict[str, Any]]:
    """Normalize ``save_view``'s ``exposed`` argument.

    Diagram widgets are duck-typed through the ``_lgn_view_state`` stamp
    (:func:`longeron.diagrams._stamp_view_state`): root element, diagram
    kind, and non-default builder options, merged with the widget's LIVE
    presentation (:func:`capture_presentation`)."""

    state = getattr(exposed, "_lgn_view_state", None)
    if state is not None:
        options = dict(state.get("options") or {})
        options.update(capture_presentation(exposed))
        return [state["element"]], state.get("kind"), options
    items = list(exposed) if isinstance(exposed, (list, tuple)) else [exposed]
    elements: list[M.Element] = []
    for item in items:
        if isinstance(item, M.Element):
            elements.append(item)
        elif isinstance(item, str):
            elements.append(resolver.resolve(item))
        else:
            raise SysMLError(
                "exposed must be a diagram widget, an element, a qualified "
                f"name, or a list of elements/names; not {type(item).__name__}"
            )
    return elements, None, {}


def _resolve_or_none(resolver: Resolver, qname: str) -> M.Element | None:
    try:
        return resolver.resolve(qname)
    except ResolutionError:
        return None


def _inferred_kind(element: M.Element) -> ViewKind:
    kind = getattr(element, "kind", None)
    if kind in ("state", "action"):
        return cast(ViewKind, str(kind))
    return "structure"


def _owning_package(model: M.Model, element: M.Element) -> M.Namespace:
    """Where a new view usage lands: the exposed scope itself when it is a
    package, else its nearest owning package, else the model root
    (ratified question 1: append to the owning file's package)."""

    node: M.Element | None = element
    while node is not None:
        if isinstance(node, (M.Package, M.Model)):
            return node
        node = node.owner
    return model


def _existing_view(owner: M.Namespace, name: str) -> M.Usage | None:
    for member in owner.members:
        if (
            isinstance(member, M.Usage)
            and member.kind == "view"
            and name
            in (
                member.name,
                member.short_name,
            )
        ):
            return member
    return None


def capture_presentation(widget: Any) -> dict[str, Any]:
    """The live presentation of a diagram widget, in sidecar vocabulary.

    Reads the CURRENT layout direction and edge routing off the widget's
    source tree (the toolbar tools re-apply their traits there, so live
    toggles are captured) and the collapse state: the structure view's
    per-node levels and per-compartment folds
    (:class:`longeron.diagrams.CollapseTool`) plus any nodes whose
    children are all hidden (the state/action widgets' stock collapse,
    the legacy ``collapsed`` key).  Only deviations from the defaults are
    returned -- absent sidecar keys mean defaults, so the file only grows
    when a user actually deviates from them.
    """

    out: dict[str, Any] = {}
    tree = getattr(getattr(widget, "source", None), "value", None)
    if tree is None:
        return out
    layout = tree.layoutOptions or {}
    direction = str(layout.get("elk.direction", "RIGHT")).lower()
    routing = str(layout.get("elk.edgeRouting", "ORTHOGONAL")).lower()
    if direction != "right":
        out["direction"] = direction
    if routing != "orthogonal":
        out["routing"] = routing
    # per-node collapse state: the structure view's CollapseTool traits
    # are authoritative (levels + per-compartment folds); the
    # hidden-children scan still covers the state/action widgets' stock
    # hidden collapse (the legacy 'collapsed' key)
    for tool in getattr(widget, "tools", ()):
        levels = getattr(tool, "levels", None)
        folds = getattr(tool, "folded", None)
        if isinstance(levels, dict) and isinstance(folds, dict):
            if levels:
                out["levels"] = {str(q): str(v) for q, v in sorted(levels.items())}
            if folds:
                out["folded"] = {
                    str(q): [str(s) for s in sections] for q, sections in sorted(folds.items())
                }
            break
    collapsed = sorted(
        str(node.id)
        for node in _walk_widget_nodes(tree)
        if node.id
        and not str(node.id).startswith("__lgn__:")
        and node.children
        and all(child.properties.hidden for child in node.children)
    )
    if collapsed:
        out["collapsed"] = collapsed
    return out


def _walk_widget_nodes(node: Any) -> Any:
    yield node
    for child in node.children:
        yield from _walk_widget_nodes(child)


def _index_path_id(element: M.Element) -> str | None:
    """The element's index-path UUID, exactly as the API projection
    derives it (``uuid5(ns, "$root/0/3/...")``; :mod:`longeron.ecore`).
    A cross-reference HINT only -- index paths shift when siblings are
    inserted, which is why the sidecar joins on qualified names."""

    indexes: list[int] = []
    node: M.Element = element
    while node.owner is not None:
        owner = node.owner
        if not isinstance(owner, M.Namespace):
            return None
        try:
            indexes.append(owner.members.index(node))
        except ValueError:
            return None
        node = owner
    if not isinstance(node, M.Model):
        return None
    path = "$root/" + "/".join(str(i) for i in reversed(indexes))
    return str(uuid.uuid5(_UUID_NAMESPACE, path))


def _sidecar_entry(view: M.Usage, kind: str, options: Mapping[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {}
    element_id = _index_path_id(view)
    if element_id is not None:
        entry["elementId"] = element_id
    entry["kind"] = kind
    remaining = dict(options)
    nested = remaining.pop("options", None)
    if isinstance(nested, Mapping):
        remaining = {**nested, **remaining}
    for key in _PRESENTATION_KEYS:
        if key in remaining:
            entry[key] = remaining.pop(key)
    if remaining:
        entry["options"] = remaining
    return entry


# ---------------------------------------------------------------------------
# the sidecar file (design doc "The sidecar")
# ---------------------------------------------------------------------------


def sidecar_path(source: M.Model | str | Path) -> Path | None:
    """The workspace sidecar location for a model or a source path.

    One JSON file per workspace, ``.longeron/views.json``, next to the
    ``.sysml`` sources: for a file that is ``<dir>/.longeron/views.json``
    beside it, for a directory it lives inside the directory.  A model
    resolves through its ``source_name``; models not loaded from disk
    (``loads`` text, merged multi-path models) return ``None``.
    """

    if isinstance(source, M.Model):
        source_name = source.source_name
        if not source_name:
            return None
        candidate = Path(source_name)
        if not candidate.exists():
            return None
        source = candidate
    path = Path(source)
    base = path if path.is_dir() else path.parent
    return base / ".longeron" / "views.json"


def load_sidecar(path: str | Path) -> dict[str, dict[str, Any]]:
    """Read a sidecar file; returns the per-view entries keyed by view
    qualified name (``{}`` when the file does not exist).

    Forward-compatible by contract: any ``version >= 1`` is accepted and
    unknown per-view keys are preserved (they ride through
    :func:`save_sidecar` untouched).  A file that is not a longeron views
    sidecar raises :class:`~longeron.errors.SysMLError` -- silently
    treating it as empty would overwrite foreign data on the next save.
    """

    file = _sidecar_file(path)
    if not file.exists():
        return {}
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        raise SysMLError(f"{file} is not valid JSON: {err}") from err
    if not isinstance(data, dict) or data.get("schema") != SIDECAR_SCHEMA:
        raise SysMLError(f"{file} is not a {SIDECAR_SCHEMA!r} sidecar")
    version = data.get("version")
    if not isinstance(version, int) or version < SIDECAR_VERSION:
        raise SysMLError(f"{file} has unsupported sidecar version {version!r}")
    views = data.get("views")
    return dict(views) if isinstance(views, dict) else {}


def save_sidecar(
    path: str | Path, views: Mapping[str, Mapping[str, Any]], *, model: M.Model | None = None
) -> Path:
    """Write the sidecar file (schema ``longeron/views``, version 1).

    Entries are written under sorted qualified-name keys with stable
    two-space indentation -- small, diffable, merge-friendly.  When
    ``model`` is given, entries whose qualified name no longer resolves
    in it are PRUNED (the design doc's orphan rule: a view deleted by
    another tool cannot wedge the sidecar).  Returns the file path.
    """

    file = _sidecar_file(path)
    kept: dict[str, Any] = {}
    for key in sorted(views):
        if model is not None and model.find(key) is None:
            continue  # pruned: the view no longer exists in the model
        kept[key] = dict(views[key])
    document = {"schema": SIDECAR_SCHEMA, "version": SIDECAR_VERSION, "views": kept}
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return file


def _sidecar_file(path: str | Path) -> Path:
    target = Path(path)
    if target.is_dir():
        return target / ".longeron" / "views.json"
    return target


# ---------------------------------------------------------------------------
# restoring (design doc "Restore flow")
# ---------------------------------------------------------------------------


def restore_view(
    model: M.Model,
    view: M.Usage | str,
    *,
    sidecar: str | Path | Mapping[str, Any] | None = None,
) -> Any:
    """Rebuild the diagram a view usage describes; returns the widget.

    Three steps, per the design doc: the view's typing picks the diagram
    builder (untyped views fall back to the ``render`` reference, then
    the sidecar ``kind``, then structure -- unknown view definitions warn
    and fall back), the expose closure yields the diagram scope
    (:func:`expose_closure`; dangling exposes warn and are skipped, a
    fully dangling view restores to an empty diagram), and the sidecar
    entry re-applies presentation: ``direction``, ``routing``, builder
    ``options``, and the collapse state (structure/requirements widgets
    rebuild per-node ``levels`` and per-compartment ``folded`` through
    ``structure_diagram(levels=..., folded=...)``; a legacy flat
    ``collapsed`` list maps to the smallest rendition, level
    ``"collapsed"``; state/action widgets keep the stock hidden-children
    collapse).  No sidecar entry means spec
    content with default presentation -- the degraded mode IS the
    standard mode.

    ``sidecar`` may be a path, an already-loaded entries mapping, or
    ``None`` to auto-discover the workspace sidecar next to the model's
    sources (silently absent for in-memory models).  Needs the diagram
    toolchain (the vendored ipyelk), like :mod:`longeron.diagrams`.
    """

    from . import diagrams

    resolver = Resolver(model)
    element = view if isinstance(view, M.Usage) else _find_view(model, view, resolver)
    entry = _sidecar_entry_for(model, element, sidecar)
    kind = _restore_kind(element, entry, resolver)
    closure = expose_closure(model, element, resolver=resolver)
    tops = _closure_tops(closure)
    if not tops:
        warnings.warn(
            f"view {element.qualified_name or element.label!r} exposes nothing "
            "that resolves; restoring an empty diagram",
            stacklevel=2,
        )

    # the sidecar is data from disk: the casts state the trust boundary
    # (illegal values keep failing loudly in apply_direction/apply_routing,
    # exactly as before)
    direction = cast("LayoutDirection", str(entry.get("direction", "right")))
    routing = cast("EdgeRouting", str(entry.get("routing", "orthogonal")))
    collapsed = tuple(str(name) for name in entry.get("collapsed") or ())
    # per-node collapse levels (stale sidecars are TOLERATED: unknown
    # level values are dropped, unknown qnames draw nothing); the legacy
    # flat 'collapsed' list maps to the smallest rendition
    levels_entry = entry.get("levels")
    levels: dict[str | M.Element, NodeLevel] = (
        {
            str(qname): cast("NodeLevel", str(value))
            for qname, value in levels_entry.items()
            if str(value) in ("partial", "collapsed")
        }
        if isinstance(levels_entry, Mapping)
        else {}
    )
    for name in collapsed:
        levels.setdefault(name, "collapsed")
    folded_entry = entry.get("folded")
    folded: dict[str, tuple[CompartmentSection, ...]] = (
        {
            str(qname): tuple(cast("CompartmentSection", str(section)) for section in sections)
            for qname, sections in folded_entry.items()
        }
        if isinstance(folded_entry, Mapping)
        else {}
    )
    options = entry.get("options")
    options = dict(options) if isinstance(options, Mapping) else {}

    if kind in ("state", "action"):
        machine = next(
            (el for el in tops if isinstance(el, (M.Definition, M.Usage)) and el.kind == kind),
            None,
        )
        if machine is None:
            warnings.warn(
                f"view {element.label!r} is a {kind} view but exposes no {kind} "
                "element; falling back to the structure view",
                stacklevel=2,
            )
            kind = "structure"
        else:
            builder = diagrams.state_diagram if kind == "state" else diagrams.action_diagram
            widget = builder(
                machine,
                direction=direction,
                routing=routing,
                **_known_options(builder, options),
            )
            _apply_collapsed(widget, collapsed)
            return widget

    scope = _structure_scope(element, tops)
    if kind == "requirements":
        from .widgets.explorer import requirements_view

        widget = requirements_view(
            scope,  # type: ignore[arg-type]
            resolver=resolver,
            direction=direction,
            routing=routing,
            levels=levels,
            folded=folded,
            **_known_options(diagrams.structure_diagram, options),
        )
    else:
        widget = diagrams.structure_diagram(
            scope,  # type: ignore[arg-type]
            direction=direction,
            routing=routing,
            levels=levels,
            folded=folded,
            **_known_options(diagrams.structure_diagram, options),
        )
    return widget


def _find_view(model: M.Model, qname: str, resolver: Resolver) -> M.Usage:
    found: M.Element | None = model.find(qname)
    if found is None:
        found = _resolve_or_none(resolver, qname)
    if not (isinstance(found, M.Usage) and found.kind == "view"):
        raise SysMLError(f"{qname!r} is not a view usage in this model")
    return found


def _sidecar_entry_for(
    model: M.Model,
    view: M.Usage,
    sidecar: str | Path | Mapping[str, Any] | None,
) -> dict[str, Any]:
    if sidecar is None:
        path = sidecar_path(model)
        entries: Mapping[str, Any] = load_sidecar(path) if path is not None else {}
    elif isinstance(sidecar, Mapping):
        views = sidecar.get("views") if sidecar.get("schema") == SIDECAR_SCHEMA else sidecar
        entries = views if isinstance(views, Mapping) else {}
    else:
        entries = load_sidecar(sidecar)
    entry = entries.get(view.qualified_name or "")
    return dict(entry) if isinstance(entry, Mapping) else {}


def _restore_kind(view: M.Usage, entry: Mapping[str, Any], resolver: Resolver) -> ViewKind:
    kind = view_kind(view)
    if kind is not None:
        return kind
    if view.types:
        warnings.warn(
            f"view {view.label!r} is typed by an unknown view definition "
            f"({view.types[0]!r}); falling back to the structure view",
            stacklevel=3,
        )
    for member in view.members:
        if isinstance(member, M.Usage) and member.kind == "render" and member.subsets:
            rendering = member.subsets[0].rsplit("::", 1)[-1]
            mapped = _KIND_BY_RENDERING.get(rendering, "structure")
            if mapped is not None:
                if rendering != "asInterconnectionDiagram":
                    warnings.warn(
                        f"view {view.label!r} renders {rendering}; longeron has no "
                        "such renderer -- restoring through the structure view",
                        stacklevel=3,
                    )
                return mapped
    sidecar_kind = entry.get("kind")
    if sidecar_kind in VIEW_KINDS:
        return cast("ViewKind", str(sidecar_kind))
    return "structure"


def _closure_tops(closure: list[M.Element]) -> list[M.Element]:
    """The closure elements without a closure ancestor (the drawn roots;
    everything else is presented nested inside them)."""

    ids = {id(el) for el in closure}
    tops = []
    for element in closure:
        node = element.owner
        while node is not None and id(node) not in ids:
            node = node.owner
        if node is None:
            tops.append(element)
    return tops


def _structure_scope(view: M.Usage, tops: list[M.Element]) -> M.Element:
    """What the structure builder runs over: the single exposed namespace
    itself (the saved-diagram common case, ``expose Pkg::**``), or -- for
    multi-expose and filtered closures -- a synthetic package listing the
    top elements WITHOUT re-parenting them, the
    :func:`longeron.widgets.explorer.requirements_view` projection idiom (owner
    chains, and therefore diagram node ids, stay those of the real
    model)."""

    if len(tops) == 1 and isinstance(tops[0], M.Namespace):
        return tops[0]
    package = M.Package(name=view.name or view.label)
    package.members = list(tops)  # deliberately NOT add(): no re-parenting
    root = M.Model(source_name=f"view {view.label}")
    root.add(package)
    return root


def _known_options(builder: Any, options: dict[str, Any]) -> dict[str, Any]:
    """The sidecar options a builder understands; unknown keys warn and
    are dropped (forward compatibility: a future longeron may have
    written kwargs this one does not know)."""

    import inspect

    parameters = inspect.signature(builder).parameters
    known = {key: value for key, value in options.items() if key in parameters}
    dropped = sorted(set(options) - set(known))
    if dropped:
        warnings.warn(
            f"ignoring unknown sidecar option(s) {', '.join(map(repr, dropped))}",
            stacklevel=4,
        )
    return known


def _apply_collapsed(widget: Any, collapsed: Any) -> None:
    """Re-apply the sidecar's collapse state on a STATE/ACTION widget:
    hide the children of every named node (exactly what ipyelk's stock
    ToggleCollapsedTool toggles).  Structure/requirements widgets never
    come here -- their collapsed set rides the builder's ``collapsed=``
    (rows for rowable nodes, hidden children for the rest)."""

    if not collapsed:
        return
    wanted = {str(item) for item in collapsed}
    tree = getattr(getattr(widget, "source", None), "value", None)
    if tree is None:
        return
    for node in _walk_widget_nodes(tree):
        if node.id and str(node.id) in wanted:
            for child in node.children:
                child.properties.hidden = True
