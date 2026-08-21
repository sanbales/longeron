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
  variables (``+ - * /``; division introduces an auxiliary variable via
  ``add_division_equality`` with floor rounding at 1e-6 resolution).
* ``assert constraint`` bodies -> half-reified linear constraints under one
  named enforcement literal each, so :meth:`TradeStudy.explain` can ask
  CP-SAT which requirement subset is sufficient for infeasibility.

Feasible architectures are enumerated (or optimized) by CP-SAT; every
reported :class:`Architecture` is then re-evaluated *exactly* by the
interpreter (metrics + a ``verified`` constraint re-check), so fixed-point
rounding can never misreport a design.

The CP-SAT mapper covers linear-ish catalogs (``+ - * /``).  Models whose
derived attributes lean on real physics -- ``sqrt``/``pow``, conditionals,
calc invocations (e.g. ``examples/uav_missions.sysml``) -- are *not*
encodable and the solver methods raise :class:`AnalysisError`.  The honest
pattern at catalog scale is then :meth:`TradeStudy.all_architectures` /
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
from math import ceil, floor, lcm
from typing import Any, ClassVar

from .. import ast as A
from .. import model as M
from ..errors import EvaluationError
from ..interpreter import Interpreter
from ._expr import AnalysisError, QName, constraint_expr, free_refs, is_scalar, named_members

__all__ = ["Architecture", "TradeStudy", "VariationPoint", "pareto"]

_DIV_SCALE = 10**6  # fixed-point resolution of division results


def _cp() -> Any:
    try:
        from ortools.sat.python import cp_model
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "longeron.analysis.trades needs OR-Tools CP-SAT; install the extra "
            "with 'pip install \"longeron[trades]\"'"
        ) from err
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
    return Fraction(str(value)) if isinstance(value, float) else Fraction(value)


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

    # -- numeric ------------------------------------------------------------

    def value(self, expr: A.Expr) -> _Val:
        if isinstance(expr, A.Literal):
            if isinstance(expr.value, bool) or not is_scalar(expr.value):
                raise AnalysisError(f"literal {expr.value!r} is not numeric")
            return _Val(const=_frac(expr.value))
        if isinstance(expr, (A.FeatureRef, A.ChainAccess)):
            return self.study._lookup(self, _path(expr))
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
        raise AnalysisError(
            f"cannot encode expression '{expr.to_text()}' ({type(expr).__name__}) for CP-SAT"
        )

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
        va, vb = self._as_var(a), self._as_var(b)
        cands = [x / y for x in a.bounds for y in b.bounds]
        lo, hi = min(cands), max(cands)
        target = self._new_var(lo, hi, _DIV_SCALE)
        # value = (va/sa)/(vb/sb) = va*sb / (vb*sa); floor at 1/_DIV_SCALE
        self.model.add_division_equality(target, va * (b.scale * _DIV_SCALE), vb * a.scale)
        return _Val(expr=target, scale=_DIV_SCALE, lo=lo, hi=hi)

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
        raise AnalysisError(f"cannot encode constraint '{expr.to_text()}' for CP-SAT")

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
                if var.types:
                    inst = self.interp.instantiate(
                        self._namespace(self.interp.resolver.resolve(var.types[0], typ))
                    )
                else:
                    inst = self.interp.instantiate(var)
                variants[var.name] = {k: v for k, v in inst.slots.items() if is_scalar(v)}
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
            self._derived_vals[name] = encoder.value(expr)

        literals = []
        for con in named_members(self.interp, self.assembly, ("constraint",)):
            body = constraint_expr(self.interp, con)
            if body is None:
                continue
            lit = model.new_bool_var(con.name or con.label)
            encoder.constrain(body, lit)
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
            source = (
                self._namespace(self.interp.resolver.resolve(usage.types[0], typ))
                if usage.types
                else usage
            )
            bindings[pname] = self.interp.instantiate(source)
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
