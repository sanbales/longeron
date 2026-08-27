"""Model validation: dangling references, duplicate names, cycles.

``validate`` walks a model and returns :class:`Diagnostic` records.  Name
resolution is stdlib-aware: unless disabled (``stdlib=False``), references
resolve against the vendored standard library as a fallback, so
``ScalarValues::Real`` -- or a bare ``Real``, without any import --
validates silently while a misspelled ``Reall`` warns.  Implied
specializations are honored too: a plain ``action def`` implicitly
specializes ``Actions::Action``, so inherited names like ``start`` and
``done`` resolve in expressions.  Unresolved references are *warnings*;
structural problems (duplicate names, specialization cycles, transitions
to unknown states) are *errors*.

The dimensional lint (design: ``docs/design/units.md``) also lives here:
unit annotations must resolve (``unresolved-unit``), arithmetic over
attributes with known dimension vectors must agree (``dimension-mismatch``
-- the ``mass + flightTime`` bug the interpreter silently evaluates),
mixed measurement scales under ``+``/``-`` are an error
(``scale-mismatch``: ``dBW + W``, ``°C + K``), same-dimension operands in
different units warn without the ``[units]`` extra (``mixed-units``), and
scoreboard ramp/target anchors are checked against their requirement's
``measure`` (``anchor-dimension-mismatch``).  Dimensions come from
:mod:`longeron.units`, derived from the vendored library's own
definitional algebra; unknown dimensions are bottom and propagate
silently -- the lint only speaks when two *known* vectors conflict.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from . import ast as A
from . import model as M
from . import stdlib as stdlib_module
from . import units as units_module
from .errors import ResolutionError, SourceLocation
from .interpreter import BUILTINS, Resolver

Severity = Literal["error", "warning"]


@dataclass
class Diagnostic:
    severity: Severity
    code: str
    message: str
    element: str  # qualified name (or best-effort label) of the subject
    location: SourceLocation | None = None  # file:line:column, when parsed

    def __str__(self) -> str:
        prefix = f"{self.location}: " if self.location is not None else ""
        return f"{prefix}{self.severity}[{self.code}] {self.element}: {self.message}"


def validate(
    model: M.Model, *, stdlib: bool | None = None, strict_imports: bool = False
) -> list[Diagnostic]:
    """Validate a model; returns diagnostics sorted errors-first.

    ``stdlib`` controls the standard-library fallback used for name
    resolution: ``None`` (default) auto-attaches the vendored library when
    it loads, ``True`` forces it, ``False`` disables it.  The library is
    only consulted by the resolver -- ``model`` is never mutated.

    ``strict_imports`` additionally warns (``stdlib-implicit-name``) for
    bare standard-library names that resolve *only* through the implicit
    library-visibility hop -- the KerML global-namespace convenience for
    standard library packages.  Qualified names (``ScalarValues::Real``)
    and explicitly imported names stay silent.

    Elements inside ``library`` packages are never the subject of
    diagnostics: a merged-in standard library (e.g. via the CLI's
    ``--stdlib``) is resolution context, not the model under validation.
    """

    library: M.Model | None = None
    if stdlib is None:
        try:
            library = stdlib_module.standard_library_model(cache=True)
        except Exception:
            library = None  # degrade to resolution without the library
    elif stdlib:
        library = stdlib_module.standard_library_model(cache=True)
    checker = _Checker(model, library=library, strict_imports=strict_imports)
    checker.check_all()
    order = {"error": 0, "warning": 1}
    return sorted(checker.diagnostics, key=lambda d: (order[d.severity], d.element, d.code))


class _Checker:
    def __init__(
        self, model: M.Model, library: M.Model | None = None, strict_imports: bool = False
    ):
        self.model = model
        self.resolver = Resolver(model, library=library)
        self.strict_imports = strict_imports
        self._used_implicit = False  # set by _resolves, read right after
        self.diagnostics: list[Diagnostic] = []
        self._unit_table: units_module.UnitTable | None = None
        self._meanings: dict[int, _Meaning | None] = {}  # id(usage) -> declared meaning

    def report(self, severity: Severity, code: str, element: M.Element, message: str) -> None:
        where = element.qualified_name or element.label
        location = getattr(element, "source_location", None)
        self.diagnostics.append(Diagnostic(severity, code, message, where, location))

    # -- driver ---------------------------------------------------------------

    def check_all(self) -> None:
        self._check_tree(self.model)

    def _check_tree(self, element: M.Element) -> None:
        if isinstance(element, M.Package) and (element.is_library or element.is_standard):
            return  # library packages are resolution context, not subjects
        if isinstance(element, M.Namespace):
            self.check_duplicate_names(element)
        if isinstance(element, (M.Definition, M.Usage)):
            self.check_references(element)
            self.check_specialization_cycle(element)
            self.check_expressions(element)
            self.check_units(element)
            self.check_scoreboard_anchors(element)
        if isinstance(element, M.Import):
            self.check_target(element, element.target, "import")
        if isinstance(element, M.Expose):
            self.check_expose(element)
        if isinstance(element, M.Alias):
            self.check_target(element, element.target, "alias")
        if isinstance(element, M.Dependency):
            for ref in element.clients + element.suppliers:
                self.check_target(element, ref, "dependency")
        if isinstance(element, (M.Definition, M.Usage)) and element.kind == "state":
            self.check_state_machine(element)
        if isinstance(element, M.Usage) and element.kind == "calc":
            self.check_calc_result(element)
        if isinstance(element, M.Definition) and element.kind == "calc":
            self.check_calc_result(element)
        for child in element.children():
            self._check_tree(child)

    # -- checks ------------------------------------------------------------------

    def check_duplicate_names(self, ns: M.Namespace) -> None:
        seen: dict[str, M.Element] = {}
        for member in ns.members:
            for name in (member.name, member.short_name):
                if name is None:
                    continue
                if name in seen and seen[name] is not member:
                    self.report(
                        "error",
                        "duplicate-name",
                        member,
                        f"name {name!r} is already used by another member of {ns.label}",
                    )
                else:
                    seen[name] = member

    def _reference_fields(self, element: M.Definition | M.Usage) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []
        if isinstance(element, M.Definition):
            refs += [("specializes", s) for s in element.supers]
            return refs
        refs += [("typed by", t.lstrip("~")) for t in element.types]
        refs += [("subsets", s) for s in element.subsets]
        refs += [("redefines", r) for r in element.redefines]
        if element.references:
            refs.append(("references", element.references))
        if element.crosses:
            refs.append(("crosses", element.crosses))
        if isinstance(element, (M.ConnectionUsage, M.InterfaceUsage, M.AllocationUsage)):
            refs += [("connects", e.target) for e in element.ends]
        if isinstance(element, M.BindingConnector):
            for end in (element.source_end, element.target_end):
                if end is not None:
                    refs.append(("binds", end.target))
        if isinstance(element, M.SatisfyUsage) and element.by:
            refs.append(("satisfied by", element.by))
        return refs

    def check_references(self, element: M.Definition | M.Usage) -> None:
        for role, ref in self._reference_fields(element):
            self.check_target(element, ref, role)

    def check_target(self, element: M.Element, ref: str, role: str) -> None:
        if not ref:
            return
        if self._resolves(ref, element):
            self._check_implicit(element, ref)
            return
        self.report("warning", "unresolved-reference", element, f"{role} {ref!r} does not resolve")

    def check_expose(self, expose: M.Expose) -> None:
        """dangling-expose: an ``expose`` inside a view usage names an
        element that no longer resolves.  Restore skips such exposes with
        a warning (:mod:`longeron.views`); this diagnostic surfaces the
        same condition in ``validate`` / ``longeron lint``.  Warning, not
        error: the spec places no well-formedness constraint on an import
        target's continued existence, and the target may live in a file
        that was not loaded."""

        if not expose.target or self._resolves(expose.target, expose):
            return
        owner = expose.owner
        where = (owner.qualified_name or owner.label) if owner is not None else expose.label
        location = getattr(expose, "source_location", None)
        self.diagnostics.append(
            Diagnostic(
                "warning",
                "dangling-expose",
                f"expose target {expose.target!r} does not resolve",
                where,
                location,
            )
        )

    def _check_implicit(self, element: M.Element, ref: str) -> None:
        """stdlib-implicit-name: ``ref`` resolved, but only through the
        resolver's implicit library-visibility hop (strict mode only)."""

        if self.strict_imports and self._used_implicit:
            self.report(
                "warning",
                "stdlib-implicit-name",
                element,
                f"stdlib name {ref!r} used without import",
            )

    def _resolves(self, ref: str, context: M.Element) -> bool:
        scope: M.Element = context.owner or self.model
        implicit = False
        for segment in ref.split("."):
            if segment == "$":  # root escape: re-anchor at the model root
                scope = self.model
                continue
            try:
                scope = self.resolver.resolve(segment, scope)
            except ResolutionError:
                self._used_implicit = False
                return False
            implicit = implicit or self.resolver.last_hop == "library-implicit"
        self._used_implicit = implicit
        return True

    def check_specialization_cycle(self, element: M.Definition | M.Usage) -> None:
        seen: set[int] = set()
        stack: list[M.Element] = [element]
        while stack:
            node = stack.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            for general in self._cycle_generals(node):
                if general is element:
                    self.report(
                        "error",
                        "specialization-cycle",
                        element,
                        "specialization hierarchy is cyclic",
                    )
                    return
                stack.append(general)

    def _cycle_generals(self, node: M.Element) -> list[M.Namespace]:
        """Specialization edges for the cycle check: ``supers`` / ``types`` /
        ``subsets`` plus implied bases -- but *not* redefinition edges.

        A redefinition (``attribute x :>> x``) legitimately reuses the
        redefined feature's name, so resolving it lands on the redefining
        element itself; folding redefinition edges into the walk (as the
        resolver's ``_generals`` does) turns that shadowing into a false
        "cyclic" error.
        """

        names: list[str] = []
        if isinstance(node, M.Definition):
            names = list(node.supers)
        elif isinstance(node, M.Usage):
            names = list(node.types) + list(node.subsets)
        out: list[M.Namespace] = []
        for name in names:
            if name.startswith("~"):
                name = name[1:]
            try:
                general = self.resolver.resolve(name, node.owner or self.model)
            except ResolutionError:
                continue
            if isinstance(general, M.Namespace):
                out.append(general)
        for general in self.resolver.implied_generals(node):
            if general not in out:
                out.append(general)
        return out

    # -- expressions ------------------------------------------------------------------

    def check_expressions(self, element: M.Definition | M.Usage) -> None:
        local_names = self._local_names(element)
        for owner, expr in self._owned_expressions(element):
            for head in _expression_heads(expr):
                if head in local_names or head in BUILTINS or head == "$":
                    continue
                if self._resolves(head, owner):
                    self._check_implicit(owner, head)
                    continue
                if self._inherited_name(head, owner):
                    continue
                self.report(
                    "warning",
                    "unresolved-name",
                    owner,
                    f"expression name {head!r} does not resolve",
                )

    def _inherited_name(self, name: str, context: M.Element) -> bool:
        """True when ``name`` is a member inherited through an *implied*
        specialization (e.g. ``start``/``done`` via ``Actions::Action``)."""

        node: M.Element | None = context
        while node is not None:
            if isinstance(node, (M.Definition, M.Usage)):
                for member in self.resolver.members_of(node, implied=True):
                    if name in (member.name, member.short_name):
                        return True
            node = node.owner
        return False

    def _local_names(self, element: M.Namespace) -> set[str]:
        names: set[str] = set()
        for item in element.iter_tree():
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
        return names

    def _owned_expressions(self, element: M.Definition | M.Usage) -> list[tuple[M.Element, A.Expr]]:
        out: list[tuple[M.Element, A.Expr]] = []
        if isinstance(element, M.Usage) and element.value is not None:
            out.append((element, element.value.expr))
        if element.result is not None:
            out.append((element, element.result))
        for item in element.members:
            if isinstance(item, M.AssignmentAction):
                out.append((item if item.name else element, item.expr))
            elif isinstance(item, M.IfAction):
                out.append((element, item.condition))
            elif isinstance(item, M.WhileLoop):
                if item.condition is not None:
                    out.append((element, item.condition))
                if item.until is not None:
                    out.append((element, item.until))
            elif isinstance(item, M.ForLoop):
                out.append((element, item.seq))
            elif isinstance(item, M.SendAction):
                out.append((element, item.payload))
            elif isinstance(item, (M.Succession, M.TransitionUsage)) and item.guard is not None:
                out.append((element, item.guard))
        return out

    # -- state machines / calcs -----------------------------------------------------------

    def check_state_machine(self, machine: M.Definition | M.Usage) -> None:
        states = {
            m.name
            for m in machine.members
            if isinstance(m, M.Usage) and m.kind == "state" and m.name
        }
        if not states:
            return
        transitions = [m for m in machine.members if isinstance(m, M.TransitionUsage)]
        has_entry = any(t.source == M.ENTRY_SOURCE for t in transitions)
        if not has_entry:
            self.report(
                "warning",
                "no-entry-transition",
                machine,
                "state machine has states but no 'entry; then <state>;' transition",
            )
        for transition in transitions:
            if transition.source not in (None, M.ENTRY_SOURCE) and transition.source not in states:
                self.report(
                    "error",
                    "unknown-state",
                    machine,
                    f"transition source {transition.source!r} is not a state of {machine.label}",
                )
            if transition.target and transition.target not in states:
                self.report(
                    "error",
                    "unknown-state",
                    machine,
                    f"transition target {transition.target!r} is not a state of {machine.label}",
                )

    def check_calc_result(self, calc: M.Definition | M.Usage) -> None:
        if calc.result is not None:
            return
        for member in calc.members:
            if (
                isinstance(member, M.Usage)
                and member.direction == "return"
                and member.value is not None
            ):
                return
        if (
            not calc.members
            and isinstance(calc, M.Usage)
            and (calc.types or calc.subsets or calc.value)
        ):
            return  # reference/typed calc usages delegate their result
        self.report("warning", "calc-without-result", calc, "calculation has no result expression")

    # -- units ------------------------------------------------------------------

    def _units(self) -> units_module.UnitTable:
        """The unit table for this model (standard + model-derived), built
        lazily once per checker; degrades to an empty table on failure."""

        if self._unit_table is None:
            try:
                self._unit_table = units_module.unit_table(
                    self.model, include_standard=self.resolver.library is not None
                )
            except Exception:
                self._unit_table = units_module.UnitTable()
        return self._unit_table

    def check_units(self, element: M.Definition | M.Usage) -> None:
        """The dimensional lint: walk every owned expression, resolving
        unit annotations (``unresolved-unit``) and checking arithmetic
        over known dimension vectors and scale tags
        (``dimension-mismatch`` / ``scale-mismatch`` / ``mixed-units``)."""

        for owner, expr in self._owned_expressions(element):
            self._unit_meaning(owner, expr, report=True)

    _COMPARISONS = ("<", ">", "<=", ">=", "==", "!=")

    def _unit_meaning(self, owner: M.Element, expr: A.Expr, *, report: bool) -> _Meaning | None:
        """Bottom-up dimensional meaning of ``expr`` (``None`` = unknown),
        emitting diagnostics at conflicting operators when ``report``.

        Unknowns are bottom: a bare literal has *no* dimension (35.0 could
        be anything), unknown operands silence the check, and only two
        *known* vectors can conflict -- per the design's lint contract.
        """

        if isinstance(expr, A.QuantityOp):
            self._unit_meaning(owner, expr.base, report=report)
            return self._annotation_meaning(owner, expr.unit, report=report)
        if isinstance(expr, (A.FeatureRef, A.ChainAccess)):
            return self._feature_meaning(owner, expr)
        if isinstance(expr, A.Unary):
            operand = self._unit_meaning(owner, expr.operand, report=report)
            return operand if expr.op in ("+", "-") else None
        if isinstance(expr, A.Conditional):
            self._unit_meaning(owner, expr.test, report=report)
            then = self._unit_meaning(owner, expr.then, report=report)
            orelse = self._unit_meaning(owner, expr.orelse, report=report)
            if then is not None and orelse is not None and then.dim == orelse.dim:
                return then
            return None
        if isinstance(expr, A.Binary):
            return self._binary_meaning(owner, expr, report=report)
        # anything else: recurse for nested reporting, meaning unknown
        for field_name in ("base", "index", "items", "args", "result"):
            value = getattr(expr, field_name, None)
            if isinstance(value, A.Expr):
                self._unit_meaning(owner, value, report=report)
            elif isinstance(value, tuple):
                for item in value:
                    if isinstance(item, A.Expr):
                        self._unit_meaning(owner, item, report=report)
        return None

    def _binary_meaning(self, owner: M.Element, expr: A.Binary, *, report: bool) -> _Meaning | None:
        left = self._unit_meaning(owner, expr.left, report=report)
        right = self._unit_meaning(owner, expr.right, report=report)
        op = expr.op
        if op in ("+", "-") or op in self._COMPARISONS:
            if left is None or right is None:
                if op in ("+", "-"):
                    return left or right  # additive: the known side carries
                return None
            if len(left.dim.exp) != len(right.dim.exp):
                return None  # different bases (foreign system): incomparable
            table = self._units()
            if (
                op in ("+", "-")
                and left.scale is not None
                and right.scale is not None
                and left.scale != right.scale
            ):
                if report:
                    self.report(
                        "error",
                        "scale-mismatch",
                        owner,
                        f"operands of '{op}' mix measurement scales: "
                        f"{left.display(table)} is {left.scale}-scale, "
                        f"{right.display(table)} is {right.scale}-scale; "
                        "convert explicitly",
                    )
                return None
            if left.dim != right.dim:
                if report:
                    self.report(
                        "warning",
                        "dimension-mismatch",
                        owner,
                        f"operands of '{op}' have different dimensions: "
                        f"{left.display(table)} vs {right.display(table)}",
                    )
                return None
            if left.ident is not None and right.ident is not None and left.ident != right.ident:
                if report and not units_module.units_extra_available():
                    self.report(
                        "warning",
                        "mixed-units",
                        owner,
                        f"operands of '{op}' use different units of one "
                        f"dimension: {left.display(table)} vs {right.display(table)}; "
                        "magnitudes are not normalized without the [units] extra",
                    )
                if op in ("+", "-"):
                    return _Meaning(left.dim, left.scale, None, None)
            if op in ("+", "-"):
                return left
            return None  # comparisons yield booleans
        if op in ("*", "/"):
            # scaling by a bare numeric literal cannot change dimension
            # (`3 * x [m/s]`: the annotation binds to the primary `x`)
            if left is None and right is not None and _literal_number(expr.left) is not None:
                return right if op == "*" else None
            if right is None and left is not None and _literal_number(expr.right) is not None:
                return left
            if left is None or right is None:
                return None
            if len(left.dim.exp) != len(right.dim.exp):
                return None
            dim = left.dim * right.dim if op == "*" else left.dim / right.dim
            scale = "linear" if left.scale == right.scale == "linear" else None
            return _Meaning(dim, scale, None, None)
        if op in ("^", "**"):
            if left is None:
                return None
            power = _literal_number(expr.right)
            if power is None:
                return None
            scale = "linear" if left.scale == "linear" else None
            return _Meaning(left.dim ** Fraction(power).limit_denominator(1000), scale, None, None)
        return None  # logic, range, equality-of-identity, ...

    def _annotation_meaning(
        self, owner: M.Element, unit_expr: A.Expr, *, report: bool
    ) -> _Meaning | None:
        """The meaning carried by a ``[unit]`` annotation.  Reports
        ``unresolved-unit`` (once per dangling reference) when asked."""

        if isinstance(unit_expr, A.FeatureRef):
            info = self._resolve_unit(owner, unit_expr, report=report)
            if info is None:
                return None
            return _Meaning(info.dim, info.scale, info.qname, info.label)
        if isinstance(unit_expr, A.Binary) and unit_expr.op in ("*", "/", "^", "**"):
            left = self._annotation_meaning(owner, unit_expr.left, report=report)
            if unit_expr.op in ("^", "**"):
                power = _literal_number(unit_expr.right)
                if left is None or power is None:
                    return None
                dim = left.dim ** Fraction(power).limit_denominator(1000)
                return _Meaning(dim, left.scale, f"({left.ident}^{power})", None)
            right = self._annotation_meaning(owner, unit_expr.right, report=report)
            if left is None or right is None:
                return None
            if len(left.dim.exp) != len(right.dim.exp):
                return None
            dim = left.dim * right.dim if unit_expr.op == "*" else left.dim / right.dim
            scale = "linear" if left.scale == right.scale == "linear" else None
            ident = f"({left.ident}{unit_expr.op}{right.ident})"
            return _Meaning(dim, scale, ident, None)
        if isinstance(unit_expr, A.Literal) and isinstance(unit_expr.value, (int, float)):
            table = self._units()
            return _Meaning(table.dimensionless, "linear", None, None)
        return None  # exotic annotation shapes stay unchecked

    def _resolve_unit(
        self, owner: M.Element, ref: A.FeatureRef, *, report: bool
    ) -> units_module.UnitInfo | None:
        """Resolve one unit reference; ``unresolved-unit`` when it dangles.

        Bare stdlib unit names (``[kg]``) resolve through the implicit
        library hop *without* tripping ``strict_imports`` -- units are the
        measurement library's vocabulary, and bare references to it are
        the spec's own idiom.  A reference that resolves but is not a
        derivable unit contributes no dimension (bottom, silent).
        """

        scope = owner.owner or self.model
        try:
            element = self.resolver.resolve(ref.parts, scope)
        except ResolutionError:
            if report:
                self.report(
                    "warning",
                    "unresolved-unit",
                    owner,
                    f"unit {'::'.join(ref.parts)!r} does not resolve",
                )
            return None
        qname = element.qualified_name
        return self._units().lookup(qname) if qname else None

    def _feature_meaning(self, owner: M.Element, expr: A.Expr) -> _Meaning | None:
        """Meaning of a name in value position, from its declaration."""

        target = self._resolve_feature(owner, expr)
        if isinstance(target, M.Usage):
            return self._declared_meaning(target)
        return None

    def _resolve_feature(self, owner: M.Element, expr: A.Expr) -> M.Element | None:
        parts: tuple[str, ...]
        if isinstance(expr, A.FeatureRef):
            parts = expr.parts
        elif isinstance(expr, A.ChainAccess) and isinstance(expr.base, A.FeatureRef):
            parts = expr.base.parts + expr.parts
        else:
            return None
        scope: M.Element = owner.owner or self.model
        for segment in parts:
            if segment == "$":
                scope = self.model
                continue
            try:
                scope = self.resolver.resolve(segment, scope)
            except ResolutionError:
                return None
        return scope

    def _declared_meaning(self, usage: M.Usage) -> _Meaning | None:
        """Dimensional meaning of an attribute declaration: its value
        expression's annotation first, then quantity typing/subsetting
        (``:> ISQ::mass``), then the declaration it redefines or subsets.
        Memoized and cycle-guarded per checker."""

        key = id(usage)
        if key in self._meanings:
            return self._meanings[key]
        self._meanings[key] = None  # cycle guard: recursion sees bottom
        meaning: _Meaning | None = None
        if usage.value is not None:
            meaning = self._unit_meaning(usage, usage.value.expr, report=False)
        if meaning is None:
            meaning = self._quantity_typing_meaning(usage)
        self._meanings[key] = meaning
        return meaning

    def _quantity_typing_meaning(self, usage: M.Usage) -> _Meaning | None:
        table = self._units()
        scope = usage.owner or self.model
        for ref in list(usage.types) + list(usage.subsets) + list(usage.redefines):
            try:
                element = self.resolver.resolve(ref.lstrip("~").replace(".", "::"), scope)
            except ResolutionError:
                continue
            qname = element.qualified_name
            if qname is not None:
                dim = table.quantity_dimension(qname)
                if dim is not None:
                    # scale/identity unknown: quantity kinds type dimensions,
                    # not units, so only dimension-mismatch can fire
                    return _Meaning(dim, None, None, None)
            if isinstance(element, M.Usage) and element is not usage:
                inherited = self._declared_meaning(element)
                if inherited is not None:
                    return inherited
        return None

    #: the scoreboard convention's utility-shape parameters (kept in sync
    #: with :mod:`longeron.analysis.scoreboard`)
    _ANCHOR_ATTRS = ("ramp0", "ramp1", "target", "limit")

    def check_scoreboard_anchors(self, element: M.Definition | M.Usage) -> None:
        """anchor-dimension-mismatch: a scoreboard-convention ``ramp0`` /
        ``ramp1`` / ``target`` / ``limit`` attribute disagrees
        dimensionally with its sibling ``measure`` -- a ramp anchored in
        minutes scoring a measure computed in hours."""

        attributes = {
            member.name: member
            for member in element.members
            if isinstance(member, M.Usage) and member.kind == "attribute" and member.name
        }
        measure = attributes.get("measure")
        if measure is None:
            return
        measured = self._declared_meaning(measure)
        if measured is None:
            return
        table = self._units()
        for name in self._ANCHOR_ATTRS:
            anchor = attributes.get(name)
            if anchor is None:
                continue
            anchored = self._declared_meaning(anchor)
            if anchored is None:
                continue
            if anchored.dim != measured.dim:
                self.report(
                    "warning",
                    "anchor-dimension-mismatch",
                    anchor,
                    f"'{name}' {anchored.display(table)} disagrees dimensionally "
                    f"with 'measure' {measured.display(table)}",
                )
            elif (
                anchored.ident is not None
                and measured.ident is not None
                and anchored.ident != measured.ident
                and not units_module.units_extra_available()
            ):
                # the design's own example: a ramp anchored in minutes
                # scoring a measure computed in hours -- dimensionally
                # fine, numerically 60x off until the [units] extra
                # converts anchors at scoreboard build time
                self.report(
                    "warning",
                    "anchor-dimension-mismatch",
                    anchor,
                    f"'{name}' {anchored.display(table)} and 'measure' "
                    f"{measured.display(table)} use different units; magnitudes "
                    "are not normalized without the [units] extra",
                )


