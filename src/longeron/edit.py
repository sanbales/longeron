"""Model editing: small mutations with round-trip guarantees.

This is the seam UI inspectors mutate a model through: each operation
takes the model plus an element (or its ``::``-qualified name), validates
its input precisely, applies the smallest possible change, and leaves the
model in a state that still exports to parseable text
(:func:`longeron.to_sysml`), still resolves, and still validates.  No
operation inserts or removes siblings of existing elements (``set_doc``
appends or edits in place), so index-path element ids -- the
:mod:`longeron.ecore` projection ids derived from member positions --
stay stable across edits.

The operations::

    import longeron
    from longeron import edit

    model = longeron.loads("package P { part def Vehicle; part v : Vehicle; }")
    tracker = edit.track(model)
    edit.rename(model, "P::Vehicle", "Car")     # cascades into 'v : Car'
    edit.set_doc(model, "P::v", "The prototype.")
    tracker.dirty                                # True
    tracker.changes                              # [(op, qname, detail), ...]

**The honest-refusal rename philosophy.**  Renaming an element changes
the qualified names of its whole subtree, and every *textual reference*
in the model that reaches the element -- or its descendants -- through
the old name must be rewritten with it: typings, subsets, redefines,
connector ends, satisfy targets, exposes, imports, aliases, dependency
ends, metadata prefixes, and the name references inside owned
expressions.  :func:`rename` resolves every reference site through the
same machinery :func:`longeron.validate` uses, rewrites exactly the
segments that resolve to the renamed element, and then *re-resolves every
site* to prove that nothing changed meaning.  Whatever cannot be proven
safe is refused: references in positions that cannot be statically
resolved (member access on a computed value, e.g. ``seq#(1).mass``) raise
:class:`~longeron.errors.EditError` listing the offending sites, and a
rename that would silently re-bind *any* reference (name capture through
shadowing) is rolled back and refused.  A rename that silently breaks
references is worse than no rename.

**Value writes validate semantics, not just syntax.**
:func:`set_attribute_value` applies the same philosophy to units: a new
expression carrying a measurement reference that does not resolve
(``0.42 [SI::kgg]``), or whose dimension contradicts the attribute's
quantity typing (``0.42 [SI::s]`` on a ``MassValue``) or -- when the
typing pins nothing -- the current value's own unit (``0.42 [SI::s]``
replacing ``0.38 [SI::kg]``), is refused before anything mutates --
through the very machinery ``validate``'s dimensional lint uses, so the
edit seam and the lint share one truth.  The *compact* quantity form the
inspector displays commits too: ``17 g`` (or ``17g``) resolves the
symbol through the same derived unit table the display uses and is
rewritten to the canonical bracket expression (``17 [SI::g]``) for
storage; a symbol the model never names but that decomposes through the
model's own prefix vocabulary (``17 mg``) rescales into the prefix's
reference unit (``0.017 [SI::g]``) -- model-derived, never invented --
and an ambiguous or unknown symbol is refused, never guessed.
``validate=False`` is the documented escape hatch for deliberate
unchecked writes (including deliberate re-dimensioning).

Known blind spots, matching ``validate``'s own: metadata *value* bodies
(``level = 3;`` inside ``@Safety``) resolve against the metadata
definition only one level deep, and references that reach an element
purely through an :class:`~longeron.model.Alias` are not rewritten when
the alias itself is renamed (the post-verification refuses such renames
rather than break them).

**Change tracking.**  :func:`track` registers a :class:`Tracker` in a
module-level :class:`weakref.WeakKeyDictionary` keyed by the model object
itself, so trackers die with their models and no wrapper type is needed.
Every ``edit.*`` operation that mutates a tracked model appends a
:class:`Change` record and fires the tracker's callbacks; ``dirty`` is
simply "there are recorded changes since the last :meth:`Tracker.mark_saved`".
"""

from __future__ import annotations

import dataclasses
import difflib
import re
import weakref
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any, NamedTuple

from . import ast as A
from . import model as M
from . import stdlib as stdlib_module
from .ast import expr_to_text
from .errors import EditError, ResolutionError, SysMLError
from .export import doc_comment_body
from .interpreter import Resolver
from .units import Dim, UnitInfo, UnitTable, unit_table

__all__ = [
    "Change",
    "EditError",
    "Tracker",
    "rename",
    "set_attribute_value",
    "set_doc",
    "track",
    "untrack",
]


# ---------------------------------------------------------------------------
# change tracking
# ---------------------------------------------------------------------------


class Change(NamedTuple):
    """One recorded edit: unpacks as ``(op, qname, detail)``."""

    op: str  #: "rename" | "set_value" | "set_doc"
    qname: str  #: qualified name of the edited element (after the edit)
    detail: dict[str, Any]  #: op-specific payload (old/new values, ...)


class Tracker:
    """Accumulates :class:`Change` records for one tracked model.

    ``dirty`` is derived: True whenever ``changes`` is non-empty.
    :meth:`mark_saved` clears both -- ``changes`` is defined as "the edits
    since the last save", which is exactly what an app needs to decide
    whether to prompt, and what to write into a commit message.
    Callbacks registered with :meth:`on_change` fire synchronously, once
    per change, after the change is appended; exceptions propagate to the
    caller of the edit operation.
    """

    def __init__(self) -> None:
        self.changes: list[Change] = []
        self._callbacks: list[Callable[[Change], None]] = []

    @property
    def dirty(self) -> bool:
        return bool(self.changes)

    def on_change(self, callback: Callable[[Change], None]) -> None:
        self._callbacks.append(callback)

    def mark_saved(self) -> None:
        self.changes.clear()

    def _record(self, change: Change) -> None:
        self.changes.append(change)
        for callback in list(self._callbacks):
            callback(change)


