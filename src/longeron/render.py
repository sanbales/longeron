"""Headless rendering of SysML diagrams to SVG/PNG.

The interactive widgets (:mod:`longeron.diagrams`) lay themselves out in the
browser.  This module runs the same layout engine -- elkjs 0.9.3, vendored
as ``_js/elk.bundled.js`` (EPL-2.0) -- in a node subprocess instead, then
draws the result as styled SVG:

    from longeron import diagrams, render

    render.to_svg(diagrams.state_diagram(machine), "machine.svg")
    render.to_png(model, "model.png")            # builds a view automatically

PNG conversion uses cairosvg when available (``pixi`` environments include
it).  Label sizes are estimated (the browser pipeline measures real glyphs),
so proportions differ slightly from the live widget.
"""

from __future__ import annotations

import itertools
import json
import math
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

# ---------------------------------------------------------------------------
# palette -- the single source of truth for diagram colors (V3)
# ---------------------------------------------------------------------------
# The browser stylesheet (diagrams.SYSML_STYLE) and the replay widget's CSS
# (replay._CSS) are DERIVED from these tables; change colors here only.

#: cssClasses fragment -> SVG attributes.  A non-CSS ``shape`` key selects a
#: non-rectangular glyph drawing (consumed by ``draw_node`` headless and by
#: the derived browser stylesheet; never emitted as a CSS property):
#: ``diamond`` (decision/merge rhombus), ``bullseye`` (done/final), and
#: ``circle-x`` (terminate).
_NODE_STYLES: dict[str, dict[str, str]] = {
    "sysml-package": {"fill": "#fbfbfb", "stroke": "#b0b0b0", "rx": "0"},
    "sysml-definition": {"fill": "#eef4fb", "stroke": "#4878a8", "rx": "4"},
    "sysml-usage": {"fill": "#f4faee", "stroke": "#6a9a48", "rx": "4"},
    "sysml-state": {"fill": "#fdf6e3", "stroke": "#b58900", "rx": "12"},
    "sysml-step": {"fill": "#f2eefb", "stroke": "#6c56a8", "rx": "6"},
    "sysml-marker": {"fill": "#333333", "stroke": "#333333", "rx": "7"},
    # behavior-view control glyphs (SysML v2 action flow notation): fork/join
    # bar (a filled rect), decision/merge rhombus, done/final bullseye, and
    # the terminate circle-X -- all in the neutral marker family
    "sysml-ctrl-bar": {"fill": "#333333", "stroke": "#333333", "rx": "1"},
    "sysml-ctrl-diamond": {"fill": "#ffffff", "stroke": "#333333", "shape": "diamond"},
    "sysml-final": {"fill": "#333333", "stroke": "#333333", "shape": "bullseye"},
    "sysml-terminate": {"fill": "#ffffff", "stroke": "#333333", "shape": "circle-x"},
}

#: fixed-size glyph nodes: no title box, labels hang below the glyph
_GLYPH_NODE_CLASSES = (
    "sysml-marker",
    "sysml-ctrl-bar",
    "sysml-ctrl-diamond",
    "sysml-final",
    "sysml-terminate",
)

_EDGE_STYLES: dict[str, dict[str, str]] = {
    "sysml-edge-specializes": {"stroke": "#4878a8", "stroke-dasharray": "none"},
    # the WHOLE specialization family draws SOLID lines (spec 8.2.3 BNF
    # printed p.200): feature typing is distinguished by its shaft
    # adornment, never by a dashed line
    "sysml-edge-typed": {"stroke": "#6a9a48", "stroke-dasharray": "none"},
    "sysml-edge-redefines": {"stroke": "#6a9a48", "stroke-dasharray": "none"},
    "sysml-edge-subsets": {"stroke": "#6a9a48", "stroke-dasharray": "none"},
    "sysml-edge-references": {"stroke": "#6a9a48", "stroke-dasharray": "none"},
    "sysml-edge-member": {"stroke": "#555555"},
    "sysml-edge-refmember": {"stroke": "#555555"},
    "sysml-edge-connect": {"stroke": "#555555"},
    "sysml-edge-transition": {"stroke": "#b58900"},
    # action-flow successions are DASHED with open-V arrows (spec figures
    # printed pp.90-92); state-view transitions stay solid
    "sysml-edge-succession": {"stroke": "#6c56a8", "stroke-dasharray": "4 2"},
}

