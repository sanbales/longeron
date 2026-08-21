"""Execution engine for SysML v2 models.

Capabilities
============
* **Expression evaluation** over the AST in :mod:`sysml2.ast` (arithmetic,
  comparison, logic, conditionals, sequences, ``->`` collection operators,
  invocation of calc definitions and builtin math functions, feature chains,
  enum literals, instance features).
* **Instantiation** of part/item definitions into :class:`Instance` trees,
  evaluating attribute values (with inheritance, redefinition overrides and
  caller-supplied bindings).
* **Constraint / requirement checking** against instances.
* **Action execution**: parameters, ``assign``, ``if``/``while``/``for``,
  ``send``/``accept``, ``perform``, ``terminate``, nested actions and calc
  bindings, in declaration order.
* **State machine simulation**: entry transitions, triggers (``accept``),
  guards, effects, entry/do/exit actions.

Deliberate simplifications (this is a modeling sandbox, not a full KerML
semantic engine): declaration order is execution order for actions (explicit
successions are honored as documentation, not reordered), quantities/units
evaluate to their numeric value, and control nodes (fork/join/merge/decide)
are modeled but not executed.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar

from . import ast as A
from . import model as M
from .errors import EvaluationError, ExecutionError, ResolutionError

# ---------------------------------------------------------------------------
# Runtime values
# ---------------------------------------------------------------------------


class Instance:
    """A runtime instance of a part/item definition (or anonymous usage)."""

    def __init__(self, type_name: str, definition: M.Definition | M.Usage | None = None):
        self.type_name = type_name
        self.definition = definition
        self.slots: dict[str, Any] = {}

    def get(self, path: str) -> Any:
        node: Any = self
        for part in path.split("."):
            if isinstance(node, Instance):
                if part not in node.slots:
                    raise EvaluationError(f"instance of {node.type_name} has no feature {part!r}")
                node = node.slots[part]
            else:
                raise EvaluationError(f"cannot access {part!r} on {node!r}")
        return node

    def set(self, path: str, value: Any) -> None:
        parts = path.split(".")
        node: Any = self
        for part in parts[:-1]:
            node = node.slots[part] if isinstance(node, Instance) else None
            if node is None:
                raise EvaluationError(f"cannot traverse {part!r} in {path!r}")
        node.slots[parts[-1]] = value

    def to_dict(self) -> dict[str, Any]:
        def convert(value):
            if isinstance(value, Instance):
                return value.to_dict()
            if isinstance(value, list):
                return [convert(v) for v in value]
            if isinstance(value, EnumValue):
                return str(value)
            return value

        return {"@type": self.type_name, **{k: convert(v) for k, v in self.slots.items()}}

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self.slots.items())
        return f"{self.type_name}({inner})"


@dataclass(frozen=True)
class EnumValue:
    enum: str  # qualified name of the enumeration definition
    name: str

    def __str__(self) -> str:
        return f"{self.enum}::{self.name}"


@dataclass
class TypeValue:
    """A definition used as a value (e.g. in ``istype`` or invocations)."""

    definition: M.Namespace

    def __repr__(self) -> str:
        return f"<type {self.definition.qualified_name}>"


@dataclass
class Closure:
    body: A.BodyExpr
    env: Env


@dataclass
class SentEvent:
    payload: Any
    to: Any = None
    via: Any = None


@dataclass
class ConstraintResult:
    name: str
    kind: str  # 'constraint' | 'assume' | 'require' | 'assert'
    passed: bool | None
    expression: str
    message: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return bool(self.passed)


@dataclass
class RequirementResult:
    name: str
    assumptions: list[ConstraintResult] = field(default_factory=list)
    requirements: list[ConstraintResult] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return all(r.passed for r in self.assumptions)

    @property
    def satisfied(self) -> bool | None:
        if not self.applicable:
            return None
        return all(r.passed for r in self.requirements)


@dataclass
class ActionResult:
    outputs: dict[str, Any]
    sends: list[SentEvent]
    trace: list[str]
    env: dict[str, Any]
    terminated: bool = False
    time: float = 0.0


@dataclass
class TransitionFired:
    source: str
    event: str | None
    target: str
    time: float = 0.0  # StateMachine clock (`now`) when the transition fired

    def __repr__(self) -> str:
        return f"{self.source} --{self.event or 'auto'}--> {self.target}"


@dataclass
class SimulationResult:
    final_state: str | None
    trace: list[TransitionFired]
    ignored_events: list[str]
    env: dict[str, Any]
    sends: list[SentEvent]
    time: float = 0.0
    active_states: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Builtin function library
# ---------------------------------------------------------------------------


def _named_usages(
    members: list[M.Element], directions: tuple[str, ...]
) -> list[tuple[str, M.Usage]]:
    """(name, usage) pairs for named parameters with one of ``directions``."""

    return [
        (m.name, m)
        for m in members
        if isinstance(m, M.Usage) and m.direction in directions and m.name is not None
    ]


def _seq(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


BUILTINS: dict[str, Any] = {
    "sqrt": math.sqrt,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
    "exp": math.exp,
    "ln": math.log,
    "log": math.log10,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "pow": math.pow,
    "max": lambda *a: max(_flatten(a)),
    "min": lambda *a: min(_flatten(a)),
    "sum": lambda *a: sum(_flatten(a)),
    "size": lambda s: len(_seq(s)),
    "isEmpty": lambda s: len(_seq(s)) == 0,
    "notEmpty": lambda s: len(_seq(s)) > 0,
    "ToString": lambda v: "true" if v is True else "false" if v is False else str(v),
    "ToInteger": int,
    "ToReal": float,
    "ToNatural": int,
    "ToBoolean": lambda v: v in (True, "true", 1),
    "pi": math.pi,
    "e": math.e,
}


def _flatten(args):
    out = []
    for a in args:
        out.extend(_seq(a))
    return out


_ARROW_OPS: dict[str, Callable] = {
    "size": lambda seq, *_: len(seq),
    "isEmpty": lambda seq, *_: len(seq) == 0,
    "notEmpty": lambda seq, *_: len(seq) > 0,
    "head": lambda seq, *_: seq[0] if seq else None,
    "last": lambda seq, *_: seq[-1] if seq else None,
    "tail": lambda seq, *_: seq[1:],
    "reverse": lambda seq, *_: list(reversed(seq)),
    "sum": lambda seq, *_: sum(seq),
    "max": lambda seq, *_: max(seq),
    "min": lambda seq, *_: min(seq),
}


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

#: Implied specializations (SysML v2 spec clause 7: every definition/usage
#: kind must directly or indirectly specialize a base element of the
#: Systems Model Library, e.g. ``checkPartDefinitionSpecialization``).  A
#: definition or usage that declares *no* explicit specializations
#: implicitly specializes (definitions) / subsets (usages) these library
#: elements: kind -> (definition base, usage base).
IMPLIED_SPECIALIZATIONS: dict[str, tuple[str | None, str | None]] = {
    "part": ("Parts::Part", "Parts::parts"),
    "item": ("Items::Item", "Items::items"),
    # KerML's Base::DataValue lives in the vendored ScalarValues shim; the
    # kernel's Base::dataValues usage is not vendored, so attribute/enum
    # usages get no implied subsetting here.
    "attribute": ("ScalarValues::DataValue", None),
    "enum": ("ScalarValues::DataValue", None),
    "action": ("Actions::Action", "Actions::actions"),
    "calc": ("Calculations::Calculation", "Calculations::calculations"),
    "constraint": ("Constraints::ConstraintCheck", "Constraints::constraintChecks"),
    "requirement": ("Requirements::RequirementCheck", "Requirements::requirementChecks"),
    "state": ("States::StateAction", "States::stateActions"),
    "connection": ("Connections::Connection", "Connections::connections"),
    "port": ("Ports::Port", "Ports::ports"),
    "interface": ("Interfaces::Interface", "Interfaces::interfaces"),
    "allocation": ("Allocations::Allocation", "Allocations::allocations"),
    "occurrence": ("Occurrences::Occurrence", "Occurrences::occurrences"),
}


def _in_library_package(element: M.Element) -> bool:
    """True when ``element`` lives inside a (standard) library package.

    Library elements declare their generalizations explicitly; implying
    bases onto the library's own roots would fabricate specialization
    cycles (``Anything -> Item -> ... -> Anything``).
    """

    node: M.Element | None = element
    while node is not None:
        if isinstance(node, M.Package) and (node.is_library or node.is_standard):
            return True
        node = node.owner
    return False


class Resolver:
    """Qualified-name resolution with memoization.

    Resolution follows KerML-style scoping: inner scopes shadow outer
    ones, and within a scope own members are found before inherited ones,
    which are found before imported ones.  When a ``library`` model is
    supplied, names that fail to resolve in the user model's root
    namespace fall back to the library -- first to the library's root
    packages themselves (so ``ScalarValues::Real`` resolves) and then to
    their contents as if implicitly imported (so a bare ``Real`` resolves
    without an explicit import).  That last hop is the KerML
    global-namespace convenience for *standard library packages*: a
    deliberate leniency so existing models that never import
    ``ScalarValues`` stay warning-free.  The user model is never mutated.

    The caches assume the model is not mutated while this resolver is in
    use; create a new :class:`Interpreter` (or call :meth:`clear_cache`)
    after structural changes such as ``add_standard_library``.
    """

    def __init__(self, model: M.Model, library: M.Model | None = None):
        self.model = model
        self.library = library
        self._active_imports: set = set()
        self._active_lookups: set[tuple[int, str]] = set()
        self._resolve_cache: dict[tuple[tuple[str, ...], int], tuple[M.Element, str] | None] = {}
        #: how the last successful :meth:`resolve` found its *first*
        #: segment: ``"scope"`` (lexical scoping, incl. imports),
        #: ``"library"`` (a standard-library root package, i.e. qualified
        #: access), or ``"library-implicit"`` (a bare name found inside a
        #: root library package without any import -- the KerML
        #: global-namespace convenience; see
        #: ``validate(strict_imports=True)``)
        self.last_hop: str = "scope"
        self._hop: str = "scope"
        self._member_cache: dict[tuple[int, str, bool, bool], M.Element | None] = {}
        self._generals_cache: dict[tuple[int, bool], list[M.Namespace]] = {}
        self._members_of_cache: dict[tuple[int, bool], list[M.Element]] = {}
        self._library_index: dict[str, M.Namespace] | None = None

    def clear_cache(self) -> None:
        self._resolve_cache.clear()
        self._member_cache.clear()
        self._generals_cache.clear()
        self._members_of_cache.clear()
        self._library_index = None

    def resolve(self, qname: str | tuple[str, ...], context: M.Element | None = None) -> M.Element:
        parts = tuple(qname.split("::") if isinstance(qname, str) else qname)
        key = (parts, id(context))
        if key in self._resolve_cache:
            cached = self._resolve_cache[key]
            if cached is None:
                raise ResolutionError(f"cannot resolve name {parts[0]!r}")
            element, self.last_hop = cached
            return element
        try:
            element = self._resolve_uncached(list(parts), context)
        except ResolutionError:
            if not self._active_imports and not self._active_lookups:
                self._resolve_cache[key] = None
            raise
        self.last_hop = self._hop
        if not self._active_imports and not self._active_lookups:
            self._resolve_cache[key] = (element, self._hop)
        return element

    def _resolve_uncached(self, parts: list[str], context: M.Element | None) -> M.Element:
        if parts and parts[0] == "$":
            parts = parts[1:]
            context = self.model
        element = self._resolve_first(parts[0], context or self.model)
        if element is None:
            raise ResolutionError(
                f"cannot resolve name {parts[0]!r}"
                + (
                    f" from {context.qualified_name}"
                    if context is not None and context.qualified_name
                    else ""
                )
            )
        hop = self._hop  # first-segment hop, before deeper lookups clobber it
        for part in parts[1:]:
            child = self._member(element, part, include_imports=True, only_public_imports=True)
            if child is None:
                raise ResolutionError(
                    f"{element.qualified_name or element.label} has no member {part!r}"
                )
            element = child
        self._hop = hop
        return element

    def _resolve_first(self, name: str, context: M.Element) -> M.Element | None:
        # _hop is set at each RETURN point (nested lookups may recurse
        # through this method; the last write before returning wins)
        node: M.Element | None = context
        while node is not None:
            if isinstance(node, M.Namespace):
                found = self._member(node, name, include_imports=True)
                if found is not None:
                    self._hop = "scope"
                    return found
            node = node.owner
        # fall back to the model root
        found = self._member(self.model, name, include_imports=True)
        if found is not None or self.library is None:
            self._hop = "scope"
            return found
        # library fallback: root packages, then their (implicitly
        # imported) contents -- see the class docstring
        found = self._member(self.library, name, include_imports=True)
        if found is not None:
            self._hop = "library"
            return found
        package = self._library_packages().get(name)
        if package is not None:
            found = self._member(package, name, include_imports=False)
            if found is not None:  # set AFTER the lookup (it may recurse)
                self._hop = "library-implicit"
            return found
        return None

    def _library_packages(self) -> dict[str, M.Namespace]:
        """Bare name -> root library package that directly declares it.

        Built once per resolver: only DIRECT members of the library's root
        packages participate (no import following), which keeps both the
        build and every miss O(1).  Import re-exports are deliberately
        excluded from the bare-name convenience -- they remain reachable
        through qualified names.  Without this index, a miss explored the
        whole stdlib import graph with caching disabled (the _active_*
        guards), which effectively hung validation on any typo.
        """

        index = self._library_index
        if index is None:
            index = {}
            assert self.library is not None
            for package in self.library.members:
                if not isinstance(package, M.Namespace):
                    continue
                for member in package.members:
                    names = (member.name, getattr(member, "short_name", None))
                    for nm in names:
                        if nm and nm not in index:
                            index[nm] = package
            self._library_index = index
        return index

    def _member(
        self,
        element: M.Element,
        name: str,
        include_imports: bool = False,
        only_public_imports: bool = False,
    ) -> M.Element | None:
        """Find ``name`` in a namespace.

        ``include_imports`` follows imports (in-scope lookup).  With
        ``only_public_imports`` only ``public import`` re-exports are
        followed -- the rule for qualified access from outside (`A::x`
        finds `x` that `A` publicly imports).
        """

        key = (id(element), name, include_imports, only_public_imports)
        if key in self._member_cache:
            return self._member_cache[key]
        lookup_key = (id(element), name)
        if lookup_key in self._active_lookups:
            return None  # already searching this namespace for this name
        self._active_lookups.add(lookup_key)
        try:
            found = self._member_uncached(element, name, include_imports, only_public_imports)
        finally:
            self._active_lookups.discard(lookup_key)
        if not self._active_imports and not self._active_lookups:
            self._member_cache[key] = found  # only cache top-level lookups
        return found

    def _member_uncached(
        self, element: M.Element, name: str, include_imports: bool, only_public_imports: bool
    ) -> M.Element | None:
        if not isinstance(element, M.Namespace):
            return None
        for member in element.members:
            if isinstance(member, M.Alias):
                continue  # matched below, by resolving the alias target
            if name in (member.name, member.short_name):
                return member
        for member in element.members:
            if isinstance(member, M.Alias) and name in (member.name, member.short_name):
                try:
                    return self.resolve(member.target, element)
                except ResolutionError:
                    return None
        # inherited members (definition supers / usage types+subsets)
        for general in self._generals(element):
            found = self._member(general, name)
            if found is not None:
                return found
        if include_imports:
            for member in element.members:
                if not isinstance(member, M.Import):
                    continue
                if only_public_imports and member.visibility != "public":
                    continue
                key = (id(member), name)
                if key in self._active_imports:
                    continue  # break import resolution cycles
                self._active_imports.add(key)
                try:
                    if member.is_namespace:
                        target = self._resolve_import_target(member.target, element)
                        found = self._member(
                            target, name, include_imports=True, only_public_imports=True
                        )
                        if found is not None:
                            return found
                    elif member.target.split("::")[-1] == name:
                        return self._resolve_import_target(member.target, element)
                except ResolutionError:
                    continue
                finally:
                    self._active_imports.discard(key)
        return None

    def _resolve_import_target(self, qname: str, ns: M.Element) -> M.Element:
        """Resolve an import's target.

        The first segment is looked up among the importing namespace's own
        members and then in its *enclosing* scopes -- never through the
        namespace's own imports, which would make import chains cyclic.
        """

        parts = qname.split("::")
        element: M.Element | None = self._member(ns, parts[0])
        if element is None:
            owner = ns.owner
            element = self._resolve_first(parts[0], owner if owner is not None else self.model)
        if element is None:
            raise ResolutionError(f"cannot resolve import target {qname!r}")
        for part in parts[1:]:
            child = self._member(element, part, include_imports=True, only_public_imports=True)
            if child is None:
                raise ResolutionError(f"import target {qname!r}: no member {part!r}")
            element = child
        return element

    def implied_generals(self, element: M.Element) -> list[M.Namespace]:
        """The implied standard-library base of ``element``.

        Implied specializations apply only when the element declares *no*
        explicit supers/types/subsets/redefines (see
        :data:`IMPLIED_SPECIALIZATIONS`).  The base is resolved against
        the model plus the library fallback; unresolvable bases yield
        ``[]`` silently.
        """

        if isinstance(element, M.Definition):
            if element.supers:
                return []
            index = 0
        elif isinstance(element, M.Usage):
            if element.types or element.subsets or element.redefines:
                return []
            index = 1
        else:
            return []
        if _in_library_package(element):
            return []
        bases = IMPLIED_SPECIALIZATIONS.get(element.kind)
        qname = bases[index] if bases is not None else None
        if qname is None:
            return []
        try:
            base = self.resolve(qname, self.model)
        except ResolutionError:
            return []
        if isinstance(base, M.Namespace) and base is not element:
            return [base]
        return []

    def _generals(self, element: M.Element, *, implied: bool = False) -> list[M.Namespace]:
        key = (id(element), implied)
        cached = self._generals_cache.get(key)
        if cached is not None:
            return cached
        names: list[str] = []
        if isinstance(element, M.Definition):
            names = element.supers
        elif isinstance(element, M.Usage):
            names = list(element.types) + list(element.subsets) + list(element.redefines)
        out: list[M.Namespace] = []
        for name in names:
            if name.startswith("~"):
                name = name[1:]
            try:
                general = self.resolve(name, element.owner or self.model)
            except ResolutionError:
                continue
            if isinstance(general, M.Namespace):
                out.append(general)
        if implied:
            for general in self.implied_generals(element):
                if general not in out:
                    out.append(general)
        if not self._active_imports and not self._active_lookups:
            self._generals_cache[key] = out
        return out

    def members_of(self, element: M.Namespace, *, implied: bool = False) -> list[M.Element]:
        """Own + inherited members; redefinitions shadow inherited names.

        With ``implied=True`` the implied standard-library bases (see
        :meth:`implied_generals`) contribute inherited members too.
        """

        cached = self._members_of_cache.get((id(element), implied))
        if cached is not None:
            return cached
        collected: dict[int, M.Element] = {}
        order: list[M.Element] = []
        shadowed: set = set()
        visited: set[int] = set()

        def visit(ns: M.Namespace) -> None:
            if id(ns) in visited:  # specialization cycles / diamonds
                return
            visited.add(id(ns))
            for member in ns.members:
                key = member.name or member.short_name
                if key is not None and key in shadowed:
                    continue
                if key is not None:
                    shadowed.add(key)
                if isinstance(member, M.Usage):
                    for redefined in member.redefines:
                        shadowed.add(redefined.split("::")[-1].split(".")[-1])
                if id(member) not in collected:
                    collected[id(member)] = member
                    order.append(member)
            for general in self._generals(ns, implied=implied):
                visit(general)

        visit(element)
        self._members_of_cache[(id(element), implied)] = order
        return order


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


class Env:
    """Layered lookup: local frames -> instance slots -> model namespace."""

    def __init__(
        self,
        interpreter: Interpreter,
        context: M.Element | None,
        frames: list[dict[str, Any]] | None = None,
        instance: Instance | None = None,
    ):
        self.interpreter = interpreter
        self.context = context
        self.frames = frames if frames is not None else [{}]
        self.instance = instance

    def child(self, frame: dict[str, Any] | None = None) -> Env:
        return Env(
            self.interpreter,
            self.context,
            [frame if frame is not None else {}, *self.frames],
            self.instance,
        )

    def bind(self, name: str, value: Any) -> None:
        self.frames[0][name] = value

    def assign(self, path: str, value: Any) -> None:
        first = path.split(".")[0]
        for frame in self.frames:
            if first in frame:
                if "." in path:
                    node = frame[first]
                    if not isinstance(node, Instance):
                        raise EvaluationError(f"cannot assign into non-instance {first!r}")
                    node.set(path.split(".", 1)[1], value)
                else:
                    frame[first] = value
                return
        if self.instance is not None and first in self.instance.slots:
            self.instance.set(path, value)
            return
        self.frames[0][path.split(".")[0] if "." not in path else path] = value
        if "." in path:
            raise EvaluationError(f"cannot assign to unknown path {path!r}")

    def lookup(self, name: str) -> Any:
        for frame in self.frames:
            if name in frame:
                return frame[name]
        if self.instance is not None and name in self.instance.slots:
            return self.instance.slots[name]
        return self.interpreter._resolve_value(name, self.context, self)


# ---------------------------------------------------------------------------
# Interpreter
# ---------------------------------------------------------------------------

_MAX_LOOP_ITERATIONS = 100_000


class Interpreter:
    """Evaluate and execute elements of a :class:`~sysml2.model.Model`."""

    def __init__(self, model: M.Model):
        self.model = model
        self.resolver = Resolver(model)
        self._const_cache: dict[int, Any] = {}

    # -- public API -----------------------------------------------------------

    def resolve(self, qname: str) -> M.Element:
        return self.resolver.resolve(qname)

    def evaluate(
        self, expr: str | A.Expr, context: str | M.Namespace | None = None, **bindings: Any
    ) -> Any:
        """Evaluate an expression (text or AST) with optional name bindings."""

        if isinstance(expr, str):
            from .builder import parse_expression

            expr = parse_expression(expr)
        if isinstance(context, str):
            context = self.resolver.resolve(context)  # type: ignore[assignment]
        env = Env(
            self, context if isinstance(context, M.Namespace) else self.model, [dict(bindings)]
        )
        return self.eval(expr, env)

    def instantiate(self, definition: str | M.Definition | M.Usage, **bindings: Any) -> Instance:
        """Create an instance of a part/item definition, evaluating attribute
        values; ``bindings`` override attribute values by name."""

        defn = self.resolver.resolve(definition) if isinstance(definition, str) else definition
        if not isinstance(defn, (M.Definition, M.Usage)):
            raise EvaluationError(f"cannot instantiate {definition!r}")
        return self._instantiate(defn, bindings)

    def call(self, calc: str | M.Definition | M.Usage, *args: Any, **kwargs: Any) -> Any:
        """Invoke a calc (or constraint) definition/usage as a function."""

        target = self.resolver.resolve(calc) if isinstance(calc, str) else calc
        return self._call_calc(target, list(args), kwargs)

    def check(self, instance: Instance) -> list[ConstraintResult]:
        """Evaluate all constraints declared on the instance's definition."""

        defn = instance.definition
        if defn is None:
            raise EvaluationError("instance has no definition to check")
        env = Env(self, defn, [{}], instance=instance)
        results = []
        for member in self.resolver.members_of(defn):
            if isinstance(member, M.Usage) and member.kind == "constraint":
                results.append(self._check_constraint(member, env))
        return results

    def check_requirement(
        self,
        requirement: str | M.Definition | M.Usage,
        subject: Instance | None = None,
        **bindings: Any,
    ) -> RequirementResult:
        req = self.resolver.resolve(requirement) if isinstance(requirement, str) else requirement
        if not isinstance(req, (M.Definition, M.Usage)):
            raise EvaluationError(f"{requirement!r} is not a requirement")
        frame: dict[str, Any] = dict(bindings)
        members = self.resolver.members_of(req)
        if subject is not None:
            subject_names = [
                m.name for m in members if isinstance(m, M.Usage) and m.kind == "subject" and m.name
            ]
            frame[subject_names[0] if subject_names else "subject"] = subject
        env = Env(self, req, [frame], instance=subject)
        result = RequirementResult(name=req.name or "<requirement>")
        for member in members:
            if not (isinstance(member, M.Usage) and member.kind == "constraint"):
                continue
            outcome = self._check_constraint(member, env)
            if member.constraint_kind == "assume":
                result.assumptions.append(outcome)
            else:
                result.requirements.append(outcome)
        return result

    def run_action(
        self,
        action: str | M.Definition | M.Usage,
        inputs: dict[str, Any] | None = None,
        events: list[Any] | None = None,
    ) -> ActionResult:
        target = self.resolver.resolve(action) if isinstance(action, str) else action
        if not isinstance(target, (M.Definition, M.Usage)):
            raise ExecutionError(f"{action!r} is not an action")
        executor = _ActionExecutor(self, target, inputs or {}, deque(events or []))
        return executor.run()

    def snapshot(
        self, instance: Instance, name: str | None = None, kind: M.UsageKind = "part"
    ) -> M.Usage:
        """Convert a runtime :class:`Instance` back into a model usage.

        The result is a part usage typed by the instance's definition, with
        every slot bound to its computed value -- suitable for adding to a
        package and saving (the "full loop": load, run, write results back).
        """

        usage = M.Usage(kind=kind, name=name)
        defn = instance.definition
        if defn is not None and defn.qualified_name:
            usage.types = [defn.qualified_name]
        for slot, value in instance.slots.items():
            for member in self._snapshot_members(slot, value):
                usage.add(member)
        return usage

    def _snapshot_members(self, name: str, value: Any) -> list[M.Element]:
        if isinstance(value, Instance):
            return [self.snapshot(value, name=name)]
        if isinstance(value, list) and any(isinstance(v, Instance) for v in value):
            return [self.snapshot(v, name=f"{name}_{i + 1}") for i, v in enumerate(value)]
        expr = self._value_to_expr(value)
        if expr is None:
            return []
        return [M.Usage(kind="attribute", name=name, value=M.FeatureValue(expr))]

    def _value_to_expr(self, value: Any) -> A.Expr | None:
        if value is None or isinstance(value, (bool, int, float, str)):
            return A.Literal(value)
        if isinstance(value, EnumValue):
            return A.FeatureRef((*value.enum.split("::"), value.name))
        if isinstance(value, list):
            items = [self._value_to_expr(v) for v in value]
            if any(item is None for item in items):
                return None
            return A.SequenceExpr(tuple(items))  # type: ignore[arg-type]
        return None  # closures, type values, ... are not snapshottable

    def simulate(
        self,
        state_machine: str | M.Definition | M.Usage,
        events: list[Any] | None = None,
        inputs: dict[str, Any] | None = None,
        max_steps: int = 1000,
    ) -> SimulationResult:
        """Simulate a state machine.

        ``events`` entries are event names (or ``(name, payload)`` tuples);
        a plain number advances the simulation clock by that amount, firing
        due ``accept after``/``accept at`` transitions.
        """

        target = (
            self.resolver.resolve(state_machine)
            if isinstance(state_machine, str)
            else state_machine
        )
        if not isinstance(target, (M.Definition, M.Usage)):
            raise ExecutionError(f"{state_machine!r} is not a state machine")
        sim = StateMachine(self, target, inputs or {})
        sim.start()
        for event in events or []:
            if isinstance(event, (int, float)) and not isinstance(event, bool):
                sim.advance(event)
            else:
                sim.send(event)
            if len(sim.trace) > max_steps:
                raise ExecutionError("state machine exceeded max_steps")
        return SimulationResult(
            final_state=sim.current,
            trace=sim.trace,
            ignored_events=sim.ignored,
            env=dict(sim.env.frames[0]),
            sends=sim.sends,
            time=sim.now,
            active_states=sim.active_states(),
        )

    # -- name-to-value resolution ----------------------------------------------

    def _resolve_value(self, name: str, context: M.Element | None, env: Env) -> Any:
        if name in BUILTINS:
            return BUILTINS[name]
        try:
            element = self.resolver.resolve(name, context)
        except ResolutionError as exc:
            raise EvaluationError(str(exc)) from exc
        return self._element_value(element, env)

    def _element_value(self, element: M.Element, env: Env) -> Any:
        if isinstance(element, M.Usage):
            if element.kind == "enum_literal":
                enum = element.owner
                enum_name = (enum.qualified_name or enum.label) if enum is not None else "<enum>"
                return EnumValue(enum_name, element.label)
            if element.kind in ("calc", "constraint"):
                return TypeValue(element)
            if element.value is not None:
                key = id(element)
                if key not in self._const_cache:
                    owner_env = Env(self, element.owner or self.model, [{}], instance=env.instance)
                    self._const_cache[key] = self.eval(element.value.expr, owner_env)
                return self._const_cache[key]
            return TypeValue(element)
        if isinstance(element, (M.Definition, M.Package)):
            return TypeValue(element)
        raise EvaluationError(f"{element.label} ({type(element).__name__}) has no runtime value")

    # -- expression evaluation ----------------------------------------------------

    def eval(self, expr: A.Expr, env: Env) -> Any:
        if isinstance(expr, A.Literal):
            return expr.value
        if isinstance(expr, A.FeatureRef):
            value = env.lookup(expr.parts[0]) if expr.parts[0] != "$" else TypeValue(self.model)
            for part in expr.parts[1:]:
                value = self._member_value(value, part, env)
            return value
        if isinstance(expr, A.ChainAccess):
            value = self.eval(expr.base, env)
            for part in expr.parts:
                for sub in part.split("::"):
                    value = self._member_value(value, sub, env)
            return value
        if isinstance(expr, A.Unary):
            return self._unary(expr.op, self.eval(expr.operand, env))
        if isinstance(expr, A.Binary):
            return self._binary(expr, env)
        if isinstance(expr, A.Conditional):
            test = self.eval(expr.test, env)
            return self.eval(expr.then if test else expr.orelse, env)
        if isinstance(expr, A.Classification):
            return self._classify(expr, env)
        if isinstance(expr, A.Cast):
            return self._cast(expr, env)
        if isinstance(expr, A.SequenceExpr):
            out: list[Any] = []
            for item in expr.items:
                value = self.eval(item, env)
                out.extend(value) if isinstance(value, list) else out.append(value)
            return out
        if isinstance(expr, A.IndexOp):
            base = _seq(self.eval(expr.base, env))
            index = self.eval(expr.index[0], env)
            if not isinstance(index, int) or not 1 <= index <= len(base):
                raise EvaluationError(f"index {index!r} out of range (sequences are 1-based)")
            return base[index - 1]
        if isinstance(expr, A.QuantityOp):
            return self.eval(expr.base, env)  # units are annotations
        if isinstance(expr, A.Invocation):
            return self._invoke(expr, env)
        if isinstance(expr, A.Constructor):
            return self._construct(expr.type, list(expr.args), dict(expr.named), env)
        if isinstance(expr, A.ArrowOp):
            return self._arrow(expr, env)
        if isinstance(expr, A.CollectOp):
            return [self._apply_body(expr.body, [v], env) for v in _seq(self.eval(expr.base, env))]
        if isinstance(expr, A.SelectOp):
            return [
                v for v in _seq(self.eval(expr.base, env)) if self._apply_body(expr.body, [v], env)
            ]
        if isinstance(expr, A.BodyExpr):
            return Closure(expr, env)
        if isinstance(expr, (A.AllOf, A.MetadataAccess)):
            raise EvaluationError(f"expression form {type(expr).__name__} is not executable")
        raise EvaluationError(f"cannot evaluate {expr!r}")

    def _member_value(self, value: Any, name: str, env: Env) -> Any:
        if isinstance(value, Instance):
            if name in value.slots:
                return value.slots[name]
            raise EvaluationError(f"instance of {value.type_name} has no feature {name!r}")
        if isinstance(value, list):
            return [self._member_value(v, name, env) for v in value]
        if isinstance(value, TypeValue):
            member = self.resolver._member(value.definition, name)
            if member is None:
                raise EvaluationError(f"{value.definition.label} has no member {name!r}")
            return self._element_value(member, env)
        if isinstance(value, EnumValue):
            raise EvaluationError(f"cannot access {name!r} on enum value {value}")
        raise EvaluationError(f"cannot access member {name!r} of {value!r}")

    def _unary(self, op: str, operand: Any) -> Any:
        if op == "not":
            return not operand
        if op == "-":
            return -operand
        if op == "+":
            return operand
        raise EvaluationError(f"unary operator {op!r} not supported")

    def _binary(self, expr: A.Binary, env: Env) -> Any:
        op = expr.op
        if op in ("and", "or", "implies", "??"):
            left = self.eval(expr.left, env)
            if op == "and":
                return self.eval(expr.right, env) if left else left
            if op == "or":
                return left if left else self.eval(expr.right, env)
            if op == "implies":
                return True if not left else bool(self.eval(expr.right, env))
            return left if left is not None else self.eval(expr.right, env)
        left = self.eval(expr.left, env)
        right = self.eval(expr.right, env)
        try:
            if op == "+":
                if isinstance(left, list) or isinstance(right, list):
                    return _seq(left) + _seq(right)
                return left + right
            if op == "-":
                return left - right
            if op == "*":
                return left * right
            if op == "/":
                return left / right
            if op == "%":
                return left % right
            if op in ("**", "^"):
                return left**right
            if op == "==":
                return left == right
            if op == "!=":
                return left != right
            if op == "===":
                return left is right
            if op == "!==":
                return left is not right
            if op == "<":
                return left < right
            if op == ">":
                return left > right
            if op == "<=":
                return left <= right
            if op == ">=":
                return left >= right
            if op == "xor":
                return bool(left) != bool(right)
            if op == "|":
                return bool(left) or bool(right)
            if op == "&":
                return bool(left) and bool(right)
            if op == "..":
                if not all(isinstance(v, int) for v in (left, right)):
                    raise EvaluationError("range '..' requires integers")
                return list(range(left, right + 1))
        except TypeError as exc:
            raise EvaluationError(f"cannot apply {op!r} to {left!r} and {right!r}") from exc
        raise EvaluationError(f"binary operator {op!r} not supported")

    _PRIMITIVE_CHECKS: ClassVar[dict[str, Callable[[Any], bool]]] = {
        "Boolean": lambda v: isinstance(v, bool),
        "Integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "Natural": lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
        "Real": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        "String": lambda v: isinstance(v, str),
    }

    def _classify(self, expr: A.Classification, env: Env) -> bool:
        if expr.operand is None:
            raise EvaluationError("classification without operand is not executable")
        value = self.eval(expr.operand, env)
        type_name = expr.type[-1]
        check = self._PRIMITIVE_CHECKS.get(type_name)
        if check is not None:
            return check(value)
        try:
            target = self.resolver.resolve(expr.type, env.context)
        except ResolutionError as exc:
            raise EvaluationError(str(exc)) from exc
        if isinstance(value, Instance):
            return self._conforms(value.definition, target)
        if isinstance(value, EnumValue):
            return (target.qualified_name or target.label) == value.enum
        return False

    def _conforms(self, definition, target) -> bool:
        if definition is None:
            return False
        if definition is target:
            return True
        for general in self.resolver._generals(definition):
            if self._conforms(general, target):
                return True
        return False

    def _cast(self, expr: A.Cast, env: Env) -> Any:
        if expr.operand is None:
            raise EvaluationError("cast without operand is not executable")
        value = self.eval(expr.operand, env)
        type_name = expr.type[-1]
        if type_name in ("Integer", "Natural"):
            return int(value)
        if type_name == "Real":
            return float(value)
        if type_name == "String":
            return str(value)
        if type_name == "Boolean":
            return bool(value)
        return value  # instance casts are identity when they conform

    def _invoke(self, expr: A.Invocation, env: Env) -> Any:
        name = expr.target
        args = [self.eval(a, env) for a in expr.args]
        named = {n: self.eval(e, env) for n, e in expr.named}
        if len(name) == 1 and name[0] in BUILTINS and _is_shadow_free(env, name[0]):
            return BUILTINS[name[0]](*args, **named)
        try:
            target = env.lookup(name[0])
            for part in name[1:]:
                target = self._member_value(target, part, env)
        except EvaluationError:
            if len(name) == 1 and name[0] in BUILTINS:
                return BUILTINS[name[0]](*args, **named)
            raise
        if callable(target):
            return target(*args, **named)
        if isinstance(target, TypeValue):
            defn = target.definition
            if isinstance(defn, (M.Definition, M.Usage)) and defn.kind in ("calc", "constraint"):
                return self._call_calc(defn, args, named)
            return self._construct_from(defn, args, named)
        raise EvaluationError(f"{'::'.join(name)} is not callable")

    def _construct(
        self, type_name: tuple[str, ...], args: list[Any], named: dict[str, Any], env: Env
    ) -> Any:
        args = [self.eval(a, env) if isinstance(a, A.Expr) else a for a in args]
        named = {n: (self.eval(e, env) if isinstance(e, A.Expr) else e) for n, e in named.items()}
        try:
            defn = self.resolver.resolve(type_name, env.context)
        except ResolutionError as exc:
            raise EvaluationError(str(exc)) from exc
        return self._construct_from(defn, args, named)

    def _construct_from(self, defn, args: list[Any], named: dict[str, Any]) -> Instance:
        bindings = dict(named)
        if args:
            attrs = [
                (m.name, m)
                for m in self.resolver.members_of(defn)
                if isinstance(m, M.Usage) and m.kind == "attribute" and m.name is not None
            ]
            if len(args) > len(attrs):
                raise EvaluationError(f"too many positional arguments for {defn.label}")
            for (attr_name, _), value in zip(attrs, args, strict=False):
                bindings[attr_name] = value
        return self._instantiate(defn, bindings)

    def _arrow(self, expr: A.ArrowOp, env: Env) -> Any:
        seq = _seq(self.eval(expr.base, env))
        name = expr.name[-1]
        if expr.body is not None:
            body = expr.body
            if name == "collect":
                return [self._apply_body(body, [v], env) for v in seq]
            if name == "select":
                return [v for v in seq if self._apply_body(body, [v], env)]
            if name == "reject":
                return [v for v in seq if not self._apply_body(body, [v], env)]
            if name == "forAll":
                return all(self._apply_body(body, [v], env) for v in seq)
            if name == "exists":
                return any(self._apply_body(body, [v], env) for v in seq)
            if name == "reduce":
                if not seq:
                    return None
                acc = seq[0]
                for v in seq[1:]:
                    acc = self._apply_body(body, [acc, v], env)
                return acc
            raise EvaluationError(f"->{name} with a body is not supported")
        if expr.func is not None:
            fn_name = expr.func[-1]
            if name == "reduce" and fn_name in BUILTINS:
                fn = BUILTINS[fn_name]
                if not seq:
                    return None
                acc = seq[0]
                for v in seq[1:]:
                    acc = fn(acc, v)
                return acc
            raise EvaluationError(f"->{name} {fn_name} is not supported")
        args = [self.eval(a, env) for a in expr.args]
        if name == "includes":
            return args[0] in seq
        if name == "excludes":
            return args[0] not in seq
        if name == "at":
            return seq[args[0] - 1]
        if name in _ARROW_OPS:
            return _ARROW_OPS[name](seq, *args)
        raise EvaluationError(f"collection operator ->{name} is not supported")

    def _apply_body(self, body: A.BodyExpr, args: list[Any], env: Env) -> Any:
        frame: dict[str, Any] = {}
        for param, value in zip(body.params, args, strict=False):
            frame[param.name] = value
        local = env.child(frame)
        for let_name, let_expr in body.lets:
            local.bind(let_name, self.eval(let_expr, local))
        if body.result is None:
            raise EvaluationError("body expression has no result")
        return self.eval(body.result, local)

    # -- calc execution -------------------------------------------------------------

    def _call_calc(self, calc, args: list[Any], named: dict[str, Any]) -> Any:
        if not isinstance(calc, (M.Definition, M.Usage)):
            raise EvaluationError(f"{calc!r} is not callable")
        members = self.resolver.members_of(calc)
        params = _named_usages(members, ("in", "inout"))
        frame: dict[str, Any] = {}
        env = Env(self, calc, [frame])
        if len(args) > len(params):
            raise EvaluationError(f"{calc.label} takes {len(params)} parameters, got {len(args)}")
        for (param_name, _), value in zip(params, args, strict=False):
            frame[param_name] = value
        for name, value in named.items():
            if not any(param_name == name for param_name, _ in params):
                raise EvaluationError(f"{calc.label} has no parameter {name!r}")
            frame[name] = value
        for param_name, param in params:
            if param_name not in frame:
                if param.value is None:
                    raise EvaluationError(
                        f"missing argument for parameter {param_name!r} of {calc.label}"
                    )
                frame[param_name] = self.eval(param.value.expr, env)
        # bind valued locals (calc usages / attributes), then the result
        return_expr: A.Expr | None = None
        for member in members:
            if not isinstance(member, M.Usage):
                continue
            if member.direction == "return":
                if member.value is not None and return_expr is None:
                    return_expr = member.value.expr
                continue
            if member.name is None or member.direction in ("in", "inout"):
                continue
            if member.value is not None:
                frame[member.name] = self.eval(member.value.expr, env)
        result_expr = calc.result if calc.result is not None else return_expr
        if result_expr is None:
            raise EvaluationError(f"{calc.label} has no result expression")
        return self.eval(result_expr, env)

    # -- instantiation -----------------------------------------------------------------

    #: usage kinds that never materialize as instance slots
    _NON_SLOT_KINDS = frozenset(
        "constraint action state requirement concern case analysis "
        "verification use_case view viewpoint rendering objective subject "
        "actor stakeholder connection binding event metadata interface "
        "allocation flow message render satisfy verify frame include".split()
    )

    def _instantiate(
        self, defn, bindings: dict[str, Any], _depth: int = 0, _active: tuple[int, ...] = ()
    ) -> Instance:
        if _depth > 32:
            raise EvaluationError(
                "instantiation recursion limit exceeded (cyclic part composition?)"
            )
        _active = (*_active, id(defn))
        instance = Instance(defn.qualified_name or defn.label, defn)
        members = [
            m
            for m in self.resolver.members_of(defn)
            if isinstance(m, M.Usage) and m.kind not in self._NON_SLOT_KINDS and not m.is_abstract
        ]
        pending: dict[str, M.Usage] = {}
        for member in members:
            name = member.name or (
                member.redefines[0].split("::")[-1] if member.redefines else None
            )
            if name is None or name in instance.slots or name in pending:
                continue
            pending[name] = member

        # first pass: explicit bindings
        for name, value in bindings.items():
            if name not in pending:
                raise EvaluationError(f"{defn.label} has no feature {name!r} to bind")
            instance.slots[name] = value

        # second pass: evaluate remaining features (attributes lazily to allow
        # cross-references)
        in_progress: set = set()

        def materialize(name: str) -> Any:
            if name in instance.slots:
                return instance.slots[name]
            member = pending.get(name)
            if member is None:
                raise EvaluationError(f"{defn.label} has no feature {name!r}")
            if name in in_progress:
                raise EvaluationError(f"cyclic value dependency on {name!r} in {defn.label}")
            in_progress.add(name)
            try:
                value = compute(member)
            except EvaluationError:
                if member.owner is defn:
                    raise  # errors in the definition's own features surface
                value = None  # inherited (library) defaults degrade gracefully
            finally:
                in_progress.discard(name)
            instance.slots[name] = value
            return value

        lazy_env = Env(self, defn, [_LazyFrame(materialize, pending)], instance=instance)

        def compute(member: M.Usage) -> Any:
            if member.value is not None:
                return self.eval(member.value.expr, lazy_env)
            if member.kind in ("part", "item", "occurrence") and member.types:
                try:
                    target = self.resolver.resolve(member.types[0], member.owner or defn)
                except ResolutionError:
                    return None
                if id(target) in _active:
                    return None  # self-referential composition (Part in Part)
                count = self._instance_count(member, lazy_env)
                overrides = self._inline_overrides(member, lazy_env)
                if count is None:
                    return self._instantiate(target, overrides, _depth + 1, _active)
                return [
                    self._instantiate(target, overrides, _depth + 1, _active) for _ in range(count)
                ]
            if member.kind in ("part", "item") and member.members:
                return self._instantiate(member, {}, _depth + 1, _active)
            return None

        for name in list(pending):
            if name not in instance.slots:
                materialize(name)
        return instance

    def _instance_count(self, member: M.Usage, env: Env) -> int | None:
        """How many nested instances to create.

        ``None`` means a single instance (no multiplicity given).  Exact
        bounds (``[4]``) expand fully; ranges (``[0..*]``, ``[1..8]``)
        populate their *lower* bound -- which also keeps self-referential
        library compositions (``Part`` containing ``Part[0..*]``) finite.
        """

        mult = member.multiplicity
        if mult is None or mult.upper is None:
            return None
        try:
            upper = self.eval(mult.upper, env)
            lower = self.eval(mult.lower, env) if mult.lower is not None else upper
        except EvaluationError:
            return 0
        if isinstance(upper, int) and isinstance(lower, int) and lower == upper:
            return upper
        if isinstance(lower, int):
            return lower
        return 0

    def _inline_overrides(self, member: M.Usage, env: Env) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        for sub in member.members:
            if isinstance(sub, M.Usage) and sub.value is not None:
                name = sub.name or (sub.redefines[0].split("::")[-1] if sub.redefines else None)
                if name:
                    overrides[name] = self.eval(sub.value.expr, env)
        return overrides

    # -- constraints ----------------------------------------------------------------------

    def _constraint_expr(self, usage: M.Usage) -> A.Expr | None:
        if usage.result is not None:
            return usage.result
        for name in usage.types + usage.subsets:
            try:
                target = self.resolver.resolve(name, usage.owner or self.model)
            except ResolutionError:
                continue
            if isinstance(target, (M.Definition, M.Usage)) and target.result is not None:
                return target.result
        return None

    def _check_constraint(self, usage: M.Usage, env: Env) -> ConstraintResult:
        kind = usage.constraint_kind or "constraint"
        name = (
            usage.name
            or usage.short_name
            or (usage.subsets[0] if usage.subsets else "<constraint>")
        )
        expr = self._constraint_expr(usage)
        if expr is None:
            return ConstraintResult(name, kind, None, "", "no evaluable expression")
        try:
            value = bool(self.eval(expr, env.child()))
        except EvaluationError as exc:
            return ConstraintResult(name, kind, None, expr.to_text(), str(exc))
        if usage.is_negated:
            value = not value
        return ConstraintResult(name, kind, value, expr.to_text())


