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

Object-valued I/O (the ratified ``docs/design/mdao-objects.md``) rides
OpenMDAO's stock discrete-variable machinery -- no fork, no patched
internals:

* ENTITY BINDING: a part/item member typed by a ``variation`` definition
  becomes ONE discrete input carrying the configured **M0 individual**
  (:class:`longeron.m0.Individual` -- resolved attribute values, stable
  ``qname#index`` identity, definition backlink), instead of a scalar
  shred.  The case being evaluated is an :class:`longeron.m0.
  Interpretation` (``build_problem(..., interpretation=...)``); without
  one, a model that has variation points lazily materializes the
  implicit anonymous interpretation (first declared variants -- the same
  choice the interpreter makes), and scalar-only models behave exactly
  as before.  :func:`bind_entity` rebinds a variation point to another
  individual (qname or instance, conformance-checked, pickle-checked);
  :func:`entity_cases` turns a trade study's variation points into
  ``om.ListGenerator``-shaped DOE cases whose values are individuals.
  Homogeneous ``[n]`` multiplicities bind their (shared) per-unit
  individual; per-index heterogeneous selection is deferred with the
  trades phase-2 item.
* RESULT RECORDING: :func:`record_case` returns a NEW immutable
  interpretation snapshot per case -- the case's individuals with the
  problem's outputs written onto their slots (stable ids, JSON-clean
  ``to_dict``).  The input interpretation stays pristine; in-place
  ``Instance.set()`` remains available for interactive use but is
  outside the recorded lifecycle.  :func:`case_values` feeds a snapshot
  straight into the scoreboard's ``values=`` seam.
* OBJECT FLOW: structured payloads (mesh dicts, cadquery *recipes* --
  never live kernel solids) move between components as discrete values,
  keyed by M0 individual id (``geometry.tag_parts``).  Serial OpenMDAO
  passes discretes BY REFERENCE: payloads are frozen by convention
  (producers emit fresh dicts, consumers never mutate).  Under MPI every
  discrete crossing a rank boundary is pickled -- picklability is
  asserted at bind time with an error naming the offender.
* FILE BOUNDARY: :class:`FileArtifact` (path + sha256 + media type)
  flows as a tiny discrete value while the bytes stay on disk --
  ``ExternalCodeComp``-compatible, recorder-friendly (its ``to_json`` is
  the lossless ``make_serializable`` hook), and the hash is the caching
  identity.  :func:`write_artifact` / :func:`file_artifact` build one;
  :func:`artifact_component` wraps a writer callable as a boundary
  component.  The matching SysML convention ships as
  ``examples/analysis_conventions.sysml`` (``item def FileArtifact``),
  so flows can be *typed* by it.
* ITEM-FLOW WIRING: :func:`derive_flows` resolves a part's
  ``flow of Payload from a.out to b.in`` usages against its action
  members and returns proposed OpenMDAO connections (endpoints
  validated, payload type checked against both ends);
  :func:`apply_flows` wires them.  Propose + apply, never silent magic.

