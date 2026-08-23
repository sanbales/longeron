"""Interactive SysML v2 diagrams for Jupyter, rendered with ipyelk/ELK.

Requires the vendored ipyelk (``pip install -e vendor/ipyelk``; the pixi
environments install it automatically).  Three views, one dispatcher:

* :func:`structure_diagram` -- packages, definitions (with attribute
  compartments), nested usages; specialization / typing / redefinition /
  subsetting / membership / connection edges with spec-notation glyphs:
  the specialization family draws solid lines into a closed hollow
  triangle at the general end, adorned on the shaft per relationship
  (colon dots = typing, bar tick = redefinition, double colon dots =
  reference subsetting); composite/referential membership draws a
  filled/hollow diamond at the whole end with end multiplicities.
* :func:`state_diagram` -- hierarchical states, entry markers, transitions
  labeled ``trigger [guard] / effect``; state usages typed by a state def
  expand into the definition's submachine (``submachine_depth`` bounds the
  expansion).
* :func:`action_diagram` -- the succession control-flow graph (the same one
  the interpreter executes), with the spec behavior glyphs: start dot,
  done bullseye, terminate circle-X, fork/join bars, decision/merge
  rhombi, accept/send badge boxes; successions render dashed.
* :func:`diagram` -- picks a view based on the element's kind.

Every view ships a compact toolbar (:mod:`longeron.toolbar`): icon-only
Fit / Center / Toggle-Collapse buttons plus a live search box that
highlights matching elements without touching the selection; pass
``toolbar=False`` to keep ipyelk's stock text buttons.

Node ids are qualified names, so browser-side selections map back to model
elements: use :func:`on_select` to react to clicks.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable
from typing import Any

try:
    import ipyelk
    from ipyelk.contrib.molds.connectors import Rhomb, StraightArrow, ThinArrow
    from ipyelk.elements import (
        Edge,
        EdgeProperties,
        EdgeShape,
        Label,
        LabelProperties,
        Node,
        NodeProperties,
    )
    from ipyelk.elements.elements import ElementMetadata
    from ipyelk.elements.shapes import SVG, Diamond, Icon, Path, Point
    from ipyelk.elements.symbol import EndpointSymbol, Symbol, SymbolSpec
except ImportError as _err:  # pragma: no cover - exercised without ipyelk
    from .errors import MissingExtraError

    raise MissingExtraError(
        "longeron.diagrams",
        "ipyelk (the vendored copy)",
        command="pip install -e vendor/ipyelk",
    ) from _err

from . import model as M
from .interpreter import Interpreter, _succession_plan
from .render import (
    _ADORN_GAP,
    _BADGE_HEIGHT,
    _BADGE_WIDTH,
    _BAR_LONG,
    _BAR_SHORT,
    _BULLSEYE_CORE_RATIO,
    _CTRL_DIAMOND_SIZE,
    _DCOLON_SPACING,
    _DOT_OFFSET,
    _DOT_RADIUS,
    _EDGE_ENDS,
    _EDGE_STARTS,
    _EDGE_STYLES,
    _GLYPH_SIZE,
    _GUARDED_DASHARRAY,
    _LABEL_STYLES,
    _NODE_STYLES,
    _TICK_HALF,
    _badge_points,
    _edge_end,
    _edge_start,
    _measure,
)
from .toolbar import upgrade_toolbar

__all__ = [
    "SYSML_STYLE",
    "action_diagram",
    "diagram",
    "on_select",
    "state_diagram",
    "structure_diagram",
]

_KIND_STEREOTYPES = {"use_case": "use case", "enum_literal": "", "feature": ""}


def _sysml_style() -> dict[str, dict[str, str]]:
    """Build the browser stylesheet from the shared palette.

    The colors live in :mod:`longeron.render` (``_NODE_STYLES`` /
    ``_EDGE_STYLES`` / ``_LABEL_STYLES``) -- the single source of truth
    also driving the headless SVG renderer and the replay CSS -- so the
    pipelines cannot drift apart (V3).
    """

    style: dict[str, dict[str, str]] = {" rect": {"transition": "all 0.2s"}}
    selected = "var(--jp-elk-color-selected)"
    for css, node_style in _NODE_STYLES.items():
        attrs = {key: value for key, value in node_style.items() if key != "shape"}
        shape = node_style.get("shape")
        if shape is None:
            style[f" .{css} > rect"] = attrs
        elif shape == "diamond":  # decision/merge: hollow rhombus
            style[f" .{css} > polygon"] = {
                "fill": attrs["fill"],
                "stroke": attrs["stroke"],
                "stroke-width": "1.2",
            }
        elif shape == "bullseye":  # done/final: filled dot in an empty circle
            style[f" .{css} .glyph-ring"] = {
                "fill": "#ffffff",
                "stroke": attrs["stroke"],
                "stroke-width": "1.2",
            }
            style[f" .{css} .glyph-core"] = {"fill": attrs["fill"]}
            # selection contract rule 3: the FILLED core follows the stroke
            # color; the hollow ring keeps its white fill forever
            style[f" .{css} > .elknode.selected .glyph-ring"] = {"stroke": selected}
            style[f" .{css} > .elknode.selected .glyph-core"] = {"fill": selected}
        elif shape == "circle-x":  # terminate: circle with an inscribed X
            style[f" .{css} .glyph-ring"] = {
                "fill": attrs["fill"],
                "stroke": attrs["stroke"],
                "stroke-width": "1.2",
            }
            style[f" .{css} .glyph-x"] = {
                "fill": "none",
                "stroke": attrs["stroke"],
                "stroke-width": "1.2",
            }
            style[f" .{css} > .elknode.selected .glyph-ring"] = {"stroke": selected}
            style[f" .{css} > .elknode.selected .glyph-x"] = {"stroke": selected}
    # fork/join bars are FILLED rects: selection flips fill with the stroke
    # (rule 3); the tiny glyph nodes pin their stroke width in every state
    # (the theme bumps selected nodes to width 3 -- a 6px bar becomes a blob)
    style[" .sysml-ctrl-bar > .elknode.selected"] = {"fill": selected, "stroke": selected}
    for css in ("sysml-marker", "sysml-ctrl-bar", "sysml-ctrl-diamond"):
        style[f" .{css} > .elknode"] = {"stroke-width": "1.2"}
    for css, label_style in _LABEL_STYLES.items():
        style[f" .{css} > text"] = {
            "fill": label_style["fill"],
            "font-size": f"{label_style['font-size']}px",
        }
    for css, edge_style in _EDGE_STYLES.items():
        style[f" .{css} > path"] = dict(edge_style)
        # arrowheads (the <use class="elkarrow"> child) must be recolored
        # separately: they inherit the theme gray from the edge <g>, not the
        # per-kind stroke we put on '> path' (see .handoff/edge-style-forensics)
        arrow_style = {"stroke": edge_style["stroke"]}
        end_form = _EDGE_ENDS.get(css, "")
        start_form = _EDGE_STARTS.get(css)
        if end_form.startswith("hollow"):
            # specialization-family heads are HOLLOW closed triangles
            # (SysML v2 / KerML): white fill occludes the line underneath,
            # the outline takes the edge color -- derived from the same
            # table the headless markers use (V3)
            arrow_style["fill"] = "#ffffff"
            if end_form != "hollow":
                # adorned heads (typing colon dots, redefinition tick,
                # reference-subsetting double dots) draw their FILLED
                # adornments with currentColor: bind it to the edge stroke
                arrow_style["color"] = edge_style["stroke"]
        if start_form == "filled-diamond":
            # composite membership: the diamond fill is BOUND to the edge
            # stroke (selection flips both, rule 3)
            arrow_style["fill"] = edge_style["stroke"]
        elif start_form == "hollow-diamond":
            # referential membership: hollow diamonds stay white forever
            arrow_style["fill"] = "#ffffff"
        style[f" .{css} > .elkarrow"] = arrow_style
        if start_form == "filled-diamond":
            style[f" .elkedge.{css}.selected > .elkarrow"] = {"fill": selected}
    # accept/send action badges: filled tags riding as icon labels; the
    # theme's .elklabel.selected rule cannot reach through our id-scoped
    # fill, so selection is restated here (filled family follows selection)
    for badge in ("accept-badge", "send-badge"):
        style[f" .{badge}"] = {"fill": "#333333", "stroke": "none"}
        style[f" .elklabel.{badge}.selected"] = {"fill": selected}
    # AFTER the per-kind rules: same specificity, so source order decides
    style[" .sysml-edge-guarded > path"] = {"stroke-dasharray": _GUARDED_DASHARRAY}
    style.update(
        {
            # layout-only packing edges (structure_diagram chains disconnected
            # members into rows; ELK skips component packing under
            # INCLUDE_CHILDREN): invisible in the browser, skipped headless
            " .sysml-packing > path": {"stroke": "none"},
            " .sysml-packing > .elkarrow": {"display": "none"},
            # the invisible compound node that pack_components wraps loose members
            # in: no box in the browser (headless skips its rect entirely)
            " .sysml-packgroup > rect": {"fill": "none", "stroke": "none"},
            # pin BOTH strokes in every state (the theme bumps the edge group's
            # stroke-width to 3 on selection / 2 on hover, which the path inherits
            # -- fat line, thin head): selection is a color change, not a weight
            # change
            " .sysml-edge > path": {"stroke-width": "var(--jp-elk-stroke-width)"},
            " .sysml-edge > .elkarrow": {"stroke-width": "1"},
            # selection: the WHOLE edge takes the selection color, heads stay thin;
            # HOLLOW glyph fills are never touched -- white bodies keep occluding
            # the line; FILLED glyphs follow the stroke via the per-kind rules and
            # the currentColor binding below (selection contract rule 3)
            " .elkedge.sysml-edge.selected > path": {"stroke": "var(--jp-elk-color-selected)"},
            " .elkedge.sysml-edge.selected > .elkarrow": {
                "stroke": "var(--jp-elk-color-selected)",
                "color": "var(--jp-elk-color-selected)",
                "stroke-width": "1",
            },
            " .elkedge.sysml-edge.selected.mouseover > .elkarrow": {"stroke-width": "1"},
            # halo so edge labels stay readable over crossings (browser-only path)
            " .sysml-edge text": {
                "paint-order": "stroke",
                "stroke": "#ffffff",
                "stroke-width": "3px",
                "stroke-linejoin": "round",
            },
            " text": {"font-family": "sans-serif", "font-size": "11px"},
            # the theme (and fast-foundation constructed stylesheets, which sit
            # late in the cascade) style .elklabel with the UI font, but label
            # BOXES are sized for 11px sans-serif (pre-sized edge labels + the
            # headless heuristic): if the glyph font is wider than the layout
            # font, text overflows its centered box. !important, scoped to this
            # widget, wins against any theme regardless of load order.
            " text.elklabel": {
                "font-family": "Helvetica, Arial, sans-serif !important",
                "font-size": "11px !important",
            },
        }
    )
    return style


SYSML_STYLE: dict[str, dict[str, str]] = _sysml_style()

_ROOT_LAYOUT = {
    "elk.algorithm": "layered",
    "elk.hierarchyHandling": "INCLUDE_CHILDREN",
    "elk.spacing.nodeNode": "24",
    # room for centered edge labels between layers (browser-measured text
    # is wider than the headless heuristic)
    "elk.layered.spacing.nodeNodeBetweenLayers": "52",
    # straighter edges, clearer labels (see .handoff forensics 2026-08-19):
    # NETWORK_SIMPLEX aligns chains that BRANDES_KOEPF leaves stepped under
    # INCLUDE_CHILDREN; edge/node clearance stops routes hugging borders
    "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
    "elk.layered.nodePlacement.favorStraightEdges": "true",
    "elk.spacing.edgeNode": "14",
    "elk.layered.spacing.edgeNodeBetweenLayers": "16",
    "elk.spacing.edgeLabel": "4",
    # center edge labels along the route (default MEDIAN_LAYER can put
    # them at a segment end, half under the target node)
    "elk.edgeLabels.centerLabelPlacementStrategy": "CENTER_LAYER",
}

_NODE_LAYOUT = {
    "nodeSize.constraints": "NODE_LABELS PORTS MINIMUM_SIZE",
    # H_CENTER: ipyelk's loader injects centered placement per label in the
    # browser anyway (overriding any node-level value); declaring it keeps
    # the headless SVG identical to what Lab shows
    "nodeLabels.placement": "H_CENTER V_TOP INSIDE",
    # uniform, slightly taller boxes: edges between equal-height siblings
    # attach at matching heights and route straight instead of jogging
    "elk.nodeSize.minimum": "(60, 44)",
    "elk.padding": "[top=8,left=8,bottom=8,right=8]",
}


def _stmt_text(statement: M.Element, limit: int = 28) -> str:
    """A one-line rendering of an action statement (for labels)."""

    from .export import _Printer

    printer = _Printer("  ")
    try:
        text = printer.stmt_fragment(statement)
    except TypeError:
        if isinstance(statement, M.IfAction):
            text = f"if {statement.condition.to_text()}"
        elif isinstance(statement, M.WhileLoop):
            text = (
                "loop" if statement.condition is None else f"while {statement.condition.to_text()}"
            )
        elif isinstance(statement, M.ForLoop):
            text = f"for {statement.var} in {statement.seq.to_text()}"
        else:
            text = statement.label
    if len(text) > limit:
        text = text[: limit - 1] + "\u2026"
    return text


def _usage_title(element: M.Usage) -> str:
    title = element.label
    if element.types:
        title += f" : {element.types[0]}"
    if element.multiplicity is not None:
        from .export import _Printer

        mult = _Printer("  ").multiplicity_text(element.multiplicity)
        if mult:
            title += f" {mult}"
    return title


def _walk_nodes(node: Node):
    yield node
    for child in node.children:
        yield from _walk_nodes(child)


def _mult_bracket_text(mult: M.Multiplicity) -> str | None:
    """The ``[n]`` / ``[n..m]`` part of a multiplicity (no ordered/nonunique
    suffix -- end labels stay compact per the spec's connector figures)."""

    from .export import _Printer

    text = _Printer("  ").multiplicity_text(mult)
    if not text.startswith("["):
        return None
    return text.split("]")[0] + "]"


def _add_end_multiplicity(edge: Edge, mult: M.Multiplicity, placement: str) -> None:
    """Attach an end-multiplicity label (``[4]``) near the edge's HEAD or
    TAIL, in the attribute typography; pre-sized like every edge label."""

    text = _mult_bracket_text(mult)
    if text is None:
        return
    label = _label(text, "sysml-attribute")
    label.layoutOptions = {"elk.edgeLabels.placement": placement}
    shape = label.properties.get_shape()
    shape.width, shape.height = _measure(text, "sysml-attribute")
    edge.labels = [*(edge.labels or []), label]


_MARKER_LAYOUT = {
    # place the 'start'/'done'/entry text below the dot, not on top of it
    "nodeLabels.placement": "OUTSIDE H_CENTER V_BOTTOM",
}


def _marker_node(text: str | None = None) -> Node:
    return _glyph_node(None, text, "sysml-marker", 14, 14)


def _glyph_node(
    element: M.Element | None,
    text: str | None,
    css: str,
    width: float,
    height: float,
    shape: Any | None = None,
) -> Node:
    """A fixed-size notation glyph (marker dot, control bar/rhombus,
    bullseye, terminate circle): no title box, the label hangs below."""

    labels = []
    if text:
        label = _label(text, "sysml-stereotype")
        # ipyelk's Loader.apply_layout_defaults injects an INSIDE placement
        # onto every label without layoutOptions, and the per-LABEL value
        # overrides the node-level option -- so the outside placement must
        # live on the label itself or the text lands on top of the glyph
        label.layoutOptions = dict(_MARKER_LAYOUT)
        labels.append(label)
    node = Node(
        width=width,
        height=height,
        labels=labels,
        layoutOptions=dict(_MARKER_LAYOUT),
        properties=NodeProperties(cssClasses=css),
    )
    if shape is not None:
        node.properties.shape = shape
    if element is not None and element.qualified_name:
        node.id = element.qualified_name
    return node


def _bullseye_svg() -> str:
    """done/final: a filled dot inside a slightly larger empty circle (spec
    8.2.3 printed p.227).  The glyph-* classes let the derived stylesheet
    drive the paints (selection flips core fill + ring stroke together)."""

    c = _GLYPH_SIZE / 2
    ring = c - 0.6
    core = _GLYPH_SIZE * _BULLSEYE_CORE_RATIO
    return (
        f'<circle class="glyph-ring" cx="{c:g}" cy="{c:g}" r="{ring:g}" '
        f'fill="#ffffff" stroke="#333333" stroke-width="1.2"/>'
        f'<circle class="glyph-core" cx="{c:g}" cy="{c:g}" r="{core:g}" fill="#333333"/>'
    )


def _terminate_svg() -> str:
    """terminate: a circle with an inscribed X (spec 8.2.3 printed p.227)."""

    c = _GLYPH_SIZE / 2
    ring = c - 0.6
    k = ring / math.sqrt(2)
    return (
        f'<circle class="glyph-ring" cx="{c:g}" cy="{c:g}" r="{ring:g}" '
        f'fill="#ffffff" stroke="#333333" stroke-width="1.2"/>'
        f'<path class="glyph-x" d="M {c - k:.2f},{c - k:.2f} L {c + k:.2f},{c + k:.2f} '
        f'M {c + k:.2f},{c - k:.2f} L {c - k:.2f},{c + k:.2f}" '
        f'fill="none" stroke="#333333" stroke-width="1.2"/>'
    )


def _label(text: str, css: str = "") -> Label:
    label = Label(text=text)
    if css:
        label.properties = LabelProperties(cssClasses=css)
    return label


def _node(element: M.Element | None, title: str, css: str, stereotype: str | None = None) -> Node:
    labels = []
    if stereotype:
        labels.append(_label(f"\u00ab{stereotype}\u00bb", "sysml-stereotype"))
    labels.append(_label(title))
    node = Node(
        labels=labels, layoutOptions=dict(_NODE_LAYOUT), properties=NodeProperties(cssClasses=css)
    )
    if element is not None and element.qualified_name:
        node.id = element.qualified_name
    return node


#: edge-end form (render._EDGE_ENDS) -> browser symbol identifier; the id
#: rides the <use class="elkarrow"> as a CSS class (sprotty setClass), so
#: the stylesheet can target each form
_END_SYMBOLS = {
    "hollow": "generalization",
    "hollow-colon": "generalization-colon",
    "hollow-tick": "generalization-tick",
    "hollow-dcolon": "generalization-dcolon",
    "open": "arrow",
}

#: edge-start form (render._EDGE_STARTS) -> browser symbol identifier
_START_SYMBOLS = {
    "filled-diamond": "composition",
    "hollow-diamond": "aggregation",
}


def _edge(
    source: Node,
    target: Node,
    css: str,
    text: str | None = None,
    event: str | None = None,
) -> Edge:
    edge = Edge(
        source=source, target=target, properties=EdgeProperties(cssClasses=f"sysml-edge {css}")
    )
    # endpoint glyphs derive from the SAME tables the headless markers use
    # (render._EDGE_ENDS / _EDGE_STARTS): one geometry, two encodings
    end = _END_SYMBOLS.get(_edge_end(css))
    start_form = _edge_start(css)
    start = _START_SYMBOLS.get(start_form) if start_form else None
    if end or start:
        edge.properties.shape = EdgeShape(start=start, end=end)
    if event:  # carried through to the SVG data-event (longeron.replay)
        edge.metadata = _EdgeMetadata(event=event)
    if text:
        # not inline: inline labels sit ON the line (the sprotty renderer
        # never interrupts it) and their dummy nodes add edge jogs
        label = _label(text)
        # pre-size edge labels: in the live pipeline they reach elkjs
        # unmeasured (the browser text-sizer path loses them), so ELK
        # "centers" a zero-width box and the text overflows right of the
        # midpoint. Pre-sized labels skip the browser sizer entirely and
        # match the headless renderer's geometry (same heuristic).
        shape = label.properties.get_shape()
        shape.width, shape.height = _measure(text)
        edge.labels = [label]
    return edge


class _EdgeMetadata(ElementMetadata):
    """Layout-inert annotation: the event name(s) a transition accepts."""

    event: str | None = None


def _specialization_svg(adorn: str) -> str:
    """Raw SVG for an adorned specialization head, in endpoint-symbol space
    (triangle tip at the origin, +x back along the edge).

    Explicit paints are required here: CSS cannot select into <use> shadow
    content, so the white triangle body and the currentColor adornments
    (bound to the edge stroke by the stylesheet) ride the geometry itself.
    """

    bits = [
        '<path d="M 6,-6 L 0,0 L 6,6 Z" fill="#ffffff" stroke="currentColor" stroke-width="1"/>'
    ]
    back = 6.0
    if adorn in ("colon", "dcolon"):
        near = back + _ADORN_GAP + _DOT_RADIUS
        columns = [near] if adorn == "colon" else [near, near + _DCOLON_SPACING]
        bits += [
            f'<circle cx="{cx:g}" cy="{cy:g}" r="{_DOT_RADIUS:g}" '
            f'fill="currentColor" stroke="none"/>'
            for cx in columns
            for cy in (-_DOT_OFFSET, _DOT_OFFSET)
        ]
    elif adorn == "tick":
        x = back + _ADORN_GAP + 0.7
        bits.append(
            f'<path d="M {x:g},{-_TICK_HALF:g} L {x:g},{_TICK_HALF:g}" '
            f'fill="none" stroke="currentColor" stroke-width="1.4"/>'
        )
    return "".join(bits)


def _adorned_triangle(identifier: str, adorn: str) -> EndpointSymbol:
    return EndpointSymbol(
        identifier=identifier,
        element=Node(properties=NodeProperties(shape=SVG(use=_specialization_svg(adorn)))),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-7, y=0),  # the line stops at the triangle back
    )