class _LazyFrame(dict):
    """Env frame that materializes instance features on demand."""

    def __init__(self, materialize, pending):
        super().__init__()
        self._materialize = materialize
        self._pending = pending

    def __contains__(self, key) -> bool:
        return dict.__contains__(self, key) or key in self._pending

    def __getitem__(self, key):
        if dict.__contains__(self, key):
            return dict.__getitem__(self, key)
        if key in self._pending:
            return self._materialize(key)
        raise KeyError(key)


def _is_shadow_free(env: Env, name: str) -> bool:
    for frame in env.frames:
        if name in frame:
            return False
    if env.instance is not None and name in env.instance.slots:
        return False
    return True


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------


class _ActionExecutor:
    #: observer hook (see sysml2.replay): called as ``on_step(index,
    #: element, phase)`` around every *named* action step (see
    #: :func:`_is_named_step`) -- phase ``"enter"`` with the step's
    #: ordinal (counted from 0 across the whole run), then
    #: ``"complete"`` with the ordinal the *next* step would get.
    #: Class-level defaults keep the bare instances built by
    #: ``StateMachine._run_statement`` (via ``__new__``) safe.
    on_step: Callable[[int, M.Element, str], None] | None = None
    _step_index: int = 0

    def __init__(
        self,
        interpreter: Interpreter,
        action: M.Definition | M.Usage,
        inputs: dict[str, Any],
        events: deque,
        parent_env: Env | None = None,
    ):
        self.interp = interpreter
        self.action = action
        self.events = events
        self.sends: list[SentEvent] = []
        self.trace: list[str] = []
        self.terminated = False
        members = interpreter.resolver.members_of(action)
        self.params = _named_usages(members, ("in", "out", "inout"))
        frame: dict[str, Any] = {}
        outer = parent_env.frames if parent_env is not None else []
        self.env = Env(interpreter, action, [frame, *outer])
        for name, param in self.params:
            if param.direction in ("in", "inout"):
                if name in inputs:
                    frame[name] = inputs[name]
                elif param.value is not None:
                    frame[name] = interpreter.eval(param.value.expr, self.env)
                else:
                    raise ExecutionError(f"missing input {name!r} for {action.label}")
            else:
                frame[name] = inputs.get(name)
        unknown = set(inputs) - {name for name, _ in self.params}
        if unknown:
            raise ExecutionError(f"unknown input(s) {sorted(unknown)} for {action.label}")
        self.members = members
        self.clock = 0.0

    def run(self) -> ActionResult:
        plan = _succession_plan(self.members)
        if plan is not None:
            self.run_graph(plan)
        else:
            self.execute_items(self.members)
        outputs = {
            name: self.env.lookup(name)
            for name, p in self.params
            if p.direction in ("out", "inout")
        }
        return ActionResult(
            outputs=outputs,
            sends=self.sends,
            trace=self.trace,
            env=dict(self.env.frames[0]),
            terminated=self.terminated,
            time=self.clock,
        )

    # -- succession-graph execution ------------------------------------------

    def run_graph(self, plan: _SuccessionPlan) -> None:
        # declarations and value bindings first, in declaration order
        for member in self.members:
            if isinstance(member, (M.Succession, M.InitialNode)):
                continue
            if isinstance(member, M.Usage) and member.name in plan.steps:
                continue
            if id(member) in plan.step_ids:
                continue
            self.execute(member)
        current = plan.initial
        for _ in range(_MAX_LOOP_ITERATIONS):
            if current is None or current == "done" or self.terminated:
                return
            node = plan.steps.get(current)
            if node is None:
                raise ExecutionError(f"succession targets unknown step {current!r}")
            if isinstance(node, M.ControlNode) and node.kind == "fork":
                current = self._run_fork(current, plan)
                continue
            if not isinstance(node, M.ControlNode):
                self.trace.append(f"step {current}")
                self.execute(node)
            current = self._next_step(current, plan)
        raise ExecutionError("action exceeded step limit")

    def _next_step(self, current: str, plan: _SuccessionPlan) -> str | None:
        outgoing = [e for e in plan.edges if e.source == current]
        if not outgoing:
            return None
        for edge in outgoing:
            if edge.guard is not None and self.interp.eval(edge.guard, self.env):
                return edge.target
        for edge in outgoing:
            if edge.is_else:
                return edge.target
        for edge in outgoing:
            if edge.guard is None and not edge.is_else:
                return edge.target
        self.trace.append(f"no successor guard satisfied after {current}")
        return None

    def _run_fork(self, fork_name: str, plan: _SuccessionPlan) -> str | None:
        self.trace.append(f"fork {fork_name}")
        join: str | None = None
        for edge in [e for e in plan.edges if e.source == fork_name]:
            branch: str | None = edge.target
            for _ in range(_MAX_LOOP_ITERATIONS):
                if branch is None or branch == "done" or self.terminated:
                    break
                node = plan.steps.get(branch)
                if node is None:
                    raise ExecutionError(f"succession targets unknown step {branch!r}")
                if isinstance(node, M.ControlNode) and node.kind == "join":
                    join = branch
                    break
                if not isinstance(node, M.ControlNode):
                    self.trace.append(f"step {branch}")
                    self.execute(node)
                branch = self._next_step(branch, plan)
        if join is None:
            return None
        self.trace.append(f"join {join}")
        return self._next_step(join, plan)

    def execute_items(self, items: list[M.Element]) -> None:
        for item in items:
            if self.terminated:
                return
            self.execute(item)

    def execute(self, item: M.Element) -> None:
        hook = self.on_step
        if hook is None or not _is_named_step(item):
            self._execute(item)
            return
        index = self._step_index
        self._step_index = index + 1
        hook(index, item, "enter")
        try:
            self._execute(item)
        finally:
            hook(self._step_index, item, "complete")

    def _execute(self, item: M.Element) -> None:
        interp = self.interp
        if isinstance(item, M.AssignmentAction):
            value = interp.eval(item.expr, self.env)
            self.env.assign(item.target, value)
            self.trace.append(f"assign {item.target} := {value!r}")
            return
        if isinstance(item, M.IfAction):
            branch_taken = bool(interp.eval(item.condition, self.env))
            self.trace.append(f"if {item.condition.to_text()} -> {branch_taken}")
            if branch_taken:
                self.execute_items(item.then_body)
            elif isinstance(item.else_body, M.IfAction):
                self.execute(item.else_body)
            elif item.else_body:
                self.execute_items(item.else_body)
            return
        if isinstance(item, M.WhileLoop):
            iterations = 0
            while not self.terminated:
                if item.condition is not None and not interp.eval(item.condition, self.env):
                    break
                self.execute_items(item.body)
                iterations += 1
                if item.until is not None and interp.eval(item.until, self.env):
                    break
                if iterations > _MAX_LOOP_ITERATIONS:
                    raise ExecutionError("while loop exceeded iteration limit")
            self.trace.append(f"while: {iterations} iteration(s)")
            return
        if isinstance(item, M.ForLoop):
            seq = _seq(interp.eval(item.seq, self.env))
            for value in seq:
                if self.terminated:
                    return
                self.env.bind(item.var, value)
                self.execute_items(item.body)
            self.trace.append(f"for {item.var}: {len(seq)} iteration(s)")
            return
        if isinstance(item, M.SendAction):
            event = SentEvent(
                payload=interp.eval(item.payload, self.env),
                to=interp.eval(item.to, self.env) if item.to else None,
                via=interp.eval(item.via, self.env) if item.via else None,
            )
            self.sends.append(event)
            self.trace.append(f"send {event.payload!r}")
            return
        if isinstance(item, M.AcceptAction):
            self.accept(item)
            return
        if isinstance(item, M.PerformAction):
            self.perform(item)
            return
        if isinstance(item, M.TerminateAction):
            self.terminated = True
            self.trace.append("terminate")
            return
        if isinstance(item, M.Usage):
            if item.direction is not None:
                return  # parameters were bound during initialization
            if item.kind == "action" and (item.members or item.value):
                self.trace.append(f"action {item.label}")
                self.execute_items(list(item.members))
                return
            if item.name and item.value is not None:
                value = interp.eval(item.value.expr, self.env)
                self.env.bind(item.name, value)
                self.trace.append(f"bind {item.name} = {value!r}")
                return
        # successions / control nodes / declarations: ordering metadata only

    def accept(self, item: M.AcceptAction) -> None:
        if item.trigger_kind is not None:
            self._accept_time_trigger(item)
            return
        if not self.events:
            raise ExecutionError(
                f"accept {item.payload_name or item.payload_types}: no more events in the queue"
            )
        event = self.events.popleft()
        name, payload = _event_parts(event)
        if item.payload_types:
            wanted = {t.split("::")[-1] for t in item.payload_types}
            if name not in wanted:
                raise ExecutionError(f"accept expected one of {sorted(wanted)}, got {name!r}")
        if item.payload_name:
            self.env.bind(item.payload_name, payload if payload is not None else name)
        self.trace.append(f"accept {name}")

    def _accept_time_trigger(self, item: M.AcceptAction) -> None:
        value = self.interp.eval(item.trigger, self.env) if item.trigger is not None else 0
        if item.trigger_kind == "after":
            self.clock += value
            self.trace.append(f"wait {value} (clock={self.clock})")
        elif item.trigger_kind == "at":
            self.clock = max(self.clock, float(value))
            self.trace.append(f"wait until {value} (clock={self.clock})")
        else:  # 'when'
            if not value:
                raise ExecutionError(
                    "accept when: condition is false and no further progress is possible (deadlock)"
                )
            self.trace.append("when condition satisfied")
        if item.payload_name:
            self.env.bind(item.payload_name, self.clock)

    def perform(self, item: M.PerformAction) -> None:
        interp = self.interp
        if item.action is not None and (item.action.members or not item.action.subsets):
            self.trace.append(f"perform action {item.action.label}")
            self.execute_items(list(item.action.members))
            return
        ref = item.target or (item.action.subsets[0] if item.action else None)
        if ref is None:
            return
        try:
            target = interp.resolver.resolve(ref, self.action)
        except ResolutionError as exc:
            raise ExecutionError(str(exc)) from exc
        if not isinstance(target, (M.Definition, M.Usage)):
            raise ExecutionError(f"cannot perform {ref!r}")
        inputs = {}
        for name, _ in _named_usages(interp.resolver.members_of(target), ("in", "inout")):
            try:
                inputs[name] = self.env.lookup(name)
            except EvaluationError:
                continue
        sub = _ActionExecutor(interp, target, inputs, self.events, parent_env=self.env)
        sub.on_step = self.on_step  # nested performs keep reporting steps
        sub._step_index = self._step_index
        result = sub.run()
        self._step_index = sub._step_index
        self.sends.extend(result.sends)
        self.trace.append(f"perform {ref}")
        self.trace.extend(f"  {t}" for t in result.trace)
        for out_name, out_value in result.outputs.items():
            self.env.bind(out_name, out_value)