#: cssClasses fragment -> arrowhead form at the target end, per the SysML
#: v2/KerML graphical notation (single source for BOTH pipelines).
#:
#: The specialization family rule (spec 8.2.3, printed p.200): the line is
#: ALWAYS solid, the head ALWAYS a closed hollow triangle at the general/
#: definition end, and the shaft adornment tight behind the head mirrors
#: the extra textual characters of the relationship:
#: * ``hollow`` -- plain triangle: subclassification and subsetting ``:>``
#: * ``hollow-colon`` -- two filled dots straddling the shaft (a colon):
#:   feature typing ``:``
#: * ``hollow-tick`` -- one bar tick perpendicular across the shaft:
#:   redefinition ``:>>``
#: * ``hollow-dcolon`` -- two columns of two filled dots (double colon):
#:   reference subsetting ``::>``
#: * ``open`` -- two-stroke V: transitions and successions.
#: * ``none`` -- connectors (connect/interface/binding) and the membership
#:   edges (whose glyph is the diamond at the START end) carry no head.
_EDGE_ENDS: dict[str, str] = {
    "sysml-edge-specializes": "hollow",
    "sysml-edge-typed": "hollow-colon",
    "sysml-edge-redefines": "hollow-tick",
    "sysml-edge-subsets": "hollow",
    "sysml-edge-references": "hollow-dcolon",
    "sysml-edge-member": "none",
    "sysml-edge-refmember": "none",
    "sysml-edge-connect": "none",
    "sysml-edge-transition": "open",
    "sysml-edge-succession": "open",
}

#: cssClasses fragment -> glyph form at the SOURCE end (marker-start).
#: Membership edges put a diamond at the whole/type end (spec 8.2.3 printed
#: pp.200-201): filled black for composite part membership, hollow for
#: referential (``ref``) membership.
_EDGE_STARTS: dict[str, str] = {
    "sysml-edge-member": "filled-diamond",
    "sysml-edge-refmember": "hollow-diamond",
}


def _edge_end(css: str) -> str:
    for name, end in _EDGE_ENDS.items():
        if name in css:
            return end
    return "open"


def _edge_start(css: str) -> str | None:
    for name, form in _EDGE_STARTS.items():
        if name in css:
            return form
    return None


#: guarded transitions/successions (edges also carrying sysml-edge-guarded)
_GUARDED_DASHARRAY = "6 2"

#: replay highlight (longeron.replay swaps fired edges to this marker)
_FIRED_STROKE = "#e05a00"

# ---------------------------------------------------------------------------
# shared glyph geometry -- one geometry, two encodings (SVG markers headless,
# ipyelk symbols in the browser); all sizes in diagram units
# ---------------------------------------------------------------------------

#: specialization-family shaft adornments (behind the hollow triangle head)
_ADORN_GAP = 2.5  # gap between the head's back edge and the adornment
_DOT_RADIUS = 1.6  # colon dot radius (dots are FILLED in the edge color)
_DOT_OFFSET = 3.0  # dot center distance from the shaft
_DCOLON_SPACING = 4.0  # spacing between the double-colon dot columns
_TICK_HALF = 5.0  # redefinition bar tick half-height

#: membership diamonds (12 long x 6 across, matches ipyelk Rhomb r=6)
_DIAMOND_LENGTH = 12.0
_DIAMOND_HALF = 3.0

#: behavior-view node glyphs
_GLYPH_SIZE = 16.0  # bullseye / terminate circle bounding box
_BULLSEYE_CORE_RATIO = 0.28  # core dot radius as a fraction of the box
_BAR_SHORT, _BAR_LONG = 6.0, 40.0  # fork/join bar (perpendicular to flow)
_CTRL_DIAMOND_SIZE = 24.0  # decision/merge rhombus

