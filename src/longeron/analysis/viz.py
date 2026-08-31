"""Views of trade-study results: figures and a parallel-coordinates widget.

Two kinds of output over the mix tables produced by
:mod:`longeron.analysis.trades`:

* static, publication-styled matplotlib figures --
  :func:`pareto_figure` (the two-objective frontier inside the full
  candidate space; the frontier is computed *from the plotted axes* so a
  many-objective front can never masquerade as a two-objective one) and
  :func:`margin_sweep_figure` (requirement margins across a
  design-variable sweep of an OpenMDAO problem; every stretch where ANY
  margin goes negative is shaded warm and hatched and labeled with the
  constraint(s) binding there -- feasible stretches stay unshaded, the
  absence of shading IS the feasible region);
* an interactive parallel-coordinates anywidget -- :func:`parcoords` --
  following the house widget pattern (:mod:`longeron.widgets.replay`): Python bakes
  the whole payload (axis specs, tick labels, normalized line positions)
  into one JSON-string traitlet, the inline vanilla-JS front-end only
  paints.  Brush gestures live in a narrow zone around each axis (the
  brushes are movable/resizable intervals with end handles); polyline
  hover works everywhere else; the brushed subset syncs back through the
  ``selected`` traitlet.

Requires the ``viz`` extra: ``pip install "longeron[viz]"`` (matplotlib
for the figures, anywidget for the widget; both import lazily).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from ..errors import MissingExtraError
from ._expr import AnalysisError
from .trades import Architecture, TradeStudy, pareto

if TYPE_CHECKING:
    import anywidget

__all__ = ["margin_sweep_figure", "mix_table", "parcoords", "parcoords_payload", "pareto_figure"]

# Shared palette (restrained: one accent, grays for scaffolding).  The
# accent family varies lightness, never hue -- see the categorical /
# single-series guidance the figures follow.
INK = "#2b2d31"
MUTE = "#9aa0a8"
FAINT = "#d9dbdf"
ACCENT = "#2f6b8f"  # petrol blue: frontier / brushed lines
ACCENT_RAMP = ("#2f6b8f", "#5b8dad", "#8fb2c7", "#b7cedd")
WARM = "#c2603e"  # terracotta: the one warm highlight


def _plt() -> Any:
    try:
        import matplotlib.pyplot as plt
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError("longeron.analysis.viz figures", "matplotlib", "viz") from err
    return plt


def _pe() -> Any:
    import matplotlib.patheffects as patheffects  # after _plt() succeeded

    return patheffects


# ---------------------------------------------------------------------------
# mix tables
# ---------------------------------------------------------------------------


def mix_table(
    study: TradeStudy,
    architectures: Sequence[Architecture] | None = None,
    derived: Mapping[str, Callable[[Architecture], Any]] | None = None,
) -> list[dict[str, Any]]:
    """Flat rows (selection + metrics + ``feasible``) for plotting.

    ``derived`` adds computed columns, e.g. ``{"thrustToWeight":
    lambda a: a.metrics["totalThrust"] / (a.metrics["totalMass"] * 9.81)}``.
    Defaults to the full candidate space
    (:meth:`~longeron.analysis.trades.TradeStudy.all_architectures`).
    """

    archs = study.all_architectures() if architectures is None else architectures
    rows: list[dict[str, Any]] = []
    for arch in archs:
        row: dict[str, Any] = dict(arch.selection)
        row.update(arch.metrics)
        for name, fn in (derived or {}).items():
            row[name] = fn(arch)
        row["feasible"] = arch.verified
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# parallel coordinates: payload (pure) + widget (anywidget)
# ---------------------------------------------------------------------------


def _fmt(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 100 or value == int(value):
        return f"{value:.0f}"
    return f"{value:.2f}" if magnitude < 10 else f"{value:.1f}"


def parcoords_payload(
    rows: Sequence[Mapping[str, Any]], axes: Sequence[str] | None = None
) -> dict[str, Any]:
    """The baked parallel-coordinates payload (house pattern: Python owns
    the schema, JS only paints).

    Per axis: a name and tick marks ``{t, label}`` in normalized [0, 1]
    coordinates (1 = top).  Per line: normalized positions ``t`` per axis,
    display strings ``v`` per axis, a hover label, and the feasible flag.
    Categorical axes place categories in first-appearance order; constant
    numeric axes pin to the middle.
    """

    if not rows:
        raise AnalysisError("parcoords needs at least one row")
    names = list(axes) if axes is not None else [k for k in rows[0] if k != "feasible"]
    missing = [n for n in names if n not in rows[0]]
    if missing:
        raise AnalysisError(f"rows have no column(s) {missing!r} (have: {sorted(rows[0])})")

    specs: list[dict[str, Any]] = []
    positions: list[list[float]] = []  # per axis, per row
    displays: list[list[str]] = []
    for name in names:
        values = [row[name] for row in rows]
        if any(isinstance(v, str) for v in values):
            categories = list(dict.fromkeys(str(v) for v in values))
            t_of = {
                c: (i / (len(categories) - 1) if len(categories) > 1 else 0.5)
                for i, c in enumerate(categories)
            }
            specs.append(
                {"name": name, "ticks": [{"t": round(t_of[c], 4), "label": c} for c in categories]}
            )
            positions.append([t_of[str(v)] for v in values])
            displays.append([str(v) for v in values])
        else:
            lo, hi = min(values), max(values)
            span = hi - lo
            specs.append(
                {
                    "name": name,
                    "ticks": [{"t": 0.0, "label": _fmt(lo)}, {"t": 1.0, "label": _fmt(hi)}],
                }
            )
            positions.append([(v - lo) / span if span else 0.5 for v in values])
            displays.append([_fmt(float(v)) for v in values])

    lines = []
    for index, row in enumerate(rows):
        cats = [str(row[n]) for n in names if isinstance(row[n], str)]
        lines.append(
            {
                "label": row.get("label") or " / ".join(cats) or f"mix {index}",
                "t": [round(positions[a][index], 4) for a in range(len(names))],
                "v": [displays[a][index] for a in range(len(names))],
                "feasible": bool(row.get("feasible", True)),
            }
        )
    return {"axes": specs, "lines": lines}


# Pure brush-interval math, kept free of DOM so it can be unit-tested with
# node (tests write these functions plus an export line to a temp .mjs).
# All positions are normalized t in [0, 1] (1 = axis top); a brush is
# [lo, hi] or null; tolerances arrive in t units (px / plot height).
_PC_MATH_JS = r"""
const clamp01 = (t) => Math.min(1, Math.max(0, t));
const interval = (a, b) => (a <= b ? [a, b] : [b, a]);
const inBrush = (brush, t) => !brush || (t >= brush[0] && t <= brush[1]);
// Which part of a brush t touches: "lo"/"hi" within tol of that handle
// (nearest end wins when both are in reach), "body" strictly inside,
// null outside or when there is no brush.
function brushZone(t, brush, tol) {
  if (!brush) return null;
  const [lo, hi] = brush;
  const nearLo = Math.abs(t - lo) <= tol;
  const nearHi = Math.abs(t - hi) <= tol;
  if (nearLo && nearHi) return t < (lo + hi) / 2 ? "lo" : "hi";
  if (nearLo) return "lo";
  if (nearHi) return "hi";
  return t > lo && t < hi ? "body" : null;
}
// Translate a brush by dt, clamped to [0, 1] without changing its width.
function moveInterval(brush, dt) {
  const [lo, hi] = brush;
  const shift = Math.min(1 - hi, Math.max(-lo, dt));
  return [lo + shift, hi + shift];
}
// Drag one end ("lo"/"hi") to t; ends swap when dragged past each other.
function resizeInterval(brush, end, t) {
  const anchor = end === "lo" ? brush[1] : brush[0];
  const moved = clamp01(t);
  return { brush: interval(anchor, moved),
           end: moved <= anchor ? "lo" : "hi" };
}
"""

# Conventions follow longeron.widgets.replay: DOM built once per bake, per-interaction
# work is class toggles + one tooltip move; payload is pre-normalized so the
# JS never sees raw metric values (only t in [0,1] and baked display
# strings).  Interaction separation: brush gestures start ONLY inside a
# +/-12 px zone around each axis (crosshair cursor); the zone rects are
# appended AFTER the fat line-hit twins so they win the pointer there,
# while polyline hover/click owns everywhere else.  Brushes are editable
# intervals: drag the body to move (grab cursor), drag an end handle to
# resize (ns-resize), click the axis outside the brush -- or double-click
# anywhere in the zone -- to clear.  Re-assigning table_json from Python
# re-renders in place; brush intervals persist across re-bakes by AXIS
# NAME (a dashboard re-scoring an axis keeps the user's downselect).
_PC_ESM = (
    _PC_MATH_JS
    + r"""