def _badge_symbol(identifier: str, form: str) -> Symbol:
    return Symbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=Path.from_list(_badge_points(form, _BADGE_WIDTH, _BADGE_HEIGHT), closed=True)
            )
        ),
        width=_BADGE_WIDTH,
        height=_BADGE_HEIGHT,
    )


def _symbols() -> SymbolSpec:
    """Edge-end and badge symbols per the SysML v2 graphical notation.

    The specialization family shares one head -- the closed triangle at
    the general/definition end, hollow because its body is filled white --
    and is told apart by the shaft adornment tight behind the head
    (``generalization`` plain for subclassification/subsetting, ``-colon``
    for feature typing, ``-tick`` for redefinition, ``-dcolon`` for
    reference subsetting).  ``composition``/``aggregation`` are the
    filled/hollow membership diamonds at the whole end.  ``arrow`` is the
    open two-stroke V of transitions and successions.  ``accept-badge`` /
    ``send-badge`` are the filled top-left action-box tags.
    """

    return SymbolSpec().add(
        StraightArrow("generalization", closed=True),
        ThinArrow("arrow"),
        _adorned_triangle("generalization-colon", "colon"),
        _adorned_triangle("generalization-tick", "tick"),
        _adorned_triangle("generalization-dcolon", "dcolon"),
        Rhomb("composition", r=6),
        Rhomb("aggregation", r=6),
        _badge_symbol("accept-badge", "accept"),
        _badge_symbol("send-badge", "send"),
    )


