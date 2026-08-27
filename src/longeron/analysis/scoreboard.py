"""A MAUT scoreboard over the requirements hierarchy (spike).

Multi-attribute utility theory (MAUT) on top of the model's requirement
usages: every leaf requirement maps a raw measured value onto a [0, 1]
utility through a declared utility shape; parents aggregate their
children's utilities by importance weight; the root aggregate is the
design's overall score.  :func:`scoreboard` builds the
:class:`Scoreboard`, whose :meth:`~Scoreboard.widget` renders it as an
interactive treemap (or Voronoi) tessellation where AREA is importance
and COLOR is utility.

Weights and utility shapes live IN THE MODEL, as plain attribute usages
on requirement definitions/usages (all of which the grammar parses
today; typed usages inherit them from their requirement definition, own
declarations override inherited ones)::

    requirement endurance {
        attribute weight : Real = 3.0;              // importance (default 1.0)
        attribute utility : String = "larger-is-better";
        attribute ramp0 : Real = 15.0;              // utility 0 anchor
        attribute ramp1 : Real = 45.0;              // utility 1 anchor
        attribute measure : Real = flightTime;      // the raw value
        attribute unit : String = "min";            // display unit (optional)
    }

The optional ``unit`` attribute names the measurement unit of the raw
value, DISPLAY-ONLY: it shows after ``raw`` in the widget tooltip and
the text table (:class:`Row` carries it), and the ramp/target anchors
are read in that same unit.  No conversion happens anywhere -- SysML
quantity values like ``32.0 [SI::min]`` parse and evaluate to their
magnitude (the measurement reference is an annotation), and a proper
units integration (pint) is designed separately.

The shape vocabulary (:data:`UTILITY_FUNCTIONS`): ``larger-is-better``
and ``smaller-is-better`` (linear between the ``ramp0`` -> 0 and
``ramp1`` -> 1 anchors, orientation validated), ``ramp`` (either
orientation), ``target-is-best`` (1 at ``target``, falling to 0 at
``limit`` away), and ``step`` (pass/fail).  ``step`` is the DEFAULT: a
leaf requirement with no ``utility`` declaration scores 1 when its own
``require constraint`` bodies hold (via
:meth:`~longeron.interpreter.Interpreter.check_requirement`) and 0 when
they do not.  Raw values come from the model too -- the ``measure``
attribute's expression is evaluated by the interpreter in the
requirement's own context -- or are injected per call: ``values=``
entries override by requirement qualified name, by requirement name,
and as evaluation-frame bindings for the free names inside ``measure``
expressions and constraint bodies.  That last form is the trade-study
bridge: :func:`architecture_values` turns a
:class:`~longeron.analysis.trades.Architecture` into exactly such a
dict, so ``scoreboard(model, values=architecture_values(arch))`` scores
any mix without touching the model.  Python-side ``weights=`` /
``utilities=`` keyword overrides exist for exploration; the model
remains the source of truth.

Aggregation is pluggable (:data:`AGGREGATORS` or any
:class:`Aggregator` callable over ``(weight, utility)`` pairs):
``saw`` -- weight-normalized simple additive weighting, the default --
``min`` (weakest link), and ``geometric`` (weighted geometric mean).
Unmeasured leaves (no raw value, or a non-applicable requirement) carry
utility NaN and are excluded from their parent's aggregation; a fully
unmeasured subtree aggregates to NaN.

Area semantics in the widget: a node's area share among its siblings is
its weight's share, recursively -- so a COLLAPSED subtree (click a
group's twist to collapse or expand it in place) renders as one cell
occupying exactly the area its leaves occupied, colored by the subtree
aggregate.  Double-click zooms instead of collapsing: a group cell
re-tessellates to fill the whole canvas (a leaf zooms to its parent
group), the breadcrumb bar above the canvas walks back out (Esc steps
out one level), and ``max_depth`` windows the render depth below the
current zoom root so deep hierarchies reveal themselves level by level.
Zoom and depth window are VIEW state only -- scores and aggregates are
always computed over the full tree.  Hover shows qualified name,
weight and share, raw value (with its declared ``unit``), and utility;
click writes the ``selected`` trait
(the same observer idiom as the other longeron widgets, ready for
linked selection).  Utilities and aggregates render through ONE
consistent format everywhere (cell labels, tooltips, the text table):
percent with one decimal by default, or three-decimal floats under
``value_format="float"``.  Unmeasured cells are grey and hatched.  The color
ramp is red -> yellow -> green interpolated in OKLab (perceptual, with
a monotone-ish lightness cue for red/green-weak viewers).  Both
tessellations are deterministic: stable model order, and the Voronoi
iteration runs on a seeded PRNG (``seed=``, re-derived per zoom root so
every zoom level re-tessellates stably).

The Voronoi tessellation is computed by Kcnarf's d3-voronoi-treemap,
vendored with its dependency closure as one inlined bundle
(``longeron/_js/voronoi_treemap.bundled.js``; rebuild instructions in
``voronoi_treemap.VENDOR.md`` next to it) -- all BSD-3-Clause / ISC:
d3-voronoi-treemap 1.1.2 (BSD-3-Clause), d3-voronoi-map 2.1.1
(BSD-3-Clause), d3-weighted-voronoi 1.1.3 (BSD-3-Clause), d3-hierarchy
3.1.2 (ISC), d3-array 2.12.1 (BSD-3-Clause), d3-polygon 2.0.0
(BSD-3-Clause), d3-timer 2.0.0 (BSD-3-Clause), d3-dispatch 2.0.0
(BSD-3-Clause), internmap 1.0.1 (ISC).

The widget requires the ``viz`` extra (``pip install "longeron[viz]"``);
everything else runs on the interpreter alone.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .. import model as M
from ..errors import MissingExtraError, SysMLError
from ..interpreter import Interpreter
from ._expr import AnalysisError, is_scalar

__all__ = [
    "AGGREGATORS",
    "UTILITY_FUNCTIONS",
    "Aggregator",
    "Row",
    "Scoreboard",
    "architecture_values",
    "scoreboard",
]

#: the vendored d3-voronoi-treemap bundle (see module docstring for licenses)
_VORONOI_JS = Path(__file__).resolve().parents[1] / "_js" / "voronoi_treemap.bundled.js"

#: model attribute names the scoreboard convention reserves on requirements
WEIGHT_ATTR = "weight"
UTILITY_ATTR = "utility"
MEASURE_ATTR = "measure"
UNIT_ATTR = "unit"
_PARAM_ATTRS = ("target", "limit", "ramp0", "ramp1")

#: synthetic node-id prefix for anonymous requirements / the multi-root
#: aggregate ('~' cannot start a SysML identifier -- same idiom as the
#: explorer's tree)
_SYNTH_PREFIX = "~"


# ---------------------------------------------------------------------------
# utility functions: raw measured value -> [0, 1]
# ---------------------------------------------------------------------------


def _clamp01(value: float) -> float:
    if math.isnan(value):
        return value
    return min(1.0, max(0.0, value))


def _anchors(params: Mapping[str, float], shape: str) -> tuple[float, float]:
    if "ramp0" not in params or "ramp1" not in params:
        raise AnalysisError(f"utility shape {shape!r} needs 'ramp0' and 'ramp1' attributes")
    ramp0, ramp1 = params["ramp0"], params["ramp1"]
    if ramp0 == ramp1:
        raise AnalysisError(f"utility shape {shape!r}: ramp0 and ramp1 must differ")
    return ramp0, ramp1


def _ramp(raw: float, params: Mapping[str, float]) -> float:
    """0 at ``ramp0``, 1 at ``ramp1``, linear and clamped in between."""

    ramp0, ramp1 = _anchors(params, "ramp")
    return _clamp01((float(raw) - ramp0) / (ramp1 - ramp0))


def _larger_is_better(raw: float, params: Mapping[str, float]) -> float:
    """A rising ramp: ``ramp0 < ramp1`` (0 below, 1 above)."""

    ramp0, ramp1 = _anchors(params, "larger-is-better")
    if not ramp0 < ramp1:
        raise AnalysisError("'larger-is-better' needs ramp0 < ramp1 (use 'ramp' to invert)")
    return _clamp01((float(raw) - ramp0) / (ramp1 - ramp0))


def _smaller_is_better(raw: float, params: Mapping[str, float]) -> float:
    """A falling ramp: ``ramp1 < ramp0`` (1 below, 0 above)."""

    ramp0, ramp1 = _anchors(params, "smaller-is-better")
    if not ramp1 < ramp0:
        raise AnalysisError("'smaller-is-better' needs ramp1 < ramp0 (use 'ramp' to invert)")
    return _clamp01((float(raw) - ramp0) / (ramp1 - ramp0))


def _target_is_best(raw: float, params: Mapping[str, float]) -> float:
    """1 at ``target``, falling linearly to 0 at ``limit`` away."""

    if "target" not in params or "limit" not in params:
        raise AnalysisError("utility shape 'target-is-best' needs 'target' and 'limit' attributes")
    if params["limit"] <= 0:
        raise AnalysisError("'target-is-best' needs a positive 'limit'")
    return _clamp01(1.0 - abs(float(raw) - params["target"]) / params["limit"])


def _step(raw: Any, params: Mapping[str, float]) -> float:
    """Pass/fail: 1 for a truthy raw value, 0 otherwise."""

    if isinstance(raw, float) and math.isnan(raw):
        return math.nan
    return 1.0 if bool(raw) else 0.0


#: the utility-shape registry (each: ``fn(raw, params) -> [0, 1]``)
UTILITY_FUNCTIONS: dict[str, Callable[[Any, Mapping[str, float]], float]] = {
    "larger-is-better": _larger_is_better,
    "smaller-is-better": _smaller_is_better,
    "ramp": _ramp,
    "target-is-best": _target_is_best,
    "step": _step,
}


# ---------------------------------------------------------------------------
# aggregation strategies over (weight, utility) pairs
# ---------------------------------------------------------------------------


class Aggregator(Protocol):
    """A parent's utility from its measured children's ``(weight, utility)``.

    The scoreboard filters unmeasured (NaN-utility) children BEFORE the
    call and never calls an aggregator with an empty sequence (a fully
    unmeasured subtree is NaN without consulting the strategy) -- a
    custom aggregator only ever sees finite utilities in [0, 1] with
    non-negative weights.
    """

    def __call__(self, children: Sequence[tuple[float, float]]) -> float: ...


def _saw(children: Sequence[tuple[float, float]]) -> float:
    """Simple additive weighting, weight-normalized (the MAUT default)."""

    total = sum(weight for weight, _ in children)
    if total <= 0:
        return math.nan
    return sum(weight * utility for weight, utility in children) / total


def _weakest_link(children: Sequence[tuple[float, float]]) -> float:
    """The minimum child utility (weights only size the cells)."""

    return min(utility for _, utility in children)


def _geometric(children: Sequence[tuple[float, float]]) -> float:
    """The weighted geometric mean (a zero child zeroes the parent)."""

    total = sum(weight for weight, _ in children)
    if total <= 0:
        return math.nan
    if any(utility <= 0 for _, utility in children):
        return 0.0
    return math.exp(sum(weight * math.log(utility) for weight, utility in children) / total)


#: the aggregation-strategy registry
AGGREGATORS: dict[str, Aggregator] = {
    "saw": _saw,
    "min": _weakest_link,
    "geometric": _geometric,
}


# ---------------------------------------------------------------------------
# the scoreboard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """One requirement's line in :meth:`Scoreboard.table` (pre-order)."""

    qname: str  # qualified name (or a '~' synthetic for anonymous nodes)
    name: str  # display name
    depth: int  # 0 = the root
    kind: str  # 'leaf' | 'group'
    weight: float  # own importance weight (default 1.0)
    share: float  # weight / sum of sibling weights (1.0 at the root)
    shape: str  # utility shape name ('' for groups)
    raw: Any  # measured value (None when unmeasured; groups: None)
    unit: str  # declared measurement unit of raw ('' = none; display only)
    utility: float  # leaf utility in [0, 1]; NaN when unmeasured / a group
    aggregate: float  # subtree score (leaves: == utility); NaN unmeasured