_TRACKERS: weakref.WeakKeyDictionary[M.Model, Tracker] = weakref.WeakKeyDictionary()


def track(model: M.Model) -> Tracker:
    """Start (or continue) tracking edits to ``model``; returns its tracker.

    Idempotent: repeated calls return the same :class:`Tracker`.  The
    registry holds the model weakly -- dropping the model drops the
    tracker.
    """

    tracker = _TRACKERS.get(model)
    if tracker is None:
        tracker = Tracker()
        _TRACKERS[model] = tracker
    return tracker


def untrack(model: M.Model) -> None:
    """Stop tracking ``model`` (a no-op when it was never tracked)."""

    _TRACKERS.pop(model, None)


def _record(model: M.Model, op: str, qname: str | None, detail: dict[str, Any]) -> None:
    tracker = _TRACKERS.get(model)
    if tracker is not None:
        tracker._record(Change(op, qname or "", detail))


def _top_indices(model: M.Model, *elements: M.Element | None) -> list[int]:
    """Positions in ``model.members`` of the top-level members owning
    ``elements`` -- the change-record breadcrumb (``detail["tops"]``)
    workspace save-back maps edits to source files with
    (:func:`longeron.export.save_workspace`).  Positions, not names:
    edit operations keep member positions stable (the module docstring's
    index-path guarantee) while later renames move names.  An element
    not under a top-level member (the model root itself) contributes
    nothing -- a save-back refuses such a change honestly.
    """

    found: list[int] = []
    for element in elements:
        node = element
        while node is not None and node.owner is not None and node.owner is not model:
            node = node.owner
        if node is None or node.owner is not model:
            continue
        for index, member in enumerate(model.members):
            if member is node:
                if index not in found:
                    found.append(index)
                break
    return sorted(found)


# ---------------------------------------------------------------------------
# shared plumbing
# ---------------------------------------------------------------------------


def _resolver(model: M.Model) -> Resolver:
    """A stdlib-aware resolver, exactly as ``validate`` builds one."""

    try:
        library: M.Model | None = stdlib_module.standard_library_model(cache=True)
    except Exception:
        library = None  # degrade to resolution without the library
    return Resolver(model, library=library)


def _target(model: M.Model, element_or_qname: M.Element | str, resolver: Resolver) -> M.Element:
    """Normalize an operation target to an element of ``model``."""

    if isinstance(element_or_qname, M.Element):
        element = element_or_qname
    else:
        try:
            element = resolver.resolve(element_or_qname)
        except ResolutionError as err:
            raise EditError(str(err)) from err
    node: M.Element = element
    while node.owner is not None:
        node = node.owner
    if node is not model:
        raise EditError(
            f"{element.qualified_name or element.label!r} is not part of this model "
            "(standard-library elements cannot be edited)"
        )
    return element


def _resolve_or_none(
    resolver: Resolver, qname: tuple[str, ...], context: M.Element | None
) -> M.Element | None:
    try:
        return resolver.resolve(qname, context)
    except ResolutionError:
        return None


# ---------------------------------------------------------------------------
# reference sites (the rename cascade's ground truth)
# ---------------------------------------------------------------------------

#: sentinel targets that are never model references
_SKIP_TARGETS = frozenset({"", M.ENTRY_SOURCE})


@dataclasses.dataclass
class _Site:
    """One textual reference: where it is stored and how it resolves.

    ``obj.attr`` (indexed by ``index`` for list fields) holds either a
    stored reference string (``"P::Vehicle"``, ``"engine.port"``, possibly
    ``"~"``-prefixed) or a qualified-name tuple on an expression node.
    ``context`` is the element the first segment resolves from -- the
    owner scope for stored strings (the ``validate`` idiom), the owning
    element itself for expression names (so a constraint's own parameters
    stay visible).  ``base`` carries a :class:`~longeron.ast.ChainAccess`
    base expression whose static resolution anchors the chain parts.
    ``lookthrough`` marks ``redefines`` strings, where a same-named
    redefinition shadows the redefined feature (``attribute mass :>>
    mass``) and resolution must look through to the inherited member.
    """

    element: M.Element
    context: M.Element | None
    obj: Any
    attr: str
    index: int | None
    role: str
    base: A.Expr | None = None
    lookthrough: bool = False

    def value(self) -> str | tuple[str, ...]:
        holder = getattr(self.obj, self.attr)
        out = holder[self.index] if self.index is not None else holder
        return out  # type: ignore[no-any-return]

    def assign(self, new: str | tuple[str, ...]) -> None:
        if self.index is None:
            setattr(self.obj, self.attr, new)
        else:
            getattr(self.obj, self.attr)[self.index] = new

    def describe(self) -> str:
        where = self.element.qualified_name or self.element.label
        value = self.value()
        text = "::".join(value) if isinstance(value, tuple) else value
        return f"{where} {self.role} {text!r}"


@dataclasses.dataclass
class _DynamicRef:
    """A name in a position that cannot be statically resolved."""

    element: M.Element
    parts: tuple[str, ...]
    role: str

    def describe(self) -> str:
        where = self.element.qualified_name or self.element.label
        return f"{where} {self.role} {'.'.join(self.parts)!r}"