def _finish(
    root: Node,
    style: dict | None = None,
    direction: str | None = None,
    toolbar: bool = True,
) -> Any:
    root.layoutOptions = dict(_ROOT_LAYOUT)
    if direction:
        root.layoutOptions["elk.direction"] = direction
    result = ipyelk.from_element(root)
    result.symbols = _symbols()
    result.style = dict(SYSML_STYLE if style is None else style)
    result.layout.min_height = "400px"
    if toolbar:  # compact icon toolbar + search (longeron.toolbar)
        upgrade_toolbar(result)
    return result


# ---------------------------------------------------------------------------
# structure view
# ---------------------------------------------------------------------------


def structure_diagram(
    element: M.Model | M.Namespace,
    *,
    show_attributes: bool = True,
    show_relationships: bool = True,
    composition: str = "defs",
    toolbar: bool = True,
) -> Any:
    """Containment structure with specialization/typing/connection edges.

    ``composition="defs"`` (the default) draws definition-level membership
    edges -- a filled diamond at the whole end for composite part/item
    members, a hollow diamond for referential (``ref``) members, role name
    on the line, multiplicity at the part end -- per the SysML v2 Parts
    notation; ``composition="none"`` suppresses them.  ``toolbar=False``
    keeps ipyelk's stock text-button toolbar instead of the compact
    icon+search one (:mod:`longeron.toolbar`).
    """

    builder = _StructureBuilder(element, show_attributes, composition=composition)
    root = builder.build()
    if show_relationships:
        builder.add_relationship_edges(root)
    builder.pack_components(root)
    _size_compartment_rows(root)
    return _finish(root, toolbar=toolbar)


