"""The mission-compromise dashboard: linked widgets over the trades.

One :func:`mission_dashboard` call composes the existing house widgets
(:func:`longeron.analysis.viz.parcoords`,
:func:`longeron.analysis.viewer3d.mesh_viewer`) with plain ipywidgets into
the single artifact that ties requirements -> architectures ->
performance -> cost.  The layout is built to fit one 1080p screen
(1920x950 content area) without vertical scrolling: row HEIGHTS are
fixed while the rows and plots stretch to the container width in their
design proportions (pass ``width_px`` to pin a fixed total width
instead):

* a HEADER STRIP -- the title, a PARETO-ONLY toggle button (see below),
  and the top-N slider sizing the 3D lineup;
* a PLOT ROW -- the parallel-coordinates widget over the cross-mission
  metrics PLUS a computed ``MOE`` axis (the weighted compromise score)
  side by side with a compact MOE-vs-cost scatter; brushing a parcoords
  axis downselects the candidate pool, and the whole table re-bakes in
  place as sliders move (brushes survive by axis name).  The brush
  INTERVALS sync to the kernel by axis name too, so every recompute
  derives the brushed subset from the table it just baked -- a toggle
  flip or slider move can never pair fresh rows with stale brushed row
  indices -- and a brush that excludes everything empties the picks
  honestly instead of silently showing the whole pool;
* a CONTROL ROW -- one ipywidgets ``Tab`` next to the 3D viewer.  Tab 0
  summarizes all three missions: the best compromise, the mission
  priority sliders (one 0-100 weight per mission) feeding the MOE, and a
  per-mission scorecard.  Tabs 1-3 hold one mission each: its
  requirement-threshold sliders (defaults and constraint identities read
  from the model's own requirement attributes) and its requirement
  margin card (green holds / red broken, threshold rows tracking the
  sliders live).  The 3D viewer sits BESIDE the tab, so slider moves and
  their geometric consequences share one glance: the top-N compromises
  render to scale in an adaptive grid
  (:func:`longeron.analysis.geometry.lineup`), each cell captioned
  in-scene.  A column of LINEUP CARDS sits between the tab and the
  viewer: one card per pick (rank, mix, MOE, cost, and -- for front
  members -- a one-line justification, see below).  Hovering a card
  transiently traces that candidate's line in the parallel coordinates,
  where every dominance axis is visible.

LINKED SELECTION is one state shared by every view: clicking a lineup
card -- or a 3D model in the lineup, whose parts carry per-candidate
identity keys through :func:`longeron.analysis.geometry.lineup` --
selects that candidate everywhere at once.  The selected card border,
its scatter halo, its parallel-coordinates line, and its 3D model all
take the same violet accent (:data:`_SEL`), deliberately distinct from
the petrol-blue brush (:data:`longeron.analysis.viz.ACCENT`), the
terracotta top-N rings (:data:`longeron.analysis.viz.WARM`), and the
green/red verdicts, so a selection stays visible WHILE brushing.
Selection is sticky until the candidate leaves the visible pool (or the
background is clicked in 3D); hover stays transient on top of it.

The PARETO-ONLY toggle filters dominated candidates out of the linked
views.  Dominance is over the study's objective axes -- cost (minimized)
and every mission's primary metric (maximized) as currently thresholded:
candidate ``a`` is dominated when some candidate ``b`` is at least as
good on every axis and not identical on all of them, so exact ties
survive (:func:`pareto_mask`, pure and unit-tested).  Candidates feasible
for no mission never join the front.  The dominated set ignores the
priority WEIGHTS on purpose: re-prioritizing must never change which
designs are efficient, only which efficient design wins.  The toggle
never silently drops: when the current thresholds leave NOTHING
eligible the front is empty, and the filtered views empty out with a
message instead of falling back to the whole (dominated) catalog.

The MOE-vs-cost scatter is a 2-D PROJECTION of that 4-axis dominance
space, so a front member can sit below-right of another point and still
be non-dominated: it wins on an axis the plane hides.  The dashboard
says so explicitly (:func:`front_justifications`, pure and unit-tested):
every front member's scatter tooltip and lineup card carry one line
naming hidden metrics against the points that 2-D-dominate it in the
drawn plane -- either one metric that strictly beats ALL of them, or (no
single metric covers every dominator) a minimal set of metrics such that
EVERY dominator strictly trails on at least one.  Non-domination over
cost plus those metrics guarantees a winning metric per dominator.

The scatter's INK tells that same 4-axis truth: every front member
wears the front accent in BOTH toggle states -- FILLED when it also
leads the drawn plane, an OPEN RING when its win lives on a hidden
axis -- and gray is reserved for dominated points (light gray:
infeasible), so 'Pareto only' can never paint a front member as chaff
(the maintainer's third report: off-staircase front members drawn in
the dominated gray).  The staircase line is the PLANE's frontier, not
THE front; an in-plot legend names each ink in a few words, and a hint
beside the pressed toggle says the whole filtered view is
non-dominated.

All linking runs in Python via traitlets observers -- the candidate
table is a couple hundred rows, so every front-end stays a dumb painter
per the house widget pattern.

Compromise scoring (:func:`compromise_scores`, pure and unit-tested):

* each mission's primary metric is min-max normalized over the
  candidates FEASIBLE for that mission (an infeasible mix's metric is
  what it would score if it could fly -- fiction, so it never stretches
  the scale);
* ``score = sum_m weight_m * normalized_m`` over the missions where the
  candidate is feasible, MINUS ``weight_m * INFEASIBLE_PENALTY`` where
  it is not: a design that cannot fly a weighted mission actively costs
  its weight instead of scoring a silent zero;
* weights are the sliders' 0-100 values normalized to sum one (all-zero
  falls back to equal weighting).

That score is the dashboard's MOE (measure of effectiveness): the
parcoords axis, the scatter's y, and the lineup ranking are all the same
number, recomputed on every slider move.

Requires the ``viz`` extra (anywidget + ipywidgets arrive with it):
``pip install "longeron[viz]"``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from itertools import product
from math import ceil
from typing import TYPE_CHECKING, Any

from .. import ast as A
from .. import model as M
from ..errors import MissingExtraError
from ._expr import AnalysisError
from .trades import TradeStudy

if TYPE_CHECKING:
    import anywidget

__all__ = [
    "DEFAULT_MISSIONS",
    "DEFAULT_THRESHOLDS",
    "INFEASIBLE_PENALTY",
    "apply_thresholds",
    "compromise_scores",
    "front_justifications",
    "mission_dashboard",
    "mission_dashboard_data",
    "pareto_mask",
]

#: score deducted (times the mission's weight) when a candidate cannot
#: fly a mission at all -- documented in the module docstring
INFEASIBLE_PENALTY = 0.5

#: the DeepScout mission trio (``examples/deepscout/missions.sysml``):
#: name -> (assembly, metric)
DEFAULT_MISSIONS: dict[str, tuple[str, str]] = {
    "ISR": ("ScoutMissions::IsrUav", "stationMinutes"),
    "logistics": ("ScoutMissions::LogisticsUav", "payloadRangeKgKm"),
    "intercept": ("ScoutMissions::InterceptUav", "maxTargetSpeed"),
}

#: requirement-threshold sliders per mission: ``key`` is the achieved
#: value (a derived metric, or a variant attribute via ``variant_attr``),
#: ``constraint`` the assert it re-arms, ``attr`` the assembly attribute
#: holding the model's default -- the sliders are anchored in the model
DEFAULT_THRESHOLDS: dict[str, list[dict[str, Any]]] = {
    "ISR": [
        {
            "key": "stationMinutes",
            "label": "station (min)",
            "constraint": "stationReq",
            "attr": "minStationMinutes",
            "step": 5.0,
        },
    ],
    "logistics": [
        {
            "key": "payloadKg",
            "label": "payload (kg)",
            "constraint": "payloadReq",
            "attr": "minPayloadKg",
            "step": 0.5,
            "variant_attr": ("cargo", "payloadKg"),
        },
        {
            "key": "deliveryRadiusKm",
            "label": "radius (km)",
            "constraint": "radiusReq",
            "attr": "minDeliveryRadiusKm",
            "step": 1.0,
        },
    ],
    "intercept": [
        {
            "key": "maxTargetSpeed",
            "label": "target (m/s)",
            "constraint": "canCatch",
            "attr": "targetSpeed",
            "step": 1.0,
        },
    ],
}


def _ipywidgets() -> Any:
    try:
        import ipywidgets
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError(
            "the mission dashboard", "ipywidgets (it arrives with anywidget)", "viz"
        ) from err
    return ipywidgets


# ---------------------------------------------------------------------------
# data preparation (interpreter-exact, widget-free)
# ---------------------------------------------------------------------------


def mission_dashboard_data(
    model: M.Model,
    missions: Mapping[str, tuple[str, str]] | None = None,
    thresholds: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Bake the dashboard's candidate table from a multi-mission model.

    Candidates are the Cartesian product of the variation points SHARED
    by every mission study (for the UAV example: airframe, motors,
    props, battery, material).  Per candidate and mission, EVERY
    equipment option is kept -- its exact metric, its achieved values
    for the mission's requirement thresholds, and whether its
    non-threshold constraints hold -- so requirement sliders can
    re-evaluate feasibility live without re-running the interpreter
    (:func:`apply_thresholds`).  ``cost`` is the shared ``baseCost``
    build-up when the model derives one.  Threshold defaults come from
    the subject's own attributes (``thresholds`` specs default to
    :data:`DEFAULT_THRESHOLDS`); slider ranges from the achieved values.
    The returned dict carries the studies themselves so the dashboard
    can compute margins lazily.
    """

    named = dict(missions or DEFAULT_MISSIONS)
    if not named:
        raise AnalysisError("mission_dashboard_data needs missions")
    studies = {name: TradeStudy(model, qname) for name, (qname, _) in named.items()}
    metric_of = {name: metric for name, (_, metric) in named.items()}
    first = next(iter(studies.values()))
    shared = [p for p in first.points if all(p in s.points for s in studies.values())]
    if not shared:
        raise AnalysisError("the mission studies share no variation points")

    spec_source = DEFAULT_THRESHOLDS if thresholds is None else thresholds
    specs: dict[str, list[dict[str, Any]]] = {}
    for name, entries in spec_source.items():
        if name not in studies:
            continue
        study = studies[name]
        specs[name] = [
            {
                "key": entry["key"],
                "label": entry["label"],
                "constraint": entry["constraint"],
                "step": float(entry.get("step", 1.0)),
                "variant_attr": entry.get("variant_attr"),
                "default": float(
                    study.interp.evaluate(A.FeatureRef((entry["attr"],)), study.assembly)
                ),
                "max": 0.0,  # widened to the achieved values below
            }
            for entry in entries
        ]

    candidates: list[dict[str, Any]] = []
    for combo in product(*(first.points[p].variants for p in shared)):
        selection = dict(zip(shared, combo, strict=True))
        cand: dict[str, Any] = {
            "selection": selection,
            "label": "/".join(combo),
            "options": {},
            "cost": None,
        }
        for name, study in studies.items():
            extras = [p for p in study.points if p not in shared]
            skip = {spec["constraint"] for spec in specs.get(name, ())}
            options: list[dict[str, Any]] = []
            for extra in product(*(study.points[p].variants for p in extras)):
                mix = {**selection, **dict(zip(extras, extra, strict=True))}
                arch = study.evaluate(mix)
                values: dict[str, float] = {}
                for spec in specs.get(name, ()):
                    if spec["variant_attr"] is not None:
                        point, attr = spec["variant_attr"]
                        value = float(study.points[point].variants[mix[point]][attr])
                    else:
                        value = float(arch.metrics[spec["key"]])
                    values[spec["key"]] = value
                    spec["max"] = max(spec["max"], value)
                options.append(
                    {
                        "mix": mix,
                        "metric": float(arch.metrics[metric_of[name]]),
                        "values": values,
                        "ok": not (set(arch.violations) - skip),
                    }
                )
                if cand["cost"] is None:
                    cand["cost"] = arch.metrics.get("baseCost")
            cand["options"][name] = options
        candidates.append(cand)

    for entries2 in specs.values():
        for spec in entries2:
            step = spec["step"]
            spec["max"] = max(ceil(spec["max"] / step) * step, spec["default"] * 2, step)
    return {
        "missions": [{"name": name, "metric": metric_of[name]} for name in named],
        "shared": shared,
        "studies": studies,
        "thresholds": specs,
        "candidates": candidates,
    }