def _chains_of(value: str | tuple[str, ...]) -> tuple[list[list[str]], str]:
    """Split a stored reference into dot-chains of ``::`` parts."""

    if isinstance(value, tuple):
        return [list(value)], ""
    prefix = ""
    text = value
    while text.startswith("~"):  # conjugated-port typings: ': ~PortDef'
        prefix += "~"
        text = text[1:]
    return [segment.split("::") for segment in text.split(".")], prefix


def _rejoin(chains: list[list[str]], prefix: str, as_tuple: bool) -> str | tuple[str, ...]:
    if as_tuple:
        return tuple(chains[0])
    return prefix + ".".join("::".join(parts) for parts in chains)


def _collect_sites(model: M.Model, resolver: Resolver) -> tuple[list[_Site], list[_DynamicRef]]:
    sites: list[_Site] = []
    dynamic: list[_DynamicRef] = []
    for element in model.iter_tree():
        scope = element.owner or model
        for obj, attr, index, role in _string_refs(element, resolver):
            holder = getattr(obj, attr)
            value = holder[index] if index is not None else holder
            if not value or value in _SKIP_TARGETS:
                continue
            context: M.Element | None = scope
            lookthrough = False
            if isinstance(element, M.MetadataValue):
                context = _metadata_context(element, resolver, model)
                if context is None:
                    continue  # not statically resolvable; validate skips it too
            if attr == "redefines":
                lookthrough = True
            sites.append(_Site(element, context, obj, attr, index, role, lookthrough=lookthrough))
        bound = _ambient_locals(element)
        for expr, role in _element_exprs(element):
            _walk_expr(expr, element, role, bound, sites, dynamic)
    return sites, dynamic


def _string_refs(
    element: M.Element, resolver: Resolver
) -> Iterator[tuple[Any, str, int | None, str]]:
    """Every stored-string reference field on ``element``: (obj, attr,
    index, role).  The vocabulary mirrors ``validate``'s reference checks
    plus the reference fields it leaves to other diagnostics (imports,
    exposes, state-machine targets, metadata prefixes, ...)."""

    for i in range(len(element.metadata)):
        yield element, "metadata", i, "metadata prefix"
    if isinstance(element, M.Definition):
        for i in range(len(element.supers)):
            yield element, "supers", i, "specializes"
    if isinstance(element, M.Usage):
        for i in range(len(element.types)):
            yield element, "types", i, "typed by"
        for i in range(len(element.subsets)):
            yield element, "subsets", i, "subsets"
        for i in range(len(element.redefines)):
            yield element, "redefines", i, "redefines"
        if element.references:
            yield element, "references", None, "references"
        if element.crosses:
            yield element, "crosses", None, "crosses"
    if isinstance(element, (M.ConnectionUsage, M.InterfaceUsage, M.AllocationUsage)):
        for end in element.ends:
            yield end, "target", None, "connects"
    if isinstance(element, M.BindingConnector):
        for bound_end in (element.source_end, element.target_end):
            if bound_end is not None:
                yield bound_end, "target", None, "binds"
    if isinstance(element, M.SatisfyUsage) and element.by:
        yield element, "by", None, "satisfied by"
    if isinstance(element, M.FlowUsage):
        if element.payload:
            yield element, "payload", None, "flow payload"
        if element.source:
            yield element, "source", None, "flow source"
        if element.target_end:
            yield element, "target_end", None, "flow target"
    if isinstance(element, (M.Import, M.Alias, M.Expose)):
        yield element, "target", None, type(element).__name__.lower()
    if isinstance(element, M.Dependency):
        for i in range(len(element.clients)):
            yield element, "clients", i, "dependency client"
        for i in range(len(element.suppliers)):
            yield element, "suppliers", i, "dependency supplier"
    if isinstance(element, M.Comment):
        for i in range(len(element.about)):
            yield element, "about", i, "comment about"
    if isinstance(element, M.MetadataUsage):
        if element.typed_by:
            yield element, "typed_by", None, "metadata typed by"
        for i in range(len(element.about)):
            yield element, "about", i, "metadata about"
    if isinstance(element, M.MetadataValue) and element.redefines:
        yield element, "redefines", None, "metadata value redefines"
    if isinstance(element, (M.AssignmentAction, M.InitialNode)):
        yield element, "target", None, "targets"
    if isinstance(element, M.PerformAction) and element.target:
        yield element, "target", None, "performs"
    if isinstance(element, M.Succession):
        if element.source:
            yield element, "source", None, "succession source"
        yield element, "target", None, "succession target"
    if isinstance(element, M.TransitionUsage):
        if element.source:
            yield element, "source", None, "transition source"
        yield element, "target", None, "transition target"
    if isinstance(element, M.AcceptAction):
        for i in range(len(element.payload_types)):
            yield element, "payload_types", i, "accepts"


def _metadata_context(
    value: M.MetadataValue, resolver: Resolver, model: M.Model
) -> M.Element | None:
    """The metadata definition a top-level metadata value redefines into."""

    owner = value.owner
    if not isinstance(owner, M.MetadataUsage) or not owner.typed_by:
        return None  # nested values (or detached ones) are out of static reach
    return _resolve_or_none(resolver, tuple(owner.typed_by.split("::")), owner.owner or model)


