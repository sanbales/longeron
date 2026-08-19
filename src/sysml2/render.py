"""Headless rendering of SysML diagrams to SVG/PNG.

The interactive widgets (:mod:`sysml2.diagrams`) lay themselves out in the
browser.  This module runs the same layout engine -- elkjs 0.9.3, vendored
as ``_js/elk.bundled.js`` (EPL-2.0) -- in a node subprocess instead, then
draws the result as styled SVG:

    from sysml2 import diagrams, render

    render.to_svg(diagrams.state_diagram(machine), "machine.svg")
    render.to_png(model, "model.png")            # builds a view automatically

PNG conversion uses cairosvg when available (``pixi`` environments include
it).  Label sizes are estimated (the browser pipeline measures real glyphs),
so proportions differ slightly from the live widget.
"""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import model as M
from .errors import SysMLError

_ELK_JS = Path(__file__).parent / "_js" / "elk.bundled.js"

_NODE_SCRIPT = """
const ELK = require(process.argv[2]);
const fs = require('fs');
const graph = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
new ELK().layout(graph).then(
    (g) => fs.writeFileSync(process.argv[4], JSON.stringify(g)),
    (err) => { console.error(String(err)); process.exit(1); });
"""

#: cssClasses fragment -> SVG attributes (mirrors diagrams.SYSML_STYLE)
_NODE_STYLES: dict[str, dict[str, str]] = {
    "sysml-package": {"fill": "#fbfbfb", "stroke": "#b0b0b0", "rx": "0"},
    "sysml-definition": {"fill": "#eef4fb", "stroke": "#4878a8", "rx": "4"},
    "sysml-usage": {"fill": "#f4faee", "stroke": "#6a9a48", "rx": "4"},
    "sysml-state": {"fill": "#fdf6e3", "stroke": "#b58900", "rx": "12"},
    "sysml-step": {"fill": "#f2eefb", "stroke": "#6c56a8", "rx": "6"},
    "sysml-marker": {"fill": "#333333", "stroke": "#333333", "rx": "7"},
}

_EDGE_STYLES: dict[str, dict[str, str]] = {
    "sysml-edge-specializes": {"stroke": "#4878a8"},
    "sysml-edge-typed": {"stroke": "#6a9a48", "stroke-dasharray": "4 2"},
    "sysml-edge-connect": {"stroke": "#555555"},
    "sysml-edge-transition": {"stroke": "#b58900"},
    "sysml-edge-succession": {"stroke": "#6c56a8"},
}

_LABEL_STYLES: dict[str, dict[str, str]] = {
    "sysml-stereotype": {"font-size": "9", "fill": "#888888",
                         "font-style": "italic"},
    "sysml-attribute": {"font-size": "10", "fill": "#444444"},
}

_CHAR_WIDTH = {9: 5.2, 10: 5.8, 11: 6.4}


def _font_size(css: str) -> int:
    for name, style in _LABEL_STYLES.items():
        if name in css:
            return int(style["font-size"])
    return 11


def _measure(text: str, css: str = "") -> tuple[float, float]:
    size = _font_size(css)
    return max(10.0, len(text) * _CHAR_WIDTH[size] + 8), size + 5


# ---------------------------------------------------------------------------
# ipyelk elements -> plain ELK JSON
# ---------------------------------------------------------------------------