Requires the ``mdao`` extra: ``pip install "longeron[mdao]"``.  OpenMDAO is
imported lazily so the module can be imported (for docs, dir()) without it.
"""

from __future__ import annotations

import hashlib
import importlib
import pickle
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, fields
from itertools import product
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import ast as A
from .. import model as M
from ..errors import EvaluationError, MissingExtraError
from ..interpreter import Instance, Interpreter
from ..m0 import Individual, Interpretation, interpret
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

if TYPE_CHECKING:
    from .trades import TradeStudy

__all__ = [
    "FileArtifact",
    "ProblemBuild",
    "add_optimization",
    "apply_flows",
    "artifact_component",
    "bind_entity",
    "build_problem",
    "calc_component",
    "case_values",
    "derive_flows",
    "entity_cases",
    "external_binding",
    "file_artifact",
    "record_case",
    "write_artifact",
]

_COMPARISONS = {"<", "<=", ">", ">=", "=="}


def _om() -> Any:
    try:
        import openmdao.api as om
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError("longeron.analysis.mdao", "OpenMDAO", "mdao") from err
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
    #: entity discrete inputs: promoted name -> variation definition qname
    entities: dict[str, str] = field(default_factory=dict)
    #: the case being evaluated (``None`` until :func:`record_case` or a
    #: variation point asks -- the design's lazy implicit interpretation)
    interpretation: Interpretation | None = None
    _interp: Interpreter | None = field(default=None, repr=False)
    _target: Any = field(default=None, repr=False)  # M.Definition | M.Usage


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
    interp: Interpreter,
    context: M.Namespace,
    out_name: str,
    expr: A.Expr,
    inputs: dict[str, QName],
    entities: dict[str, tuple[Any, list[QName]]] | None = None,
) -> Any:
    """A component evaluating ``expr`` with referenced paths as inputs.

    ``entities`` maps entity member names to ``(default_individual,
    referenced_paths)``: each becomes one discrete input carrying the M0
    individual, and its referenced leaves are read off the *bound* value
    per ``compute()`` -- so rebinding the entity re-evaluates the
    expression.  Slot leaves stay floats (the units design's invariant).
    """

    om = _om()
    entity_inputs = entities or {}
    flat_names: dict[QName, str | QName] = {path: name for name, path in inputs.items()}
    for _ent, (_default, paths) in entity_inputs.items():
        for path in paths:
            flat_names[path] = sanitize(path)
    flat = rewrite_refs(expr, flat_names)

    class _ExprComp(om.ExplicitComponent):  # type: ignore[name-defined]
        def setup(self) -> None:
            for name in inputs:
                self.add_input(name, val=1.0)
            for ent, (default, _paths) in entity_inputs.items():
                self.add_discrete_input(ent, val=default)
            self.add_output(out_name, val=0.0)
            if inputs:
                self.declare_partials(out_name, "*", method="fd")

        def compute(
            self, ins: Any, outs: Any, discrete_ins: Any = None, discrete_outs: Any = None
        ) -> None:
            frame: dict[str, Any] = {name: float(ins[name][0]) for name in inputs}
            for ent, (_default, paths) in entity_inputs.items():
                payload = discrete_ins[ent]
                if not isinstance(payload, Instance):
                    raise AnalysisError(
                        f"{out_name}: discrete input {ent!r} received "
                        f"{type(payload).__name__}, not an entity Instance"
                    )
                for path in paths:
                    value = payload.get(".".join(path[1:]))
                    frame[sanitize(path)] = float(value) if is_scalar(value) else value
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
    interpretation: Interpretation | None = None,
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

    ``interpretation`` is the M0 case being evaluated
    (:func:`longeron.m0.interpret`): free scalars seed from its slots,
    and every variation-typed part/item member becomes a **discrete
    input** carrying its configured individual (see :func:`bind_entity`
    to swap cases, :func:`record_case` to freeze results).  Without it,
    scalar-only models behave exactly as before; a model that has
    variation points materializes the implicit anonymous interpretation
    lazily (first declared variants, zero ceremony).
    """

    om = _om()
    interp = Interpreter(model)
    target = interp.resolve(part) if isinstance(part, str) else part
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{part!r} is not instantiable")
    if interpretation is None and _has_variation_members(interp, target):
        # the design's implicit anonymous interpretation: entity binding
        # asked for a point, so one materializes (first declared variants)
        interpretation = interpret(model, target)
    if interpretation is not None:
        instance: Instance = _case_root(target, interpretation)
    else:
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
    build = ProblemBuild(
        problem=prob, interpretation=interpretation, _interp=interp, _target=target
    )
    fid = _Fidelity(interp, fidelity)
    _populate(om, interp, build, prob.model, target, instance, prefix="", fid=fid)
    for req_name in requirements:
        _add_requirement(om, interp, build, prob.model, req_name, target, instance, fid)
    fid.check_all_used()
    if setup:
        prob.setup()
    return build


def _case_root(target: M.Definition | M.Usage, interpretation: Interpretation) -> Instance:
    """The interpretation's root individual, checked against the target."""

    root = interpretation.root
    if root.definition is not target and interpretation.source != (
        target.qualified_name or target.label
    ):
        raise AnalysisError(
            f"interpretation of {interpretation.source!r} cannot seed a problem for {target.label}"
        )
    return root


def _has_variation_members(
    interp: Interpreter, defn: M.Definition | M.Usage, _seen: set[int] | None = None
) -> bool:
    """Whether the part tree reaches any variation-typed part/item member."""

    seen = _seen if _seen is not None else set()
    if id(defn) in seen:
        return False
    seen.add(id(defn))
    for member in named_members(interp, defn, ("part", "item")):
        if not member.types:
            continue
        try:
            typ = interp.resolver.resolve(member.types[0], member.owner or defn)
        except Exception:
            continue
        if not isinstance(typ, (M.Definition, M.Usage)):
            continue
        if typ.is_variation:
            return True
        if _has_variation_members(interp, typ, seen):
            return True
    return False


def _entity_members(
    interp: Interpreter, defn: M.Definition | M.Usage
) -> dict[str, M.Definition | M.Usage]:
    """Named part/item members typed by a variation definition."""

    out: dict[str, M.Definition | M.Usage] = {}
    for member in named_members(interp, defn, ("part", "item")):
        if not member.types:
            continue
        try:
            typ = interp.resolver.resolve(member.types[0], member.owner or defn)
        except Exception:
            continue
        if isinstance(typ, (M.Definition, M.Usage)) and typ.is_variation:
            name = member.name or member.short_name
            assert name is not None
            out[name] = typ
    return out


def _entity_refs(
    expr: A.Expr, entities: Mapping[str, M.Definition | M.Usage]
) -> dict[str, list[QName]]:
    """Referenced paths grouped by the entity member they lead into."""

    out: dict[str, list[QName]] = {}
    for path in sorted(free_refs(expr)):
        if len(path) > 1 and path[0] in entities:
            out.setdefault(path[0], []).append(path)
    return out


def _entity_value(instance: Instance, name: str, prefix: str) -> Instance:
    """The individual bound to one entity member (per-unit for ``[n]``)."""

    value = instance.slots.get(name)
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, Instance):
        raise AnalysisError(
            f"{prefix}{name}: the interpretation provides no individual "
            f"for this variation point (got {value!r})"
        )
    return value


def _assert_picklable(name: str, value: Any) -> None:
    """The recipes-not-solids rule, enforced: discretes must pickle."""

    try:
        pickle.dumps(value)
    except Exception as err:
        raise AnalysisError(
            f"discrete payload {name!r} is not picklable "
            f"({type(value).__name__}: {err}); objects crossing the "
            "analysis boundary must pickle (MPI ranks, case recording) -- "
            "pass recipes or mesh dicts, never live kernel objects "
            "(the design's recipes-not-solids rule)"
        ) from err