def _event_parts(event) -> tuple[str, Any]:
    if isinstance(event, tuple):
        return event[0], event[1]
    if isinstance(event, dict) and "name" in event:
        return event["name"], event.get("payload")
    if isinstance(event, Instance):
        return event.type_name.split("::")[-1], event
    return str(event), None


@dataclass
class _Edge:
    source: str
    target: str
    guard: A.Expr | None
    is_else: bool


@dataclass
class _SuccessionPlan:
    steps: dict[str, M.Element]
    step_ids: set[int]
    edges: list[_Edge]
    initial: str | None


_STEP_TYPES = (
    M.AssignmentAction,
    M.SendAction,
    M.AcceptAction,
    M.PerformAction,
    M.TerminateAction,
    M.IfAction,
    M.WhileLoop,
    M.ForLoop,
    M.ControlNode,
)


def _is_named_step(item: M.Element) -> bool:
    """Named action steps the ``_ActionExecutor.on_step`` observer reports.

    Mirrors what :func:`_succession_plan` collects as steps (minus control
    nodes, which are never executed): named statements and named nested
    action usages.
    """

    if item.name is None or isinstance(item, M.ControlNode):
        return False
    if isinstance(item, _STEP_TYPES):
        return True
    return (
        isinstance(item, M.Usage)
        and item.kind == "action"
        and item.direction is None
        and bool(item.members or item.value)
    )