@dataclass
class _Node:
    element: M.Definition | M.Usage | None
    qname: str
    name: str
    depth: int
    weight: float
    share: float = 1.0
    shape: str = ""
    raw: Any = None
    unit: str = ""
    utility: float = math.nan
    aggregate: float = math.nan
    measured: bool = False
    children: list[_Node] = field(default_factory=list)

    @property
    def leaves(self) -> int:
        if not self.children:
            return 1
        return sum(child.leaves for child in self.children)


def architecture_values(architecture: Any) -> dict[str, Any]:
    """A ``values=`` dict from a trade-study architecture (duck-typed).

    Any object with a ``metrics`` mapping qualifies --
    :class:`longeron.analysis.trades.Architecture` in particular, whose
    interpreter-exact derived metrics then override the same-named free
    references inside ``measure`` expressions and constraint bodies::

        best = max(
            study.all_architectures(),
            key=lambda a: scoreboard(model, values=architecture_values(a)).score,
        )
    """

    metrics = getattr(architecture, "metrics", None)
    if not isinstance(metrics, dict):
        raise AnalysisError(
            "architecture_values expects an architecture with a .metrics dict "
            "(e.g. longeron.analysis.trades.Architecture)"
        )
    return dict(metrics)


class Scoreboard:
    """MAUT utilities and aggregates over one requirement hierarchy.

    Build with :func:`scoreboard`.  ``.score`` is the root aggregate,
    :meth:`table` the flat pre-order rows, :meth:`widget` the
    treemap/Voronoi view.  ``str()`` renders an aligned text table.
    """

    def __init__(
        self,
        target: M.Model | M.Package | M.Definition | M.Usage,
        *,
        values: Mapping[str, Any] | None = None,
        aggregation: str | Aggregator = "saw",
        weights: Mapping[str, float] | None = None,
        utilities: Mapping[str, str | Callable[[Any], float]] | None = None,
        value_format: str = "percent",
    ) -> None:
        if value_format not in ("percent", "float"):
            raise AnalysisError(f"value_format must be 'percent' or 'float'; not {value_format!r}")
        self.value_format = value_format
        if isinstance(aggregation, str):
            if aggregation not in AGGREGATORS:
                options = ", ".join(sorted(AGGREGATORS))
                raise AnalysisError(f"aggregation must be one of {options}; not {aggregation!r}")
            self.aggregation = aggregation
            self._aggregator: Aggregator = AGGREGATORS[aggregation]
        else:
            self.aggregation = getattr(aggregation, "__name__", "custom").lstrip("_")
            self._aggregator = aggregation
        self.values: dict[str, Any] = dict(values or {})
        self._weights = dict(weights or {})
        self._utilities = dict(utilities or {})
        #: evaluation-frame bindings: plain-name values reach free
        #: references inside measure expressions and constraint bodies
        self._frame = {
            key: value
            for key, value in self.values.items()
            if "::" not in key and key.isidentifier()
        }
        self.interp = Interpreter(_owning_model(target))
        self._counter = itertools.count()
        roots = _root_requirements(target)
        if not roots:
            raise AnalysisError(
                f"{getattr(target, 'label', target)!r} contains no requirement usages "
                "(pass a requirement definition directly to score it as the root)"
            )
        if len(roots) == 1:
            self.root = self._build(roots[0], depth=0)
        else:
            children = [self._build(req, depth=1) for req in roots]
            self.root = _Node(
                element=None,
                qname=f"{_SYNTH_PREFIX}root",
                name=getattr(target, "name", None) or "requirements",
                depth=0,
                weight=1.0,
                children=children,
            )
        self._aggregate(self.root)
        self._share(self.root)
        self._index: dict[str, _Node] = {}
        for node in self._walk(self.root):
            self._index[node.qname] = node

    # -- construction --------------------------------------------------------

    def _build(self, req: M.Definition | M.Usage, depth: int) -> _Node:
        qname = req.qualified_name or f"{_SYNTH_PREFIX}{next(self._counter)}"
        name = req.name or req.short_name or qname.split("::")[-1]
        declared_unit = self._attr_value(req, UNIT_ATTR)
        node = _Node(
            element=req,
            qname=qname,
            name=name,
            depth=depth,
            weight=self._weight(req, qname, name),
            unit="" if declared_unit is None else str(declared_unit),
        )
        nested = [
            member
            for member in req.members
            if isinstance(member, (M.Definition, M.Usage)) and member.kind == "requirement"
        ]
        if nested:
            node.children = [self._build(child, depth + 1) for child in nested]
            return node
        self._score_leaf(node, req, qname, name)
        return node

    def _weight(self, req: M.Definition | M.Usage, qname: str, name: str) -> float:
        override = self._weights.get(qname, self._weights.get(name))
        if override is not None:
            weight = float(override)
        else:
            declared = self._attr_value(req, WEIGHT_ATTR)
            weight = 1.0 if declared is None else float(declared)
        if math.isnan(weight) or weight < 0:
            raise AnalysisError(f"{qname}: weight must be a non-negative number, not {weight!r}")
        return weight

    def _score_leaf(self, node: _Node, req: M.Definition | M.Usage, qname: str, name: str) -> None:
        shape = self._utilities.get(qname, self._utilities.get(name))
        if shape is None:
            declared = self._attr_value(req, UTILITY_ATTR)
            shape = str(declared) if declared is not None else "step"
        raw = self._raw(req, qname, name, shape)
        node.raw = raw
        if callable(shape):
            node.shape = getattr(shape, "__name__", "custom").lstrip("_")
            fn: Callable[[Any], float] = shape
        else:
            if shape not in UTILITY_FUNCTIONS:
                options = ", ".join(sorted(UTILITY_FUNCTIONS))
                raise AnalysisError(f"{qname}: unknown utility shape {shape!r} (have: {options})")
            node.shape = shape
            params = self._params(req)
            registered = UTILITY_FUNCTIONS[shape]

            def fn(value: Any) -> float:
                return registered(value, params)

        if raw is None:
            return  # unmeasured: NaN utility, excluded from aggregation
        try:
            utility = _clamp01(float(fn(raw)))
        except AnalysisError as err:
            raise AnalysisError(f"{qname}: {err}") from None
        if math.isnan(utility):
            node.raw = None
            return
        node.utility = utility
        node.aggregate = utility
        node.measured = True

    def _raw(self, req: M.Definition | M.Usage, qname: str, name: str, shape: Any) -> Any:
        if qname in self.values:
            return self.values[qname]
        if name in self.values:
            return self.values[name]
        measure = self._attr_expr(req, MEASURE_ATTR)
        if measure is not None:
            try:
                value = self.interp.evaluate(measure, req, **self._frame)
            except (SysMLError, TypeError, ValueError):
                return None
            # an unvalued attribute (a measured-elsewhere seam, e.g. the
            # geometry checks) evaluates to its type, not a number: that
            # leaf is honestly UNMEASURED until values= injects a reading
            return value if is_scalar(value) or isinstance(value, bool) else None
        if shape == "step":
            try:
                result = self.interp.check_requirement(req, **self._frame)
            except (SysMLError, TypeError, ValueError):
                return None
            if not result.requirements:  # no require-constraint bodies
                return None
            return result.satisfied  # True / False / None (not applicable)
        return None

    def _params(self, req: M.Definition | M.Usage) -> dict[str, float]:
        params: dict[str, float] = {}
        for attr in _PARAM_ATTRS:
            value = self._attr_value(req, attr)
            if value is not None:
                params[attr] = float(value)
        return params

    def _attr_expr(self, req: M.Definition | M.Usage, name: str) -> Any:
        #: own members precede inherited ones in members_of, so a usage's
        #: declaration overrides its typing definition's
        for member in self.interp.resolver.members_of(req):
            if (
                isinstance(member, M.Usage)
                and member.kind == "attribute"
                and member.name == name
                and member.value is not None
            ):
                return member.value.expr
        return None

    def _attr_value(self, req: M.Definition | M.Usage, name: str) -> Any:
        expr = self._attr_expr(req, name)
        if expr is None:
            return None
        try:
            return self.interp.evaluate(expr, req)
        except (SysMLError, TypeError, ValueError):
            return None

    def _aggregate(self, node: _Node) -> None:
        if not node.children:
            return
        for child in node.children:
            self._aggregate(child)
        measured = [
            (child.weight, child.aggregate)
            for child in node.children
            if not math.isnan(child.aggregate)
        ]
        node.measured = bool(measured)
        if measured:
            node.aggregate = _clamp01(float(self._aggregator(measured)))

    def _share(self, node: _Node) -> None:
        total = sum(child.weight for child in node.children)
        for child in node.children:
            child.share = child.weight / total if total > 0 else 1.0 / len(node.children)
            self._share(child)

    def _walk(self, node: _Node) -> Iterable[_Node]:
        yield node
        for child in node.children:
            yield from self._walk(child)

    # -- public surface --------------------------------------------------------

    @property
    def score(self) -> float:
        """The root aggregate utility (NaN when nothing is measured)."""

        return self.root.aggregate

    def table(self) -> list[Row]:
        """Flat pre-order rows: qname, weight, share, raw, utility, aggregate."""

        return [
            Row(
                qname=node.qname,
                name=node.name,
                depth=node.depth,
                kind="group" if node.children else "leaf",
                weight=node.weight,
                share=node.share,
                shape=node.shape,
                raw=node.raw,
                unit=node.unit,
                utility=node.utility,
                aggregate=node.aggregate,
            )
            for node in self._walk(self.root)
        ]

    def __str__(self) -> str:
        def fmt(value: Any) -> str:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return "-"
            if isinstance(value, bool):
                return "pass" if value else "FAIL"
            return f"{value:.3g}"

        def fmt_score(value: float) -> str:
            # utilities/aggregates live in [0, 1]: ONE consistent rendering
            # (maintainer QA: mixed 0.55 / 0.5867 / 1 read as noise) --
            # percent with 1 decimal by default, 3-decimal floats otherwise
            if isinstance(value, float) and math.isnan(value):
                return "-"
            if self.value_format == "percent":
                return f"{value * 100:.1f}%"
            return f"{value:.3f}"

        def fmt_raw(row: Row) -> str:
            text = fmt(row.raw)
            if row.unit and text != "-":  # unit after raw, display only
                text = f"{text} {row.unit}"
            return text

        rows = self.table()
        raw_width = max(8, *(len(fmt_raw(row)) for row in rows))
        lines = [
            f"{'requirement':<44} {'weight':>6} {'share':>6} {'raw':>{raw_width}} "
            f"{'utility':>7} {'aggregate':>9}"
        ]
        for row in rows:
            label = ("  " * row.depth + row.name)[:44]
            lines.append(
                f"{label:<44} {row.weight:>6.3g} {row.share:>5.0%} {fmt_raw(row):>{raw_width}} "
                f"{fmt_score(row.utility):>7} {fmt_score(row.aggregate):>9}"
            )
        lines.append(
            f"{'score (' + self.aggregation + ')':<44} {'':>6} {'':>6} {'':>{raw_width}} "
            f"{'':>7} {fmt_score(self.score):>9}"
        )
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<Scoreboard {self.root.name!r}: score={self.score:.3f} "
            f"({self.aggregation}), {self.root.leaves} leaves>"
        )

    def widget(
        self,
        tessellation: str = "treemap",
        *,
        collapsed: Iterable[str] = (),
        zoom_root: str = "",
        max_depth: int | None = None,
        seed: int = 42,
        width_px: int = 960,
        height_px: int = 540,
        value_format: str | None = None,
    ) -> Any:
        """The scoreboard as one interactive anywidget.

        ``tessellation`` picks ``"treemap"`` (squarified) or
        ``"voronoi"`` (the vendored d3-voronoi-treemap; ``seed`` makes
        its iteration deterministic, re-derived per zoom root).  Hover a
        cell for details; click to select (the ``selected`` trait).  The
        navigation gestures:

        * **double-click** a group cell to ZOOM into that subtree (it
          re-tessellates to fill the whole canvas); double-clicking a
          leaf zooms to its parent group.  A breadcrumb bar above the
          canvas tracks the zoom path (hidden at the tree root): each
          crumb zooms back out, and Esc steps out one level.  Zooming
          is pure navigation -- it never touches the collapsed set.
        * the **twist** on a group (the small triangle) collapses or
          expands that group IN PLACE, at any depth: a collapsed group
          renders as one cell occupying its subtree's total area,
          colored by the subtree aggregate.

        ``collapsed`` pre-collapses subtrees by qualified name;
        ``zoom_root`` starts zoomed into one (``""`` is the tree root);
        ``max_depth`` (default ``None`` = unlimited) windows the render
        depth below the CURRENT zoom root -- deeper levels draw as
        aggregate cells (same visual as collapsed, without entering the
        collapsed set), and zooming in reveals the next ``max_depth``
        levels.  ``value_format`` picks how utilities/aggregates render
        in cell labels and tooltips: ``"percent"`` (one decimal, e.g.
        ``61.1%``) or ``"float"`` (three decimals, e.g. ``0.611``);
        default: the scoreboard's own ``value_format`` (``percent``).
        All navigation state is scriptable: ``selected``,
        ``collapsed``, ``zoom_root``, ``max_depth`` and ``value_format``
        are two-way traits.  None of them affect scoring, which always
        runs over the full tree.  Unmeasured leaves render HATCHED (the
        honest no-data state); when MORE THAN HALF of the tree's leaves
        are unmeasured a one-line footer legend explains the hatching
        (``hatched = unmeasured (n of m leaves ...)``), so an
        all-unmeasured board never reads as broken (maintainer QA).
        Needs the ``viz`` extra (anywidget).
        """

        if tessellation not in ("treemap", "voronoi"):
            raise ValueError(f"tessellation must be 'treemap' or 'voronoi', not {tessellation!r}")
        value_format = self.value_format if value_format is None else value_format
        if value_format not in ("percent", "float"):
            raise ValueError(f"value_format must be 'percent' or 'float', not {value_format!r}")
        collapsed = [str(qname) for qname in collapsed]
        unknown = [qname for qname in collapsed if qname not in self._index]
        if unknown:
            raise ValueError(f"unknown collapsed qname(s): {unknown}")
        zoom_root = str(zoom_root)
        if zoom_root and zoom_root not in self._index:
            raise ValueError(f"unknown zoom_root qname: {zoom_root!r}")
        if max_depth is not None and max_depth < 1:
            raise ValueError(f"max_depth must be a positive int or None, not {max_depth!r}")
        cls = _widget_class()
        return cls(
            nodes_json=json.dumps(self._payload(self.root)),
            tessellation=tessellation,
            aggregation=self.aggregation,
            collapsed=sorted(collapsed),
            zoom_root=zoom_root,
            max_depth=max_depth,
            seed=seed,
            width_px=width_px,
            height_px=height_px,
            value_format=value_format,
        )

    def _payload(self, node: _Node) -> dict[str, Any]:
        def scrub(value: Any) -> Any:  # JSON has no NaN
            if isinstance(value, float) and math.isnan(value):
                return None
            return value

        return {
            "qname": node.qname,
            "label": node.name,
            "depth": node.depth,
            "weight": node.weight,
            "share": node.share,
            "shape": node.shape,
            "raw": scrub(node.raw),
            "unit": node.unit,
            "utility": scrub(node.utility),
            "aggregate": scrub(node.aggregate),
            "measured": node.measured,
            "leaves": node.leaves,
            "children": [self._payload(child) for child in node.children],
        }


