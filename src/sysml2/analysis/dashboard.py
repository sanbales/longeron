"""The mission-compromise dashboard: linked widgets over the trades.

One :func:`mission_dashboard` call composes the existing house widgets
(:func:`sysml2.analysis.viz.parcoords`,
:func:`sysml2.analysis.viewer3d.mesh_viewer`) with plain ipywidgets into a
single live view of the multi-mission trade:

* a priority panel -- one 0-100 weight slider per mission;
* per-mission requirement cards -- each mission's ``assert constraint``
  thresholds with the current best compromise's numeric margin against
  every one (green holds / red broken, via
  :meth:`~sysml2.analysis.trades.TradeStudy.margins`);
* the parallel-coordinates widget over the cross-mission metrics --
  brushing an axis downselects the candidate pool;
* the 3D viewer showing up to four selected configurations side by side
  at true scale (the best compromise leads, starred, followed by up to
  three brushed alternates), rebaked in place through ``mesh_json``.

All linking runs in Python via traitlets observers (slider ``value``,
parcoords ``selected``) -- the candidate table is a hundred-odd rows, so
the front-ends stay dumb painters per the house widget pattern.

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

Requires the ``viz`` extra (anywidget + ipywidgets arrive with it):
``pip install "longeron[viz]"``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from itertools import product
from typing import Any

from .. import model as M
from ._expr import AnalysisError
from .trades import Architecture, TradeStudy

__all__ = ["INFEASIBLE_PENALTY", "compromise_scores", "mission_dashboard",
           "mission_dashboard_data"]

#: score deducted (times the mission's weight) when a candidate cannot
#: fly a mission at all -- documented in the module docstring
INFEASIBLE_PENALTY = 0.5

#: the ``examples/uav_missions.sysml`` trio: name -> (assembly, metric)
DEFAULT_MISSIONS: dict[str, tuple[str, str]] = {
    "ISR": ("UavMissions::IsrUav", "stationMinutes"),
    "logistics": ("UavMissions::LogisticsUav", "payloadRangeKgKm"),
    "intercept": ("UavMissions::InterceptUav", "maxTargetSpeed"),
}


def _ipywidgets() -> Any:
    try:
        import ipywidgets
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "the mission dashboard needs ipywidgets (it arrives with "
            "anywidget); install the extra with "
            "'pip install \"longeron[viz]\"'") from err
    return ipywidgets


# ---------------------------------------------------------------------------
# data preparation (interpreter-exact, widget-free)
# ---------------------------------------------------------------------------


def mission_dashboard_data(model: M.Model,
                           missions: Mapping[str, tuple[str, str]]
                           | None = None) -> dict[str, Any]:
    """Bake the dashboard's candidate table from a multi-mission model.

    Candidates are the Cartesian product of the variation points SHARED
    by every mission study (for the UAV example: airframe, motors,
    props, battery).  Per candidate and mission, the study walks the
    remaining equipment points and keeps the best feasible full mix by
    the mission's primary metric (the best infeasible one when nothing
    flies, so the requirement cards can show *why* in red); the
    displayed metric is 0.0 for missions the candidate cannot fly.
    ``cost`` is the shared ``baseCost`` build-up when the model derives
    one.  The returned dict carries the studies themselves so the
    dashboard can compute margins lazily.
    """

    named = dict(missions or DEFAULT_MISSIONS)
    if not named:
        raise AnalysisError("mission_dashboard_data needs missions")
    studies = {name: TradeStudy(model, qname)
               for name, (qname, _) in named.items()}
    metric_of = {name: metric for name, (_, metric) in named.items()}
    first = next(iter(studies.values()))
    shared = [p for p in first.points
              if all(p in s.points for s in studies.values())]
    if not shared:
        raise AnalysisError("the mission studies share no variation points")

    candidates: list[dict[str, Any]] = []
    for combo in product(*(first.points[p].variants for p in shared)):
        selection = dict(zip(shared, combo, strict=True))
        cand: dict[str, Any] = {
            "selection": selection, "label": "/".join(combo),
            "metric": {}, "feasible": {}, "mission_mix": {}, "cost": None}
        for name, study in studies.items():
            extras = [p for p in study.points if p not in shared]
            best: Architecture | None = None
            best_any: Architecture | None = None
            for extra in product(*(study.points[p].variants
                                   for p in extras)):
                arch = study.evaluate(
                    {**selection, **dict(zip(extras, extra, strict=True))})
                value = arch.metrics[metric_of[name]]
                if best_any is None or value > best_any.metrics[
                        metric_of[name]]:
                    best_any = arch
                if arch.verified and (best is None or value >
                                      best.metrics[metric_of[name]]):
                    best = arch
            chosen = best if best is not None else best_any
            assert chosen is not None
            cand["feasible"][name] = best is not None
            cand["metric"][name] = (chosen.metrics[metric_of[name]]
                                    if best is not None else 0.0)
            cand["mission_mix"][name] = chosen.selection
            if cand["cost"] is None:
                cand["cost"] = chosen.metrics.get("baseCost")
        candidates.append(cand)
    return {"missions": [{"name": name, "metric": metric_of[name]}
                         for name in named],
            "shared": shared, "studies": studies, "candidates": candidates}


# ---------------------------------------------------------------------------
# compromise scoring (pure)
# ---------------------------------------------------------------------------


def compromise_scores(candidates: Sequence[Mapping[str, Any]],
                      weights: Mapping[str, float], *,
                      penalty: float = INFEASIBLE_PENALTY) -> list[float]:
    """Weighted-compromise scores, aligned with ``candidates``.

    Each candidate mapping needs ``metric`` and ``feasible`` sub-mappings
    keyed by the mission names in ``weights``.  Normalization bounds come
    from the *feasible* candidates per mission (a constant or empty
    feasible set normalizes to 1.0 for whoever is feasible); see the
    module docstring for the full scoring contract.
    """

    if not weights:
        raise AnalysisError("compromise_scores needs at least one mission")
    total = float(sum(weights.values()))
    share = {m: (float(w) / total if total else 1.0 / len(weights))
             for m, w in weights.items()}
    bounds: dict[str, tuple[float, float]] = {}
    for mission in weights:
        values = [float(c["metric"][mission]) for c in candidates
                  if c["feasible"][mission]]
        bounds[mission] = (min(values), max(values)) if values else (0.0, 0.0)

    scores: list[float] = []
    for cand in candidates:
        score = 0.0
        for mission, w in share.items():
            if not cand["feasible"][mission]:
                score -= w * penalty
                continue
            lo, hi = bounds[mission]
            norm = ((float(cand["metric"][mission]) - lo) / (hi - lo)
                    if hi > lo else 1.0)
            score += w * norm
        scores.append(score)
    return scores


# ---------------------------------------------------------------------------
# the dashboard composition
# ---------------------------------------------------------------------------

_OK = "#3a7d44"
_BAD = "#b54a35"

_CARD_STYLE = ("border:1px solid #e2e2e2; border-radius:8px; "
               "padding:8px 12px; margin:0 4px; background:#fcfcfb; "
               "font-family:Helvetica,Arial,sans-serif; font-size:12px; "
               "min-width:230px")


def _card_html(mission: str, metric: str, cand: Mapping[str, Any],
               margins: Mapping[str, Mapping[str, Any]]) -> str:
    feasible = cand["feasible"][mission]
    badge = (f'<span style="color:{_OK}">feasible</span>' if feasible else
             f'<span style="color:{_BAD}">infeasible</span>')
    value = cand["metric"][mission]
    rows = []
    for name, entry in margins.items():
        color = _OK if entry["ok"] else _BAD
        shown = ("&#10003;" if entry["ok"] else "&#10007;") if \
            entry["margin"] is None else f"{entry['margin']:+.2f}"
        rows.append(
            f'<tr><td style="padding-right:8px">{name}</td>'
            f'<td style="color:#8a8f98">{entry["text"]}</td>'
            f'<td style="text-align:right; color:{color}; '
            f'font-variant-numeric:tabular-nums"><b>{shown}</b></td></tr>')
    return (f'<div style="{_CARD_STYLE}">'
            f'<b>{mission}</b> &mdash; {metric} '
            f'<span style="font-variant-numeric:tabular-nums">'
            f'{value:.1f}</span> &nbsp;{badge}'
            f'<table style="margin-top:4px; border-spacing:0; '
            f'font-size:11px">{"".join(rows)}</table></div>')


def mission_dashboard(source: M.Model | Mapping[str, Any], *,
                      missions: Mapping[str, tuple[str, str]] | None = None,
                      width_px: int = 920) -> Any:
    """The linked mission-compromise dashboard (an ipywidgets ``VBox``).

    ``source`` is either a loaded model (the candidate table is baked
    via :func:`mission_dashboard_data`, a few seconds of interpreter
    time) or an already-prepared data dict from that function.  The
    returned layout exposes its pieces for scripting and tests:
    ``.sliders`` (mission -> IntSlider), ``.parcoords``, ``.viewer``,
    ``.cards``, ``.data``, ``.picks`` (the current top-4 candidate
    indices into ``data["candidates"]``), and ``.scores`` (the current
    subset's scores).
    """

    from . import geometry, viewer3d, viz  # local: keeps import cheap

    widgets = _ipywidgets()
    data = (dict(source) if isinstance(source, Mapping)
            else mission_dashboard_data(source, missions))
    mission_names = [m["name"] for m in data["missions"]]
    metric_of = {m["name"]: m["metric"] for m in data["missions"]}
    candidates = data["candidates"]
    studies = data["studies"]
    shared = data["shared"]

    rows = []
    for cand in candidates:
        row: dict[str, Any] = dict(cand["selection"])
        if cand["cost"] is not None:
            row["cost"] = cand["cost"]
        for name in mission_names:
            row[metric_of[name]] = cand["metric"][name]
        row["feasible"] = any(cand["feasible"].values())
        rows.append(row)
    axes = [*shared, *(["cost"] if candidates and candidates[0]["cost"]
                       is not None else []),
            *(metric_of[n] for n in mission_names)]
    pc = viz.parcoords(rows, axes=axes, width_px=width_px)

    sliders = {name: widgets.IntSlider(
        value=50, min=0, max=100, description=name,
        continuous_update=False, style={"description_width": "72px"},
        layout=widgets.Layout(width="260px")) for name in mission_names}
    cards = {name: widgets.HTML() for name in mission_names}
    ranking = widgets.HTML()
    viewer = viewer3d.mesh_viewer(
        {"unit": "m", "parts": [], "bounds": [[0, 0, 0], [0, 0, 0]]},
        width_px=width_px, height_px=int(width_px * 0.45))

    geo_study = studies[mission_names[0]]
    mesh_cache: dict[int, dict[str, Any]] = {}

    def _mesh(index: int) -> dict[str, Any]:
        if index not in mesh_cache:
            arch = Architecture(selection=dict(
                candidates[index]["selection"]), metrics={})
            mesh_cache[index] = geometry.mission_geometry(geo_study, arch)
        return mesh_cache[index]

    margin_cache: dict[tuple[str, int], dict[str, Any]] = {}

    def _margins(mission: str, index: int) -> dict[str, Any]:
        key = (mission, index)
        if key not in margin_cache:
            margin_cache[key] = studies[mission].margins(
                candidates[index]["mission_mix"][mission])
        return margin_cache[key]

    box = widgets.VBox()

    def _recompute(_change: Any = None) -> None:
        subset = pc.selected_indices() or list(range(len(candidates)))
        weights = {name: float(sliders[name].value)
                   for name in mission_names}
        scores = compromise_scores([candidates[i] for i in subset], weights)
        order = sorted(range(len(subset)), key=lambda k: -scores[k])[:4]
        picks = [subset[k] for k in order]
        box.picks = picks
        box.scores = scores

        meshes = [_mesh(i) for i in picks]
        gap = 0.35
        scene = (geometry.lineup(meshes, gap=gap,
                                 labels=[str(r + 1) for r in
                                         range(len(picks))])
                 if meshes else {"unit": "m", "parts": [],
                                 "bounds": [[0, 0, 0], [0, 0, 0]]})
        viewer.mesh_json = json.dumps(scene)
        viewer.label = "  |  ".join(
            ("\u2605 " if rank == 0 else f"{rank + 1}. ")
            + candidates[i]["label"]
            + f"  ({scores[order[rank]]:+.2f})"
            for rank, i in enumerate(picks))

        if picks:
            best = picks[0]
            for name in mission_names:
                cards[name].value = _card_html(
                    name, metric_of[name], candidates[best],
                    _margins(name, best))
            ranking.value = (
                '<div style="font-family:Helvetica,Arial,sans-serif; '
                'font-size:12px; color:#2b2d31"><b>best compromise</b> '
                f'&#9733; {candidates[best]["label"]}<br>'
                f'<span style="color:#8a8f98">{len(subset)} candidate(s) '
                'in the brushed pool; scores recompute live on sliders '
                'and brushes</span></div>')

    for slider in sliders.values():
        slider.observe(_recompute, names="value")
    pc.observe(_recompute, names="selected")

    header = widgets.HTML(
        '<div style="font-family:Helvetica,Arial,sans-serif">'
        "<b>Mission priorities</b> "
        '<span style="color:#8a8f98; font-size:11px">weight = how much '
        "each mission's best-normalized metric counts; infeasible "
        f"missions cost {INFEASIBLE_PENALTY:g}&times; their weight"
        "</span></div>")
    box.children = [
        header,
        widgets.HBox([widgets.VBox(list(sliders.values())), ranking]),
        widgets.HBox(list(cards.values())),
        pc, viewer]
    box.sliders = sliders
    box.parcoords = pc
    box.viewer = viewer
    box.cards = cards
    box.data = data
    box._recompute = _recompute
    _recompute()
    return box
