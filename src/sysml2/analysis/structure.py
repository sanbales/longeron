"""Structure views of the analysis problems themselves (anywidgets).

Two interactive diagrams over the *shape* of an analysis, not its
numbers, both following the house widget pattern (Python bakes one JSON
payload; the inline vanilla-JS front-end only paints):

* :func:`n2_view` -- the classic N2 matrix of an OpenMDAO problem built
  by :func:`sysml2.analysis.mdao.build_problem`: components on the
  diagonal in execution order, a dot wherever one component's output
  feeds another's input.  The orientation puts each connection in the
  SOURCE's column and the TARGET's row, so feed-forward couplings fall
  below the diagonal and FEEDBACK couplings land above it (drawn warm
  and ringed).  Hovering a cell highlights its row and column and lists
  the coupled variables; clicking pins the tooltip.  (For the
  full-strength deep dive OpenMDAO ships ``om.n2(problem)`` -- a
  standalone HTML app; this widget is the lightweight in-notebook map.)
* :func:`constraint_network` -- a bipartite view of a
  :class:`~sysml2.analysis.trades.TradeStudy`: variation points (the
  decision variables) in one column, ``assert constraint`` bodies in the
  other, an edge wherever a constraint's expression -- transitively,
  through the derived attributes -- touches a point's selection.
  Hovering either side highlights its neighborhood; constraints that
  actually kill candidate mixes (pass ``architectures``) are tinted warm
  with their violation count.

Payload builders (:func:`n2_payload`,
:func:`constraint_network_payload`) are widget-free and unit-tested; the
pure JS interaction math is factored into node-testable snippets.

Requires the ``viz`` extra for the widgets:
``pip install "longeron[viz]"``.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from ._expr import AnalysisError, constraint_expr, free_refs, named_members
from .trades import Architecture, TradeStudy

if TYPE_CHECKING:
    import anywidget

__all__ = ["constraint_network", "constraint_network_payload", "n2_payload", "n2_view"]


# ---------------------------------------------------------------------------
# N2: payload
# ---------------------------------------------------------------------------


def n2_payload(problem: Any) -> dict[str, Any]:
    """The baked N2 payload for a built OpenMDAO problem.

    ``problem`` is an ``om.Problem`` or a
    :class:`~sysml2.analysis.mdao.ProblemBuild` (its ``.problem`` is
    used).  Components arrive in execution order; every global
    connection becomes a cell ``{row, col, feedback, vars}`` with
    ``row`` = the receiving component, ``col`` = the source, so feedback
    (a source that runs *after* its receiver) sits above the diagonal.
    The synthetic ``_auto_ivc`` outputs (unconnected-input defaults) are
    skipped -- they are bookkeeping, not couplings.
    """

    prob = getattr(problem, "problem", problem)
    try:
        from openmdao.core.component import Component
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "sysml2.analysis.structure.n2_payload needs OpenMDAO; install "
            "the extra with 'pip install \"longeron[mdao]\"'"
        ) from err
    prob.final_setup()
    model = prob.model
    paths = [
        system.pathname
        for system in model.system_iter(recurse=True, typ=Component)
        if system.pathname != "_auto_ivc"
    ]
    index = {path: i for i, path in enumerate(paths)}

    cells: dict[tuple[int, int], list[str]] = {}
    for tgt, src in sorted(model._conn_global_abs_in2out.items()):
        src_comp, src_var = src.rsplit(".", 1)
        tgt_comp, tgt_var = tgt.rsplit(".", 1)
        if src_comp not in index or tgt_comp not in index:
            continue  # _auto_ivc or an out-of-scope system
        key = (index[tgt_comp], index[src_comp])
        cells.setdefault(key, []).append(f"{src_var} \u2192 {tgt_var}")

    def short(path: str) -> str:
        leaf = path.rsplit(".", 1)[-1]
        return leaf.removesuffix("_comp") or leaf

    return {
        "components": [{"name": short(p), "path": p} for p in paths],
        "cells": [
            {"row": row, "col": col, "feedback": col > row, "vars": names}
            for (row, col), names in sorted(cells.items())
        ],
    }


# Pure N2 interaction math, DOM-free so node can exercise it (the tests
# write these functions plus an export line to a temp .mjs).
_N2_MATH_JS = r"""
// A connection in the source's COLUMN and the target's ROW: sources that
// execute after their receiver (col > row) are feedback.
const isFeedback = (row, col) => col > row;
// Cells sharing a row or column with cells[i] (its coupling neighborhood).
function related(cells, i) {
  const { row, col } = cells[i];
  const out = [];
  cells.forEach((cell, k) => {
    if (k !== i && (cell.row === row || cell.col === col)) out.push(k);
  });
  return out;
}
"""

_N2_ESM = (
    _N2_MATH_JS
    + r"""