# ---------------------------------------------------------------------------
# pure recompute helpers
# ---------------------------------------------------------------------------


def apply_thresholds(
    candidates: Sequence[Mapping[str, Any]],
    thresholds: Mapping[str, Mapping[str, float]],
) -> list[dict[str, Any]]:
    """The live per-candidate mission table under the given floors (pure).

    ``thresholds`` maps mission -> {value key -> minimum}.  An equipment
    option is eligible when its non-threshold constraints hold (baked
    ``ok``) AND every achieved value clears its floor; the best eligible
    option by mission metric represents the candidate.  When nothing is
    eligible the best-by-metric option is kept so the requirement cards
    can show *why* in red -- but the displayed metric is 0.0 and the
    mission infeasible.  Rows align with ``candidates``.
    """

    live: list[dict[str, Any]] = []
    for cand in candidates:
        row: dict[str, Any] = {"metric": {}, "feasible": {}, "mission_mix": {}, "values": {}}
        for mission, options in cand["options"].items():
            floors = thresholds.get(mission, {})
            eligible = [
                option
                for option in options
                if option["ok"]
                and all(option["values"].get(key, 0.0) >= floor for key, floor in floors.items())
            ]
            chosen = max(eligible or options, key=lambda option: option["metric"])
            row["feasible"][mission] = bool(eligible)
            row["metric"][mission] = chosen["metric"] if eligible else 0.0
            row["mission_mix"][mission] = chosen["mix"]
            row["values"][mission] = chosen["values"]
        live.append(row)
    return live


def compromise_scores(
    candidates: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float],
    *,
    penalty: float = INFEASIBLE_PENALTY,
) -> list[float]:
    """Weighted-compromise scores (the MOE), aligned with ``candidates``.

    Each candidate mapping needs ``metric`` and ``feasible`` sub-mappings
    keyed by the mission names in ``weights``.  Normalization bounds come
    from the *feasible* candidates per mission (a constant or empty
    feasible set normalizes to 1.0 for whoever is feasible); see the
    module docstring for the full scoring contract.
    """

    if not weights:
        raise AnalysisError("compromise_scores needs at least one mission")
    total = float(sum(weights.values()))
    share = {m: (float(w) / total if total else 1.0 / len(weights)) for m, w in weights.items()}
    bounds: dict[str, tuple[float, float]] = {}
    for mission in weights:
        values = [float(c["metric"][mission]) for c in candidates if c["feasible"][mission]]
        bounds[mission] = (min(values), max(values)) if values else (0.0, 0.0)

    scores: list[float] = []
    for cand in candidates:
        score = 0.0
        for mission, w in share.items():
            if not cand["feasible"][mission]:
                score -= w * penalty
                continue
            lo, hi = bounds[mission]
            norm = (float(cand["metric"][mission]) - lo) / (hi - lo) if hi > lo else 1.0
            score += w * norm
        scores.append(score)
    return scores