function render({ model, el }) {
  const saved = {};  // brush intervals by axis name: survive re-bakes

  function draw() {
  const table = JSON.parse(model.get("table_json"));
  const axes = table.axes;
  const lines = table.lines;
  el.classList.add("longeron-parcoords");
  el.innerHTML = "";

  const W = model.get("width_px");
  const H = model.get("height_px");
  const M = { top: 30, right: 56, bottom: 14, left: 56 };
  const plotW = W - M.left - M.right;
  const plotH = H - M.top - M.bottom;
  const xs = axes.map((a, i) => M.left +
    (axes.length > 1 ? (i * plotW) / (axes.length - 1) : plotW / 2));
  const yOf = (t) => M.top + (1 - t) * plotH;

  const NS = "http://www.w3.org/2000/svg";
  const make = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    parent.appendChild(node);
    return node;
  };
  const svg = make("svg", { viewBox: `0 0 ${W} ${H}` }, el);
  svg.style.maxWidth = W + "px";
  const lineLayer = make("g", {}, svg);
  const axisLayer = make("g", {}, svg);
  const brushLayer = make("g", {}, svg);
  const hitLayer = make("g", {}, svg);   // fat polyline twins (hover)
  const zoneLayer = make("g", {}, svg);  // axis brush zones, on top

  // --- tooltip (plain div; the container is position:relative)
  const tip = document.createElement("div");
  tip.className = "longeron-pc-tip";
  tip.style.display = "none";
  el.appendChild(tip);

  // --- one path per mix (built once; only classes toggle afterwards)
  const paths = lines.map((ln) => {
    const d = ln.t.map(
      (t, i) => (i ? "L" : "M") + xs[i] + "," + yOf(t)).join("");
    const path = make("path", { d, class: "longeron-pc-line" }, lineLayer);
    if (!ln.feasible) path.classList.add("infeasible");
    return path;
  });

  // --- axes: line, halo title, baked tick labels
  axes.forEach((axis, i) => {
    make("line", { x1: xs[i], y1: M.top, x2: xs[i], y2: M.top + plotH,
                   class: "longeron-pc-axis" }, axisLayer);
    const title = make("text", { x: xs[i], y: M.top - 12,
                                 class: "longeron-pc-title" }, axisLayer);
    title.textContent = axis.name;
    for (const tick of axis.ticks) {
      make("line", { x1: xs[i] - 3, y1: yOf(tick.t), x2: xs[i] + 3,
                     y2: yOf(tick.t), class: "longeron-pc-axis" }, axisLayer);
      const label = make("text", { x: xs[i] - 6, y: yOf(tick.t) + 3,
                                   class: "longeron-pc-tick" }, axisLayer);
      label.textContent = tick.label;
    }
  });

  // --- brushing: one optional editable [lo, hi] interval per axis,
  // restored by axis name across table_json re-bakes
  const ZONE_PX = 12;    // half-width of the axis gesture zone
  const HANDLE_PX = 6;   // grab tolerance around each brush end
  const CLICK_PX = 3;    // below this a gesture is a click, not a drag
  const brushes = axes.map((a) => saved[a.name] || null);
  const keep = (i) => {
    if (brushes[i]) saved[axes[i].name] = brushes[i];
    else delete saved[axes[i].name];
  };
  const brushRects = axes.map((a, i) =>
    make("rect", { x: xs[i] - 7, width: 14, rx: 3, y: 0, height: 0,
                   class: "longeron-pc-brush", display: "none" },
         brushLayer));
  const brushHandles = axes.map((a, i) => ["lo", "hi"].map(() =>
    make("rect", { x: xs[i] - 7, width: 14, height: 3.5, rx: 1.5, y: 0,
                   class: "longeron-pc-brush-handle", display: "none" },
         brushLayer)));

  function drawBrush(i) {
    const b = brushes[i];
    const parts = [brushRects[i], ...brushHandles[i]];
    if (!b) {
      parts.forEach((p) => p.setAttribute("display", "none"));
      return;
    }
    parts.forEach((p) => p.setAttribute("display", ""));
    brushRects[i].setAttribute("y", yOf(b[1]));
    brushRects[i].setAttribute("height",
      Math.max(1, yOf(b[0]) - yOf(b[1])));
    brushHandles[i][0].setAttribute("y", yOf(b[0]) - 1.75);
    brushHandles[i][1].setAttribute("y", yOf(b[1]) - 1.75);
  }

  function update(sync) {
    const brushing = brushes.some((b) => b !== null);
    const active = [];
    lines.forEach((ln, index) => {
      const pass = brushes.every((b, a) => inBrush(b, ln.t[a]));
      if (pass) active.push(index);
      paths[index].classList.toggle("on", brushing && pass);
      paths[index].classList.toggle("dim", brushing && !pass);
    });
    if (sync) {
      model.set("selected", JSON.stringify(active));
      model.save_changes();
    }
  }

  axes.forEach((axis, i) => {
    const zone = make("rect", { x: xs[i] - ZONE_PX, width: 2 * ZONE_PX,
                                y: M.top - 4, height: plotH + 8,
                                fill: "transparent" }, zoneLayer);
    zone.style.cursor = "crosshair";
    const tol = HANDLE_PX / plotH;
    let drag = null;  // {mode: create|move|resize, t0, start, end, made}
    const tAt = (event) => {
      const box = svg.getBoundingClientRect();
      const y = ((event.clientY - box.top) * H) / box.height;
      return clamp01((M.top + plotH - y) / plotH);
    };
    const idleCursor = (t) => {
      const part = brushZone(t, brushes[i], tol);
      return part === "body" ? "grab"
        : part ? "ns-resize" : "crosshair";
    };
    zone.addEventListener("pointerdown", (event) => {
      const t = tAt(event);
      const part = brushZone(t, brushes[i], tol);
      if (part === "body") {
        drag = { mode: "move", t0: t, start: brushes[i] };
        zone.style.cursor = "grabbing";
      } else if (part) {
        drag = { mode: "resize", end: part };
      } else {
        drag = { mode: "create", t0: t, made: false };
      }
      zone.setPointerCapture(event.pointerId);
    });
    zone.addEventListener("pointermove", (event) => {
      const t = tAt(event);
      if (!drag) {  // idle: cursor announces what a drag would do
        zone.style.cursor = idleCursor(t);
        return;
      }
      if (drag.mode === "create") {
        if (!drag.made && Math.abs(t - drag.t0) * plotH < CLICK_PX) return;
        drag.made = true;
        brushes[i] = interval(drag.t0, t);
      } else if (drag.mode === "move") {
        brushes[i] = moveInterval(drag.start, t - drag.t0);
      } else {
        const r = resizeInterval(brushes[i], drag.end, t);
        brushes[i] = r.brush;
        drag.end = r.end;
      }
      keep(i);
      drawBrush(i);
      update(false);
    });
    zone.addEventListener("pointerup", (event) => {
      if (!drag) return;
      if (drag.mode === "create" && !drag.made) {
        brushes[i] = null;  // click on the axis outside the brush: clear
        keep(i);
        drawBrush(i);
      }
      drag = null;
      zone.style.cursor = idleCursor(tAt(event));
      update(true);
    });
    zone.addEventListener("dblclick", () => {
      brushes[i] = null;  // double-click anywhere in the zone: clear
      keep(i);
      drawBrush(i);
      update(true);
    });
    drawBrush(i);  // restore a saved brush after a re-bake
  });

  // --- hover: fat invisible twin paths for hit area; tooltip follows
  lines.forEach((ln, index) => {
    const hit = make("path", {
      d: paths[index].getAttribute("d"), class: "longeron-pc-hit" }, hitLayer);
    hit.addEventListener("mouseenter", () => {
      paths[index].classList.add("hover");
      tip.innerHTML = "<b>" + ln.label + "</b>" + (ln.feasible ? ""
        : " <i>(infeasible)</i>") + "<br>" +
        axes.map((a, k) => a.name + " = " + ln.v[k]).join("<br>");
      tip.style.display = "block";
    });
    hit.addEventListener("mousemove", (event) => {
      const box = el.getBoundingClientRect();
      tip.style.left = Math.min(event.clientX - box.left + 14,
                                W - 170) + "px";
      tip.style.top = event.clientY - box.top + 12 + "px";
    });
    hit.addEventListener("mouseleave", () => {
      paths[index].classList.remove("hover");
      tip.style.display = "none";
    });
  });

  update(true);
  }

  model.on("change:table_json", draw);
  draw();
}
export default { render };
"""
)

_PC_CSS = """
.longeron-parcoords { font-family: Helvetica, Arial, sans-serif;
  position: relative; }