@dataclass
class _AttrPlan:
    """How one attribute member maps onto the problem."""

    member: M.Usage
    name: str
    expr: A.Expr | None
    refs: set[QName] = field(default_factory=set)  # continuous connections
    entity_refs: dict[str, list[QName]] = field(default_factory=dict)
    baked: float | None = None  # per-unit fallback constant
    derived: bool = False  # becomes an expression component


def _attr_plans(
    interp: Interpreter,
    defn: M.Definition | M.Usage,
    instance: Instance,
    entities: Mapping[str, M.Definition | M.Usage],
    interpreted: bool,
) -> tuple[list[_AttrPlan], set[str]]:
    """Classify attribute members before emission.

    Without an interpretation this reproduces the historical rule
    exactly: an attribute is derived iff its expression references
    scalar leaves of the instantiated tree.  With one, classification
    is structural where population semantics hide values -- entity
    paths become discrete-input references, references to sibling
    outputs connect even when the M0 slot degraded to ``None`` (a
    ``sum()`` over four real individuals is a list, not a scalar), and
    expressions over homogeneous ``[n]`` sequences bake their per-unit
    value as a constant (matching ``instantiate()``'s head-of-sequence
    convention).  Returns the plans plus the names that will exist as
    promoted outputs at this level.
    """

    plans: list[_AttrPlan] = []
    for attr in named_members(interp, defn, ("attribute",)):
        name = attr.name or attr.short_name
        assert name is not None
        expr = attr.value.expr if attr.value is not None else None
        plan = _AttrPlan(attr, name, expr)
        if expr is not None:
            plan.refs = _variable_refs(expr, instance)
            if entities:
                plan.entity_refs = _entity_refs(expr, entities)
                plan.refs = {p for p in plan.refs if p[0] not in entities}
            plan.derived = bool(plan.refs or plan.entity_refs)
        plans.append(plan)
    produced = {
        plan.name for plan in plans if plan.derived or is_scalar(instance.slots.get(plan.name))
    }
    if not interpreted:
        return plans, produced
    for plan in plans:  # per-unit bake: the instantiate-path convention
        if plan.expr is not None and not plan.derived and plan.name not in produced:
            plan.baked = _bake_per_unit(interp, defn, plan.expr, instance)
            if plan.baked is not None:
                produced.add(plan.name)
    names = {plan.name for plan in plans}
    singles = {
        plan.name: {p[0] for p in free_refs(plan.expr) if len(p) == 1 and p[0] in names}
        for plan in plans
        if plan.expr is not None
    }
    changed = True
    while changed:  # sibling-output references promote to derived
        changed = False
        for plan in plans:
            if plan.expr is None or plan.derived:
                continue
            if singles.get(plan.name, set()) & produced:
                plan.derived = True
                plan.baked = None
                produced.add(plan.name)
                changed = True
    for plan in plans:
        if plan.derived and plan.expr is not None:
            plan.refs |= {(n,) for n in singles.get(plan.name, set()) & produced if n != plan.name}
    return plans, produced


def _per_unit_path(instance: Instance, parts: QName) -> Any:
    """Walk a path taking list heads: the homogeneous per-unit reading."""

    node: Any = instance
    for part in parts:
        if isinstance(node, list):
            node = node[0] if node else None
        if not isinstance(node, Instance) or part not in node.slots:
            return None
        node = node.slots[part]
    if isinstance(node, list):
        node = node[0] if node else None
    return node


