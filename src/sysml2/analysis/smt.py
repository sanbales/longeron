"""Requirement consistency and design-space bounds on Z3 (spike).

Complements :mod:`sysml2.analysis.trades` (discrete architecture selection,
CP-SAT): Z3 works over *unbounded reals*, so it answers questions CP-SAT's
scaled integers cannot -- is a requirement set consistent at all, WHICH
requirements conflict (unsat cores), and what are exact feasibility bounds
of a continuous attribute (``z3.Optimize`` handles strict inequalities by
reporting suprema).

Mapping: scalar attributes of an instantiated part tree -> Z3 ``Real`` /
``Int`` / ``Bool`` consts named by dotted path; attribute value expressions
-> equality assertions (omit paths listed in ``free``); ``assert
constraint`` bodies and requirement ``assume``/``require`` bodies -> labeled
assertions; ``calc`` invocations are inlined by substitution.  Sequences,
strings, state machines, and ``->`` collection operators are out of scope
(recorded in ``gaps``).

Requires the ``smt`` extra: ``pip install "longeron[smt]"``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import ast as A
from .. import model as M
from ..errors import EvaluationError, ResolutionError
from ..interpreter import Instance, Interpreter
from ._expr import AnalysisError, QName, constraint_expr, is_scalar, named_members

__all__ = ["SmtResult", "SmtSystem", "to_smt"]


def _z3() -> Any:
    try:
        import z3
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "sysml2.analysis.smt needs Z3; install the extra with "
            "'pip install \"longeron[smt]\"'") from err
    return z3


@dataclass
class SmtResult:
    status: str  # 'sat' | 'unsat' | 'unknown'
    witness: dict[str, float | bool] = field(default_factory=dict)
    core: list[str] = field(default_factory=list)  # unsat only


@dataclass
class SmtSystem:
    """Z3 variables + labeled assertions for one part tree."""

    variables: dict[str, Any] = field(default_factory=dict)  # path -> const
    assertions: list[tuple[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    def check(self, exclude: tuple[str, ...] = ()) -> SmtResult:
        """SAT + witness, or UNSAT + a labeled conflict core."""

        z3 = _z3()
        solver = z3.Solver()
        tracked = {}
        for label, expr in self.assertions:
            if label in exclude:
                continue
            lit = z3.Bool(f"track!{label}")
            tracked[lit] = label
            solver.assert_and_track(expr, lit)
        status = str(solver.check())
        if status == "sat":
            return SmtResult("sat", witness=self._witness(solver.model()))
        if status == "unsat":
            labels = [tracked[lit] for lit in solver.unsat_core()]
            return SmtResult("unsat", core=sorted(labels))
        return SmtResult(status)

    def maximize(self, path: str,
                 exclude: tuple[str, ...] = ()) -> tuple[str, SmtResult]:
        """Supremum of a variable over the feasible region (exact, as text).

        Strict inequalities yield open bounds: Z3 reports the supremum with
        an infinitesimal (e.g. ``2865/1090 + -1*epsilon``).
        """

        z3 = _z3()
        opt = z3.Optimize()
        for label, expr in self.assertions:
            if label not in exclude:
                opt.add(expr)
        handle = opt.maximize(self.variables[path])
        status = str(opt.check())
        if status != "sat":
            return "", SmtResult(status)
        return str(opt.upper(handle)), SmtResult(
            "sat", witness=self._witness(opt.model()))

    def _witness(self, model: Any) -> dict[str, float | bool]:
        out: dict[str, float | bool] = {}
        for path, const in self.variables.items():
            value = model.eval(const, model_completion=True)
            if hasattr(value, "as_fraction"):
                out[path] = float(value.as_fraction())
            elif str(value) in ("True", "False"):
                out[path] = str(value) == "True"
            else:
                try:
                    out[path] = float(str(value))
                except ValueError:
                    continue
        return out


# ---------------------------------------------------------------------------
# building
# ---------------------------------------------------------------------------

_TYPE_SORTS = {"Real": "real", "Integer": "int", "Natural": "int",
               "Boolean": "bool"}


def to_smt(model: M.Model, part: str | M.Definition | M.Usage,
           requirements: tuple[str, ...] = (),
           free: tuple[str, ...] = ()) -> SmtSystem:
    """Encode a part definition's tree (and requirements) for Z3."""

    interp = Interpreter(model)
    target = interp.resolve(part) if isinstance(part, str) else part
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{part!r} is not a part definition")
    instance = interp.instantiate(target)
    system = SmtSystem()
    builder = _Builder(interp, system, frozenset(free))
    builder.tree(target, instance, prefix="")
    for req_name in requirements:
        builder.requirement(req_name)
    return system