def pareto_mask(
    objectives: Sequence[Sequence[float]], eligible: Sequence[bool] | None = None
) -> list[bool]:
    """Non-dominated flags, larger-is-better on every objective axis.

    ``a`` is dominated when some eligible ``b`` is >= on every axis and
    differs on at least one -- so exact ties survive together (the same
    weak-dominance convention as :func:`longeron.analysis.trades.pareto`).
    Ineligible rows are flagged ``False`` and never dominate anyone.
    Orient minimized axes (cost) by negation before calling.
    """

    ok = list(eligible) if eligible is not None else [True] * len(objectives)
    rows = [tuple(float(v) for v in row) for row in objectives]
    flags: list[bool] = []
    for i, row in enumerate(rows):
        if not ok[i]:
            flags.append(False)
            continue
        dominated = any(
            ok[j] and all(x >= y for x, y in zip(other, row, strict=True)) and other != row
            for j, other in enumerate(rows)
        )
        flags.append(not dominated)
    return flags


def _front_flags(points: Sequence[tuple[float, float]], eligible: Sequence[bool]) -> list[bool]:
    """Non-dominated flags under (min x, max y), over the eligible points."""

    return pareto_mask([(-x, y) for x, y in points], eligible)


def front_justifications(
    points: Sequence[tuple[float, float]],
    metrics: Sequence[Mapping[str, float]],
    front: Sequence[bool],
) -> list[str | None]:
    """One-line alibis for front members drawn in a 2-D projection (pure).

    ``front`` flags non-domination over the FULL objective space;
    ``points`` are the drawn plane (x minimized, y maximized); ``metrics``
    hold each row's values on the axes the plane hides (larger is
    better).  A front member can be 2-D-dominated in the plane yet stay
    efficient, so every front row gets one compact line about its plane
    dominators (its "beaters"): the metric(s) on which it strictly beats
    ALL of them when such metrics exist, otherwise a greedy minimal
    metric set such that EVERY beater strictly trails on at least one
    (non-domination over cost plus these metrics guarantees each beater
    trails somewhere, but no single metric need cover them all).  Front
    rows nothing 2-D-dominates are called unbeaten; rows off the front
    get ``None``.  Exact plane ties never count as beaters (they overlap
    in the plot, so they cannot mislead).
    """

    from .viz import _fmt  # the house number formatting

    rows = [(float(x), float(y)) for x, y in points]
    out: list[str | None] = []
    for i, on in enumerate(front):
        if not on:
            out.append(None)
            continue
        x, y = rows[i]
        beaters = [
            j for j, (bx, by) in enumerate(rows) if bx <= x and by >= y and (bx, by) != (x, y)
        ]
        if not beaters:
            out.append("front: unbeaten in this plane")
            continue
        keys = list(metrics[i])
        mine = {key: float(metrics[i][key]) for key in keys}
        wins_of = {j: {key for key in keys if mine[key] > float(metrics[j][key])} for j in beaters}
        if any(not wins for wins in wins_of.values()):
            # ponytail: unreachable when ``front`` comes from pareto_mask over cost+metrics
            out.append("front: non-dominated over the full objectives")
            continue
        full = [key for key in keys if all(key in wins_of[j] for j in beaters)]
        if full:
            named = ", ".join(f"{key} {_fmt(mine[key])}" for key in full)
            verb = "tops" if len(full) == 1 else "top"
            out.append(f"front: {named} {verb} every pick that beats it in this plane")
            continue
        cover: list[str] = []  # greedy set cover: small, deterministic, honest
        left = set(beaters)
        while left:
            best = max(keys, key=lambda key: sum(1 for j in left if key in wins_of[j]))
            cover.append(best)
            left -= {j for j in left if best in wins_of[j]}
        named = " or ".join(f"{key} {_fmt(mine[key])}" for key in cover)
        out.append(f"front: every pick that beats it in this plane trails it on {named}")
    return out


# ---------------------------------------------------------------------------
# the MOE-vs-cost scatter (house anywidget: Python bakes, JS paints)
# ---------------------------------------------------------------------------

#: the SELECTION accent, applied identically to the selected card border,
#: scatter halo, parcoords traced line, and 3D emissive pop.  Violet on
#: purpose: the blue family belongs to the parcoords brush / frontier
#: (``viz.ACCENT``), terracotta to the top-N pick rings (``viz.WARM``),
#: green/red to the requirement verdicts -- so selection takes the one
#: free channel and stays visible WHILE brushing (maintainer finding).
_SEL = "#7b4fa6"

_SCATTER_ESM = r"""
function render({ model, el }) {
  el.classList.add("longeron-moefront");

  function draw() {
    el.innerHTML = "";
    const P = JSON.parse(model.get("payload_json"));
    const W = el.clientWidth || model.get("width_px");
    const H = model.get("height_px");
    const M = { top: 16, right: 14, bottom: 34, left: 52 };
    const NS = "http://www.w3.org/2000/svg";
    const make = (tag, attrs, parent) => {
      const node = document.createElementNS(NS, tag);
      for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
      parent.appendChild(node);
      return node;
    };
    const svg = make("svg", { viewBox: `0 0 ${W} ${H}` }, el);
    svg.style.maxWidth = W + "px";
    if (!P.points.length) return;
    const xs = P.points.map((p) => p.x);
    const ys = P.points.map((p) => p.y);
    const xlo = Math.min(...xs), xhi = Math.max(...xs);
    const ylo = Math.min(...ys), yhi = Math.max(...ys);
    const sx = (x) => M.left +
      (xhi > xlo ? (x - xlo) / (xhi - xlo) : 0.5) * (W - M.left - M.right);
    const sy = (y) => M.top +
      (yhi > ylo ? (yhi - y) / (yhi - ylo) : 0.5) * (H - M.top - M.bottom);

    make("line", { x1: M.left, y1: H - M.bottom, x2: W - M.right,
                   y2: H - M.bottom, class: "longeron-moefront-axis" }, svg);
    make("line", { x1: M.left, y1: M.top, x2: M.left, y2: H - M.bottom,
                   class: "longeron-moefront-axis" }, svg);
    const text = (x, y, cls, s, anchor) => {
      const t = make("text", { x, y, class: cls }, svg);
      if (anchor) t.setAttribute("text-anchor", anchor);
      t.textContent = s;
      return t;
    };
    text(M.left, H - M.bottom + 14, "longeron-moefront-tick", P.xticks[0],
         "middle");
    text(W - M.right, H - M.bottom + 14, "longeron-moefront-tick",
         P.xticks[1], "middle");
    text(M.left - 6, H - M.bottom + 3, "longeron-moefront-tick", P.yticks[0],
         "end");
    text(M.left - 6, M.top + 4, "longeron-moefront-tick", P.yticks[1], "end");
    text((M.left + W - M.right) / 2, H - 4, "longeron-moefront-title",
         P.xlabel, "middle");
    const ylab = text(0, 0, "longeron-moefront-title", P.ylabel, "middle");
    ylab.setAttribute("transform",
      `translate(12 ${(M.top + H - M.bottom) / 2}) rotate(-90)`);

    // the staircase is this PLANE's frontier (min cost, max MOE) --
    // NOT the front: dominance spans axes the plane hides
    const stair = P.points.filter((p) => p.stair)
      .sort((a, b) => a.x - b.x || b.y - a.y);
    if (stair.length > 1) {
      let d = `M${sx(stair[0].x)},${sy(stair[0].y)}`;
      for (let i = 1; i < stair.length; i++)
        d += `H${sx(stair[i].x)}V${sy(stair[i].y)}`;
      make("path", { d, class: "longeron-moefront-step" }, svg);
    }
    const sel = model.get("selected");
    P.points.forEach((p, j) => {
      const cls = p.front
        ? (p.stair ? "longeron-moefront-dot front stair"
                   : "longeron-moefront-dot front")
        : p.feasible ? "longeron-moefront-dot"
        : "longeron-moefront-dot infeasible";
      if (p.pick) make("circle", { cx: sx(p.x), cy: sy(p.y), r: 7,
                                   class: "longeron-moefront-pick" }, svg);
      if (j === sel) make("circle", { cx: sx(p.x), cy: sy(p.y), r: 10,
                                      class: "longeron-moefront-sel" }, svg);
      const dot = make("circle", { cx: sx(p.x), cy: sy(p.y),
                                   r: p.front ? 4 : 2.6, class: cls }, svg);
      const title = document.createElementNS(NS, "title");
      title.textContent = p.label + "\n" + P.xlabel + " " + p.x.toFixed(0) +
        " \u00b7 " + P.ylabel + " " + p.y.toFixed(2) +
        (p.feasible ? "" : "  (infeasible everywhere)") +
        (p.why ? "\n" + p.why : "");
      dot.appendChild(title);
    });

    // the ink legend, in the utopia corner (top-left of the plane is
    // beyond the front, so it stays point-free at any density); each
    // entry appears only when its ink is actually on the plot
    const legend = [];
    if (P.points.some((p) => p.front && p.stair))
      legend.push(["front stair", 4, "front: leads this plane"]);
    if (P.points.some((p) => p.front && !p.stair))
      legend.push(["front", 4, "front: wins on hidden axes"]);
    if (P.points.some((p) => !p.front && p.feasible))
      legend.push(["", 2.6, "dominated: a better design exists"]);
    legend.forEach(([kind, r, label], k) => {
      const y = M.top + 10 + 13 * k;
      make("circle", { cx: M.left + 12, cy: y, r,
                       class: "longeron-moefront-dot legend " + kind }, svg);
      text(M.left + 20, y + 3, "longeron-moefront-legend", label);
    });
    if (stair.length > 1) {
      const y = M.top + 10 + 13 * legend.length;
      make("line", { x1: M.left + 6, y1: y, x2: M.left + 18, y2: y,
                     class: "longeron-moefront-step" }, svg);
      text(M.left + 20, y + 3, "longeron-moefront-legend",
           "frontier in this plane only");
    }
  }

  model.on("change:payload_json", draw);
  model.on("change:selected", draw);
  let lastW = el.clientWidth;
  new ResizeObserver(() => {
    const w = el.clientWidth;
    if (w && Math.abs(w - lastW) > 1) { lastW = w; draw(); }
  }).observe(el);
  draw();
}
export default { render };
"""

