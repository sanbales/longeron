"""Project SysML v2 part trees and calcs onto OpenMDAO Problems (spike).

Mapping (see ``.handoff/analysis-integration-design.md`` in the main tree):

* ``calc def`` -> ``ExplicitComponent`` whose ``compute()`` calls the
  interpreter (:func:`calc_component`).
* part tree -> nested ``Group`` per part usage; each *derived* attribute
  (value expression referencing other features) becomes an
  ``ExplicitComponent``; *free* attributes (literal values) become
  ``IndepVarComp`` outputs, so they can be design variables.
* DISCIPLINE GROUPING: when a derived attribute's value invokes a calc
  def that lives in its own package (e.g. ``UavMissions::Propulsion``),
  the attribute's component is housed in an OpenMDAO ``Group`` named
  after that package (outputs promoted, so flat names keep working).
  The SysML package structure is the source of the grouping -- organize
  the calc defs into discipline packages and the generated N2 shows the
  classic Aerodynamics / Propulsion / Structures / Performance blocks.
  Calcs owned by a namespace enclosing the part definition itself are
  shared context, not disciplines, and stay ungrouped
  (``ProblemBuild.disciplines`` records the mapping).
* attribute cross-references -> ``connect()`` between promoted names
  (``chassis.mass`` connects group ``chassis``'s promoted ``mass``).
* ``assert constraint`` / requirement ``require`` with a comparison body ->
  a ``*_margin`` output (>= 0 iff the predicate holds), ready for
  ``add_constraint``.
* a ``calc def`` annotated ``@ExternalAnalysis { component = "module:attr"; }``
  declares the I/O contract of a higher-fidelity tool wrapped as an
  OpenMDAO ``ExplicitComponent``.  When a derived attribute's value is a
  direct invocation of such a calc, :func:`build_problem` can instantiate
  the referenced component instead of the interpreter-backed expression
  (``fidelity={"CalcName": "external"}``; bodiless annotated calcs bind
  externally by default), after validating the declared parameter names
  against the component's actual inputs/outputs.  The declared contract is
  the point: SysML owns the interface, the tool owns the physics, and both
  fidelities compose with the interpreter-backed components in one
  ``Problem``.

Requires the ``mdao`` extra: ``pip install "longeron[mdao]"``.  OpenMDAO is
imported lazily so the module can be imported (for docs, dir()) without it.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
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

__all__ = [
    "ProblemBuild",
    "add_optimization",
    "build_problem",
    "calc_component",
    "external_binding",
]

_COMPARISONS = {"<", "<=", ">", ">=", "=="}


def _om() -> Any:
    try:
        import openmdao.api as om
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "sysml2.analysis.mdao needs OpenMDAO; install the extra with "
            "'pip install \"longeron[mdao]\"'"
        ) from err
    return om


@dataclass
class ProblemBuild:
    """A built (not yet run) OpenMDAO problem plus its SysML bookkeeping."""

    problem: Any  # om.Problem
    independents: list[str] = field(default_factory=list)  # promoted names
    derived: list[str] = field(default_factory=list)
    constraints: dict[str, str] = field(default_factory=dict)  # name -> margin var
    gaps: list[str] = field(default_factory=list)  # unmapped constructs
    externals: dict[str, str] = field(default_factory=dict)  # attr -> component spec
    disciplines: dict[str, list[str]] = field(default_factory=dict)  # group -> attrs


# ---------------------------------------------------------------------------
# calc def -> ExplicitComponent
# ---------------------------------------------------------------------------


def calc_component(
    interp: Interpreter, calc: str | M.Definition | M.Usage, out_name: str = "result"
) -> Any:
    """Wrap a ``calc def`` as an ``ExplicitComponent`` (FD partials)."""

    om = _om()
    target = interp.resolve(calc) if isinstance(calc, str) else calc
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{calc!r} is not a calc definition")
    if target.kind != "calc":
        raise AnalysisError(f"{calc!r} is not a calc definition")
    calc_target: M.Definition | M.Usage = target
    params = [
        m
        for m in interp.resolver.members_of(calc_target)
        if isinstance(m, M.Usage) and m.direction in ("in", "inout") and m.name
    ]

    class _CalcComp(om.ExplicitComponent):  # type: ignore[name-defined]
        def setup(self) -> None:
            for p in params:
                default = 1.0
                if p.value is not None:
                    try:
                        default = float(interp.evaluate(p.value.expr, calc_target))
                    except (EvaluationError, TypeError):
                        pass
                self.add_input(p.name, val=default)
            self.add_output(out_name, val=0.0)
            self.declare_partials(out_name, "*", method="fd")

        def compute(self, inputs: Any, outputs: Any) -> None:
            kwargs = {p.name: float(inputs[p.name][0]) for p in params if p.name is not None}
            outputs[out_name] = interp.call(calc_target, **kwargs)

    comp = _CalcComp()
    comp.options.declare("sysml_calc", default=calc_target.qualified_name)
    return comp


# ---------------------------------------------------------------------------
# external analysis binding (@ExternalAnalysis on a calc def)
# ---------------------------------------------------------------------------


def external_binding(calc: M.Definition | M.Usage) -> str | None:
    """The ``@ExternalAnalysis`` component spec of a calc def, if any.

    The annotation's ``component`` value must be a string literal of the
    form ``'package.module:attr'`` where ``attr`` is an
    ``om.ExplicitComponent`` subclass or a zero-argument factory returning
    one.  Matching is by metadata-definition name (``ExternalAnalysis``),
    the convention shipped with ``examples/uav_missions.sysml``.
    """

    for member in calc.members:
        if not isinstance(member, M.MetadataUsage):
            continue
        if member.typed_by.split("::")[-1] != "ExternalAnalysis":
            continue
        for value in member.members:
            if not (
                isinstance(value, M.MetadataValue)
                and value.redefines == "component"
                and value.value is not None
            ):
                continue
            expr = value.value.expr
            if isinstance(expr, A.Literal) and isinstance(expr.value, str):
                return expr.value
            raise AnalysisError(
                f"{calc.label}: @ExternalAnalysis component must be a "
                f"string literal (got '{expr.to_text()}')"
            )
        raise AnalysisError(
            f"{calc.label}: @ExternalAnalysis annotation declares no 'component' value"
        )
    return None


def _calc_body(interp: Interpreter, calc: M.Definition | M.Usage) -> A.Expr | None:
    """The calc's result expression (own or on its ``return`` member)."""

    if calc.result is not None:
        return calc.result
    for member in interp.resolver.members_of(calc):
        if (
            isinstance(member, M.Usage)
            and member.direction == "return"
            and member.value is not None
        ):
            return member.value.expr
    return None