#: accept/send action badges (small filled tag at the box's top-left corner)
_BADGE_WIDTH, _BADGE_HEIGHT = 18.0, 12.0
_BADGE_NOTCH = 5.0  # accept: triangular notch depth cut into the LEFT edge
_BADGE_POINT = 5.0  # send: pointed RIGHT edge depth


def _badge_points(form: str, width: float, height: float) -> list[tuple[float, float]]:
    """Corner points of the accept/send action badges (filled, top-left).

    ``accept`` is a banner whose LEFT edge has a triangular notch cut into
    it; ``send`` is a pentagon tag with a flat left edge and a pointed
    right edge (spec 8.2.3 printed p.228; examples p.97).
    """

    if form == "accept":
        return [
            (0, 0),
            (width, 0),
            (width, height),
            (0, height),
            (_BADGE_NOTCH, height / 2),
        ]
    return [
        (0, 0),
        (width - _BADGE_POINT, 0),
        (width, height / 2),
        (width - _BADGE_POINT, height),
        (0, height),
    ]


def _arrow_id(stroke: str) -> str:
    return "arrow-" + stroke.lstrip("#")


def _hollow_arrow_id(stroke: str) -> str:
    return "arrow-hollow-" + stroke.lstrip("#")


def _marker_id(form: str, stroke: str) -> str:
    if form == "open":
        return _arrow_id(stroke)
    return f"arrow-{form}-{stroke.lstrip('#')}"  # hollow / hollow-colon / ...


def _diamond_id(stroke: str, hollow: bool) -> str:
    return ("diamond-hollow-" if hollow else "diamond-") + stroke.lstrip("#")


#: extra shaft length a hollow marker reserves behind the head, per form
_ADORN_TAIL = {
    "hollow": 0.0,
    "hollow-colon": _ADORN_GAP + 2 * _DOT_RADIUS + 1.5,
    "hollow-tick": _ADORN_GAP + 2 * _DOT_RADIUS + 1.5,
    "hollow-dcolon": _ADORN_GAP + 2 * _DOT_RADIUS + 1.5 + _DCOLON_SPACING,
}


def _hollow_marker(form: str, stroke: str) -> str:
    """A closed hollow triangle marker, optionally shaft-adorned (see
    ``_EDGE_ENDS``).  The white fill occludes the line underneath the head;
    the adornments sit behind the back edge, over the still-visible shaft.
    """

    tail = _ADORN_TAIL[form]
    width = 12 + tail
    back, tip = 1 + tail, 11 + tail
    bits = [
        f'<marker id="{_marker_id(form, stroke)}" viewBox="0 0 {width:g} 12" '
        f'refX="{tip:g}" refY="6" markerWidth="{width:g}" markerHeight="12" '
        f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        f'<path d="M {back:g} 1 L {tip:g} 6 L {back:g} 11 z" fill="#ffffff" '
        f'stroke="{stroke}" stroke-width="1.2"/>'
    ]
    if form in ("hollow-colon", "hollow-dcolon"):
        near = back - _ADORN_GAP - _DOT_RADIUS
        columns = [near] if form == "hollow-colon" else [near, near - _DCOLON_SPACING]
        bits += [
            f'<circle cx="{cx:g}" cy="{cy:g}" r="{_DOT_RADIUS:g}" fill="{stroke}"/>'
            for cx in columns
            for cy in (6 - _DOT_OFFSET, 6 + _DOT_OFFSET)
        ]
    elif form == "hollow-tick":
        x = back - _ADORN_GAP - 0.7
        bits.append(
            f'<path d="M {x:g} {6 - _TICK_HALF:g} L {x:g} {6 + _TICK_HALF:g}" '
            f'fill="none" stroke="{stroke}" stroke-width="1.4"/>'
        )
    bits.append("</marker>")
    return "".join(bits)


