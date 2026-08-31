"""Model-declared analysis surfaces: derive the dashboard from the model.

Design: ``docs/design/surfaces.md`` (adopted
2026-08-30), phase 1.  A dashboard is a standard **view usage**: its
``expose`` members select the content -- a subject plus analysis and
verification cases -- and each panel is a nested view usage whose
``render`` reference names a ``LongeronSurfaces`` rendering (the
vendored-stdlib-adjacent extension library).  :func:`surface` turns
that declaration into a composed ipywidgets surface:

* each **analysis case** becomes a what-if card: its ``in`` parameters
  are sliders whose bounds are MINED from the model's own constraints
  (:func:`longeron.analysis.verify.attribute_domains` -- ``assume``
  constraints in the case objective, or the subject's own constraint
  bounds reached through the parameter's default binding), the
  ``@ToolExecution`` annotation names the engine that re-measures on
  every move, and the named returns are the readout;
* each **verification case** becomes a verdict panel: the ``verify``
  members name the requirement rows, evaluated through the interpreter
  (:meth:`~longeron.interpreter.Interpreter.check_requirement`), with
  the verdict stated in the standard's ``VerdictKind`` vocabulary
  (``pass`` / ``fail`` / ``inconclusive`` / ``error``);
* results flow between panels ONLY through the model's explicit result
  bindings (``attribute :>> measured = case.result;`` -- the corpus
  spelling, and the one spelling recognized); a case result no binding
  names is listed in the wiring map as an ``unbound`` diagnostic, so a
  forgotten coupling is loud;
* **subject typing is the applicability test**: a case applies to the
  surface's subject when the subject's specialization chain reaches the
  case's declared subject type.  A case that does not apply renders as
  HONEST ABSENCE -- the panel stays in the layout, dimmed, stating the
  subject type it needs -- and swapping the subject
  (``surface(..., subject=...)``, the picker dropdown, or
  ``box.swap(...)``) re-derives every panel.

The returned widget carries the derivation as data: ``box.panels`` (one
:class:`Panel` per declared subview) and ``box.wiring`` -- the printable
:class:`WiringMap` recording which binding fired for every coupling,
the range source per slider, unbound results, and honest absences.

Renderings bind to widget builders through :data:`RENDERINGS`, a Python
registry keyed by rendering qualified name (the
``longeron.views.VIEW_DEFINITIONS`` mapping-table precedent).  Phase 1
registers the two engine-built panels the proof needs (the what-if card
and the verdict cards); the remaining vocabulary entries are declared
and render as honest absence until their builders land.

Requires the ``viz`` extra for the widgets:
``pip install "longeron[viz]"``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, cast

from .. import ast as A
from .. import model as M
from ..errors import EvaluationError, MissingExtraError, ResolutionError, SysMLError
from ..interpreter import Instance, Interpreter, RequirementResult
from ..stdlib import standard_library_model
from ..views import expose_closure
from ._expr import AnalysisError
from .dashboard import _ipywidgets
from .grand import _BAD, _CARD_STYLE, _DIM, _GRAND_CSS, _NUM, _OK, _TITLE_STYLE
from .verify import _FALLBACK_BOUNDS, Domain, attribute_domains

__all__ = [
    "RANGE_FALLBACK",
    "RANGE_MINED",
    "RANGE_OVERRIDDEN",
    "RENDERINGS",
    "Coupling",
    "Panel",
    "RangeInfo",
    "SurfaceWidget",
    "VerdictKind",
    "WiringMap",
    "surface",
]

#: the standard ``VerdictKind`` vocabulary a verdict panel aggregates to
#: (``"error"`` is the honest extra state: the evaluation itself failed),
#: cross-asserted against the tone table by the test suite
VerdictKind = Literal["pass", "fail", "inconclusive", "error"]

#: rendering qualified name -> the widgets-catalog entry (or engine-built
#: panel) it names; the registry the ``render`` references dispatch
#: through.  A rendering with no phase-1 builder renders as honest
#: absence naming this table.
RENDERINGS: dict[str, str] = {
    "LongeronSurfaces::asStructureDiagram": "structure_diagram",
    "LongeronSurfaces::asStateDiagram": "state_diagram",
    "LongeronSurfaces::asActionDiagram": "action_diagram",
    "LongeronSurfaces::asMeshViewer": "mesh_viewer",
    "LongeronSurfaces::asScoreboard": "scoreboard",
    "LongeronSurfaces::asWhatIfCard": "what-if card",
    "LongeronSurfaces::asSizingCards": "sizing cards",
    "LongeronSurfaces::asVerdictCards": "verdict cards",
    "LongeronSurfaces::asMissionGlobe": "mission_viewer",
    "LongeronSurfaces::asReplayPlayer": "replay_widget",
}

#: the engine-built panel kinds phase 1 knows how to derive
_BUILT = ("what-if card", "verdict cards")

#: the wiring map's range-source vocabulary (honesty requirement: the
#: printable map states, per slider, where its bounds came from)
RANGE_MINED = "mined-from-constraint"
RANGE_OVERRIDDEN = "overridden-by-caller"
RANGE_FALLBACK = "fallback"

_CASE_KINDS = ("analysis", "verification", "case")


# ---------------------------------------------------------------------------
# the derivation record: panels + the wiring map
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RangeInfo:
    """One derived slider's bounds, with their provenance.

    ``source`` is one of :data:`RANGE_MINED` (suffixed with the mined
    constraints' qualified names), :data:`RANGE_OVERRIDDEN`, or
    :data:`RANGE_FALLBACK`.  An override never erases what the model
    states: ``mined_lo`` / ``mined_hi`` keep the constraint bounds, and
    the case evaluation still tells the truth about values outside them.
    """

    case: str  #: the case usage's qualified name
    parameter: str  #: the in-parameter name
    lo: float
    hi: float
    source: str
    mined_lo: float | None = None  #: the model's own bound, kept under an override
    mined_hi: float | None = None
    mined_from: tuple[str, ...] = ()  #: the domain ladder's provenance, verbatim

    @property
    def label(self) -> str:
        return f"{self.case.rsplit('::', 1)[-1]}.{self.parameter}"


@dataclass(frozen=True)
class Coupling:
    """One explicit result binding that fired: source -> target."""

    source: str  #: ``<analysis case qname>.<result name>``
    target: str  #: ``<verification case qname> :>> <attribute>``
    binding: str  #: where the model states it


@dataclass
class Panel:
    """One declared subview, derived (or honestly absent)."""

    name: str
    rendering: str  #: rendering qualified name ('' when the panel names none)
    builder: str  #: the RENDERINGS entry ('' when unregistered)
    case: str = ""  #: the case usage's qualified name, when the panel has one
    absent: bool = False
    reason: str = ""  #: why the panel is absent (always stated, never silent)
    sliders: dict[str, Any] = field(default_factory=dict)  #: parameter -> FloatSlider
    ranges: dict[str, RangeInfo] = field(default_factory=dict)
    returns: tuple[str, ...] = ()  #: the case's declared result names
    results: dict[str, float] = field(default_factory=dict)  #: last run's returns
    verdict: VerdictKind | Literal[""] = ""  #: VerdictKind for verdict panels ('' elsewhere)
    rows: list[RequirementResult] = field(default_factory=list)
    tool: tuple[str, str] | None = None  #: the @ToolExecution (toolName, uri)
    readout: Any = None
    widget: Any = None
    repaint: Any = None  #: verdict panels: re-evaluate + repaint (engine wiring)


@dataclass
class WiringMap:
    """The derived wiring, printable: ``print(box.wiring)``.

    Everything the surface wired -- and everything it honestly did not:
    which binding fired for every coupling, the range source per slider,
    case results no binding names (``unbound``), and the panels that do
    not apply to the subject (``absences``).
    """

    view: str
    subject: str
    panels: list[str] = field(default_factory=list)
    ranges: list[RangeInfo] = field(default_factory=list)
    couplings: list[Coupling] = field(default_factory=list)
    unbound: list[str] = field(default_factory=list)  #: case results nothing binds
    absences: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        lines = [f"surface {self.view} -- subject {self.subject}", "panels:"]
        lines += [f"  {entry}" for entry in self.panels]
        lines.append("ranges:")
        for info in self.ranges:
            span = f"[{info.lo:g}, {info.hi:g}]"
            lines.append(f"  {info.label} in {span} -- {info.source}")
            if info.source == RANGE_OVERRIDDEN and info.mined_lo is not None:
                lines.append(
                    f"    (model constraints state [{info.mined_lo:g}, {info.mined_hi:g}])"
                )
        lines.append("couplings:")
        lines += [f"  {c.source} -> {c.target}  [{c.binding}]" for c in self.couplings] or [
            "  (none)"
        ]
        if self.unbound:
            lines.append("unbound results (no explicit binding; they flow nowhere):")
            lines += [f"  {name}" for name in self.unbound]
        if self.absences:
            lines.append("absent:")
            lines += [f"  {entry}" for entry in self.absences]
        if self.notes:
            lines.append("notes:")
            lines += [f"  {note}" for note in self.notes]
        return "\n".join(lines)


class SurfaceWidget(Protocol):
    """What :func:`surface` returns: an ipywidgets ``VBox`` (displayable
    as usual) carrying the derivation as data.  The attributes below are
    the composite's kernel-side surface -- everything a notebook or test
    reads and scripts; ``swap`` re-derives every panel for another
    subject (the picker's programmatic twin)."""

    panels: list[Panel]  #: one per declared subview, derived or absent
    wiring: WiringMap  #: the printable derivation record
    view: str  #: the view usage's qualified name
    subject: str  #: the current subject definition's qualified name
    subjects: list[str]  #: every definition the exposed cases admit
    picker: Any  #: the subject dropdown (an ipywidgets Dropdown)
    header: Any  #: the title bar (an ipywidgets HTML)
    children: Any  #: the VBox composition seam
    swap: Callable[[str | M.Definition], None]  #: re-derive for a subject


# ---------------------------------------------------------------------------
# model introspection helpers
# ---------------------------------------------------------------------------


def _usages(interp: Interpreter, scope: M.Namespace, kinds: tuple[str, ...]) -> list[M.Usage]:
    """Members (own + inherited) of the given usage kinds, named or not."""

    return [
        m for m in interp.resolver.members_of(scope) if isinstance(m, M.Usage) and m.kind in kinds
    ]


def _subject_member(interp: Interpreter, case: M.Usage) -> M.Usage | None:
    members = _usages(interp, case, ("subject",))
    return members[0] if members else None


def _specializes(interp: Interpreter, defn: M.Element, target: M.Element) -> bool:
    """Does ``defn``'s specialization chain reach ``target``?"""

    seen: set[int] = set()
    stack: list[M.Element] = [defn]
    while stack:
        node = stack.pop()
        if node is target:
            return True
        if id(node) in seen:
            continue
        seen.add(id(node))
        names = [*getattr(node, "supers", []), *getattr(node, "types", [])]
        for name in names:
            try:
                stack.append(interp.resolver.resolve(name, node.owner or node))
            except (ResolutionError, SysMLError):
                continue
    return False


def _admits(interp: Interpreter, case: M.Usage, subject: M.Definition) -> tuple[bool, str]:
    """Subject typing as the applicability test (design question 4)."""

    member = _subject_member(interp, case)
    if member is None or not member.types:
        return True, ""
    type_name = member.types[0]
    try:
        needed = interp.resolver.resolve(type_name, member.owner or case)
    except (ResolutionError, SysMLError):
        return False, f"subject type {type_name!r} does not resolve"
    if _specializes(interp, subject, needed):
        return True, ""
    case_def = case.types[0].rsplit("::", 1)[-1] if case.types else case.label
    return False, f"{case_def} applies to {needed.qualified_name or needed.label}"


def _tool_execution(interp: Interpreter, case: M.Usage) -> tuple[str, str] | None:
    """The case's ``@ToolExecution`` annotation (own or inherited)."""

    scopes: list[M.Namespace] = [case]
    for type_name in case.types:
        try:
            typed = interp.resolver.resolve(type_name, case.owner or case)
        except (ResolutionError, SysMLError):
            continue
        if isinstance(typed, M.Namespace):
            scopes.append(typed)
    for scope in scopes:
        for member in scope.members:
            if (
                isinstance(member, M.MetadataUsage)
                and member.typed_by.rsplit("::", 1)[-1] == "ToolExecution"
            ):
                values: dict[str, str] = {}
                for value in member.members:
                    if (
                        isinstance(value, M.MetadataValue)
                        and value.value is not None
                        and isinstance(value.value.expr, A.Literal)
                        and isinstance(value.value.expr.value, str)
                    ):
                        values[value.redefines] = value.value.expr.value
                if "toolName" in values:
                    return values["toolName"], values.get("uri", "")
    return None


def _subject_attribute(param: M.Usage, subject_name: str) -> str | None:
    """The subject attribute a parameter's default binds -- ``uav.loiterSpeed``
    names ``loiterSpeed`` -- or ``None`` for deeper (or absent) defaults."""

    if param.value is None:
        return None
    expr = param.value.expr
    if isinstance(expr, A.FeatureRef) and len(expr.parts) == 2 and expr.parts[0] == subject_name:
        return expr.parts[1]
    if (
        isinstance(expr, A.ChainAccess)
        and isinstance(expr.base, A.FeatureRef)
        and expr.base.parts == (subject_name,)
        and len(expr.parts) == 1
    ):
        return expr.parts[0]
    return None


def _result_binding(usage: M.Usage) -> tuple[str, str, str] | None:
    """Parse one explicit result binding: ``attribute :>> attr = case.result``.

    Returns ``(target attribute, case name, result name)`` -- or ``None``
    when the member is not the one recognized coupling spelling (design
    question 6, adopted explicit-only).
    """

    if usage.kind != "attribute" or not usage.redefines or usage.value is None:
        return None
    target = usage.redefines[0].rsplit("::", 1)[-1]
    expr = usage.value.expr
    if isinstance(expr, A.FeatureRef) and len(expr.parts) == 2:
        return target, expr.parts[0], expr.parts[1]
    if (
        isinstance(expr, A.ChainAccess)
        and isinstance(expr.base, A.FeatureRef)
        and len(expr.base.parts) == 1
        and len(expr.parts) == 1
    ):
        return target, expr.base.parts[0], expr.parts[0]
    return None


def _nested_requirements(interp: Interpreter, requirement: M.Element) -> list[M.Usage]:
    """The requirement plus its nested requirement usages, depth first."""

    out: list[M.Usage] = []
    if isinstance(requirement, (M.Definition, M.Usage)):
        for member in _usages(interp, requirement, ("requirement",)):
            out.append(member)
            out.extend(_nested_requirements(interp, member))
    return out


# ---------------------------------------------------------------------------
# the measure runners: @ToolExecution names the engine
# ---------------------------------------------------------------------------


@dataclass
class _CaseContext:
    """Everything a runner closes over for one derived analysis case."""

    interp: Interpreter
    model: M.Model
    case: M.Usage
    subject: M.Definition
    subject_name: str
    subject_instance: Instance | None
    returns: tuple[str, ...]
    return_exprs: dict[str, A.Expr | None]
    subject_attrs: dict[str, str]  #: parameter -> subject attribute it binds


def _occlusion_runner(ctx: _CaseContext) -> Callable[[dict[str, float]], dict[str, float]]:
    """``longeron.analysis.geometry / occlusion_report``: bake the subject's
    scene once, re-measure the view cone per slider move."""

    from . import geometry
    from .grand import scene_for

    mesh, _ = scene_for(ctx.model, ctx.subject, interpreter=ctx.interp)
    if mesh.get("camera") is None:
        raise AnalysisError(
            f"{ctx.subject.qualified_name} mounts no camera part; the occlusion measure needs one"
        )
    camera0 = geometry._camera_params(mesh["camera"])
    disc_overlap = geometry.disc_overlap(mesh, engine="mesh")

    def run(params: dict[str, float]) -> dict[str, float]:
        report = geometry.occlusion_report(mesh, camera={**camera0, **params}, engine="mesh")
        return {
            "occludedFraction": float(report["occludedFraction"]),
            "discOverlapVolume": float(disc_overlap),
        }

    return run


def _mdao_runner(ctx: _CaseContext) -> Callable[[dict[str, float]], dict[str, float]]:
    """``longeron.analysis.mdao / build_problem``: the subject's generated
    OpenMDAO problem, re-run per slider move."""

    from . import mdao

    build = mdao.build_problem(ctx.model, ctx.subject)

    def run(params: dict[str, float]) -> dict[str, float]:
        for name, value in params.items():
            build.problem.set_val(name, float(value))
        build.problem.run_model()
        return {name: float(build.problem.get_val(name)[0]) for name in ctx.returns}

    return run


def _interpreter_runner(ctx: _CaseContext) -> Callable[[dict[str, float]], dict[str, float]]:
    """The standing oracle: re-instantiate the subject with the slider
    values bound onto the attributes the parameters name, and evaluate
    the case's return expressions."""

    def run(params: dict[str, float]) -> dict[str, float]:
        overrides = {
            ctx.subject_attrs[name]: value
            for name, value in params.items()
            if name in ctx.subject_attrs
        }
        instance = ctx.interp.instantiate(ctx.subject, bindings=overrides)
        out: dict[str, float] = {}
        for name, expr in ctx.return_exprs.items():
            if expr is None:
                continue
            value = ctx.interp.evaluate(
                expr, context=ctx.case, bindings={ctx.subject_name: instance, **params}
            )
            out[name] = float(value)
        return out

    return run


#: (toolName, uri) -> runner factory; unregistered tools fall back to the
#: interpreter runner (recorded in the wiring map's notes)
_TOOLS: dict[tuple[str, str], Callable[[_CaseContext], Callable[..., dict[str, float]]]] = {
    ("longeron.analysis.geometry", "occlusion_report"): _occlusion_runner,
    ("longeron.analysis.mdao", "build_problem"): _mdao_runner,
}


# ---------------------------------------------------------------------------
# range derivation (mining + overrides)
# ---------------------------------------------------------------------------


def _mined_domain(
    interp: Interpreter, case: M.Usage, subject: M.Definition, subject_name: str, param: M.Usage
) -> Domain:
    """The parameter's domain: case-level mining first (objective assumes),
    the subject's own constraint bounds folded in through the parameter's
    default binding where sides stay open."""

    name = param.name or param.label
    dom = attribute_domains(interp, case, (name,))[name]
    if not dom.bounded:
        attr = _subject_attribute(param, subject_name)
        if attr is not None:
            try:
                sub = attribute_domains(interp, subject, (attr,))[attr]
            except AnalysisError:
                sub = None
            if sub is not None:
                if dom.lo is None and sub.lo is not None:
                    dom.lo = sub.lo
                if dom.hi is None and sub.hi is not None:
                    dom.hi = sub.hi
                dom.mined_from.extend(
                    note for note in sub.mined_from if not note.startswith("type:")
                )
    return dom


def _range_source(dom: Domain, overridden: bool) -> str:
    if overridden:
        return RANGE_OVERRIDDEN
    if dom.fallback or dom.lo is None or dom.hi is None:
        return RANGE_FALLBACK
    mined = list(
        dict.fromkeys(
            note.removeprefix("mined: ") for note in dom.mined_from if note.startswith("mined: ")
        )
    )
    if mined:
        return f"{RANGE_MINED} {', '.join(mined)}"
    return f"{RANGE_MINED} (z3 assumption-derived)"


def _slider_step(lo: float, hi: float) -> float:
    """A power-of-ten step, ~100-1000 positions across the span.

    Powers of ten keep the model's own defaults representable on the
    front-end's step grid (a FloatSlider snaps its value to ``min + k *
    step``): with span 180 the step is 1.0, so a declared ``-15.0``
    survives; a coarser 4.5-ish step would snap it to -14 and re-fire
    the measure with a value the model never stated (browser-verified).
    """

    span = hi - lo
    if span <= 0.0:
        return 1.0
    return 10.0 ** (math.floor(math.log10(span)) - 2)


class _Overrides:
    """The caller's ``ranges=`` mapping, resolved against every declared
    case in-parameter -- unambiguously, or loudly refused."""

    def __init__(
        self,
        ranges: Mapping[str, tuple[float, float]] | None,
        parameters: list[tuple[str, str, str]],  # (case qname, param name, param qname)
    ):
        self.by_slider: dict[tuple[str, str], tuple[float, float]] = {}
        for key, bounds in (ranges or {}).items():
            lo, hi = float(bounds[0]), float(bounds[1])
            if not lo < hi:
                raise AnalysisError(f"ranges[{key!r}]: lo must be < hi (got {lo:g} >= {hi:g})")
            hits = [
                (case, name)
                for case, name, qname in parameters
                if key in (name, qname, f"{case}::{name}")
            ]
            if not hits:
                known = sorted({name for _, name, _ in parameters})
                raise AnalysisError(
                    f"ranges key {key!r} names no case in-parameter on this "
                    f"surface (have: {', '.join(known)})"
                )
            if len(set(hits)) > 1:
                spellings = sorted(f"{case}::{name}" for case, name in set(hits))
                raise AnalysisError(
                    f"ranges key {key!r} is ambiguous across {', '.join(spellings)}; "
                    "use a qualified spelling"
                )
            self.by_slider[hits[0]] = (lo, hi)

    def get(self, case: str, name: str) -> tuple[float, float] | None:
        return self.by_slider.get((case, name))


# ---------------------------------------------------------------------------
# verdicts (the interpreter is the oracle)
# ---------------------------------------------------------------------------


def _verdict_rows(
    interp: Interpreter,
    requirements: list[M.Element],
    subject_instance: Instance | None,
    values: Mapping[str, float],
) -> list[RequirementResult]:
    rows: list[RequirementResult] = []
    for requirement in requirements:
        targets: list[M.Element] = [requirement, *_nested_requirements(interp, requirement)]
        for target in targets:
            rows.append(
                interp.check_requirement(
                    target,  # type: ignore[arg-type]
                    subject=subject_instance,
                    bindings=dict(values),
                )
            )
    return rows


def _verdict_kind(rows: list[RequirementResult]) -> VerdictKind:
    """Aggregate requirement rows into the standard ``VerdictKind``."""

    constraints = [c for row in rows if row.applicable for c in row.requirements]
    if any(c.passed is False for c in constraints):
        return "fail"
    if not constraints or any(c.passed is None for c in constraints):
        return "inconclusive"
    return "pass"


# ---------------------------------------------------------------------------
# card rendering (Lab CSS variables, the grand-tour chrome)
# ---------------------------------------------------------------------------

_VERDICT_TONE = {
    "pass": _OK,
    "fail": _BAD,
    "inconclusive": _DIM,
    "error": "var(--jp-warn-color0,#b58900)",
}


def _stat(label: str, value: str, *, color: str = "inherit") -> str:
    return (
        '<div style="display:flex; justify-content:space-between; gap:8px; margin:1px 0">'
        f'<span style="color:{_DIM}">{label}</span>'
        f'<span style="{_NUM}; color:{color}"><b>{value}</b></span></div>'
    )


def _provenance_html(info: RangeInfo) -> str:
    """The slider's range provenance, visible at a glance: mined = plain,
    override = a labeled marker (the model's bounds still stated),
    fallback = the flagged style."""

    if info.source == RANGE_OVERRIDDEN:
        mined = (
            f" (model states [{info.mined_lo:g}, {info.mined_hi:g}])"
            if info.mined_lo is not None and info.mined_hi is not None
            else ""
        )
        return (
            f'<div style="font-size:10px; color:{_DIM}">{info.parameter}: '
            f'<span style="border:1px solid {_DIM}; border-radius:3px; padding:0 3px">'
            f"override</span> [{info.lo:g}, {info.hi:g}] by caller{mined}</div>"
        )
    if info.source == RANGE_FALLBACK:
        return (
            f'<div style="font-size:10px; color:{_BAD}">{info.parameter}: '
            f"FALLBACK [{info.lo:g}, {info.hi:g}] -- no model bound mined</div>"
        )
    return (
        f'<div style="font-size:10px; color:{_DIM}">{info.parameter}: '
        f"[{info.lo:g}, {info.hi:g}] {info.source}</div>"
    )


def _absence_html(title: str, reason: str) -> str:
    style = _CARD_STYLE.replace("height:100%", "height:auto") + "; opacity:0.65"
    return (
        f'<div style="{style}"><div style="{_TITLE_STYLE}">{title}</div>'
        f'<div style="color:{_DIM}; font-size:12px">not derived for this subject</div>'
        f'<div style="color:{_DIM}; font-size:11px; margin-top:4px">{reason}</div></div>'
    )


def _readout_html(panel: Panel, note: str = "") -> str:
    rows = [
        _stat(name, f"{value:.4g}", color=_OK if value == value else _DIM)
        for name, value in panel.results.items()
    ]
    if not rows:
        rows.append(f'<div style="color:{_DIM}">no measured results</div>')
    if panel.tool is not None:
        rows.append(
            f'<div style="font-size:10px; color:{_DIM}">via @ToolExecution '
            f"{panel.tool[0]} / {panel.tool[1]}</div>"
        )
    if note:
        rows.append(f'<div style="font-size:10px; color:{_BAD}">{note}</div>')
    rows.extend(_provenance_html(info) for info in panel.ranges.values())
    return "".join(rows)


def _verdict_html(panel: Panel, bound: Mapping[str, float], unmeasured: list[str]) -> str:
    tone = _VERDICT_TONE.get(panel.verdict, _DIM)
    parts = [
        f'<div style="margin:2px 0 4px"><span style="color:{_DIM}">verdict</span> '
        f'<span style="color:{tone}; font-weight:600">{panel.verdict.upper()}</span></div>'
    ]
    for row in panel.rows:
        if not row.applicable:
            parts.append(
                f'<div style="color:{_DIM}">{row.name}: inapplicable (assumption failed)</div>'
            )
            continue
        for check in row.requirements:
            if check.passed is None:
                parts.append(f'<div style="color:{_DIM}">&#9675; {check.name} (unevaluated)</div>')
            else:
                mark = "&#10003;" if check.passed else "&#10007;"
                color = _OK if check.passed else _BAD
                parts.append(f'<div style="color:{color}; {_NUM}">{mark} {check.name}</div>')
    for name, value in bound.items():
        parts.append(_stat(name, f"{value:.4g}"))
    for name in unmeasured:
        parts.append(
            f'<div style="font-size:10px; color:{_DIM}">{name}: unmeasured (no binding)</div>'
        )
    return "".join(parts)


# ---------------------------------------------------------------------------
# the engine
# ---------------------------------------------------------------------------


def surface(
    model: M.Model,
    view: str | M.Usage,
    *,
    subject: str | M.Definition | None = None,
    ranges: Mapping[str, tuple[float, float]] | None = None,
) -> SurfaceWidget:
    """Derive the composed dashboard a view usage declares.

    ``view`` names the surface's view usage (qualified name or element).
    Its own ``expose`` names the home subject; each nested view usage is
    one panel, deriving through its own ``expose`` (the content: an
    analysis or verification case) and ``render`` (the presentation: a
    rendering the :data:`RENDERINGS` registry maps to a builder).

    ``subject`` re-targets the whole surface at another definition (a
    qualified name or the element).  Applicability re-derives: cases
    whose subject type the new subject does not reach render as honest
    absence, stating the type they need.

    ``ranges`` overrides the mined slider bounds per parameter --
    ``ranges={"loiterSpeed": (8.0, 30.0)}`` -- keyed by the in-parameter's
    name or qualified spelling (``<case qname>::<name>`` or the
    parameter's own qualified name).  A key matching no parameter, a key
    matching more than one, or bounds with ``lo >= hi`` are refused
    loudly.  An override REPLACES the mined range for that slider only;
    every other slider stays mined.  It is a UI freedom, not a model
    edit: the mined bounds stay recorded (:attr:`RangeInfo.mined_lo` /
    ``mined_hi``, and on the slider's provenance marker), and when an
    override widens past a model constraint the case evaluation still
    tells the truth -- the interpreter and the verdict panels report the
    violation the model states.

    Returns an ipywidgets ``VBox`` carrying the derivation as data (the
    :class:`SurfaceWidget` protocol): ``.panels`` (:class:`Panel` per
    subview), ``.wiring`` (the printable :class:`WiringMap`), ``.subject``,
    ``.subjects`` (every definition the exposed cases admit), ``.picker``
    (a dropdown that re-derives on change), and ``.swap(subject)`` (the
    same re-derivation, scriptable).
    """

    widgets = _ipywidgets()
    interp = Interpreter(model)
    if interp.resolver.library is None:
        interp.resolver.library = standard_library_model()

    view_el = _resolve_view(interp, view)
    view_qname = view_el.qualified_name or view_el.label
    subviews = [m for m in view_el.members if isinstance(m, M.Usage) and m.kind == "view"]
    if not subviews:
        raise AnalysisError(f"{view_qname} declares no panel subviews")

    # panel content resolves once (the declaration is fixed; the subjectisn't)
    contents: list[tuple[M.Usage, str, str, M.Usage | None]] = []
    parameters: list[tuple[str, str, str]] = []
    for sub in subviews:
        rendering, builder = _panel_rendering(interp, sub)
        case = _panel_case(interp, model, sub)
        contents.append((sub, rendering, builder, case))
        if case is not None and case.kind == "analysis":
            case_qname = case.qualified_name or case.label
            for param in _in_parameters(interp, case):
                name = param.name or param.label
                parameters.append((case_qname, name, param.qualified_name or name))
    overrides = _Overrides(ranges, parameters)

    home = (
        _resolve_subject(interp, subject) if subject is not None else _home_subject(interp, view_el)
    )

    box = widgets.VBox()
    header = widgets.HTML()
    row = widgets.HBox(
        layout=widgets.Layout(width="100%", align_items="stretch", flex_flow="row wrap")
    )
    guard = {"active": False}
    cases = [case for _, _, _, case in contents if case is not None]
    subjects = _admissible_subjects(interp, model, cases, home)
    picker = widgets.Dropdown(
        options=subjects,
        value=home.qualified_name if home.qualified_name in subjects else None,
        description="subject",
        style={"description_width": "62px"},
        layout=widgets.Layout(width="320px"),
    )

    def _derive(subject_def: M.Definition) -> None:
        panels, wiring = _derive_panels(
            widgets, interp, model, view_qname, contents, subject_def, overrides
        )
        box.panels = panels
        box.wiring = wiring
        box.subject = subject_def.qualified_name or subject_def.label
        row.children = tuple(panel.widget for panel in panels)
        derived = sum(not panel.absent for panel in panels)
        header.value = (
            f'<div style="{_CARD_STYLE.replace("height:100%", "height:auto")}">'
            f"<b>{view_qname}</b> &mdash; subject <b>{box.subject}</b> "
            f'<span style="color:{_DIM}">({derived} of {len(panels)} panels apply)</span></div>'
        )

    def swap(new_subject: str | M.Definition) -> None:
        """Re-derive every panel for another subject (design: re-derive,
        never patch)."""

        subject_def = _resolve_subject(interp, new_subject)
        _derive(subject_def)
        if picker.value != box.subject and box.subject in subjects:
            guard["active"] = True
            try:
                picker.value = box.subject
            finally:
                guard["active"] = False

    def _on_pick(change: Any) -> None:
        if guard["active"] or change["new"] is None:
            return
        swap(str(change["new"]))

    picker.observe(_on_pick, names="value")
    _derive(home)

    box.children = [
        widgets.HTML(_GRAND_CSS, layout=widgets.Layout(display="none")),
        header,
        picker,
        row,
    ]
    box.layout = widgets.Layout(width="100%")
    box.view = view_qname
    box.subjects = subjects
    box.picker = picker
    box.header = header
    box.swap = swap
    return cast(SurfaceWidget, box)  # a VBox wearing the protocol's attributes


# ---------------------------------------------------------------------------
# derivation steps
# ---------------------------------------------------------------------------


def _resolve_view(interp: Interpreter, view: str | M.Usage) -> M.Usage:
    element = interp.resolver.resolve(view) if isinstance(view, str) else view
    if not (isinstance(element, M.Usage) and element.kind == "view"):
        raise AnalysisError(f"{view!r} is not a view usage")
    return element


def _resolve_subject(interp: Interpreter, subject: str | M.Definition) -> M.Definition:
    element = interp.resolver.resolve(subject) if isinstance(subject, str) else subject
    if not isinstance(element, M.Definition):
        raise AnalysisError(f"{subject!r} is not a definition (the surface subject must be one)")
    return element


def _home_subject(interp: Interpreter, view_el: M.Usage) -> M.Definition:
    """The view's own expose names the home subject."""

    for expose in (m for m in view_el.members if isinstance(m, M.Expose)):
        try:
            target = interp.resolver.resolve(expose.target, view_el)
        except (ResolutionError, SysMLError):
            continue
        if isinstance(target, M.Definition):
            return target
    raise AnalysisError(
        f"{view_el.qualified_name or view_el.label} exposes no subject definition "
        "(give the view usage an `expose <configuration>;` or pass subject=)"
    )


def _panel_rendering(interp: Interpreter, sub: M.Usage) -> tuple[str, str]:
    """The subview's rendering qualified name and its registry entry."""

    for member in sub.members:
        if isinstance(member, M.Usage) and member.kind == "render" and member.subsets:
            try:
                rendering = interp.resolver.resolve(member.subsets[0], sub)
            except (ResolutionError, SysMLError):
                return member.subsets[0], ""
            qname = rendering.qualified_name or member.subsets[0]
            return qname, RENDERINGS.get(qname, "")
    return "", ""


def _panel_case(interp: Interpreter, model: M.Model, sub: M.Usage) -> M.Usage | None:
    closure = expose_closure(model, sub, resolver=interp.resolver)
    for element in closure:
        if isinstance(element, M.Usage) and element.kind in _CASE_KINDS:
            return element
    return None


def _in_parameters(interp: Interpreter, case: M.Usage) -> list[M.Usage]:
    return [
        m
        for m in interp.resolver.members_of(case)
        if isinstance(m, M.Usage) and m.direction == "in" and (m.name or m.short_name)
    ]


def _returns(interp: Interpreter, case: M.Usage) -> list[M.Usage]:
    """The case's named results: the ``return`` parameter plus ``out``
    attributes (the standard allows one return; extra measured channels
    are out parameters)."""

    return [
        m
        for m in interp.resolver.members_of(case)
        if isinstance(m, M.Usage) and m.direction in ("return", "out") and (m.name or m.short_name)
    ]


def _admissible_subjects(
    interp: Interpreter, model: M.Model, cases: list[M.Usage], home: M.Definition
) -> list[str]:
    """Every non-abstract definition at least one exposed case admits."""

    out: set[str] = set()
    if home.qualified_name:
        out.add(home.qualified_name)
    for element in model.iter_tree():
        if (
            not isinstance(element, M.Definition)
            or element.kind not in ("part", "item")
            or element.is_abstract
            or not element.qualified_name
        ):
            continue
        if any(_admits(interp, case, element)[0] for case in cases):
            out.add(element.qualified_name)
    return sorted(out)


def _derive_panels(
    widgets: Any,
    interp: Interpreter,
    model: M.Model,
    view_qname: str,
    contents: list[tuple[M.Usage, str, str, M.Usage | None]],
    subject_def: M.Definition,
    overrides: _Overrides,
) -> tuple[list[Panel], WiringMap]:
    subject_qname = subject_def.qualified_name or subject_def.label
    wiring = WiringMap(view=view_qname, subject=subject_qname)
    try:
        subject_instance: Instance | None = interp.instantiate(subject_def)
    except (EvaluationError, AnalysisError) as err:
        subject_instance = None
        wiring.notes.append(f"subject {subject_qname} did not instantiate: {err}")

    panels: list[Panel] = []
    analysis_panels: list[Panel] = []
    verification_panels: list[tuple[Panel, M.Usage]] = []
    runners: dict[str, Callable[[dict[str, float]], dict[str, float]] | None] = {}
    results: dict[str, dict[str, float]] = {}
    couplings_by_case: dict[str, list[tuple[Panel, str, str]]] = {}

    for sub, rendering, builder, case in contents:
        title = sub.name or sub.label
        panel = Panel(name=title, rendering=rendering, builder=builder)
        panels.append(panel)
        if case is not None:
            panel.case = case.qualified_name or case.label
        if not rendering:
            _mark_absent(widgets, panel, "the panel subview declares no render reference")
            continue
        if not builder:
            _mark_absent(widgets, panel, f"no registered builder for {rendering} (RENDERINGS)")
            wiring.notes.append(f"{title}: rendering {rendering} is not in RENDERINGS")
            continue
        if builder not in _BUILT:
            _mark_absent(widgets, panel, f"builder {builder!r} for {rendering} arrives in phase 2")
            continue
        if case is None:
            _mark_absent(widgets, panel, "the panel exposes no analysis or verification case")
            continue
        admitted, reason = _admits(interp, case, subject_def)
        if not admitted:
            _mark_absent(widgets, panel, reason)
            wiring.absences.append(f"{title} ({panel.case}): {reason}")
            continue
        if case.kind == "analysis":
            _build_whatif(
                widgets,
                interp,
                model,
                panel,
                case,
                subject_def,
                subject_instance,
                overrides,
                wiring,
                runners,
                results,
            )
            analysis_panels.append(panel)
        else:
            verification_panels.append((panel, case))

    # verification panels wire after every analysis panel has first results
    bound_results: set[str] = set()
    for panel, case in verification_panels:
        _build_verdict(
            widgets,
            interp,
            panel,
            case,
            subject_instance,
            results,
            wiring,
            couplings_by_case,
            bound_results,
        )

    # unbound-result diagnostics: applicable case results nothing binds
    for panel in analysis_panels:
        for name in panel.returns:
            label = f"{panel.case.rsplit('::', 1)[-1]}.{name}"
            if f"{panel.case}.{name}" not in bound_results:
                wiring.unbound.append(label)

    # live re-measure: slider -> runner -> readout -> coupled verdicts
    for panel in analysis_panels:
        _wire_whatif(panel, runners, results, couplings_by_case)

    for panel in panels:
        state = f"ABSENT: {panel.reason}" if panel.absent else f"[{panel.builder}]"
        suffix = f" :: {panel.case}" if panel.case else ""
        wiring.panels.append(
            f"{panel.name} -> {panel.rendering or '(no rendering)'} {state}{suffix}"
        )
    wiring.ranges = [info for panel in analysis_panels for info in panel.ranges.values()]
    return panels, wiring


def _mark_absent(widgets: Any, panel: Panel, reason: str) -> None:
    panel.absent = True
    panel.reason = reason
    panel.widget = widgets.HTML(
        _absence_html(panel.name, reason),
        layout=widgets.Layout(flex="1 1 260px", min_width="220px", margin="4px"),
    )


def _card(widgets: Any, title: str, children: list[Any]) -> Any:
    titled = widgets.HTML(f'<div style="{_TITLE_STYLE}">{title}</div>')
    card = widgets.VBox(
        [titled, *children],
        layout=widgets.Layout(flex="1 1 260px", min_width="220px", margin="4px"),
    )
    card.add_class("lgn-grand-card")
    return card


def _build_whatif(
    widgets: Any,
    interp: Interpreter,
    model: M.Model,
    panel: Panel,
    case: M.Usage,
    subject_def: M.Definition,
    subject_instance: Instance | None,
    overrides: _Overrides,
    wiring: WiringMap,
    runners: dict[str, Callable[[dict[str, float]], dict[str, float]] | None],
    results: dict[str, dict[str, float]],
) -> None:
    subject_member = _subject_member(interp, case)
    subject_name = (subject_member.name if subject_member else None) or "subject"
    return_members = _returns(interp, case)
    return_exprs: dict[str, A.Expr | None] = {
        (m.name or m.label): (m.value.expr if m.value is not None else None) for m in return_members
    }
    panel.returns = tuple(return_exprs)
    params = _in_parameters(interp, case)
    subject_attrs = {
        (p.name or p.label): attr
        for p in params
        if (attr := _subject_attribute(p, subject_name)) is not None
    }
    ctx = _CaseContext(
        interp=interp,
        model=model,
        case=case,
        subject=subject_def,
        subject_name=subject_name,
        subject_instance=subject_instance,
        returns=tuple(return_exprs),
        return_exprs=return_exprs,
        subject_attrs=subject_attrs,
    )
    panel.tool = _tool_execution(interp, case)
    note = ""
    factory = _TOOLS.get(panel.tool) if panel.tool is not None else None
    if panel.tool is not None and factory is None:
        wiring.notes.append(
            f"{panel.name}: @ToolExecution {panel.tool[0]} / {panel.tool[1]} is not "
            "registered; the interpreter evaluates the returns instead"
        )
        factory = _interpreter_runner
    if factory is None:
        factory = _interpreter_runner
    try:
        runner = factory(ctx)
    except (AnalysisError, EvaluationError, MissingExtraError) as err:
        runner = None
        note = f"measure unavailable: {err}"
        wiring.notes.append(f"{panel.name}: {note}")
    runners[panel.case] = runner

    sliders: list[Any] = []
    for param in params:
        name = param.name or param.label
        dom = _mined_domain(interp, case, subject_def, subject_name, param)
        override = overrides.get(panel.case, name)
        lo, hi = dom.lo, dom.hi
        if override is not None:
            lo, hi = override
        else:
            if lo is None:
                lo = _FALLBACK_BOUNDS[0]
                dom.fallback = True
            if hi is None:
                hi = _FALLBACK_BOUNDS[1]
                dom.fallback = True
        info = RangeInfo(
            case=panel.case,
            parameter=name,
            lo=float(lo),
            hi=float(hi),
            source=_range_source(dom, override is not None),
            mined_lo=dom.lo,
            mined_hi=dom.hi,
            mined_from=tuple(dom.mined_from),
        )
        panel.ranges[name] = info
        value = (lo + hi) / 2.0
        if param.value is not None and subject_instance is not None:
            try:
                value = float(
                    interp.evaluate(
                        param.value.expr, context=case, bindings={subject_name: subject_instance}
                    )
                )
            except (EvaluationError, TypeError, ValueError):
                pass
        slider = widgets.FloatSlider(
            value=min(max(value, info.lo), info.hi),
            min=info.lo,
            max=info.hi,
            step=_slider_step(info.lo, info.hi),
            description=name,
            readout_format=".1f",
            continuous_update=True,
            style={"description_width": "72px"},
            layout=widgets.Layout(width="96%"),
        )
        panel.sliders[name] = slider
        sliders.append(slider)

    if runner is not None:
        try:
            measured = runner({name: float(s.value) for name, s in panel.sliders.items()})
            panel.results = {name: measured[name] for name in panel.returns if name in measured}
        except (AnalysisError, EvaluationError, MissingExtraError, ValueError) as err:
            note = f"measure failed: {err}"
            wiring.notes.append(f"{panel.name}: {note}")
    results[panel.case] = dict(panel.results)
    panel.readout = widgets.HTML(_readout_html(panel, note))
    panel.widget = _card(
        widgets,
        f"{panel.name} -- {panel.case.rsplit('::', 1)[-1]}",
        [
            *sliders,
            panel.readout,
        ],
    )


def _build_verdict(
    widgets: Any,
    interp: Interpreter,
    panel: Panel,
    case: M.Usage,
    subject_instance: Instance | None,
    results: dict[str, dict[str, float]],
    wiring: WiringMap,
    couplings_by_case: dict[str, list[tuple[Panel, str, str]]],
    bound_results: set[str],
) -> None:
    panel.tool = _tool_execution(interp, case)
    verified: list[M.Element] = []
    for member in interp.resolver.members_of(case):
        if isinstance(member, M.Usage) and member.kind == "objective":
            for inner in interp.resolver.members_of(member):
                if isinstance(inner, M.Usage) and inner.kind == "verify":
                    verified.extend(_resolve_all(interp, inner.subsets, member))
        elif isinstance(member, M.Usage) and member.kind == "verify":
            verified.extend(_resolve_all(interp, member.subsets, case))
    if not verified:
        wiring.notes.append(f"{panel.name}: {panel.case} verifies no requirement")

    bindings: dict[str, tuple[str, str]] = {}  # target attr -> (case qname, result)
    for member in interp.resolver.members_of(case):
        if not isinstance(member, M.Usage):
            continue
        parsed = _result_binding(member)
        if parsed is None:
            continue
        target, case_name, result = parsed
        try:
            source_case = interp.resolver.resolve(case_name, member.owner or case)
        except (ResolutionError, SysMLError):
            wiring.notes.append(
                f"{panel.name}: binding ':>> {target}' names {case_name!r}, which does not resolve"
            )
            continue
        source_qname = source_case.qualified_name or case_name
        bindings[target] = (source_qname, result)
        bound_results.add(f"{source_qname}.{result}")
        wiring.couplings.append(
            Coupling(
                source=f"{source_qname.rsplit('::', 1)[-1]}.{result}",
                target=f"{panel.case.rsplit('::', 1)[-1]} :>> {target}",
                binding=f"explicit binding on {panel.case}",
            )
        )
        couplings_by_case.setdefault(source_qname, []).append((panel, target, result))

    measured_channels = [
        m.name
        for m in interp.resolver.members_of(case)
        if isinstance(m, M.Usage) and m.kind == "attribute" and m.name and m.value is None
    ]

    def evaluate() -> None:
        values = {
            target: results[source][result]
            for target, (source, result) in bindings.items()
            if source in results and result in results[source]
        }
        unmeasured = [name for name in measured_channels if name not in values]
        try:
            panel.rows = _verdict_rows(interp, verified, subject_instance, values)
            panel.verdict = _verdict_kind(panel.rows)
        except (EvaluationError, AnalysisError) as err:
            panel.rows = []
            panel.verdict = "error"
            wiring.notes.append(f"{panel.name}: verdict evaluation failed: {err}")
        panel.readout.value = _verdict_html(panel, values, unmeasured)

    panel.readout = widgets.HTML()
    panel.repaint = evaluate
    evaluate()
    panel.widget = _card(
        widgets, f"{panel.name} -- {panel.case.rsplit('::', 1)[-1]}", [panel.readout]
    )


def _resolve_all(interp: Interpreter, names: list[str], context: M.Element) -> list[M.Element]:
    out: list[M.Element] = []
    for name in names:
        try:
            out.append(interp.resolver.resolve(name, context))
        except (ResolutionError, SysMLError):
            continue
    return out


def _wire_whatif(
    panel: Panel,
    runners: dict[str, Callable[[dict[str, float]], dict[str, float]] | None],
    results: dict[str, dict[str, float]],
    couplings_by_case: dict[str, list[tuple[Panel, str, str]]],
) -> None:
    runner = runners.get(panel.case)

    def _on_change(_change: Any = None) -> None:
        if runner is None:
            return
        params = {name: float(s.value) for name, s in panel.sliders.items()}
        try:
            measured = runner(params)
        except (AnalysisError, EvaluationError, ValueError) as err:
            panel.readout.value = _readout_html(panel, f"measure failed: {err}")
            return
        panel.results = {name: measured[name] for name in panel.returns if name in measured}
        results[panel.case] = dict(panel.results)
        panel.readout.value = _readout_html(panel)
        for coupled, _target, _result in couplings_by_case.get(panel.case, ()):
            coupled.repaint()

    for slider in panel.sliders.values():
        slider.observe(_on_change, names="value")
