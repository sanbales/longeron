"""Project SysML v2 part trees and calcs onto OpenMDAO Problems (spike).

Mapping (see ``.handoff/analysis-integration-design.md`` in the main tree):

* ``calc def`` -> ``ExplicitComponent`` whose ``compute()`` calls the
  interpreter (:func:`calc_component`).
* part tree -> nested ``Group`` per part usage; each *derived* attribute
  (value expression referencing other features) becomes an
  ``ExplicitComponent``; *free* attributes (literal values) become
  ``IndepVarComp`` outputs, so they can be design variables.
* attribute cross-references -> ``connect()`` between promoted names
  (``chassis.mass`` connects group ``chassis``'s promoted ``mass``).
* ``assert constraint`` / requirement ``require`` with a comparison body ->
  a ``*_margin`` output (>= 0 iff the predicate holds), ready for
  ``add_constraint``.

Requires the ``mdao`` extra: ``pip install "longeron[mdao]"``.  OpenMDAO is
imported lazily so the module can be imported (for docs, dir()) without it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .. import ast as A
from .. import model as M
from ..errors import EvaluationError
from ..interpreter import Instance, Interpreter
from ._expr import (
    AnalysisError,
    QName,
    constraint_expr,
    free_refs,
    instance_path,
    is_scalar,
    named_members,
    rewrite_refs,
    sanitize,
)

__all__ = ["ProblemBuild", "add_optimization", "build_problem", "calc_component"]

_COMPARISONS = {"<", "<=", ">", ">=", "=="}


def _om() -> Any:
    try:
        import openmdao.api as om
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "sysml2.analysis.mdao needs OpenMDAO; install the extra with "
            "'pip install \"longeron[mdao]\"'") from err
    return om


@dataclass
class ProblemBuild:
    """A built (not yet run) OpenMDAO problem plus its SysML bookkeeping."""

    problem: Any  # om.Problem
    independents: list[str] = field(default_factory=list)  # promoted names
    derived: list[str] = field(default_factory=list)
    constraints: dict[str, str] = field(default_factory=dict)  # name -> margin var
    gaps: list[str] = field(default_factory=list)  # unmapped constructs


# ---------------------------------------------------------------------------
# calc def -> ExplicitComponent
# ---------------------------------------------------------------------------


def calc_component(interp: Interpreter, calc: str | M.Definition | M.Usage,
                   out_name: str = "result") -> Any:
    """Wrap a ``calc def`` as an ``ExplicitComponent`` (FD partials)."""

    om = _om()
    target = interp.resolve(calc) if isinstance(calc, str) else calc
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{calc!r} is not a calc definition")
    if target.kind != "calc":
        raise AnalysisError(f"{calc!r} is not a calc definition")
    calc_target: M.Definition | M.Usage = target
    params = [m for m in interp.resolver.members_of(calc_target)
              if isinstance(m, M.Usage) and m.direction in ("in", "inout")
              and m.name]

    class _CalcComp(om.ExplicitComponent):  # type: ignore[name-defined]
        def setup(self) -> None:
            for p in params:
                default = 1.0
                if p.value is not None:
                    try:
                        default = float(interp.evaluate(p.value.expr,
                                                        calc_target))
                    except (EvaluationError, TypeError):
                        pass
                self.add_input(p.name, val=default)
            self.add_output(out_name, val=0.0)
            self.declare_partials(out_name, "*", method="fd")

        def compute(self, inputs: Any, outputs: Any) -> None:
            kwargs = {p.name: float(inputs[p.name][0]) for p in params
                      if p.name is not None}
            outputs[out_name] = interp.call(calc_target, **kwargs)

    comp = _CalcComp()
    comp.options.declare("sysml_calc", default=calc_target.qualified_name)
    return comp


# ---------------------------------------------------------------------------
# expression -> ExplicitComponent
# ---------------------------------------------------------------------------


def _expr_component(interp: Interpreter, context: M.Namespace, out_name: str,
                    expr: A.Expr, inputs: dict[str, QName]) -> Any:
    """A component evaluating ``expr`` with referenced paths as inputs."""

    om = _om()
    flat = rewrite_refs(expr, {path: name for name, path in inputs.items()})

    class _ExprComp(om.ExplicitComponent):  # type: ignore[name-defined]
        def setup(self) -> None:
            for name in inputs:
                self.add_input(name, val=1.0)
            self.add_output(out_name, val=0.0)
            self.declare_partials(out_name, "*", method="fd")

        def compute(self, ins: Any, outs: Any) -> None:
            frame = {name: float(ins[name][0]) for name in inputs}
            outs[out_name] = float(interp.evaluate(flat, context, **frame))

    return _ExprComp()


# ---------------------------------------------------------------------------
# part tree -> Problem
# ---------------------------------------------------------------------------


def build_problem(model: M.Model, part: str | M.Definition | M.Usage,
                  requirements: tuple[str, ...] = (),
                  setup: bool = True) -> ProblemBuild:
    """Build an OpenMDAO ``Problem`` mirroring a part definition's tree."""

    om = _om()
    interp = Interpreter(model)
    target = interp.resolve(part) if isinstance(part, str) else part
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{part!r} is not instantiable")
    instance = interp.instantiate(target)
    prob = om.Problem(reports=False)
    build = ProblemBuild(problem=prob)
    _populate(om, interp, build, prob.model, target, instance, prefix="")
    for req_name in requirements:
        _add_requirement(om, interp, build, prob.model, req_name, target, instance)
    if setup:
        prob.setup()
    return build