def _diamond_marker(stroke: str, hollow: bool) -> str:
    """A membership diamond for marker-start: it rides the line from the
    whole/type end outward; filled = composite, hollow = referential."""

    length, half = _DIAMOND_LENGTH, _DIAMOND_HALF
    width, height = length + 2, 2 * half + 2
    mid = half + 1
    fill = "#ffffff" if hollow else stroke
    return (
        f'<marker id="{_diamond_id(stroke, hollow)}" viewBox="0 0 {width:g} {height:g}" '
        f'refX="1" refY="{mid:g}" markerWidth="{width:g}" markerHeight="{height:g}" '
        f'markerUnits="userSpaceOnUse" orient="auto">'
        f'<path d="M 1 {mid:g} L {1 + length / 2:g} 1 L {1 + length:g} {mid:g} '
        f'L {1 + length / 2:g} {height - 1:g} z" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="1.2"/></marker>'
    )


def _arrow_defs() -> str:
    """Markers per glyph form and edge color (see ``_EDGE_ENDS`` /
    ``_EDGE_STARTS``).

    Open V heads for every edge color (plus the default gray and the
    replay fired-edge orange -- longeron.replay swaps fired edges to that
    marker id, so it must stay defined); closed hollow triangles -- plain
    and shaft-adorned, white-filled so they occlude the line underneath --
    for the specialization family; filled/hollow diamonds at the START end
    for the membership edges.  ``userSpaceOnUse`` keeps heads a constant
    size when a stylesheet widens the path stroke (e.g. the replay
    fired-edge highlight).
    """

    open_strokes = sorted(
        {style["stroke"] for style in _EDGE_STYLES.values()} | {"#666666", _FIRED_STROKE}
    )
    markers = [
        f'<marker id="{_arrow_id(stroke)}" viewBox="0 0 10 10" refX="9" '
        f'refY="5" markerWidth="10" markerHeight="10" '
        f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        f'<path d="M 0 1 L 9 5 L 0 9" fill="none" stroke="{stroke}" '
        f'stroke-width="1.4"/></marker>'
        for stroke in open_strokes
    ]
    for form in ("hollow", "hollow-colon", "hollow-tick", "hollow-dcolon"):
        strokes = sorted(
            {style["stroke"] for css, style in _EDGE_STYLES.items() if _EDGE_ENDS.get(css) == form}
        )
        markers += [_hollow_marker(form, stroke) for stroke in strokes]
    for start_form, hollow in (("filled-diamond", False), ("hollow-diamond", True)):
        strokes = sorted(
            {
                style["stroke"]
                for css, style in _EDGE_STYLES.items()
                if _EDGE_STARTS.get(css) == start_form
            }
        )
        markers += [_diamond_marker(stroke, hollow) for stroke in strokes]
    return "<defs>" + "".join(markers) + "</defs>"


_LABEL_STYLES: dict[str, dict[str, str]] = {
    "sysml-stereotype": {"font-size": "9", "fill": "#888888", "font-style": "italic"},
    "sysml-attribute": {"font-size": "10", "fill": "#444444"},
}

#: Helvetica AFM advance widths (thousandths of an em, Adobe Core 14) --
#: real metrics so label boxes match rendered glyphs (text.elklabel pins
#: the browser to Helvetica 11px; cairosvg/resvg use the same family)
_AFM = {
    " ": 278,
    "!": 278,
    '"': 355,
    "#": 556,
    "$": 556,
    "%": 889,
    "&": 667,
    "'": 191,
    "(": 333,
    ")": 333,
    "*": 389,
    "+": 584,
    ",": 278,
    "-": 333,
    ".": 278,
    "/": 278,
    "0": 556,
    "1": 556,
    "2": 556,
    "3": 556,
    "4": 556,
    "5": 556,
    "6": 556,
    "7": 556,
    "8": 556,
    "9": 556,
    ":": 278,
    ";": 278,
    "<": 584,
    "=": 584,
    ">": 584,
    "?": 556,
    "@": 1015,
    "A": 667,
    "B": 667,
    "C": 722,
    "D": 722,
    "E": 667,
    "F": 611,
    "G": 778,
    "H": 722,
    "I": 278,
    "J": 500,
    "K": 667,
    "L": 556,
    "M": 833,
    "N": 722,
    "O": 778,
    "P": 667,
    "Q": 778,
    "R": 722,
    "S": 667,
    "T": 611,
    "U": 722,
    "V": 667,
    "W": 944,
    "X": 667,
    "Y": 667,
    "Z": 611,
    "[": 278,
    "\\": 278,
    "]": 278,
    "^": 469,
    "_": 556,
    "`": 333,
    "a": 556,
    "b": 556,
    "c": 500,
    "d": 556,
    "e": 556,
    "f": 278,
    "g": 556,
    "h": 556,
    "i": 222,
    "j": 222,
    "k": 500,
    "l": 222,
    "m": 833,
    "n": 556,
    "o": 556,
    "p": 556,
    "q": 556,
    "r": 333,
    "s": 500,
    "t": 278,
    "u": 556,
    "v": 500,
    "w": 722,
    "x": 500,
    "y": 500,
    "z": 500,
    "{": 334,
    "|": 260,
    "}": 334,
    "~": 584,
    "\u00ab": 556,
    "\u00bb": 556,
    "\u2026": 1000,
}