def _bake_per_unit(
    interp: Interpreter, defn: M.Definition | M.Usage, expr: A.Expr, instance: Instance
) -> float | None:
    """Evaluate an expression per-unit over the interpretation's tree."""

    frame: dict[str, Any] = {}
    mapping: dict[QName, str | QName] = {}
    for path in free_refs(expr):
        value = _per_unit_path(instance, path)
        if is_scalar(value):
            mapping[path] = sanitize(path)
            frame[sanitize(path)] = float(value)
    if not mapping:
        return None
    flat = rewrite_refs(expr, mapping)
    try:
        value = interp.evaluate(flat, defn, **frame)
    except (EvaluationError, TypeError):
        return None
    return float(value) if is_scalar(value) else None


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
    entities = _entity_members(interp, defn) if build.interpretation is not None else {}
    entity_binds: dict[str, Any] = {}
    for ent_name, point in entities.items():
        individual = _entity_value(instance, ent_name, prefix)
        _assert_picklable(f"{prefix}{ent_name}", individual)
        entity_binds[ent_name] = individual
        build.entities[f"{prefix}{ent_name}"] = point.qualified_name or point.label

    def host_of(disc: str | None) -> tuple[Any, str]:
        """The group housing a component + its connect-path prefix."""

        if disc is None:
            return group, ""
        if disc not in disc_groups:
            sub = group.add_subsystem(sanitize((disc,)), om.Group(), promotes_outputs=["*"])
            sub.options["auto_order"] = True
            disc_groups[disc] = sub
        return disc_groups[disc], f"{sanitize((disc,))}."

    plans, produced = _attr_plans(
        interp, defn, instance, entities, interpreted=build.interpretation is not None
    )
    for plan in plans:
        name, expr = plan.name, plan.expr
        if expr is not None:  # external binding replaces the whole value
            calc = _resolve_calc(interp, defn, expr)
            if calc is not None and fid.mode(calc) == "external":
                assert isinstance(expr, A.Invocation)
                spec = external_binding(calc)
                assert spec is not None
                if entities:
                    ent_args = sorted({p[0] for p in free_refs(expr) if p[0] in entities})
                    if ent_args:
                        raise AnalysisError(
                            f"{prefix}{name}: external binding of {calc.label} "
                            f"passes entity argument(s) {ent_args}; entity-valued "
                            "external contracts are not supported yet (select "
                            "fidelity 'model')"
                        )
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
        if not plan.derived:
            value = plan.baked if plan.baked is not None else instance.slots.get(name)
            if is_scalar(value):
                consts.append((name, float(value)))
                build.independents.append(f"{prefix}{name}")
            else:
                build.gaps.append(f"{prefix}{name}: non-scalar attribute skipped")
            continue
        assert expr is not None
        refs, entity_refs = plan.refs, plan.entity_refs
        _guard_nested(interp, defn, expr, fid, f"{prefix}{name}")
        disc = _discipline(interp, defn, expr)
        _, path_prefix = host_of(disc)
        comp_name = f"{sanitize((name,))}_comp"
        comps.append(
            (
                comp_name,
                _expr_component(
                    interp,
                    defn,
                    name,
                    expr,
                    {sanitize(p): p for p in refs},
                    {e: (entity_binds[e], paths) for e, paths in entity_refs.items()},
                ),
                name,
                disc,
            )
        )
        connections += [(".".join(p), f"{path_prefix}{comp_name}.{sanitize(p)}") for p in refs]
        connections += [(e, f"{path_prefix}{comp_name}.{e}") for e in entity_refs]
        build.derived.append(f"{prefix}{name}")
        if disc is not None:
            build.disciplines.setdefault(disc, []).append(f"{prefix}{name}")

    for con in named_members(interp, defn, ("constraint",)):
        margin = _margin_expr(interp, con)
        if margin is None:
            build.gaps.append(f"{prefix}{con.label}: constraint body is not a comparison; skipped")
            continue
        refs = _variable_refs(margin, instance)
        entity_refs = _entity_refs(margin, entities) if entities else {}
        if entities:
            refs = {p for p in refs if p[0] not in entities}
        if build.interpretation is not None:
            refs |= {p for p in free_refs(margin) if len(p) == 1 and p[0] in produced}
        _guard_nested(interp, defn, margin, fid, f"{prefix}{con.name or con.label}")
        out = f"{con.name or con.label}_margin"
        comp_name = f"{sanitize((out,))}_comp"
        comps.append(
            (
                comp_name,
                _expr_component(
                    interp,
                    defn,
                    out,
                    margin,
                    {sanitize(p): p for p in refs},
                    {e: (entity_binds[e], paths) for e, paths in entity_refs.items()},
                ),
                out,
                None,  # requirement margins stay at the system level
            )
        )
        connections += [(".".join(p), f"{comp_name}.{sanitize(p)}") for p in refs]
        connections += [(e, f"{comp_name}.{e}") for e in entity_refs]
        build.constraints[f"{prefix}{con.name or con.label}"] = f"{prefix}{out}"

    # dependency order: independents and child parts first, then derived
    # expressions (auto_order untangles derived-to-derived references)
    if consts or entity_binds:
        ivc = om.IndepVarComp()
        for name, value in consts:
            ivc.add_output(name, val=value)
        for ent_name, individual in entity_binds.items():
            ivc.add_discrete_output(ent_name, val=individual)
        group.add_subsystem("consts", ivc, promotes=["*"])

    for name, slot in instance.slots.items():
        if name in entities:
            continue  # bound as a discrete entity input, not a sub-group
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
        if build.interpretation is not None:
            # population semantics can hide root-output refs (None/list
            # slots); connect by structure like the _populate plans do
            root_outputs = {n for n in (*build.independents, *build.derived) if "." not in n}
            refs |= {p for p in free_refs(margin) if len(p) == 1 and p[0] in root_outputs}
            entity_headed = {p for p in refs if p[0] in build.entities}
            if entity_headed:
                refs -= entity_headed
                build.gaps.append(
                    f"{req.label}::{con.name or con.label}: references into "
                    f"entity members {sorted('.'.join(p) for p in entity_headed)} "
                    "are not connected (requirements read subject outputs)"
                )
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


# ---------------------------------------------------------------------------
# entity binding (tier 1): discrete cases as M0 individuals
# ---------------------------------------------------------------------------


def bind_entity(build: ProblemBuild, feature: str, entity: str | Instance) -> None:
    """Rebind a variation point to an individual (the discrete case swap).

    ``feature`` is a promoted entity input of the build (see
    ``ProblemBuild.entities``); ``entity`` is either an
    :class:`~longeron.interpreter.Instance` (typically an
    :class:`~longeron.m0.Individual` from :func:`longeron.m0.interpret`
    or :func:`entity_cases`) or a qualified name resolved through the
    model -- a catalog part def (``"UavMissions::EcoMotor"``) or a
    variant usage (``"P::MotorChoice::light"``, which keeps its inline
    ``:>>`` redefinitions).  The individual's definition is checked for
    conformance against the variation point's base type, and the payload
    must pickle (MPI ranks, case recording).  Call between ``setup()``
    and ``run_model()``; homogeneous ``[n]`` members rebind their shared
    per-unit individual.
    """

    if feature not in build.entities:
        known = sorted(build.entities)
        raise AnalysisError(
            f"{feature!r} is not an entity input of this problem "
            f"(entities: {known or 'none -- the model has no variation points'})"
        )
    interp = build._interp
    assert interp is not None
    if isinstance(entity, str):
        resolved = interp.resolver.resolve(entity)
        if not isinstance(resolved, (M.Definition, M.Usage)):
            raise AnalysisError(f"{entity!r} does not name an instantiable definition or usage")
        if resolved.is_variation:
            raise AnalysisError(
                f"{entity!r} is a variation definition; bind a concrete "
                "variant or catalog entry, not the whole choice space"
            )
        individual: Instance = interpret(interp.model, resolved).root
    elif isinstance(entity, Instance):
        individual = entity
    else:
        raise AnalysisError(
            f"cannot bind {type(entity).__name__} as an entity (pass a "
            "qualified name or an Instance/Individual)"
        )
    _check_conformance(interp, feature, individual, build.entities[feature])
    _assert_picklable(feature, individual)
    build.problem.set_val(feature, individual)