class _Builder:
    def __init__(self, interp: Interpreter, system: SmtSystem,
                 free: frozenset[str]):
        self.z3 = _z3()
        self.interp = interp
        self.system = system
        self.free = free

    def tree(self, defn: M.Definition | M.Usage, instance: Instance,
             prefix: str) -> None:
        for attr in named_members(self.interp, defn, ("attribute",)):
            name = attr.name or attr.short_name
            assert name is not None
            path = f"{prefix}{name}"
            slot = instance.slots.get(name)
            const = self._declare(path, attr, slot)
            if const is None:
                continue
            if path in self.free:
                continue
            expr = attr.value.expr if attr.value is not None else None
            if expr is not None:
                try:
                    encoded = self._encode(expr, defn, prefix, {})
                    self.system.assertions.append((f"{path}.value",
                                                   const == encoded))
                    continue
                except AnalysisError as err:
                    self.system.gaps.append(f"{path}: {err}")
            if is_scalar(slot) or isinstance(slot, bool):
                self.system.assertions.append((f"{path}.value",
                                               const == slot))
        for con in named_members(self.interp, defn, ("constraint",)):
            expr = constraint_expr(self.interp, con)
            if expr is None:
                continue
            label = f"{defn.label}::{con.name or con.label}"
            try:
                encoded = self._encode(expr, defn, prefix, {})
            except AnalysisError as err:
                self.system.gaps.append(f"{label}: {err}")
                continue
            if con.is_negated:
                encoded = self.z3.Not(encoded)
            self.system.assertions.append((label, encoded))
        for name, slot in instance.slots.items():
            if isinstance(slot, Instance) and slot.definition is not None:
                self.tree(slot.definition, slot, prefix=f"{prefix}{name}.")
            elif isinstance(slot, list) and slot and \
                    isinstance(slot[0], Instance):
                for i, item in enumerate(slot):
                    if item.definition is not None:
                        self.tree(item.definition, item,
                                  prefix=f"{prefix}{name}_{i + 1}.")

    def requirement(self, req_name: str) -> None:
        req = self.interp.resolve(req_name)
        if not isinstance(req, (M.Definition, M.Usage)):
            raise AnalysisError(f"{req_name!r} is not a requirement")
        subjects = [m.name for m in self.interp.resolver.members_of(req)
                    if isinstance(m, M.Usage) and m.kind == "subject" and m.name]
        prefixes = {subjects[0]: ""} if subjects else {}
        for con in named_members(self.interp, req, ("constraint",)):
            expr = constraint_expr(self.interp, con)
            if expr is None:
                continue
            kind = con.constraint_kind or "require"
            label = f"{req.label}::{con.name or con.label} [{kind}]"
            try:
                encoded = self._encode(expr, req, "", {}, prefixes)
            except AnalysisError as err:
                self.system.gaps.append(f"{label}: {err}")
                continue
            self.system.assertions.append((label, encoded))

    def _declare(self, path: str, attr: M.Usage, slot: Any) -> Any:
        z3 = self.z3
        sort = None
        for type_name in attr.types:
            sort = _TYPE_SORTS.get(type_name.split("::")[-1])
            if sort:
                break
        if sort is None:
            if isinstance(slot, bool):
                sort = "bool"
            elif is_scalar(slot):
                sort = "real"
            else:
                self.system.gaps.append(f"{path}: no scalar type; skipped")
                return None
        const = {"real": z3.Real, "int": z3.Int, "bool": z3.Bool}[sort](path)
        self.system.variables[path] = const
        natural = any(t.split("::")[-1] == "Natural" for t in attr.types)
        if natural:
            self.system.assertions.append((f"{path}.natural", const >= 0))
        return const

    # -- expression encoding --------------------------------------------------

    def _encode(self, expr: A.Expr, context: M.Namespace, prefix: str,
                frame: dict[str, Any],
                prefixes: dict[str, str] | None = None) -> Any:
        z3 = self.z3
        if isinstance(expr, A.Literal):
            if isinstance(expr.value, bool):
                return z3.BoolVal(expr.value)
            if isinstance(expr.value, int):
                return z3.IntVal(expr.value)
            if isinstance(expr.value, float):
                return z3.RealVal(str(expr.value))  # exact decimal
            raise AnalysisError(f"literal {expr.value!r} has no Z3 sort")
        if isinstance(expr, (A.FeatureRef, A.ChainAccess)):
            return self._ref(expr, context, prefix, frame, prefixes or {})
        if isinstance(expr, A.QuantityOp):
            return self._encode(expr.base, context, prefix, frame, prefixes)
        if isinstance(expr, A.Unary):
            operand = self._encode(expr.operand, context, prefix, frame,
                                   prefixes)
            if expr.op == "not":
                return z3.Not(operand)
            return -operand if expr.op == "-" else operand
        if isinstance(expr, A.Conditional):
            return z3.If(
                self._encode(expr.test, context, prefix, frame, prefixes),
                self._encode(expr.then, context, prefix, frame, prefixes),
                self._encode(expr.orelse, context, prefix, frame, prefixes))
        if isinstance(expr, A.Binary):
            return self._binary(expr, context, prefix, frame, prefixes)
        if isinstance(expr, A.Invocation):
            return self._invoke(expr, context, prefix, frame, prefixes)
        raise AnalysisError(f"'{expr.to_text()}' ({type(expr).__name__}) is "
                            "not encodable for Z3")

    def _binary(self, expr: A.Binary, context: M.Namespace, prefix: str,
                frame: dict[str, Any],
                prefixes: dict[str, str] | None) -> Any:
        z3 = self.z3
        left = self._encode(expr.left, context, prefix, frame, prefixes)
        right = self._encode(expr.right, context, prefix, frame, prefixes)
        op = expr.op
        if op == "and":
            return z3.And(left, right)
        if op == "or":
            return z3.Or(left, right)
        if op == "implies":
            return z3.Implies(left, right)
        if op == "xor":
            return z3.Xor(left, right)
        if op in ("**", "^"):
            return left ** right
        if op in ("==", "==="):
            return left == right
        if op in ("!=", "!=="):
            return left != right
        table = {"+": lambda a, b: a + b, "-": lambda a, b: a - b,
                 "*": lambda a, b: a * b, "/": lambda a, b: a / b,
                 "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
                 ">": lambda a, b: a > b, ">=": lambda a, b: a >= b}
        if op in table:
            return table[op](left, right)
        raise AnalysisError(f"operator {op!r} is not encodable for Z3")

    def _ref(self, expr: A.FeatureRef | A.ChainAccess, context: M.Namespace,
             prefix: str, frame: dict[str, Any],
             prefixes: dict[str, str]) -> Any:
        if isinstance(expr, A.FeatureRef):
            parts: QName = expr.parts
        else:
            assert isinstance(expr.base, A.FeatureRef), "chained non-ref base"
            parts = (*expr.base.parts, *expr.parts)
        if parts[0] in frame:
            if len(parts) > 1:
                raise AnalysisError(f"member access on parameter "
                                    f"{parts[0]!r} is not supported")
            return frame[parts[0]]
        if parts[0] in prefixes:
            parts = (*filter(None, prefixes[parts[0]].split(".")), *parts[1:])
        path = prefix + ".".join(parts)
        if path in self.system.variables:
            return self.system.variables[path]
        try:  # model-level constant (enum-free scalar attribute, stdlib, ...)
            value = self.interp.evaluate(A.FeatureRef(parts), context)
        except EvaluationError as err:
            raise AnalysisError(f"cannot resolve '{'.'.join(parts)}'") from err
        if isinstance(value, bool):
            return self.z3.BoolVal(value)
        if is_scalar(value):
            return self.z3.RealVal(str(float(value)))
        raise AnalysisError(f"'{'.'.join(parts)}' is not scalar ({value!r})")

    def _invoke(self, expr: A.Invocation, context: M.Namespace, prefix: str,
                frame: dict[str, Any],
                prefixes: dict[str, str] | None) -> Any:
        z3 = self.z3
        name = expr.target[-1]
        args = [self._encode(a, context, prefix, frame, prefixes)
                for a in expr.args]
        named = {n: self._encode(e, context, prefix, frame, prefixes)
                 for n, e in expr.named}
        try:
            target = self.interp.resolver.resolve(expr.target, context)
        except ResolutionError:
            target = None
        if isinstance(target, (M.Definition, M.Usage)) and \
                target.kind in ("calc", "constraint"):
            return self._inline_calc(target, args, named)
        if name == "abs" and len(args) == 1 and not named:
            return z3.If(args[0] >= 0, args[0], -args[0])
        raise AnalysisError(f"invocation of {'::'.join(expr.target)!r} is "
                            "not encodable (only calc defs and abs)")

    def _inline_calc(self, calc: M.Definition | M.Usage, args: list[Any],
                     named: dict[str, Any]) -> Any:
        params = [m for m in self.interp.resolver.members_of(calc)
                  if isinstance(m, M.Usage) and m.direction in ("in", "inout")
                  and m.name]
        frame: dict[str, Any] = {}
        for param, value in zip(params, args, strict=False):
            assert param.name is not None
            frame[param.name] = value
        frame.update(named)
        result: A.Expr | None = calc.result
        for member in self.interp.resolver.members_of(calc):
            if not isinstance(member, M.Usage):
                continue
            if member.direction == "return":
                if member.value is not None and result is None:
                    result = member.value.expr
                continue
            if member.name is None or member.name in frame:
                continue
            if member.value is not None:  # defaults and locals
                frame[member.name] = self._encode(member.value.expr, calc, "",
                                                  dict(frame))
        if result is None:
            raise AnalysisError(f"calc {calc.label} has no result expression")
        return self._encode(result, calc, "", frame)