def _element_exprs(element: M.Element) -> Iterator[tuple[A.Expr, str]]:
    """Every owned expression of ``element`` (not of its children)."""

    if isinstance(element, M.Usage):
        if element.value is not None:
            yield element.value.expr, "value expression"
        if element.multiplicity is not None:
            yield from _mult_exprs(element.multiplicity)
    if isinstance(element, (M.Definition, M.Usage)) and element.result is not None:
        yield element.result, "result expression"
    if isinstance(element, (M.ConnectionUsage, M.InterfaceUsage, M.AllocationUsage)):
        for end in element.ends:
            if end.multiplicity is not None:
                yield from _mult_exprs(end.multiplicity)
    if isinstance(element, (M.Import, M.Expose)):
        for expr in element.filters:
            yield expr, "filter"
    if isinstance(element, M.ElementFilter):
        yield element.condition, "filter"
    if isinstance(element, M.MetadataValue) and element.value is not None:
        yield element.value.expr, "metadata value"
    if isinstance(element, M.AssignmentAction):
        yield element.expr, "assignment"
    if isinstance(element, M.IfAction):
        yield element.condition, "condition"
    if isinstance(element, M.WhileLoop):
        if element.condition is not None:
            yield element.condition, "condition"
        if element.until is not None:
            yield element.until, "until"
    if isinstance(element, M.ForLoop):
        yield element.seq, "loop sequence"
    if isinstance(element, M.SendAction):
        yield element.payload, "send payload"
        if element.via is not None:
            yield element.via, "send via"
        if element.to is not None:
            yield element.to, "send to"
    if isinstance(element, M.AcceptAction):
        if element.trigger is not None:
            yield element.trigger, "trigger"
        if element.via is not None:
            yield element.via, "accept via"
    if isinstance(element, M.TerminateAction) and element.target is not None:
        yield element.target, "terminates"
    if isinstance(element, (M.Succession, M.TransitionUsage)) and element.guard is not None:
        yield element.guard, "guard"


def _mult_exprs(mult: M.Multiplicity) -> Iterator[tuple[A.Expr, str]]:
    if mult.lower is not None:
        yield mult.lower, "multiplicity"
    if mult.upper is not None:
        yield mult.upper, "multiplicity"


def _ambient_locals(element: M.Element) -> frozenset[str]:
    """Names bound by the nearest definition/usage scope (loop variables,
    accept payload names) -- the ``validate`` idiom, so a loop variable
    that shadows a model element never triggers a false rewrite."""

    node: M.Element | None = element
    while node is not None and not isinstance(node, (M.Definition, M.Usage)):
        node = node.owner
    if node is None:
        return frozenset()
    names: set[str] = set()
    for item in node.iter_tree():
        if isinstance(item, M.ForLoop):
            names.add(item.var)
        elif isinstance(item, M.AcceptAction) and item.payload_name:
            names.add(item.payload_name)
        elif (
            isinstance(item, M.TransitionUsage)
            and item.trigger is not None
            and item.trigger.payload_name
        ):
            names.add(item.trigger.payload_name)
    return frozenset(names)


def _walk_expr(
    expr: A.Expr,
    element: M.Element,
    role: str,
    bound: frozenset[str],
    sites: list[_Site],
    dynamic: list[_DynamicRef],
) -> None:
    """Collect qualified-name sites (and dynamic names) from one expression."""

    if isinstance(expr, A.FeatureRef):
        if expr.parts and expr.parts[0] in bound:
            if len(expr.parts) > 1:  # members of a bound local: dynamic
                dynamic.append(_DynamicRef(element, expr.parts[1:], role))
        elif expr.parts:
            sites.append(_Site(element, element, expr, "parts", None, role))
        return
    if isinstance(expr, A.ChainAccess):
        _walk_expr(expr.base, element, role, bound, sites, dynamic)
        base = _static_base(expr.base, bound)
        if base is None:
            dynamic.append(_DynamicRef(element, expr.parts, role))
        else:
            sites.append(_Site(element, element, expr, "parts", None, role, base=base))
        return
    if isinstance(expr, (A.Classification, A.Cast, A.AllOf, A.Constructor)):
        sites.append(_Site(element, element, expr, "type", None, role))
    elif isinstance(expr, A.Invocation):
        sites.append(_Site(element, element, expr, "target", None, role))
    elif isinstance(expr, A.MetadataAccess):
        sites.append(_Site(element, element, expr, "target", None, role))
        return
    elif isinstance(expr, A.ArrowOp):
        # ArrowOp.name is the collection-operation vocabulary ('select',
        # 'size', ...), never a user-model reference -- deliberately not a
        # site.  The function-reference argument form ('->reduce MyAdd') is.
        if expr.func is not None:
            sites.append(_Site(element, element, expr, "func", None, role))
    elif isinstance(expr, A.BodyExpr):
        inner = bound | {p.name for p in expr.params} | {name for name, _ in expr.lets}
        for _, let_expr in expr.lets:
            _walk_expr(let_expr, element, role, inner, sites, dynamic)
        if expr.result is not None:
            _walk_expr(expr.result, element, role, inner, sites, dynamic)
        return
    # generic recursion into nested expressions
    for f in dataclasses.fields(expr):
        value = getattr(expr, f.name)
        if isinstance(value, A.Expr):
            _walk_expr(value, element, role, bound, sites, dynamic)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, A.Expr):
                    _walk_expr(item, element, role, bound, sites, dynamic)
                elif (
                    isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], A.Expr)
                ):  # (name, expr) pairs
                    _walk_expr(item[1], element, role, bound, sites, dynamic)