def _size_compartment_rows(node: Node) -> None:
    """Pre-size attribute rows to the node's widest label (V2).

    The browser draws label text start-anchored at its box's left edge and
    ELK centers each box: full-width attribute boxes therefore share one
    left edge (the compartment's left rule, per UML/SysML convention),
    while snug title/stereotype boxes stay visually centered.  Pre-sized
    labels skip the browser text sizer, exactly like pre-sized edge labels
    (same heuristic, so the geometry matches the headless renderer).
    """

    labels = node.labels or []

    def _is_row(label: Label) -> bool:
        return "sysml-attribute" in (label.properties.cssClasses or "")

    if any(_is_row(label) for label in labels):
        sizes = [_measure(label.text or "", label.properties.cssClasses or "") for label in labels]
        max_width = max(width for width, _ in sizes)
        for label, (_, height) in zip(labels, sizes, strict=True):
            if _is_row(label):
                shape = label.properties.get_shape()
                shape.width, shape.height = max_width, height
    for child in node.children:
        _size_compartment_rows(child)


#: target width:height for packing disconnected members (see pack_components)
_PACK_ASPECT = 1.6

#: tightened spacing for containers that are pure packing grids: no real
#: edges means no edge labels to leave room for (see pack_components)
_PACK_GRID_LAYOUT = {
    # a pure grid has no cross-hierarchy edges by construction, so it can
    # safely leave the global INCLUDE_CHILDREN layout: an isolated
    # sub-layout uses THESE spacings instead of the global layer grid
    # (under INCLUDE_CHILDREN, per-container spacing is ignored)
    "elk.hierarchyHandling": "SEPARATE_CHILDREN",
    "elk.layered.spacing.nodeNodeBetweenLayers": "16",
    "elk.spacing.nodeNode": "16",
    "elk.spacing.edgeNode": "4",
    "elk.layered.spacing.edgeNodeBetweenLayers": "4",
}