def _succession_plan(members: list[M.Element]) -> _SuccessionPlan | None:
    """Build a control-flow graph from explicit successions.

    Returns ``None`` when the body has no (usable) successions, in which
    case execution falls back to declaration order.  A plan is usable when
    every succession endpoint is a named step (or ``start``/``done``).
    """

    steps: dict[str, M.Element] = {}
    step_ids: set[int] = set()
    edges: list[_Edge] = []
    initial: str | None = None
    for member in members:
        name = member.name
        if isinstance(member, M.Usage) and member.kind == "action" and name:
            steps[name] = member
            step_ids.add(id(member))
        elif isinstance(member, _STEP_TYPES) and name:
            steps[name] = member
            step_ids.add(id(member))
        elif isinstance(member, M.InitialNode):
            if member.target != "start":
                initial = member.target
        elif isinstance(member, M.Succession):
            if member.source is None:
                return None  # attached to an anonymous statement
            edges.append(_Edge(member.source, member.target, member.guard, member.is_else))
    if not edges and initial is None:
        return None
    known = set(steps) | {"start", "done"}
    for edge in edges:
        if edge.source not in known or edge.target not in known:
            return None
    if initial is None:
        start_edges = [e for e in edges if e.source == "start"]
        if not start_edges:
            return None
        initial = start_edges[0].target
    if initial not in set(steps) | {"done"}:
        return None
    return _SuccessionPlan(steps, step_ids, edges, initial)


