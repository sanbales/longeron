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
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from . import ast as A
from . import model as M
from .errors import EvaluationError, ExecutionError, ResolutionError

# ---------------------------------------------------------------------------
# Runtime values
# ---------------------------------------------------------------------------


class Instance:
    """A runtime instance of a part/item definition (or anonymous usage)."""

    def __init__(self, type_name: str, definition=None):
        self.type_name = type_name
        self.definition = definition
        self.slots: Dict[str, Any] = {}

    def get(self, path: str) -> Any:
        node: Any = self
        for part in path.split("."):
            if isinstance(node, Instance):
                if part not in node.slots:
                    raise EvaluationError(
                        f"instance of {node.type_name} has no feature {part!r}")
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

    def to_dict(self) -> Dict[str, Any]:
        def convert(value):
            if isinstance(value, Instance):
                return value.to_dict()
            if isinstance(value, list):
                return [convert(v) for v in value]
            if isinstance(value, EnumValue):
                return str(value)
            return value

        return {"@type": self.type_name,
                **{k: convert(v) for k, v in self.slots.items()}}

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

    definition: Union[M.Definition, M.Usage]

    def __repr__(self) -> str:
        return f"<type {self.definition.qualified_name}>"


@dataclass
class Closure:
    body: A.BodyExpr
    env: "Env"


@dataclass
class SentEvent:
    payload: Any
    to: Any = None
    via: Any = None


@dataclass
class ConstraintResult:
    name: str
    kind: str  # 'constraint' | 'assume' | 'require' | 'assert'
    passed: Optional[bool]
    expression: str
    message: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return bool(self.passed)


@dataclass
class RequirementResult:
    name: str
    assumptions: List[ConstraintResult] = field(default_factory=list)
    requirements: List[ConstraintResult] = field(default_factory=list)

    @property
    def applicable(self) -> bool:
        return all(r.passed for r in self.assumptions)

    @property
    def satisfied(self) -> Optional[bool]:
        if not self.applicable:
            return None
        return all(r.passed for r in self.requirements)


@dataclass
class ActionResult:
    outputs: Dict[str, Any]
    sends: List[SentEvent]
    trace: List[str]
    env: Dict[str, Any]
    terminated: bool = False


@dataclass
class TransitionFired:
    source: str
    event: Optional[str]
    target: str

    def __repr__(self) -> str:
        return f"{self.source} --{self.event or 'auto'}--> {self.target}"


@dataclass
class SimulationResult:
    final_state: Optional[str]
    trace: List[TransitionFired]
    ignored_events: List[str]
    env: Dict[str, Any]
    sends: List[SentEvent]


# ---------------------------------------------------------------------------
# Builtin function library
# ---------------------------------------------------------------------------