#: the invisible compound node wrapping loose members inside a container
#: that also has connected members: the grid spacing above, no padding,
#: no minimum size -- the group contributes geometry, never chrome
_PACK_GROUP_LAYOUT = {
    **_PACK_GRID_LAYOUT,
    "elk.padding": "[top=0,left=0,bottom=0,right=0]",
    "elk.nodeSize.minimum": "(0, 0)",
}


class _StructureBuilder:
    def __init__(
        self,
        element: M.Model | M.Namespace,
        show_attributes: bool,
        composition: str = "defs",
    ):
        self.element = element
        self.show_attributes = show_attributes
        self.composition = composition
        owner: M.Element = element
        while owner.owner is not None:
            owner = owner.owner
        self.model = owner if isinstance(owner, M.Model) else M.Model()
        self.interp = Interpreter(self.model)
        self.nodes: dict[int, Node] = {}

    def build(self) -> Node:
        root = Node(properties=NodeProperties(cssClasses="sysml-root"))
        roots = self.element.members if isinstance(self.element, M.Model) else [self.element]
        for member in roots:
            child = self._visit(member)
            if child is not None:
                root.children.append(child)
        return root

    def _visit(self, element: M.Element) -> Node | None:
        if isinstance(element, M.Package):
            node = _node(element, element.label, "sysml-package", "package")
            for member in element.members:
                child = self._visit(member)
                if child is not None:
                    node.children.append(child)
        elif isinstance(element, M.Definition):
            stereotype = _KIND_STEREOTYPES.get(element.kind, element.kind)
            node = _node(element, element.label, "sysml-definition", f"{stereotype} def".strip())
            self._fill_features(node, element)
        elif isinstance(element, M.Usage) and element.kind in (
            "part",
            "item",
            "port",
            "action",
            "state",
            "occurrence",
        ):
            node = _node(element, _usage_title(element), "sysml-usage", element.kind)
            self._fill_features(node, element)
        else:
            return None
        self.nodes[id(element)] = node
        return node

    def _fill_features(self, node: Node, element: M.Namespace) -> None:
        for member in element.members:
            if not isinstance(member, M.Usage):
                child = self._visit(member)
                if child is not None:
                    node.children.append(child)
                continue
            if member.kind == "attribute" and self.show_attributes:
                text = _usage_title(member)
                if member.value is not None:
                    text += f" = {member.value.expr.to_text()}"
                node.labels.append(_label(text, "sysml-attribute"))
            elif member.kind == "enum_literal":
                node.labels.append(_label(member.label, "sysml-attribute"))
            elif member.direction is not None and self.show_attributes:
                title = (
                    _usage_title(member)
                    if member.name
                    else (f": {member.types[0]}" if member.types else "")
                )
                node.labels.append(_label(f"{member.direction} {title}".strip(), "sysml-attribute"))
            elif member.kind == "constraint" and self.show_attributes:
                kind = member.constraint_kind or "constraint"
                text = f"{kind} {member.name}" if member.name else kind
                if member.result is not None:
                    expr = member.result.to_text()
                    if len(expr) > 30:
                        expr = expr[:29] + "\u2026"
                    text += f" {{{expr}}}"
                node.labels.append(_label(text, "sysml-attribute"))
            elif member.kind == "subject" and self.show_attributes:
                node.labels.append(_label(f"subject {_usage_title(member)}", "sysml-attribute"))
            else:
                child = self._visit(member)
                if child is not None:
                    node.children.append(child)

    # -- relationship edges -------------------------------------------------

    def add_relationship_edges(self, root: Node) -> None:
        for element in list(self.nodes_elements()):
            node = self.nodes[id(element)]
            if isinstance(element, M.Definition):
                for super_name in element.supers:
                    target = self._resolve_node(super_name, element)
                    if target is not None:
                        root.edges.append(_edge(node, target, "sysml-edge-specializes"))
                if self.composition != "none":
                    self._add_membership_edges(root, element, node)
            if isinstance(element, M.Usage):
                for type_name in element.types:
                    target = self._resolve_node(type_name.lstrip("~"), element)
                    if target is not None:
                        # feature typing is a Specialization (KerML): SOLID
                        # line, hollow triangle at the definition, colon
                        # dots on the shaft (spec 8.2.3 printed p.200)
                        root.edges.append(_edge(node, target, "sysml-edge-typed"))
                # the rest of the specialization family: same solid line
                # and hollow head, told apart by the shaft adornment (the
                # spec draws NO keyword labels on these edges)
                for names, css in (
                    (element.redefines, "sysml-edge-redefines"),
                    (element.subsets, "sysml-edge-subsets"),
                    ([element.references] if element.references else [], "sysml-edge-references"),
                ):
                    for name in names:
                        target = self._resolve_feature_node(name, element)
                        if target is not None:
                            root.edges.append(_edge(node, target, css))
            if isinstance(element, (M.ConnectionUsage, M.InterfaceUsage, M.AllocationUsage)):
                self._connect_ends(root, element)
        # connections owned by anything we visited
        for element in list(self.nodes_elements()):
            for member in element.members if isinstance(element, M.Namespace) else []:
                if (
                    isinstance(member, (M.ConnectionUsage, M.BindingConnector))
                    and id(member) not in self.nodes
                ):
                    self._connect_ends(root, member)

    def _add_membership_edges(self, root: Node, element: M.Definition, node: Node) -> None:
        """Definition-level part membership edges (spec Parts notation,
        printed pp.37-38): ``Whole <>-- PartType`` with the diamond at the
        whole end -- FILLED for composite members, HOLLOW for referential
        (``ref``) members -- the member's role name on the line, and its
        multiplicity at the part end.  Usage containment stays drawn as
        nesting; a membership edge is never drawn to a node nested inside
        the whole itself (the nesting already shows it)."""

        inside = {id(child) for child in _walk_nodes(node)}
        for member in element.members:
            if not isinstance(member, M.Usage) or member.kind not in ("part", "item", "ref"):
                continue
            if not member.types:
                continue
            target = self._resolve_node(member.types[0].lstrip("~"), member)
            if target is None or target is node or id(target) in inside:
                continue
            referential = member.is_ref or member.kind == "ref"
            css = "sysml-edge-refmember" if referential else "sysml-edge-member"
            edge = _edge(node, target, css, text=member.name)
            if member.multiplicity is not None:
                _add_end_multiplicity(edge, member.multiplicity, "HEAD")
            root.edges.append(edge)

    def nodes_elements(self):
        for element in self.model.iter_tree():
            if id(element) in self.nodes:
                yield element

    def _connect_ends(self, root: Node, element: M.Usage) -> None:
        ends = (
            element.ends
            if hasattr(element, "ends")
            else [
                e
                for e in (
                    getattr(element, "source_end", None),
                    getattr(element, "target_end", None),
                )
                if e
            ]
        )
        resolved = [self._resolve_node(end.target, element) for end in ends]
        if len(resolved) >= 2 and all(n is not None for n in resolved):
            label = element.label if element.name else None
            for (end_a, source), (end_b, target) in itertools.pairwise(
                zip(ends, resolved, strict=True)
            ):
                edge = _edge(source, target, "sysml-edge-connect", text=label)
                # cross multiplicities render near the ends they constrain
                if end_a.multiplicity is not None:
                    _add_end_multiplicity(edge, end_a.multiplicity, "TAIL")
                if end_b.multiplicity is not None:
                    _add_end_multiplicity(edge, end_b.multiplicity, "HEAD")
                root.edges.append(edge)

    # -- component packing ----------------------------------------------------

    def pack_components(self, root: Node) -> None:
        """Chain disconnected members into rows so containers pack wide.

        ELK's connected-component packing does not run under the
        ``INCLUDE_CHILDREN`` hierarchy handling the structure view needs
        for cross-container edges, so members that touch no edge each
        claim their own layer: a package of unrelated definitions renders
        as one tall column.  Invisible ``sysml-packing`` edges chain the
        edge-free members of every container into rows sized toward
        :data:`_PACK_ASPECT`, giving the layered algorithm a grid instead.
        """

        touched: set[int] = set()
        for edge in root.edges:
            touched.add(id(edge.source))
            touched.add(id(edge.target))

        def is_loose(node: Node) -> bool:
            if id(node) in touched:
                return False
            return all(is_loose(child) for child in node.children)

        chains: list[tuple[Node, Node, Node]] = []  # (owner, source, target)

        def chain_rows(owner: Node, loose: list[Node]) -> None:
            per_row = max(2, math.ceil(math.sqrt(len(loose) * _PACK_ASPECT)))
            for i in range(1, len(loose)):
                if i % per_row:  # i % per_row == 0 starts the next row
                    chains.append((owner, loose[i - 1], loose[i]))

        def pack(container: Node) -> None:
            members = list(container.children)
            loose = [child for child in members if is_loose(child)]
            if len(loose) > 1:
                if len(loose) == len(members):
                    # a pure packing grid: every gap in this container is
                    # an invisible chain hop or a row gap, so the global
                    # edge-label-sized layer spacing is pure whitespace
                    container.layoutOptions.update(_PACK_GRID_LAYOUT)
                    chain_rows(container, loose)
                else:
                    # mixed container: wrap the loose members in an
                    # invisible group so they pack as one tight block
                    # instead of spreading across the real edges' layers
                    group = Node(
                        layoutOptions=dict(_PACK_GROUP_LAYOUT),
                        properties=NodeProperties(cssClasses="sysml-packgroup"),
                    )
                    group.children = loose
                    connected = [
                        child for child in members if id(child) not in {id(n) for n in loose}
                    ]
                    container.children = [*connected, group]
                    chain_rows(group, loose)
            for child in members:
                pack(child)

        pack(root)
        for owner, source, target in chains:
            owner.edges.append(
                Edge(
                    source=source,
                    target=target,
                    properties=EdgeProperties(cssClasses="sysml-packing"),
                )
            )

    def _resolve_node(self, name: str, context: M.Element) -> Node | None:
        try:
            found = self.interp.resolver.resolve(name.split(".")[0], context.owner or self.model)
            for part in name.split(".")[1:]:
                found = self.interp.resolver.resolve(part, found)
        except Exception:
            return None
        return self.nodes.get(id(found))

    def _resolve_feature_node(self, name: str, element: M.Usage) -> Node | None:
        """Resolve a subsets/redefines target to its node.

        The redefining feature usually shadows the name it redefines
        (``part engine :>> engine;``), so a plain scope lookup finds the
        element itself; the intended target then lives in the owner's
        generals.  Never yields the element's own node (no self-loops).
        """

        found: M.Element | None
        try:
            found = self.interp.resolver.resolve(name.split(".")[0], element.owner or self.model)
            for part in name.split(".")[1:]:
                found = self.interp.resolver.resolve(part, found)
        except Exception:
            return None
        if found is element and element.owner is not None:
            found = None
            for general in _state_generals(element.owner, self.interp.resolver):
                try:
                    found = self.interp.resolver.resolve(name, general)
                    break
                except Exception:
                    continue
        if found is None or found is element:
            return None
        return self.nodes.get(id(found))