def _check_conformance(
    interp: Interpreter, feature: str, individual: Instance, point_qname: str
) -> None:
    """The individual's definition must conform to the variation point's
    base type (the variation def itself, or one of its ``:>`` bases)."""

    if individual.definition is None:
        raise AnalysisError(
            f"cannot bind {feature!r}: the individual has no definition to conformance-check"
        )
    try:
        point = interp.resolver.resolve(point_qname)
    except Exception:  # the point resolved at build time; stay permissive
        return
    if not isinstance(point, (M.Definition, M.Usage)):
        return
    bases: list[M.Element] = [point]
    for super_name in getattr(point, "supers", []):
        try:
            bases.append(interp.resolver.resolve(super_name, point.owner or interp.model))
        except Exception:
            continue
    for base in bases:
        try:
            if interp._conforms(individual.definition, base):
                return
        except Exception:
            continue
    raise AnalysisError(
        f"cannot bind {feature!r}: {individual.definition.label} does not "
        f"conform to the variation point's base type ({point.label})"
    )


def entity_cases(study: TradeStudy, *points: str) -> list[list[tuple[str, Any]]]:
    """DOE cases over a trade study's catalog: one case per mix.

    Walks the study's variation points (all of them, or the named
    subset) and returns the full Cartesian product in
    ``om.ListGenerator`` shape -- one ``[(point, individual), ...]``
    list per case, where each value is the variant's **M0 individual**
    (:func:`longeron.m0.interpret` of the variant usage, so inline
    ``:>>`` redefinitions are honored).  Feed them to a ``DOEDriver``
    after ``add_design_var()``-ing each point::

        cases = mdao.entity_cases(study, "motors", "props")
        build.problem.model.add_design_var("motors")
        build.problem.model.add_design_var("props")
        build.problem.driver = om.DOEDriver(om.ListGenerator(cases))

    The verify design's covering arrays slot in later as another
    generator of the same currency: a population of interpretations.
    """

    names = list(points) if points else list(study.points)
    unknown = sorted(set(names) - set(study.points))
    if unknown:
        raise AnalysisError(f"unknown variation point(s) {unknown} (have: {sorted(study.points)})")
    interp = study.interp
    per_point = [
        [interpret(interp.model, usage).root for usage in _variant_usages(interp, study, name)]
        for name in names
    ]
    return [
        [(name, individual) for name, individual in zip(names, combo, strict=True)]
        for combo in product(*per_point)
    ]


def _variant_usages(interp: Interpreter, study: TradeStudy, pname: str) -> list[M.Usage]:
    """The variant usages behind one of the study's variation points."""

    member = None
    for m in named_members(interp, study.assembly, ("part", "item")):
        if pname in (m.name, m.short_name):
            member = m
    if member is None or not member.types:
        raise AnalysisError(f"{pname!r} is not a variation point of {study.assembly.label}")
    typ = interp.resolver.resolve(member.types[0], member.owner or study.assembly)
    if not (isinstance(typ, (M.Definition, M.Usage)) and typ.is_variation):
        raise AnalysisError(f"{pname!r} is not typed by a variation definition")
    variants = [v for v in typ.members if isinstance(v, M.Usage) and v.is_variant and v.name]
    if not variants:
        raise AnalysisError(f"{typ.label} declares no named variants")
    return variants


# ---------------------------------------------------------------------------
# result recording: a case is an interpretation, results land on a snapshot
# ---------------------------------------------------------------------------


def record_case(build: ProblemBuild, outputs: Mapping[str, Any] | None = None) -> Interpretation:
    """A new interpretation snapshot: the case's individuals + the outputs.

    Call after ``run_model()``.  The build's interpretation (created
    lazily when absent -- the design's implicit anonymous point) is
    copied, rebound entities are reflected (their positional individual
    ids stay stable across mixes), and every promoted output lands as an
    attribute value on the matching individual's slot.  ``outputs``
    overrides the default set (independents + derived attributes +
    constraint margins, read from the problem).  The result is an
    immutable-by-convention snapshot: the input interpretation stays
    pristine, re-recording never overwrites evidence, ``to_dict()`` is
    JSON-clean, and ``rollup()``/:func:`case_values` work as usual.
    Values that fit no slot path are noted in the snapshot's ``gaps``.
    """

    source = _ensure_interpretation(build)
    prob = build.problem
    root = _copy_individual(source.root)
    assert isinstance(root, Individual)
    snapshot = Interpretation(
        source=source.source,
        strategy=source.strategy,
        seed=source.seed,
        root=root,
        selection=dict(source.selection),
        gaps=list(source.gaps),
        _interpreter=source._interpreter,
        _bindings=dict(source._bindings),
        _pins=dict(source._pins),
    )
    for feature in build.entities:
        _reflect_binding(source.root, snapshot, feature, prob.get_val(feature))
    if outputs is None:
        values: dict[str, Any] = {}
        for name in (*build.independents, *build.derived, *build.constraints.values()):
            values[name] = float(prob.get_val(name)[0])
    else:
        values = dict(outputs)
    for name, value in values.items():
        try:
            _snapshot_set(root, name, value)
        except EvaluationError as err:
            snapshot.gaps.append(f"{name}: not recorded ({err})")
    return snapshot