def _literal_number(expr: A.Expr) -> float | None:
    """The numeric value of a literal (or negated literal) exponent."""

    if isinstance(expr, A.Literal) and isinstance(expr.value, (int, float)):
        return float(expr.value)
    if isinstance(expr, A.Unary) and expr.op == "-":
        inner = _literal_number(expr.operand)
        return -inner if inner is not None else None
    return None


@dataclass(frozen=True)
class _Meaning:
    """What the dimensional lint knows about one expression: its exponent
    vector, its scale tag (``None`` = unknown), and -- when the value is
    still in one declared unit -- that unit's identity and label."""

    dim: units_module.Dim
    scale: str | None
    ident: str | None  # unit identity (qualified name / canonical compound)
    label: str | None  # display label ('kg', 'm / s'); None for derived

    def display(self, table: units_module.UnitTable) -> str:
        dim_text = table.format_dim(self.dim)
        if self.label:
            return f"'{self.label}' [{dim_text}]"
        return f"[{dim_text}]"


def _expression_heads(expr: A.Expr) -> set[str]:
    """First name segments referenced by an expression (skipping locals of
    nested body expressions)."""

    heads: set[str] = set()

    def walk(node: A.Expr, bound: frozenset[str]) -> None:
        if isinstance(node, A.FeatureRef):
            if node.parts and node.parts[0] not in bound:
                heads.add(node.parts[0])
            return
        if isinstance(node, (A.Invocation, A.Constructor)):
            head = node.target[0] if isinstance(node, A.Invocation) else node.type[0]
            if head not in bound:
                heads.add(head)
            for arg in node.args:
                walk(arg, bound)
            for _, arg in node.named:
                walk(arg, bound)
            return
        if isinstance(node, A.BodyExpr):
            inner = bound | {p.name for p in node.params} | {name for name, _ in node.lets}
            for _, let_expr in node.lets:
                walk(let_expr, inner)
            if node.result is not None:
                walk(node.result, inner)
            return
        if isinstance(node, A.ArrowOp):
            walk(node.base, bound)
            for arg in node.args:
                walk(arg, bound)
            if node.body is not None:
                walk(node.body, bound)
            return
        if isinstance(node, (A.CollectOp, A.SelectOp)):
            walk(node.base, bound)
            walk(node.body, bound)
            return
        for field_name in (
            "operand",
            "left",
            "right",
            "test",
            "then",
            "orelse",
            "base",
            "index",
            "items",
        ):
            # note: QuantityOp.unit is deliberately skipped here -- unit
            # references get their own resolution check (unresolved-unit)
            value = getattr(node, field_name, None)
            if isinstance(value, A.Expr):
                walk(value, bound)
            elif isinstance(value, tuple):
                for item in value:
                    if isinstance(item, A.Expr):
                        walk(item, bound)

    walk(expr, frozenset())
    return heads