# ---------------------------------------------------------------------------
# state view
# ---------------------------------------------------------------------------


def state_diagram(
    machine: M.Definition | M.Usage,
    *,
    submachine_depth: int | None = None,
    toolbar: bool = True,
) -> Any:
    """A hierarchical state machine: states, entry markers, transitions.

    A state usage typed by a state def (``state swap : ToteSwap;``) is
    expanded into the definition's full submachine -- states, entry
    marker, transitions -- the same member view the interpreter executes
    (``StateMachine`` descends through ``members_of``).  Expansion is
    recursive and cycle-safe: a definition reached again through its own
    submachine draws as a collapsed leaf.

    ``submachine_depth`` bounds how many *typing hops* to expand:
    ``None`` (the default) is unlimited, ``0`` draws typed states as
    plain leaves (the pre-0.8 behavior).  Plain nested states are always
    shown.  ``toolbar=False`` keeps ipyelk's stock toolbar.

    Expanded substate ids are instance-qualified
    (``…::swapSource::swap::evaluating``) so they stay unique per
    expansion site, selectable in the browser (the resolver walks typing
    hops), and exactly what :mod:`longeron.replay` records: two usages of
    one definition never share a replay key.
    """

    root = Node(properties=NodeProperties(cssClasses="sysml-root"))
    owner: M.Element = machine
    while owner.owner is not None:
        owner = owner.owner
    model = owner if isinstance(owner, M.Model) else M.Model()
    resolver = Interpreter(model).resolver
    base = machine.qualified_name or machine.label
    _fill_states(root, machine, root, resolver, base, submachine_depth, frozenset({id(machine)}))
    return _finish(root, toolbar=toolbar)


