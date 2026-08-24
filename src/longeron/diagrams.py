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
  Connector-family notation: port usages render as small squares ON the
  owning box's border (direction arrows inside, ``~T`` conjugation
  textual), interface / connection / binding / flow ends attach
  square-to-square, connector ends naming undrawn nested features draw
  the spec's proxy dot on the shallowest drawn ancestor, connections
  typed by a definition with directed (source/target) ends grow an
  open-V head, 3+-end connects meet at a filled junction dot, flow
  connections run pin-to-pin (filled arrowhead at the target),
  binding connectors ride an ``=`` glyph, anonymous allocations draw
  the «allocate» keyword arrow (named ones the «allocation» box),
  dependencies draw
  dashed open-V client->supplier (n-ary via a filled junction dot),
  satisfies draw the «satisfy» keyword edge or -- for named satisfy
  usages -- the reference-subsetting head into the «requirement» box;
  aliases draw a hollow circle at the referencing end, portion usages
  (timeslice/snapshot) a filled notched ball at their individual, and
  actors/stakeholders render as «actor»/«stakeholder» keyword boxes.
  Packages carry the spec's folder tab.
  ``membership="edges"`` swaps package nesting for the spec's ALTERNATIVE
  owned-membership presentation: members as sibling nodes, solid edges
  with a circle-plus at the owning namespace end.
  ``annotations=True`` adds comment/doc notes with dashed anchor lines
  and «@Type» metadata adornments.
* :func:`state_diagram` -- hierarchical states, entry markers, transitions
  labeled ``trigger [guard] / effect``; state usages typed by a state def
  expand into the definition's submachine (``submachine_depth`` bounds the
  expansion).
* :func:`action_diagram` -- the succession control-flow graph (the same one
  the interpreter executes), with the spec behavior glyphs: start dot,
  done bullseye, terminate circle-X, fork/join bars, decision/merge
  rhombi, accept/send badge boxes; successions render dashed.  Control
  glyphs converge their edge fans on single anchor points; ``lanes=``
  partitions the flow into dashed «performer» swim lanes.
* :func:`diagram` -- picks a view based on the element's kind.

Every view ships a compact toolbar (:mod:`longeron.toolbar`): icon-only
Fit / Center / Toggle-Collapse buttons, an edge-routing button that
cycles orthogonal / polyline / splines re-layouts (also available as the
``routing=`` kwarg on every view constructor for headless renders), plus
a live search box that
highlights matching elements without touching the selection; pass
``toolbar=False`` to keep ipyelk's stock text buttons.

Node ids are qualified names, so browser-side selections map back to model
elements: use :func:`on_select` to react to clicks.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

try:
    import ipyelk
    from ipyelk.contrib.molds.connectors import Rhomb
    from ipyelk.elements import (
        Edge,
        EdgeProperties,
        EdgeShape,
        Label,
        LabelProperties,
        Node,
        NodeProperties,
        Port,
        PortProperties,
    )
    from ipyelk.elements.elements import ElementMetadata
    from ipyelk.elements.shapes import SVG, Diamond, Icon, Path, Point, PortShape
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
    _BADGE_INSET_X,
    _BADGE_INSET_Y,
    _BADGE_STRIP,
    _BADGE_WIDTH,
    _BALL_MOUTH_DEG,
    _BALL_RADIUS,
    _BAR_LONG,
    _BAR_SHORT,
    _BULLSEYE_CORE_RATIO,
    _CIRCLE_RADIUS,
    _CTRL_DIAMOND_SIZE,
    _DCOLON_SPACING,
    _DOT_OFFSET,
    _DOT_RADIUS,
    _EDGE_END_CLEARANCE,
    _EDGE_ENDS,
    _EDGE_STARTS,
    _EDGE_STYLES,
    _FLOW_HEAD_HALF,
    _FLOW_HEAD_LENGTH,
    _GLYPH_SIZE,
    _GUARDED_DASHARRAY,
    _HEAD_HALF,
    _HEAD_LENGTH,
    _JUNCTION_SIZE,
    _LABEL_STYLES,
    _NODE_STYLES,
    _PIN_RX,
    _PIN_SIZE,
    _PORT_RX,
    _PORT_SIZE,
    _PROXY_SIZE,
    _TAB_HEIGHT,
    _TAB_WIDTH,
    _TICK_HALF,
    _V_HALF,
    _V_LENGTH,
    _badge_points,
    _edge_end,
    _edge_start,
    _measure,
    _note_path_d,
    _port_arrow_d,
)
from .toolbar import apply_routing, upgrade_toolbar

__all__ = [
    "SYSML_STYLE",
    "action_diagram",
    "diagram",
    "on_select",
    "state_diagram",
    "structure_diagram",
]