def _static_base(expr: A.Expr, bound: frozenset[str]) -> A.Expr | None:
    """The base expression of a chain, when it is statically resolvable."""

    if isinstance(expr, A.FeatureRef):
        return expr if (expr.parts and expr.parts[0] not in bound) else None
    if isinstance(expr, A.ChainAccess):
        return expr if _static_base(expr.base, bound) is not None else None
    return None


def _static_element(
    expr: A.Expr, context: M.Element | None, resolver: Resolver, model: M.Model
) -> M.Element | None:
    """Statically resolve a chain-base expression to a model element."""

    if isinstance(expr, A.FeatureRef):
        return _resolve_or_none(resolver, expr.parts, context)
    if isinstance(expr, A.ChainAccess):
        anchor = _static_element(expr.base, context, resolver, model)
        for part in expr.parts:
            if anchor is None:
                return None
            anchor = _resolve_or_none(resolver, (part,), anchor)
        return anchor
    return None


def _site_resolution(
    site: _Site, resolver: Resolver, model: M.Model
) -> list[list[M.Element | None]]:
    """Resolve a site part-by-part; one row of elements per dot-chain.

    Row entries align with the chain's name parts (``None`` from the
    first unresolvable part onward); comparing two resolutions of the
    same site is comparing element *identities*, which is exactly the
    rename post-verification.
    """

    chains, _ = _chains_of(site.value())
    rows: list[list[M.Element | None]] = []
    if site.base is not None:  # chain access on a statically-known base
        anchor = _static_element(site.base, site.context, resolver, model)
        row: list[M.Element | None] = []
        for part in chains[0]:
            anchor = _resolve_or_none(resolver, (part,), anchor) if anchor is not None else None
            row.append(anchor)
        return [row]
    prev: M.Element | None = None
    for ci, parts in enumerate(chains):
        context = site.context if ci == 0 else prev
        row = []
        start = 0
        if parts and parts[0] == "$":  # root-relative reference
            row.append(model)
            start = 1
        ok = context is not None or start > 0
        for i in range(start + 1, len(parts) + 1):
            found = _resolve_or_none(resolver, tuple(parts[:i]), context) if ok else None
            if found is None:
                ok = False
            elif (
                ci == 0
                and i == start + 1
                and site.lookthrough
                and found is site.element
                and len(parts) == start + 1
            ):
                # a same-named redefinition shadows the feature it
                # redefines; the reference means the inherited member
                found = _redefined_member(site.element, parts[i - 1], resolver, model)
            row.append(found)
        prev = row[-1] if row else None
        rows.append(row)
    return rows


def _redefined_member(
    element: M.Element, name: str, resolver: Resolver, model: M.Model
) -> M.Element:
    """The inherited member a self-shadowing ``redefines`` points at."""

    owner = element.owner
    if owner is None:
        return element
    general_names: list[str] = []
    if isinstance(owner, M.Definition):
        general_names = list(owner.supers)
    elif isinstance(owner, M.Usage):
        general_names = [t.lstrip("~") for t in owner.types] + list(owner.subsets)
    for general_name in general_names:
        general = _resolve_or_none(resolver, tuple(general_name.split("::")), owner.owner or model)
        if not isinstance(general, M.Namespace):
            continue
        for member in resolver.members_of(general, implied=True):
            if member is not element and name in (member.name, member.short_name):
                return member
    return element


# ---------------------------------------------------------------------------
# rename
# ---------------------------------------------------------------------------


def rename(model: M.Model, element_or_qname: M.Element | str, new_name: str) -> M.Element:
    """Rename an element, rewriting every textual reference that reaches it.

    Validates that ``new_name`` is a legal name (non-empty, no ``::`` or
    ``.`` separators, no ``$``, no control characters -- anything else
    exports through the quoted-name form) and that no sibling already
    answers to it.  Every reference site in the model is then resolved
    (with the same stdlib-aware machinery ``validate`` uses), the
    segments that resolve to the renamed element are rewritten, and the
    whole model is re-resolved to prove that every site still means what
    it meant before.  Names in positions that cannot be statically
    resolved (member access on computed values) are refused up front when
    they mention the old name, and any silent re-binding (name capture)
    is rolled back -- both raise :class:`~longeron.errors.EditError`
    listing the affected references.  See the module docstring for the
    philosophy.

    Renaming to the current name is a no-op.  Returns the element.
    """

    resolver = _resolver(model)
    target = _target(model, element_or_qname, resolver)
    if target is model:
        raise EditError("cannot rename the model root")
    _check_name(new_name)
    old_name = target.name
    if new_name == old_name:
        return target
    owner = target.owner
    if isinstance(owner, M.Namespace):
        for member in owner.members:
            if member is not target and new_name in (member.name, member.short_name):
                raise EditError(
                    f"name {new_name!r} is already used by another member of "
                    f"{owner.qualified_name or owner.label}"
                )
    old_qname = target.qualified_name

    sites, dynamic = _collect_sites(model, resolver)
    if old_name is not None:
        broken = [ref.describe() for ref in dynamic if old_name in ref.parts]
        if broken:
            raise EditError(
                f"rename would break {len(broken)} reference(s) that cannot be "
                "statically rewritten: " + "; ".join(broken)
            )
    snapshot: list[list[list[M.Element | None]]] = []
    plan: list[tuple[_Site, str | tuple[str, ...], str | tuple[str, ...]]] = []
    for site in sites:
        rows = _site_resolution(site, resolver, model)
        snapshot.append(rows)
        if old_name is None:
            continue
        value = site.value()
        chains, prefix = _chains_of(value)
        changed = False
        for ci, parts in enumerate(chains):
            offset = 1 if (ci == 0 and site.base is None and parts and parts[0] == "$") else 0
            for pi in range(offset, len(parts)):
                row = rows[ci]
                resolved = row[pi] if pi < len(row) else None
                if resolved is target and parts[pi] == old_name:
                    parts[pi] = new_name
                    changed = True
        if changed:
            plan.append((site, _rejoin(chains, prefix, isinstance(value, tuple)), value))

    # apply, then prove nothing changed meaning
    target.name = new_name
    for site, new_value, _ in plan:
        site.assign(new_value)
    post = Resolver(model, library=resolver.library)  # same library: identity-comparable
    mismatched = [
        site.describe()
        for site, rows in zip(sites, snapshot, strict=True)
        if _site_resolution(site, post, model) != rows
    ]
    if mismatched:
        target.name = old_name
        for site, _, old_value in plan:
            site.assign(old_value)
        raise EditError(
            f"rename would change what {len(mismatched)} reference(s) resolve to "
            "(name capture); refusing: " + "; ".join(mismatched)
        )
    _record(
        model,
        "rename",
        target.qualified_name,
        {
            "old_name": old_name,
            "new_name": new_name,
            "old_qname": old_qname,
            "new_qname": target.qualified_name,
            "rewritten": len(plan),
            # the renamed element's top-level member AND every top whose
            # references the cascade rewrote (renames cross file borders)
            "tops": _top_indices(model, target, *(site.element for site, _, _ in plan)),
        },
    )
    return target