def _transition_text(transition: M.TransitionUsage) -> str | None:
    bits = []
    if transition.trigger is not None:
        trigger = transition.trigger
        if trigger.payload_types:
            bits.append(", ".join(t.split("::")[-1] for t in trigger.payload_types))
        elif trigger.payload_name:
            bits.append(trigger.payload_name)
        elif trigger.trigger_kind and trigger.trigger is not None:
            bits.append(f"{trigger.trigger_kind} {trigger.trigger.to_text()}")
    if transition.guard is not None:
        bits.append(f"[{transition.guard.to_text()}]")
    if transition.effect is not None:
        bits.append(f"/ {_stmt_text(transition.effect)}")
    return " ".join(bits) or None


def _transition_event(transition: M.TransitionUsage) -> str | None:
    """Comma-joined event names the transition accepts (or None).

    Mirrors StateMachine._trigger_matches (interpreter.py): payload types
    win over the payload name; time/when triggers accept no event.
    """

    trigger = transition.trigger
    if trigger is None or trigger.trigger_kind is not None:
        return None
    names = [t.split("::")[-1] for t in trigger.payload_types]
    if not names and trigger.payload_name:
        names = [trigger.payload_name]
    return ",".join(names) or None


def _state_generals(container: M.Element, resolver: Any) -> list[M.Element]:
    """The definitions a state container inherits members from.

    Its types (``state swap : ToteSwap``) and supers (``state def X :>
    Y``), resolved in the container's owner scope -- unresolvable names
    are skipped, mirroring how the relationship edges resolve.
    """

    names = [name.lstrip("~") for name in getattr(container, "types", [])]
    names += list(getattr(container, "supers", []))
    found: list[M.Element] = []
    for name in names:
        try:
            found.append(resolver.resolve(name, container.owner or container))
        except Exception:
            continue
    return found


def _fill_states(
    container_node: Node,
    container: M.Definition | M.Usage,
    root: Node,
    resolver: Any,
    base: str,
    budget: int | None,
    seen: frozenset[int],
) -> None:
    """Draw ``container``'s states and transitions into ``container_node``.

    ``budget`` is the number of typing hops still allowed below this
    container (``None`` = unlimited); ``seen`` holds the ids of
    definitions already being expanded on this branch, so a submachine
    that reaches a definition again draws it as a collapsed leaf instead
    of recursing forever.
    """

    members: list[M.Element] = list(container.members)
    child_budget = budget
    if budget is None or budget > 0:
        generals = _state_generals(container, resolver)
        if generals and not any(id(general) in seen for general in generals):
            # inline the inherited submachine: the exact member view the
            # interpreter executes (StateMachine._states_of -> members_of)
            members = list(resolver.members_of(container))
            seen = seen | {id(general) for general in generals}
            child_budget = None if budget is None else budget - 1
    states: dict[str, Node] = {}
    for member in members:
        if isinstance(member, M.Usage) and member.kind == "state" and member.name:
            node = _node(member, _usage_title(member), "sysml-state", "state")
            # instance-qualified (unique per expansion site of a typed
            # submachine, unlike the shared definition members' qualified
            # names) -- the same key longeron.replay records
            node.id = f"{base}::{member.name}"
            _fill_states(node, member, root, resolver, node.id, child_budget, seen)
            states[member.name] = node
            container_node.children.append(node)
    marker: Node | None = None
    for member in members:
        if not isinstance(member, M.TransitionUsage):
            continue
        target = states.get(member.target)
        if target is None:
            continue
        if member.source == M.ENTRY_SOURCE:
            if marker is None:
                marker = _marker_node()
                container_node.children.append(marker)
            root.edges.append(
                _edge(
                    marker,
                    target,
                    "sysml-edge-transition",
                    text=(f"[{member.guard.to_text()}]" if member.guard else None),
                )
            )
        else:
            source = states.get(member.source or "")
            if source is None:
                continue
            css = "sysml-edge-transition"
            if member.guard is not None:
                css += " sysml-edge-guarded"
            root.edges.append(
                _edge(
                    source,
                    target,
                    css,
                    text=_transition_text(member),
                    event=_transition_event(member),
                )
            )