_KIND_STEREOTYPES = {
    "use_case": "use case",
    "enum_literal": "",
    "feature": "",
    # the «satisfy requirement» usage box (spec printed p.133)
    "satisfy": "satisfy requirement",
}


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
        elif shape == "note":  # comment/doc note: folded-corner path + crease
            style[f" .{css} > path"] = {
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
            # stroke NONE: the core is pure fill -- without it the circle
            # inherits the theme's .elknode stroke (a gray outline around
            # the filled center dot; maintainer repro: the done node)
            style[f" .{css} .glyph-core"] = {"fill": attrs["fill"], "stroke": "none"}
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
    # fork/join bars and the n-ary dependency junction dot are FILLED
    # glyphs: selection flips fill with the stroke (rule 3); the tiny glyph
    # nodes pin their stroke width in every state (the theme bumps selected
    # nodes to width 3 -- a 6px bar becomes a blob).  Lane boundaries pin
    # too: selection recolors the dashed border, never fattens it.
    for css in ("sysml-ctrl-bar", "sysml-junction", "sysml-connjunction"):
        style[f" .{css} > .elknode.selected"] = {"fill": selected, "stroke": selected}
    for css in (
        "sysml-marker",
        "sysml-ctrl-bar",
        "sysml-ctrl-diamond",
        "sysml-junction",
        "sysml-connjunction",
    ):
        style[f" .{css} > .elknode"] = {"stroke-width": "1.2"}
    style[" .sysml-lane > .elknode"] = {"stroke-width": "1.2"}
    style[" .sysml-lane > .elknode.selected"] = {"stroke-width": "1.2"}
    for css, label_style in _LABEL_STYLES.items():
        style[f" .{css} > text"] = {
            "fill": label_style["fill"],
            "font-size": f"{label_style['font-size']}px",
        }
    for css, edge_style in _EDGE_STYLES.items():
        style[f" .{css} > path"] = dict(edge_style)
        # arrowheads (the <use class="elkarrow"> child) must be recolored
        # separately: they inherit the theme gray from the edge <g>, not the
        # per-kind stroke we put on '> path' (see .handoff/edge-style-forensics).
        # `color` binds currentColor for the self-painted symbol geometry
        # (adorned triangle dots/ticks, flow pins, portion ball) to the
        # edge stroke.
        arrow_style = {"stroke": edge_style["stroke"], "color": edge_style["stroke"]}
        end_form = _EDGE_ENDS.get(css, "")
        start_form = _EDGE_STARTS.get(css)
        if end_form.startswith("hollow"):
            # specialization-family heads are HOLLOW closed triangles
            # (SysML v2 / KerML): white fill occludes the line underneath,
            # the outline takes the edge color -- derived from the same
            # table the headless markers use (V3)
            arrow_style["fill"] = "#ffffff"
        if end_form == "filled":
            # port-attached flow arrowheads: FILLED family, the fill is
            # bound to the edge stroke (selection flips both, rule 3)
            arrow_style["fill"] = edge_style["stroke"]
        if start_form == "filled-diamond":
            # composite membership: the diamond fill is BOUND to the edge
            # stroke (selection flips both, rule 3)
            arrow_style["fill"] = edge_style["stroke"]
        elif start_form in ("hollow-diamond", "circle", "circle-plus"):
            # referential membership diamonds / membership circles (alias
            # hollow circle, owned-member circle-plus) stay white; the
            # circle-plus cross strokes are self-painted currentColor, so
            # they follow the stroke color (selection contract rule 3)
            arrow_style["fill"] = "#ffffff"
        style[f" .{css} > .elkarrow"] = arrow_style
        if start_form == "filled-diamond" or end_form == "filled":
            style[f" .elkedge.{css}.selected > .elkarrow"] = {"fill": selected}
    # accept/send action badges: filled tags riding as icon labels; the
    # theme's .elklabel.selected rule cannot reach through our id-scoped
    # fill, so selection is restated here (filled family follows selection)
    for badge in ("accept-badge", "send-badge"):
        style[f" .{badge}"] = {"fill": "#333333", "stroke": "none"}
        style[f" .elklabel.{badge}.selected"] = {"fill": selected}
    # the package folder tab (spec printed p.24): a fixed-size icon label
    # riding the box's top-left.  The tab renders as <use> shadow content,
    # where the theme's `.elklabel` rule (label-color fill, stroke-width 0)
    # beats any class-based fill/stroke we could put on the <use> -- so the
    # symbol geometry carries the package palette as EXPLICIT attributes
    # (like the endpoint symbols) with the outline in currentColor; these
    # rules bind currentColor so selection recolors the tab WITH the box.
    style[" .package-tab"] = {"color": _NODE_STYLES["sysml-package"]["stroke"]}
    style[" .elklabel.package-tab.selected"] = {"color": selected}
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
    # ... but the label KINDS are measured at their own sizes (attribute
    # rows 10px, «keyword» stereotypes 9px, per _LABEL_STYLES): the blanket
    # 11px !important above was inflating them in the browser, so their
    # pre-sized boxes overflowed the node (maintainer repro: QuadCopter's
    # totalMass row).  Per-kind rules -- higher specificity than the
    # blanket rule -- restore the measured sizes; selection still recolors.
    for css, label_style in _LABEL_STYLES.items():
        kind_style = {
            "font-size": f"{label_style['font-size']}px !important",
            "fill": label_style["fill"],
        }
        if label_style.get("font-style"):
            kind_style["font-style"] = label_style["font-style"]
        style[f" text.elklabel.{css}"] = kind_style
        style[f" text.elklabel.{css}.selected"] = {"fill": selected}
    # ports (interconnection squares to come, flow pins, and the stubs
    # ipyelk substitutes for collapsed content -- 'slack' ports): white
    # body, border in the OWNING node kind's stroke color, stroke width
    # pinned in every state; selection recolors the FILL (§2.0 rule 4),
    # hover never fattens.  Single-sourced from _NODE_STYLES.
    style[" .elkport"] = {
        "fill": "#ffffff",
        "stroke-width": "var(--jp-elk-stroke-width)",
        "rx": "2",
    }
    style[" .elkport.selected"] = {
        "fill": selected,
        "stroke-width": "var(--jp-elk-stroke-width)",
        # direction arrows (self-painted currentColor inside the square)
        # recolor to white against the selection fill (§2.0 rule 4)
        "color": "#ffffff",
    }
    style[" .elkport.mouseover"] = {"stroke-width": "var(--jp-elk-stroke-width)"}
    # the proxy dot is FILLED (currentColor body): selection follows the
    # selection color instead of dropping to white (rule 3, filled family)
    style[" .elkport.port-proxy.selected"] = {"color": selected}
    for css, node_style in _NODE_STYLES.items():
        style[f" .{css} .elkport"] = {
            "stroke": node_style["stroke"],
            # currentColor for the direction arrow / proxy dot geometry
            "color": node_style["stroke"],
        }
        style[f" .{css} .elkport.selected"] = {
            "fill": selected,
            "stroke": selected,
            "stroke-width": "var(--jp-elk-stroke-width)",
        }
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
    # edge channels keep at least an endpoint glyph's reach from the nodes
    # they enter, so no orthogonal bend ever falls under an arrowhead
    # (render._EDGE_END_CLEARANCE; restated per hierarchy level in _finish)
    "elk.layered.spacing.edgeNodeBetweenLayers": f"{_EDGE_END_CLEARANCE:g}",
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


def _endpoint_node(endpoint: Node | Port) -> Node:
    """The owning NODE of an edge endpoint (a Port anchors the edge, but
    identity and packing stay with its parent node)."""

    if isinstance(endpoint, Node):
        return endpoint
    parent = endpoint.get_parent()
    assert isinstance(parent, Node)  # ports always ride nodes
    return parent


def _mult_bracket_text(mult: M.Multiplicity) -> str | None:
    """The ``[n]`` / ``[n..m]`` part of a multiplicity (no ordered/nonunique
    suffix -- end labels stay compact per the spec's connector figures)."""

    from .export import _Printer

    text = _Printer("  ").multiplicity_text(mult)
    if not text.startswith("["):
        return None
    return text.split("]")[0] + "]"


def _add_end_label(edge: Edge, text: str, placement: str, css: str = "sysml-attribute") -> None:
    """Attach a label near the edge's HEAD or TAIL (end multiplicities,
    flow payload items), pre-sized like every edge label."""

    label = _label(text, css)
    label.layoutOptions = {"elk.edgeLabels.placement": placement}
    shape = label.properties.get_shape()
    shape.width, shape.height = _measure(text, css)
    edge.labels = [*(edge.labels or []), label]


def _add_center_label(edge: Edge, text: str, css: str = "") -> None:
    """Append a centered, pre-sized label to an edge (the binding ``=``)."""

    label = _label(text, css)
    shape = label.properties.get_shape()
    shape.width, shape.height = _measure(text, css)
    edge.labels = [*(edge.labels or []), label]


def _add_end_multiplicity(edge: Edge, mult: M.Multiplicity, placement: str) -> None:
    """Attach an end-multiplicity label (``[4]``) near the edge's HEAD or
    TAIL, in the attribute typography; pre-sized like every edge label."""

    text = _mult_bracket_text(mult)
    if text is None:
        return
    _add_end_label(edge, text, placement)


_MARKER_LAYOUT = {
    # place the 'start'/'done'/entry text below the dot, not on top of it
    "nodeLabels.placement": "OUTSIDE H_CENTER V_BOTTOM",
}


def _marker_node(text: str | None = None) -> Node:
    return _glyph_node(None, text, "sysml-marker", 14, 14)


#: convergence anchors for control glyphs (fixed sides, centered): all
#: incoming edges join at ONE west port, all outgoing leave from ONE east
#: port, so multi-branch fans meet the tiny glyph at a single point each
_ANCHOR_LAYOUT = {
    "elk.portConstraints": "FIXED_SIDE",
    "elk.portAlignment.default": "CENTER",
}


def _add_anchor_ports(node: Node) -> Node:
    """Give a glyph node single in/out convergence points (invisible 0-size
    ELK ports on its west/east sides).  Fork/join bars deliberately do NOT
    get these: their edges distribute along the bar's long side, which is
    the bar's semantic."""

    node.layoutOptions.update(_ANCHOR_LAYOUT)
    for side, key in (("WEST", "in"), ("EAST", "out")):
        port = Port(
            width=0,
            height=0,
            layoutOptions={"elk.port.side": side},
            properties=PortProperties(key=key),
        )
        node.add_port(port, key=key)
    return node


def _anchor(node: Node, key: str) -> Node | Port:
    """The node's convergence port (``in``/``out``) if it has one, else the
    node itself -- edge endpoints resolve through this everywhere in the
    action view."""

    for port in node.ports:
        if port.properties.key == key:
            return port
    return node


def _add_center_anchor(node: Node) -> Node:
    """Anchor EVERY spoke at the junction dot's CENTER: two invisible
    fixed-side ports (in = WEST, out = EAST) whose ``elk.port.anchor``
    pulls the attachment point to the glyph's midpoint, so the fan
    visually radiates from the dot itself -- the spec's n-ary figures
    (printed pp.19, 66) draw all lines meeting AT the dot, and border
    attachment scattered them across the dot's boundary.  ELK still
    routes clients in one side and suppliers out the other (a single
    center port made outgoing spokes detour back around the dot); the
    dot's fill covers the meeting point."""

    node.layoutOptions.update(_ANCHOR_LAYOUT)
    half = (node.width or 0) / 2
    for side, key, anchor in (("WEST", "in", half), ("EAST", "out", -half)):
        port = Port(
            width=0,
            height=0,
            layoutOptions={"elk.port.side": side, "elk.port.anchor": f"({anchor:g},0)"},
            properties=PortProperties(key=key),
        )
        node.add_port(port, key=key)
    return node


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
        f'<circle class="glyph-core" cx="{c:g}" cy="{c:g}" r="{core:g}" '
        f'fill="#333333" stroke="none"/>'
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
    "filled": "flow-arrow",
    "pin-arrow": "flow-target-pin",
    "ball-notch": "portion-ball",
}

#: edge-start form (render._EDGE_STARTS) -> browser symbol identifier
_START_SYMBOLS = {
    "filled-diamond": "composition",
    "hollow-diamond": "aggregation",
    "pin": "flow-source-pin",
    "circle": "alias-circle",
    "circle-plus": "owned-circle-plus",
}


def _edge(
    source: Node | Port,
    target: Node | Port,
    css: str,
    text: str | None = None,
    event: str | None = None,
    text_css: str = "",
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
        label = _label(text, text_css)
        # pre-size edge labels: in the live pipeline they reach elkjs
        # unmeasured (the browser text-sizer path loses them), so ELK
        # "centers" a zero-width box and the text overflows right of the
        # midpoint. Pre-sized labels skip the browser sizer entirely and
        # match the headless renderer's geometry (same heuristic).
        shape = label.properties.get_shape()
        shape.width, shape.height = _measure(text, text_css)
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
    Head geometry mirrors the headless markers (render._HEAD_LENGTH /
    _HEAD_HALF -- the slender 2:1 spec proportions, never 45 degrees).
    """

    back = _HEAD_LENGTH
    bits = [
        f'<path d="M {back:g},{-_HEAD_HALF:g} L 0,0 L {back:g},{_HEAD_HALF:g} Z" '
        f'fill="#ffffff" stroke="currentColor" stroke-width="1"/>'
    ]
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
        path_offset=Point(x=-_HEAD_LENGTH - 1, y=0),  # line stops at the head's back
    )


def _closed_triangle(identifier: str) -> EndpointSymbol:
    """The plain hollow specialization head: same slender 2:1 geometry as
    the headless markers (was ipyelk's 45-degree ``StraightArrow``)."""

    return EndpointSymbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=Path.from_list(
                    [(_HEAD_LENGTH, -_HEAD_HALF), (0, 0), (_HEAD_LENGTH, _HEAD_HALF)],
                    closed=True,
                )
            )
        ),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-_HEAD_LENGTH - 1, y=0),
    )