def scoreboard(
    model_or_element: M.Model | M.Package | M.Definition | M.Usage,
    values: Mapping[str, Any] | None = None,
    aggregation: str | Aggregator = "saw",
    *,
    weights: Mapping[str, float] | None = None,
    utilities: Mapping[str, str | Callable[[Any], float]] | None = None,
    value_format: str = "percent",
) -> Scoreboard:
    """MAUT-score the requirement hierarchy under ``model_or_element``.

    The scope's root requirement usages become the top level (several
    roots aggregate under one synthetic root; requirement definitions
    contribute their attributes through typing -- pass a definition
    itself to score it directly).  ``values`` injects raw measurements:
    by requirement qualified name, by requirement name, or -- for plain
    identifiers -- as evaluation-frame bindings overriding the free
    references inside ``measure`` expressions and constraint bodies
    (see :func:`architecture_values` for the trade-study bridge).
    ``aggregation`` is a name from :data:`AGGREGATORS` or any
    :class:`Aggregator`; ``weights``/``utilities`` are exploration-time
    overrides keyed like ``values``.  ``value_format`` picks ONE
    consistent rendering for utilities/aggregates everywhere they
    display (``str()``'s table, the widget's cell labels and tooltips):
    ``"percent"`` (the default; one decimal, ``61.1%``) or ``"float"``
    (three decimals, ``0.611``).  :meth:`Scoreboard.table` always
    carries the raw floats.
    """

    return Scoreboard(
        model_or_element,
        values=values,
        aggregation=aggregation,
        weights=weights,
        utilities=utilities,
        value_format=value_format,
    )


