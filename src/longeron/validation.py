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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from . import ast as A
from . import model as M
from . import stdlib as stdlib_module
from .errors import ResolutionError
from .interpreter import BUILTINS, Resolver

Severity = Literal["error", "warning"]


@dataclass
class Diagnostic:
    severity: Severity
    code: str
    message: str
    element: str  # qualified name (or best-effort label) of the subject

    def __str__(self) -> str:
        return f"{self.severity}[{self.code}] {self.element}: {self.message}"


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

    def report(self, severity: Severity, code: str, element: M.Element, message: str) -> None:
        where = element.qualified_name or element.label
        self.diagnostics.append(Diagnostic(severity, code, message, where))

    # -- driver ---------------------------------------------------------------

    def check_all(self) -> None:
        for element in self.model.iter_tree():
            if isinstance(element, M.Namespace):
                self.check_duplicate_names(element)
            if isinstance(element, (M.Definition, M.Usage)):
                self.check_references(element)
                self.check_specialization_cycle(element)
                self.check_expressions(element)
            if isinstance(element, M.Import):
                self.check_target(element, element.target, "import")
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
            for general in self.resolver._generals(node, implied=True):
                if general is element:
                    self.report(
                        "error",
                        "specialization-cycle",
                        element,
                        "specialization hierarchy is cyclic",
                    )
                    return
                stack.append(general)

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
            # note: QuantityOp.unit is deliberately skipped -- unit
            # references live in measurement libraries we do not load
            value = getattr(node, field_name, None)
            if isinstance(value, A.Expr):
                walk(value, bound)
            elif isinstance(value, tuple):
                for item in value:
                    if isinstance(item, A.Expr):
                        walk(item, bound)

    walk(expr, frozenset())
    return heads