def _seq(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


BUILTINS: Dict[str, Callable] = {
    "sqrt": math.sqrt, "abs": abs, "floor": math.floor, "ceil": math.ceil,
    "round": round, "exp": math.exp, "ln": math.log, "log": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin,
    "acos": math.acos, "atan": math.atan, "pow": math.pow,
    "max": lambda *a: max(_flatten(a)), "min": lambda *a: min(_flatten(a)),
    "sum": lambda *a: sum(_flatten(a)),
    "size": lambda s: len(_seq(s)),
    "ToString": lambda v: ("true" if v is True else "false" if v is False
                           else str(v)),
    "ToInteger": int, "ToReal": float, "ToNatural": int,
    "ToBoolean": lambda v: v in (True, "true", 1),
    "pi": math.pi, "e": math.e,
}


def _flatten(args):
    out = []
    for a in args:
        out.extend(_seq(a))
    return out


_ARROW_OPS: Dict[str, Callable] = {
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


class Resolver:
    def __init__(self, model: M.Model):
        self.model = model
        self._active_imports: set = set()

    def resolve(self, qname: Union[str, Tuple[str, ...]],
                context: Optional[M.Namespace] = None) -> M.Element:
        parts = list(qname.split("::") if isinstance(qname, str) else qname)
        if parts and parts[0] == "$":
            parts = parts[1:]
            context = self.model
        element = self._resolve_first(parts[0], context or self.model)
        if element is None:
            raise ResolutionError(f"cannot resolve name {parts[0]!r}"
                                  + (f" from {context.qualified_name}"
                                     if context is not None and
                                     context.qualified_name else ""))
        for part in parts[1:]:
            child = self._member(element, part)
            if child is None:
                raise ResolutionError(
                    f"{element.qualified_name or element.label} has no member "
                    f"{part!r}")
            element = child
        return element

    def _resolve_first(self, name: str, context: M.Namespace
                       ) -> Optional[M.Element]:
        node: Optional[M.Element] = context
        while node is not None:
            if isinstance(node, M.Namespace):
                found = self._member(node, name, include_imports=True)
                if found is not None:
                    return found
            node = node.owner
        # fall back to the model root
        return self._member(self.model, name, include_imports=True)

    def _member(self, element: M.Element, name: str,
                include_imports: bool = False) -> Optional[M.Element]:
        if not isinstance(element, M.Namespace):
            return None
        for member in element.members:
            if isinstance(member, M.Alias):
                continue  # matched below, by resolving the alias target
            if name in (member.name, member.short_name):
                return member
        for member in element.members:
            if isinstance(member, M.Alias) and name in (member.name,
                                                        member.short_name):
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
                key = (id(member), name)
                if key in self._active_imports:
                    continue  # break import resolution cycles
                self._active_imports.add(key)
                try:
                    if member.is_namespace:
                        target = self.resolve(member.target, element)
                        found = self._member(target, name)
                        if found is not None:
                            return found
                    elif member.target.split("::")[-1] == name:
                        return self.resolve(member.target, element)
                except ResolutionError:
                    continue
                finally:
                    self._active_imports.discard(key)
        return None

    def _generals(self, element: M.Element) -> List[M.Namespace]:
        names: List[str] = []
        if isinstance(element, M.Definition):
            names = element.supers
        elif isinstance(element, M.Usage):
            names = list(element.types) + list(element.subsets) + \
                list(element.redefines)
        out = []
        for name in names:
            if name.startswith("~"):
                name = name[1:]
            try:
                general = self.resolve(name, element.owner or self.model)
            except ResolutionError:
                continue
            if isinstance(general, M.Namespace):
                out.append(general)
        return out

    def members_of(self, element: M.Namespace) -> List[M.Element]:
        """Own + inherited members; redefinitions shadow inherited names."""

        collected: Dict[int, M.Element] = {}
        order: List[M.Element] = []
        shadowed: set = set()

        def visit(ns: M.Namespace) -> None:
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
            for general in self._generals(ns):
                visit(general)

        visit(element)
        return order


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


class Env:
    """Layered lookup: local frames -> instance slots -> model namespace."""

    def __init__(self, interpreter: "Interpreter",
                 context: Optional[M.Namespace],
                 frames: Optional[List[Dict[str, Any]]] = None,
                 instance: Optional[Instance] = None):
        self.interpreter = interpreter
        self.context = context
        self.frames = frames if frames is not None else [{}]
        self.instance = instance

    def child(self, frame: Optional[Dict[str, Any]] = None) -> "Env":
        return Env(self.interpreter, self.context,
                   [frame if frame is not None else {}] + self.frames,
                   self.instance)

    def bind(self, name: str, value: Any) -> None:
        self.frames[0][name] = value

    def assign(self, path: str, value: Any) -> None:
        first = path.split(".")[0]
        for frame in self.frames:
            if first in frame:
                if "." in path:
                    node = frame[first]
                    if not isinstance(node, Instance):
                        raise EvaluationError(
                            f"cannot assign into non-instance {first!r}")
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
        self._const_cache: Dict[int, Any] = {}

    # -- public API -----------------------------------------------------------

    def resolve(self, qname: str) -> M.Element:
        return self.resolver.resolve(qname)

    def evaluate(self, expr: Union[str, A.Expr],
                 context: Optional[Union[str, M.Namespace]] = None,
                 **bindings: Any) -> Any:
        """Evaluate an expression (text or AST) with optional name bindings."""

        if isinstance(expr, str):
            from .builder import parse_expression

            expr = parse_expression(expr)
        if isinstance(context, str):
            context = self.resolver.resolve(context)  # type: ignore[assignment]
        env = Env(self, context if isinstance(context, M.Namespace) else self.model,
                  [dict(bindings)])
        return self.eval(expr, env)

    def instantiate(self, definition: Union[str, M.Definition, M.Usage],
                    **bindings: Any) -> Instance:
        """Create an instance of a part/item definition, evaluating attribute
        values; ``bindings`` override attribute values by name."""

        defn = (self.resolver.resolve(definition)
                if isinstance(definition, str) else definition)
        if not isinstance(defn, (M.Definition, M.Usage)):
            raise EvaluationError(f"cannot instantiate {definition!r}")
        return self._instantiate(defn, bindings)

    def call(self, calc: Union[str, M.Definition, M.Usage], *args: Any,
             **kwargs: Any) -> Any:
        """Invoke a calc (or constraint) definition/usage as a function."""

        target = (self.resolver.resolve(calc) if isinstance(calc, str) else calc)
        return self._call_calc(target, list(args), kwargs)

    def check(self, instance: Instance) -> List[ConstraintResult]:
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

    def check_requirement(self, requirement: Union[str, M.Definition, M.Usage],
                          subject: Optional[Instance] = None,
                          **bindings: Any) -> RequirementResult:
        req = (self.resolver.resolve(requirement)
               if isinstance(requirement, str) else requirement)
        frame: Dict[str, Any] = dict(bindings)
        members = self.resolver.members_of(req)
        if subject is not None:
            subject_names = [m.name for m in members
                             if isinstance(m, M.Usage) and m.kind == "subject"
                             and m.name]
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

    def run_action(self, action: Union[str, M.Definition, M.Usage],
                   inputs: Optional[Dict[str, Any]] = None,
                   events: Optional[List[Any]] = None) -> ActionResult:
        target = (self.resolver.resolve(action)
                  if isinstance(action, str) else action)
        executor = _ActionExecutor(self, target, inputs or {},
                                   deque(events or []))
        return executor.run()

    def simulate(self, state_machine: Union[str, M.Definition, M.Usage],
                 events: Optional[List[Any]] = None,
                 inputs: Optional[Dict[str, Any]] = None,
                 max_steps: int = 1000) -> SimulationResult:
        target = (self.resolver.resolve(state_machine)
                  if isinstance(state_machine, str) else state_machine)
        sim = StateMachine(self, target, inputs or {})
        sim.start()
        for event in events or []:
            sim.send(event)
            if len(sim.trace) > max_steps:
                raise ExecutionError("state machine exceeded max_steps")
        return SimulationResult(final_state=sim.current, trace=sim.trace,
                                ignored_events=sim.ignored,
                                env=dict(sim.env.frames[0]), sends=sim.sends)

    # -- name-to-value resolution ----------------------------------------------

    def _resolve_value(self, name: str, context: Optional[M.Namespace],
                       env: Env) -> Any:
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
                return EnumValue(enum.qualified_name or enum.label, element.label)
            if element.kind in ("calc", "constraint"):
                return TypeValue(element)
            if element.value is not None:
                key = id(element)
                if key not in self._const_cache:
                    owner_env = Env(self, element.owner or self.model, [{}],
                                    instance=env.instance)
                    self._const_cache[key] = self.eval(element.value.expr,
                                                       owner_env)
                return self._const_cache[key]
            return TypeValue(element)
        if isinstance(element, (M.Definition, M.Package)):
            return TypeValue(element)
        raise EvaluationError(
            f"{element.label} ({type(element).__name__}) has no runtime value")

    # -- expression evaluation ----------------------------------------------------

    def eval(self, expr: A.Expr, env: Env) -> Any:  # noqa: C901
        if isinstance(expr, A.Literal):
            return expr.value
        if isinstance(expr, A.FeatureRef):
            value = env.lookup(expr.parts[0]) if expr.parts[0] != "$" else \
                TypeValue(self.model)
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
            out: List[Any] = []
            for item in expr.items:
                value = self.eval(item, env)
                out.extend(value) if isinstance(value, list) else out.append(value)
            return out
        if isinstance(expr, A.IndexOp):
            base = _seq(self.eval(expr.base, env))
            index = self.eval(expr.index[0], env)
            if not isinstance(index, int) or not 1 <= index <= len(base):
                raise EvaluationError(f"index {index!r} out of range "
                                      f"(sequences are 1-based)")
            return base[index - 1]
        if isinstance(expr, A.QuantityOp):
            return self.eval(expr.base, env)  # units are annotations
        if isinstance(expr, A.Invocation):
            return self._invoke(expr, env)
        if isinstance(expr, A.Constructor):
            return self._construct(expr.type, list(expr.args),
                                   dict(expr.named), env)
        if isinstance(expr, A.ArrowOp):
            return self._arrow(expr, env)
        if isinstance(expr, A.CollectOp):
            return [self._apply_body(expr.body, [v], env)
                    for v in _seq(self.eval(expr.base, env))]
        if isinstance(expr, A.SelectOp):
            return [v for v in _seq(self.eval(expr.base, env))
                    if self._apply_body(expr.body, [v], env)]
        if isinstance(expr, A.BodyExpr):
            return Closure(expr, env)
        if isinstance(expr, (A.AllOf, A.MetadataAccess)):
            raise EvaluationError(
                f"expression form {type(expr).__name__} is not executable")
        raise EvaluationError(f"cannot evaluate {expr!r}")

    def _member_value(self, value: Any, name: str, env: Env) -> Any:
        if isinstance(value, Instance):
            if name in value.slots:
                return value.slots[name]
            raise EvaluationError(
                f"instance of {value.type_name} has no feature {name!r}")
        if isinstance(value, list):
            return [self._member_value(v, name, env) for v in value]
        if isinstance(value, TypeValue):
            member = self.resolver._member(value.definition, name)
            if member is None:
                raise EvaluationError(
                    f"{value.definition.label} has no member {name!r}")
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
                return left ** right
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
            raise EvaluationError(f"cannot apply {op!r} to {left!r} and "
                                  f"{right!r}") from exc
        raise EvaluationError(f"binary operator {op!r} not supported")

    _PRIMITIVE_CHECKS = {
        "Boolean": lambda v: isinstance(v, bool),
        "Integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
        "Natural": lambda v: isinstance(v, int) and not isinstance(v, bool)
        and v >= 0,
        "Real": lambda v: isinstance(v, (int, float))
        and not isinstance(v, bool),
        "String": lambda v: isinstance(v, str),
    }

    def _classify(self, expr: A.Classification, env: Env) -> bool:
        if expr.operand is None:
            raise EvaluationError("classification without operand is not "
                                  "executable")
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
            if isinstance(defn, (M.Definition, M.Usage)) and \
                    defn.kind in ("calc", "constraint"):
                return self._call_calc(defn, args, named)
            return self._construct_from(defn, args, named)
        raise EvaluationError(f"{'::'.join(name)} is not callable")

    def _construct(self, type_name: Tuple[str, ...], args: List[Any],
                   named: Dict[str, Any], env: Env) -> Any:
        args = [self.eval(a, env) if isinstance(a, A.Expr) else a for a in args]
        named = {n: (self.eval(e, env) if isinstance(e, A.Expr) else e)
                 for n, e in named.items()}
        try:
            defn = self.resolver.resolve(type_name, env.context)
        except ResolutionError as exc:
            raise EvaluationError(str(exc)) from exc
        return self._construct_from(defn, args, named)

    def _construct_from(self, defn, args: List[Any],
                        named: Dict[str, Any]) -> Instance:
        bindings = dict(named)
        if args:
            attrs = [m for m in self.resolver.members_of(defn)
                     if isinstance(m, M.Usage) and m.kind == "attribute"
                     and m.name]
            if len(args) > len(attrs):
                raise EvaluationError(
                    f"too many positional arguments for {defn.label}")
            for attr, value in zip(attrs, args):
                bindings[attr.name] = value
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

    def _apply_body(self, body: A.BodyExpr, args: List[Any], env: Env) -> Any:
        frame: Dict[str, Any] = {}
        for param, value in zip(body.params, args):
            frame[param.name] = value
        local = env.child(frame)
        for let_name, let_expr in body.lets:
            local.bind(let_name, self.eval(let_expr, local))
        if body.result is None:
            raise EvaluationError("body expression has no result")
        return self.eval(body.result, local)

    # -- calc execution -------------------------------------------------------------

    def _call_calc(self, calc, args: List[Any], named: Dict[str, Any]) -> Any:
        if not isinstance(calc, (M.Definition, M.Usage)):
            raise EvaluationError(f"{calc!r} is not callable")
        members = self.resolver.members_of(calc)
        params = [m for m in members if isinstance(m, M.Usage)
                  and m.direction in ("in", "inout")]
        frame: Dict[str, Any] = {}
        env = Env(self, calc, [frame])
        if len(args) > len(params):
            raise EvaluationError(f"{calc.label} takes {len(params)} "
                                  f"parameters, got {len(args)}")
        for param, value in zip(params, args):
            frame[param.name] = value
        for name, value in named.items():
            if not any(p.name == name for p in params):
                raise EvaluationError(f"{calc.label} has no parameter {name!r}")
            frame[name] = value
        for param in params:
            if param.name not in frame:
                if param.value is None:
                    raise EvaluationError(
                        f"missing argument for parameter {param.name!r} of "
                        f"{calc.label}")
                frame[param.name] = self.eval(param.value.expr, env)
        # bind valued locals (calc usages / attributes), then the result
        return_expr: Optional[A.Expr] = None
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
        "actor stakeholder connection binding event metadata".split())

    def _instantiate(self, defn, bindings: Dict[str, Any],
                     _depth: int = 0) -> Instance:
        if _depth > 32:
            raise EvaluationError("instantiation recursion limit exceeded "
                                  "(cyclic part composition?)")
        instance = Instance(defn.qualified_name or defn.label, defn)
        members = [m for m in self.resolver.members_of(defn)
                   if isinstance(m, M.Usage)
                   and m.kind not in self._NON_SLOT_KINDS]
        env = Env(self, defn, [{}], instance=instance)
        pending: Dict[str, M.Usage] = {}
        for member in members:
            name = member.name or (member.redefines[0].split("::")[-1]
                                   if member.redefines else None)
            if name is None or name in instance.slots or name in pending:
                continue
            pending[name] = member

        # first pass: explicit bindings
        for name, value in bindings.items():
            if name not in pending:
                raise EvaluationError(
                    f"{defn.label} has no feature {name!r} to bind")
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
                raise EvaluationError(
                    f"cyclic value dependency on {name!r} in {defn.label}")
            in_progress.add(name)
            try:
                value = compute(member)
            finally:
                in_progress.discard(name)
            instance.slots[name] = value
            return value

        lazy_env = Env(self, defn, [_LazyFrame(materialize, pending)],
                       instance=instance)

        def compute(member: M.Usage) -> Any:
            if member.value is not None:
                return self.eval(member.value.expr, lazy_env)
            if member.kind in ("part", "item", "occurrence") and member.types:
                try:
                    target = self.resolver.resolve(member.types[0], defn)
                except ResolutionError:
                    return None
                count = self._fixed_multiplicity(member, lazy_env)
                overrides = self._inline_overrides(member, lazy_env)
                if count is None:
                    return self._instantiate(target, overrides, _depth + 1)
                return [self._instantiate(target, overrides, _depth + 1)
                        for _ in range(count)]
            if member.kind in ("part", "item") and member.members:
                return self._instantiate(member, {}, _depth + 1)
            return None

        for name in list(pending):
            if name not in instance.slots:
                materialize(name)
        return instance

    def _fixed_multiplicity(self, member: M.Usage, env: Env) -> Optional[int]:
        mult = member.multiplicity
        if mult is None or mult.upper is None:
            return None
        try:
            upper = self.eval(mult.upper, env)
            lower = self.eval(mult.lower, env) if mult.lower is not None else upper
        except EvaluationError:
            return None
        if isinstance(upper, int) and isinstance(lower, int) and lower == upper:
            return upper
        return None

    def _inline_overrides(self, member: M.Usage, env: Env) -> Dict[str, Any]:
        overrides: Dict[str, Any] = {}
        for sub in member.members:
            if isinstance(sub, M.Usage) and sub.value is not None:
                name = sub.name or (sub.redefines[0].split("::")[-1]
                                    if sub.redefines else None)
                if name:
                    overrides[name] = self.eval(sub.value.expr, env)
        return overrides

    # -- constraints ----------------------------------------------------------------------

    def _constraint_expr(self, usage: M.Usage) -> Optional[A.Expr]:
        if usage.result is not None:
            return usage.result
        for name in usage.types + usage.subsets:
            try:
                target = self.resolver.resolve(name, usage.owner or self.model)
            except ResolutionError:
                continue
            if isinstance(target, (M.Definition, M.Usage)) and \
                    target.result is not None:
                return target.result
        return None

    def _check_constraint(self, usage: M.Usage, env: Env) -> ConstraintResult:
        kind = usage.constraint_kind or "constraint"
        name = usage.name or usage.short_name or (
            usage.subsets[0] if usage.subsets else "<constraint>")
        expr = self._constraint_expr(usage)
        if expr is None:
            return ConstraintResult(name, kind, None, "",
                                    "no evaluable expression")
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
    def __init__(self, interpreter: Interpreter, action,
                 inputs: Dict[str, Any], events: deque,
                 parent_env: Optional[Env] = None):
        self.interp = interpreter
        self.action = action
        self.events = events
        self.sends: List[SentEvent] = []
        self.trace: List[str] = []
        self.terminated = False
        members = interpreter.resolver.members_of(action)
        self.params = [m for m in members if isinstance(m, M.Usage)
                       and m.direction in ("in", "out", "inout")]
        frame: Dict[str, Any] = {}
        outer = parent_env.frames if parent_env is not None else []
        self.env = Env(interpreter, action, [frame] + outer)
        for param in self.params:
            if param.direction in ("in", "inout"):
                if param.name in inputs:
                    frame[param.name] = inputs[param.name]
                elif param.value is not None:
                    frame[param.name] = interpreter.eval(param.value.expr,
                                                         self.env)
                else:
                    raise ExecutionError(
                        f"missing input {param.name!r} for {action.label}")
            else:
                frame[param.name] = inputs.get(param.name)
        unknown = set(inputs) - {p.name for p in self.params}
        if unknown:
            raise ExecutionError(
                f"unknown input(s) {sorted(unknown)} for {action.label}")
        self.members = members

    def run(self) -> ActionResult:
        self.execute_items(self.members)
        outputs = {p.name: self.env.lookup(p.name) for p in self.params
                   if p.direction in ("out", "inout")}
        return ActionResult(outputs=outputs, sends=self.sends,
                            trace=self.trace, env=dict(self.env.frames[0]),
                            terminated=self.terminated)

    def execute_items(self, items: List[M.Element]) -> None:
        for item in items:
            if self.terminated:
                return
            self.execute(item)

    def execute(self, item: M.Element) -> None:  # noqa: C901
        interp = self.interp
        if isinstance(item, M.AssignmentAction):
            value = interp.eval(item.expr, self.env)
            self.env.assign(item.target, value)
            self.trace.append(f"assign {item.target} := {value!r}")
            return
        if isinstance(item, M.IfAction):
            branch_taken = bool(interp.eval(item.condition, self.env))
            self.trace.append(f"if {item.condition.to_text()} -> "
                              f"{branch_taken}")
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
                if item.condition is not None and \
                        not interp.eval(item.condition, self.env):
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
                via=interp.eval(item.via, self.env) if item.via else None)
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
        if not self.events:
            raise ExecutionError(
                f"accept {item.payload_name or item.payload_types}: no more "
                f"events in the queue")
        event = self.events.popleft()
        name, payload = _event_parts(event)
        if item.payload_types:
            wanted = {t.split("::")[-1] for t in item.payload_types}
            if name not in wanted:
                raise ExecutionError(
                    f"accept expected one of {sorted(wanted)}, got {name!r}")
        if item.payload_name:
            self.env.bind(item.payload_name, payload if payload is not None
                          else name)
        self.trace.append(f"accept {name}")

    def perform(self, item: M.PerformAction) -> None:
        interp = self.interp
        target = None
        if item.action is not None and (item.action.members or
                                        not item.action.subsets):
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
        inputs = {}
        for member in interp.resolver.members_of(target):
            if isinstance(member, M.Usage) and \
                    member.direction in ("in", "inout") and member.name:
                try:
                    inputs[member.name] = self.env.lookup(member.name)
                except EvaluationError:
                    continue
        sub = _ActionExecutor(interp, target, inputs, self.events,
                              parent_env=self.env)
        result = sub.run()
        self.sends.extend(result.sends)
        self.trace.append(f"perform {ref}")
        self.trace.extend(f"  {t}" for t in result.trace)
        for out_name, out_value in result.outputs.items():
            self.env.bind(out_name, out_value)