def _owning_model(element: M.Element) -> M.Model:
    node: M.Element = element
    while node.owner is not None:
        node = node.owner
    if isinstance(node, M.Model):
        return node
    # a detached fragment: list it under a throwaway root WITHOUT
    # re-parenting (Model.add would steal it from its real owner)
    root = M.Model()
    root.members = [node]
    return root


def _root_requirements(scope: M.Element) -> list[M.Definition | M.Usage]:
    """Requirement usages with no requirement ancestor inside ``scope``."""

    if isinstance(scope, (M.Definition, M.Usage)) and scope.kind == "requirement":
        return [scope]
    roots: list[M.Definition | M.Usage] = []

    def walk(namespace: M.Namespace) -> None:
        for member in namespace.members:
            if isinstance(member, M.Usage) and member.kind == "requirement":
                roots.append(member)
            elif isinstance(member, M.Namespace) and not (
                isinstance(member, (M.Definition, M.Usage)) and member.kind == "requirement"
            ):
                walk(member)

    if isinstance(scope, M.Namespace):
        walk(scope)
    return roots


# ---------------------------------------------------------------------------
# the widget (one anywidget; both tessellations behind the same front-end)
# ---------------------------------------------------------------------------

_SCOREBOARD_JS = r"""
let lgnSbInstances = 0;

// ---- perceptual color ramp: red -> yellow -> green, OKLab-interpolated ----
function lgnSbSrgbToLin(c) {
  c /= 255;
  return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
}
function lgnSbLinToSrgb(c) {
  return Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055));
}
function lgnSbHexToOklab(hex) {
  const r = lgnSbSrgbToLin(parseInt(hex.slice(1, 3), 16));
  const g = lgnSbSrgbToLin(parseInt(hex.slice(3, 5), 16));
  const b = lgnSbSrgbToLin(parseInt(hex.slice(5, 7), 16));
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s,
  ];
}
function lgnSbOklabToRgb(L, a, b) {
  const l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3);
  const m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3);
  const s = Math.pow(L - 0.0894841775 * a - 1.291485548 * b, 3);
  const clamp = (x) => Math.min(1, Math.max(0, x));
  return [
    lgnSbLinToSrgb(clamp(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s)),
    lgnSbLinToSrgb(clamp(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s)),
    lgnSbLinToSrgb(clamp(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s)),
  ];
}
const LGN_SB_STOPS = ["#a50026", "#d73027", "#fee08b", "#66bd63", "#1a9850"].map(lgnSbHexToOklab);
function lgnSbColor(u) {
  u = Math.min(1, Math.max(0, u));
  const t = u * (LGN_SB_STOPS.length - 1);
  const i = Math.min(LGN_SB_STOPS.length - 2, Math.floor(t));
  const f = t - i;
  const A = LGN_SB_STOPS[i], B = LGN_SB_STOPS[i + 1];
  const L = A[0] + (B[0] - A[0]) * f;
  const [r, g, b] = lgnSbOklabToRgb(L, A[1] + (B[1] - A[1]) * f, A[2] + (B[2] - A[2]) * f);
  return { css: `rgb(${r},${g},${b})`, dark: L > 0.72 };
}

// ---- squarified treemap (zero-dependency) ----------------------------------
function lgnSbSquarify(areas, rect) {
  // areas: number[] (already scaled so their sum equals rect area);
  // returns rects aligned with the input order (deterministic: the
  // descending processing order ties break on the original index).
  const rects = new Array(areas.length);
  const order = areas
    .map((a, i) => ({ a: Math.max(a, 0), i }))
    .sort((p, q) => q.a - p.a || p.i - q.i);
  let x = rect.x, y = rect.y, w = rect.w, h = rect.h;
  let start = 0;
  while (start < order.length) {
    const side = Math.max(Math.min(w, h), 1e-9);
    let end = start, sum = 0, best = Infinity, mn = Infinity, mx = 0;
    for (let k = start; k < order.length; k++) {
      const s = sum + order[k].a;
      mn = Math.min(mn, order[k].a);
      mx = Math.max(mx, order[k].a);
      const worst = s > 0
        ? Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn))
        : Infinity;
      if (worst <= best || k === start) { best = worst; end = k; sum = s; }
      else break;
    }
    const horizontal = w >= h; // lay the row along the shorter side
    const thickness = sum > 0 ? sum / Math.max(horizontal ? h : w, 1e-9) : 0;
    let offset = 0;
    for (let k = start; k <= end; k++) {
      const len = thickness > 0 ? order[k].a / thickness : 0;
      rects[order[k].i] = horizontal
        ? { x, y: y + offset, w: thickness, h: len }
        : { x: x + offset, y, w: len, h: thickness };
      offset += len;
    }
    if (horizontal) { x += thickness; w -= thickness; }
    else { y += thickness; h -= thickness; }
    start = end + 1;
  }
  return rects;
}

function lgnSbPolyArea(poly) {
  let s = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}
function lgnSbPolyCentroid(poly) {
  let a = 0, cx = 0, cy = 0;
  for (let i = 0; i < poly.length; i++) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    const cross = x1 * y2 - x2 * y1;
    a += cross; cx += (x1 + x2) * cross; cy += (y1 + y2) * cross;
  }
  if (Math.abs(a) < 1e-9) return poly[0];
  return [cx / (3 * a), cy / (3 * a)];
}
function lgnSbMixSeed(seed, zoomRoot) {
  // FNV-1a over the zoom root's qname, folded into the base seed: each
  // zoom level gets its own stable PRNG stream (deterministic re-renders)
  let h = ((seed >>> 0) ^ 2166136261) >>> 0;
  for (let i = 0; i < zoomRoot.length; i++) {
    h = Math.imul(h ^ zoomRoot.charCodeAt(i), 16777619) >>> 0;
  }
  return h || 1;
}
function lgnSbTwistAnchor(polygon) {
  // just inside the polygon (convex): its topmost vertex nudged toward
  // the centroid -- the voronoi analogue of a rect's top-left corner
  let top = polygon[0];
  for (const p of polygon) {
    if (p[1] < top[1] || (p[1] === top[1] && p[0] < top[0])) top = p;
  }
  const [cx, cy] = lgnSbPolyCentroid(polygon);
  const dist = Math.hypot(cx - top[0], cy - top[1]) || 1;
  const t = Math.min(0.5, 13 / dist);
  return [top[0] + (cx - top[0]) * t, top[1] + (cy - top[1]) * t];
}

function render({ model, el }) {
  // unique across ALL module copies (anywidget loads one module per
  // widget): a duplicated pattern id would resolve to another widget's
  // <defs>, which JupyterLab's windowed notebook may have detached --
  // an unresolvable paint server paints nothing (the hatch went white)
  globalThis.lgnSbSeq = (globalThis.lgnSbSeq || 0) + 1;
  const iid = `lgn-sb-${globalThis.lgnSbSeq}-${lgnSbInstances++}`;
  el.classList.add("lgn-sb-host");
  const crumbs = document.createElement("div");
  crumbs.className = "lgn-sb-crumbs";
  const wrap = document.createElement("div");
  wrap.className = "lgn-sb-wrap";
  wrap.tabIndex = -1; // focusable (not tabbable): Esc zooms out one level
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  const tip = document.createElement("div");
  tip.className = "lgn-sb-tip";
  wrap.append(svg, tip);
  // the honest-unmeasured hint (maintainer QA: an all-hatched board reads
  // as broken): a one-line footer naming what hatching means, shown only
  // when MOST leaves are unmeasured (see renderAll)
  const legend = document.createElement("div");
  legend.className = "lgn-sb-legend";
  legend.style.display = "none";
  const legendSwatch = document.createElement("span");
  legendSwatch.className = "lgn-sb-legend-swatch";
  const legendText = document.createElement("span");
  legendText.className = "lgn-sb-legend-text";
  legend.append(legendSwatch, legendText);
  el.append(crumbs, wrap, legend);

  let root = null;
  const parentOf = new Map(); // qname -> parent node (null at the root)
  const byQname = new Map();
  function rebuild() {
    parentOf.clear();
    byQname.clear();
    root = JSON.parse(model.get("nodes_json") || "null");
    (function index(node, parent) {
      if (!node) return;
      byQname.set(node.qname, node);
      parentOf.set(node.qname, parent);
      for (const child of node.children || []) index(child, node);
    })(root, null);
    renderAll();
  }

  const collapsedSet = () => new Set(model.get("collapsed") || []);
  const selectedSet = () => new Set(model.get("selected") || []);
  const zoomNode = () => byQname.get(model.get("zoom_root") || "") || root;
  const viewState = () => {
    const maxDepth = model.get("max_depth");
    return {
      zoom: zoomNode(),
      collapsed: collapsedSet(),
      window: maxDepth == null || maxDepth < 1 ? Infinity : maxDepth,
    };
  };

  function zoomTo(node) {
    const qname = !node || node === root ? "" : node.qname;
    if ((model.get("zoom_root") || "") === qname) return;
    model.set("zoom_root", qname);
    model.save_changes();
  }

  // what renders below a node: null = it draws as ONE aggregate cell.
  // depth is RELATIVE to the zoom root; the zoom root itself always
  // expands (its own collapsed-set entry must not hide what zooming in
  // reveals), and levels past the max_depth window draw as aggregates
  function expandedKids(node, view, depth) {
    if (!node.children || !node.children.length) return null;
    if (depth >= view.window) return null;
    if (depth > 0 && view.collapsed.has(node.qname)) return null;
    return node.children;
  }

  // area semantics: a node's share of its parent's area is its weight's
  // share among the siblings, recursively -- collapse is area-preserving
  function assignAreas(node, area, view, depth) {
    node._area = area;
    const kids = expandedKids(node, view, depth);
    if (!kids) return;
    const total = kids.reduce((s, k) => s + Math.max(k.weight, 0), 0);
    for (const k of kids) {
      const share = total > 0 ? Math.max(k.weight, 0) / total : 1 / kids.length;
      assignAreas(k, area * share, view, depth + 1);
    }
  }

  function treemapCells(node, rect, view, cells, outlines, depth) {
    const d = `M${rect.x},${rect.y}H${rect.x + rect.w}V${rect.y + rect.h}H${rect.x}Z`;
    const twist = [rect.x + 11, rect.y + 12];
    const kids = expandedKids(node, view, depth);
    if (!kids) {
      cells.push({ node, d, cx: rect.x + rect.w / 2, cy: rect.y + rect.h / 2,
                   area: rect.w * rect.h, width: rect.w, twist });
      return;
    }
    if (depth > 0) outlines.push({ node, d, depth, area: rect.w * rect.h, twist });
    const rects = lgnSbSquarify(kids.map((k) => k._area), rect);
    kids.forEach((k, i) => treemapCells(k, rects[i], view, cells, outlines, depth + 1));
  }

  function voronoiCells(W, H, view, cells, outlines) {
    if (typeof lgnVoronoi === "undefined") {
      return false; // vendored bundle missing: caller shows the notice
    }
    const minArea = W * H * 1e-6;
    if (!expandedKids(view.zoom, view, 0)) {
      // a childless zoom root (a leaf, by scripting zoom_root): one cell
      // covering the canvas -- d3-voronoi-treemap needs children to run
      const poly = [[0, 0], [0, H], [W, H], [W, 0]];
      const d = `M${poly.map((p) => `${p[0]},${p[1]}`).join("L")}Z`;
      cells.push({ node: view.zoom, d, cx: W / 2, cy: H / 2, area: W * H,
                   width: W, twist: [11, 12] });
      return true;
    }
    function prune(node, depth) {
      const kids = expandedKids(node, view, depth);
      if (!kids) return { node, value: Math.max(node._area, minArea) };
      return { node, children: kids.map((k) => prune(k, depth + 1)) };
    }
    const hier = lgnVoronoi.hierarchy(prune(view.zoom, 0)).sum((d) => d.value || 0);
    let s = lgnSbMixSeed(model.get("seed"), model.get("zoom_root") || "");
    const prng = () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; };
    lgnVoronoi
      .voronoiTreemap()
      .clip([[0, 0], [0, H], [W, H], [W, 0]])
      .prng(prng)(hier);
    for (const n of hier.descendants()) {
      if (!n.polygon) continue;
      const d = `M${n.polygon.map((p) => `${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("L")}Z`;
      const twist = lgnSbTwistAnchor(n.polygon);
      if (n.children) {
        if (n.depth > 0) {
          outlines.push({ node: n.data.node, d, depth: n.depth,
                          area: lgnSbPolyArea(n.polygon), twist });
        }
        continue;
      }
      const [cx, cy] = lgnSbPolyCentroid(n.polygon);
      const area = lgnSbPolyArea(n.polygon);
      cells.push({ node: n.data.node, d, cx, cy, area, width: Math.sqrt(area) * 1.15, twist });
    }
    return true;
  }

  const fmtNum = (v) => {
    if (v === null || v === undefined) return "\u2014";
    if (typeof v === "boolean") return v ? "pass" : "fail";
    if (typeof v !== "number") return String(v);
    return Math.abs(v) >= 1000 ? v.toFixed(0) : +v.toPrecision(4) + "";
  };

  // utilities/aggregates ([0, 1]) render through ONE consistent format
  // (maintainer QA: mixed 0.55 / 0.5867 / 1 read as noise): percent with
  // 1 decimal by default, 3-decimal floats under value_format='float'
  const fmtScore = (v) => {
    if (v === null || v === undefined || typeof v !== "number") return "\u2014";
    return model.get("value_format") === "float"
      ? v.toFixed(3)
      : `${(100 * v).toFixed(1)}%`;
  };

  function tooltipFor(node, collapsed) {
    const lines = [];
    const group = node.children && node.children.length;
    const isCollapsed = group && collapsed.has(node.qname);
    // a group only reaches the tooltip as ONE aggregate cell (collapsed,
    // or cut off by the max_depth render window)
    lines.push(["title", node.label + (group ? `  (${node.leaves} leaves)` : "")]);
    lines.push(["dim", node.qname]);
    const parent = parentOf.get(node.qname);
    const share = parent ? ` \u00b7 ${(node.share * 100).toFixed(0)}% of ${parent.label}` : "";
    lines.push(["row", `weight ${fmtNum(node.weight)}${share}`]);
    if (!group) {
      const unit = node.unit && node.raw != null ? ` ${node.unit}` : "";
      const shape = node.shape ? ` \u00b7 ${node.shape}` : "";
      lines.push(["row", `raw ${fmtNum(node.raw)}${unit}${shape}`]);
      lines.push(["row", node.measured ? `utility ${fmtScore(node.utility)}` : "unmeasured"]);
    } else {
      const agg = `aggregate ${fmtScore(node.aggregate)}` +
        ` (${model.get("aggregation")} over ${node.leaves} leaves)`;
      lines.push(["row", node.measured ? agg : "unmeasured"]);
    }
    const hint = group
      ? `double-click to zoom in${isCollapsed ? " \u00b7 \u25b8 expands in place" : ""}`
      : "double-click to zoom to the group";
    lines.push(["dim", hint]);
    return lines;
  }

  function showTip(ev, node, collapsed) {
    tip.textContent = "";
    for (const [kind, text] of tooltipFor(node, collapsed)) {
      if (!text) continue;
      const line = document.createElement("div");
      line.className = `lgn-sb-tip-${kind}`;
      line.textContent = text;
      tip.append(line);
    }
    tip.style.display = "block";
    const bounds = wrap.getBoundingClientRect();
    let x = ev.clientX - bounds.left + 12;
    let y = ev.clientY - bounds.top + 12;
    x = Math.min(x, bounds.width - tip.offsetWidth - 6);
    y = Math.min(y, bounds.height - tip.offsetHeight - 6);
    tip.style.left = `${Math.max(0, x)}px`;
    tip.style.top = `${Math.max(0, y)}px`;
  }

  function setSelected(ids) {
    const current = model.get("selected") || [];
    if (current.length !== ids.length || current.some((v, i) => v !== ids[i])) {
      model.set("selected", ids);
      model.save_changes();
    }
  }

  function toggle(node) {
    if (!node.children || !node.children.length) return; // twists sit on groups only
    const collapsed = collapsedSet();
    if (collapsed.has(node.qname)) collapsed.delete(node.qname); // expand
    else collapsed.add(node.qname);
    model.set("collapsed", [...collapsed].sort());
    model.save_changes();
  }

  function renderCrumbs() {
    crumbs.textContent = "";
    const zoom = zoomNode();
    if (!root || zoom === root) {
      crumbs.style.display = "none"; // zero chrome when unzoomed
      return;
    }
    crumbs.style.display = "flex";
    const path = [];
    for (let n = zoom; n; n = parentOf.get(n.qname)) path.unshift(n);
    path.forEach((n, i) => {
      if (i > 0) {
        const sep = document.createElement("span");
        sep.className = "lgn-sb-crumb-sep";
        sep.textContent = "\u25b8";
        crumbs.append(sep);
      }
      if (i === path.length - 1) {
        const here = document.createElement("span");
        here.className = "lgn-sb-crumb lgn-sb-crumb-here";
        here.textContent = n.label;
        here.title = n.qname;
        crumbs.append(here);
      } else {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "lgn-sb-crumb";
        btn.textContent = n.label;
        btn.title = n.qname;
        btn.addEventListener("click", (ev) => { ev.stopPropagation(); zoomTo(n); });
        crumbs.append(btn);
      }
    });
  }

  function restyle() {
    const selected = selectedSet();
    for (const path of svg.querySelectorAll(".lgn-sb-cell")) {
      const hit = selected.has(path.dataset.qname);
      path.classList.toggle("lgn-sb-selected", hit);
      if (hit) path.parentNode.append(path); // over its siblings' strokes
    }
  }

  function renderLegend() {
    // counted over the FULL tree (never the zoom/collapse view): the
    // legend describes the DATA -- how much of the board is honestly
    // unmeasured -- and must not flicker with navigation
    let total = 0;
    let unmeasured = 0;
    (function count(node) {
      if (!node) return;
      if (!node.children || !node.children.length) {
        total += 1;
        if (!node.measured) unmeasured += 1;
        return;
      }
      for (const child of node.children) count(child);
    })(root);
    if (total && unmeasured * 2 > total) {
      legendText.textContent =
        `hatched = unmeasured (${unmeasured} of ${total} leaves have no ` +
        "measure attribute or values= entry)";
      legend.style.display = "flex";
    } else {
      legend.style.display = "none";
    }
  }

  function renderAll() {
    if (!root) return;
    const W = model.get("width_px") || 960;
    const H = model.get("height_px") || 540;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.textContent = "";
    const defs = document.createElementNS(NS, "defs");
    const pattern = document.createElementNS(NS, "pattern");
    pattern.setAttribute("id", `${iid}-hatch`);
    pattern.setAttribute("width", "7");
    pattern.setAttribute("height", "7");
    pattern.setAttribute("patternUnits", "userSpaceOnUse");
    pattern.setAttribute("patternTransform", "rotate(45)");
    const back = document.createElementNS(NS, "rect");
    back.setAttribute("width", "7");
    back.setAttribute("height", "7");
    back.setAttribute("fill", "#d7d7d7");
    const line = document.createElementNS(NS, "line");
    line.setAttribute("x1", "0"); line.setAttribute("y1", "0");
    line.setAttribute("x2", "0"); line.setAttribute("y2", "7");
    line.setAttribute("stroke", "#a9a9a9");
    line.setAttribute("stroke-width", "2.5");
    pattern.append(back, line);
    defs.append(pattern);
    svg.append(defs);

    renderCrumbs();
    renderLegend();
    const view = viewState();
    assignAreas(view.zoom, W * H, view, 0);
    const cells = [], outlines = [];
    const mode = model.get("tessellation") || "treemap";
    if (mode === "voronoi") {
      if (!voronoiCells(W, H, view, cells, outlines)) {
        const note = document.createElementNS(NS, "text");
        note.setAttribute("x", "16"); note.setAttribute("y", "28");
        note.setAttribute("class", "lgn-sb-note");
        note.textContent = "voronoi unavailable: the vendored d3-voronoi-treemap bundle is missing";
        svg.append(note);
        return;
      }
    } else {
      treemapCells(view.zoom, { x: 0, y: 0, w: W, h: H }, view, cells, outlines, 0);
    }

    const cellLayer = document.createElementNS(NS, "g");
    const lineLayer = document.createElementNS(NS, "g");
    const textLayer = document.createElementNS(NS, "g");
    const twistLayer = document.createElementNS(NS, "g");
    svg.append(cellLayer, lineLayer, textLayer, twistLayer);

    const placedTwists = [];
    function addTwist(node, at, open) {
      // nudge right out of any earlier twist: nested groups share their
      // top-left corner, especially in the treemap
      let [x, y] = at;
      while (placedTwists.some((p) => Math.abs(p.x - x) < 14 && Math.abs(p.y - y) < 13)) x += 14;
      placedTwists.push({ x, y });
      const glyph = document.createElementNS(NS, "text");
      glyph.setAttribute("x", x);
      glyph.setAttribute("y", y);
      glyph.setAttribute("class", "lgn-sb-twist");
      glyph.dataset.qname = node.qname;
      glyph.textContent = open ? "\u25be" : "\u25b8";
      const title = document.createElementNS(NS, "title");
      title.textContent = view.collapsed.has(node.qname)
        ? "expand in place" : "collapse in place";
      glyph.append(title);
      const swallow = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
      glyph.addEventListener("dblclick", swallow); // the twist never zooms
      glyph.addEventListener("click", (ev) => { swallow(ev); toggle(node); }); // never selects
      twistLayer.append(glyph);
    }

    // outlines (and their twists) first: parents claim their corner
    // before their descendants' twists get nudged aside
    for (const outline of outlines.sort((a, b) => a.depth - b.depth)) {
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", outline.d);
      path.setAttribute("class", "lgn-sb-outline");
      path.setAttribute("stroke-width", Math.max(1, 4 - outline.depth).toFixed(1));
      lineLayer.append(path);
      // every expanded group collapses in place from its own twist --
      // including one whose children are all groups
      if (outline.area >= W * H * 0.004) addTwist(outline.node, outline.twist, true);
    }
    for (const cell of cells) {
      const node = cell.node;
      const path = document.createElementNS(NS, "path");
      path.setAttribute("d", cell.d);
      path.setAttribute("class", "lgn-sb-cell");
      path.dataset.qname = node.qname;
      const measured = node.measured && node.aggregate !== null;
      const color = measured ? lgnSbColor(node.aggregate) : null;
      path.setAttribute("fill", measured ? color.css : `url(#${iid}-hatch)`);
      path.addEventListener("pointermove", (ev) => showTip(ev, node, collapsedSet()));
      path.addEventListener("pointerleave", () => { tip.style.display = "none"; });
      path.addEventListener("click", (ev) => { ev.stopPropagation(); setSelected([node.qname]); });
      path.addEventListener("dblclick", (ev) => {
        // zoom is navigation, never collapse: a group cell zooms in, a
        // leaf zooms to its parent group
        ev.stopPropagation();
        ev.preventDefault();
        const group = node.children && node.children.length;
        zoomTo(group ? node : parentOf.get(node.qname));
      });
      cellLayer.append(path);

      if (cell.area >= W * H * 0.004) {
        const group = node.children && node.children.length;
        if (group) addTwist(node, cell.twist, false); // aggregate cell: closed twist
        const size = Math.min(15, Math.max(9, 0.14 * Math.sqrt(cell.area)));
        const dark = measured ? color.dark : true;
        const label = document.createElementNS(NS, "text");
        label.setAttribute("x", cell.cx);
        label.setAttribute("y", cell.cy);
        const cls = `lgn-sb-label ${dark ? "lgn-sb-label-dark" : "lgn-sb-label-light"}`;
        label.setAttribute("class", cls);
        label.setAttribute("font-size", size.toFixed(1));
        const maxChars = Math.max(3, Math.floor(cell.width / (0.62 * size)));
        let text = node.label;
        if (text.length > maxChars) text = `${text.slice(0, Math.max(1, maxChars - 1))}\u2026`;
        label.textContent = text;
        textLayer.append(label);
        if (cell.area >= W * H * 0.012) {
          const value = document.createElementNS(NS, "text");
          value.setAttribute("x", cell.cx);
          value.setAttribute("y", cell.cy + size * 1.15);
          value.setAttribute("class", label.getAttribute("class"));
          value.setAttribute("font-size", (size * 0.85).toFixed(1));
          value.textContent = measured ? fmtScore(node.aggregate) : "\u2014";
          textLayer.append(value);
        }
      }
    }
    restyle();
  }

  svg.addEventListener("click", () => setSelected([]));
  svg.addEventListener("dblclick", (ev) => ev.preventDefault());
  wrap.addEventListener("pointerdown", () => wrap.focus({ preventScroll: true }));
  wrap.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape") return;
    const zoom = zoomNode();
    if (!root || zoom === root) return; // unzoomed: Esc stays JupyterLab's
    ev.stopPropagation();
    ev.preventDefault();
    zoomTo(parentOf.get(zoom.qname)); // one level out
  });
  model.on("change:nodes_json", rebuild);
  model.on("change:collapsed", renderAll);
  model.on("change:tessellation", renderAll);
  model.on("change:seed", renderAll);
  model.on("change:zoom_root", renderAll);
  model.on("change:max_depth", renderAll);
  model.on("change:width_px", renderAll);
  model.on("change:height_px", renderAll);
  model.on("change:value_format", renderAll);
  model.on("change:selected", restyle);
  rebuild();
}
export default { render };
"""