# ---------------------------------------------------------------------------
# State machine simulation
# ---------------------------------------------------------------------------


class _ActiveState:
    """A node in the active-state configuration tree."""

    def __init__(
        self,
        usage: M.Usage,
        container: M.Definition | M.Usage,
        parent: _ActiveState | None,
        entered_at: float,
    ):
        self.usage = usage
        self.container = container  # namespace owning this state's transitions
        self.parent = parent
        self.entered_at = entered_at
        self.children: list[_ActiveState] = []

    @property
    def name(self) -> str:
        return self.usage.name or "<anonymous>"

    def path(self) -> str:
        parts = []
        node: _ActiveState | None = self
        while node is not None:
            parts.append(node.name)
            node = node.parent
        return ".".join(reversed(parts))

    def leaves(self) -> list[_ActiveState]:
        if not self.children:
            return [self]
        out: list[_ActiveState] = []
        for child in self.children:
            out.extend(child.leaves())
        return out


class StateMachine:
    """Hierarchical state machine execution.

    Supports nested (composite) states, ``parallel`` regions, event triggers,
    guards, effects, entry/do/exit actions, eventless and ``when``-guarded
    completion transitions, and ``after``/``at`` time triggers driven by
    :meth:`advance`.
    """

    _MAX_FIRINGS = 10_000

    def __init__(
        self, interpreter: Interpreter, definition: M.Definition | M.Usage, inputs: dict[str, Any]
    ):
        self.interp = interpreter
        self.definition = definition
        frame: dict[str, Any] = dict(inputs)
        self.env = Env(interpreter, definition, [frame])
        self.sends: list[SentEvent] = []
        self.trace: list[TransitionFired] = []
        self.ignored: list[str] = []
        self.roots: list[_ActiveState] = []
        self.now = 0.0
        self._firings = 0
        #: observer hook (see sysml2.replay): called once after start()
        #: completes the initial entry and once after each fired transition,
        #: always AFTER the active configuration has been updated
        self.on_step: Callable[[float, TransitionFired | None], None] | None = None
        for member in interpreter.resolver.members_of(definition):
            if (
                isinstance(member, M.Usage)
                and member.name
                and member.value is not None
                and member.kind not in ("state",)
            ):
                if member.name not in frame:  # inputs take precedence
                    frame[member.name] = interpreter.eval(member.value.expr, self.env)

    # -- structure queries -------------------------------------------------------

    def _members(self, container: M.Definition | M.Usage) -> list[M.Element]:
        return self.interp.resolver.members_of(container)

    def _states_of(self, container) -> dict[str, M.Usage]:
        return {
            m.name: m
            for m in self._members(container)
            if isinstance(m, M.Usage) and m.kind == "state" and m.name
        }

    def _transitions_of(self, container) -> list[M.TransitionUsage]:
        return [m for m in self._members(container) if isinstance(m, M.TransitionUsage)]

    def _initial_of(self, container) -> str | None:
        for transition in self._transitions_of(container):
            if transition.source != M.ENTRY_SOURCE:
                continue
            if transition.guard is not None and not self.interp.eval(transition.guard, self.env):
                continue
            return transition.target
        return None

    # -- lifecycle ------------------------------------------------------------------

    @property
    def current(self) -> str | None:
        """Dotted path of the first active leaf state (compatibility)."""

        if not self.roots:
            return None
        return self.roots[0].leaves()[0].path()

    def active_states(self) -> list[str]:
        return [leaf.path() for root in self.roots for leaf in root.leaves()]

    def start(self) -> None:
        self.roots = self._enter_container(self.definition, parent=None, require_entry=True)
        if self.on_step is not None:
            self.on_step(self.now, None)
        self._completion_scan()

    def _enter_container(
        self, container, parent: _ActiveState | None, require_entry: bool = False
    ) -> list[_ActiveState]:
        states = self._states_of(container)
        if not states:
            return []
        parallel = getattr(container, "is_parallel", False)
        if parallel:
            targets = list(states)
        else:
            initial = self._initial_of(container)
            if initial is None:
                if require_entry:
                    raise ExecutionError(
                        f"{container.label} has no entry transition ('entry; then <state>;')"
                    )
                return []
            targets = [initial]
        return [self._enter_state(name, container, parent) for name in targets]

    def _enter_state(self, name: str, container, parent: _ActiveState | None) -> _ActiveState:
        states = self._states_of(container)
        usage = states.get(name)
        if usage is None:
            raise ExecutionError(f"transition targets unknown state {name!r} in {container.label}")
        node = _ActiveState(usage, container, parent, self.now)
        self._run_state_actions(usage, "entry")
        self._run_state_actions(usage, "do")
        node.children = self._enter_container(usage, parent=node)
        return node

    # -- event dispatch -----------------------------------------------------------------

    def send(self, event) -> None:
        if not self.roots:
            raise ExecutionError("state machine not started")
        name, payload = _event_parts(event)
        parallel = getattr(self.definition, "is_parallel", False)
        if not self._dispatch(self.roots, parallel, name, payload):
            self.ignored.append(name)
        else:
            self._completion_scan()

    def _dispatch(self, nodes: list[_ActiveState], parallel: bool, name: str, payload: Any) -> bool:
        if not nodes:
            return False
        if parallel:
            results = [self._dispatch_node(node, name, payload) for node in list(nodes)]
            return any(results)
        return self._dispatch_node(nodes[0], name, payload)

    def _dispatch_node(self, node: _ActiveState, name: str, payload: Any) -> bool:
        # innermost states get the first chance to consume the event
        if self._dispatch(node.children, node.usage.is_parallel, name, payload):
            return True
        for transition in self._transitions_of(node.container):
            if transition.source != node.name:
                continue
            if not self._trigger_matches(transition, name):
                continue
            local = self._event_env(transition, name, payload)
            if transition.guard is not None and not self.interp.eval(transition.guard, local):
                continue
            self._fire(node, transition, name, payload)
            return True
        return False

    def _trigger_matches(self, transition: M.TransitionUsage, name: str) -> bool:
        trigger = transition.trigger
        if trigger is None or trigger.trigger_kind is not None:
            return False  # eventless / time / when triggers
        wanted = {t.split("::")[-1] for t in trigger.payload_types}
        if trigger.payload_name and not wanted:
            wanted = {trigger.payload_name}
        return name in wanted if wanted else True

    def _event_env(self, transition: M.TransitionUsage, name: str | None, payload: Any) -> Env:
        frame: dict[str, Any] = {}
        if transition.trigger is not None and transition.trigger.payload_name:
            frame[transition.trigger.payload_name] = payload if payload is not None else name
        return self.env.child(frame)

    # -- firing -------------------------------------------------------------------------

    def _fire(
        self,
        node: _ActiveState,
        transition: M.TransitionUsage,
        event_name: str | None,
        payload: Any,
    ) -> None:
        self._firings += 1
        if self._firings > self._MAX_FIRINGS:
            raise ExecutionError("state machine exceeded firing limit")
        prefix = node.parent.path() + "." if node.parent else ""
        self._exit_subtree(node)
        if transition.effect is not None:
            self._run_statement(transition.effect, self._event_env(transition, event_name, payload))
        fired = TransitionFired(
            prefix + node.name, event_name, prefix + transition.target, time=self.now
        )
        self.trace.append(fired)
        replacement = self._enter_state(transition.target, node.container, node.parent)
        siblings = node.parent.children if node.parent is not None else self.roots
        siblings[siblings.index(node)] = replacement
        if self.on_step is not None:
            self.on_step(self.now, fired)

    def _exit_subtree(self, node: _ActiveState) -> None:
        for child in reversed(node.children):
            self._exit_subtree(child)
        node.children = []
        self._run_state_actions(node.usage, "exit")

    # -- completion / time --------------------------------------------------------------

    def _completion_scan(self) -> None:
        for _ in range(100):
            if not self._fire_one_completion():
                return
        raise ExecutionError("state machine livelock: completion transitions kept firing")

    def _fire_one_completion(self) -> bool:
        for node in self._all_nodes_innermost_first():
            for transition in self._transitions_of(node.container):
                if transition.source != node.name:
                    continue
                trigger = transition.trigger
                if trigger is None:
                    pass  # plain completion transition
                elif trigger.trigger_kind == "when":
                    if trigger.trigger is None or not self.interp.eval(trigger.trigger, self.env):
                        continue
                else:
                    continue
                if transition.guard is not None and not self.interp.eval(
                    transition.guard, self.env
                ):
                    continue
                self._fire(node, transition, None, None)
                return True
        return False

    def _all_nodes_innermost_first(self) -> list[_ActiveState]:
        out: list[_ActiveState] = []

        def visit(node: _ActiveState) -> None:
            for child in node.children:
                visit(child)
            out.append(node)

        for root in list(self.roots):
            visit(root)
        return out

    def advance(self, duration: float) -> None:
        """Advance the simulation clock, firing due time-triggered
        transitions (``accept after d`` / ``accept at t``) in deadline
        order."""

        if not self.roots:
            raise ExecutionError("state machine not started")
        target_time = self.now + float(duration)
        for _ in range(self._MAX_FIRINGS):
            due = self._earliest_due(target_time)
            if due is None:
                break
            node, transition, deadline = due
            self.now = max(self.now, deadline)
            self._fire(node, transition, None, None)
            self._completion_scan()
        self.now = target_time

    def _earliest_due(self, limit: float) -> tuple[_ActiveState, M.TransitionUsage, float] | None:
        best: tuple[_ActiveState, M.TransitionUsage, float] | None = None
        for node in self._all_nodes_innermost_first():
            for transition in self._transitions_of(node.container):
                if transition.source != node.name:
                    continue
                trigger = transition.trigger
                if trigger is None or trigger.trigger_kind not in ("after", "at"):
                    continue
                if trigger.trigger is None:
                    continue
                offset = self.interp.eval(trigger.trigger, self.env)
                deadline = node.entered_at + offset if trigger.trigger_kind == "after" else offset
                if deadline > limit:
                    continue
                if transition.guard is not None and not self.interp.eval(
                    transition.guard, self.env
                ):
                    continue
                if best is None or deadline < best[2]:
                    best = (node, transition, deadline)
        return best

    # -- actions --------------------------------------------------------------------------

    def _run_state_actions(self, state: M.Usage, kind: str) -> None:
        for member in state.members:
            if (
                isinstance(member, M.StateAction)
                and member.kind == kind
                and member.action is not None
            ):
                self._run_statement(member.action, self.env)

    def _run_statement(self, statement: M.Element, env: Env) -> None:
        executor = _ActionExecutor.__new__(_ActionExecutor)
        executor.interp = self.interp
        executor.action = self.definition
        executor.events = deque()
        executor.sends = self.sends
        executor.trace = []
        executor.terminated = False
        executor.clock = self.now
        executor.env = env
        executor.execute(statement)