# ---------------------------------------------------------------------------
# action view
# ---------------------------------------------------------------------------


def action_diagram(action: M.Definition | M.Usage, *, toolbar: bool = True) -> Any:
    """The succession control-flow graph the interpreter executes.

    Successions render dashed with open-V arrows and the behavior nodes
    use the spec glyphs (spec 8.2.3 printed p.227-228; figures pp.90-92):
    start = filled dot, done = bullseye, terminate = circle-X, fork/join =
    thick filled bar, decision/merge = empty rhombus, accept/send = the
    standard rounded action box with a filled top-left badge.
    ``toolbar=False`` keeps ipyelk's stock toolbar.
    """

    root = Node(properties=NodeProperties(cssClasses="sysml-root"))

    plan = _succession_plan(list(action.members))
    steps: dict[str, Node] = {}

    def marker(name: str) -> Node:
        node = _marker_node(name)
        root.children.append(node)
        return node

    def done_node() -> Node:
        node = _glyph_node(
            None, "done", "sysml-final", _GLYPH_SIZE, _GLYPH_SIZE, shape=SVG(use=_bullseye_svg())
        )
        root.children.append(node)
        return node

    if plan is not None:
        for name, element in plan.steps.items():
            node = _action_step_node(element, name)
            steps[name] = node
            root.children.append(node)
        steps["start"] = marker("start")
        steps["done"] = done_node()
        if plan.initial in steps:
            root.edges.append(_edge(steps["start"], steps[plan.initial], "sysml-edge-succession"))
        for edge in plan.edges:
            if edge.source == "start":
                continue  # covered by the initial edge above
            source, target = steps.get(edge.source), steps.get(edge.target)
            if source is None or target is None:
                continue
            css = "sysml-edge-succession"
            text = None
            if edge.guard is not None:
                css += " sysml-edge-guarded"
                text = f"[{edge.guard.to_text()}]"
            elif edge.is_else:
                css += " sysml-edge-guarded"
                text = "[else]"
            root.edges.append(_edge(source, target, css, text=text))
    else:  # declaration order: a simple chain
        previous = marker("start")
        for member in action.members:
            if isinstance(
                member,
                (
                    M.AssignmentAction,
                    M.SendAction,
                    M.AcceptAction,
                    M.PerformAction,
                    M.IfAction,
                    M.WhileLoop,
                    M.ForLoop,
                    M.TerminateAction,
                ),
            ) or (isinstance(member, M.Usage) and member.kind == "action"):
                title = member.name or _statement_title(member)
                node = _action_step_node(member, title)
                root.children.append(node)
                root.edges.append(_edge(previous, node, "sysml-edge-succession"))
                previous = node
        root.edges.append(_edge(previous, done_node(), "sysml-edge-succession"))

    return _finish(root, direction="RIGHT", toolbar=toolbar)


def _action_step_node(element: M.Element, title: str) -> Node:
    """A node for one action-flow step, using the spec glyph for control
    nodes, terminate, and the accept/send badge boxes; everything else is
    the standard rounded «keyword» step box."""

    if isinstance(element, M.ControlNode):
        if element.kind in ("fork", "join"):
            # a thick filled bar, perpendicular to the (horizontal) flow;
            # fork vs join is topology, the glyph is identical
            return _glyph_node(element, title, "sysml-ctrl-bar", _BAR_SHORT, _BAR_LONG)
        # decision vs merge: identical empty rhombus, role by topology
        return _glyph_node(
            element,
            title,
            "sysml-ctrl-diamond",
            _CTRL_DIAMOND_SIZE,
            _CTRL_DIAMOND_SIZE,
            shape=Diamond(),
        )
    if isinstance(element, M.TerminateAction):
        return _glyph_node(
            element,
            element.name or "terminate",
            "sysml-terminate",
            _GLYPH_SIZE,
            _GLYPH_SIZE,
            shape=SVG(use=_terminate_svg()),
        )
    if isinstance(element, (M.AcceptAction, M.SendAction)):
        form = "accept" if isinstance(element, M.AcceptAction) else "send"
        node = _node(element, title, f"sysml-step sysml-step-{form}", form)
        badge = Label(text="")
        badge.properties = LabelProperties(
            cssClasses=f"sysml-badge sysml-badge-{form}",
            shape=Icon(use=f"{form}-badge", width=_BADGE_WIDTH, height=_BADGE_HEIGHT),
        )
        badge.layoutOptions = {"nodeLabels.placement": "H_LEFT V_TOP INSIDE"}
        node.labels.insert(0, badge)
        return node
    kind = getattr(element, "kind", None) or type(element).__name__.replace("Action", "")
    return _node(element, title, "sysml-step", str(kind))


def _statement_title(member: M.Element) -> str:
    return _stmt_text(member)


# ---------------------------------------------------------------------------
# dispatcher & interactivity
# ---------------------------------------------------------------------------


def diagram(element: M.Model | M.Element, **kwargs: Any) -> Any:
    """Pick a view by element kind: state machines, actions, else structure."""

    kind = getattr(element, "kind", None)
    if kind == "state":
        return state_diagram(element, **kwargs)  # type: ignore[arg-type]
    if kind == "action":
        return action_diagram(element, **kwargs)  # type: ignore[arg-type]
    return structure_diagram(element, **kwargs)  # type: ignore[arg-type]


def on_select(
    diagram_widget: Any, model: M.Model, callback: Callable[[list[M.Element]], None]
) -> None:
    """Invoke ``callback`` with the model elements selected in the browser.

    Node ids are qualified names, so selections resolve directly.
    """

    interp = Interpreter(model)

    def _observe(change: Any) -> None:
        elements = []
        for identifier in change["new"]:
            try:
                elements.append(interp.resolve(identifier))
            except Exception:
                continue
        callback(elements)

    diagram_widget.view.selection.observe(_observe, "ids")