def _open_v(identifier: str) -> EndpointSymbol:
    """The open two-stroke V, sized like the headless markers (9x4 -- the
    vendored ``ThinArrow`` drew a smaller 6x3 head)."""

    return EndpointSymbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=Path.from_list([(_V_LENGTH, -_V_HALF), (0, 0), (_V_LENGTH, _V_HALF)])
            )
        ),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-1, y=0),
    )


def _filled_v(identifier: str) -> EndpointSymbol:
    """The FILLED flow arrowhead for port-attached flows (spec printed
    p.77): same slender V geometry, closed; the stylesheet binds its fill
    to the edge stroke (filled family, §2.0 rule 3)."""

    return EndpointSymbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=Path.from_list(
                    [(_V_LENGTH, -_V_HALF), (0, 0), (_V_LENGTH, _V_HALF)], closed=True
                )
            )
        ),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-_V_LENGTH - 1, y=0),
    )


def _pin_svg(with_arrow: bool) -> str:
    """Raw SVG for the flow pins, in endpoint-symbol space (line end at the
    origin = the node border, +x back along the edge).  The square
    straddles the border; the target-input pin adds a small FILLED
    arrowhead tight against the square's outer edge (errata E16).
    Explicit paints: white body, currentColor outline/arrow (the
    stylesheet binds currentColor to the edge stroke)."""

    half = _PIN_SIZE / 2
    bits = [
        f'<rect x="{-half:g}" y="{-half:g}" width="{_PIN_SIZE:g}" height="{_PIN_SIZE:g}" '
        f'rx="{_PIN_RX:g}" fill="#ffffff" stroke="currentColor" stroke-width="1.2"/>'
    ]
    if with_arrow:
        back = half + _FLOW_HEAD_LENGTH
        bits.insert(
            0,
            f'<path d="M {half:g},0 L {back:g},{-_FLOW_HEAD_HALF:g} '
            f'L {back:g},{_FLOW_HEAD_HALF:g} Z" fill="currentColor" stroke="none"/>',
        )
    return "".join(bits)


def _pin_symbol(identifier: str, with_arrow: bool) -> EndpointSymbol:
    reach = _PIN_SIZE / 2 + (_FLOW_HEAD_LENGTH if with_arrow else 0)
    return EndpointSymbol(
        identifier=identifier,
        element=Node(properties=NodeProperties(shape=SVG(use=_pin_svg(with_arrow)))),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-reach, y=0),
    )


def _portion_ball_svg() -> str:
    """Raw SVG for the portion-membership ball (filled, open-V notch on the
    line side; notch vertex at the ball center), in endpoint-symbol space:
    the ball's forward edge touches the origin (the whole-occurrence node
    border), the mouth opens back along the edge (+x)."""

    r = _BALL_RADIUS
    cx = r  # ball center; forward edge at the origin
    rad = math.radians(_BALL_MOUTH_DEG)
    px = cx + r * math.cos(rad)
    py = r * math.sin(rad)
    return (
        f'<path d="M {cx:g},0 L {px:.2f},{-py:.2f} A {r:g} {r:g} 0 1 0 {px:.2f},{py:.2f} Z" '
        f'fill="currentColor" stroke="none"/>'
    )


def _portion_ball(identifier: str) -> EndpointSymbol:
    return EndpointSymbol(
        identifier=identifier,
        element=Node(properties=NodeProperties(shape=SVG(use=_portion_ball_svg()))),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-_BALL_RADIUS, y=0),  # the line ends at the notch vertex
    )


def _alias_circle(identifier: str) -> EndpointSymbol:
    """The small hollow circle at the alias/unowned-membership referencing
    end, touching the node border (errata E18)."""

    r = _CIRCLE_RADIUS
    return EndpointSymbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=SVG(
                    use=(
                        f'<circle cx="{r:g}" cy="0" r="{r:g}" fill="#ffffff" '
                        f'stroke="currentColor" stroke-width="1.2"/>'
                    )
                )
            )
        ),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-2 * r, y=0),
    )


def _circle_plus(identifier: str) -> EndpointSymbol:
    """The circle-plus at the owned-membership OWNING namespace end,
    touching the node border (errata E18, spec printed p.26).  A TRUE
    circled plus: both cross strokes span the full diameter, endpoints ON
    the circle -- never a floating '+' inside the circle.  Hollow family:
    explicit white body, cross strokes in currentColor (bound to the edge
    stroke by the stylesheet, so selection recolors circle and cross)."""

    r = _CIRCLE_RADIUS
    return EndpointSymbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=SVG(
                    use=(
                        f'<circle cx="{r:g}" cy="0" r="{r:g}" fill="#ffffff" '
                        f'stroke="currentColor" stroke-width="1.2"/>'
                        f'<path d="M 0,0 L {2 * r:g},0 M {r:g},{-r:g} L {r:g},{r:g}" '
                        f'fill="none" stroke="currentColor" stroke-width="1.2"/>'
                    )
                )
            )
        ),
        symbol_offset=Point(x=-1, y=0),
        path_offset=Point(x=-2 * r, y=0),
    )


def _badge_symbol(identifier: str, form: str) -> Symbol:
    """An accept/send badge (filled top-left tag).  Explicit paints ride
    the geometry (like the tab and endpoint symbols): the badge is <use>
    shadow content, where the theme's ``.elklabel`` fill would otherwise
    leak in; the ``.accept-badge``/``.send-badge`` rules still drive the
    selection recolor (CSS beats presentation attributes)."""

    points = " ".join(
        f"{'M' if index == 0 else 'L'} {px:g},{py:g}"
        for index, (px, py) in enumerate(_badge_points(form, _BADGE_WIDTH, _BADGE_HEIGHT))
    )
    return Symbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=SVG(use=f'<path d="{points} Z" fill="#333333" stroke="none"/>')
            )
        ),
        width=_BADGE_WIDTH,
        height=_BADGE_HEIGHT,
    )


def _port_symbol(identifier: str, direction: str, side: str) -> Symbol:
    """A directed port square (spec Ports, printed p.59): the 10x10 square
    with the direction arrow drawn INSIDE.  One symbol per (direction,
    side): the arrow orients relative to the NODE INTERIOR -- an ``in``
    arrow points INTO the owning node on whatever border the port sits
    (render._port_arrow_d), never absolutely +x.  The square rect carries
    no paints, so it inherits the ``.elkport`` fill (white; the selection
    color when selected) and the owning node kind's stroke; the arrow is
    self-painted currentColor (bound per §2.0 rule 4)."""

    svg = (
        f'<rect x="0" y="0" width="{_PORT_SIZE:g}" height="{_PORT_SIZE:g}" '
        f'rx="{_PORT_RX:g}"/>'
        f'<path d="{_port_arrow_d(direction, _PORT_SIZE, side)}" fill="none" '
        f'stroke="currentColor" stroke-width="1.2"/>'
    )
    return Symbol(
        identifier=identifier,
        element=Node(properties=NodeProperties(shape=SVG(use=svg))),
        width=_PORT_SIZE,
        height=_PORT_SIZE,
    )


def _proxy_symbol(identifier: str) -> Symbol:
    """The proxy connector-end dot (spec printed p.67): a small FILLED
    ball riding the border of the shallowest drawn ancestor; currentColor
    body follows the owning node kind's stroke."""

    r = _PROXY_SIZE / 2
    return Symbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=SVG(
                    use=(
                        f'<circle cx="{r:g}" cy="{r:g}" r="{r - 0.5:g}" '
                        f'fill="currentColor" stroke="none"/>'
                    )
                )
            )
        ),
        width=_PROXY_SIZE,
        height=_PROXY_SIZE,
    )