_SCATTER_CSS = """
.longeron-moefront svg { display: block; width: 100%; height: auto; }
.longeron-moefront-axis { stroke: #c4c7cc; stroke-width: 1; }
.longeron-moefront-tick { fill: #6b7078; font-size: 9px;
  font-variant-numeric: tabular-nums; }
.longeron-moefront-title { fill: #2b2d31; font-size: 10px; font-weight: 600; }
.longeron-moefront-dot { fill: #c3c7cd; }
.longeron-moefront-dot.infeasible { fill: #e3e5e8; }
.longeron-moefront-dot.front { fill: #ffffff; stroke: #2f6b8f;
  stroke-width: 1.4; }
.longeron-moefront-dot.front.stair { fill: #2f6b8f; stroke: #ffffff;
  stroke-width: 0.7; }
.longeron-moefront-legend { fill: #6b7078; font-size: 9px; }
.longeron-moefront-step { fill: none; stroke: #2f6b8f; stroke-width: 1.3;
  opacity: 0.85; }
.longeron-moefront-pick { fill: none; stroke: #c2603e; stroke-width: 1.4; }
.longeron-moefront-sel { fill: none; stroke: %SEL%; stroke-width: 2.2; }
.longeron-moefront { font-family: Helvetica, Arial, sans-serif; }
""".replace("%SEL%", _SEL)

_SCATTER_CLS: type[anywidget.AnyWidget] | None = None


def _scatter_class() -> type[anywidget.AnyWidget]:
    global _SCATTER_CLS
    if _SCATTER_CLS is not None:
        return _SCATTER_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the MOE-vs-cost scatter", "anywidget", "viz") from err

    class MoeFrontWidget(_anywidget.AnyWidget):
        """MOE-vs-cost scatter with the 2D front highlighted."""

        _esm = _SCATTER_ESM
        _css = _SCATTER_CSS
        payload_json = traitlets.Unicode("{}").tag(sync=True)
        #: index (into ``points``) of the selected candidate; -1 = none
        selected = traitlets.Int(-1).tag(sync=True)
        width_px = traitlets.Int(360).tag(sync=True)
        height_px = traitlets.Int(300).tag(sync=True)

    _SCATTER_CLS = MoeFrontWidget
    return MoeFrontWidget


# ---------------------------------------------------------------------------
# the lineup cards (house anywidget: Python bakes, JS paints; hover syncs)
# ---------------------------------------------------------------------------

_LINEUP_ESM = r"""
function render({ model, el }) {
  el.classList.add("longeron-lineup");
  const send = (line) => { model.set("hover", line); model.save_changes(); };

  function mark() {
    const on = model.get("selected");
    for (const div of el.querySelectorAll(".longeron-lineup-card")) {
      const hit = Number(div.dataset.line) === on;
      div.classList.toggle("pinned", hit);
      if (hit) div.scrollIntoView({ block: "nearest" });
    }
  }

  function draw() {
    el.innerHTML = "";
    const head = document.createElement("div");
    head.className = "longeron-lineup-head";
    head.textContent = "lineup \u00b7 hover traces \u00b7 click selects";
    el.appendChild(head);
    for (const card of JSON.parse(model.get("cards_json"))) {
      const div = document.createElement("div");
      div.className = "longeron-lineup-card";
      div.dataset.line = card.line;
      div.innerHTML = "<b>" + card.mark + card.label + "</b>" +
        "<div class='longeron-lineup-nums'>MOE " + card.moe +
        (card.cost ? " \u00b7 $" + card.cost : "") + "</div>" +
        (card.why ? "<div class='longeron-lineup-why" +
          (card.front ? "" : " dominated") + "'>" + card.why + "</div>" : "");
      div.addEventListener("mouseenter", () => send(card.line));
      div.addEventListener("mouseleave", () => send(-1));
      div.addEventListener("click", () => {
        model.set("selected",
                  model.get("selected") === card.line ? -1 : card.line);
        model.save_changes();
      });
      el.appendChild(div);
    }
    mark();
  }

  model.on("change:cards_json", draw);
  model.on("change:selected", mark);
  draw();
}
export default { render };
"""

_LINEUP_CSS = """
.longeron-lineup { font-family: Helvetica, Arial, sans-serif;
  overflow-y: auto; }
.longeron-lineup-head { font-size: 10px; font-weight: 600; color: #6b7078;
  letter-spacing: 0.06em; text-transform: uppercase; margin: 2px 0 4px; }
.longeron-lineup-card { border: 1px solid #e2e2e2; border-radius: 6px;
  padding: 5px 8px; margin-bottom: 5px; background: #fcfcfb;
  font-size: 11px; line-height: 1.35; cursor: pointer; }
.longeron-lineup-card:hover { border-color: #20303c; }
.longeron-lineup-card.pinned { border-color: %SEL%; background: #f6f2f9;
  box-shadow: inset 0 0 0 1px %SEL%; }
.longeron-lineup-nums { color: #6b7078;
  font-variant-numeric: tabular-nums; }
.longeron-lineup-why { color: #2f6b8f; margin-top: 2px; }
.longeron-lineup-why.dominated { color: #8a8f98; }
""".replace("%SEL%", _SEL)

_LINEUP_CLS: type[anywidget.AnyWidget] | None = None