def _font_size(css: str) -> int:
    for name, style in _LABEL_STYLES.items():
        if name in css:
            return int(style["font-size"])
    return 11


def _measure(text: str, css: str = "") -> tuple[float, float]:
    size = _font_size(css)
    ems = sum(_AFM.get(char, 600) for char in text) / 1000.0
    return max(10.0, ems * size + 4), size + 5


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
            data = {
                "id": f"{owner}.l{index}",
                "text": text,
                "width": width,
                "height": height,
                "properties": {"cssClasses": css},
            }
            if label.layoutOptions:
                data["layoutOptions"] = dict(label.layoutOptions)
            labels.append(data)
        return labels

    def convert(node: Any) -> dict:
        identifier = node_id(node)
        css = node.properties.cssClasses or ""
        is_marker = any(name in css for name in _GLYPH_NODE_CLASSES)
        has_children = bool(node.children)

        # place labels manually: a snug vertical stack (the browser pipeline
        # measures real glyphs; headless we control the geometry ourselves)
        labels = []
        cursor = 5.0
        measured = []
        for label in node.labels or []:
            text = label.text or ""
            label_css = label.properties.cssClasses or ""
            shape = label.properties.shape
            if "sysml-badge" in label_css and shape is not None and shape.width:
                # accept/send badges: pre-sized glyph labels, no text
                measured.append((text, label_css, float(shape.width), float(shape.height or 12)))
            else:
                measured.append((text, label_css, *_measure(text, label_css)))
        max_width = max((m[2] for m in measured), default=0.0)
        for index, (text, label_css, width, height) in enumerate(measured):
            is_attribute = "sysml-attribute" in label_css
            entry: dict[str, Any] = {
                "id": f"{identifier}.l{index}",
                "text": text,
                "width": width,
                "height": height,
                "properties": {"cssClasses": label_css},
            }
            if "sysml-badge" in label_css:
                # the badge pins to the box's top-left corner; the text
                # stack starts below it (spec: badge in the top-left,
                # keyword/name to its right at spec zoom -- stacking keeps
                # the headless geometry overlap-free)
                entry["x"], entry["y"] = 6.0, 4.0
                cursor = max(cursor, 4.0 + height + 2.0)
            elif is_marker:  # keep the dot small; hang the label below it
                entry["x"] = ((node.width or 14) - width) / 2
                entry["y"] = (node.height or 14) + 2 + index * height
            elif has_children:
                # containers: leave x/y to ELK, which centers the title
                # against the FINAL box (children decide the width).
                # Compartment rows get full-width boxes so their centered
                # left edges align; the SVG writer left-anchors their text
                # (V2: attribute compartments read left-aligned)
                if is_attribute:
                    entry["width"] = max_width
                cursor += height
            else:
                # leaves: titles center against the widest line (which the
                # box wraps with an 8px margin either side); compartment
                # rows pin to the left margin (V2)
                entry["x"] = 8.0 if is_attribute else 8.0 + (max_width - width) / 2
                entry["y"] = cursor
                cursor += height
            labels.append(entry)

        layout_options = {
            key: value
            for key, value in (node.layoutOptions or {}).items()
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
            # reserve the label block, then let ELK size around the children
            # and center the title labels; a minimum width keeps wide labels
            # inside the box
            data["layoutOptions"]["elk.nodeLabels.placement"] = "H_CENTER V_TOP INSIDE"
            data["layoutOptions"]["elk.padding"] = "[top=8,left=12,bottom=12,right=12]"
            data["layoutOptions"]["elk.nodeSize.constraints"] = "NODE_LABELS MINIMUM_SIZE"
            data["layoutOptions"]["elk.nodeSize.minimum"] = (
                f"({max_width + 20:.0f},{cursor + 20:.0f})"
            )
        else:  # leaf: snug width, uniform height (aligned boxes route
            # straighter: edges between equal-height siblings stay level)
            data["width"] = max(max_width + 16, 40.0)
            data["height"] = max(cursor + 5, 44.0)
        edges = []
        for index, edge in enumerate(node.edges):
            edge_id = f"{identifier}.e{index}"
            # `event` rides through elkjs untouched (like cssClasses) and
            # becomes the SVG data-event attribute (longeron.replay matches
            # fired transitions against it)
            edges.append(
                {
                    "id": edge_id,
                    "sources": [node_id(edge.source)],
                    "targets": [node_id(edge.target)],
                    "labels": convert_edge_labels(edge, edge_id),
                    "properties": {
                        "cssClasses": edge.properties.cssClasses or "",
                        "event": getattr(edge.metadata, "event", None) or "",
                    },
                }
            )
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
            "the pixi environments provide one (or install Node.js)"
        )
    return executable