function render({ model, el }) {
  const P = JSON.parse(model.get("payload_json"));
  const n = P.components.length;
  el.classList.add("sysml2-n2");
  el.innerHTML = "";
  if (!n) return;

  const W = model.get("width_px");
  const M = 10;
  const s = Math.max(30, Math.min(72, (W - 2 * M) / n));
  const size = n * s + 2 * M;
  const NS = "http://www.w3.org/2000/svg";
  const make = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    parent.appendChild(node);
    return node;
  };
  const svg = make("svg", { viewBox: `0 0 ${size} ${size}` }, el);
  svg.style.maxWidth = size + "px";
  const at = (i) => M + i * s;

  const tip = document.createElement("div");
  tip.className = "sysml2-n2-tip";
  tip.style.display = "none";
  el.appendChild(tip);
  let pinned = false;

  // row/column highlight bands (drawn first, toggled by hover)
  const bands = P.components.map((c, i) => [
    make("rect", { x: M, y: at(i), width: n * s, height: s,
                   class: "sysml2-n2-band" }, svg),
    make("rect", { x: at(i), y: M, width: s, height: n * s,
                   class: "sysml2-n2-band" }, svg)]);
  for (let i = 0; i <= n; i++) {  // the lattice
    make("line", { x1: M, y1: M + i * s, x2: M + n * s, y2: M + i * s,
                   class: "sysml2-n2-grid" }, svg);
    make("line", { x1: M + i * s, y1: M, x2: M + i * s, y2: M + n * s,
                   class: "sysml2-n2-grid" }, svg);
  }

  function showTip(html, x, y) {
    tip.innerHTML = html;
    tip.style.display = "block";
    const box = el.getBoundingClientRect();
    tip.style.left = Math.min(x - box.left + 14, box.width - 190) + "px";
    tip.style.top = y - box.top + 12 + "px";
  }
  function hideTip() { if (!pinned) tip.style.display = "none"; }
  function highlight(row, col, on) {
    bands[row][0].classList.toggle("on", on);
    bands[col][1].classList.toggle("on", on);
  }

  P.components.forEach((comp, i) => {  // the diagonal
    const g = make("g", {}, svg);
    make("rect", { x: at(i) + 2, y: at(i) + 2, width: s - 4, height: s - 4,
                   rx: 4, class: "sysml2-n2-diag" }, g);
    const label = make("text", { x: at(i) + s / 2, y: at(i) + s / 2 + 3,
                                 class: "sysml2-n2-label" }, g);
    const chars = Math.max(3, Math.floor((s - 8) / 5.4));
    label.textContent = comp.name.length > chars
      ? comp.name.slice(0, chars - 1) + "\u2026" : comp.name;
    g.addEventListener("mouseenter", (e) => {
      highlight(i, i, true);
      showTip("<b>" + comp.name + "</b><br><i>" + comp.path + "</i>",
              e.clientX, e.clientY);
    });
    g.addEventListener("mouseleave", () => { highlight(i, i, false);
                                             hideTip(); });
  });

  P.cells.forEach((cell, k) => {  // the couplings
    const g = make("g", {}, svg);
    if (cell.feedback)
      make("circle", { cx: at(cell.col) + s / 2, cy: at(cell.row) + s / 2,
                       r: s * 0.26, class: "sysml2-n2-feedback-ring" }, g);
    make("circle", { cx: at(cell.col) + s / 2, cy: at(cell.row) + s / 2,
                     r: s * 0.15,
                     class: "sysml2-n2-dot" + (cell.feedback
                                               ? " feedback" : "") }, g);
    const hit = make("rect", { x: at(cell.col), y: at(cell.row), width: s,
                               height: s, fill: "transparent" }, g);
    const html = () =>
      "<b>" + P.components[cell.col].name + " \u2192 " +
      P.components[cell.row].name + "</b>" +
      (cell.feedback ? " <i>(feedback)</i>" : "") + "<br>" +
      cell.vars.join("<br>");
    hit.addEventListener("mouseenter", (e) => {
      highlight(cell.row, cell.col, true);
      if (!pinned) showTip(html(), e.clientX, e.clientY);
    });
    hit.addEventListener("mouseleave", () => {
      highlight(cell.row, cell.col, false);
      hideTip();
    });
    hit.addEventListener("click", (e) => {  // pin / unpin the tooltip
      pinned = !pinned;
      if (pinned) { showTip(html(), e.clientX, e.clientY); }
      else tip.style.display = "none";
      e.stopPropagation();
    });
  });
  svg.addEventListener("click", () => {
    pinned = false;
    tip.style.display = "none";
  });
}
export default { render };
"""
)

_N2_CSS = """
.sysml2-n2 { font-family: Helvetica, Arial, sans-serif;
  position: relative; }