def _check_name(new_name: str) -> None:
    if not isinstance(new_name, str) or not new_name:
        raise EditError("new name must be a non-empty string")
    if "::" in new_name or "." in new_name:
        raise EditError(f"{new_name!r} is not a legal name: '::' and '.' separate name segments")
    if new_name == "$":
        raise EditError("'$' is reserved for root-relative references")
    if any(ch in new_name for ch in "\n\r\t\x00"):
        raise EditError(f"{new_name!r} is not a legal name: control characters are not allowed")


# ---------------------------------------------------------------------------
# set_attribute_value
# ---------------------------------------------------------------------------


def set_attribute_value(
    model: M.Model,
    attr_or_qname: M.Usage | str,
    text: str | None,
    *,
    validate: bool = True,
) -> M.Usage:
    """Set (or clear) a usage's value from expression text.

    ``text`` is parsed with the package's expression parser
    (:func:`longeron.parse_expression`); a syntax error raises
    :class:`~longeron.errors.EditError` carrying the parse diagnostics.

    Semantics are validated *before* anything mutates (the module's
    honest-refusal philosophy, applied to values): every measurement
    reference the new expression carries must resolve against the
    model's unit vocabulary -- ``0.42 [SI::kgg]`` raises
    :class:`~longeron.errors.EditError` naming the fake unit and the
    nearest real spellings -- and when the usage's typing pins a
    quantity dimension (``payload : MassValue``) the new value's derived
    dimension must agree: ``0.42 [SI::s]`` on a mass-typed attribute is
    refused stating both dimensions, while ``0.42 [SI::g]`` is a real
    mass unit and passes.  When the typing pins nothing (``mass : Real``)
    but the CURRENT value carries a resolvable unit, that unit's
    dimension is the pin instead -- replacing a ``[SI::kg]`` value with a
    ``[SI::s]`` one is refused stating both dimensions and the
    ``validate=False`` override (a deliberate re-dimensioning is
    legitimate, a silent one is corruption).  A unit on a previously
    unit-less attribute is accepted as long as it resolves (adding units
    is legitimate), and a bare number always passes -- its dimension is
    unknown, exactly as ``validate`` treats it.  The model is untouched
    by any refusal, and refused attempts record nothing on the tracker.
    ``validate=False`` skips this semantic gate for deliberate unchecked
    writes (syntax is still required).

    The compact quantity form the inspector displays commits as well:
    ``17 g`` / ``17g`` -- a number, optional space, one unit symbol --
    resolves the symbol through the model's derived unit table (the very
    table the display reads) and stores the canonical bracket expression
    ``17 [SI::g]``; the dimension gates above apply to it unchanged.  A
    symbol the model does not name but that decomposes through the
    model's own prefix vocabulary (``17 mg``) is rescaled into the
    prefix's reference unit and stored as ``0.017 [SI::g]``.  An
    ambiguous decomposition is refused naming every candidate, and an
    unknown symbol is refused with the nearest real spellings.  The
    rewrite is form normalization, so it applies under ``validate=False``
    too.

    The existing value's ``default =`` / ``:=`` flags are preserved; a
    usage without a value gets a plain ``=`` binding.  ``None`` (or
    blank text) removes the value entirely.  Returns the usage.
    """

    resolver = _resolver(model)
    target = _target(model, attr_or_qname, resolver)
    if not isinstance(target, M.Usage):
        raise EditError(
            f"{target.qualified_name or target.label!r} is a "
            f"{type(target).__name__}, not a usage that can carry a value"
        )
    old = target.value
    if text is None or not text.strip():
        target.value = None
        _record(
            model,
            "set_value",
            target.qualified_name,
            {
                "text": None,
                "previous": expr_to_text(old.expr) if old else None,
                "tops": _top_indices(model, target),
            },
        )
        return target
    from .builder import parse_expression

    compact = _COMPACT_VALUE.fullmatch(text)
    rewritten = _compact_quantity(model, compact.group(1), compact.group(2)) if compact else None
    try:
        expr = parse_expression(rewritten if rewritten is not None else text)
    except SysMLError as err:
        if compact is not None:  # '17 xyz': a unit problem, not a syntax one
            raise EditError(_unknown_symbol_message(model, compact.group(2))) from err
        raise EditError(f"cannot parse {text!r} as an expression: {err}") from err
    if validate:
        _check_value_units(model, target, expr, resolver)
    target.value = M.FeatureValue(
        expr=expr,
        is_default=old.is_default if old else False,
        is_initial=old.is_initial if old else False,
    )
    _record(
        model,
        "set_value",
        target.qualified_name,
        {
            "text": expr_to_text(expr),
            "previous": expr_to_text(old.expr) if old else None,
            "tops": _top_indices(model, target),
        },
    )
    return target