def case_values(case: Interpretation) -> dict[str, Any]:
    """A scoreboard ``values=`` dict from a recorded case snapshot.

    The snapshot's root-level scalar (and boolean) slots, keyed by
    feature name -- the same shape as
    :func:`~longeron.analysis.scoreboard.architecture_values`, so
    ``scoreboard(model, values=case_values(snapshot))`` scores a
    recorded case directly.
    """

    return {
        name: value
        for name, value in case.root.slots.items()
        if is_scalar(value) or isinstance(value, bool)
    }


def _ensure_interpretation(build: ProblemBuild) -> Interpretation:
    """The build's case, materialized lazily (design Q1: the implicit
    anonymous interpretation appears only when something asks)."""

    if build.interpretation is None:
        interp, target = build._interp, build._target
        assert interp is not None and target is not None
        build.interpretation = interpret(interp.model, target)
    return build.interpretation


def _copy_case_value(value: Any) -> Any:
    if isinstance(value, Instance):
        return _copy_individual(value)
    if isinstance(value, list):
        return [_copy_case_value(item) for item in value]
    return value


def _copy_individual(node: Instance, ident: str | None = None) -> Instance:
    """A structural copy sharing the (never-mutated) M1 definitions."""

    clone: Instance
    if isinstance(node, Individual):
        clone = Individual(ident or node.id, node.type_name, node.definition)
    else:
        clone = Instance(node.type_name, node.definition)
    clone.slots = {name: _copy_case_value(value) for name, value in node.slots.items()}
    return clone


_SEQ_HOP = re.compile(r"(.+)_(\d+)$")


def _snapshot_hop(node: Any, part: str, path: str) -> Any:
    """One step along a promoted name; ``motors_2`` reaches ``motors[1]``."""

    if isinstance(node, Instance):
        if part in node.slots:
            return node.slots[part]
        matched = _SEQ_HOP.match(part)
        if matched and matched.group(1) in node.slots:
            seq = node.slots[matched.group(1)]
            index = int(matched.group(2)) - 1
            if isinstance(seq, list) and 0 <= index < len(seq):
                return seq[index]
    raise EvaluationError(f"cannot traverse {part!r} in {path!r}")


def _snapshot_set(root: Instance, path: str, value: Any) -> None:
    """Write a promoted output onto the snapshot (final slot may be new)."""

    parts = path.split(".")
    node: Any = root
    for part in parts[:-1]:
        node = _snapshot_hop(node, part, path)
    if not isinstance(node, Instance):
        raise EvaluationError(f"cannot set {parts[-1]!r} in {path!r}")
    node.slots[parts[-1]] = value


def _reflect_binding(
    original_root: Instance, snapshot: Interpretation, feature: str, bound: Any
) -> None:
    """Mirror a rebound entity into the snapshot, keeping positional ids."""

    if not isinstance(bound, Instance):
        return
    parts = feature.split(".")
    original: Any = original_root
    node: Any = snapshot.root
    for part in parts[:-1]:
        original = _snapshot_hop(original, part, feature)
        node = _snapshot_hop(node, part, feature)
    if not isinstance(original, Instance) or not isinstance(node, Instance):
        return
    leaf = parts[-1]
    current = original.slots.get(leaf)
    if current is bound or (isinstance(current, list) and any(item is bound for item in current)):
        return  # never rebound: the interpretation's own individual
    if isinstance(current, list):
        node.slots[leaf] = [
            _copy_individual(bound, item.id if isinstance(item, Individual) else None)
            for item in current
        ] or [_copy_individual(bound)]
    else:
        ident = current.id if isinstance(current, Individual) else None
        node.slots[leaf] = _copy_individual(bound, ident)
    definition = bound.definition
    if definition is not None and (definition.name or definition.label):
        snapshot.selection[feature] = definition.name or definition.label


# ---------------------------------------------------------------------------
# the file boundary (tier 3): FileArtifact
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FileArtifact:
    """A file crossing the analysis boundary: a path plus content identity.

    Flows as a tiny discrete value while the bytes stay on disk.  The
    hash is the caching identity (same recipe, same hash -- skip the
    external run) and the recorder-bloat fix: ``to_json`` is the hook
    OpenMDAO's ``make_serializable`` tries first, so a recorded case
    reads back this record losslessly instead of megabytes of payload
    (or a silent class-name string).  Consumers hand ``path`` to
    ``ExternalCodeComp``'s ``external_input_files`` or their own
    subprocess.  The matching SysML convention is the
    ``item def FileArtifact`` in ``examples/analysis_conventions.sysml``
    (attributes ``path``/``sha256``/``mediaType``), so flows can be
    typed by it.
    """

    path: str
    sha256: str
    media_type: str = "application/octet-stream"

    def to_json(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256, "media_type": self.media_type}


def file_artifact(path: str | Path, media_type: str = "application/octet-stream") -> FileArtifact:
    """A :class:`FileArtifact` for an existing file (contents hashed)."""

    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return FileArtifact(path=str(path), sha256=digest.hexdigest(), media_type=media_type)