_SCOREBOARD_CSS = """
.lgn-sb-host {
  font-family: var(--jp-ui-font-family, system-ui, sans-serif);
}
.lgn-sb-wrap { position: relative; width: 100%; }
.lgn-sb-wrap:focus { outline: none; }
.lgn-sb-crumbs {
  display: none; align-items: center; flex-wrap: wrap; gap: 2px;
  margin: 0 0 4px; padding: 3px 8px; border-radius: 6px;
  border: 1px solid var(--jp-border-color2, #e0e0e0);
  background: var(--jp-layout-color2, #f5f5f5);
  color: var(--jp-ui-font-color1, #333333);
  font-size: 11.5px; line-height: 1.4;
}
.lgn-sb-crumb {
  border: 0; background: none; margin: 0; padding: 1px 3px; border-radius: 3px;
  font: inherit; color: var(--jp-brand-color1, #1976d2); cursor: pointer;
}
button.lgn-sb-crumb:hover {
  text-decoration: underline; background: var(--jp-layout-color3, #ededed);
}
.lgn-sb-crumb-here {
  color: var(--jp-ui-font-color1, #333333); cursor: default; font-weight: 600;
}
.lgn-sb-crumb-sep {
  color: var(--jp-ui-font-color2, #777777); font-size: 10px; padding: 0 1px;
}
.lgn-sb-wrap svg {
  display: block; width: 100%; height: auto;
  border: 1px solid var(--jp-border-color2, #e0e0e0); border-radius: 6px;
  background: var(--jp-layout-color1, #ffffff);
}
.lgn-sb-cell {
  cursor: pointer; stroke: var(--jp-layout-color1, #ffffff); stroke-width: 1;
}
.lgn-sb-cell:hover { filter: brightness(1.07); }
.lgn-sb-cell.lgn-sb-selected {
  stroke: var(--jp-brand-color1, #1976d2); stroke-width: 3;
}
.lgn-sb-outline {
  fill: none; stroke: var(--jp-layout-color1, #ffffff);
  pointer-events: none; opacity: 0.9;
}
.lgn-sb-twist {
  cursor: pointer; user-select: none;
  text-anchor: middle; dominant-baseline: middle; font-size: 12px;
  paint-order: stroke; stroke: var(--jp-layout-color1, #ffffff);
  stroke-width: 3px; stroke-linejoin: round; fill: rgba(0, 0, 0, 0.72);
}
.lgn-sb-twist:hover { fill: var(--jp-brand-color1, #1976d2); }
.lgn-sb-label {
  pointer-events: none; user-select: none;
  text-anchor: middle; dominant-baseline: middle;
}
.lgn-sb-label-dark { fill: rgba(0, 0, 0, 0.82); }
.lgn-sb-label-light { fill: rgba(255, 255, 255, 0.94); }
.lgn-sb-note { font-size: 13px; fill: var(--jp-ui-font-color2, #777777); }
.lgn-sb-legend {
  display: flex; align-items: center; gap: 5px; margin-top: 4px;
  font-size: 11px; line-height: 1.4;
  color: var(--jp-ui-font-color2, #777777);
}
.lgn-sb-legend-swatch {
  width: 14px; height: 11px; border-radius: 2px; flex: none;
  border: 1px solid var(--jp-border-color2, #cccccc);
  /* the hatch cells' look, in CSS (the svg pattern id is per-instance) */
  background: repeating-linear-gradient(
    45deg, #d7d7d7, #d7d7d7 3px, #a9a9a9 3px, #a9a9a9 5px);
}
.lgn-sb-legend-text {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.lgn-sb-tip {
  position: absolute; display: none; z-index: 10; pointer-events: none;
  max-width: 320px; padding: 6px 9px; border-radius: 5px;
  background: rgba(33, 33, 33, 0.93); color: #ffffff;
  font-size: 11.5px; line-height: 1.45;
}
.lgn-sb-tip-title { font-weight: 600; font-size: 12px; }
.lgn-sb-tip-dim { color: rgba(255, 255, 255, 0.62); font-size: 10.5px; }
"""