.sysml2-n2 svg { display: block; width: 100%; height: auto; }
.sysml2-n2-grid { stroke: #e7e8ea; stroke-width: 1; }
.sysml2-n2-band { fill: transparent; pointer-events: none; }
.sysml2-n2-band.on { fill: rgba(47, 107, 143, 0.07); }
.sysml2-n2-diag { fill: #eef1f3; stroke: #b9bec5; stroke-width: 1; }
.sysml2-n2-label { fill: #2b2d31; font-size: 9.5px; text-anchor: middle; }
.sysml2-n2-dot { fill: #2f6b8f; }
.sysml2-n2-dot.feedback { fill: #c2603e; }
.sysml2-n2-feedback-ring { fill: none; stroke: #c2603e;
  stroke-width: 1; stroke-dasharray: 2 2; }
.sysml2-n2-tip { position: absolute; pointer-events: none;
  background: #ffffff; border: 1px solid #d4d4d4; border-radius: 6px;
  padding: 6px 9px; font-size: 11px; line-height: 1.5; color: #2b2d31;
  box-shadow: 0 2px 8px rgba(20, 24, 28, 0.12); max-width: 210px; }
"""


# ---------------------------------------------------------------------------
# constraint network: payload
# ---------------------------------------------------------------------------


def constraint_network_payload(
    study: TradeStudy,
    architectures: Sequence[Architecture] | None = None,
) -> dict[str, Any]:
    """The baked bipartite constraint-participation payload.

    ``variables`` are the study's variation points; ``constraints`` its
    ``assert constraint`` bodies; ``edges`` are ``[variable_index,
    constraint_index]`` pairs wherever the body references a point --
    directly or transitively through the derived attributes it names.
    With ``architectures`` (e.g. ``study.all_architectures()``) each
    constraint carries its violation count over that space and is
    ``tinted`` when it actually kills mixes.
    """

    refs_of = {name: {p[0] for p in free_refs(expr)} for name, expr in study.derived_order}

    def touched_points(names: set[str]) -> set[str]:
        seen: set[str] = set()
        queue = list(names)
        points: set[str] = set()
        while queue:
            name = queue.pop()
            if name in seen:
                continue
            seen.add(name)
            if name in study.points:
                points.add(name)
            elif name in refs_of:
                queue.extend(refs_of[name])
        return points

    violations: Counter[str] = Counter()
    for arch in architectures or ():
        violations.update(arch.violations)

    variables = [
        {"name": point.name, "variants": len(point.variants)} for point in study.points.values()
    ]
    v_index = {v["name"]: i for i, v in enumerate(variables)}
    constraints: list[dict[str, Any]] = []
    edges: list[list[int]] = []
    for con in named_members(study.interp, study.assembly, ("constraint",)):
        body = constraint_expr(study.interp, con)
        if body is None:
            continue
        name = con.name or con.label
        count = violations.get(name, 0)
        c_i = len(constraints)
        constraints.append(
            {"name": name, "text": body.to_text(), "violations": count, "tinted": count > 0}
        )
        for point in sorted(touched_points({p[0] for p in free_refs(body)})):
            edges.append([v_index[point], c_i])
    if not constraints:
        raise AnalysisError(f"{study.assembly.label} declares no encodable constraints")
    return {"variables": variables, "constraints": constraints, "edges": edges}


# Pure bipartite adjacency math (node-tested like the N2 helpers).
_NET_MATH_JS = r"""
// The neighborhood of node `index` on `side` (0 = variable, 1 =
// constraint): the incident edge indices and the opposite-side nodes.
function neighborhood(edges, side, index) {
  const es = [];
  const nodes = [];
  edges.forEach((edge, k) => {
    if (edge[side] !== index) return;
    es.push(k);
    if (!nodes.includes(edge[1 - side])) nodes.push(edge[1 - side]);
  });
  return { edges: es, nodes };
}
"""

_NET_ESM = (
    _NET_MATH_JS
    + r"""
function render({ model, el }) {
  const P = JSON.parse(model.get("payload_json"));
  el.classList.add("sysml2-connet");
  el.innerHTML = "";

  const W = model.get("width_px");
  const rows = Math.max(P.variables.length, P.constraints.length);
  const RH = 34;
  const H = rows * RH + 40;
  const NODE_W = 150;
  const xL = 14, xR = W - 14 - NODE_W;
  const NS = "http://www.w3.org/2000/svg";
  const make = (tag, attrs, parent) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    parent.appendChild(node);
    return node;
  };
  const svg = make("svg", { viewBox: `0 0 ${W} ${H}` }, el);
  svg.style.maxWidth = W + "px";
  const edgeLayer = make("g", {}, svg);
  const nodeLayer = make("g", {}, svg);
  const yAt = (i, count) =>
    30 + (i + 0.5) * ((H - 40) / Math.max(count, 1));

  const tip = document.createElement("div");
  tip.className = "sysml2-connet-tip";
  tip.style.display = "none";
  el.appendChild(tip);

  const title = (x, text) => {
    const t = make("text", { x, y: 14, class: "sysml2-connet-title" }, svg);
    t.textContent = text;
  };
  title(xL, "decisions");
  title(xR, "constraints");

  const edgePaths = P.edges.map(([vi, ci]) => {
    const y0 = yAt(vi, P.variables.length);
    const y1 = yAt(ci, P.constraints.length);
    const x0 = xL + NODE_W, x1 = xR;
    const mid = (x0 + x1) / 2;
    return make("path", {
      d: `M${x0},${y0} C${mid},${y0} ${mid},${y1} ${x1},${y1}`,
      class: "sysml2-connet-edge" }, edgeLayer);
  });

  function nodeBox(x, y, cls, text, badge) {
    const g = make("g", {}, nodeLayer);
    make("rect", { x, y: y - 12, width: NODE_W, height: 24, rx: 6,
                   class: cls }, g);
    const label = make("text", { x: x + 9, y: y + 3.5,
                                 class: "sysml2-connet-label" }, g);
    label.textContent = text.length > 24 ? text.slice(0, 23) + "\u2026"
                                         : text;
    if (badge) {
      const b = make("text", { x: x + NODE_W - 8, y: y + 3.5,
                               class: "sysml2-connet-badge" }, g);
      b.textContent = badge;
    }
    return g;
  }

  function wire(g, side, index, html) {
    g.addEventListener("mouseenter", (event) => {
      const hood = neighborhood(P.edges, side, index);
      hood.edges.forEach((k) => edgePaths[k].classList.add("on"));
      g.classList.add("on");
      hood.nodes.forEach((k) =>
        (side ? varNodes[k] : conNodes[k]).classList.add("on"));
      tip.innerHTML = html;
      tip.style.display = "block";
      const box = el.getBoundingClientRect();
      tip.style.left = Math.min(event.clientX - box.left + 14,
                                W - 210) + "px";
      tip.style.top = event.clientY - box.top + 12 + "px";
    });
    g.addEventListener("mouseleave", () => {
      edgePaths.forEach((p) => p.classList.remove("on"));
      document.querySelectorAll(".sysml2-connet .on").forEach(
        (node) => node.classList.remove("on"));
      tip.style.display = "none";
    });
  }

  const varNodes = P.variables.map((v, i) => {
    const g = nodeBox(xL, yAt(i, P.variables.length),
                      "sysml2-connet-var", v.name, v.variants + "\u00d7");
    wire(g, 0, i, "<b>" + v.name + "</b><br>" + v.variants + " variants");
    return g;
  });
  const conNodes = P.constraints.map((c, i) => {
    const g = nodeBox(xR, yAt(i, P.constraints.length),
                      "sysml2-connet-con" + (c.tinted ? " tinted" : ""),
                      c.name, c.tinted ? "\u00d7" + c.violations : "");
    wire(g, 1, i, "<b>" + c.name + "</b>" +
      (c.tinted ? " <i>kills " + c.violations + " mixes</i>" : "") +
      "<br>" + c.text);
    return g;
  });
}
export default { render };
"""
)

_NET_CSS = """
.sysml2-connet { font-family: Helvetica, Arial, sans-serif;
  position: relative; }
.sysml2-connet svg { display: block; width: 100%; height: auto; }
.sysml2-connet-title { fill: #9aa0a8; font-size: 10px;
  letter-spacing: 0.08em; text-transform: uppercase; }
.sysml2-connet-edge { fill: none; stroke: #d3d7db; stroke-width: 1;
  transition: stroke 0.12s; }
.sysml2-connet-edge.on { stroke: #2f6b8f; stroke-width: 1.6; }
.sysml2-connet-var { fill: #eef1f3; stroke: #b9bec5; stroke-width: 1; }
.sysml2-connet-con { fill: #f6f4ef; stroke: #c5c0b4; stroke-width: 1; }
.sysml2-connet-con.tinted { fill: #f6e4dc; stroke: #c2603e; }
.sysml2-connet g.on rect { stroke: #2f6b8f; stroke-width: 1.6; }
.sysml2-connet-label { fill: #2b2d31; font-size: 11px; }
.sysml2-connet-badge { fill: #9aa0a8; font-size: 10px;
  text-anchor: end; font-variant-numeric: tabular-nums; }
.sysml2-connet-tip { position: absolute; pointer-events: none;
  background: #ffffff; border: 1px solid #d4d4d4; border-radius: 6px;
  padding: 6px 9px; font-size: 11px; line-height: 1.5; color: #2b2d31;
  box-shadow: 0 2px 8px rgba(20, 24, 28, 0.12); max-width: 230px; }
"""


# ---------------------------------------------------------------------------
# widget classes (lazy: anywidget is an optional extra)
# ---------------------------------------------------------------------------

_WIDGET_CLS: dict[str, type[anywidget.AnyWidget]] = {}


def _payload_widget(kind: str, esm: str, css: str, doc: str) -> type[anywidget.AnyWidget]:
    if kind in _WIDGET_CLS:
        return _WIDGET_CLS[kind]
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise ImportError(
            "the structure diagrams need anywidget; install the extra "
            "with 'pip install \"longeron[viz]\"'"
        ) from err

    cls = type(
        kind,
        (_anywidget.AnyWidget,),
        {
            "__doc__": doc,
            "_esm": esm,
            "_css": css,
            "payload_json": traitlets.Unicode("").tag(sync=True),
            "width_px": traitlets.Int(640).tag(sync=True),
        },
    )
    _WIDGET_CLS[kind] = cls
    return cls


def n2_view(problem: Any, *, width_px: int = 640) -> anywidget.AnyWidget:
    """An interactive N2 matrix of a built OpenMDAO problem.

    Diagonal = components in execution order; dots = data couplings
    (source column, target row); feedback couplings sit above the
    diagonal, warm and dash-ringed.  Hover highlights a cell's row and
    column and lists the coupled variables; click pins the tooltip.
    """

    cls = _payload_widget("N2Widget", _N2_ESM, _N2_CSS, "N2 matrix over a baked problem payload.")
    return cls(payload_json=json.dumps(n2_payload(problem)), width_px=width_px)


def constraint_network(
    study: TradeStudy, architectures: Sequence[Architecture] | None = None, *, width_px: int = 760
) -> anywidget.AnyWidget:
    """The bipartite decision/constraint participation view of a study.

    Hover a constraint to light up the variation points its expression
    (transitively) touches, and vice versa; constraints that kill mixes
    in ``architectures`` are tinted warm with their violation count.
    """

    cls = _payload_widget(
        "ConstraintNetworkWidget", _NET_ESM, _NET_CSS, "Bipartite constraint-participation network."
    )
    return cls(
        payload_json=json.dumps(constraint_network_payload(study, architectures)), width_px=width_px
    )
