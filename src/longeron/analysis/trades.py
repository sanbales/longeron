"""Discrete architecture trade studies on OR-Tools CP-SAT (spike).

Maps a SysML v2 assembly whose part usages are typed by ``variation``
definitions (a component catalog) onto a CP-SAT model:

* variation part usage -> one Boolean selection literal per ``variant``
  (+ exactly-one); a ``[4]`` multiplicity selects homogeneously (all four
  motors are the same variant -- per-index heterogeneous selection is a
  documented phase-2 item).
* variant attribute values -> integer variables channeled to the selected
  variant's values, in exact fixed-point (per-attribute scale = lcm of the
  value denominators).
* derived assembly attributes -> fixed-point arithmetic over those
  variables: ``+ - * /``, constant non-negative integer exponents,
  ``max()``/``min()`` (native ``add_max_equality``/``add_min_equality``),
  and ``calc def`` invocations, which are inlined -- the invoked calc's
  result expression is encoded with the caller's argument values bound to
  its parameters (recursively; cycles are refused).
* ``assert constraint`` bodies -> half-reified linear constraints under one
  named enforcement literal each, so :meth:`TradeStudy.explain` can ask
  CP-SAT which requirement subset is sufficient for infeasibility.

Fixed-point error budget (all rounding is one-sided and bounded):

* float constants and variant values are rounded to seven significant
  decimal digits (relative error <= 5e-7);
* division results and rescaled intermediates keep at least six
  significant digits (relative error <= 1e-5 per operation).

Feasible architectures are enumerated (or optimized) by CP-SAT; every
reported :class:`Architecture` is then re-evaluated *exactly* by the
interpreter (metrics + a ``verified`` constraint re-check), so fixed-point
rounding can never misreport a design.  A mix that CP-SAT's rounded
arithmetic judges feasible but the interpreter refutes is returned with
``verified=False`` -- the interpreter stays the sole semantic oracle.

What the mapper still refuses -- with an :class:`AnalysisError` naming the
innermost unencodable operation -- is arithmetic with no exact fixed-point
form: ``sqrt``, fractional ``pow``, and ``if``/``else`` conditionals (the
real physics of the DeepScout mission layers,
``examples/deepscout/missions.sysml``).  The
honest pattern there is :meth:`TradeStudy.all_architectures` /
:meth:`TradeStudy.evaluate`: walk the (small) Cartesian candidate space and
let the interpreter evaluate every mix exactly, ``violations`` naming the
constraints an infeasible mix breaks.

Requires the ``trades`` extra: ``pip install "longeron[trades]"``
(:meth:`TradeStudy.evaluate` and :meth:`TradeStudy.all_architectures` run
on the interpreter alone).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from itertools import product
from math import ceil, floor, gcd, lcm, log10
from typing import Any, ClassVar

from .. import ast as A
from .. import model as M
from ..errors import EvaluationError, MissingExtraError
from ..interpreter import BUILTINS, Interpreter
from ._expr import AnalysisError, QName, constraint_expr, free_refs, is_scalar, named_members

__all__ = ["Architecture", "TradeStudy", "VariationPoint", "pareto"]

_DIGITS = 6  # significant decimal digits kept by rescaled intermediates
_CONST_DENOM_CAP = 10**_DIGITS  # constants above this are decimal-rounded


def _cp() -> Any:
    try:
        from ortools.sat.python import cp_model
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError("longeron.analysis.trades", "OR-Tools CP-SAT", "trades") from err
    return cp_model


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------


@dataclass
class VariationPoint:
    """A part usage typed by a ``variation`` definition."""

    name: str  # part usage name in the assembly, e.g. 'motors'
    count: int  # multiplicity (homogeneous selection)
    variants: dict[str, dict[str, Any]]  # variant name -> attribute values


@dataclass
class Architecture:
    """One component mix, with interpreter-exact metrics."""

    selection: dict[str, str]  # point name -> variant name
    metrics: dict[str, float]  # derived attribute -> exact value
    verified: bool = True  # all constraints re-checked by the interpreter
    #: names of the constraints the interpreter found violated (the
    #: mix-level answer to "why is this one infeasible?")
    violations: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        mix = ", ".join(f"{k}={v}" for k, v in self.selection.items())
        vals = ", ".join(f"{k}={v:g}" for k, v in self.metrics.items())
        return f"[{mix}] {vals}"


def pareto(
    architectures: list[Architecture],
    minimize: tuple[str, ...] = (),
    maximize: tuple[str, ...] = (),
) -> list[Architecture]:
    """The non-dominated subset under the given objectives."""

    def key(a: Architecture) -> tuple[float, ...]:
        return (*(a.metrics[m] for m in minimize), *(-a.metrics[m] for m in maximize))

    def dominated(a: Architecture) -> bool:
        ka = key(a)
        return any(
            all(x <= y for x, y in zip(key(b), ka, strict=True)) and key(b) != ka
            for b in architectures
        )

    return [a for a in architectures if not dominated(a)]


# ---------------------------------------------------------------------------
# fixed-point expression values
# ---------------------------------------------------------------------------


@dataclass
class _Val:
    """Either an exact rational constant or ``expr / scale`` with bounds."""

    const: Fraction | None = None
    expr: Any = None  # cp_model.LinearExpr
    scale: int = 1
    lo: Fraction = Fraction(0)
    hi: Fraction = Fraction(0)

    @property
    def bounds(self) -> tuple[Fraction, Fraction]:
        if self.const is not None:
            return self.const, self.const
        return self.lo, self.hi


def _frac(value: Any) -> Fraction:
    out = Fraction(str(value)) if isinstance(value, float) else Fraction(value)
    if out.denominator <= _CONST_DENOM_CAP:
        return out
    # seven significant decimal digits (relative error <= 5e-7): keeps every
    # scale in the encoder a product of 2s and 5s, so rescaling divides evenly
    mag = floor(log10(abs(out)))
    quantum = 10 ** max(0, _DIGITS - mag)
    return Fraction(round(out * quantum), quantum)


def _snippet(expr: A.Expr, limit: int = 72) -> str:
    """A one-line, length-capped rendering of an expression for messages."""

    text = " ".join(expr.to_text().split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class _Encoder:
    """AST -> CP-SAT fixed-point arithmetic / half-reified constraints."""

    _FLIP: ClassVar[dict[str, str]] = {
        "<": ">=",
        "<=": ">",
        ">": "<=",
        ">=": "<",
        "==": "!=",
        "!=": "==",
    }

    def __init__(self, study: TradeStudy, model: Any):
        self.study = study
        self.model = model
        self._aux = 0
        #: inlined-calc scopes: (calc element, parameter name -> value)
        self._frames: list[tuple[M.Definition | M.Usage, dict[str, _Val]]] = []

    # -- numeric ------------------------------------------------------------

    def value(self, expr: A.Expr) -> _Val:
        if isinstance(expr, A.Literal):
            if isinstance(expr.value, bool) or not is_scalar(expr.value):
                raise AnalysisError(f"literal {expr.value!r} is not numeric")
            return _Val(const=_frac(expr.value))
        if isinstance(expr, (A.FeatureRef, A.ChainAccess)):
            return self._ref(_path(expr))
        if isinstance(expr, A.Invocation):
            return self._invoke(expr)
        if isinstance(expr, A.QuantityOp):
            return self.value(expr.base)
        if isinstance(expr, A.Unary) and expr.op in ("-", "+"):
            val = self.value(expr.operand)
            return val if expr.op == "+" else self.mul(_Val(const=Fraction(-1)), val)
        if isinstance(expr, A.Binary) and expr.op in ("+", "-", "*", "/"):
            left, right = self.value(expr.left), self.value(expr.right)
            if expr.op == "+":
                return self.add(left, right)
            if expr.op == "-":
                return self.add(left, self.mul(_Val(const=Fraction(-1)), right))
            if expr.op == "*":
                return self.mul(left, right)
            return self.div(left, right)
        if isinstance(expr, A.Binary) and expr.op == "**":
            # constant non-negative integer exponent: unrolled multiplication
            # (d ** 4.0 stays exact fixed-point; anything else is refused)
            if isinstance(expr.right, A.Literal) and is_scalar(expr.right.value):
                exponent = Fraction(_frac(expr.right.value))
                if exponent.denominator == 1 and exponent >= 0:
                    base = self.value(expr.left)
                    out = _Val(const=Fraction(1))
                    for _ in range(int(exponent)):
                        out = self.mul(out, base)
                    return out
            raise AnalysisError(
                f"cannot encode exponent '{_snippet(expr)}' for CP-SAT "
                "(only constant non-negative integer exponents unroll)"
            )
        if isinstance(expr, A.Conditional):
            raise AnalysisError(
                f"'{_snippet(expr, 48)}': a conditional has no fixed-point encoding"
            )
        raise AnalysisError(
            f"cannot encode expression '{_snippet(expr)}' ({type(expr).__name__}) for CP-SAT"
        )

    def _ref(self, path: QName) -> _Val:
        """Resolve a reference: inlined-calc frame first, then the study."""

        if not self._frames:
            return self.study._lookup(self, path)
        calc, frame = self._frames[-1]
        if len(path) == 1 and path[0] in frame:
            return frame[path[0]]
        try:  # calc-scope constant (a package-level value, say)
            value = self.study.interp.evaluate(A.FeatureRef(path), calc)
        except EvaluationError as err:
            raise AnalysisError(
                f"cannot resolve '{'.'.join(path)}' inside calc '{calc.label}' "
                "during CP-SAT encoding"
            ) from err
        if not is_scalar(value):
            raise AnalysisError(f"'{'.'.join(path)}' is not numeric ({value!r})")
        return _Val(const=_frac(value))

    # -- invocations ----------------------------------------------------------

    def _invoke(self, expr: A.Invocation) -> _Val:
        name = expr.target
        shadowed = bool(self._frames) and name[0] in self._frames[-1][1]
        if len(name) == 1 and name[0] in BUILTINS and not shadowed:
            return self._builtin(name[0], expr)
        context = self._frames[-1][0] if self._frames else self.study.assembly
        try:
            target = self.study.interp.resolver.resolve(name, context)
        except Exception as err:
            raise AnalysisError(
                f"cannot resolve invocation target '{'::'.join(name)}' for CP-SAT"
            ) from err
        if isinstance(target, (M.Definition, M.Usage)) and target.kind in ("calc", "constraint"):
            return self._inline_calc(target, expr)
        raise AnalysisError(
            f"cannot encode invocation '{_snippet(expr, 48)}': "
            f"'{'::'.join(name)}' is not a calc definition"
        )

    def _builtin(self, name: str, expr: A.Invocation) -> _Val:
        if expr.named:
            raise AnalysisError(f"builtin '{name}' takes no named arguments")
        args = [self.value(a) for a in expr.args]
        if name in ("max", "min") and args:
            return self.extremum(name, args)
        if args and all(a.const is not None for a in args):
            # constant fold through the interpreter's own builtin (float
            # semantics, so the proxy matches what re-evaluation computes)
            result = BUILTINS[name](*(float(a.const) for a in args))  # type: ignore[arg-type]
            if not is_scalar(result):
                raise AnalysisError(f"builtin '{name}' did not fold to a number")
            return _Val(const=_frac(result))
        raise AnalysisError(
            f"'{_snippet(expr, 48)}': {name} of a selection-dependent value "
            "has no fixed-point encoding"
        )

    def _inline_calc(self, calc: M.Definition | M.Usage, expr: A.Invocation) -> _Val:
        if any(calc is frame_calc for frame_calc, _ in self._frames):
            raise AnalysisError(
                f"recursive invocation of calc '{calc.label}' cannot be inlined for CP-SAT"
            )
        members = self.study.interp.resolver.members_of(calc)
        params = [
            (m.name, m)
            for m in members
            if isinstance(m, M.Usage) and m.direction in ("in", "inout") and m.name
        ]
        if len(expr.args) > len(params):
            raise AnalysisError(f"{calc.label} takes {len(params)} parameters")
        # arguments are encoded in the CALLER's scope, before the frame opens
        frame: dict[str, _Val] = {}
        for (pname, _), arg in zip(params, expr.args, strict=False):
            frame[pname] = self.value(arg)
        names = {pname for pname, _ in params}
        for aname, aexpr in expr.named:
            if aname not in names:
                raise AnalysisError(f"{calc.label} has no parameter {aname!r}")
            frame[aname] = self.value(aexpr)
        self._frames.append((calc, frame))
        try:
            for pname, param in params:  # defaults, in the callee's scope
                if pname in frame:
                    continue
                if param.value is None:
                    raise AnalysisError(f"missing argument for parameter {pname!r} of {calc.label}")
                frame[pname] = self.value(param.value.expr)
            return_expr: A.Expr | None = None
            for member in members:  # valued locals, mirroring _call_calc
                if not isinstance(member, M.Usage):
                    continue
                if member.direction == "return":
                    if member.value is not None and return_expr is None:
                        return_expr = member.value.expr
                    continue
                if member.name is None or member.direction in ("in", "inout"):
                    continue
                if member.value is not None:
                    frame[member.name] = self.value(member.value.expr)
            result = calc.result if calc.result is not None else return_expr
            if result is None:
                raise AnalysisError(f"{calc.label} has no result expression")
            return self.value(result)
        finally:
            self._frames.pop()

    # -- arithmetic -----------------------------------------------------------

    def extremum(self, op: str, args: list[_Val]) -> _Val:
        """``max``/``min`` over fixed-point values (native CP-SAT)."""

        if all(a.const is not None for a in args):
            pick = max if op == "max" else min
            return _Val(const=pick(a.const for a in args))  # type: ignore[type-var]
        args = [self._rescale(a) for a in args]
        scale = 1
        for a in args:
            scale = lcm(scale, a.const.denominator if a.const is not None else a.scale)
        los = [a.bounds[0] for a in args]
        his = [a.bounds[1] for a in args]
        pick = max if op == "max" else min
        lo, hi = pick(los), pick(his)
        target = self._new_var(lo, hi, scale)
        exprs = [self._at(a, scale) for a in args]
        adder = self.model.add_max_equality if op == "max" else self.model.add_min_equality
        adder(target, exprs)
        return _Val(expr=target, scale=scale, lo=lo, hi=hi)

    def add(self, a: _Val, b: _Val) -> _Val:
        if a.const is not None and b.const is not None:
            return _Val(const=a.const + b.const)
        scale = self._common_scale(a, b)
        (alo, ahi), (blo, bhi) = a.bounds, b.bounds
        return _Val(
            expr=self._at(a, scale) + self._at(b, scale), scale=scale, lo=alo + blo, hi=ahi + bhi
        )

    def mul(self, a: _Val, b: _Val) -> _Val:
        if a.const is not None and b.const is not None:
            return _Val(const=a.const * b.const)
        if b.const is not None:
            a, b = b, a
        if a.const is not None:  # constant * expression: exact
            c = a.const
            (blo, bhi) = b.bounds
            bounds = sorted((c * blo, c * bhi))
            return _Val(
                expr=b.expr * c.numerator, scale=b.scale * c.denominator, lo=bounds[0], hi=bounds[1]
            )
        a, b = self._rescale(a), self._rescale(b)
        if a.const is not None or b.const is not None:  # zero-width bounds folded
            return self.mul(a, b)
        va, vb = self._as_var(a), self._as_var(b)
        cands = [x * y for x in a.bounds for y in b.bounds]
        lo, hi = min(cands), max(cands)
        scale = a.scale * b.scale
        target = self._new_var(lo, hi, scale)
        self.model.add_multiplication_equality(target, [va, vb])
        return _Val(expr=target, scale=scale, lo=lo, hi=hi)

    def div(self, a: _Val, b: _Val) -> _Val:
        if b.const is not None:
            if b.const == 0:
                raise AnalysisError("division by constant zero")
            return self.mul(_Val(const=1 / b.const), a)
        if b.lo <= 0:
            raise AnalysisError(
                "division by an expression that may be <= 0 "
                "is not supported (bounds "
                f"[{b.lo}, {b.hi}])"
            )
        a, b = self._rescale(a), self._rescale(b)
        if b.const is not None:
            return self.div(a, b)
        cands = [x / y for x in a.bounds for y in b.bounds]
        lo, hi = min(cands), max(cands)
        if a.const is not None:  # constant / expression: still a division
            a = self._materialize(a)
        va, vb = self._as_var(a), self._as_var(b)
        # value = (va/sa)/(vb/sb) = va*sb / (vb*sa), quantized to `scale`:
        # target = va*(sb*scale)/(vb*sa), with the coefficient fraction
        # reduced so the int64 budget survives large operand scales
        scale = self._fit_scale(lo, hi)
        while scale >= 1:
            g = gcd(b.scale * scale, a.scale)
            ncoef, dcoef = b.scale * scale // g, a.scale // g
            bound = max(abs(floor(a.lo * a.scale)), abs(ceil(a.hi * a.scale))) * ncoef
            if bound < 2**62:
                break
            scale //= 10  # trade resolution for range
        else:
            raise AnalysisError(
                "fixed-point division overflows CP-SAT's integer domain: "
                "evaluate mixes exactly with all_architectures()/evaluate() instead"
            )
        # truncation slop: the quotient may fall one quantum outside the
        # exact interval, so the declared domain widens by 1/scale
        lo, hi = lo - Fraction(1, scale), hi + Fraction(1, scale)
        target = self._new_var(lo, hi, scale)
        self.model.add_division_equality(target, va * ncoef, vb * dcoef)
        return _Val(expr=target, scale=scale, lo=lo, hi=hi)

    # -- boolean ------------------------------------------------------------

    def constrain(self, expr: A.Expr, literal: Any) -> None:
        """Assert ``literal => expr`` (half-reified)."""

        if isinstance(expr, A.Binary) and expr.op == "and":
            self.constrain(expr.left, literal)
            self.constrain(expr.right, literal)
            return
        if isinstance(expr, A.Binary) and expr.op == "or":
            arms = []
            for arm in (expr.left, expr.right):
                lit = self.model.new_bool_var(f"or_{self._aux}")
                self._aux += 1
                self.constrain(arm, lit)
                arms.append(lit)
            self.model.add_bool_or(arms).only_enforce_if(literal)
            return
        if (
            isinstance(expr, A.Unary)
            and expr.op == "not"
            and isinstance(expr.operand, A.Binary)
            and expr.operand.op in self._FLIP
        ):
            flipped = A.Binary(
                self._FLIP[expr.operand.op],  # type: ignore[arg-type]
                expr.operand.left,
                expr.operand.right,
            )
            self.constrain(flipped, literal)
            return
        if isinstance(expr, A.Binary) and expr.op in ("<", "<=", ">", ">=", "==", "!="):
            diff = self.add(
                self.value(expr.left), self.mul(_Val(const=Fraction(-1)), self.value(expr.right))
            )
            self._compare(diff, expr.op, literal)
            return
        raise AnalysisError(f"cannot encode constraint '{_snippet(expr)}' for CP-SAT")

    def _compare(self, diff: _Val, op: str, literal: Any) -> None:
        if diff.const is not None:  # statically decided
            holds = {
                "<": diff.const < 0,
                "<=": diff.const <= 0,
                ">": diff.const > 0,
                ">=": diff.const >= 0,
                "==": diff.const == 0,
                "!=": diff.const != 0,
            }[op]
            if not holds:
                self.model.add_bool_and([literal.negated()])
            return
        e = diff.expr
        con = {"<": e <= -1, "<=": e <= 0, ">": e >= 1, ">=": e >= 0, "==": e == 0, "!=": e != 0}[
            op
        ]
        self.model.add(con).only_enforce_if(literal)

    # -- plumbing -----------------------------------------------------------

    @staticmethod
    def _fit_scale(lo: Fraction, hi: Fraction) -> int:
        """A power-of-ten scale keeping ~:data:`_DIGITS` significant digits."""

        maxabs = max(abs(lo), abs(hi))
        if maxabs == 0:
            return 1
        return int(10 ** max(0, _DIGITS + 1 - ceil(log10(float(maxabs)) + 1)))

    def _rescale(self, v: _Val) -> _Val:
        """Requantize an oversized fixed-point value to ~:data:`_DIGITS`
        significant digits (one floor division, error <= 1/new scale)."""

        if v.const is not None:
            return v
        if v.lo == v.hi:  # bounds always contain the value: it is constant
            return _Val(const=v.lo)
        want = self._fit_scale(v.lo, v.hi)
        if v.scale <= want:
            return v
        # the largest divisor of scale of the form 2^i * 5^j that fits `want`
        # (scales are products of decimal denominators, so this finds one)
        twos = fives = 0
        rest = v.scale
        while rest % 2 == 0:
            twos, rest = twos + 1, rest // 2
        while rest % 5 == 0:
            fives, rest = fives + 1, rest // 5
        best = 1
        for i in range(twos + 1):
            if 2**i > want:
                break
            for j in range(fives + 1):
                cand = 2**i * 5**j
                if cand > want:
                    break
                best = max(best, cand)
        if best >= v.scale:
            return v
        # truncation slop: widen the declared domain by one quantum
        lo, hi = v.lo - Fraction(1, best), v.hi + Fraction(1, best)
        target = self._new_var(lo, hi, best)
        self.model.add_division_equality(target, v.expr, v.scale // best)
        return _Val(expr=target, scale=best, lo=lo, hi=hi)

    def _materialize(self, v: _Val) -> _Val:
        """A constant as a (fixed) variable-backed value."""

        assert v.const is not None
        return _Val(
            expr=self.model.new_constant(v.const.numerator) * 1,
            scale=v.const.denominator,
            lo=v.const,
            hi=v.const,
        )

    def _common_scale(self, a: _Val, b: _Val) -> int:
        scale = 1
        for v in (a, b):
            scale = lcm(scale, v.const.denominator if v.const is not None else v.scale)
        return scale

    def _at(self, v: _Val, scale: int) -> Any:
        if v.const is not None:
            return int(v.const * scale)
        return v.expr * (scale // v.scale)

    def _as_var(self, v: _Val) -> Any:
        if v.const is not None:
            raise AnalysisError("constant cannot be materialized as var")
        var = self._new_var(v.lo, v.hi, v.scale)
        self.model.add(var == v.expr)
        return var

    def _new_var(self, lo: Fraction, hi: Fraction, scale: int) -> Any:
        self._aux += 1
        lo_i, hi_i = floor(lo * scale), ceil(hi * scale)
        if max(abs(lo_i), abs(hi_i)) >= 2**62:  # CP-SAT domain is int64
            raise AnalysisError(
                f"fixed-point encoding overflows CP-SAT's integer domain "
                f"(scale {scale}): this model's arithmetic is beyond the "
                "linear mapper -- evaluate mixes exactly with "
                "all_architectures()/evaluate() instead"
            )
        return self.model.new_int_var(lo_i, hi_i, f"aux_{self._aux}")


def _path(expr: A.Expr) -> QName:
    if isinstance(expr, A.FeatureRef):
        return expr.parts
    if isinstance(expr, A.ChainAccess) and isinstance(expr.base, A.FeatureRef):
        return (*expr.base.parts, *expr.parts)
    raise AnalysisError(f"unsupported reference form '{expr.to_text()}'")


# ---------------------------------------------------------------------------
# the trade study
# ---------------------------------------------------------------------------


class TradeStudy:
    """Enumerate/optimize variant selections for one assembly definition."""

    def __init__(self, model: M.Model, assembly: str | M.Definition | M.Usage):
        self.interp = Interpreter(model)
        target = self.interp.resolve(assembly) if isinstance(assembly, str) else assembly
        if not isinstance(target, (M.Definition, M.Usage)):
            raise AnalysisError(f"{assembly!r} is not a part definition")
        self.assembly = target
        self.points = self._find_points()
        if not self.points:
            raise AnalysisError(f"{target.label} has no variation points")
        self.derived_order = self._derived_attributes()
        self.constraint_names = [
            c.name or c.label
            for c in named_members(self.interp, target, ("constraint",))
            if constraint_expr(self.interp, c) is not None
        ]
        self.gaps: list[str] = []

    # -- model introspection --------------------------------------------------

    def _find_points(self) -> dict[str, VariationPoint]:
        points: dict[str, VariationPoint] = {}
        for member in named_members(self.interp, self.assembly, ("part", "item")):
            if not member.types:
                continue
            try:
                typ = self.interp.resolver.resolve(member.types[0], member.owner or self.assembly)
            except Exception:
                continue
            if not (isinstance(typ, (M.Definition, M.Usage)) and typ.is_variation):
                continue
            variants: dict[str, dict[str, Any]] = {}
            for var in typ.members:
                if not (isinstance(var, M.Usage) and var.is_variant and var.name):
                    continue
                # instantiate the variant usage itself: the resolver's member
                # walk merges its body redefinitions (':>> mass = 0.055;')
                # over the typed variant's inherited defaults -- instantiating
                # the *type* would silently drop the body overrides
                inst = self.interp.instantiate(var)
                # strings ride along beside the numerics: the geometry
                # bridge reads declared section specs (wingSection) off
                # the variant table, and the encoders only channel the
                # attributes that constraints actually reference
                variants[var.name] = {
                    k: v for k, v in inst.slots.items() if is_scalar(v) or isinstance(v, str)
                }
            count = 1
            if member.multiplicity is not None and member.multiplicity.upper is not None:
                try:
                    count = int(self.interp.evaluate(member.multiplicity.upper, self.assembly))
                except (EvaluationError, TypeError):
                    count = 1
            assert member.name is not None
            points[member.name] = VariationPoint(member.name, count, variants)
        return points

    def _derived_attributes(self) -> list[tuple[str, A.Expr]]:
        """Assembly attributes whose values depend on variant selections.

        Detection runs to a fixed point and the result is ordered by
        dependency (an attribute comes after every derived attribute it
        references), so a specialization's own metrics may reference
        inherited ones -- and vice versa -- regardless of member order.
        """

        exprs: dict[str, A.Expr] = {}
        refs: dict[str, set[str]] = {}
        order: list[str] = []
        for attr in named_members(self.interp, self.assembly, ("attribute",)):
            if attr.value is None or attr.name is None:
                continue
            exprs[attr.name] = attr.value.expr
            refs[attr.name] = {p[0] for p in free_refs(attr.value.expr)}
            order.append(attr.name)

        derived: set[str] = set()
        changed = True
        while changed:  # fixed point: member order must not matter
            changed = False
            for name in order:
                if name not in derived and refs[name] & (set(self.points) | derived):
                    derived.add(name)
                    changed = True

        out: list[tuple[str, A.Expr]] = []
        placed: set[str] = set()
        remaining = [n for n in order if n in derived]
        while remaining:  # Kahn's algorithm, stable on member order
            ready = [n for n in remaining if refs[n] & derived <= placed]
            if not ready:
                raise AnalysisError("cyclic derived attributes: " + ", ".join(sorted(remaining)))
            for name in ready:
                out.append((name, exprs[name]))
                placed.add(name)
            remaining = [n for n in remaining if n not in placed]
        return out

    # -- CP-SAT build -----------------------------------------------------------

    def _build(self, enforce: bool) -> tuple[Any, Any, dict, dict, list]:
        cp = _cp()
        model = cp.CpModel()
        sel: dict[str, dict[str, Any]] = {}
        for pname, point in self.points.items():
            sel[pname] = {v: model.new_bool_var(f"{pname}={v}") for v in point.variants}
            model.add_exactly_one(sel[pname].values())

        self._attr_vars: dict[QName, _Val] = {}
        self._derived_vals: dict[str, _Val] = {}
        encoder = _Encoder(self, model)
        self._encoder_sel = sel
        for name, expr in self.derived_order:
            try:
                self._derived_vals[name] = encoder.value(expr)
            except AnalysisError as err:
                raise AnalysisError(
                    f"CP-SAT cannot encode derived attribute '{name}' -- {err}; "
                    "the interpreter path (all_architectures()/evaluate()) stays exact"
                ) from err

        literals = []
        for con in named_members(self.interp, self.assembly, ("constraint",)):
            body = constraint_expr(self.interp, con)
            if body is None:
                continue
            lit = model.new_bool_var(con.name or con.label)
            try:
                encoder.constrain(body, lit)
            except AnalysisError as err:
                raise AnalysisError(
                    f"CP-SAT cannot encode constraint '{con.name or con.label}' -- {err}; "
                    "the interpreter path (all_architectures()/evaluate()) stays exact"
                ) from err
            literals.append(lit)
            if enforce:
                model.add_bool_and([lit])
        return cp, model, sel, self._derived_vals, literals

    def _lookup(self, encoder: _Encoder, path: QName) -> _Val:
        """Resolve a referenced path during encoding."""

        if len(path) == 2 and path[0] in self.points:
            return self._channel(encoder, path)
        if len(path) == 1 and path[0] in self._derived_vals:
            return self._derived_vals[path[0]]
        try:
            value = self.interp.evaluate(A.FeatureRef(path), self.assembly)
        except EvaluationError as err:
            raise AnalysisError(
                f"cannot resolve '{'.'.join(path)}' during CP-SAT encoding"
            ) from err
        if not is_scalar(value):
            raise AnalysisError(f"'{'.'.join(path)}' is not numeric ({value!r})")
        return _Val(const=_frac(value))

    def _channel(self, encoder: _Encoder, path: QName) -> _Val:
        """An IntVar equal to the selected variant's attribute value."""

        if path in self._attr_vars:
            return self._attr_vars[path]
        pname, attr = path
        point = self.points[pname]
        values: dict[str, Fraction] = {}
        for vname, slots in point.variants.items():
            if attr not in slots:
                raise AnalysisError(f"variant {pname}.{vname} does not define attribute {attr!r}")
            if not is_scalar(slots[attr]):
                raise AnalysisError(
                    f"variant attribute {pname}.{vname}.{attr} is not numeric ({slots[attr]!r})"
                )
            values[vname] = _frac(slots[attr])
        scale = lcm(*(v.denominator for v in values.values()))
        lo, hi = min(values.values()), max(values.values())
        var = encoder.model.new_int_var(floor(lo * scale), ceil(hi * scale), f"{pname}.{attr}")
        for vname, value in values.items():
            encoder.model.add(var == int(value * scale)).only_enforce_if(
                self._encoder_sel[pname][vname]
            )
        val = _Val(expr=var, scale=scale, lo=lo, hi=hi)
        self._attr_vars[path] = val
        return val

    # -- exact reporting ---------------------------------------------------------

    def _bindings(self, selection: dict[str, str]) -> dict[str, Any]:
        """Interpreter bindings (variant instances + derived values)."""

        bindings: dict[str, Any] = {}
        for pname, vname in selection.items():
            typ = self._namespace(
                self.interp.resolver.resolve(self._point_type(pname), self.assembly)
            )
            usage = None
            for var in typ.members:
                if isinstance(var, M.Usage) and var.name == vname:
                    usage = var
                    break
            assert usage is not None
            # the variant usage, not its type: body redefinitions must
            # survive into the interpreter-exact re-evaluation too
            bindings[pname] = self.interp.instantiate(usage)
        for name, expr in self.derived_order:
            bindings[name] = self.interp.evaluate(expr, self.assembly, **bindings)
        return bindings

    def _architecture(self, selection: dict[str, str]) -> Architecture:
        """Re-evaluate a selection exactly with the interpreter."""

        bindings = self._bindings(selection)
        metrics = {name: float(bindings[name]) for name, _ in self.derived_order}
        violations: list[str] = []
        for con in named_members(self.interp, self.assembly, ("constraint",)):
            body = constraint_expr(self.interp, con)
            if body is None:
                continue
            if not bool(self.interp.evaluate(body, self.assembly, **bindings)):
                violations.append(con.name or con.label)
        return Architecture(
            selection=dict(selection),
            metrics=metrics,
            verified=not violations,
            violations=violations,
        )

    @staticmethod
    def _namespace(element: M.Element) -> M.Definition | M.Usage:
        if not isinstance(element, (M.Definition, M.Usage)):
            raise AnalysisError(f"{element.label} is not instantiable")
        return element

    def _point_type(self, pname: str) -> str:
        member = None
        for m in named_members(self.interp, self.assembly, ("part", "item")):
            if m.name == pname:
                member = m
        assert member is not None and member.types
        return member.types[0]

    # -- public API -----------------------------------------------------------

    def evaluate(self, selection: dict[str, str]) -> Architecture:
        """Interpreter-exact metrics for any mix, feasible or not.

        ``selection`` maps every variation-point name to a variant name;
        the returned ``verified`` flag reports whether all constraints
        hold.  No solver runs -- this needs only the interpreter.
        """

        self._check_selection(selection)
        return self._architecture({p: selection[p] for p in self.points})

    def margins(self, selection: dict[str, str]) -> dict[str, dict[str, Any]]:
        """Numeric constraint margins for one mix (>= 0 iff it holds).

        Per constraint name: ``{"margin", "ok", "text"}``.  ``margin``
        follows the standard orientation (``lhs <= rhs`` -> ``rhs -
        lhs``, ``lhs >= rhs`` -> ``lhs - rhs``; strict comparisons use
        their closure) and is ``None`` when the body is not a plain
        comparison -- ``ok`` still reports the interpreter's verdict.
        ``text`` is the constraint body's source text, so a view can
        show the requirement threshold next to the achieved margin.
        """

        self._check_selection(selection)
        bindings = self._bindings({p: selection[p] for p in self.points})
        out: dict[str, dict[str, Any]] = {}
        for con in named_members(self.interp, self.assembly, ("constraint",)):
            body = constraint_expr(self.interp, con)
            if body is None:
                continue
            ok = bool(self.interp.evaluate(body, self.assembly, **bindings))
            margin: float | None = None
            if isinstance(body, A.Binary) and body.op in ("<", "<=", ">", ">="):
                lhs = float(self.interp.evaluate(body.left, self.assembly, **bindings))
                rhs = float(self.interp.evaluate(body.right, self.assembly, **bindings))
                margin = (rhs - lhs) if body.op in ("<", "<=") else (lhs - rhs)
            out[con.name or con.label] = {"margin": margin, "ok": ok, "text": body.to_text()}
        return out

    def _check_selection(self, selection: dict[str, str]) -> None:
        for pname, point in self.points.items():
            if pname not in selection:
                raise AnalysisError(f"selection is missing point {pname!r}")
            if selection[pname] not in point.variants:
                raise AnalysisError(
                    f"unknown variant {selection[pname]!r} for point "
                    f"{pname!r} (have: {sorted(point.variants)})"
                )
        extra = set(selection) - set(self.points)
        if extra:
            raise AnalysisError(f"unknown variation point(s) {sorted(extra)}")

    def all_architectures(self) -> list[Architecture]:
        """Every candidate mix (the full Cartesian product), exact metrics.

        Unlike :meth:`enumerate`, infeasible mixes are included (with
        ``verified=False``) -- the raw material for views that show the
        frontier inside the whole candidate space.
        """

        names = list(self.points)
        return [
            self._architecture(dict(zip(names, combo, strict=True)))
            for combo in product(*(self.points[n].variants for n in names))
        ]

    def enumerate(self) -> list[Architecture]:
        """All feasible architectures, interpreter-verified."""

        cp, model, sel, _, _ = self._build(enforce=True)
        selections: list[dict[str, str]] = []

        class _Collect(cp.CpSolverSolutionCallback):  # type: ignore[name-defined]
            def on_solution_callback(self) -> None:
                selections.append(
                    {
                        pname: next(v for v, lit in variants.items() if self.boolean_value(lit))
                        for pname, variants in sel.items()
                    }
                )

        solver = cp.CpSolver()
        solver.parameters.enumerate_all_solutions = True
        solver.solve(model, _Collect())
        return [self._architecture(s) for s in selections]

    def minimize(self, metric: str) -> Architecture | None:
        return self._optimize(metric, maximize=False)

    def maximize(self, metric: str) -> Architecture | None:
        return self._optimize(metric, maximize=True)

    def _optimize(self, metric: str, maximize: bool) -> Architecture | None:
        """Optimal architecture for one derived metric (``None`` if infeasible).

        The objective is the fixed-point proxy; ties/rankings closer than the
        division resolution (1e-6) are settled by the exact re-evaluation.
        """

        cp, model, sel, derived, _ = self._build(enforce=True)
        if metric not in derived:
            raise AnalysisError(f"{metric!r} is not a derived attribute (have: {sorted(derived)})")
        val = derived[metric]
        if val.const is not None:
            raise AnalysisError(f"{metric!r} is constant")
        model.maximize(val.expr) if maximize else model.minimize(val.expr)
        solver = cp.CpSolver()
        status = solver.solve(model)
        if status not in (cp.OPTIMAL, cp.FEASIBLE):
            return None
        selection = {
            pname: next(v for v, lit in variants.items() if solver.boolean_value(lit))
            for pname, variants in sel.items()
        }
        return self._architecture(selection)

    def explain(self) -> list[str]:
        """``[]`` when feasible; else constraint names sufficient for UNSAT."""

        cp, model, _, _, literals = self._build(enforce=False)
        model.add_assumptions(literals)
        solver = cp.CpSolver()
        status = solver.solve(model)
        if status != cp.INFEASIBLE:
            return []
        indices = set(solver.sufficient_assumptions_for_infeasibility())
        return [lit.name for lit in literals if lit.index in indices]