def _to_elk_json(root: Any) -> dict:
    counter = itertools.count()
    generated: dict[int, str] = {}

    def node_id(node: Any) -> str:
        if node.id:
            return str(node.id)
        return generated.setdefault(id(node), f"_n{next(counter)}")

    def convert_edge_labels(edge: Any, owner: str) -> list[dict]:
        labels = []
        for index, label in enumerate(edge.labels or []):
            text = label.text or ""
            css = label.properties.cssClasses or ""
            width, height = _measure(text, css)
            data = {"id": f"{owner}.l{index}", "text": text,
                    "width": width, "height": height,
                    "properties": {"cssClasses": css}}
            if label.layoutOptions:
                data["layoutOptions"] = dict(label.layoutOptions)
            labels.append(data)
        return labels

    def convert(node: Any) -> dict:
        identifier = node_id(node)
        css = node.properties.cssClasses or ""
        is_marker = "sysml-marker" in css
        has_children = bool(node.children)

        # place labels manually: a snug vertical stack (the browser pipeline
        # measures real glyphs; headless we control the geometry ourselves)
        labels = []
        cursor = 5.0
        max_width = 0.0
        for index, label in enumerate(node.labels or []):
            text = label.text or ""
            label_css = label.properties.cssClasses or ""
            width, height = _measure(text, label_css)
            if is_marker:  # keep the dot small; hang the label below it
                x, y = 0.0, (node.height or 14) + 2 + index * height
            else:
                x, y = 8.0, cursor
                cursor += height
                max_width = max(max_width, width)
            labels.append({"id": f"{identifier}.l{index}", "text": text,
                           "x": x, "y": y, "width": width, "height": height,
                           "properties": {"cssClasses": label_css}})

        layout_options = {
            key: value for key, value in (node.layoutOptions or {}).items()
            if not key.startswith(("nodeLabels", "nodeSize", "elk.padding"))
        }
        data: dict[str, Any] = {
            "id": identifier,
            "layoutOptions": layout_options,
            "properties": {"cssClasses": css},
            "labels": labels,
            "children": [convert(child) for child in node.children],
        }
        if is_marker or node.width:
            data["width"] = node.width or 14
            data["height"] = node.height or 14
        elif has_children:
            # reserve the label block, then let ELK size around the children;
            # a minimum width keeps wide labels inside the box
            data["layoutOptions"]["elk.padding"] = (
                f"[top={cursor + 8:.0f},left=12,bottom=12,right=12]")
            data["layoutOptions"]["elk.nodeSize.constraints"] = "MINIMUM_SIZE"
            data["layoutOptions"]["elk.nodeSize.minimum"] = (
                f"({max_width + 20:.0f},{cursor + 20:.0f})")
        else:  # leaf: snug fit around the label stack
            data["width"] = max(max_width + 16, 40.0)
            data["height"] = max(cursor + 5, 26.0)
        edges = []
        for index, edge in enumerate(node.edges):
            edge_id = f"{identifier}.e{index}"
            # `event` rides through elkjs untouched (like cssClasses) and
            # becomes the SVG data-event attribute (sysml2.replay matches
            # fired transitions against it)
            edges.append({
                "id": edge_id,
                "sources": [node_id(edge.source)],
                "targets": [node_id(edge.target)],
                "labels": convert_edge_labels(edge, edge_id),
                "properties": {"cssClasses": edge.properties.cssClasses or "",
                               "event": getattr(edge.metadata, "event",
                                                None) or ""},
            })
        if edges:
            data["edges"] = edges
        return data

    return convert(root)


# ---------------------------------------------------------------------------
# elkjs layout via node
# ---------------------------------------------------------------------------


def _find_node() -> str:
    executable = shutil.which("node")
    if executable is None:
        raise SysMLError(
            "headless rendering needs a `node` executable for elkjs; "
            "the pixi environments provide one (or install Node.js)")
    return executable