def _return_name(interp: Interpreter, calc: M.Definition | M.Usage) -> str | None:
    """The declared name of the calc's return parameter (usually absent)."""

    for member in interp.resolver.members_of(calc):
        if isinstance(member, M.Usage) and member.direction == "return":
            return member.name
    return None


class _Fidelity:
    """Per-calc fidelity choices (``'model'`` | ``'external'``) + bookkeeping."""

    def __init__(self, interp: Interpreter, fidelity: Mapping[str, str] | None):
        self.interp = interp
        self.requested = dict(fidelity or {})
        self.used: set[str] = set()
        bad = {k: v for k, v in self.requested.items() if v not in ("model", "external")}
        if bad:
            raise AnalysisError(f"fidelity values must be 'model' or 'external' (got {bad})")

    def mode(self, calc: M.Definition | M.Usage) -> str:
        """The effective fidelity: bodiless annotated calcs default external."""

        spec = external_binding(calc)
        if spec is None:
            return "model"
        has_body = _calc_body(self.interp, calc) is not None
        for key in (calc.qualified_name, calc.name):
            if key is not None and key in self.requested:
                self.used.add(key)
                if self.requested[key] == "model" and not has_body:
                    raise AnalysisError(
                        f"{calc.label}: fidelity 'model' requested but the "
                        "calc declares no body -- only 'external' is "
                        "possible"
                    )
                return self.requested[key]
        return "model" if has_body else "external"

    def check_all_used(self) -> None:
        unused = set(self.requested) - self.used
        if unused:
            raise AnalysisError(
                f"fidelity given for calc(s) never bound in this problem: "
                f"{sorted(unused)} (known keys are names/qualified names of "
                "@ExternalAnalysis-annotated calc defs reached by the part "
                "tree)"
            )