def _populate(om: Any, interp: Interpreter, build: ProblemBuild, group: Any,
              defn: M.Definition | M.Usage, instance: Instance,
              prefix: str) -> None:
    consts: list[tuple[str, float]] = []
    connections: list[tuple[str, str]] = []
    comps: list[tuple[str, Any, str]] = []  # (subsystem name, comp, output)

    for attr in named_members(interp, defn, ("attribute",)):
        name = attr.name or attr.short_name
        assert name is not None
        expr = attr.value.expr if attr.value is not None else None
        refs = _variable_refs(expr, instance) if expr is not None else {}
        if expr is None or not refs:
            value = instance.slots.get(name)
            if is_scalar(value):
                consts.append((name, float(value)))
                build.independents.append(f"{prefix}{name}")
            else:
                build.gaps.append(f"{prefix}{name}: non-scalar attribute skipped")
            continue
        comp_name = f"{sanitize((name,))}_comp"
        comps.append((comp_name,
                      _expr_component(interp, defn, name, expr,
                                      {sanitize(p): p for p in refs}), name))
        connections += [(".".join(p), f"{comp_name}.{sanitize(p)}") for p in refs]
        build.derived.append(f"{prefix}{name}")

    for con in named_members(interp, defn, ("constraint",)):
        margin = _margin_expr(interp, con)
        if margin is None:
            build.gaps.append(f"{prefix}{con.label}: constraint body is not a "
                              "comparison; skipped")
            continue
        refs = _variable_refs(margin, instance)
        out = f"{con.name or con.label}_margin"
        comp_name = f"{sanitize((out,))}_comp"
        comps.append((comp_name,
                      _expr_component(interp, defn, out, margin,
                                      {sanitize(p): p for p in refs}), out))
        connections += [(".".join(p), f"{comp_name}.{sanitize(p)}") for p in refs]
        build.constraints[f"{prefix}{con.name or con.label}"] = f"{prefix}{out}"

    # dependency order: independents and child parts first, then derived
    # expressions (auto_order untangles derived-to-derived references)
    if consts:
        ivc = om.IndepVarComp()
        for name, value in consts:
            ivc.add_output(name, val=value)
        group.add_subsystem("consts", ivc, promotes=["*"])

    for name, slot in instance.slots.items():
        member = _member_named(interp, defn, name)
        if isinstance(slot, Instance) and slot.definition is not None:
            sub = group.add_subsystem(sanitize((name,)), om.Group())
            _populate(om, interp, build, sub, slot.definition, slot,
                      prefix=f"{prefix}{name}.")
        elif isinstance(slot, list) and slot and isinstance(slot[0], Instance):
            for i, item in enumerate(slot):
                if item.definition is None:
                    continue
                sub = group.add_subsystem(f"{sanitize((name,))}_{i + 1}", om.Group())
                _populate(om, interp, build, sub, item.definition, item,
                          prefix=f"{prefix}{name}_{i + 1}.")
            if member is not None and _refs_into(defn, interp, name):
                build.gaps.append(f"{prefix}{name}: references into sequence "
                                  "parts are not connected (phase 2: arrays)")

    for comp_name, comp, out in comps:
        group.add_subsystem(comp_name, comp, promotes_outputs=[out])
    group.options["auto_order"] = True

    for src, tgt in connections:
        group.connect(src, tgt)