def layout(elk_json: dict) -> dict:
    """Run the vendored elkjs on an ELK JSON graph and return the layout."""

    executable = _find_node()
    with tempfile.TemporaryDirectory(prefix="longeron-elk-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "run.js").write_text(_NODE_SCRIPT, encoding="utf-8")
        (tmp_path / "in.json").write_text(json.dumps(elk_json), encoding="utf-8")
        result = subprocess.run(
            [
                executable,
                str(tmp_path / "run.js"),
                str(_ELK_JS),
                str(tmp_path / "in.json"),
                str(tmp_path / "out.json"),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SysMLError(f"elkjs layout failed: {result.stderr.strip()}")
        loaded = json.loads((tmp_path / "out.json").read_text("utf-8"))
        if not isinstance(loaded, dict):
            raise SysMLError("elkjs layout returned unexpected output")
        return loaded


# ---------------------------------------------------------------------------
# laid-out ELK JSON -> SVG
# ---------------------------------------------------------------------------


def _style_for(
    css: str, table: dict[str, dict[str, str]], default: dict[str, str]
) -> dict[str, str]:
    for name, style in table.items():
        if name in css:
            return style
    return default


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_attr(text: str) -> str:
    return _escape(text).replace('"', "&quot;")


def _svg_from_layout(graph: dict, padding: float = 8.0, title: str | None = None) -> str:
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
        if node is not graph and "sysml-packgroup" not in css:
            # (pack groups are layout-only: geometry, never chrome)
            style = _style_for(
                css, _NODE_STYLES, {"fill": "#ffffff", "stroke": "#999999", "rx": "2"}
            )
            # data-qname (the node id: a model qualified name, instance-
            # qualified for expanded typed submachine states) makes states
            # addressable from longeron.replay
            qname = f'data-qname="{_escape_attr(str(node.get("id")))}"'
            shape = style.get("shape")
            if shape == "diamond":
                points = (
                    f"{x + width / 2:.1f},{y:.1f} {x + width:.1f},{y + height / 2:.1f} "
                    f"{x + width / 2:.1f},{y + height:.1f} {x:.1f},{y + height / 2:.1f}"
                )
                parts.append(
                    f'<polygon {qname} points="{points}" fill="{style["fill"]}" '
                    f'stroke="{style["stroke"]}" stroke-width="1.2"/>'
                )
            elif shape == "bullseye":
                cx, cy = x + width / 2, y + height / 2
                ring = min(width, height) / 2 - 0.6
                core = min(width, height) * _BULLSEYE_CORE_RATIO
                parts.append(
                    f"<g {qname}>"
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ring:.1f}" fill="#ffffff" '
                    f'stroke="{style["stroke"]}" stroke-width="1.2"/>'
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{core:.1f}" '
                    f'fill="{style["fill"]}"/></g>'
                )
            elif shape == "circle-x":
                cx, cy = x + width / 2, y + height / 2
                ring = min(width, height) / 2 - 0.6
                k = ring / math.sqrt(2)
                parts.append(
                    f"<g {qname}>"
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{ring:.1f}" '
                    f'fill="{style["fill"]}" stroke="{style["stroke"]}" stroke-width="1.2"/>'
                    f'<path d="M {cx - k:.1f} {cy - k:.1f} L {cx + k:.1f} {cy + k:.1f} '
                    f'M {cx + k:.1f} {cy - k:.1f} L {cx - k:.1f} {cy + k:.1f}" '
                    f'fill="none" stroke="{style["stroke"]}" stroke-width="1.2"/></g>'
                )
            else:
                parts.append(
                    f"<rect {qname} "
                    f'x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
                    f'height="{height:.1f}" rx="{style["rx"]}" '
                    f'fill="{style["fill"]}" stroke="{style["stroke"]}"/>'
                )
        for label in node.get("labels", []):
            draw_label(label, x, y)
        for child in node.get("children", []):
            draw_node(child, x, y)
        for edge in node.get("edges", []):
            draw_edge(edge, x, y)

    def edge_origin(edge: dict, default: tuple[float, float]) -> tuple[float, float]:
        container = edge.get("container")
        if container is not None:
            return origins.get(str(container), default)
        return default

    def draw_label(label: dict, ox: float, oy: float, on_edge: bool = False) -> None:
        css = label.get("properties", {}).get("cssClasses", "")
        if "sysml-badge" in css:
            # accept/send action badges: a small filled polygon at the box's
            # top-left corner (see _badge_points); no text
            bx, by = ox + label.get("x", 0), oy + label.get("y", 0)
            form = "accept" if "sysml-badge-accept" in css else "send"
            points = _badge_points(
                form, label.get("width", _BADGE_WIDTH), label.get("height", _BADGE_HEIGHT)
            )
            rendered = " ".join(f"{bx + px:.1f},{by + py:.1f}" for px, py in points)
            parts.append(f'<polygon points="{rendered}" fill="#333333"/>')
            return
        text = label.get("text", "")
        if not text:
            return
        style = _style_for(css, _LABEL_STYLES, {"font-size": "11", "fill": "#222222"})
        size = float(style["font-size"])
        extra = ' font-style="italic"' if style.get("font-style") else ""
        if on_edge:
            # center the text in the label box ELK reserved; a halo lifts it
            # from the artwork instead of an opaque background rectangle
            # (which looked wrong over filled nodes). Drawn as a separate
            # under-text because cairosvg ignores paint-order.
            x = ox + label.get("x", 0) + label.get("width", 0) / 2
            y = oy + label.get("y", 0) + label.get("height", 12) / 2 + size * 0.36
            common = (
                f'x="{x:.1f}" y="{y:.1f}" '
                f'font-size="{style["font-size"]}" '
                f'font-family="Helvetica,Arial,sans-serif" '
                f'text-anchor="middle"{extra}'
            )
            parts.append(
                f'<text {common} fill="#ffffff" stroke="#ffffff" '
                f'stroke-width="3" stroke-linejoin="round">'
                f"{_escape(text)}</text>"
            )
            parts.append(f'<text {common} fill="{style["fill"]}">{_escape(text)}</text>')
            return
        # anchor title/stereotype labels at the middle of the box ELK
        # reserved: the width heuristic overestimates for most strings, so
        # start-anchored text drifts left of where the (centered) box
        # actually sits.  Compartment rows (attributes etc.) left-align at
        # their box edge instead -- the UML/SysML convention (V2); their
        # boxes are margin-pinned (leaves) or full-width (containers), so
        # the box edge IS the compartment's left rule.
        if "sysml-attribute" in css:
            x = ox + label.get("x", 0)
            anchor = "start"
        else:
            x = ox + label.get("x", 0) + label.get("width", 0) / 2
            anchor = "middle"
        y = oy + label.get("y", 0) + size
        parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{style["font-size"]}" '
            f'fill="{style["fill"]}" font-family="Helvetica,Arial,sans-serif"'
            f' text-anchor="{anchor}"{extra}>{_escape(text)}</text>'
        )

    def draw_edge(edge: dict, node_x: float, node_y: float) -> None:
        css = edge.get("properties", {}).get("cssClasses", "")
        if "sysml-packing" in css:
            return  # layout-only: chains disconnected members into rows
        ox, oy = edge_origin(edge, (node_x, node_y))
        style = _style_for(css, _EDGE_STYLES, {"stroke": "#666666"})
        dashes = style.get("stroke-dasharray")
        if dashes == "none":
            dashes = None
        if "sysml-edge-guarded" in css:
            dashes = _GUARDED_DASHARRAY
        # a group per edge, addressable from longeron.replay: data-edge is
        # "<source id>-><target id>" (qualified names for model nodes),
        # data-event the comma-joined accepted event names (or "")
        sources, targets = edge.get("sources", []), edge.get("targets", [])
        data_edge = f"{sources[0]}->{targets[0]}" if sources and targets else ""
        event = edge.get("properties", {}).get("event", "") or ""
        parts.append(
            f'<g data-edge="{_escape_attr(data_edge)}" data-event="{_escape_attr(event)}">'
        )
        end = _edge_end(css)
        if end == "none":
            marker = ""  # connectors and membership lines carry no head
        else:
            marker = f' marker-end="url(#{_marker_id(end, style["stroke"])})"'
        start = _edge_start(css)
        if start is not None:  # membership diamond at the whole/type end
            hollow = start == "hollow-diamond"
            marker += f' marker-start="url(#{_diamond_id(style["stroke"], hollow)})"'
        for section in edge.get("sections", []):
            points = [section["startPoint"], *section.get("bendPoints", []), section["endPoint"]]
            path = " ".join(
                f"{'M' if i == 0 else 'L'} {ox + p['x']:.1f} {oy + p['y']:.1f}"
                for i, p in enumerate(points)
            )
            dash = f' stroke-dasharray="{dashes}"' if dashes else ""
            parts.append(
                f'<path d="{path}" fill="none" stroke="{style["stroke"]}" '
                f'stroke-width="1.4"{dash}{marker}/>'
            )
        for label in edge.get("labels", []):
            draw_label(label, ox, oy, on_edge=True)
        parts.append("</g>")

    draw_node(graph, padding, padding)
    width = graph.get("width", 0) + 2 * padding
    height = graph.get("height", 0) + 2 * padding
    # <title> as the first child names the diagram (V4): hover text in
    # browsers, the accessible name for assistive tech, and a saved
    # machine.svg is no longer anonymous
    caption = f"<title>{_escape(title)}</title>" if title else ""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">'
        + caption
        + _arrow_defs()
        + '<rect width="100%" height="100%" fill="white"/>'
        + "".join(parts)
        + "</svg>"
    )


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


def _svg_title(source: Any, root: Any) -> str | None:
    """A name for the exported diagram (V4): the element's qualified name.

    Model elements name themselves; for pre-built widgets/nodes the name is
    recovered from the node ids (qualified names), as the longest common
    ``::`` prefix of the root's named children.
    """

    if isinstance(source, M.Model):
        return getattr(source, "source_name", None) or "model"
    if isinstance(source, M.Element):
        return source.qualified_name or source.label
    if getattr(root, "id", None):
        return str(root.id)
    ids = [str(child.id) for child in getattr(root, "children", []) or [] if child.id]
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]
    segments = [identifier.split("::") for identifier in ids]
    common: list[str] = []
    for parts in zip(*segments, strict=False):  # stop at the shortest id
        if len(set(parts)) != 1:
            break
        common.append(parts[0])
    return "::".join(common) or None


def to_svg(source: Any, path: str | Path | None = None) -> str:
    """Render a diagram (widget, ipyelk node, or model element) to SVG."""

    root = _root_of(source)
    graph = layout(_to_elk_json(root))
    svg = _svg_from_layout(graph, title=_svg_title(source, root))
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
            "to_svg()"
        ) from err
    svg = to_svg(source)
    target = Path(path)
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=str(target), scale=scale)
    return target