def layout(elk_json: dict) -> dict:
    """Run the vendored elkjs on an ELK JSON graph and return the layout."""

    executable = _find_node()
    with tempfile.TemporaryDirectory(prefix="sysml2-elk-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "run.js").write_text(_NODE_SCRIPT, encoding="utf-8")
        (tmp_path / "in.json").write_text(json.dumps(elk_json),
                                          encoding="utf-8")
        result = subprocess.run(
            [executable, str(tmp_path / "run.js"), str(_ELK_JS),
             str(tmp_path / "in.json"), str(tmp_path / "out.json")],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise SysMLError(f"elkjs layout failed: {result.stderr.strip()}")
        loaded = json.loads((tmp_path / "out.json").read_text("utf-8"))
        if not isinstance(loaded, dict):
            raise SysMLError("elkjs layout returned unexpected output")
        return loaded


# ---------------------------------------------------------------------------
# laid-out ELK JSON -> SVG
# ---------------------------------------------------------------------------


def _style_for(css: str, table: dict[str, dict[str, str]],
               default: dict[str, str]) -> dict[str, str]:
    for name, style in table.items():
        if name in css:
            return style
    return default


def _escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _escape_attr(text: str) -> str:
    return _escape(text).replace('"', "&quot;")


def _svg_from_layout(graph: dict, padding: float = 8.0) -> str:
    parts: list[str] = []

    # First pass: absolute origins of every node.  elkjs moves each edge to
    # the common ancestor of its endpoints (the output's `container` field)
    # and emits its coordinates relative to *that* node -- not relative to
    # where the edge was declared.
    origins: dict[str, tuple[float, float]] = {}

    def index(node: dict, ox: float, oy: float) -> None:
        x, y = ox + node.get("x", 0), oy + node.get("y", 0)
        origins[str(node.get("id"))] = (x, y)
        for child in node.get("children", []):
            index(child, x, y)

    index(graph, padding, padding)

    def draw_node(node: dict, ox: float, oy: float) -> None:
        x, y = ox + node.get("x", 0), oy + node.get("y", 0)
        width, height = node.get("width", 0), node.get("height", 0)
        css = node.get("properties", {}).get("cssClasses", "")
        if node is not graph:  # the invisible root gets no box
            style = _style_for(css, _NODE_STYLES,
                               {"fill": "#ffffff", "stroke": "#999999",
                                "rx": "2"})
            # data-qname (the node id, a model qualified name for model
            # nodes) makes states addressable from sysml2.replay
            parts.append(
                f'<rect data-qname="{_escape_attr(str(node.get("id")))}" '
                f'x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
                f'height="{height:.1f}" rx="{style["rx"]}" '
                f'fill="{style["fill"]}" stroke="{style["stroke"]}"/>')
        for label in node.get("labels", []):
            draw_label(label, x, y)
        for child in node.get("children", []):
            draw_node(child, x, y)
        for edge in node.get("edges", []):
            draw_edge(edge, x, y)

    def edge_origin(edge: dict, default: tuple[float, float]
                    ) -> tuple[float, float]:
        container = edge.get("container")
        if container is not None:
            return origins.get(str(container), default)
        return default

    def draw_label(label: dict, ox: float, oy: float,
                   on_edge: bool = False) -> None:
        text = label.get("text", "")
        if not text:
            return
        css = label.get("properties", {}).get("cssClasses", "")
        style = _style_for(css, _LABEL_STYLES,
                           {"font-size": "11", "fill": "#222222"})
        size = float(style["font-size"])
        extra = ' font-style="italic"' if style.get("font-style") else ""
        if on_edge:
            # center the text in the label box ELK reserved; a halo lifts it
            # from the artwork instead of an opaque background rectangle
            # (which looked wrong over filled nodes). Drawn as a separate
            # under-text because cairosvg ignores paint-order.
            x = ox + label.get("x", 0) + label.get("width", 0) / 2
            y = oy + label.get("y", 0) + label.get("height", 12) / 2 \
                + size * 0.36
            common = (f'x="{x:.1f}" y="{y:.1f}" '
                      f'font-size="{style["font-size"]}" '
                      f'font-family="Helvetica,Arial,sans-serif" '
                      f'text-anchor="middle"{extra}')
            parts.append(
                f'<text {common} fill="#ffffff" stroke="#ffffff" '
                f'stroke-width="3" stroke-linejoin="round">'
                f'{_escape(text)}</text>')
            parts.append(
                f'<text {common} fill="{style["fill"]}">'
                f'{_escape(text)}</text>')
            return
        x = ox + label.get("x", 0)
        y = oy + label.get("y", 0) + size
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{style["font-size"]}" '
            f'fill="{style["fill"]}" font-family="Helvetica,Arial,sans-serif"'
            f'{extra}>{_escape(text)}</text>')

    def draw_edge(edge: dict, node_x: float, node_y: float) -> None:
        ox, oy = edge_origin(edge, (node_x, node_y))
        css = edge.get("properties", {}).get("cssClasses", "")
        style = _style_for(css, _EDGE_STYLES, {"stroke": "#666666"})
        dashes = style.get("stroke-dasharray")
        if "sysml-edge-guarded" in css:
            dashes = "6 2"
        # a group per edge, addressable from sysml2.replay: data-edge is
        # "<source id>-><target id>" (qualified names for model nodes),
        # data-event the comma-joined accepted event names (or "")
        sources, targets = edge.get("sources", []), edge.get("targets", [])
        data_edge = (f"{sources[0]}->{targets[0]}"
                     if sources and targets else "")
        event = edge.get("properties", {}).get("event", "") or ""
        parts.append(f'<g data-edge="{_escape_attr(data_edge)}" '
                     f'data-event="{_escape_attr(event)}">')
        for section in edge.get("sections", []):
            points = [section["startPoint"],
                      *section.get("bendPoints", []),
                      section["endPoint"]]
            path = " ".join(f"{'M' if i == 0 else 'L'} "
                            f"{ox + p['x']:.1f} {oy + p['y']:.1f}"
                            for i, p in enumerate(points))
            dash = f' stroke-dasharray="{dashes}"' if dashes else ""
            parts.append(
                f'<path d="{path}" fill="none" stroke="{style["stroke"]}" '
                f'stroke-width="1.4"{dash} marker-end="url(#arrow)"/>')
        for label in edge.get("labels", []):
            draw_label(label, ox, oy, on_edge=True)
        parts.append("</g>")

    draw_node(graph, padding, padding)
    width = graph.get("width", 0) + 2 * padding
    height = graph.get("height", 0) + 2 * padding
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 1 L 9 5 L 0 9 z" fill="#555555"/></marker></defs>'
        f'<rect width="100%" height="100%" fill="white"/>'
        + "".join(parts) + "</svg>")


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


def _root_of(source: Any) -> Any:
    """Accept a Diagram widget, an ipyelk Node, or a model element."""

    if isinstance(source, (M.Model, M.Element)):
        from . import diagrams

        source = diagrams.diagram(source)
    value = getattr(getattr(source, "source", None), "value", None)
    if value is not None:
        return value
    return source  # assume an ipyelk Node


def to_svg(source: Any, path: str | Path | None = None) -> str:
    """Render a diagram (widget, ipyelk node, or model element) to SVG."""

    graph = layout(_to_elk_json(_root_of(source)))
    svg = _svg_from_layout(graph)
    if path is not None:
        Path(path).write_text(svg, encoding="utf-8")
    return svg


def to_png(source: Any, path: str | Path, scale: float = 2.0) -> Path:
    """Render a diagram to PNG (requires cairosvg)."""

    try:
        import cairosvg
    except Exception as err:  # ImportError, or OSError from native cairo
        raise SysMLError(
            "PNG rendering needs cairosvg and the native cairo library "
            "(the pixi environments include both); alternatively use "
            "to_svg()") from err
    svg = to_svg(source)
    target = Path(path)
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(target),
                     scale=scale)
    return target