def _lineup_class() -> type[anywidget.AnyWidget]:
    global _LINEUP_CLS
    if _LINEUP_CLS is not None:
        return _LINEUP_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the lineup cards", "anywidget", "viz") from err

    class LineupCardsWidget(_anywidget.AnyWidget):
        """One card per lineup pick, with its front justification."""

        _esm = _LINEUP_ESM
        _css = _LINEUP_CSS
        cards_json = traitlets.Unicode("[]").tag(sync=True)
        #: parcoords line index under the pointer (JS -> Python; -1 = none)
        hover = traitlets.Int(-1).tag(sync=True)
        #: parcoords line index of the SELECTED card (two-way; -1 = none):
        #: card clicks write it, and Python writes it back when a 3D model
        #: is clicked or a re-bake re-seats the selection
        selected = traitlets.Int(-1).tag(sync=True)

    _LINEUP_CLS = LineupCardsWidget
    return LineupCardsWidget


# the dashboard's parcoords: the house widget plus (a) a Python-driven
# ``highlight`` line index reusing the existing hover style plus a sticky
# ``traced`` selection line in the selection accent -- the lineup cards
# drive both through traitlets observers; (b) brush INTERVALS synced by
# axis name so the kernel recomputes the brushed subset itself; (c) a
# fluid draw width so the plot row can flex (finding 3)
_PC_HIGHLIGHT_JS = r"""
function renderHighlight(ctx) {
  render(ctx);
  const { model, el } = ctx;
  const apply = () => {
    const hov = model.get("highlight");
    const sel = model.get("traced");
    el.querySelectorAll(".longeron-pc-line").forEach((path, i) => {
      path.classList.toggle("hover", i === hov);
      path.classList.toggle("selected", i === sel);
    });
  };
  model.on("change:highlight", apply);
  model.on("change:traced", apply);
  model.on("change:table_json", apply);  // registered after draw: runs after re-bakes
  apply();
}
export default { render: renderHighlight };
"""

_PC_SEL_CSS = """
.longeron-pc-line.selected:not(.hover) { stroke: %SEL%; stroke-width: 2.2;
  opacity: 1; }
""".replace("%SEL%", _SEL)

_PC_HL_CLS: type[anywidget.AnyWidget] | None = None


def _highlight_parcoords_class() -> type[anywidget.AnyWidget]:
    global _PC_HL_CLS
    if _PC_HL_CLS is not None:
        return _PC_HL_CLS
    from . import viz

    base = viz._parcoords_class()
    import traitlets

    surgeries = (
        # fluid width: the dashboard rows flex, so draw at the measured
        # host width (width_px stays the pre-layout fallback)
        (
            'const W = model.get("width_px");',
            'const W = el.clientWidth || model.get("width_px");',
        ),
        # sync the brush INTERVALS by axis name alongside the passing
        # rows: the kernel recomputes the brushed subset against the
        # CURRENT pool, so no transition can consult stale row indices
        (
            'model.set("selected", JSON.stringify(active));',
            'model.set("selected", JSON.stringify(active));\n'
            "      const named = {};\n"
            "      brushes.forEach((b, k) => { if (b) named[axes[k].name] = b; });\n"
            '      model.set("brushes", JSON.stringify(named));',
        ),
        # re-draw when the flexed host resizes
        (
            'model.on("change:table_json", draw);',
            'model.on("change:table_json", draw);\n'
            "  let lastW = el.clientWidth;\n"
            "  new ResizeObserver(() => {\n"
            "    const w = el.clientWidth;\n"
            "    if (w && Math.abs(w - lastW) > 1) { lastW = w; draw(); }\n"
            "  }).observe(el);",
        ),
        ("export default { render };", _PC_HIGHLIGHT_JS.strip()),
    )
    esm = viz._PC_ESM
    for old, new in surgeries:
        patched = esm.replace(old, new)
        if patched == esm:  # the seam moved: fail loud, never silently broken
            raise AnalysisError(f"viz._PC_ESM lost its seam {old!r}; update dashboard.py")
        esm = patched

    class HighlightParCoordsWidget(base):  # type: ignore[valid-type,misc]
        """House parcoords + highlight/selection lines + synced brushes."""

        _esm = esm
        _css = viz._PC_CSS + _PC_SEL_CSS
        #: line index drawn with the hover style (Python -> JS; -1 = none)
        highlight = traitlets.Int(-1).tag(sync=True)
        #: line index drawn with the SELECTION accent (Python -> JS)
        traced = traitlets.Int(-1).tag(sync=True)
        #: JSON object {axis name: [lo, hi]} of the live brush intervals
        #: in normalized t-space (JS -> Python; "{}" = no brush)
        brushes = traitlets.Unicode("{}").tag(sync=True)

    _PC_HL_CLS = HighlightParCoordsWidget
    return HighlightParCoordsWidget


_DASH_VIEWER_CLS: type[anywidget.AnyWidget] | None = None


def _dash_viewer_class() -> type[anywidget.AnyWidget]:
    """The house 3D viewer, dashboard-tuned.

    Three ESM patches: the canvas keeps a FIXED height (``height_px``)
    while filling the flexed host width, so a fluid dashboard never
    grows past the one-screen budget; the linked-selection emissive
    accent is pinned to the dashboard's selection violet (:data:`_SEL`)
    so the 3D pop matches the card/scatter/parcoords selection exactly
    (the base widget's JupyterLab brand blue reads too close to the
    parcoords brush blue -- the maintainer finding); and every click
    stamps ``picked_json`` with a monotonic counter so repeat clicks
    (background after a card-made selection, the same part twice) still
    change the trait and reach the kernel -- state alone would silently
    swallow them.
    """

    global _DASH_VIEWER_CLS
    if _DASH_VIEWER_CLS is not None:
        return _DASH_VIEWER_CLS
    from . import viewer3d

    surgeries = (
        ("height = Math.round(w / aspect);", 'height = model.get("height_px");'),
        (
            "const accent = (getComputedStyle(el)\n"
            '      .getPropertyValue("--jp-brand-color2") || "").trim() || "#2196f3";',
            f'const accent = "{_SEL}";',
        ),
        (
            "const raycaster = new THREE.Raycaster();",
            "const raycaster = new THREE.Raycaster();\n  let pickStamp = 0;",
        ),
        (
            'model.set("picked_json",\n'
            "              JSON.stringify(hit ? [hit.object.userData.key] : []));",
            'model.set("picked_json", JSON.stringify(\n'
            "      hit ? [hit.object.userData.key, ++pickStamp] : [++pickStamp]));",
        ),
    )
    esm = viewer3d._ESM
    for old, new in surgeries:
        patched = esm.replace(old, new)
        if patched == esm:  # the seam moved: fail loud, never silently broken
            raise AnalysisError(f"viewer3d._ESM lost its seam {old!r}; update dashboard.py")
        esm = patched
    base = viewer3d._viewer_class()

    class DashboardViewerWidget(base):  # type: ignore[valid-type,misc]
        """Mesh viewer with a fixed height + the dashboard selection accent."""

        _esm = esm

    _DASH_VIEWER_CLS = DashboardViewerWidget
    return DashboardViewerWidget


# ---------------------------------------------------------------------------
# the dashboard composition
# ---------------------------------------------------------------------------

_OK = "#3a7d44"
_BAD = "#b54a35"

_CARD_STYLE = (
    "border:1px solid #e2e2e2; border-radius:8px; "
    "padding:8px 12px; margin:0 4px; background:#fcfcfb; "
    "font-family:Helvetica,Arial,sans-serif; font-size:12px; "
    "min-width:230px"
)

_SECTION_STYLE = (
    "font-family:Helvetica,Arial,sans-serif; font-size:11px; "
    "font-weight:600; color:#6b7078; letter-spacing:0.06em; "
    "text-transform:uppercase; margin:4px 0 2px"
)