def _tab_symbol(identifier: str) -> Symbol:
    """The package folder tab (spec printed p.24): a small closed
    rectangle riding the box's top-left -- ONE continuous folder
    silhouette, so the tab carries the package palette itself.

    Explicit paints are required (like the endpoint symbols): the tab is
    <use> shadow content, and the theme's ``.elklabel`` rule (label-color
    fill, stroke-width 0) would otherwise paint it as a borderless gray
    block.  The body takes the package fill directly; the outline is
    currentColor, bound to the package stroke by the ``.package-tab``
    rule -- and to the selection color when selected -- so the tab always
    recolors WITH the box border."""

    style = _NODE_STYLES["sysml-package"]
    svg = (
        f'<path d="M 0,0 L {_TAB_WIDTH:g},0 L {_TAB_WIDTH:g},{_TAB_HEIGHT:g} '
        f'L 0,{_TAB_HEIGHT:g} Z" fill="{style["fill"]}" stroke="currentColor" '
        f'stroke-width="1"/>'
    )
    return Symbol(
        identifier=identifier,
        element=Node(properties=NodeProperties(shape=SVG(use=svg))),
        width=_TAB_WIDTH,
        height=_TAB_HEIGHT,
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
    open two-stroke V of transitions and successions.  ``flow-source-pin``
    / ``flow-target-pin`` are the flow-connection border squares (the
    target pin carries the filled direction arrowhead), ``portion-ball``
    the notched portion-membership ball, ``alias-circle`` the hollow
    unowned-membership circle, ``owned-circle-plus`` the true circled plus
    at the owned-membership owning end.  ``flow-arrow`` is the filled V
    for flows attached to drawn port squares; ``port-in-west`` /
    ``port-out-east`` / ``port-inout-north`` / ... draw the boundary port
    square with its direction arrow oriented for the border side it rides
    (in = INTO the node, out = OUT of it, from whichever side),
    ``port-proxy`` the filled proxy-connection dot, and ``package-tab``
    the folder tab riding package boxes.  ``accept-badge`` / ``send-badge``
    are the
    filled top-left action-box tags.  All heads share the slender 2:1
    proportions of the headless markers (single-sourced in render.py).
    """

    return SymbolSpec().add(
        _closed_triangle("generalization"),
        _open_v("arrow"),
        _filled_v("flow-arrow"),
        _adorned_triangle("generalization-colon", "colon"),
        _adorned_triangle("generalization-tick", "tick"),
        _adorned_triangle("generalization-dcolon", "dcolon"),
        Rhomb("composition", r=6),
        Rhomb("aggregation", r=6),
        _pin_symbol("flow-source-pin", with_arrow=False),
        _pin_symbol("flow-target-pin", with_arrow=True),
        _portion_ball("portion-ball"),
        _alias_circle("alias-circle"),
        _circle_plus("owned-circle-plus"),
        _badge_symbol("accept-badge", "accept"),
        _badge_symbol("send-badge", "send"),
        *(
            _port_symbol(f"port-{direction}-{side.lower()}", direction, side)
            for direction in ("in", "out", "inout")
            for side in ("WEST", "EAST", "NORTH", "SOUTH")
        ),
        _proxy_symbol("port-proxy"),
        _tab_symbol("package-tab"),
    )


def _finish(
    root: Node,
    style: dict | None = None,
    direction: str | None = None,
    toolbar: bool = True,
    layout: dict[str, str] | None = None,
    routing: str = "orthogonal",
) -> Any:
    root.layoutOptions = dict(_ROOT_LAYOUT)
    if direction:
        root.layoutOptions["elk.direction"] = direction
    if layout:
        root.layoutOptions.update(layout)
    # ELK does NOT inherit layered spacing through INCLUDE_CHILDREN
    # hierarchy levels: a compound node's contents are spaced by ITS
    # layoutOptions or the elkjs defaults (edge channels then land 10px
    # from the node border -- inside every arrowhead's footprint, so the
    # shaft visibly entered the triangle's side and shaft adornments
    # floated off the turned line).  Restate the endpoint-glyph clearance
    # per level; pack grids keep their deliberately tighter values.
    for node in _walk_nodes(root):
        if node is not root and node.children:
            node.layoutOptions.setdefault(
                "elk.layered.spacing.edgeNodeBetweenLayers", f"{_EDGE_END_CLEARANCE:g}"
            )
    # edge routing (orthogonal / polyline / splines): restated per
    # hierarchy level for the same INCLUDE_CHILDREN reason; the toolbar's
    # EdgeRoutingTool re-applies it live through the same helper
    apply_routing(root, routing)
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
    membership: str = "nested",
    annotations: bool = False,
    toolbar: bool = True,
    routing: str = "orthogonal",
) -> Any:
    """Containment structure with specialization/typing/connection edges.

    ``composition="defs"`` (the default) draws definition-level membership
    edges -- a filled diamond at the whole end for composite part/item
    members, a hollow diamond for referential (``ref``) members, role name
    on the line, multiplicity at the part end -- per the SysML v2 Parts
    notation; ``composition="none"`` suppresses them.  Flow / binding /
    dependency / satisfy / alias / portion notation is always drawn when
    both ends resolve to drawn nodes (see the module docstring).

    ``membership="nested"`` (the default) draws each package's owned
    members NESTED inside its box -- the spec's primary presentation and
    exactly the pre-0.8 output.  ``membership="edges"`` draws the spec's
    ALTERNATIVE presentation instead (printed p.26, errata E18): packages
    do not swallow their drawn members -- every member becomes a SIBLING
    node and a solid owned-membership edge runs from the owning package,
    carrying a true circle-plus at the owning end.  (Siblings keep ELK's
    layered layout stable: an edge between a package and a node nested
    inside it is the ancestor<->descendant case the layout mishandles.)
    Membership edges are containment presentation, not relationship
    edges, so ``show_relationships=False`` keeps them.

    Port usages owned by a drawn definition/usage box render as the
    spec's boundary squares (10x10, straddling the border, ``name :
    Type`` label INSIDE the box next to the square -- where the spec's
    part figures write it -- direction arrow inside the square when the
    port
    definition's directed features agree on one); interface / connection
    / binding / flow ends then attach square-to-square, and connector
    ends naming UNDRAWN nested features draw the spec's proxy dot on the
    shallowest drawn ancestor (printed p.67).  Only nodes that own drawn
    ports opt into ELK port handling -- everything else keeps the exact
    pre-port layout path.

    ``annotations=True`` (default off, to keep existing diagrams
    uncluttered) additionally draws comment/documentation notes -- the
    folded-corner box with a dashed anchor line (no endpoint glyph) to
    each annotated element (spec printed pp.20-21) -- and «@Type» /
    «#keyword» metadata adornments on annotated nodes.

    ``toolbar=False`` keeps ipyelk's stock text-button toolbar instead of
    the compact icon+search one (:mod:`longeron.toolbar`).

    ``routing`` picks the ELK edge routing style -- ``"orthogonal"`` (the
    default), ``"polyline"`` or ``"splines"`` -- for headless renders and
    the initial widget; the toolbar's routing button cycles it live.
    """

    if membership not in ("nested", "edges"):
        raise ValueError(f"membership must be 'nested' or 'edges', not {membership!r}")
    builder = _StructureBuilder(
        element, show_attributes, composition=composition, membership=membership
    )
    root = builder.build()
    if show_relationships:
        builder.add_relationship_edges(root)
    if annotations:
        builder.add_annotations(root)
    builder.pack_components(root)
    _size_compartment_rows(root)
    # package tabs ride flush with the box top (outside icon labels; the
    # spacing option applies per hierarchy level, so the package nodes
    # restate it for their nested packages)
    return _finish(root, toolbar=toolbar, layout={"elk.spacing.labelNode": "0"}, routing=routing)


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
        membership: str = "nested",
    ):
        self.element = element
        self.show_attributes = show_attributes
        self.composition = composition
        self.membership = membership
        owner: M.Element = element
        while owner.owner is not None:
            owner = owner.owner
        self.model = owner if isinstance(owner, M.Model) else M.Model()
        self.interp = Interpreter(self.model)
        self.nodes: dict[int, Node] = {}
        # boundary port squares by model element id (spec Ports): connector
        # ends resolve to these before nodes
        self.ports: dict[int, Port] = {}
        # proxy connector-end dots, deduplicated per (owner node, residual)
        self._proxies: dict[tuple[int, str], Port] = {}
        # membership="edges": members unnested into diagram-root siblings,
        # and the (owning package node, member node) pairs to connect
        self._unnested: list[Node] = []
        self._owned: list[tuple[Node, Node]] = []

    def build(self) -> Node:
        root = Node(properties=NodeProperties(cssClasses="sysml-root"))
        roots = self.element.members if isinstance(self.element, M.Model) else [self.element]
        for member in roots:
            child = self._visit(member)
            if child is not None:
                root.children.append(child)
        # membership="edges" (errata E18, spec printed p.26): packages did
        # not swallow their drawn members -- every member becomes a SIBLING
        # node at the diagram root, joined to its owning package by a solid
        # owned-membership edge with the circle-plus at the owning end.
        # These edges are containment presentation (they replace nesting),
        # so they draw regardless of show_relationships.
        root.children.extend(self._unnested)
        for owner_node, member_node in self._owned:
            root.edges.append(_edge(owner_node, member_node, "sysml-edge-owned"))
        return root

    def _visit(self, element: M.Element) -> Node | None:
        if isinstance(element, M.Package):
            node = _node(element, element.label, "sysml-package", "package")
            self._add_package_tab(node)
            for member in element.members:
                child = self._visit(member)
                if child is None:
                    continue
                if self.membership == "edges":
                    self._unnested.append(child)
                    self._owned.append((node, child))
                else:
                    node.children.append(child)
        elif isinstance(element, M.Definition):
            stereotype = _KIND_STEREOTYPES.get(element.kind, element.kind)
            if element.is_individual:  # «individual part def» (errata N15)
                stereotype = f"individual {stereotype}".strip()
            node = _node(element, element.label, "sysml-definition", f"{stereotype} def".strip())
            self._fill_features(node, element)
        elif isinstance(element, M.Usage) and element.kind in (
            "part",
            "item",
            "port",
            "action",
            "state",
            "occurrence",
            # «individual» / «timeslice» / «snapshot» occurrence boxes
            # (errata N15 keywords + the portion-membership row)
            "individual",
            "timeslice",
            "snapshot",
            # «actor» / «stakeholder» keyword-box form (errata N17: the
            # official alternative to the stick figure)
            "actor",
            "stakeholder",
            # «requirement» usage boxes: the ends of satisfy edges
            # (spec printed p.133 draws requirement USAGES as boxes)
            "requirement",
            "satisfy",
            # named allocations draw the spec's «allocation» box form
            # (printed p.79); anonymous `allocate a to b` draws the
            # «allocate» keyword edge instead
            "allocation",
        ):
            if element.kind in ("satisfy", "allocation") and not element.name:
                # the anonymous shorthands (`satisfy R by sys;`,
                # `allocate a to b;`) draw as keyword edges, not boxes
                return None
            stereotype = _KIND_STEREOTYPES.get(element.kind, element.kind)
            node = _node(element, _usage_title(element), "sysml-usage", stereotype)
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
            if member.kind == "port":
                # boundary squares straddling this box's border (spec
                # Ports, printed p.59) -- never nested child boxes
                self._add_boundary_port(node, member)
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
        self._finalize_ports(node)

    def _add_package_tab(self, node: Node) -> None:
        """The package folder tab (spec printed p.24): a fixed-size icon
        label pinned OUTSIDE at the top-left, flush with the box top (ELK
        reserves the space, so nothing overlaps in either pipeline).  The
        single-space text keeps ELK's label placement engaged (it skips
        empty labels); nothing renders it."""

        tab = Label(text=" ")
        tab.properties = LabelProperties(
            cssClasses="sysml-tab",
            shape=Icon(use="package-tab", width=_TAB_WIDTH, height=_TAB_HEIGHT),
        )
        tab.layoutOptions = {"nodeLabels.placement": "H_LEFT V_TOP OUTSIDE"}
        node.labels.insert(0, tab)
        # label-node spacing applies per hierarchy level: restate it for
        # packages nested inside this one
        node.layoutOptions["elk.spacing.labelNode"] = "0"

    def _port_direction(self, element: M.Usage) -> str | None:
        """The arrow drawn inside a port square (spec printed p.59).

        The language has no direction syntax on ports themselves; the
        spec's figures derive the arrow from the port DEFINITION's
        directed features: all ``in`` draws the inward arrow, all ``out``
        the outward one, anything mixed or ``inout`` the double-headed
        form, none draws a plain square.  Conjugated ports (``~T``) flip
        in/out (spec 7.12.3: conjugation reverses directed features).
        """

        if not element.types:
            return None
        type_name = element.types[0]
        conjugated = type_name.startswith("~")
        try:
            found = self.interp.resolver.resolve(type_name.lstrip("~"), element.owner or self.model)
        except Exception:
            return None
        if not isinstance(found, M.Definition):
            return None
        directions = {
            member.direction
            for member in found.members
            if isinstance(member, M.Usage) and member.direction in ("in", "out", "inout")
        }
        if not directions:
            return None
        if directions == {"in"}:
            direction = "in"
        elif directions == {"out"}:
            direction = "out"
        else:
            direction = "inout"
        if conjugated and direction != "inout":
            direction = "in" if direction == "out" else "out"
        return direction

    def _add_boundary_port(self, owner: Node, element: M.Usage, prefix: str = "") -> None:
        """Draw a port usage as the spec's small square ON the owning
        node's border (plan P1/P2/P3): 10x10, straddling the border via a
        negative border offset, ``name : Type`` label placed INSIDE the
        box by
        ELK, direction arrow inside the square, conjugation textual
        (``~T`` in the label -- the spec's figures draw conjugated squares
        unshaded, printed p.76).  Nested ports flatten onto the same
        border with dotted labels (plan P5's documented fallback)."""

        direction = self._port_direction(element)
        css = "sysml-port" + (f" sysml-port-{direction}" if direction else "")
        port = Port(
            width=_PORT_SIZE,
            height=_PORT_SIZE,
            layoutOptions={"elk.port.borderOffset": f"{-_PORT_SIZE / 2:g}"},
            properties=PortProperties(cssClasses=css),
        )
        # the direction arrow's SYMBOL is side-dependent (it orients
        # relative to the node interior), so _finalize_ports assigns it
        # together with the pinned side
        if element.qualified_name:
            port.id = element.qualified_name
        text = prefix + _usage_title(element)
        label = _label(text)
        shape = label.properties.get_shape()
        shape.width, shape.height = _measure(text)
        port.labels = [label]
        owner.add_port(port)
        self.ports[id(element)] = port
        for member in element.members:
            if isinstance(member, M.Usage) and member.kind == "port":
                self._add_boundary_port(owner, member, prefix=f"{prefix}{element.label}.")

    def _finalize_ports(self, node: Node) -> None:
        """Opt the node into ELK port handling -- ONLY nodes that own drawn
        ports leave the pre-port layout path.  Port labels place INSIDE
        the owning box, adjacent to the square (the spec's part figures --
        printed pp.59/75/77 -- all write ``name : Type`` within the part
        body), and the box sizes around them (PORT_LABELS).  Direction
        arrows need known orientations, so any directed square pins every
        side (in = WEST, everything else EAST) and takes the symbol
        oriented for that side -- the arrow points INTO/OUT OF the node
        from whatever border it rides; nodes with only plain squares keep
        FREE constraints for ELK's routing."""

        drawn = [port for port in node.ports if port.properties.cssClasses]
        if not drawn:
            return
        node.layoutOptions["elk.portLabels.placement"] = "INSIDE"
        node.layoutOptions["nodeSize.constraints"] = "NODE_LABELS PORTS PORT_LABELS MINIMUM_SIZE"
        if any(" sysml-port-" in f" {port.properties.cssClasses}" for port in drawn):
            node.layoutOptions["elk.portConstraints"] = "FIXED_SIDE"
            for port in drawn:
                css = port.properties.cssClasses or ""
                direction = next(
                    (d for d in ("inout", "in", "out") if f"sysml-port-{d}" in css), None
                )
                side = "WEST" if direction == "in" else "EAST"
                port.layoutOptions["elk.port.side"] = side
                if direction:
                    port.properties.shape = PortShape(use=f"port-{direction}-{side.lower()}")

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
                # portion usages (timeslice/snapshot) draw the portion-
                # membership glyph INSTEAD of a plain typing edge to their
                # portioned occurrence: solid line, filled ball with an
                # open-V notch at the WHOLE end (errata new row; spec
                # printed p.52, BNF p.205)
                portion_target: Node | None = None
                if element.portion_kind and element.types:
                    portion_target = self._resolve_node(element.types[0].lstrip("~"), element)
                for type_name in element.types:
                    target = self._resolve_node(type_name.lstrip("~"), element)
                    if target is None:
                        continue
                    if portion_target is not None and target is portion_target:
                        # ball rides the TARGET (whole-occurrence) end
                        root.edges.append(_edge(node, target, "sysml-edge-portion"))
                        portion_target = None  # one portion edge only
                        continue
                    # feature typing is a Specialization (KerML): SOLID
                    # line, hollow triangle at the definition, colon
                    # dots on the shaft (spec 8.2.3 printed p.200)
                    root.edges.append(_edge(node, target, "sysml-edge-typed"))
                # the rest of the specialization family: same solid line
                # and hollow head, told apart by the shaft adornment (the
                # spec draws NO keyword labels on these edges).  A satisfy
                # usage's satisfied requirement is a REFERENCE subsetting
                # whichever list the builder parked it in (spec printed
                # p.133 draws the double-colon dots).
                subsets_css = (
                    "sysml-edge-references"
                    if isinstance(element, M.SatisfyUsage)
                    else "sysml-edge-subsets"
                )
                for names, css in (
                    (element.redefines, "sysml-edge-redefines"),
                    (element.subsets, subsets_css),
                    ([element.references] if element.references else [], "sysml-edge-references"),
                ):
                    for name in names:
                        target = self._resolve_feature_node(name, element)
                        if target is not None:
                            root.edges.append(_edge(node, target, css))
        # relationship members owned by anything we visited: connections,
        # bindings, interfaces, allocations, flows, dependencies, anonymous
        # satisfies, aliases
        for element in list(self.nodes_elements()):
            for member in element.members if isinstance(element, M.Namespace) else []:
                if id(member) in self.nodes:
                    continue
                if isinstance(member, (M.ConnectionUsage, M.BindingConnector, M.InterfaceUsage)):
                    self._connect_ends(root, member)
                elif isinstance(member, M.AllocationUsage):
                    self._add_allocate_edges(root, member)
                elif isinstance(member, M.FlowUsage) and member.kind == "flow":
                    self._add_flow_edge(root, member)
                elif isinstance(member, M.SatisfyUsage):
                    self._add_satisfy_edges(root, member)
                elif isinstance(member, M.Dependency):
                    self._add_dependency_edges(root, member)
                elif isinstance(member, M.Alias):
                    self._add_alias_edge(root, element, member)

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
        binding = isinstance(element, M.BindingConnector)
        css = "sysml-edge-binding" if binding else "sysml-edge-connect"
        # ends resolve to boundary PORT squares when drawn (interfaces run
        # square-to-square, spec printed p.75); ends naming UNDRAWN nested
        # features draw the proxy dot on the shallowest drawn ancestor
        # (spec printed p.67)
        endpoints: list[Node | Port] = []
        for end in ends:
            anchor, residual = self._resolve_end_anchor(end.target, element)
            if anchor is None:
                return  # an unresolvable end draws nothing (as before)
            if residual and isinstance(anchor, Node):
                anchor = self._add_proxy_port(anchor, residual)
            endpoints.append(anchor)
        if len(endpoints) < 2:
            return
        label = element.label if element.name else None
        if not binding and len(endpoints) >= 3:
            # `connect (a, b, c)`: the spec's n-ary junction form
            self._add_nary_connection(root, element, ends, endpoints)
            return
        if not binding and self._connection_direction(element):
            # 'connection (with direction indication)' (spec printed
            # p.66): open-V head at the target end, name : Type label
            css = "sysml-edge-directed"
            if element.name and element.types:
                label = f"{element.label} : {element.types[0]}"
        for (end_a, source), (end_b, target) in itertools.pairwise(
            zip(ends, endpoints, strict=True)
        ):
            edge = _edge(source, target, css, text=label)
            if binding:
                # the '=' glyph rides the solid line mid-span (errata
                # E15) -- a centered, pre-sized label like any other
                _add_center_label(edge, "=")
            # cross multiplicities render near the ends they constrain
            if end_a.multiplicity is not None:
                _add_end_multiplicity(edge, end_a.multiplicity, "TAIL")
            if end_b.multiplicity is not None:
                _add_end_multiplicity(edge, end_b.multiplicity, "HEAD")
            root.edges.append(edge)

    def _connection_direction(self, element: M.Usage) -> bool:
        """True when the connection's DEFINITION declares directed ends.

        The spec's 'connection (with direction indication)' (printed p.66)
        has textual notation identical to the undirected form -- the only
        model signal is the definition's end NAMES (``sourceEnd`` /
        ``targetEnd`` in the spec's own example; ``source``/``target``
        accepted too).  Connector ends bind to definition ends in
        declaration order, so the arrow rides the second (target) end.
        """

        if not getattr(element, "types", None):
            return False
        try:
            found = self.interp.resolver.resolve(
                element.types[0].lstrip("~"), element.owner or self.model
            )
        except Exception:
            return False
        if not isinstance(found, M.Definition):
            return False
        def_ends = [m for m in found.members if isinstance(m, M.Usage) and m.is_end]
        if len(def_ends) != 2:
            return False
        names = [(m.name or "").lower() for m in def_ends]
        return names[0].startswith("source") and names[1].startswith("target")

    def _add_nary_connection(
        self,
        root: Node,
        element: M.Usage,
        ends: Sequence[M.ConnectorEnd],
        endpoints: Sequence[Node | Port],
    ) -> None:
        """``connect (a, b, c)`` -- the spec's n-ary form (printed p.66): a
        small filled junction dot where the end lines meet, the connection
        label beside it, end multiplicities near the ends they constrain
        (reusing the n-ary dependency machinery, connector-family gray)."""

        text = element.label if element.name else None
        if text and element.types:
            text = f"{text} : {element.types[0]}"
        junction = _glyph_node(element, text, "sysml-connjunction", _JUNCTION_SIZE, _JUNCTION_SIZE)
        _add_center_anchor(junction)
        owner_node = self.nodes.get(id(element.owner)) if element.owner is not None else None
        (owner_node or root).children.append(junction)
        first, *rest = zip(ends, endpoints, strict=True)
        edge = _edge(first[1], _anchor(junction, "in"), "sysml-edge-connect")
        if first[0].multiplicity is not None:
            _add_end_multiplicity(edge, first[0].multiplicity, "TAIL")
        root.edges.append(edge)
        for end, endpoint in rest:
            edge = _edge(_anchor(junction, "out"), endpoint, "sysml-edge-connect")
            if end.multiplicity is not None:
                _add_end_multiplicity(edge, end.multiplicity, "HEAD")
            root.edges.append(edge)

    def _add_allocate_edges(self, root: Node, alloc: M.AllocationUsage) -> None:
        """Anonymous ``allocate a to b`` (spec printed p.79): a solid line
        with an open-V arrow and the «allocate» keyword, source to target,
        in the dependency/requirement family hue.  Named allocation usages
        draw as «allocation» boxes instead (the spec's node form) -- they
        are in ``self.nodes`` and never reach this method."""

        if alloc.name:
            return
        endpoints = []
        for end in alloc.ends:
            anchor, _residual = self._resolve_end_anchor(end.target, alloc)
            if anchor is None:
                return
            endpoints.append(anchor)
        for source, target in itertools.pairwise(endpoints):
            root.edges.append(
                _edge(
                    source,
                    target,
                    "sysml-edge-allocate",
                    text="\u00aballocate\u00bb",
                    text_css="sysml-stereotype",
                )
            )

    def _lookup(self, element: M.Element) -> Node | Port | None:
        """The drawn thing for a model element: its boundary port square
        when it has one, else its node."""

        return self.ports.get(id(element)) or self.nodes.get(id(element))

    def _contains(self, anchor: Node | Port, candidate: Node | Port) -> bool:
        """Whether ``candidate`` is drawn at or under the node that hosts
        ``anchor`` -- the test that keeps connector ends from wandering
        into definition boxes (`connect part2.part4 ...` must NOT anchor
        on Part2's member box; it draws the proxy dot instead)."""

        base = anchor if isinstance(anchor, Node) else anchor.get_parent()
        if not isinstance(base, Node):
            return False
        if isinstance(candidate, Port):
            owner = candidate.get_parent()
            return any(owner is node for node in _walk_nodes(base))
        return candidate is not base and any(candidate is node for node in _walk_nodes(base))

    def _resolve_end_anchor(
        self, name: str, context: M.Element
    ) -> tuple[Node | Port | None, list[str]]:
        """Resolve a dotted connector-end path to its drawn endpoint.

        Walks the path segment by segment, descending only through things
        actually DRAWN inside the current anchor (nested boxes, boundary
        ports).  Returns the deepest such endpoint plus the residual
        segments that could not be descended -- a non-empty residual is
        the proxy-connection case (spec printed p.67).
        """

        parts = name.split(".")
        try:
            found = self.interp.resolver.resolve(parts[0], context.owner or self.model)
        except Exception:
            return None, []
        anchor = self._lookup(found)
        residual: list[str] = []
        for index, part in enumerate(parts[1:], start=1):
            try:
                found = self.interp.resolver.resolve(part, found)
            except Exception:
                residual.extend(parts[index:])
                break
            candidate = self._lookup(found)
            if anchor is None:
                if candidate is not None:
                    anchor = candidate
            elif candidate is not None and not residual and self._contains(anchor, candidate):
                anchor = candidate
            else:
                residual.append(part)
        return anchor, residual

    def _add_proxy_port(self, owner: Node, residual: list[str]) -> Port:
        """The proxy-connection dot (spec printed p.67): a small FILLED
        ball ON the border of the shallowest drawn ancestor, labeled with
        the residual path (``.part4``) INSIDE the box, adjacent to the dot
        -- exactly where the spec figure writes it.  Deduplicated per
        (node, path), so several connectors to one nested feature share a
        dot."""

        text = "." + ".".join(residual)
        key = (id(owner), text)
        existing = self._proxies.get(key)
        if existing is not None:
            return existing
        port = Port(
            width=_PROXY_SIZE,
            height=_PROXY_SIZE,
            layoutOptions={"elk.port.borderOffset": f"{-_PROXY_SIZE / 2:g}"},
            properties=PortProperties(
                cssClasses="sysml-port-proxy", shape=PortShape(use="port-proxy")
            ),
        )
        if owner.layoutOptions.get("elk.portConstraints") == "FIXED_SIDE":
            port.layoutOptions["elk.port.side"] = "EAST"
        label = _label(text)
        shape = label.properties.get_shape()
        shape.width, shape.height = _measure(text)
        port.labels = [label]
        owner.add_port(port)
        owner.layoutOptions["elk.portLabels.placement"] = "INSIDE"
        owner.layoutOptions["nodeSize.constraints"] = "NODE_LABELS PORTS PORT_LABELS MINIMUM_SIZE"
        self._proxies[key] = port
        return port

    def _add_flow_edge(self, root: Node, flow: M.FlowUsage) -> None:
        """A flow connection (errata E16/M1): solid line from a small square
        source-output pin to a small square target-input pin, small FILLED
        arrowhead at the target pin, payload item labels near each end.
        Ends resolving to DRAWN boundary ports attach to the square itself
        (the port IS the pin, spec printed p.77) and the edge drops the
        marker pins, keeping only the filled arrowhead."""

        if not flow.source or not flow.target_end:
            return
        source, _sres = self._resolve_end_anchor(flow.source, flow)
        target, _tres = self._resolve_end_anchor(flow.target_end, flow)
        if source is None or target is None or source is target:
            return
        ported = isinstance(source, Port) or isinstance(target, Port)
        css = "sysml-edge-portflow" if ported else "sysml-edge-flow"
        edge = _edge(source, target, css, text=flow.name or None)
        if flow.payload:  # payload item labels near BOTH ends (spec p.81)
            _add_end_label(edge, flow.payload, "TAIL")
            _add_end_label(edge, flow.payload, "HEAD")
        root.edges.append(edge)

    def _add_satisfy_edges(self, root: Node, satisfy: M.SatisfyUsage) -> None:
        """The shorthand satisfy (``satisfy R by sys;``): a plain solid line
        with an open-V arrow and the «satisfy» keyword from the satisfying
        element to the requirement (spec printed p.133; BNF keyword-arrow
        convention).  Named satisfy usages draw as boxes instead, with the
        reference-subsetting edge (handled by the specialization family)."""

        if not satisfy.by:
            return
        source = self._resolve_node(satisfy.by, satisfy)
        if source is None:
            return
        names = [*satisfy.subsets, *([satisfy.references] if satisfy.references else [])]
        for name in names:
            target = self._resolve_node(name, satisfy)
            if target is not None and target is not source:
                root.edges.append(
                    _edge(
                        source,
                        target,
                        "sysml-edge-satisfies",
                        text="\u00absatisfy\u00bb",
                        text_css="sysml-stereotype",
                    )
                )

    def _add_dependency_edges(self, root: Node, dep: M.Dependency) -> None:
        """Dependencies (errata E8): dashed open-V client->supplier with the
        optional ``(rel-name)`` label; n-ary dependencies radiate dashed
        links from a small filled junction dot (client links plain,
        supplier links arrowed)."""

        clients = [self._resolve_node(name, dep) for name in dep.clients]
        suppliers = [self._resolve_node(name, dep) for name in dep.suppliers]
        clients = [node for node in clients if node is not None]
        suppliers = [node for node in suppliers if node is not None]
        if not clients or not suppliers:
            return
        label = f"({dep.name})" if dep.name else None
        if len(clients) == 1 and len(suppliers) == 1:
            root.edges.append(_edge(clients[0], suppliers[0], "sysml-edge-dependency", text=label))
            return
        junction = _glyph_node(dep, label, "sysml-junction", _JUNCTION_SIZE, _JUNCTION_SIZE)
        _add_center_anchor(junction)
        # lay the dot out inside the namespace that owns the dependency
        # (falling back to the diagram root)
        owner_node = self.nodes.get(id(dep.owner)) if dep.owner is not None else None
        (owner_node or root).children.append(junction)
        for client in clients:
            root.edges.append(_edge(client, _anchor(junction, "in"), "sysml-edge-depclient"))
        for supplier in suppliers:
            root.edges.append(_edge(_anchor(junction, "out"), supplier, "sysml-edge-dependency"))

    def _add_alias_edge(self, root: Node, owner: M.Element, alias: M.Alias) -> None:
        """Membership (unowned/alias member, errata E18 official v2 form):
        solid line, small HOLLOW circle at the referencing namespace end,
        alias name as the edge label.  (The owned-member circle-plus form
        is the ``membership="edges"`` presentation -- by default longeron
        shows owned membership as nesting, the spec's primary form, so no
        cross-namespace owned-member edge exists to decorate.)"""

        owner_node = self.nodes.get(id(owner))
        if owner_node is None or not alias.target:
            return
        try:
            found = self.interp.resolver.resolve(alias.target, owner)
        except Exception:
            return
        target = self.nodes.get(id(found))
        if target is None or target is owner_node:
            return
        inside = {id(child) for child in _walk_nodes(owner_node)}
        if id(target) in inside:  # nesting already shows the membership
            return
        root.edges.append(_edge(owner_node, target, "sysml-edge-alias", text=alias.name))

    # -- annotations (opt-in) --------------------------------------------------

    def add_annotations(self, root: Node) -> None:
        """The annotation layer (``annotations=True``): comment and
        documentation elements as folded-corner note boxes with a DASHED
        anchor line -- no endpoint glyph -- to each annotated element
        (spec printed pp.20-21), plus «@Type» / «#keyword» metadata
        adornments on annotated nodes (spec Metadata, printed p.157).

        Notes are placed as SIBLINGS of their (first) anchor target --
        never inside it -- so anchor edges stay ordinary sibling edges
        (an edge into one's own ancestor is the case ELK's layered
        algorithm mishandles)."""

        parents: dict[int, Node] = {}
        for node in _walk_nodes(root):
            for child in node.children:
                parents[id(child)] = node
        for element in list(self.nodes_elements()):
            owner_node = self.nodes[id(element)]
            if element.metadata:  # '#keyword' prefix metadata
                for keyword in reversed(element.metadata):
                    owner_node.labels.insert(
                        0, _label(f"\u00ab#{keyword}\u00bb", "sysml-stereotype")
                    )
            if not isinstance(element, M.Namespace):
                continue
            for member in element.members:
                if isinstance(member, M.Comment):
                    targets = [
                        target
                        for name in member.about
                        if (target := self._lookup_annotated(name, member)) is not None
                    ]
                    self._add_note(root, parents, member, "comment", targets or [owner_node])
                elif isinstance(member, M.Documentation):
                    # documentation annotates its owning element
                    self._add_note(root, parents, member, "doc", [owner_node])
                elif isinstance(member, M.MetadataUsage) and member.typed_by:
                    targets = [
                        target
                        for name in member.about
                        if isinstance((target := self._lookup_annotated(name, member)), Node)
                    ] or [owner_node]
                    for target in targets:
                        target.labels.insert(
                            0, _label(f"\u00ab@{member.typed_by}\u00bb", "sysml-stereotype")
                        )

    def _lookup_annotated(self, name: str, context: M.Element) -> Node | Port | None:
        try:
            found = self.interp.resolver.resolve(name.split(".")[0], context.owner or self.model)
            for part in name.split(".")[1:]:
                found = self.interp.resolver.resolve(part, found)
        except Exception:
            return None
        return self._lookup(found)

    def _add_note(
        self,
        root: Node,
        parents: dict[int, Node],
        element: M.Comment | M.Documentation,
        keyword: str,
        targets: Sequence[Node | Port],
    ) -> None:
        """One note box -- the UML/SysML note silhouette: the top-right
        corner cut off PLUS the two short crease lines outlining the fold
        triangle (the dog-ear, spec printed pp.20-21) -- with the
        «comment»/«doc» keyword and the body capped for the canvas,
        anchored to each target by a dashed line with NO endpoint glyph.

        The geometry is pinned ONCE (pre-measured labels, fixed size, the
        exact leaf layout the headless renderer computes) and the outline
        + crease ride an explicit ``Path`` shape: the vendored ipyelk
        ``Comment`` view draws only the plain 5-sided polygon -- no
        crease -- so both pipelines share render._note_path_d instead."""

        body = element.text.splitlines()[0].strip() if element.text else ""
        if len(body) > 40:
            body = body[:39] + "\u2026"
        labels = [_label(f"\u00ab{keyword}\u00bb", "sysml-stereotype")]
        if body:
            labels.append(_label(body, "sysml-attribute"))
        measured = [
            (label, *_measure(label.text or "", label.properties.cssClasses or ""))
            for label in labels
        ]
        max_width = max(width for _, width, _ in measured)
        width = max(max_width + 16.0, 40.0)
        cursor = 5.0
        for label, label_width, label_height in measured:
            shape = label.properties.get_shape()
            shape.width, shape.height = label_width, label_height
            is_row = "sysml-attribute" in (label.properties.cssClasses or "")
            label.x = 8.0 if is_row else 8.0 + (max_width - label_width) / 2
            label.y = cursor
            label.layoutOptions = {"nodeLabels.placement": ""}  # pinned
            cursor += label_height
        height = cursor + 5.0  # notes hug their text
        note = Node(
            width=width,
            height=height,
            labels=labels,
            layoutOptions={
                "elk.nodeSize.constraints": "MINIMUM_SIZE",
                "elk.nodeSize.minimum": f"({width:g}, {height:g})",
            },
            properties=NodeProperties(
                cssClasses="sysml-note", shape=Path(use=_note_path_d(width, height))
            ),
        )
        if element.qualified_name:
            note.id = element.qualified_name
        host = parents.get(id(_endpoint_node(targets[0])), root)
        host.children.append(note)
        for target in targets:
            root.edges.append(_edge(note, target, "sysml-edge-anchor"))

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
            # port-anchored edges (interfaces, proxies, flows-to-ports)
            # connect their OWNING nodes for packing purposes
            touched.add(id(_endpoint_node(edge.source)))
            touched.add(id(_endpoint_node(edge.target)))

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
    routing: str = "orthogonal",
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
    shown.  ``toolbar=False`` keeps ipyelk's stock toolbar; ``routing``
    picks the edge routing style (orthogonal / polyline / splines).

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
    return _finish(root, toolbar=toolbar, routing=routing)


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


def action_diagram(
    action: M.Definition | M.Usage,
    *,
    lanes: Mapping[str, Sequence[str]] | bool | None = None,
    toolbar: bool = True,
    routing: str = "orthogonal",
) -> Any:
    """The succession control-flow graph the interpreter executes.

    Successions render dashed with open-V arrows and the behavior nodes
    use the spec glyphs (spec 8.2.3 printed p.227-228; figures pp.90-92):
    start = filled dot, done = bullseye, terminate = circle-X, fork/join =
    thick filled bar, decision/merge = empty rhombus, accept/send = the
    standard rounded action box with a filled top-left badge.  Control
    glyphs carry single convergence anchors: every incoming edge joins at
    one point and every outgoing edge leaves from one point (fork/join
    bars excepted -- their edges distribute along the bar, which is the
    bar's semantic).

    ``lanes`` (default off) partitions the flow into dashed-boundary
    «performer» swim lanes (spec "Perform Actions Swimlanes", printed
    p.90): pass a mapping of lane title -> step names, or ``True`` to
    derive lanes from ``perform`` targets (``perform part1.action1`` lands
    in lane ``part1``).  Lanes are content-sized dashed containers ordered
    left-to-right via ELK layer partitioning -- an honest approximation of
    the spec's full-height, shared-boundary lanes.  Steps in no lane stay
    outside (like the spec's start/done markers).  ``toolbar=False`` keeps
    ipyelk's stock toolbar; ``routing`` picks the edge routing style
    (orthogonal / polyline / splines).
    """

    root = Node(properties=NodeProperties(cssClasses="sysml-root"))

    plan = _succession_plan(list(action.members))
    steps: dict[str, Node] = {}
    elements: dict[str, M.Element] = {}

    def marker(name: str) -> Node:
        node = _add_anchor_ports(_marker_node(name))
        root.children.append(node)
        return node

    def done_node() -> Node:
        node = _glyph_node(
            None, "done", "sysml-final", _GLYPH_SIZE, _GLYPH_SIZE, shape=SVG(use=_bullseye_svg())
        )
        _add_anchor_ports(node)
        root.children.append(node)
        return node

    def link(source: Node, target: Node, css: str, text: str | None = None) -> Edge:
        # control glyphs converge their fans on single anchor points
        return _edge(_anchor(source, "out"), _anchor(target, "in"), css, text=text)

    if plan is not None:
        for name, element in plan.steps.items():
            node = _action_step_node(element, name)
            steps[name] = node
            elements[name] = element
            root.children.append(node)
        steps["start"] = marker("start")
        steps["done"] = done_node()
        if plan.initial in steps:
            root.edges.append(link(steps["start"], steps[plan.initial], "sysml-edge-succession"))
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
            root.edges.append(link(source, target, css, text=text))
    else:  # declaration order: a simple chain
        previous = marker("start")
        steps["start"] = previous
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
                root.edges.append(link(previous, node, "sysml-edge-succession"))
                steps[title] = node
                elements[title] = member
                previous = node
        steps["done"] = done_node()
        root.edges.append(link(previous, steps["done"], "sysml-edge-succession"))

    layout = None
    if lanes:
        layout = _apply_lanes(root, lanes, steps, elements)

    return _finish(root, direction="RIGHT", toolbar=toolbar, layout=layout, routing=routing)


def _lane_groups(
    lanes: Mapping[str, Sequence[str]] | bool,
    steps: dict[str, Node],
    elements: dict[str, M.Element],
) -> dict[str, list[str]]:
    """Lane title -> step names.  ``True`` derives lanes from perform
    targets: a ``perform part1.action1`` step performs in lane ``part1``
    (the target path minus its final segment)."""

    if lanes is True:
        derived: dict[str, list[str]] = {}
        for name, element in elements.items():
            if isinstance(element, M.PerformAction) and element.target and "." in element.target:
                lane = element.target.rsplit(".", 1)[0]
                derived.setdefault(lane, []).append(name)
        return derived
    if not isinstance(lanes, Mapping):  # lanes=False behaves like None
        return {}
    return {title: [n for n in names if n in steps] for title, names in lanes.items()}


def _apply_lanes(
    root: Node,
    lanes: Mapping[str, Sequence[str]] | bool,
    steps: dict[str, Node],
    elements: dict[str, M.Element],
) -> dict[str, str] | None:
    """Re-parent lane member steps into dashed «performer» containers and
    order the lanes left-to-right with ELK layer partitioning (start
    before the first lane, done after the last).  Returns the extra root
    layout options, or ``None`` when no lane has members."""

    groups = _lane_groups(lanes, steps, elements)
    groups = {title: names for title, names in groups.items() if names}
    if not groups:
        return None
    start, done = steps.get("start"), steps.get("done")
    if start is not None:
        start.layoutOptions["elk.partitioning.partition"] = "0"
    for index, (title, names) in enumerate(groups.items(), start=1):
        lane = _node(None, title, "sysml-lane", "performer")
        lane.layoutOptions["elk.partitioning.partition"] = str(index)
        members = {id(steps[name]) for name in names}
        lane.children = [child for child in root.children if id(child) in members]
        root.children = [child for child in root.children if id(child) not in members]
        root.children.append(lane)
    if done is not None:
        done.layoutOptions["elk.partitioning.partition"] = str(len(groups) + 1)
    return {"elk.partitioning.activate": "true"}


def _action_step_node(element: M.Element, title: str) -> Node:
    """A node for one action-flow step, using the spec glyph for control
    nodes, terminate, and the accept/send badge boxes; everything else is
    the standard rounded «keyword» step box.  Control glyphs (not bars)
    get single-point convergence anchors."""

    if isinstance(element, M.ControlNode):
        if element.kind in ("fork", "join"):
            # a thick filled bar, perpendicular to the (horizontal) flow;
            # fork vs join is topology, the glyph is identical; edges
            # deliberately distribute along the bar (no anchor ports)
            return _glyph_node(element, title, "sysml-ctrl-bar", _BAR_SHORT, _BAR_LONG)
        # decision vs merge: identical empty rhombus, role by topology
        return _add_anchor_ports(
            _glyph_node(
                element,
                title,
                "sysml-ctrl-diamond",
                _CTRL_DIAMOND_SIZE,
                _CTRL_DIAMOND_SIZE,
                shape=Diamond(),
            )
        )
    if isinstance(element, M.TerminateAction):
        return _add_anchor_ports(
            _glyph_node(
                element,
                element.name or "terminate",
                "sysml-terminate",
                _GLYPH_SIZE,
                _GLYPH_SIZE,
                shape=SVG(use=_terminate_svg()),
            )
        )
    if isinstance(element, (M.AcceptAction, M.SendAction)):
        form = "accept" if isinstance(element, M.AcceptAction) else "send"
        return _badged_step_box(_node(element, title, f"sysml-step sysml-step-{form}", form), form)
    kind = getattr(element, "kind", None) or type(element).__name__.replace("Action", "")
    return _node(element, title, "sysml-step", str(kind))


def _badged_step_box(node: Node, form: str) -> Node:
    """Pin the accept/send box geometry -- identically in BOTH pipelines.

    ELK's inside-label placer put the H_LEFT V_TOP badge at the very
    corner, protruding past the rounded corner arc (sysml-step rx), and
    centered the «accept»/«send» keyword row over the node width -- the
    top-left and top-center label cells share the top strip, so the row
    overlapped the badge.  So no label is left to ELK here: the badge sits
    at the corner inset (clear of the corner radius), the text rows start
    below the badge strip and center against the fixed box width -- the
    exact geometry the headless renderer draws (labels with empty
    placement sets are left untouched by ELK; the box size is pinned via
    MINIMUM_SIZE).  Fonts are pinned by the stylesheet (text.elklabel
    !important), so the _measure pre-sizing is faithful in the browser,
    like every pre-sized edge label and attribute row."""

    measured = [
        (label, *_measure(label.text or "", label.properties.cssClasses or ""))
        for label in node.labels
    ]
    # the box wraps the widest row with the usual 8px margins, but never
    # drops under the browser minimum (_NODE_LAYOUT elk.nodeSize.minimum)
    width = max(max(w for _, w, _ in measured) + 16.0, 60.0)
    cursor = _BADGE_STRIP
    for label, w, h in measured:
        shape = label.properties.get_shape()
        shape.width, shape.height = w, h  # pre-sized: skips the browser sizer
        label.x, label.y = (width - w) / 2, cursor
        label.layoutOptions = {"nodeLabels.placement": ""}  # pinned
        cursor += h
    height = max(cursor + 5.0, 44.0)
    badge = Label(text="")
    badge.properties = LabelProperties(
        cssClasses=f"sysml-badge sysml-badge-{form}",
        shape=Icon(use=f"{form}-badge", width=_BADGE_WIDTH, height=_BADGE_HEIGHT),
    )
    badge.x, badge.y = _BADGE_INSET_X, _BADGE_INSET_Y
    badge.layoutOptions = {"nodeLabels.placement": ""}
    node.labels.insert(0, badge)
    node.width, node.height = width, height
    node.layoutOptions = {
        "elk.nodeSize.constraints": "MINIMUM_SIZE",
        "elk.nodeSize.minimum": f"({width:g}, {height:g})",
    }
    return node


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