_WIDGET_CLS: type[Any] | None = None


def _widget_class() -> type[Any]:
    """Define ScoreboardWidget lazily -- anywidget is an optional extra."""

    global _WIDGET_CLS
    if _WIDGET_CLS is not None:
        return _WIDGET_CLS
    try:
        import anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the requirements scoreboard widget", "anywidget", "viz") from err

    vendored = _VORONOI_JS.read_text(encoding="utf-8") if _VORONOI_JS.is_file() else ""

    class ScoreboardWidget(anywidget.AnyWidget):
        """Treemap/Voronoi over one scoreboard payload (area = weight,
        color = utility).  ``selected``, ``collapsed``, ``zoom_root``
        and ``max_depth`` are the two-way automation surface; build
        instances via :meth:`Scoreboard.widget`."""

        _esm = vendored + _SCOREBOARD_JS
        _css = _SCOREBOARD_CSS

        nodes_json = traitlets.Unicode("null").tag(sync=True)
        tessellation = traitlets.Unicode("treemap").tag(sync=True)
        aggregation = traitlets.Unicode("saw").tag(sync=True)
        selected = traitlets.List(
            traitlets.Unicode(), help="selected requirement qnames; [] = none"
        ).tag(sync=True)
        collapsed = traitlets.List(
            traitlets.Unicode(), help="collapsed subtree qnames (each renders as one cell)"
        ).tag(sync=True)
        zoom_root = traitlets.Unicode(
            "", help="qname of the subtree the view is zoomed into; '' = the tree root"
        ).tag(sync=True)
        max_depth = traitlets.Int(
            None,
            allow_none=True,
            help="render-depth window below the current zoom root; None = unlimited",
        ).tag(sync=True)
        seed = traitlets.Int(42, help="Voronoi iteration seed (determinism)").tag(sync=True)
        width_px = traitlets.Int(960).tag(sync=True)
        height_px = traitlets.Int(540).tag(sync=True)
        value_format = traitlets.Enum(
            ("percent", "float"),
            default_value="percent",
            help="how utilities/aggregates render: '61.1%' or '0.611'",
        ).tag(sync=True)

        def __init__(self, **kwargs: Any) -> None:
            # set BEFORE super().__init__: trait kwargs may fire observers
            self._select_callbacks: list[Callable[[list[str]], None]] = []
            super().__init__(**kwargs)

        def on_select(self, callback: Callable[[list[str]], None]) -> None:
            """Call ``callback`` with the selected qnames on every change."""

            self._select_callbacks.append(callback)

        @traitlets.observe("selected")
        def _dispatch_select(self, change: Any) -> None:
            ids = list(change["new"])
            for callback in list(getattr(self, "_select_callbacks", ())):
                callback(ids)

    _WIDGET_CLS = ScoreboardWidget
    return ScoreboardWidget
