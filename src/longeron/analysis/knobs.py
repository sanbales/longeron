"""The knobs of the grand tour, derived from the model.

A **knob** is a slider or a dropdown that the tour derives from the model
for one subject (:mod:`longeron.analysis.subject`). No annotation and no
Python table declares a knob. :func:`derive_knobs` reads the knobs off
one definition with these rules:

1. An **input attribute** is an attribute whose value is a numeric
   literal, not a derived expression. The function lists the input
   attributes of the definition, own and inherited.
2. A **bound source** is an ``assert`` constraint of the definition, or a
   ``require`` constraint of a requirement definition whose subject type
   the definition conforms to. The function removes the subject name from
   a ``require`` body, so ``uav.x`` becomes ``x``.
3. An ``assume`` constraint is never a bound source. An assume
   constraint states where a requirement applies, not a range.
4. The function folds ``x >= a`` and ``x <= b`` in both orientations and
   through ``and`` conjunctions. Only a literal ``a`` or ``b`` counts.
5. An input attribute with a lower and an upper bound becomes a
   :class:`Slider` over the closed interval. The slider starts at the
   literal value.
6. An input attribute with one bound gets no slider. :attr:`KnobSet.skipped`
   lists it with the reason, so a notebook can print the gap.
7. Each variation point of the trade study becomes a :class:`Dropdown`
   over its variants, except the airframe point. A click in the tour
   fills the airframe point.

The module imports no third-party package, and no function creates a
widget. The knob set describes the knobs, and the tour builds them.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from .. import ast as A
from .. import model as M
from ..interpreter import Interpreter
from ._expr import AnalysisError, constraint_expr
from .trades import TradeStudy
from .verify import Domain, _literal_number, _mine_comparison

__all__ = ["Dropdown", "KnobSet", "SkipReason", "Skipped", "Slider", "derive_knobs"]

#: why an input attribute with a bound gets no slider:
#: ``"lower_only"`` and ``"upper_only"`` name the one bound found, and
#: ``"default_outside"`` says the literal value is outside the interval
SkipReason = Literal["lower_only", "upper_only", "default_outside"]


@dataclass(frozen=True)
class Slider:
    """An input attribute with two literal bounds.

    ``name`` is the override key of :meth:`TradeStudy.evaluate
    <longeron.analysis.trades.TradeStudy.evaluate>`. An attribute of the
    airframe variant takes the form ``<point>.<attribute>``.
    """

    name: str
    low: float
    high: float
    step: float  #: a power of ten, see ``_slider_step``
    value: float  #: the literal value of the attribute in the model


@dataclass(frozen=True)
class Dropdown:
    """A variation point and its variants, in model order."""

    point: str
    variants: tuple[str, ...]
    selected: str


@dataclass(frozen=True)
class Skipped:
    """An input attribute with a bound but no slider, and the reason."""

    name: str  #: in the form of :attr:`Slider.name`
    reason: SkipReason
    low: float | None
    high: float | None


@dataclass(frozen=True)
class KnobSet:
    """The knobs of one subject, in model order."""

    sliders: tuple[Slider, ...]
    dropdowns: tuple[Dropdown, ...]
    skipped: tuple[Skipped, ...]


def _slider_step(lo: float, hi: float) -> float:
    """The step of a slider over ``[lo, hi]``: a power of ten.

    The step is the power of ten that gives 100 to 1000 positions across
    the interval. For example, the interval [25, 240] gets the step 1.0,
    and [0.5, 2] gets 0.01. A front-end slider snaps its value to ``lo +
    k * step``. A power-of-ten step keeps a round literal value of the
    model on that grid, so the slider does not move the value at start.
    An empty interval gets the step 1.0.
    """

    span = hi - lo
    if span <= 0.0:
        return 1.0
    return 10.0 ** (math.floor(math.log10(span)) - 2)


def _strip(expr: A.Expr, subject: str) -> A.Expr:
    """``expr`` with the ``subject.`` prefix removed from each reference.

    Only the forms that :func:`_mine_comparison` reads need a rewrite:
    comparisons, ``and`` conjunctions, and their feature references.
    """

    if isinstance(expr, A.ChainAccess) and expr.base == A.FeatureRef((subject,)):
        return A.FeatureRef(expr.parts)
    if isinstance(expr, A.Binary):
        return A.Binary(expr.op, _strip(expr.left, subject), _strip(expr.right, subject))
    return expr


def _bound_sources(
    interp: Interpreter, definition: M.Definition | M.Usage
) -> list[tuple[A.Expr, str]]:
    """The bodies of the bound sources of ``definition``, with their labels."""

    def label(con: M.Usage) -> str:
        return con.qualified_name or con.name or con.label

    sources = [
        (body, label(m))
        for m in interp.resolver.members_of(definition)
        if isinstance(m, M.Usage)
        and m.kind == "constraint"
        and m.constraint_kind == "assert"
        and not m.is_negated
        and (body := constraint_expr(interp, m)) is not None
    ]
    for req in interp.model.iter_tree():
        if not (isinstance(req, M.Definition) and req.kind == "requirement"):
            continue
        members = interp.resolver.members_of(req)
        # the first subject member is the one check_requirement binds
        subjects = [m for m in members if isinstance(m, M.Usage) and m.kind == "subject"]
        if not subjects or not subjects[0].types or subjects[0].name is None:
            continue
        needed = interp.resolver.resolve(subjects[0].types[0], subjects[0].owner or req)
        if not interp._conforms(definition, needed):
            continue
        sources.extend(
            (_strip(body, subjects[0].name), label(m))
            for m in members
            if isinstance(m, M.Usage)
            and m.kind == "constraint"
            and m.constraint_kind == "require"
            and (body := constraint_expr(interp, m)) is not None
        )
    return sources


def _sliders(
    interp: Interpreter, definition: M.Definition | M.Usage, prefix: str
) -> tuple[list[Slider], list[Skipped]]:
    """The sliders and the skipped inputs of one definition."""

    sources = _bound_sources(interp, definition)
    sliders: list[Slider] = []
    skipped: list[Skipped] = []
    for attr in interp.resolver.members_of(definition):
        if not (isinstance(attr, M.Usage) and attr.kind == "attribute" and attr.name):
            continue
        if attr.value is None or (value := _literal_number(attr.value.expr)) is None:
            continue  # a derived expression or a non-numeric literal is not an input
        dom = Domain(attr.name, "Real")
        for body, source in sources:
            _mine_comparison(dom, body, source)
        name = prefix + attr.name
        if dom.lo is None and dom.hi is None:
            continue
        if dom.lo is None or dom.hi is None:
            skipped.append(
                Skipped(name, "upper_only" if dom.lo is None else "lower_only", dom.lo, dom.hi)
            )
        elif not dom.lo <= value <= dom.hi:
            skipped.append(Skipped(name, "default_outside", dom.lo, dom.hi))
        else:
            sliders.append(Slider(name, dom.lo, dom.hi, _slider_step(dom.lo, dom.hi), value))
    return sliders, skipped


def derive_knobs(
    interp: Interpreter,
    definition: M.Definition | M.Usage,
    *,
    study: TradeStudy | None = None,
    selection: Mapping[str, str] | None = None,
    point: str = "airframe",
) -> KnobSet:
    """The knobs of ``definition`` by the rules of this module.

    ``definition`` is a mission definition, an airframe definition, an
    airframe variant usage, or a sizing context such as
    ``ScoutSizing::IsrPrime``.

    ``study`` is the trade study over ``definition``. Each of its
    variation points except ``point`` becomes a dropdown. Without a
    study, the knob set has no dropdowns.

    ``selection`` maps variation points to variant names, in the form of
    :meth:`TradeStudy.evaluate <longeron.analysis.trades.TradeStudy.evaluate>`.
    If it names a ``point`` variant, the sliders of that variant join the
    set as ``<point>.<attribute>``. Each dropdown selects the variant that
    ``selection`` names, or the first variant if ``selection`` names none.
    A ``selection`` needs a ``study``.
    """

    sliders, skipped = _sliders(interp, definition, "")
    dropdowns: list[Dropdown] = []
    if study is None:
        if selection:
            raise AnalysisError("a selection needs the trade study that owns its points")
        return KnobSet(tuple(sliders), (), tuple(skipped))
    if study.assembly is not definition:
        raise AnalysisError(
            f"the trade study is over {study.assembly.label}, not {definition.label}"
        )
    chosen = dict(selection or {})
    unknown = sorted(set(chosen) - set(study.points))
    if unknown:
        raise AnalysisError(f"unknown variation point(s) {unknown} (have: {sorted(study.points)})")
    for name, vp in study.points.items():
        if name in chosen and chosen[name] not in vp.variants:
            raise AnalysisError(
                f"unknown variant {chosen[name]!r} for point {name!r} (have: {list(vp.variants)})"
            )
        if name != point:
            variants = tuple(vp.variants)
            dropdowns.append(Dropdown(name, variants, chosen.get(name, variants[0])))
    if point in chosen:
        more, gaps = _sliders(interp, study._variant_usage(point, chosen[point]), f"{point}.")
        sliders.extend(more)
        skipped.extend(gaps)
    return KnobSet(tuple(sliders), tuple(dropdowns), tuple(skipped))