def _resolve_calc(
    interp: Interpreter, context: M.Namespace, expr: A.Expr
) -> M.Definition | M.Usage | None:
    """The calc definition a direct invocation targets, if it is one."""

    if not isinstance(expr, A.Invocation):
        return None
    try:
        target = interp.resolver.resolve(expr.target, context)
    except Exception:
        return None
    if isinstance(target, (M.Definition, M.Usage)) and target.kind == "calc":
        return target
    return None


def _discipline(interp: Interpreter, defn: M.Namespace, expr: A.Expr) -> str | None:
    """The discipline group an attribute's component belongs to, if any.

    The owning package of the FIRST calc def the value expression
    invokes (depth-first), when that package is a discipline package --
    i.e. not a namespace that encloses the part definition itself
    (calcs beside the part are shared context, not a discipline).  The
    model's package structure is deliberately the single source of this
    grouping.
    """

    found: M.Definition | M.Usage | None = None

    def visit(node: Any) -> None:
        nonlocal found
        if found is not None:
            return
        if isinstance(node, A.Invocation):
            calc = _resolve_calc(interp, defn, node)
            if calc is not None:
                found = calc
                return
        if isinstance(node, A.Expr):
            for f in fields(node):
                visit(getattr(node, f.name))
        elif isinstance(node, tuple):
            for item in node:
                visit(item)

    visit(expr)
    if found is None:
        return None
    package: M.Element | None = found.owner
    while package is not None and not isinstance(package, M.Package):
        package = package.owner
    if package is None or package.name is None:
        return None
    node: M.Element | None = defn
    while node is not None:  # enclosing namespaces are context, not disciplines
        if node is package:
            return None
        node = node.owner
    return package.name


def _contains_bodiless_external(interp: Interpreter, context: M.Namespace, expr: A.Expr) -> bool:
    """Whether ``expr`` invokes (anywhere) a bodiless external calc."""

    found = False

    def visit(node: Any) -> None:
        nonlocal found
        if isinstance(node, A.Invocation):
            calc = _resolve_calc(interp, context, node)
            if (
                calc is not None
                and external_binding(calc) is not None
                and _calc_body(interp, calc) is None
            ):
                found = True
        if isinstance(node, A.Expr):
            for f in fields(node):
                visit(getattr(node, f.name))
        elif isinstance(node, tuple):
            for item in node:
                visit(item)

    visit(expr)
    return found


def _guard_nested(
    interp: Interpreter,
    context: M.Namespace,
    expr: A.Expr,
    fid: _Fidelity,
    where: str,
    skip: A.Expr | None = None,
) -> None:
    """Reject externally-bound calcs invoked inside larger expressions.

    An external component can only replace a whole attribute value
    (``attribute x = Calc(...)``); an invocation nested in arithmetic has
    no output to graft the component onto, and silently falling back to
    the interpreter would evaluate the wrong fidelity (or no body at all).
    ``skip`` exempts the direct invocation already bound externally.
    """

    def visit(node: Any) -> None:
        if isinstance(node, A.Invocation) and node is not skip:
            calc = _resolve_calc(interp, context, node)
            if calc is not None and fid.mode(calc) == "external":
                raise AnalysisError(
                    f"{where}: calc {calc.label} is bound to an external "
                    "component but is invoked inside a larger expression; "
                    "only a direct 'attribute x = Calc(...)' value can "
                    "bind externally (or select fidelity 'model')"
                )
        if isinstance(node, A.Expr):
            for f in fields(node):
                visit(getattr(node, f.name))
        elif isinstance(node, tuple):
            for item in node:
                visit(item)

    visit(expr)