def _card_html(
    mission: str,
    metric: str,
    row: Mapping[str, Any],
    margins: Mapping[str, Mapping[str, Any]],
    specs: Sequence[Mapping[str, Any]],
    floors: Mapping[str, float],
) -> str:
    feasible = row["feasible"][mission]
    badge = (
        f'<span style="color:{_OK}">feasible</span>'
        if feasible
        else f'<span style="color:{_BAD}">infeasible</span>'
    )
    value = row["metric"][mission]
    by_constraint = {spec["constraint"]: spec for spec in specs}
    rows = []
    for name, entry in margins.items():
        spec = by_constraint.get(name)
        if spec is not None:  # threshold rows track the sliders live
            floor = float(floors.get(spec["key"], spec["default"]))
            achieved = float(row["values"][mission].get(spec["key"], 0.0))
            entry = {
                "margin": achieved - floor,
                "ok": achieved >= floor,
                "text": f"{spec['key']} >= {floor:g}",
            }
        color = _OK if entry["ok"] else _BAD
        shown = (
            ("&#10003;" if entry["ok"] else "&#10007;")
            if entry["margin"] is None
            else f"{entry['margin']:+.2f}"
        )
        rows.append(
            f'<tr><td style="padding-right:8px">{name}</td>'
            f'<td style="color:#8a8f98">{entry["text"]}</td>'
            f'<td style="text-align:right; color:{color}; '
            f'font-variant-numeric:tabular-nums"><b>{shown}</b></td></tr>'
        )
    return (
        f'<div style="{_CARD_STYLE}">'
        f"<b>{mission}</b> &mdash; {metric} "
        f'<span style="font-variant-numeric:tabular-nums">'
        f"{value:.1f}</span> &nbsp;{badge}"
        f'<table style="margin-top:4px; border-spacing:0; '
        f'font-size:11px">{"".join(rows)}</table></div>'
    )


def _summary_html(
    row: Mapping[str, Any],
    metric_of: Mapping[str, str],
    mission_names: Sequence[str],
) -> str:
    """The all-missions scorecard for one candidate (tab 0)."""

    lines = []
    for name in mission_names:
        feasible = row["feasible"][name]
        color = _OK if feasible else _BAD
        verdict = "feasible" if feasible else "infeasible"
        lines.append(
            f'<tr><td style="padding-right:10px"><b>{name}</b></td>'
            f'<td style="color:#8a8f98; padding-right:10px">{metric_of[name]}</td>'
            f'<td style="text-align:right; font-variant-numeric:tabular-nums; '
            f'padding-right:10px">{row["metric"][name]:.1f}</td>'
            f'<td style="color:{color}">{verdict}</td></tr>'
        )
    return (
        f'<div style="{_CARD_STYLE}"><b>best compromise, mission by '
        f'mission</b><table style="margin-top:4px; border-spacing:0; '
        f'font-size:11px">{"".join(lines)}</table></div>'
    )