def _member_named(interp: Interpreter, defn: M.Definition | M.Usage,
                  name: str) -> M.Usage | None:
    for m in interp.resolver.members_of(defn):
        if isinstance(m, M.Usage) and name in (m.name, m.short_name):
            return m
    return None


def _refs_into(defn: M.Definition | M.Usage, interp: Interpreter,
               slot_name: str) -> bool:
    for attr in named_members(interp, defn, ("attribute", "constraint")):
        expr = attr.value.expr if attr.value is not None else attr.result
        if expr is None:
            continue
        if any(p[0] == slot_name and len(p) > 1 for p in free_refs(expr)):
            return True
    return False


def _variable_refs(expr: A.Expr, instance: Instance) -> set[QName]:
    """Referenced paths that resolve to scalar leaves of the instance tree."""

    refs = set()
    for path in free_refs(expr):
        value = instance_path(instance, path)
        if is_scalar(value):
            refs.add(path)
    return refs


def _margin_expr(interp: Interpreter, con: M.Usage) -> A.Expr | None:
    """``lhs OP rhs`` -> an expression that is >= 0 iff the predicate holds.

    Strict comparisons are relaxed to their closure (``>`` -> margin >= 0),
    which is the standard treatment for continuous optimization.
    """

    expr = constraint_expr(interp, con)
    if not isinstance(expr, A.Binary) or expr.op not in _COMPARISONS:
        return None
    if expr.op in ("<", "<="):
        return A.Binary("-", expr.right, expr.left)
    if expr.op in (">", ">="):
        return A.Binary("-", expr.left, expr.right)
    return A.Unary("-", A.Invocation(("abs",), (A.Binary("-", expr.left,
                                                         expr.right),)))


def _add_requirement(om: Any, interp: Interpreter, build: ProblemBuild,
                     group: Any, req_name: str,
                     subject_defn: M.Definition | M.Usage,
                     instance: Instance) -> None:
    """Map a requirement's require-constraints to margin outputs at the root.

    The requirement's ``subject`` name is stripped from reference paths, so
    ``drone.totalMass`` connects to the root group's ``totalMass``.
    """

    req = interp.resolve(req_name)
    if not isinstance(req, (M.Definition, M.Usage)):
        raise AnalysisError(f"{req_name!r} is not a requirement")
    subjects = [m.name for m in interp.resolver.members_of(req)
                if isinstance(m, M.Usage) and m.kind == "subject" and m.name]
    subject = subjects[0] if subjects else "subject"
    for con in named_members(interp, req, ("constraint",)):
        if con.constraint_kind == "assume":
            continue
        margin = _margin_expr(interp, con)
        if margin is None:
            build.gaps.append(f"{req.label}::{con.label}: not a comparison")
            continue
        stripped: dict[QName, str | QName] = {
            path: path[1:] for path in free_refs(margin)
            if path[0] == subject and len(path) > 1}
        margin = rewrite_refs(margin, stripped)
        refs = _variable_refs(margin, instance)
        out = f"{con.name or con.label}_margin"
        comp_name = f"{sanitize((req.label, out))}_comp"
        group.add_subsystem(
            comp_name,
            _expr_component(interp, req, out, margin,
                            {sanitize(p): p for p in refs}),
            promotes_outputs=[out])
        for p in refs:
            group.connect(".".join(p), f"{comp_name}.{sanitize(p)}")
        build.constraints[f"{req.label}::{con.name or con.label}"] = out


# ---------------------------------------------------------------------------
# optimization sugar
# ---------------------------------------------------------------------------


def add_optimization(build: ProblemBuild, objective: str,
                     design_vars: dict[str, tuple[float, float]],
                     maximize: bool = False,
                     constraints: tuple[str, ...] | None = None) -> None:
    """Configure SLSQP over margin constraints; call before ``setup()``."""

    om = _om()
    prob = build.problem
    prob.driver = om.ScipyOptimizeDriver(optimizer="SLSQP", tol=1e-9)
    for name, (lower, upper) in design_vars.items():
        prob.model.add_design_var(name, lower=lower, upper=upper)
    prob.model.add_objective(objective, scaler=-1.0 if maximize else 1.0)
    names = (build.constraints if constraints is None
             else {c: build.constraints[c] for c in constraints})
    for margin_var in names.values():
        prob.model.add_constraint(margin_var, lower=0.0)