def write_artifact(
    path: str | Path, data: bytes | str, media_type: str = "application/octet-stream"
) -> FileArtifact:
    """Write ``data`` (str encodes as UTF-8) and return its artifact."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
    target.write_bytes(payload)
    return FileArtifact(
        path=str(target), sha256=hashlib.sha256(payload).hexdigest(), media_type=media_type
    )


def artifact_component(
    write: Callable[[Any, str], str | Path],
    directory: str | Path,
    *,
    payload: str = "payload",
    artifact: str = "artifact",
    media_type: str = "application/octet-stream",
    payload_default: Any = None,
) -> Any:
    """A boundary component: write the payload to disk, emit the artifact.

    ``write(payload_value, directory)`` produces the file (STEP, STL,
    JSON, ...) and returns its path; the component hashes it and emits a
    :class:`FileArtifact` as the ``artifact`` discrete output.  This is
    the ``ExternalCodeComp``-compatible pattern: downstream components
    (or the external code's ``external_input_files``) consume the path,
    the recorder sees ~200 bytes of JSON.  Key ``directory`` per case
    (e.g. by interpretation id + case counter) so concurrent DOE cases
    never collide.  ``payload_default`` types the discrete input's
    default (OpenMDAO checks connection compatibility by ``isinstance``
    on declared defaults; the default ``{}`` suits mesh/recipe dicts).
    """

    om = _om()
    default = {} if payload_default is None else payload_default
    workdir = Path(directory)
    workdir.mkdir(parents=True, exist_ok=True)

    class _ArtifactComp(om.ExplicitComponent):  # type: ignore[name-defined]
        def setup(self) -> None:
            self.add_discrete_input(payload, val=default)
            self.add_discrete_output(artifact, val=FileArtifact(path="", sha256=""))

        def compute(
            self, ins: Any, outs: Any, discrete_ins: Any = None, discrete_outs: Any = None
        ) -> None:
            written = Path(write(discrete_ins[payload], str(workdir)))
            if not written.is_file():
                raise AnalysisError(
                    f"artifact writer returned {str(written)!r}, which is not a file"
                )
            discrete_outs[artifact] = file_artifact(written, media_type=media_type)

    return _ArtifactComp()


# ---------------------------------------------------------------------------
# SysML integration (tier 4): item flows -> proposed connections
# ---------------------------------------------------------------------------

# The resolution semantics deliberately mirror validate()'s landed flow
# diagnostics (validation.py: check_flow / check_flow_payload) -- the
# segment-wise resolver walk for endpoints, the payload-text parsing
# ('T' / 'x : T' / 'x : T1, T2'), declared-types collection, and the
# 'only speak when two KNOWN things conflict' idiom with either-direction
# conformance.  Intentional divergences (an API about to wire connections
# cannot shrug):
#   * dangling endpoints RAISE here (validate() warns dangling-flow);
#   * parameter direction is checked (out/inout -> in/inout: an OpenMDAO
#     connect() needs it; validation has no direction diagnostic);
#   * builtin scalar payload names (Real & co) are checked BY NAME --
#     the validator's resolver cannot see grammar-level builtins and
#     stays silent there (a unification candidate).

#: builtin scalar value types never reach the resolver (grammar-level)
_SCALAR_TYPE_NAMES = frozenset({"Real", "Integer", "Boolean", "String", "Natural", "Rational"})


def derive_flows(
    model: M.Model, part: str | M.Definition | M.Usage
) -> list[tuple[str, str, str | None]]:
    """Resolved (source, target, payload qname) triples from a part's flows.

    Each ``flow of Payload from a.out to b.in`` usage is resolved
    against the part's members through the resolver's specialization
    walk (the same semantics as ``validate()``'s ``dangling-flow`` /
    ``flow-payload-mismatch`` diagnostics): every endpoint must resolve,
    the source's final hop must be an ``out``/``inout`` parameter, the
    target's an ``in``/``inout`` parameter, and -- when both the payload
    typing and the target end's typing are KNOWN -- some pair of them
    must be related by specialization in either direction.  Violations
    raise :class:`AnalysisError` naming the offending endpoint; unknown
    typing stays silent, exactly like the validator.  Succession flows
    (control ordering, no payload) are skipped.

    The triples are *proposals*: pass them to :func:`apply_flows` to
    wire an OpenMDAO problem whose component names mirror the action
    names.  Nothing is connected implicitly.
    """

    interp = Interpreter(model)
    target = interp.resolve(part) if isinstance(part, str) else part
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{part!r} is not a part definition or usage")
    triples: list[tuple[str, str, str | None]] = []
    for member in interp.resolver.members_of(target):
        if not isinstance(member, M.FlowUsage) or member.is_succession:
            continue
        if not member.source or not member.target_end:
            continue  # endpoint-less flow renderings carry nothing to wire
        src = _flow_end(interp, target, member, member.source, "source")
        tgt = _flow_end(interp, target, member, member.target_end, "target")
        if not isinstance(src, M.Usage) or src.direction not in ("out", "inout"):
            raise AnalysisError(
                f"{target.label}: flow source '{member.source}' is not an "
                f"'out' parameter (direction: "
                f"{getattr(src, 'direction', None) or 'none'})"
            )
        if not isinstance(tgt, M.Usage) or tgt.direction not in ("in", "inout"):
            raise AnalysisError(
                f"{target.label}: flow target '{member.target_end}' is not an "
                f"'in' parameter (direction: "
                f"{getattr(tgt, 'direction', None) or 'none'})"
            )
        triples.append(
            (member.source, member.target_end, _flow_payload(interp, target, member, tgt))
        )
    return triples


def apply_flows(target: Any, flows: Iterable[tuple[str, str, str | None]]) -> None:
    """Wire derived flow triples as ``connect()`` calls (before setup).

    ``target`` is a :class:`ProblemBuild`, an ``om.Problem``, or a
    group; components are expected under the action names the endpoints
    use (``build.mesh -> rcs.mesh`` connects component ``build``'s
    ``mesh`` output to component ``rcs``'s ``mesh`` input, discrete or
    continuous).
    """

    group = target
    if isinstance(target, ProblemBuild):
        group = target.problem.model
    elif hasattr(target, "model") and not hasattr(target, "connect"):
        group = target.model
    for source, sink, _payload in flows:
        group.connect(source, sink)


def _flow_path(interp: Interpreter, context: M.Element, ref: str) -> M.Element | None:
    """Resolve a dotted path from ``context``'s scope; ``None`` on failure.

    The shared walk behind the validator's flow checks: each segment
    resolves through the resolver (specialization walk included),
    starting from the owning scope; ``$`` re-anchors at the model root.
    """

    scope: M.Element = context.owner if context.owner is not None else interp.model
    for segment in ref.split("."):
        if segment == "$":
            scope = interp.model
            continue
        try:
            scope = interp.resolver.resolve(segment, scope)
        except Exception:
            return None
    return scope


def _flow_end(
    interp: Interpreter,
    part: M.Definition | M.Usage,
    flow: M.FlowUsage,
    endpoint: str,
    role: str,
) -> M.Element:
    """Resolve one dotted flow endpoint, loudly (validate() warns here)."""

    resolved = _flow_path(interp, flow if flow.owner is not None else part, endpoint)
    if resolved is None:
        raise AnalysisError(f"{part.label}: flow {role} '{endpoint}' does not resolve")
    return resolved


def _payload_type_refs(payload: str) -> list[str]:
    """Type references declared by the payload feature text.

    The model keeps the payload as canonical text (``'x : T'`` / ``'T'``
    / ``'x : T1, T2'``); the part after the colon is the declared
    typing, and a colon-free payload is a single reference.
    """

    if ":" in payload:
        return [t.strip() for t in payload.split(":", 1)[1].split(",") if t.strip()]
    return [payload.strip()] if payload.strip() else []


def _declared_types(
    interp: Interpreter, element: M.Element | None
) -> tuple[list[M.Element], set[str]]:
    """The declared typing behind a resolved reference, plus any builtin
    scalar type names (which never resolve to elements): a definition is
    its own type, a usage contributes its resolved ``types``."""

    if element is None:
        return [], set()
    if isinstance(element, M.Definition):
        return [element], set()
    names: list[str] = []
    if isinstance(element, M.AcceptAction):
        names = list(element.payload_types)
    elif isinstance(element, M.Usage):
        names = list(element.types)
    out: list[M.Element] = []
    scalars: set[str] = set()
    for name in names:
        clean = name.lstrip("~")
        resolved = _flow_path(interp, element, clean)
        if resolved is not None:
            out.append(resolved)
        elif clean.split("::")[-1] in _SCALAR_TYPE_NAMES:
            scalars.add(clean.split("::")[-1])
    return out, scalars


def _flow_payload(
    interp: Interpreter,
    part: M.Definition | M.Usage,
    flow: M.FlowUsage,
    tgt: M.Element,
) -> str | None:
    """The payload's resolved qname; mismatch check against the target end.

    Honest like the validator: the check speaks only when *both* the
    payload typing and the target end's typing are known, and no pair is
    related by the specialization walk in either direction (a supertype
    payload may still hold a conforming value at runtime).
    """

    if not flow.payload:
        return None
    context: M.Element = flow if flow.owner is not None else part
    payload_types: list[M.Element] = []
    payload_scalars: set[str] = set()
    for ref in _payload_type_refs(flow.payload):
        clean = ref.lstrip("~")
        if clean.split("::")[-1] in _SCALAR_TYPE_NAMES:
            payload_scalars.add(clean.split("::")[-1])
            continue
        resolved = _flow_path(interp, context, clean)
        if resolved is None:
            return None  # unresolved payload: no guessing (idiom-aligned)
        types, scalars = _declared_types(interp, resolved)
        if isinstance(resolved, M.Definition):
            payload_types.extend(types)
        elif not types and not scalars:
            return _qname(resolved)  # untyped payload feature: known name, no typing
        else:
            payload_types.extend(types)
            payload_scalars |= scalars
    if not payload_types and not payload_scalars:
        return None
    qname = _qname(payload_types[0]) if payload_types else sorted(payload_scalars)[0]
    accepted, accepted_scalars = _declared_types(interp, tgt)
    if not accepted and not accepted_scalars:
        return qname  # untyped or dangling target typing: silent here
    for payload_type in payload_types:
        for target_type in accepted:
            for a, b in ((payload_type, target_type), (target_type, payload_type)):
                try:
                    if interp._conforms(a, b):
                        return qname
                except Exception:
                    continue
    if payload_scalars & accepted_scalars:
        return qname
    names = ", ".join(repr(t.label) for t in accepted) or ", ".join(
        repr(s) for s in sorted(accepted_scalars)
    )
    raise AnalysisError(
        f"{part.label}: payload {flow.payload!r} is incompatible with flow "
        f"target '{flow.target_end}' (accepts {names})"
    )


def _qname(element: M.Element) -> str:
    return element.qualified_name or element.label