def _load_component(om: Any, spec: str) -> Any:
    """Instantiate an external component from a ``'module:attr'`` spec."""

    module_name, sep, attr = spec.partition(":")
    if not (sep and module_name and attr):
        raise AnalysisError(
            f"external component spec {spec!r} is not of the form 'package.module:attr'"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as err:
        raise AnalysisError(
            f"cannot import module {module_name!r} for external component {spec!r}: {err}"
        ) from err
    try:
        target = getattr(module, attr)
    except AttributeError as err:
        raise AnalysisError(
            f"module {module_name!r} has no attribute {attr!r} (external component {spec!r})"
        ) from err
    component = target() if callable(target) else target
    if not isinstance(component, om.ExplicitComponent):
        raise AnalysisError(
            f"external component {spec!r} produced "
            f"{type(component).__name__}, not an om.ExplicitComponent"
        )
    return component


def _component_io(om: Any, spec: str) -> tuple[set[str], list[str]]:
    """Actual input/output names of an external component.

    Instantiates a throwaway probe in its own Problem (components cannot
    be re-parented after setup), so the declared SysML contract can be
    validated against what the component really exposes.
    """

    probe_problem = om.Problem(reports=False)
    probe = probe_problem.model.add_subsystem("probe", _load_component(om, spec))
    probe_problem.setup()
    probe_problem.final_setup()
    inputs = {name.rsplit(".", 1)[-1] for name, _ in probe.list_inputs(out_stream=None)}
    outputs = [name.rsplit(".", 1)[-1] for name, _ in probe.list_outputs(out_stream=None)]
    return inputs, outputs


def _ref_path(expr: A.Expr) -> QName | None:
    if isinstance(expr, A.FeatureRef):
        return expr.parts
    if isinstance(expr, A.ChainAccess) and isinstance(expr.base, A.FeatureRef):
        return (*expr.base.parts, *expr.parts)
    return None


def _add_external(
    om: Any,
    interp: Interpreter,
    build: ProblemBuild,
    group: Any,
    defn: M.Namespace,
    name: str,
    invocation: A.Invocation,
    calc: M.Definition | M.Usage,
    spec: str,
    prefix: str,
    path_prefix: str = "",
) -> list[tuple[str, str]]:
    """Wire an external component in place of ``attribute name = Calc(...)``.

    Validates the calc's declared in/out parameters against the
    component's actual I/O (that declared contract is the point), promotes
    the component's single output under the attribute name, and returns
    the connections for the invocation's arguments (attribute references
    connect, numeric literals become an aux ``IndepVarComp``).  ``group``
    is the housing group (a discipline group when the calc lives in a
    discipline package); ``path_prefix`` is that group's path relative to
    the group the connections are declared on.
    """

    params = [
        m
        for m in interp.resolver.members_of(calc)
        if isinstance(m, M.Usage) and m.direction in ("in", "inout") and m.name is not None
    ]
    declared = [p.name for p in params if p.name is not None]

    bound: dict[str, A.Expr] = {}
    for pname, arg in zip(declared, invocation.args, strict=False):
        bound[pname] = arg
    for pname, arg in invocation.named:
        if pname in bound:
            raise AnalysisError(
                f"{calc.label}: argument {pname!r} given twice in the external binding"
            )
        bound[pname] = arg
    unknown = sorted(set(bound) - set(declared))
    if unknown:
        raise AnalysisError(
            f"{calc.label}: invocation passes parameter(s) {unknown} the calc does not declare"
        )

    inputs, outputs = _component_io(om, spec)
    if set(declared) != inputs:
        missing = sorted(set(declared) - inputs)
        extra = sorted(inputs - set(declared))
        raise AnalysisError(
            f"{calc.label}: external component {spec!r} does not match the "
            f"declared contract: component lacks declared input(s) "
            f"{missing}; component declares undeclared input(s) {extra}"
        )
    if len(outputs) != 1:
        raise AnalysisError(
            f"{calc.label}: external component {spec!r} must expose exactly "
            f"one output (found {sorted(outputs)})"
        )
    declared_out = _return_name(interp, calc)
    if declared_out is not None and outputs[0] != declared_out:
        raise AnalysisError(
            f"{calc.label}: external component {spec!r} output "
            f"{outputs[0]!r} does not match the declared return "
            f"{declared_out!r}"
        )

    comp_name = f"{sanitize((name,))}_ext"
    group.add_subsystem(comp_name, _load_component(om, spec), promotes_outputs=[(outputs[0], name)])
    connections: list[tuple[str, str]] = []
    consts: list[tuple[str, float]] = []
    for pname, arg in bound.items():
        path = _ref_path(arg)
        if path is not None:
            connections.append((".".join(path), f"{path_prefix}{comp_name}.{pname}"))
        elif isinstance(arg, A.Literal) and is_scalar(arg.value):
            consts.append((pname, float(arg.value)))
        else:
            raise AnalysisError(
                f"{calc.label}: external-binding argument {pname!r} must be "
                f"an attribute reference or numeric literal "
                f"(got '{arg.to_text()}')"
            )
    if consts:
        ivc = om.IndepVarComp()
        for pname, value in consts:
            ivc.add_output(pname, val=value)
        group.add_subsystem(f"{comp_name}_args", ivc)
        connections += [
            (f"{path_prefix}{comp_name}_args.{pname}", f"{path_prefix}{comp_name}.{pname}")
            for pname, _ in consts
        ]
    build.externals[f"{prefix}{name}"] = spec
    return connections


# ---------------------------------------------------------------------------
# expression -> ExplicitComponent
# ---------------------------------------------------------------------------


def _expr_component(
    interp: Interpreter, context: M.Namespace, out_name: str, expr: A.Expr, inputs: dict[str, QName]
) -> Any:
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


def build_problem(
    model: M.Model,
    part: str | M.Definition | M.Usage,
    requirements: tuple[str, ...] = (),
    setup: bool = True,
    fidelity: Mapping[str, str] | None = None,
) -> ProblemBuild:
    """Build an OpenMDAO ``Problem`` mirroring a part definition's tree.

    ``fidelity`` selects, per ``@ExternalAnalysis``-annotated calc def
    (keyed by name or qualified name), whether a direct
    ``attribute x = Calc(...)`` value evaluates the calc's first-order
    body through the interpreter (``'model'``, the default when a body
    exists) or instantiates the annotated external component
    (``'external'``; the default -- and only -- choice when the calc
    declares no body).  The two fidelities are drop-in replacements, so
    lo-fi/hi-fi swap studies are one keyword away.
    """

    om = _om()
    interp = Interpreter(model)
    target = interp.resolve(part) if isinstance(part, str) else part
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{part!r} is not instantiable")
    # bodiless externally-bound calcs cannot be evaluated by the
    # interpreter: instantiate around them with placeholder slots (their
    # real values come from the external component at run time; nested
    # uses are rejected loudly by the guard in _populate)
    placeholders: dict[str, Any] = {}
    for attr in named_members(interp, target, ("attribute",)):
        if attr.value is None or attr.name is None:
            continue
        if _contains_bodiless_external(interp, target, attr.value.expr):
            placeholders[attr.name] = 1.0
    instance = interp.instantiate(target, **placeholders)
    prob = om.Problem(reports=False)
    build = ProblemBuild(problem=prob)
    fid = _Fidelity(interp, fidelity)
    _populate(om, interp, build, prob.model, target, instance, prefix="", fid=fid)
    for req_name in requirements:
        _add_requirement(om, interp, build, prob.model, req_name, target, instance, fid)
    fid.check_all_used()
    if setup:
        prob.setup()
    return build


def _populate(
    om: Any,
    interp: Interpreter,
    build: ProblemBuild,
    group: Any,
    defn: M.Definition | M.Usage,
    instance: Instance,
    prefix: str,
    fid: _Fidelity,
) -> None:
    consts: list[tuple[str, float]] = []
    connections: list[tuple[str, str]] = []
    comps: list[tuple[str, Any, str, str | None]] = []  # (name, comp, output, discipline)
    disc_groups: dict[str, Any] = {}

    def host_of(disc: str | None) -> tuple[Any, str]:
        """The group housing a component + its connect-path prefix."""

        if disc is None:
            return group, ""
        if disc not in disc_groups:
            sub = group.add_subsystem(sanitize((disc,)), om.Group(), promotes_outputs=["*"])
            sub.options["auto_order"] = True
            disc_groups[disc] = sub
        return disc_groups[disc], f"{sanitize((disc,))}."

    for attr in named_members(interp, defn, ("attribute",)):
        name = attr.name or attr.short_name
        assert name is not None
        expr = attr.value.expr if attr.value is not None else None
        if expr is not None:  # external binding replaces the whole value
            calc = _resolve_calc(interp, defn, expr)
            if calc is not None and fid.mode(calc) == "external":
                assert isinstance(expr, A.Invocation)
                spec = external_binding(calc)
                assert spec is not None
                _guard_nested(interp, defn, expr, fid, f"{prefix}{name}", skip=expr)
                disc = _discipline(interp, defn, expr)
                host, path_prefix = host_of(disc)
                connections += _add_external(
                    om, interp, build, host, defn, name, expr, calc, spec, prefix, path_prefix
                )
                build.derived.append(f"{prefix}{name}")
                if disc is not None:
                    build.disciplines.setdefault(disc, []).append(f"{prefix}{name}")
                continue
        refs = _variable_refs(expr, instance) if expr is not None else {}
        if expr is None or not refs:
            value = instance.slots.get(name)
            if is_scalar(value):
                consts.append((name, float(value)))
                build.independents.append(f"{prefix}{name}")
            else:
                build.gaps.append(f"{prefix}{name}: non-scalar attribute skipped")
            continue
        _guard_nested(interp, defn, expr, fid, f"{prefix}{name}")
        disc = _discipline(interp, defn, expr)
        _, path_prefix = host_of(disc)
        comp_name = f"{sanitize((name,))}_comp"
        comps.append(
            (
                comp_name,
                _expr_component(interp, defn, name, expr, {sanitize(p): p for p in refs}),
                name,
                disc,
            )
        )
        connections += [(".".join(p), f"{path_prefix}{comp_name}.{sanitize(p)}") for p in refs]
        build.derived.append(f"{prefix}{name}")
        if disc is not None:
            build.disciplines.setdefault(disc, []).append(f"{prefix}{name}")

    for con in named_members(interp, defn, ("constraint",)):
        margin = _margin_expr(interp, con)
        if margin is None:
            build.gaps.append(f"{prefix}{con.label}: constraint body is not a comparison; skipped")
            continue
        refs = _variable_refs(margin, instance)
        _guard_nested(interp, defn, margin, fid, f"{prefix}{con.name or con.label}")
        out = f"{con.name or con.label}_margin"
        comp_name = f"{sanitize((out,))}_comp"
        comps.append(
            (
                comp_name,
                _expr_component(interp, defn, out, margin, {sanitize(p): p for p in refs}),
                out,
                None,  # requirement margins stay at the system level
            )
        )
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
            _populate(
                om, interp, build, sub, slot.definition, slot, prefix=f"{prefix}{name}.", fid=fid
            )
        elif isinstance(slot, list) and slot and isinstance(slot[0], Instance):
            for i, item in enumerate(slot):
                if item.definition is None:
                    continue
                sub = group.add_subsystem(f"{sanitize((name,))}_{i + 1}", om.Group())
                _populate(
                    om,
                    interp,
                    build,
                    sub,
                    item.definition,
                    item,
                    prefix=f"{prefix}{name}_{i + 1}.",
                    fid=fid,
                )
            if member is not None and _refs_into(defn, interp, name):
                build.gaps.append(
                    f"{prefix}{name}: references into sequence "
                    "parts are not connected (phase 2: arrays)"
                )

    for comp_name, comp, out, disc in comps:
        host, _ = host_of(disc)
        host.add_subsystem(comp_name, comp, promotes_outputs=[out])
    group.options["auto_order"] = True

    for src, tgt in connections:
        group.connect(src, tgt)


def _member_named(interp: Interpreter, defn: M.Definition | M.Usage, name: str) -> M.Usage | None:
    for m in interp.resolver.members_of(defn):
        if isinstance(m, M.Usage) and name in (m.name, m.short_name):
            return m
    return None


def _refs_into(defn: M.Definition | M.Usage, interp: Interpreter, slot_name: str) -> bool:
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
    return A.Unary("-", A.Invocation(("abs",), (A.Binary("-", expr.left, expr.right),)))


def _add_requirement(
    om: Any,
    interp: Interpreter,
    build: ProblemBuild,
    group: Any,
    req_name: str,
    subject_defn: M.Definition | M.Usage,
    instance: Instance,
    fid: _Fidelity,
) -> None:
    """Map a requirement's require-constraints to margin outputs at the root.

    The requirement's ``subject`` name is stripped from reference paths, so
    ``drone.totalMass`` connects to the root group's ``totalMass``.
    """

    req = interp.resolve(req_name)
    if not isinstance(req, (M.Definition, M.Usage)):
        raise AnalysisError(f"{req_name!r} is not a requirement")
    subjects = [
        m.name
        for m in interp.resolver.members_of(req)
        if isinstance(m, M.Usage) and m.kind == "subject" and m.name
    ]
    subject = subjects[0] if subjects else "subject"
    for con in named_members(interp, req, ("constraint",)):
        if con.constraint_kind == "assume":
            continue
        margin = _margin_expr(interp, con)
        if margin is None:
            build.gaps.append(f"{req.label}::{con.label}: not a comparison")
            continue
        stripped: dict[QName, str | QName] = {
            path: path[1:] for path in free_refs(margin) if path[0] == subject and len(path) > 1
        }
        margin = rewrite_refs(margin, stripped)
        refs = _variable_refs(margin, instance)
        _guard_nested(interp, req, margin, fid, f"{req.label}::{con.name or con.label}")
        out = f"{con.name or con.label}_margin"
        comp_name = f"{sanitize((req.label, out))}_comp"
        group.add_subsystem(
            comp_name,
            _expr_component(interp, req, out, margin, {sanitize(p): p for p in refs}),
            promotes_outputs=[out],
        )
        for p in refs:
            group.connect(".".join(p), f"{comp_name}.{sanitize(p)}")
        build.constraints[f"{req.label}::{con.name or con.label}"] = out


# ---------------------------------------------------------------------------
# optimization sugar
# ---------------------------------------------------------------------------


def add_optimization(
    build: ProblemBuild,
    objective: str,
    design_vars: dict[str, tuple[float, float]],
    maximize: bool = False,
    constraints: tuple[str, ...] | None = None,
) -> None:
    """Configure SLSQP over margin constraints; call before ``setup()``."""

    om = _om()
    prob = build.problem
    prob.driver = om.ScipyOptimizeDriver(optimizer="SLSQP", tol=1e-9)
    for name, (lower, upper) in design_vars.items():
        prob.model.add_design_var(name, lower=lower, upper=upper)
    prob.model.add_objective(objective, scaler=-1.0 if maximize else 1.0)
    names = (
        build.constraints if constraints is None else {c: build.constraints[c] for c in constraints}
    )
    for margin_var in names.values():
        prob.model.add_constraint(margin_var, lower=0.0)
