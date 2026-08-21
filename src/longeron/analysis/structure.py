"""Structure views of the analysis problems themselves (anywidgets).

Two interactive diagrams over the *shape* of an analysis, not its
numbers, both following the house widget pattern (Python bakes one JSON
payload; the inline vanilla-JS front-end only paints):

* :func:`n2_view` -- the classic N2 matrix of an OpenMDAO problem built
  by :func:`longeron.analysis.mdao.build_problem`, in the NASA/OpenMDAO
  orientation: components on the diagonal in execution order, a dot
  wherever one component's output feeds another's input.  Each
  connection sits in the SOURCE's row and the TARGET's column, so the
  flow reads clockwise -- out along the source's row, then down the
  column to the receiver -- FEED-FORWARD couplings fill the UPPER
  triangle and FEEDBACK couplings (a source that runs *after* its
  receiver) land in the LOWER triangle, drawn warm and ringed.
  DISCIPLINE blocks -- components grouped by build_problem from the
  model's own package structure -- are outlined and named along the
  diagonal.  Hovering a cell highlights its row and column and lists
  the coupled variables; clicking pins the tooltip.
  (:func:`openmdao_n2` embeds OpenMDAO's own full-strength diagram for
  the deep dive; this widget is the lightweight dependency-free
  in-notebook map.)
* :func:`openmdao_n2` -- the official interactive N2 application
  (``openmdao.api.n2``) generated headlessly and returned inline as a
  sandboxed ``srcdoc`` iframe, so the full tool (solver hierarchy,
  collapsing, search) opens right in the notebook.
* :func:`constraint_network` -- a bipartite view of a
  :class:`~longeron.analysis.trades.TradeStudy`: variation points (the
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

__all__ = [
    "constraint_network",
    "constraint_network_payload",
    "n2_payload",
    "n2_view",
    "openmdao_n2",
]


# ---------------------------------------------------------------------------
# N2: payload
# ---------------------------------------------------------------------------


def n2_payload(problem: Any) -> dict[str, Any]:
    """The baked N2 payload for a built OpenMDAO problem.

    ``problem`` is an ``om.Problem`` or a
    :class:`~longeron.analysis.mdao.ProblemBuild` (its ``.problem`` is
    used).  Components arrive in execution order; every global
    connection becomes a cell ``{row, col, feedback, vars}`` in the
    NASA/OpenMDAO orientation -- ``row`` = the SOURCE component, ``col``
    = the TARGET -- so feed-forward couplings (source runs first) fill
    the upper triangle and the flow reads clockwise: out along the
    source's row, down the target's column.  Feedback (a source that
    runs *after* its receiver) sits below the diagonal.  ``groups``
    records one level of grouping -- contiguous components sharing a
    top-level OpenMDAO group (a SysML discipline package or a nested
    part) as ``{name, start, end}`` index runs, so the view can outline
    the discipline blocks.  The synthetic ``_auto_ivc`` outputs
    (unconnected-input defaults) are skipped -- they are bookkeeping,
    not couplings.
    """

    prob = getattr(problem, "problem", problem)
    try:
        from openmdao.core.component import Component
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "longeron.analysis.structure.n2_payload needs OpenMDAO; install "
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
        key = (index[src_comp], index[tgt_comp])
        cells.setdefault(key, []).append(f"{src_var} \u2192 {tgt_var}")

    def short(path: str) -> str:
        leaf = path.rsplit(".", 1)[-1]
        return leaf.removesuffix("_comp") or leaf

    # one level of grouping: contiguous runs sharing a top-level group
    # (a discipline package or a nested part) become outlined blocks
    groups: list[dict[str, Any]] = []
    for i, path in enumerate(paths):
        name = path.split(".", 1)[0] if "." in path else None
        if (
            name is not None
            and groups
            and groups[-1]["name"] == name
            and groups[-1]["end"] == i - 1
        ):
            groups[-1]["end"] = i
        elif name is not None:
            groups.append({"name": name, "start": i, "end": i})

    return {
        "components": [{"name": short(p), "path": p} for p in paths],
        "groups": groups,
        "cells": [
            {"row": row, "col": col, "feedback": col < row, "vars": names}
            for (row, col), names in sorted(cells.items())
        ],
    }


# Pure N2 interaction math, DOM-free so node can exercise it (the tests
# write these functions plus an export line to a temp .mjs).
_N2_MATH_JS = r"""
// NASA/OpenMDAO orientation: a connection sits in the source's ROW and
// the target's COLUMN (flow reads clockwise: out along the row, down
// the column).  Sources that execute after their receiver (col < row)
// are feedback -- the lower triangle.
const isFeedback = (row, col) => col < row;
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
  el.classList.add("longeron-n2");
  el.innerHTML = "";
  if (!n) return;

  const W = model.get("width_px");
  const M = 24;  // headroom for group labels above the matrix
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
  tip.className = "longeron-n2-tip";
  tip.style.display = "none";
  el.appendChild(tip);
  let pinned = false;

  // row/column highlight bands (drawn first, toggled by hover)
  const bands = P.components.map((c, i) => [
    make("rect", { x: M, y: at(i), width: n * s, height: s,
                   class: "longeron-n2-band" }, svg),
    make("rect", { x: at(i), y: M, width: s, height: n * s,
                   class: "longeron-n2-band" }, svg)]);
  for (let i = 0; i <= n; i++) {  // the lattice
    make("line", { x1: M, y1: M + i * s, x2: M + n * s, y2: M + i * s,
                   class: "longeron-n2-grid" }, svg);
    make("line", { x1: M + i * s, y1: M, x2: M + i * s, y2: M + n * s,
                   class: "longeron-n2-grid" }, svg);
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
                   rx: 4, class: "longeron-n2-diag" }, g);
    const label = make("text", { x: at(i) + s / 2, y: at(i) + s / 2 + 3,
                                 class: "longeron-n2-label" }, g);
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

  // discipline blocks: outline each contiguous group along the diagonal
  // and name it above its first tile (one level of grouping)
  (P.groups || []).forEach((grp) => {
    const x = at(grp.start), size = (grp.end - grp.start + 1) * s;
    make("rect", { x, y: x, width: size, height: size, rx: 6,
                   class: "longeron-n2-group" }, svg);
    const label = make("text", { x: x + 3, y: x - 3,
                                 class: "longeron-n2-group-label" }, svg);
    label.textContent = grp.name;
  });

  P.cells.forEach((cell, k) => {  // the couplings
    const g = make("g", {}, svg);
    if (cell.feedback)
      make("circle", { cx: at(cell.col) + s / 2, cy: at(cell.row) + s / 2,
                       r: s * 0.26, class: "longeron-n2-feedback-ring" }, g);
    make("circle", { cx: at(cell.col) + s / 2, cy: at(cell.row) + s / 2,
                     r: s * 0.15,
                     class: "longeron-n2-dot" + (cell.feedback
                                               ? " feedback" : "") }, g);
    const hit = make("rect", { x: at(cell.col), y: at(cell.row), width: s,
                               height: s, fill: "transparent" }, g);
    const html = () =>
      "<b>" + P.components[cell.row].name + " \u2192 " +
      P.components[cell.col].name + "</b>" +
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
.longeron-n2 { font-family: Helvetica, Arial, sans-serif;
  position: relative; }
.longeron-n2 svg { display: block; width: 100%; height: auto; }
.longeron-n2-grid { stroke: #e7e8ea; stroke-width: 1; }
.longeron-n2-band { fill: transparent; pointer-events: none; }
.longeron-n2-band.on { fill: rgba(47, 107, 143, 0.07); }
.longeron-n2-diag { fill: #eef1f3; stroke: #b9bec5; stroke-width: 1; }
.longeron-n2-group { fill: none; stroke: #2f6b8f; stroke-width: 1.2;
  stroke-dasharray: 5 3; opacity: 0.55; pointer-events: none; }
.longeron-n2-group-label { fill: #2f6b8f; font-size: 9px; font-weight: 600;
  letter-spacing: 0.05em; }
.longeron-n2-label { fill: #2b2d31; font-size: 9.5px; text-anchor: middle; }
.longeron-n2-dot { fill: #2f6b8f; }
.longeron-n2-dot.feedback { fill: #c2603e; }
.longeron-n2-feedback-ring { fill: none; stroke: #c2603e;
  stroke-width: 1; stroke-dasharray: 2 2; }
.longeron-n2-tip { position: absolute; pointer-events: none;
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
  el.classList.add("longeron-connet");
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
  tip.className = "longeron-connet-tip";
  tip.style.display = "none";
  el.appendChild(tip);

  const title = (x, text) => {
    const t = make("text", { x, y: 14, class: "longeron-connet-title" }, svg);
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
      class: "longeron-connet-edge" }, edgeLayer);
  });

  function nodeBox(x, y, cls, text, badge) {
    const g = make("g", {}, nodeLayer);
    make("rect", { x, y: y - 12, width: NODE_W, height: 24, rx: 6,
                   class: cls }, g);
    const label = make("text", { x: x + 9, y: y + 3.5,
                                 class: "longeron-connet-label" }, g);
    label.textContent = text.length > 24 ? text.slice(0, 23) + "\u2026"
                                         : text;
    if (badge) {
      const b = make("text", { x: x + NODE_W - 8, y: y + 3.5,
                               class: "longeron-connet-badge" }, g);
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
      document.querySelectorAll(".longeron-connet .on").forEach(
        (node) => node.classList.remove("on"));
      tip.style.display = "none";
    });
  }

  const varNodes = P.variables.map((v, i) => {
    const g = nodeBox(xL, yAt(i, P.variables.length),
                      "longeron-connet-var", v.name, v.variants + "\u00d7");
    wire(g, 0, i, "<b>" + v.name + "</b><br>" + v.variants + " variants");
    return g;
  });
  const conNodes = P.constraints.map((c, i) => {
    const g = nodeBox(xR, yAt(i, P.constraints.length),
                      "longeron-connet-con" + (c.tinted ? " tinted" : ""),
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
.longeron-connet { font-family: Helvetica, Arial, sans-serif;
  position: relative; }
.longeron-connet svg { display: block; width: 100%; height: auto; }
.longeron-connet-title { fill: #9aa0a8; font-size: 10px;
  letter-spacing: 0.08em; text-transform: uppercase; }
.longeron-connet-edge { fill: none; stroke: #d3d7db; stroke-width: 1;
  transition: stroke 0.12s; }
.longeron-connet-edge.on { stroke: #2f6b8f; stroke-width: 1.6; }
.longeron-connet-var { fill: #eef1f3; stroke: #b9bec5; stroke-width: 1; }
.longeron-connet-con { fill: #f6f4ef; stroke: #c5c0b4; stroke-width: 1; }
.longeron-connet-con.tinted { fill: #f6e4dc; stroke: #c2603e; }
.longeron-connet g.on rect { stroke: #2f6b8f; stroke-width: 1.6; }
.longeron-connet-label { fill: #2b2d31; font-size: 11px; }
.longeron-connet-badge { fill: #9aa0a8; font-size: 10px;
  text-anchor: end; font-variant-numeric: tabular-nums; }
.longeron-connet-tip { position: absolute; pointer-events: none;
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

    NASA/OpenMDAO orientation: diagonal = components in execution
    order; dots = data couplings in the source's row and the target's
    column, so the flow reads clockwise (out along the row, down the
    column) and feed-forward fills the upper triangle; feedback
    couplings sit below the diagonal, warm and dash-ringed.  Discipline
    groups (from the model's package structure, via
    :func:`~longeron.analysis.mdao.build_problem`) are outlined and named
    along the diagonal.  Hover highlights a cell's row and column and
    lists the coupled variables; click pins the tooltip.
    """

    cls = _payload_widget("N2Widget", _N2_ESM, _N2_CSS, "N2 matrix over a baked problem payload.")
    return cls(payload_json=json.dumps(n2_payload(problem)), width_px=width_px)


class _InlineHTML:
    """A minimal display object (``_repr_html_``) for a baked HTML string.

    Serves the same role as ``IPython.display.HTML`` without importing
    IPython (and without its please-use-IFrame warning for srcdoc
    iframes); ``.data`` carries the raw markup, matching the HTML API.
    """

    def __init__(self, data: str):
        self.data = data

    def _repr_html_(self) -> str:
        return self.data


def openmdao_n2(problem: Any, *, height: int = 620) -> _InlineHTML:
    """OpenMDAO's own interactive N2 diagram, embedded inline.

    Generates the official standalone HTML application
    (``openmdao.api.n2`` with ``show_browser=False, embeddable=True``)
    into a temporary file and returns it as an inline ``<iframe
    srcdoc=...>`` display object -- self-contained (no server, no files
    left behind) and sandbox-friendly, which renders reliably in
    JupyterLab.  Use it as the full-strength deep dive (solver
    hierarchy, collapsing, search) next to the lightweight
    :func:`n2_view` map.
    """

    import tempfile
    from pathlib import Path

    prob = getattr(problem, "problem", problem)
    try:
        import openmdao.api as om
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "longeron.analysis.structure.openmdao_n2 needs OpenMDAO; install "
            "the extra with 'pip install \"longeron[mdao]\"'"
        ) from err

    with tempfile.TemporaryDirectory() as tmp:
        outfile = Path(tmp) / "n2.html"
        om.n2(
            prob,
            outfile=str(outfile),
            show_browser=False,
            embeddable=True,
            display_in_notebook=False,
        )
        page = outfile.read_text(encoding="utf-8")
    escaped = page.replace("&", "&amp;").replace('"', "&quot;")
    return _InlineHTML(
        f'<iframe srcdoc="{escaped}" width="100%" height="{height}" '
        'style="border:1px solid #d4d4d4; border-radius:6px; background:#fff" '
        'sandbox="allow-scripts"></iframe>'
    )


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