.longeron-parcoords svg { display: block; width: 100%; height: auto; }
.longeron-pc-line { fill: none; stroke: #8fa6b4; stroke-width: 1;
  opacity: 0.6; transition: stroke 0.12s, opacity 0.12s; }
.longeron-pc-line.infeasible { stroke: #c9ccd2; stroke-dasharray: 3 3;
  opacity: 0.45; }
.longeron-pc-line.on { stroke: #2f6b8f; stroke-width: 1.4; opacity: 0.9; }
.longeron-pc-line.dim { stroke: #d9dbdf; opacity: 0.18; }
.longeron-pc-line.hover { stroke: #20303c; stroke-width: 2; opacity: 1; }
.longeron-pc-hit { fill: none; stroke: transparent; stroke-width: 9; }
.longeron-pc-axis { stroke: #c4c7cc; stroke-width: 1; }
.longeron-pc-title { fill: #2b2d31; font-size: 11px; font-weight: 600;
  text-anchor: middle; paint-order: stroke; stroke: #ffffff;
  stroke-width: 3px; }
.longeron-pc-tick { fill: #6b7078; font-size: 9px; text-anchor: end;
  font-variant-numeric: tabular-nums; paint-order: stroke;
  stroke: #ffffff; stroke-width: 3px; }
.longeron-pc-brush { fill: rgba(47, 107, 143, 0.14); stroke: #2f6b8f;
  stroke-width: 1; }
.longeron-pc-brush-handle { fill: #2f6b8f; stroke: #ffffff;
  stroke-width: 0.5; }
.longeron-pc-tip { position: absolute; pointer-events: none;
  background: #ffffff; border: 1px solid #d4d4d4; border-radius: 6px;
  padding: 6px 9px; font-size: 11px; line-height: 1.5; color: #2b2d31;
  box-shadow: 0 2px 8px rgba(20, 24, 28, 0.12); max-width: 190px;
  font-variant-numeric: tabular-nums; }
"""

_PC_CLS: type[anywidget.AnyWidget] | None = None


def _parcoords_class() -> type[anywidget.AnyWidget]:
    """Define the widget lazily -- anywidget is an optional extra."""

    global _PC_CLS
    if _PC_CLS is not None:
        return _PC_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the parallel-coordinates widget", "anywidget", "viz") from err

    class ParCoordsWidget(_anywidget.AnyWidget):
        """Brushable parallel coordinates over a baked mix table."""

        _esm = _PC_ESM
        _css = _PC_CSS
        table_json = traitlets.Unicode("").tag(sync=True)
        #: JSON list of row indices passing every axis brush (JS -> Python)
        selected = traitlets.Unicode("[]").tag(sync=True)
        width_px = traitlets.Int(920).tag(sync=True)
        height_px = traitlets.Int(380).tag(sync=True)

        def selected_indices(self) -> list[int]:
            return list(json.loads(self.selected or "[]"))

    _PC_CLS = ParCoordsWidget
    return ParCoordsWidget


def parcoords(
    rows: Sequence[Mapping[str, Any]],
    axes: Sequence[str] | None = None,
    *,
    width_px: int = 920,
    height_px: int = 380,
) -> anywidget.AnyWidget:
    """A brushable parallel-coordinates widget over :func:`mix_table` rows.

    Brush gestures live in a narrow zone around each axis (the cursor
    turns to a crosshair there); everywhere else the pointer belongs to
    the polylines (hover for the full mix).  Drag along an axis to brush
    a range -- lines outside any brush fade.  A brush is editable after
    creation: drag its body to move the whole interval (grab cursor),
    drag an end handle to extend/contract that end (ns-resize cursor),
    and click the axis outside the brush -- or double-click anywhere in
    the zone -- to clear it.  The indices of rows passing every brush
    sync back through the ``selected`` traitlet
    (``widget.selected_indices()``).  Re-assigning ``table_json`` re-bakes
    the view in place (brushes survive by axis name), so a dashboard can
    re-score an axis live.
    """

    cls = _parcoords_class()
    payload = parcoords_payload(rows, axes)
    return cls(
        table_json=json.dumps(payload),
        selected=json.dumps(list(range(len(payload["lines"])))),
        width_px=width_px,
        height_px=height_px,
    )


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------


def _style_axes(ax: Any) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTE)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=MUTE, labelsize=8, length=3, width=0.8)
    for label in ax.get_xticklabels() + ax.get_yticklabels():
        label.set_color(INK)
    ax.xaxis.label.set(color=INK, size=9)
    ax.yaxis.label.set(color=INK, size=9)
    ax.set_axisbelow(True)


def pareto_figure(
    architectures: Iterable[Architecture],
    *,
    x: str,
    y: str,
    sense: tuple[str, str] = ("min", "min"),
    panel_y: str | None = None,
    xlabel: str | None = None,
    ylabel: str | None = None,
    panel_ylabel: str | None = None,
    annotate: Mapping[str, Architecture] | None = None,
    title: str | None = None,
) -> Any:
    """The two-objective Pareto frontier inside the full candidate space.

    ``architectures`` is every evaluated mix (feasible or not, e.g. from
    :meth:`~longeron.analysis.trades.TradeStudy.all_architectures`).  The
    highlighted frontier is computed *here*, from the plotted axes
    themselves: the feasible mixes that are non-dominated under
    ``sense`` -- an explicit ``(x_sense, y_sense)`` pair, each ``"min"``
    or ``"max"``.  The default is the conservative ``("min", "min")``;
    a chart whose y metric is better *large* (station time, payload
    range, catchable target speed, ...) must say so explicitly with
    ``sense=("min", "max")`` -- there is deliberately no silent
    maximize default, because a front computed with the wrong sense
    hugs the wrong corner and leaves genuinely better mixes drawn as
    dominated dots outside the drawn staircase.

    A caller-supplied front is likewise not accepted -- a front computed
    over more objectives than the two plotted axes is only a projection,
    and a projection puts points on the drawn "frontier" that are
    strictly worse on *both* plotted metrics (they earn their Pareto
    rank through an unplotted objective).  Track such extra objectives
    with ``panel_y`` -- a small-multiple panel over the same x axis --
    and call-outs via ``annotate`` instead.

    Dominated mixes are muted dots, infeasible ones pale crosses --
    infeasible mixes *can* land outside the frontier (their metrics are
    what the mix would score if it could fly; the constraints it breaks
    are exactly why the front does not reach them).  The frontier is
    the accent + a step line oriented by ``sense`` so the staircase
    always bounds the attainable side (when it has more than one
    point); give ``title`` as a finding ("The $118 cruiser dominates the
    cost-endurance trade"), not a caption.
    """

    plt = _plt()
    x_sense, y_sense = sense
    if x_sense not in ("min", "max") or y_sense not in ("min", "max"):
        raise AnalysisError(f"sense must pair 'min'/'max' (got {sense!r})")
    archs = list(architectures)
    feasible = [a for a in archs if a.verified]
    senses = ((x, x_sense), (y, y_sense))
    front = pareto(
        feasible,
        minimize=tuple(m for m, s in senses if s == "min"),
        maximize=tuple(m for m, s in senses if s == "max"),
    )
    front_keys = {tuple(sorted(a.selection.items())) for a in front}
    groups: dict[str, list[Architecture]] = {"front": [], "dominated": [], "infeasible": []}
    for arch in archs:
        key = tuple(sorted(arch.selection.items()))
        groups[
            "front" if key in front_keys else "dominated" if arch.verified else "infeasible"
        ].append(arch)

    if panel_y is not None:
        fig, (ax, panel) = plt.subplots(
            2, 1, figsize=(7.0, 5.4), sharex=True, height_ratios=(3.0, 1.25), layout="constrained"
        )
    else:
        fig, ax = plt.subplots(figsize=(7.0, 4.2), layout="constrained")
        panel = None

    def scatter(target: Any, metric_y: str, labeled: bool) -> None:
        styles: dict[str, dict[str, Any]] = {
            "infeasible": {
                "marker": "x",
                "c": FAINT,
                "s": 18,
                "linewidths": 1.0,
                "label": "infeasible (excluded from front)" if labeled else None,
            },
            "dominated": {
                "marker": "o",
                "c": "#c3c7cd",
                "s": 24,
                "label": "feasible, dominated" if labeled else None,
            },
            "front": {
                "marker": "o",
                "c": ACCENT,
                "s": 46,
                "edgecolors": "white",
                "linewidths": 0.7,
                "zorder": 4,
                "label": "Pareto frontier" if labeled else None,
            },
        }
        for name, archs in groups.items():
            if archs:
                target.scatter(
                    [a.metrics[x] for a in archs],
                    [a.metrics[metric_y] for a in archs],
                    **styles[name],
                )

    scatter(ax, y, labeled=True)
    steps = sorted(groups["front"], key=lambda a: a.metrics[x])
    if len(steps) > 1:
        # the staircase must bound the attainable side: with x minimized
        # the best-so-far y holds until the next (costlier) point is
        # bought (steps-post); with x maximized the mirror image.
        ax.plot(
            [a.metrics[x] for a in steps],
            [a.metrics[y] for a in steps],
            drawstyle="steps-post" if x_sense == "min" else "steps-pre",
            color=ACCENT,
            linewidth=1.4,
            alpha=0.85,
            zorder=3,
        )

    x_mid = (
        (
            min(a.metrics[x] for a in groups["front"] or steps or [])
            + max(a.metrics[x] for a in groups["front"])
        )
        / 2
        if groups["front"]
        else 0.0
    )
    for name, arch in (annotate or {}).items():
        left = arch.metrics[x] <= x_mid
        ax.annotate(
            name,
            (arch.metrics[x], arch.metrics[y]),
            xytext=(14 if left else -14, -18),
            textcoords="offset points",
            ha="left" if left else "right",
            fontsize=8.5,
            color=INK,
            arrowprops={
                "arrowstyle": "-",
                "connectionstyle": "arc3,rad=-0.2",
                "color": MUTE,
                "linewidth": 0.8,
            },
        )

    ax.grid(axis="y", color=FAINT, linewidth=0.5)
    ax.set_ylabel(ylabel or y)
    if title:
        ax.set_title(title, fontsize=10, color=INK, loc="left")
    ax.legend(frameon=False, fontsize=8, loc="best", labelcolor=INK, handletextpad=0.4)
    _style_axes(ax)

    if panel is not None:
        scatter(panel, panel_y, labeled=False)  # type: ignore[arg-type]
        panel.grid(axis="y", color=FAINT, linewidth=0.5)
        panel.set_ylabel(panel_ylabel or panel_y)
        panel.set_xlabel(xlabel or x)
        _style_axes(panel)
    else:
        ax.set_xlabel(xlabel or x)
    return fig


def _sweep_bands(
    values: Sequence[float], curves: Mapping[str, Sequence[float]]
) -> list[dict[str, Any]]:
    """The INFEASIBLE bands of a margin sweep (pure, unit-tested).

    The union over ALL margin curves: every constraint whose margin dips
    below zero anywhere in the sweep contributes an interval (edges at
    linearly interpolated zero crossings, ``margin >= 0`` counts as
    holding), and the union is split wherever the set of violated
    constraints changes.  Each band is ``{x0, x1, binding}`` with
    ``binding`` the list of constraints violated throughout that band
    (several where intervals overlap), in ``curves`` order.  Feasible
    stretches produce NO band -- a view shades only the no-go regions.
    """

    if not curves:
        raise AnalysisError("margin bands need at least one margin curve")

    def negative_intervals(ys: Sequence[float]) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        start: float | None = None
        for i, y in enumerate(ys):
            if y < 0 and start is None:
                if i == 0:
                    start = float(values[0])
                else:  # interpolate the entry crossing
                    frac = ys[i - 1] / (ys[i - 1] - y)
                    start = float(values[i - 1]) + frac * float(values[i] - values[i - 1])
            elif y >= 0 and start is not None:  # interpolate the exit
                frac = ys[i - 1] / (ys[i - 1] - y)
                out.append((start, float(values[i - 1]) + frac * float(values[i] - values[i - 1])))
                start = None
        if start is not None:
            out.append((start, float(values[-1])))
        return out

    intervals = {
        name: segs for name, ys in curves.items() if (segs := negative_intervals(list(ys)))
    }
    edges = sorted({edge for segs in intervals.values() for seg in segs for edge in seg})
    bands: list[dict[str, Any]] = []
    for x0, x1 in pairwise(edges):
        mid = (x0 + x1) / 2
        binding = [
            name
            for name in curves
            if name in intervals and any(a <= mid <= b for a, b in intervals[name])
        ]
        if not binding:
            continue  # a feasible gap between violations
        if bands and bands[-1]["x1"] == x0 and bands[-1]["binding"] == binding:
            bands[-1]["x1"] = x1
        else:
            bands.append({"x0": x0, "x1": x1, "binding": binding})
    return bands


def margin_sweep_figure(
    problem: Any,
    var: str,
    values: Sequence[float],
    margins: Mapping[str, str] | Sequence[str],
    *,
    xlabel: str | None = None,
    title: str | None = None,
) -> Any:
    """Requirement margins across a design-variable sweep.

    One chart answering "where can ``var`` go, and which requirement
    stops it": re-runs ``problem`` (an OpenMDAO ``Problem``, duck-typed:
    ``set_val``/``run_model``/``get_val``) for each entry of ``values``,
    plotting every margin output (>= 0 iff the constraint holds, per
    :mod:`longeron.analysis.mdao`) with direct end labels.  Only the
    INFEASIBLE stretches are shaded (:func:`_sweep_bands`): wherever ANY
    margin goes negative the band is tinted warm and hatched, labeled
    with every constraint binding there (stacked when several overlap),
    and its boundaries are marked -- the union over all constraints, so
    a floor broken at the slow end, a ceiling broken at the fast end,
    and a requirement lost in the middle all show up with their own
    names.  Feasible stretches stay unshaded: the clear axis IS the
    go region.  Restores the original value afterwards.  Give ``title``
    as the finding the chart shows ("Payloads above 0.46 kg cannot
    fly").
    """

    named = dict(margins) if isinstance(margins, Mapping) else {m: m for m in margins}
    if not named:
        raise AnalysisError("margin_sweep_figure needs at least one margin")
    baseline = float(problem.get_val(var)[0])
    curves: dict[str, list[float]] = {label: [] for label in named}
    for value in values:
        problem.set_val(var, value)
        problem.run_model()
        for label, output in named.items():
            curves[label].append(float(problem.get_val(output)[0]))
    problem.set_val(var, baseline)
    problem.run_model()

    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.0, 3.6), layout="constrained")
    span = values[-1] - values[0]
    colors = dict(zip(curves, ACCENT_RAMP * (1 + len(named) // 4), strict=False))
    for label, ys in curves.items():
        ax.plot(values, ys, color=colors[label], linewidth=1.6)
    # direct end labels, pushed apart where curves converge
    y_all = [y for ys in curves.values() for y in ys]
    min_gap = 0.06 * ((max(y_all) - min(y_all)) or 1.0)
    slot = None
    for final, label in sorted((ys[-1], label) for label, ys in curves.items()):
        slot = final if slot is None else max(final, slot + min_gap)
        ax.annotate(
            label.split("::")[-1].removesuffix("_margin"),
            (values[-1], slot),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            fontsize=8,
            color=colors[label],
        )
    ax.axhline(0.0, color=MUTE, linewidth=0.9, linestyle=(0, (4, 3)))

    def shorten(label: str) -> str:
        return label.split("::")[-1].removesuffix("_margin")

    halo = [_pe().withStroke(linewidth=2.5, foreground="white")]
    bands = _sweep_bands(values, curves)
    for band in bands:
        x0, x1 = band["x0"], band["x1"]
        ax.axvspan(x0, x1, facecolor=WARM, alpha=0.07, linewidth=0)
        ax.axvspan(x0, x1, facecolor="none", edgecolor=WARM, alpha=0.30, hatch="//", linewidth=0)
        for edge in (x0, x1):  # mark interior no-go boundaries
            if values[0] < edge < values[-1]:
                ax.axvline(edge, color=WARM, linewidth=1.0)
        if x1 - x0 > 0.03 * span:  # skip labels in slivers
            caption = "\n".join(["infeasible:", *(shorten(b) for b in band["binding"])])
            ax.text(
                (x0 + x1) / 2,
                0.04,
                caption,
                transform=ax.get_xaxis_transform(),
                ha="center",
                va="bottom",
                fontsize=8,
                color=WARM,
                path_effects=halo,
            )

    ax.set_xlim(values[0], values[-1] + 0.22 * span)
    ax.set_xlabel(xlabel or var)
    ax.set_ylabel("margin (>= 0 holds)")
    if title:
        ax.set_title(title, fontsize=10, color=INK, loc="left")
    ax.grid(axis="y", color=FAINT, linewidth=0.5)
    _style_axes(ax)
    return fig