def mission_dashboard(
    source: M.Model | Mapping[str, Any],
    *,
    missions: Mapping[str, tuple[str, str]] | None = None,
    width_px: int | None = None,
) -> Any:
    """The linked mission-compromise dashboard (an ipywidgets ``VBox``).

    ``source`` is either a loaded model (the candidate table is baked
    via :func:`mission_dashboard_data`, a half-minute of interpreter
    time) or an already-prepared data dict from that function.  By
    default the layout is FLUID: rows and plots stretch to the container
    width in their design proportions while the row heights stay fixed,
    so the dashboard fills any screen without ever needing vertical
    scroll at 1080p.  Pass ``width_px`` to pin a fixed total width
    instead (see the module docstring for the layout).

    The returned layout exposes its pieces for scripting and tests:
    ``.sliders`` (mission -> priority IntSlider), ``.requirements``
    (mission -> key -> threshold FloatSlider), ``.top_n``,
    ``.pareto_toggle`` (dominated-candidate filter), ``.pareto_hint``
    (the one-line all-non-dominated hint beside the pressed toggle),
    ``.tabs`` (summary +
    one tab per mission), ``.parcoords`` (its ``brushes`` trait carries
    the live brush intervals by axis name; ``traced`` the selected line),
    ``.scatter``, ``.viewer``, ``.cards``, ``.summary``, ``.lineup``
    (the pick cards; ``hover`` carries the transient parcoords line
    index, mirrored to ``.parcoords.highlight``; ``selected`` the sticky
    selected card line), ``.data``, ``.live`` (the current
    :func:`apply_thresholds` table), ``.front`` (per-candidate
    non-dominated flags), ``.pool`` (the candidate indices currently in
    view -- EMPTY when the toggle is on and nothing is eligible),
    ``.picks`` (the current top-N candidate indices), ``.scores`` (the
    MOE per candidate), ``.selected`` (the selected candidate index, or
    ``None``), and ``.select(index)`` (drive the linked selection from
    Python; ``None`` clears).
    """

    from . import geometry, viz  # local: keeps import cheap

    widgets = _ipywidgets()
    data = dict(source) if isinstance(source, Mapping) else mission_dashboard_data(source, missions)
    mission_names = [m["name"] for m in data["missions"]]
    metric_of = {m["name"]: m["metric"] for m in data["missions"]}
    candidates = data["candidates"]
    studies = data["studies"]
    shared = data["shared"]
    specs: Mapping[str, Sequence[Mapping[str, Any]]] = data.get("thresholds", {})
    has_cost = bool(candidates) and candidates[0]["cost"] is not None

    # one-screen budget: header (~40) + plot row (~360) + control row
    # (~470) stays under ~900 px of content height.  Row HEIGHTS are
    # FIXED; the pixel widths below are the design proportions (and the
    # exact widths when ``width_px`` pins the layout)
    fluid = width_px is None
    base_w = 1500 if width_px is None else int(width_px)
    scatter_w, plot_h = 400, 330
    pc_w = max(700, base_w - scatter_w - 40)
    tab_w = 640
    lineup_w = 200
    viewer_w = max(560, base_w - tab_w - lineup_w - 60)
    viewer_h = 430

    req_sliders: dict[str, dict[str, Any]] = {
        name: {
            spec["key"]: widgets.FloatSlider(
                value=spec["default"],
                min=0.0,
                max=spec["max"],
                step=spec["step"],
                description=spec["label"],
                continuous_update=True,
                readout_format=".1f",
                style={"description_width": "88px"},
                layout=widgets.Layout(width="264px"),
            )
            for spec in specs.get(name, ())
        }
        for name in mission_names
    }
    weight_sliders = {
        name: widgets.IntSlider(
            value=50,
            min=0,
            max=100,
            description=name,
            continuous_update=True,
            style={"description_width": "88px"},
            layout=widgets.Layout(width="264px"),
        )
        for name in mission_names
    }
    top_n = widgets.IntSlider(
        value=4,
        min=2,
        max=8,
        description="lineup N",
        continuous_update=True,
        style={"description_width": "64px"},
        # a usable track: never shrunk by the header's flexing blurb
        layout=widgets.Layout(width="380px", min_width="380px", flex="0 0 auto"),
    )
    pareto_toggle = widgets.ToggleButton(
        value=False,
        description="Pareto only",
        tooltip=(
            "show only non-dominated candidates (cost minimized, every "
            "mission metric maximized; ties survive; priority weights "
            "never change the front)"
        ),
        layout=widgets.Layout(width="110px", flex="0 0 auto"),
    )
    #: self-describing 'Pareto only' state: the one-line hint beside the
    #: pressed toggle (empty when released) -- the maintainer kept landing
    #: in the filtered view and reading its gray as dominated
    pareto_hint = widgets.HTML(layout=widgets.Layout(flex="0 0 auto", margin="0 12px 0 6px"))
    cards = {name: widgets.HTML() for name in mission_names}
    ranking = widgets.HTML()
    summary = widgets.HTML()
    viewer = _dash_viewer_class()(
        mesh_json=json.dumps({"unit": "m", "parts": [], "bounds": [[0, 0, 0], [0, 0, 0]]}),
        width_px=viewer_w,
        height_px=viewer_h,
    )
    scatter = _scatter_class()(width_px=scatter_w, height_px=plot_h)
    lineup = _lineup_class()()

    geo_study = studies[mission_names[0]]
    mesh_cache: dict[int, dict[str, Any]] = {}

    def _mesh(index: int) -> dict[str, Any]:
        if index not in mesh_cache:
            from .trades import Architecture

            arch = Architecture(selection=dict(candidates[index]["selection"]), metrics={})
            mesh = geometry.mission_geometry(geo_study, arch)
            # per-candidate identity keys: :func:`geometry.lineup` carries
            # them through its label prefixes, so a 3D click can name its
            # candidate and the selection can pop the whole model
            mesh["parts"] = [{**part, "key": f"cand:{index}"} for part in mesh["parts"]]
            mesh_cache[index] = mesh
        return mesh_cache[index]

    margin_cache: dict[tuple[str, tuple[tuple[str, str], ...]], dict[str, Any]] = {}

    def _margins(mission: str, mix: Mapping[str, str]) -> dict[str, Any]:
        key = (mission, tuple(sorted(mix.items())))
        if key not in margin_cache:
            margin_cache[key] = studies[mission].margins(dict(mix))
        return margin_cache[key]

    def _floors() -> dict[str, dict[str, float]]:
        return {
            name: {key: float(slider.value) for key, slider in req_sliders[name].items()}
            for name in mission_names
        }

    axes = [
        *shared,
        *(["cost"] if has_cost else []),
        *(metric_of[n] for n in mission_names),
        "MOE",
    ]

    def _rows(live: list[dict[str, Any]], scores: list[float]) -> list[dict[str, Any]]:
        rows = []
        for cand, row, score in zip(candidates, live, scores, strict=True):
            entry: dict[str, Any] = dict(cand["selection"])
            if has_cost:
                entry["cost"] = cand["cost"]
            for name in mission_names:
                entry[metric_of[name]] = row["metric"][name]
            entry["MOE"] = round(score, 4)
            entry["label"] = cand["label"]
            entry["feasible"] = any(row["feasible"].values())
            rows.append(entry)
        return rows

    def _objectives(live: list[dict[str, Any]]) -> list[tuple[float, ...]]:
        """The dominance axes: -cost (so larger is better) + mission metrics."""

        return [
            (
                *((-float(candidates[i]["cost"]),) if has_cost else ()),
                *(float(live[i]["metric"][name]) for name in mission_names),
            )
            for i in range(len(candidates))
        ]

    floors0 = _floors()
    live0 = apply_thresholds(candidates, floors0)
    scores0 = compromise_scores(live0, dict.fromkeys(mission_names, 50.0))
    table0 = viz.parcoords_payload(_rows(live0, scores0), axes)
    pc = _highlight_parcoords_class()(
        table_json=json.dumps(table0),
        selected=json.dumps(list(range(len(table0["lines"])))),
        width_px=pc_w,
        height_px=plot_h,
    )
    # fixed-HEIGHT row members; fluid mode lets the two plots split the
    # plot row in their design ratio (grow factors = design widths, zero
    # basis) and the 3D viewer absorb the control row's slack, while the
    # tab set and the cards column keep their design widths.  Fixed mode
    # pins everything (HBox children default to flex-shrink 1, and a
    # shrunk parcoords/tab bar is exactly the cramped layout this replaces)
    if fluid:
        pc.layout = widgets.Layout(flex=f"{pc_w} 1 0px", min_width="480px", overflow="hidden")
        scatter.layout = widgets.Layout(
            flex=f"{scatter_w} 1 0px", min_width="260px", overflow="hidden"
        )
        viewer.layout = widgets.Layout(flex="1 1 0px", min_width="420px", overflow="hidden")
    else:
        for widget, w in ((pc, pc_w), (scatter, scatter_w), (viewer, viewer_w)):
            widget.layout = widgets.Layout(width=f"{w}px", flex="0 0 auto")
    lineup.layout = widgets.Layout(
        width=f"{lineup_w}px", height=f"{viewer_h + 34}px", flex="0 0 auto"
    )

    box = widgets.VBox()
    box.live = live0
    box.scores = scores0
    box.picks = []
    box.front = []
    box.pool = list(range(len(candidates)))
    box.selected = None  # the ONE linked-selection state (candidate index)

    syncing = {"on": False}  # guards the selection fan-out re-entrancy

    def _apply_selection() -> None:
        """Repaint every view from the one selection state (violet)."""

        sel = box.selected
        pos = box.pool.index(sel) if sel in box.pool else -1
        picked = sel is not None and sel in box.picks
        syncing["on"] = True
        try:
            lineup.selected = pos if picked else -1
            pc.traced = pos
            scatter.selected = pos
            viewer.highlight([f"cand:{sel}"] if picked else [])
        finally:
            syncing["on"] = False

    def _select(index: int | None) -> None:
        """Select one candidate in every linked view (``None`` clears)."""

        box.selected = index if index in box.pool else None
        _apply_selection()

    def _recompute(_change: Any = None) -> None:
        floors = _floors()
        live = apply_thresholds(candidates, floors)
        weights = {name: float(weight_sliders[name].value) for name in mission_names}
        scores = compromise_scores(live, weights)
        box.live = live
        box.scores = scores

        eligible = [any(row["feasible"].values()) for row in live]
        front = pareto_mask(_objectives(live), eligible)
        box.front = front
        # the toggle NEVER silently drops: an empty front (nothing
        # eligible at these thresholds) empties the filtered views and
        # says so below, instead of falling back to the whole catalog
        pool = (
            [i for i, on in enumerate(front) if on]
            if pareto_toggle.value
            else list(range(len(candidates)))
        )
        box.pool = pool
        pareto_hint.value = (
            '<span style="font-family:Helvetica,Arial,sans-serif; '
            f'font-size:11px; color:{viz.ACCENT}">all shown are '
            "non-dominated (4 objectives)</span>"
            if pareto_toggle.value
            else ""
        )

        rows = _rows(live, scores)
        payload = (
            viz.parcoords_payload([rows[i] for i in pool], axes)
            if pool
            else {"axes": viz.parcoords_payload(rows, axes)["axes"], "lines": []}
        )
        table = json.dumps(payload)
        if pc.table_json != table:  # identical re-bakes stay silent
            pc.table_json = table

        # the brushed subset, recomputed KERNEL-SIDE from the synced
        # intervals against the table just baked: a toggle flip or slider
        # move can never pair fresh rows with stale brushed row indices,
        # and a brush that excludes everything empties the picks honestly
        brush_map: dict[str, Any] = json.loads(pc.brushes or "{}")
        if brush_map:
            at = {axis["name"]: k for k, axis in enumerate(payload["axes"])}
            subset = [
                pool[j]
                for j, line in enumerate(payload["lines"])
                if all(
                    lo <= line["t"][at[name]] <= hi
                    for name, (lo, hi) in brush_map.items()
                    if name in at
                )
            ]
        else:  # the scripting seam: ``selected`` positions in the current table
            brushed = [pool[j] for j in pc.selected_indices() if 0 <= j < len(pool)]
            subset = brushed or pool
        order = sorted(subset, key=lambda i: -scores[i])
        picks = order[: int(top_n.value)]
        box.picks = picks

        whys: list[str | None] = [None] * len(pool)
        if has_cost and pool:
            points = [(float(candidates[i]["cost"]), scores[i]) for i in pool]
            shown_eligible = [eligible[i] for i in pool]
            stairs = _front_flags(points, shown_eligible)
            whys = front_justifications(
                points,
                [{metric_of[n]: live[i]["metric"][n] for n in mission_names} for i in pool],
                [front[i] for i in pool],
            )
            pick_set = set(picks)
            scatter.payload_json = json.dumps(
                {
                    "xlabel": "cost (USD)",
                    "ylabel": "MOE",
                    "xticks": [
                        f"{min(p[0] for p in points):.0f}",
                        f"{max(p[0] for p in points):.0f}",
                    ],
                    "yticks": [
                        f"{min(p[1] for p in points):.2f}",
                        f"{max(p[1] for p in points):.2f}",
                    ],
                    "points": [
                        {
                            "x": round(points[j][0], 2),
                            "y": round(points[j][1], 4),
                            # the 4-D truth (the INK) vs this plane's
                            # frontier (the marker shape + the staircase)
                            "front": front[index],
                            "stair": stairs[j],
                            "feasible": shown_eligible[j],
                            "pick": index in pick_set,
                            "label": candidates[index]["label"],
                            "why": whys[j],
                        }
                        for j, index in enumerate(pool)
                    ],
                }
            )
        elif has_cost:  # empty pool: an honest empty scatter, not a stale one
            scatter.payload_json = json.dumps({"points": []})

        line_of = {index: j for j, index in enumerate(pool)}
        lineup.cards_json = json.dumps(
            [
                {
                    "mark": "\u2605 " if rank == 0 else f"{rank + 1} \u00b7 ",
                    "label": candidates[i]["label"],
                    "moe": f"{scores[i]:+.2f}",
                    "cost": f"{candidates[i]['cost']:.0f}" if has_cost else "",
                    "front": front[i],
                    "why": (whys[line_of[i]] or "")
                    if front[i]
                    else "dominated: the Pareto toggle would hide it",
                    "line": line_of[i],
                }
                for rank, i in enumerate(picks)
            ]
        )
        lineup.hover = -1  # cards re-baked: any hover trace is stale

        meshes = [_mesh(i) for i in picks]
        labels = [
            ("\u2605 " if rank == 0 else f"{rank + 1} \u00b7 ")
            + candidates[i]["selection"][shared[0]]
            for rank, i in enumerate(picks)
        ]
        scene = (
            geometry.lineup(meshes, gap=0.35, labels=labels)
            if meshes
            else {"unit": "m", "parts": [], "bounds": [[0, 0, 0], [0, 0, 0]]}
        )
        viewer.mesh_json = json.dumps(scene)
        viewer.label = "  |  ".join(
            ("\u2605 " if rank == 0 else f"{rank + 1}. ")
            + candidates[i]["label"]
            + f"  ({scores[i]:+.2f})"
            for rank, i in enumerate(picks)
        )

        if picks:
            best = picks[0]
            for name in mission_names:
                cards[name].value = _card_html(
                    name,
                    metric_of[name],
                    live[best],
                    _margins(name, live[best]["mission_mix"][name]),
                    specs.get(name, ()),
                    floors.get(name, {}),
                )
            summary.value = _summary_html(live[best], metric_of, mission_names)
            feasible_now = sum(1 for flag in eligible if flag)
            front_now = sum(1 for flag in front if flag)
            ranking.value = (
                '<div style="font-family:Helvetica,Arial,sans-serif; '
                'font-size:12px; color:#2b2d31"><b>best compromise</b> '
                f"&#9733; {candidates[best]['label']}<br>"
                f'<span style="color:#8a8f98">{feasible_now} of '
                f"{len(candidates)} candidates fly &ge; 1 mission at these "
                f"thresholds; {front_now} non-dominated; {len(subset)} in "
                "view. Sliders, brushes, and the Pareto toggle recompute "
                "everything live.</span></div>"
            )
        else:  # honest empty state: say WHY there is nothing to pick
            note = (
                "no candidate flies any mission at these thresholds, so "
                "the Pareto front is empty &mdash; relax the requirement "
                "floors or release the toggle"
                if not pool
                else "the brush excludes every candidate in view &mdash; "
                "move or clear it to get picks back"
            )
            empty = f'<div style="{_CARD_STYLE}; color:#8a8f98">{note}</div>'
            for name in mission_names:
                cards[name].value = empty
            summary.value = empty
            ranking.value = (
                '<div style="font-family:Helvetica,Arial,sans-serif; '
                f'font-size:12px; color:{_BAD}"><b>no picks</b> &mdash; '
                f"{note}</div>"
            )

        if box.selected not in line_of:  # the selection left the visible pool
            box.selected = None
        _apply_selection()

    for slider in weight_sliders.values():
        slider.observe(_recompute, names="value")
    for sliders_by_key in req_sliders.values():
        for slider in sliders_by_key.values():
            slider.observe(_recompute, names="value")
    top_n.observe(_recompute, names="value")
    pareto_toggle.observe(_recompute, names="value")
    pc.observe(_recompute, names="selected")
    pc.observe(_recompute, names="brushes")

    def _trace(_change: Any = None) -> None:
        pc.highlight = int(lineup.hover)

    lineup.observe(_trace, names="hover")

    def _on_card_select(_change: Any = None) -> None:
        if syncing["on"]:
            return
        line = int(lineup.selected)
        _select(box.pool[line] if 0 <= line < len(box.pool) else None)

    def _on_pick(_change: Any = None) -> None:
        keys = json.loads(viewer.picked_json or "[]")
        hit = next((k for k in keys if str(k).startswith("cand:")), None)
        _select(int(hit[5:]) if hit else None)

    lineup.observe(_on_card_select, names="selected")
    viewer.observe(_on_pick, names="picked_json")

    def _section(text: str) -> Any:
        return widgets.HTML(f'<div style="{_SECTION_STYLE}">{text}</div>')

    header = widgets.HBox(
        [
            widgets.HTML(
                '<div style="font-family:Helvetica,Arial,sans-serif">'
                "<b>Mission compromise</b> "
                '<span style="color:#8a8f98; font-size:11px">requirements '
                "re-filter the candidates; priorities re-weight the MOE "
                "(infeasible missions cost "
                f"{INFEASIBLE_PENALTY:g}&times; their weight); brush any "
                "axis to downselect; the toggle hides dominated designs "
                "(min cost, max mission metrics); dominance spans all four "
                "objectives &mdash; the scatter is only a projection, so a "
                "front pick's card and tooltip name the hidden axes it "
                "wins; click a card or a 3D model to select a candidate "
                "across every view</span></div>",
                layout=widgets.Layout(flex="1 1 auto", min_width="0"),
            ),
            pareto_toggle,
            pareto_hint,
            top_n,
        ],
        layout=widgets.Layout(align_items="center", width="100%" if fluid else f"{base_w}px"),
    )
    summary_tab = widgets.VBox(
        [
            ranking,
            _section("mission priorities"),
            *(weight_sliders[n] for n in mission_names),
            summary,
        ]
    )
    mission_tabs = [
        widgets.VBox(
            [
                _section("requirement floors"),
                *req_sliders[name].values(),
                cards[name],
            ]
        )
        for name in mission_names
    ]
    tabs = widgets.Tab(
        children=[summary_tab, *mission_tabs],
        layout=widgets.Layout(width=f"{tab_w}px", height=f"{viewer_h + 34}px", flex="0 0 auto"),
    )
    tabs.set_title(0, "all missions")
    for position, name in enumerate(mission_names, start=1):
        tabs.set_title(position, name)
    row = widgets.Layout(flex_flow="row nowrap", width="100%" if fluid else f"{base_w}px")
    box.children = [
        header,
        widgets.HBox([pc, scatter], layout=row),
        widgets.HBox([tabs, lineup, viewer], layout=row),
    ]
    box.layout = widgets.Layout(width="100%" if fluid else f"{base_w + 8}px")
    box.sliders = weight_sliders
    box.requirements = req_sliders
    box.top_n = top_n
    box.pareto_toggle = pareto_toggle
    box.pareto_hint = pareto_hint
    box.tabs = tabs
    box.parcoords = pc
    box.scatter = scatter
    box.viewer = viewer
    box.cards = cards
    box.summary = summary
    box.lineup = lineup
    box.ranking = ranking
    box.data = data
    box.select = _select
    box._recompute = _recompute
    _recompute()
    return box