#: the compact quantity form the inspector DISPLAYS ('17 g', '17g'):
#: a number, optional space, one symbol-shaped token (first char never
#: an operator or bracket, so '2 +' and '17 -3' stay ordinary
#: expressions).  A token that resolves to nothing falls through to the
#: ordinary expression parse before it is refused as an unknown unit.
_COMPACT_VALUE = re.compile(
    r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)[ \t]*"
    r"([^\s\d+\-*/^%<>=!&|(),.;:?@#\[\]{}'\"~\\`][^\s\[\]]*)\s*"
)


def _compact_quantity(model: M.Model, number: str, symbol: str) -> str | None:
    """The canonical bracket rewrite of a compact quantity, or ``None``.

    ``symbol`` resolves through the same derived table the inspector's
    display uses (:func:`longeron.units.unit_table` -- one truth): a
    named unit rewrites in place (``'17', 'g'`` -> ``'17 [SI::g]'``); a
    symbol the model never names but that decomposes through the model's
    own prefix vocabulary rescales into the prefix's reference unit
    (``'17', 'mg'`` -> ``'0.017 [SI::g]'`` via ``SIPrefixes::milli`` --
    model-derived, never invented).  An ambiguous decomposition raises
    :class:`~longeron.errors.EditError` naming every candidate; a symbol
    that resolves to nothing returns ``None`` (the caller falls back to
    the ordinary expression parse).
    """

    table = unit_table(model)
    info = table.lookup(symbol)
    if info is not None:
        return f"{number} [{_bracket_ref(info)}]"
    splits = table.prefix_splits(symbol)
    if len(splits) > 1:
        candidates = " or ".join(
            f"{key!r} + {base.label!r} ({_bracket_ref(base)})" for key, _, base in splits
        )
        raise EditError(
            f"unit {symbol!r} is ambiguous: {candidates}; "
            "spell the value with an explicit bracket unit"
        )
    if splits:
        _, factor, base = splits[0]
        magnitude = repr(float(Decimal(number) * Decimal(repr(factor))))
        return f"{magnitude} [{_bracket_ref(base)}]"
    return None


def _bracket_ref(info: UnitInfo) -> str:
    """The canonical bracket spelling of a table unit: the package
    prefix of its qualified name plus its display label (``SI::g``),
    quoted where the label needs it (``SI::'km/h'``)."""

    from .export import fmt_name, fmt_qname

    package, sep, last = info.qname.rpartition("::")
    label = info.symbol or info.name or last
    return (fmt_qname(package) + "::" if sep else "") + fmt_name(label)


def _unknown_symbol_message(model: M.Model, symbol: str) -> str:
    """The unknown-compact-symbol refusal, with did-you-mean hints."""

    table = unit_table(model)
    hint = _nearest_units(table, symbol)
    return f"unit {symbol!r} does not resolve" + (f" (did you mean {hint}?)" if hint else "")


def _check_value_units(model: M.Model, target: M.Usage, expr: A.Expr, resolver: Resolver) -> None:
    """The unit gate on value writes: refuse fakes and dimension conflicts.

    Deliberately reuses the dimensional lint's machinery
    (:mod:`longeron.validation`) so the edit seam and ``validate`` share
    one truth: measurement references resolve with the same stdlib-aware
    lookup behind ``unresolved-unit``, and the pinned dimension is the
    lint's own declared-meaning derivation -- the quantity typing first,
    the current value's resolved unit when the typing pins nothing.
    References that resolve
    but that the unit table cannot derive contribute no dimension --
    exactly ``validate``'s posture -- so a real-but-underivable unit is
    never refused.
    """

    from .validation import _Checker  # lazy: keep edit's import surface light

    checker = _Checker(model, library=resolver.library)
    scope = target.owner or model
    missing: list[str] = []
    for ref in _unit_refs(expr):
        name = "::".join(ref.parts)
        if name in missing:
            continue
        if _resolve_or_none(checker.resolver, ref.parts, scope) is None:
            missing.append(name)
    if missing:
        table = checker._units()
        raise EditError(
            "; ".join(
                f"unit {name!r} does not resolve"
                + (f" (did you mean {hint}?)" if (hint := _nearest_units(table, name)) else "")
                for name in missing
            )
        )
    meaning = checker._unit_meaning(target, expr, report=False)
    if meaning is None:
        return  # no unit fact in the new value (bare number): nothing to check
    pinned = checker._quantity_typing_meaning(target)
    if pinned is not None and len(pinned.dim.exp) == len(meaning.dim.exp):
        if meaning.dim != pinned.dim:
            table = checker._units()
            raise EditError(
                f"attribute {target.qualified_name or target.label!r} is "
                f"{_dim_label(table, pinned.dim)}-typed; "
                f"{meaning.display(table)} is {_dim_label(table, meaning.dim)}"
            )
        return
    if pinned is not None:
        return  # foreign basis: incomparable
    # typing pins nothing: the CURRENT value's resolved unit is the pin
    # (the maintainer's own scenario -- 'mass : Real = 0.38 [SI::kg]')
    if target.value is None:
        return
    previous = checker._unit_meaning(target, target.value.expr, report=False)
    if previous is None or len(previous.dim.exp) != len(meaning.dim.exp):
        return  # no resolvable unit fact on the old value, or a foreign basis
    if meaning.dim != previous.dim:
        table = checker._units()
        prev_unit = previous.label or previous.ident or table.format_dim(previous.dim)
        raise EditError(
            f"current value of {target.qualified_name or target.label!r} is "
            f"{prev_unit!r} [{_dim_label(table, previous.dim)}]; "
            f"{meaning.display(table)} is {_dim_label(table, meaning.dim)}; "
            "pass validate=False to override"
        )