def _event_parts(event) -> Tuple[str, Any]:
    if isinstance(event, tuple):
        return event[0], event[1]
    if isinstance(event, dict) and "name" in event:
        return event["name"], event.get("payload")
    if isinstance(event, Instance):
        return event.type_name.split("::")[-1], event
    return str(event), None


# ---------------------------------------------------------------------------
# State machine simulation
# ---------------------------------------------------------------------------


class StateMachine:
    def __init__(self, interpreter: Interpreter, definition,
                 inputs: Dict[str, Any]):
        self.interp = interpreter
        self.definition = definition
        members = interpreter.resolver.members_of(definition)
        self.states: Dict[str, M.Usage] = {}
        self.transitions: List[M.TransitionUsage] = []
        self.initial: Optional[str] = None
        frame: Dict[str, Any] = dict(inputs)
        self.env = Env(interpreter, definition, [frame])
        self.sends: List[SentEvent] = []
        self.trace: List[TransitionFired] = []
        self.ignored: List[str] = []
        self.current: Optional[str] = None

        for member in members:
            if isinstance(member, M.Usage) and member.kind == "state" \
                    and member.name:
                self.states[member.name] = member
                self._collect_nested(member)
            elif isinstance(member, M.TransitionUsage):
                if member.source == M.ENTRY_SOURCE:
                    if self.initial is None:
                        self.initial = member.target
                else:
                    self.transitions.append(member)
            elif isinstance(member, M.Usage) and member.name and \
                    member.value is not None:
                if member.name not in frame:  # inputs take precedence
                    frame[member.name] = interpreter.eval(member.value.expr,
                                                          self.env)

    def _collect_nested(self, state: M.Usage) -> None:
        for member in state.members:
            if isinstance(member, M.TransitionUsage) and \
                    member.source != M.ENTRY_SOURCE:
                self.transitions.append(member)

    # -- lifecycle -------------------------------------------------------------

    def start(self) -> None:
        if self.initial is None:
            raise ExecutionError(
                f"{self.definition.label} has no entry transition "
                f"('entry; then <state>;')")
        self._enter(self.initial)

    def send(self, event) -> None:
        if self.current is None:
            raise ExecutionError("state machine not started")
        name, payload = _event_parts(event)
        for transition in self.transitions:
            if transition.source != self.current:
                continue
            if not self._trigger_matches(transition, name):
                continue
            local = self._event_env(transition, name, payload)
            if transition.guard is not None and \
                    not self.interp.eval(transition.guard, local):
                continue
            self._fire(transition, name, payload)
            return
        self.ignored.append(name)

    def _event_env(self, transition: M.TransitionUsage, name: str,
                   payload: Any) -> Env:
        frame: Dict[str, Any] = {}
        if transition.trigger is not None and transition.trigger.payload_name:
            frame[transition.trigger.payload_name] = (
                payload if payload is not None else name)
        return self.env.child(frame)

    def _trigger_matches(self, transition: M.TransitionUsage,
                         name: str) -> bool:
        trigger = transition.trigger
        if trigger is None:
            return False
        wanted = {t.split("::")[-1] for t in trigger.payload_types}
        if trigger.payload_name and not wanted:
            wanted = {trigger.payload_name}
        return name in wanted if wanted else True

    def _fire(self, transition: M.TransitionUsage, event_name: Optional[str],
              payload: Any) -> None:
        source = transition.source or self.current
        self._run_state_actions(self.current, "exit")
        if transition.effect is not None:
            self._run_statement(transition.effect,
                                self._event_env(transition, event_name or "",
                                                payload))
        self.trace.append(TransitionFired(source, event_name,
                                          transition.target))
        self._enter(transition.target)

    def _enter(self, state_name: str) -> None:
        self.current = state_name
        self._run_state_actions(state_name, "entry")
        self._run_state_actions(state_name, "do")
        # eventless (completion) transitions
        for _ in range(100):
            fired = False
            for transition in self.transitions:
                if transition.source != self.current:
                    continue
                if transition.trigger is not None:
                    continue
                if transition.guard is not None and \
                        not self.interp.eval(transition.guard, self.env):
                    continue
                self._fire(transition, None, None)
                fired = True
                break
            if not fired:
                return
        raise ExecutionError("state machine livelock: eventless transitions "
                             "kept firing")

    def _run_state_actions(self, state_name: Optional[str],
                           kind: str) -> None:
        state = self.states.get(state_name or "")
        if state is None:
            return
        for member in state.members:
            if isinstance(member, M.StateAction) and member.kind == kind \
                    and member.action is not None:
                self._run_statement(member.action, self.env)

    def _run_statement(self, statement: M.Element, env: Env) -> None:
        executor = _ActionExecutor.__new__(_ActionExecutor)
        executor.interp = self.interp
        executor.action = self.definition
        executor.events = deque()
        executor.sends = self.sends
        executor.trace = []
        executor.terminated = False
        executor.env = env
        executor.execute(statement)