def _unit_refs(expr: A.Expr, in_unit: bool = False) -> Iterator[A.FeatureRef]:
    """Every measurement reference in ``expr``: the name references inside
    the bracket annotations of its quantity nodes, at any depth (units
    compose, so an annotation may be ``SI::m / SI::s ** 2``)."""

    if isinstance(expr, A.QuantityOp):
        yield from _unit_refs(expr.base, in_unit)
        yield from _unit_refs(expr.unit, True)
        return
    if in_unit and isinstance(expr, A.FeatureRef):
        yield expr
        return
    for f in dataclasses.fields(expr):
        value = getattr(expr, f.name)
        if isinstance(value, A.Expr):
            yield from _unit_refs(value, in_unit)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, A.Expr):
                    yield from _unit_refs(item, in_unit)
                elif isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], A.Expr):
                    yield from _unit_refs(item[1], in_unit)  # (name, expr) pairs


def _nearest_units(table: UnitTable, name: str) -> str | None:
    """Up to two nearest real unit spellings, as a ``'SI::kg' or 'SI::g'``
    message fragment (``None`` when nothing is close)."""

    picks: list[str] = []
    for candidate in difflib.get_close_matches(name, list(table._by_key), n=6):
        info = table.lookup(candidate)
        if info is not None and not any(table.lookup(p) is info for p in picks):
            picks.append(candidate)
        if len(picks) == 2:
            break
    return " or ".join(repr(p) for p in picks) if picks else None


def _dim_label(table: UnitTable, dim: Dim) -> str:
    """A human dimension name (``mass``) from the table's quantity
    vocabulary (the bare lowercase-first keys are the quantity
    attributes: ``mass``, ``temperatureDifference``); the SI-base
    formula when no quantity names the dimension.  Shared by the
    refusal messages here and the inspector's unit row."""

    for key, quantity_dim in table._quantities.items():
        if "::" not in key and key[:1].islower() and quantity_dim == dim:
            return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key).lower()
    return table.format_dim(dim)


# ---------------------------------------------------------------------------
# set_doc
# ---------------------------------------------------------------------------


def set_doc(
    model: M.Model, element_or_qname: M.Element | str, text: str | None
) -> M.Documentation | None:
    """Create, update, or remove an element's documentation.

    With text: the element's first ``doc`` member is updated in place
    (keeping its member position, and collapsing any additional ``doc``
    members into it), or a new one is *appended* -- never inserted -- so
    existing siblings keep their index-path element ids.  With ``None``
    or an empty string: the ``doc`` members are removed (the one edit
    that shrinks a member list; siblings after the doc get new index
    paths).  Bodies are written in the canonical comment form
    (:func:`longeron.export.doc_comment_body`), which round-trips
    multi-line text through export/parse at a fixpoint.  Per the comment
    convention, leading ``*`` decoration and per-line indentation are not
    part of the text.  Returns the documentation element (``None`` after
    a removal).
    """

    resolver = _resolver(model)
    target = _target(model, element_or_qname, resolver)
    if not isinstance(target, M.Namespace):
        raise EditError(
            f"{target.qualified_name or target.label!r} is a "
            f"{type(target).__name__}; only namespaces carry documentation"
        )
    docs = [m for m in target.members if isinstance(m, M.Documentation)]
    previous = target.doc
    if text is None or text == "":
        for doc in docs:
            target.members.remove(doc)
        if docs:
            _record(
                model,
                "set_doc",
                target.qualified_name,
                {"text": None, "previous": previous, "tops": _top_indices(model, target)},
            )
        return None
    if "*/" in text:
        raise EditError("documentation text cannot contain '*/' (it terminates the comment)")
    body = doc_comment_body(text)
    if docs:
        doc = docs[0]
        doc.body = body
        for extra in docs[1:]:
            target.members.remove(extra)
    else:
        doc = M.Documentation(body=body)
        target.add(doc)  # APPEND, never insert (index-path id stability)
    _record(
        model,
        "set_doc",
        target.qualified_name,
        {"text": text, "previous": previous, "tops": _top_indices(model, target)},
    )
    return doc
