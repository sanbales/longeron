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
  actors render as the spec's stick figure (name below; the
  ``actor_style="box"`` kwarg keeps the «actor» keyword-box alternative)
  while stakeholders render as «stakeholder» keyword boxes.
  View usages -- saved diagram recipes (:mod:`longeron.views`) -- draw
  as «view» keyword boxes.
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
``routing=`` kwarg on every view constructor for headless renders), an
orientation button that toggles the layout flow left-to-right /
top-to-bottom (the ``direction=`` kwarg seeds it), plus
a live search box that
highlights matching elements without touching the selection; pass
``toolbar=False`` to keep ipyelk's stock text buttons.  On STRUCTURE
views the collapse button CYCLES the selected node through the three
legal renditions -- nested child boxes, textual ``name : Type`` rows
under the 'parts' compartment header, and the name compartment alone --
while every compartment header carries its own fold twist (click the
header row to fold that one compartment); the :func:`level` /
:func:`fold` kernel API mirrors both (see :class:`CollapseTool`;
state/action views keep ipyelk's stock hide-the-children collapse).
Every widget
(with or without the compact toolbar) fits-and-centers itself ONCE when
its first layout arrives -- a small margin, never zoomed past 1:1 --
and later relayouts keep the user's viewport
(:class:`longeron.toolbar.AutoFitTool`).

Compartment rows cap their display width at ``max_label_width`` px
(default 480; a kwarg on every view constructor): overlong rows --
calculation/expression attributes are the usual offenders -- draw
END-ellipsized with the full text on the row's hover tooltip, so one
absurd expression no longer makes its whole node absurd.  Pass
``max_label_width=None`` to draw every row at full width.

Node ids are qualified names, so browser-side selections map back to model
elements: use :func:`on_select` to react to clicks.  Compartment ROWS are
first-class selectable elements too: each row is the textual projection of
a model element (an attribute usage, a part usage in the collapsed
presentation, a constraint...), carries that element's qualified name as
its id, and clicks on it flow through the SAME selection seam as node and
edge clicks.  Structure boxes group their rows into the spec's labeled
compartments -- separator rule + italic name ('attributes', 'parts', ...)
per 8.2.3.6 (printed p.199) -- and ``structure_diagram(parts="rows")``
swaps nested part boxes for the spec's collapsed textual presentation;
the same swap is available PER NODE, interactively (the toolbar's
collapse button cycles a selected box through expanded / partial /
name-only renditions; header twists fold single compartments) and from
the kernel (:func:`level` / :func:`fold`, or ``structure_diagram(
levels=..., folded=...)``), with connector edges re-anchoring on the
shrunken box as the spec's proxy dots (printed p.67).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

try:
    import ipyelk
    import ipywidgets as W
    import traitlets as T
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
    from ipyelk.pipes import flows as F
    from ipyelk.tools import ToggleCollapsedTool, Tool
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
    _ACTOR_HEIGHT,
    _ACTOR_WIDTH,
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
    _SYNTH_ID_PREFIX,
    _TAB_HEIGHT,
    _TAB_WIDTH,
    _TICK_HALF,
    _V_HALF,
    _V_LENGTH,
    _actor_geometry,
    _badge_points,
    _edge_end,
    _edge_start,
    _measure,
    _note_path_d,
    _port_arrow_d,
)
from .toolbar import AutoFitTool, _iconify, apply_direction, apply_routing, upgrade_toolbar

__all__ = [
    "SYSML_STYLE",
    "CollapseTool",
    "action_diagram",
    "diagram",
    "fold",
    "level",
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

# ---------------------------------------------------------------------------
# compartments (spec 8.2.3.6 printed p.199: a definition/usage node is its
# name compartment plus a compartment-stack; every labeled compartment opens
# with a full-width separator rule and its name in italics)
# ---------------------------------------------------------------------------

#: constraint rows group by their declared kind (spec printed pp.127, 132;
#: require/assume from the BNF, printed pp.243-244)
_CONSTRAINT_SECTIONS = {
    None: "constraints",
    "assert": "assert constraints",
    "require": "require constraints",
    "assume": "assume constraints",
}

#: usage kinds drawn as NESTED BOXES by default that collapse to textual
#: ``name : Type`` rows under ``structure_diagram(parts="rows")`` -- kind ->
#: the spec's compartment keyword (each cited at _SECTION_ORDER).  ``ref``
#: members row into the parts compartment with the ``ref`` prefix exactly
#: as the spec's parts figure writes them (printed p.60).
_ROW_SECTIONS = {
    "occurrence": "occurrences",
    "individual": "individuals",
    "timeslice": "timeslices",
    "snapshot": "snapshots",
    "item": "items",
    "part": "parts",
    "ref": "parts",
    "action": "actions",
    "state": "states",
    "requirement": "requirements",
    "satisfy": "satisfy requirements",
    "allocation": "allocations",
    "actor": "actors",
    "stakeholder": "stakeholders",
    "view": "views",
}

#: compartment order down the stack, following the spec's chapter order.
#: The keyword strings are the spec's own compartment names (printed-page
#: citations from the notation tables; BNF pages where no table exists).
_SECTION_ORDER = (
    "attributes",  # printed p.46
    "enums",  # printed p.48
    "occurrences",  # printed p.53
    "individuals",  # printed p.53
    "timeslices",  # printed p.53
    "snapshots",  # printed p.53
    "items",  # printed p.57
    "parts",  # printed p.60
    "directed features",  # printed p.62
    "allocations",  # printed p.79
    "actions",  # printed p.89
    "parameters",  # printed p.91
    "states",  # printed p.117
    "constraints",  # printed p.127
    "assert constraints",  # printed p.127
    "require constraints",  # BNF printed p.243
    "assume constraints",  # BNF printed p.244
    "requirements",  # printed p.132
    "satisfy requirements",  # printed p.132
    "subject",  # BNF printed p.244
    "actors",  # BNF printed p.244
    "stakeholders",  # BNF printed p.244
    "views",  # printed p.153
)

_SECTION_RANK = {name: rank for rank, name in enumerate(_SECTION_ORDER)}

#: the compartment-header twist glyphs (the explorer tree's twist
#: precedent): every header row opens with its fold affordance -- open
#: twist while the rows follow, closed twist while the compartment is
#: folded to its header alone.  Part of the header TEXT, so both
#: pipelines measure and draw it identically.
_TWIST_OPEN = "\u25be"
_TWIST_FOLDED = "\u25b8"

#: the three per-node collapse levels, in cycling order (each toolbar
#: click REDUCES detail one step, then wraps back to full): nested child
#: boxes -> textual rows -> the name compartment alone
_LEVELS = ("expanded", "partial", "collapsed")


def _section_of(header_text: str) -> str:
    """The compartment name behind a header label's text (strip the
    twist glyph the fold affordance prepends)."""

    return header_text[2:] if header_text[:1] in (_TWIST_OPEN, _TWIST_FOLDED) else header_text


def _collapsible(element: M.Element) -> bool:
    """Whether per-node collapse would ROW anything on this element: it
    owns members the collapsed presentation draws as textual rows (the
    :data:`_ROW_SECTIONS` kinds; anonymous satisfy/allocate shorthands
    keep their keyword-edge form).  Anything else -- packages above all
    -- collapses by the legacy hidden-children presentation instead
    (see :class:`PartsCollapseTool`)."""

    if not isinstance(element, (M.Definition, M.Usage)):
        return False
    return any(
        isinstance(member, M.Usage)
        and member.kind in _ROW_SECTIONS
        and (member.name or member.kind not in ("satisfy", "allocation"))
        for member in element.members
    )


def _section_header(section: str, folded: bool = False) -> Label:
    """A compartment header label: the spec writes the compartment name in
    italics, centered, right under the separator rule (8.2.3.6 printed
    p.199).  Snug (never pre-sized), so both pipelines center it; the
    separator rule itself is drawn from this label's position -- by the
    headless SVG writer and by the vendored browser node view (LOCAL
    PATCH 13), keyed on the ``sysml-comp-label`` class.

    The header opens with its FOLD affordance, the explorer tree's twist
    (open ``\u25be`` while the rows follow, closed ``\u25b8`` while the
    compartment is folded to its header alone); clicking the header row
    in the browser toggles the fold (:class:`CollapseTool`).  Headers
    are PRESENTATION artifacts, not model elements: they carry no
    qualified name and no ``selectable`` flag, so a header click can
    never enter the model-selection seam (the anonymous-row precedent).
    """

    twist = _TWIST_FOLDED if folded else _TWIST_OPEN
    return _label(f"{twist} {section}", "sysml-comp-label")


def _row_label(text: str, element: M.Element) -> Label:
    """A compartment ROW: the textual projection of a model element (an
    attribute usage, a part usage, a constraint...), and therefore a
    first-class selectable element.  The row carries the element's
    identity -- ``label.id`` is the qualified name, exactly like node ids
    -- and the ipyelk ``selectable`` flag, so the browser's select tool
    treats a row click like a node click: the same ``SelectAction``, the
    same selection-tool ids, the same :func:`on_select` resolution.
    Anonymous elements (no qualified name) draw but stay unselectable --
    there is no identity to select.  ``sysml-attribute`` keeps the row in
    every existing sizing/ellipsis contract; ``sysml-row`` is the
    hit-target marker the stylesheet keys hover/selection styling on."""

    label = _label(text, "sysml-attribute sysml-row")
    if element.qualified_name:
        label.id = element.qualified_name
        label.properties.selectable = True
    return label


#: the node-attached ADORNMENT contract (hover/selection parity, §2.0).
#:
#: Every glyph that rides a node -- the package folder tab, the accept/
#: send action badges, boundary port squares, proxy dots, and any future
#: adornment -- is constructed through ONE helper (:func:`_adornment_label`
#: / :func:`_adornment_port`), which stamps the ``sysml-adornment`` marker
#: class, and is styled by ONE derived rule family (see ``_sysml_style``)
#: keyed on that class, so the node and its adornments behave as a single
#: shape in every interactive state BY CONSTRUCTION.  A new adornment
#: added without the helper fails the contract test
#: (tests/test_diagrams.py) immediately.
#:
#: This table registers each ICON-LABEL adornment's symbol class with its
#: two per-kind parameters: the FAMILY (``hollow`` glyphs carry an outline
#: whose geometry binds the ``--lgn-adorn-stroke-width`` bridge, so their
#: weight follows the box rect through every state; ``filled`` bodies
#: have no outline -- they recolor only, consistent with the box, whose
#: rect alone thickens) and the RESTING ink.  State colors/widths all
#: come from the theme variables -- never restated per kind.
_ADORNMENTS: dict[str, tuple[str, str]] = {
    "package-tab": ("hollow", _NODE_STYLES["sysml-package"]["stroke"]),
    "accept-badge": ("filled", "#333333"),
    "send-badge": ("filled", "#333333"),
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
    hover = "var(--jp-elk-stroke-hover)"
    hover_selected = "var(--jp-elk-stroke-hover-selected)"
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
        # per-kind stroke we put on '> path'.
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
    # -- the node-attached adornment contract (single rule family) --------
    # Adornment geometry is <use> shadow content: CSS cannot select INTO a
    # use-shadow, and explicit attributes there beat any rule on the <use>
    # -- so paints bridge through the two channels that DO inherit into
    # the shadow: currentColor (bound via `color`) and the
    # --lgn-adorn-stroke-width custom property (hollow-family outlines
    # bind it inline; filled bodies have no width to bump).  The states
    # mirror the theme's rect rules on the SAME variables, so box and
    # adornments can never move apart:
    # * rest -- per-kind ink (the _ADORNMENTS table), base width;
    # * node selected -- the select tool's decorate() stamps .selected on
    #   every child vnode, the tab/badge <use> included: selection color,
    #   selected width;
    # * node hovered -- hover feedback lands ONLY on the node's own rect
    #   (.elknode.mouseover; labels are never decorated), but the rect is
    #   the elkchildren group's PRECEDING SIBLING, so the ~ combinator
    #   reaches the adornments (direct children of .elkchildren) with the
    #   hover color and width -- without any decoration at all;
    # * hovered while selected -- hover-selected color, hover width,
    #   exactly like the rect.
    style[" .sysml-adornment"] = {"--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width)"}
    style[" .elklabel.sysml-adornment.selected"] = {
        "color": selected,
        "--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width-selected)",
    }
    style[" .elknode.mouseover ~ .elkchildren > .sysml-adornment"] = {
        "color": hover,
        "--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width-hover)",
    }
    style[" .elknode.selected.mouseover ~ .elkchildren > .sysml-adornment"] = {
        "color": hover_selected,
        "--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width-hover)",
    }
    # the resting ink is the ONE per-kind parameter (see _ADORNMENTS)
    for adorn_css, (_family, rest_color) in _ADORNMENTS.items():
        style[f" .{adorn_css}"] = {"color": rest_color}
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
    # -- compartment rows are first-class hit targets ----------------------
    # A row (.sysml-row, constructed only by _row_label) is the textual
    # projection of a model element and selects in its own right (the
    # ipyelk `selectable` label flag).  Hover shows the pointer and the
    # theme hover ink; selection takes the house accent through the
    # per-kind .selected rule above (rows also carry .sysml-attribute).
    # Hover-while-selected mirrors the rect cascade.  Source order after
    # the per-kind rules lets equal-specificity hover win at rest.
    style[" text.elklabel.sysml-row"] = {"cursor": "pointer"}
    style[" text.elklabel.sysml-row.mouseover"] = {"fill": hover}
    style[" text.elklabel.sysml-row.selected"] = {"fill": selected}
    style[" text.elklabel.sysml-row.selected.mouseover"] = {"fill": hover_selected}
    # compartment HEADERS are the fold affordance (CollapseTool): the
    # pointer cursor advertises the click; the click itself is consumed
    # before sprotty ever sees it (the fit sentinel's fold channel), so
    # headers never hover/select -- they are presentation, not elements.
    # MERGED into the per-kind typography rule built above (same key).
    style[" text.elklabel.sysml-comp-label"]["cursor"] = "pointer"
    # -- compartment separator rules (spec 8.2.3.6 printed p.199) ----------
    # The vendored node view (LOCAL PATCH 13) draws one full-width <path
    # class="sysml-comp-rule"> per compartment header label, a sibling of
    # the node's rect -- so the per-kind stroke and the state recolors
    # bind exactly like the box border (never fattening: width pinned).
    style[" .sysml-comp-rule"] = {
        "fill": "none",
        "stroke-width": "1",
        "pointer-events": "none",
    }
    for css, node_style in _NODE_STYLES.items():
        style[f" .{css} > .sysml-comp-rule"] = {"stroke": node_style["stroke"]}
    for state, state_color in (
        ("selected", selected),
        ("mouseover", hover),
        ("selected.mouseover", hover_selected),
    ):
        style[f" .elknode.{state} ~ .sysml-comp-rule"] = {"stroke": state_color}
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
    # ports join the adornment contract for NODE states (the square
    # straddles the border: one silhouette with the box).  Port elements
    # carry the sysml-adornment marker (single construction site,
    # _adornment_port) and, unlike labels, sprotty never stamps the node's
    # .selected on them (ports are selectable in their own right) -- so
    # BOTH selection and hover reach them through the sibling combinator.
    # Node states recolor the square's border and its self-painted
    # currentColor geometry (direction arrows, proxy dots); the width
    # stays PINNED in every state (the port contract above), and a port
    # selected in its OWN right keeps the fill-flip (§2.0 rule 4) -- its
    # arrow stays white against the filled body.
    for state, state_color in (
        ("selected", selected),
        ("mouseover", hover),
        ("selected.mouseover", hover_selected),
    ):
        style[f" .elknode.{state} ~ .elkchildren > .sysml-adornment .elkport"] = {
            "stroke": state_color,
            "color": state_color,
        }
        style[f" .elknode.{state} ~ .elkchildren > .sysml-adornment .elkport.selected"] = {
            "color": "#ffffff",
        }
    # actor stick figures (spec BNF printed p.244; crop gt-actor.png): the
    # figure is the node BODY -- real DOM inside the mark <g
    # class="elknode">, not use-shadow content -- so plain descendant
    # rules bind it to the SAME theme variables as the box family: the
    # silhouette recolors and thickens with selection and hover exactly
    # like a rect (the name label below follows the ordinary label
    # contract).  Hover overriding selection, and hover-while-selected
    # overriding both, mirrors the theme's rect cascade (source order for
    # the equal-specificity selected/mouseover pair, specificity for the
    # combined state).
    actor_palette = _NODE_STYLES["sysml-actor"]
    style[" .sysml-actor .glyph-actor"] = {
        "fill": "none",
        "stroke": actor_palette["stroke"],
        "stroke-width": "var(--jp-elk-stroke-width)",
    }
    style[" .sysml-actor .glyph-actor-head"] = {"fill": actor_palette["fill"]}
    for state, state_color, state_width in (
        ("selected", selected, "var(--jp-elk-stroke-width-selected)"),
        ("mouseover", hover, "var(--jp-elk-stroke-width-hover)"),
        ("selected.mouseover", hover_selected, "var(--jp-elk-stroke-width-hover)"),
    ):
        style[f" .sysml-actor > .elknode.{state} .glyph-actor"] = {
            "stroke": state_color,
            "stroke-width": state_width,
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
    # straighter edges, clearer labels:
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

#: default cap on a compartment row's DISPLAY width, px (the calculation /
#: expression rows are unbounded in the model; see ``max_label_width`` on the
#: diagram builders).  ``None`` disables the cap.
_MAX_LABEL_WIDTH = 480.0

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
    # (the horizontal-flow default; ``toolbar._orient_glyphs`` moves the
    # caption BESIDE the glyph under vertical flows, where the outgoing
    # edges leave south -- right below the glyph)
    "nodeLabels.placement": "OUTSIDE H_CENTER V_BOTTOM",
}


def _marker_node(text: str | None = None) -> Node:
    return _glyph_node(None, text, "sysml-marker", 14, 14)


#: convergence anchors for control glyphs (fixed sides, centered): all
#: incoming edges join at ONE port, all outgoing leave from ONE port, so
#: multi-branch fans meet the tiny glyph at a single point each.  Sides
#: follow the flow axis (west/east for horizontal flows, north/south for
#: vertical); ``toolbar.apply_direction`` re-derives them on every
#: direction change (``_orient_glyphs``)
_ANCHOR_LAYOUT = {
    "elk.portConstraints": "FIXED_SIDE",
    "elk.portAlignment.default": "CENTER",
}


def _add_anchor_ports(node: Node) -> Node:
    """Give a glyph node single in/out convergence points (invisible 0-size
    ELK ports on its west/east sides -- the horizontal-flow default;
    ``toolbar._orient_glyphs`` moves them to north/south under vertical
    flows).  Fork/join bars deliberately do NOT get these: their edges
    distribute along the bar's long side, which is the bar's semantic."""

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
    fixed-side ports (in = WEST, out = EAST for the horizontal-flow
    default; ``toolbar._orient_glyphs`` re-derives side and anchor on
    the flow axis per direction change) whose ``elk.port.anchor``
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
    label_css: str = "sysml-stereotype",
) -> Node:
    """A fixed-size notation glyph (marker dot, control bar/rhombus,
    bullseye, terminate circle, actor figure): no title box, the label
    hangs below (``label_css`` picks its typography -- markers annotate
    in the stereotype face, the actor's NAME reads in the title face)."""

    labels = []
    if text:
        label = _label(text, label_css)
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


def _actor_svg() -> str:
    """The actor stick figure (spec BNF printed p.244; crop gt-actor.png):
    unfilled head circle + line-art body/arms/legs, geometry single-sourced
    with the headless renderer via :func:`longeron.render._actor_geometry`.

    The figure is the node BODY (an SVG-shape node, real DOM inside the
    ``<g class="elknode">`` mark -- NOT use-shadow content), so the
    ``glyph-actor`` classes let the derived stylesheet drive the paints
    directly: the silhouette recolors and thickens with selection and
    hover on the SAME theme variables as the box rects.  The attributes
    here are only the standalone-viewing fallback (any CSS rule beats
    presentation attributes)."""

    stroke = _NODE_STYLES["sysml-actor"]["stroke"]
    cx, cy, r, limbs = _actor_geometry()
    return (
        f'<circle class="glyph-actor glyph-actor-head" cx="{cx:g}" cy="{cy:g}" r="{r:g}" '
        f'fill="#ffffff" stroke="{stroke}"/>'
        f'<path class="glyph-actor" d="{limbs}" fill="none" stroke="{stroke}"/>'
    )


def _actor_figure_node(element: M.Usage) -> Node:
    """An actor usage in the spec's FIGURE form (BNF printed p.244): the
    stick figure with the name below it -- the «actor» stereotype is
    omitted because the figure IS the stereotype.  Compartments are a box
    presentation; ``structure_diagram(actor_style="box")`` keeps the
    keyword-box alternative for actors that need them."""

    return _glyph_node(
        element,
        _usage_title(element),
        "sysml-actor",
        _ACTOR_WIDTH,
        _ACTOR_HEIGHT,
        shape=SVG(use=_actor_svg()),
        label_css="",
    )


def _label(text: str, css: str = "") -> Label:
    label = Label(text=text)
    if css:
        label.properties = LabelProperties(cssClasses=css)
    return label


def _adornment_label(css: str, use: str, width: float, height: float, text: str = "") -> Label:
    """The SINGLE construction site for node-attached ICON adornments (the
    package folder tab, accept/send badges, and any future glyph riding a
    node): stamps the ``sysml-adornment`` contract marker alongside the
    kind-specific class, so the derived stylesheet's one adornment rule
    family (see ``_sysml_style``) reaches every adornment -- node + glyphs
    behave as ONE shape for selection and hover by construction.  The
    contract test (tests/test_diagrams.py) fails any icon label that
    bypasses this helper."""

    label = Label(text=text)
    label.properties = LabelProperties(
        cssClasses=f"sysml-adornment {css}",
        shape=Icon(use=use, width=width, height=height),
    )
    return label


def _adornment_port(
    css: str,
    *,
    width: float,
    height: float,
    layout_options: dict[str, str] | None = None,
    shape: PortShape | None = None,
) -> Port:
    """The SINGLE construction site for DRAWN ports (boundary squares,
    proxy dots): stamps the ``sysml-adornment`` contract marker so the
    node-state rules (selection/hover recolor) reach the square exactly
    like every other adornment.  Invisible convergence anchors carry no
    cssClasses and stay outside the contract (they never draw)."""

    properties = PortProperties(cssClasses=f"sysml-adornment {css}")
    if shape is not None:
        properties.shape = shape
    return Port(
        width=width,
        height=height,
        layoutOptions=layout_options or {},
        properties=properties,
    )


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
    if event:  # carried through to the SVG data-event (longeron.widgets.replay)
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
    """An accept/send badge (filled top-left tag).  The badge is <use>
    shadow content, so its body paints in currentColor (like the tab and
    endpoint symbols): CSS cannot select INTO the shadow, and an explicit
    fill attribute on the path would beat any rule on the <use> -- the
    ``.accept-badge``/``.send-badge`` rules bind `color` (which inherits
    into the shadow) to dark ink, and to the selection color when the
    owning box is selected (filled family, rule 3)."""

    points = " ".join(
        f"{'M' if index == 0 else 'L'} {px:g},{py:g}"
        for index, (px, py) in enumerate(_badge_points(form, _BADGE_WIDTH, _BADGE_HEIGHT))
    )
    return Symbol(
        identifier=identifier,
        element=Node(
            properties=NodeProperties(
                shape=SVG(use=f'<path d="{points} Z" fill="currentColor" stroke="none"/>')
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
    currentColor, bound to the package stroke by the adornment contract's
    resting rule -- and to the selection/hover colors per state -- so the
    tab always recolors WITH the box border.  The outline WIDTH binds
    through the ``--lgn-adorn-stroke-width`` custom property (an inline
    ``var()`` style: custom properties inherit into use-shadow content,
    where a plain stroke-width attribute would win over anything on the
    <use>) -- the HOLLOW-family half of the adornment contract (see
    ``_ADORNMENTS``) -- so the package thickens tab and rect together,
    one silhouette in every state; the ``1`` fallback keeps the base
    weight wherever the scoped rules do not reach."""

    style = _NODE_STYLES["sysml-package"]
    svg = (
        f'<path d="M 0,0 L {_TAB_WIDTH:g},0 L {_TAB_WIDTH:g},{_TAB_HEIGHT:g} '
        f'L 0,{_TAB_HEIGHT:g} Z" fill="{style["fill"]}" stroke="currentColor" '
        f'stroke-width="1" style="stroke-width: var(--lgn-adorn-stroke-width, 1)"/>'
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


def _assign_ids(root: Node, salt: str = "") -> None:
    """Stamp a stable synthetic id on every element without one.

    The ipyelk browser transport serializes ``element.id`` verbatim: an
    unset id reaches the elkjs layout worker as ``"id": null`` and the
    import dies with ``JsonImportException: Id must be a string or an
    integer: 'null'`` -- over and over, because a failed layout never
    clears the pipeline's dirty flow.  ipyelk only repairs null ids on
    flows that wake ValidationPipe (``new``) or VisibilityPipe (hidden /
    ``layout``); the routing tool's layout-options flow wakes neither, so
    the tree must be transport-ready from birth.  The headless renderer
    is immune (it generates its own ids) -- this is for the browser.

    Model-backed elements keep their qualified names.  Everything else
    (labels, edges, markers, invisible anchor ports, the root) gets a
    deterministic DFS-position id under :data:`_SYNTH_ID_PREFIX`, which
    the qualified-name consumers (SVG ``data-qname``/title recovery,
    toolbar search, ``on_select`` resolution) all skip.  Idempotent:
    re-running on a stamped tree changes nothing, and positions are
    stable because every element is counted whether stamped or not.

    ``salt`` (the per-node collapse machinery passes a digest of the
    collapsed set) namespaces the synthetic ids per TREE STATE: sprotty's
    update animation matches elements by id across relayouts, and a
    recycled DFS position would pair one state's edge with an unrelated
    element of the next -- garbage morphs.  Distinct states never share
    synthetic ids; the SAME state (the empty salt above all, so a
    collapse round trip ends byte-identical to birth) always regenerates
    the same ids.  Salted ids still carry :data:`_SYNTH_ID_PREFIX`, so
    every consumer skip-rule keeps working.
    """

    counter = itertools.count()
    prefix = f"{_SYNTH_ID_PREFIX}{salt}:" if salt else _SYNTH_ID_PREFIX

    def visit(element: Any) -> None:
        position = next(counter)
        if element.id is None:
            element.id = f"{prefix}{position}"
        for label in element.labels or []:
            visit(label)
        for port in getattr(element, "ports", None) or []:
            visit(port)
        for child in getattr(element, "children", None) or []:
            visit(child)
        for edge in getattr(element, "edges", None) or []:
            visit(edge)

    visit(root)


def _collapse_salt(levels: Mapping[str, str], folded: Mapping[str, tuple[str, ...]]) -> str:
    """The synthetic-id namespace for one collapse state (see
    :func:`_assign_ids`): empty for the expanded default -- birth trees
    and round-tripped-back-to-expanded trees share ids byte for byte --
    and a short stable digest of the levels + folds otherwise."""

    if not levels and not folded:
        return ""
    lines = [f"{qname}={level}" for qname, level in sorted(levels.items())]
    lines += [
        f"{qname}#{section}" for qname, sections in sorted(folded.items()) for section in sections
    ]
    digest = hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()
    return f"c{digest[:8]}"


def _prepare_root(
    root: Node,
    *,
    layout: dict[str, str] | None = None,
    routing: str = "orthogonal",
    direction: str = "RIGHT",
    id_salt: str = "",
) -> None:
    """Make a built element tree transport-ready: the shared tail of
    :func:`_finish` and the per-node collapse rebuilds
    (:meth:`PartsCollapseTool.apply`), so a rebuilt tree goes through
    EXACTLY the birth tree's preparation."""

    root.layoutOptions = dict(_ROOT_LAYOUT)
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
    # layout flow (RIGHT = left-to-right, DOWN = top-to-bottom): ROOT-ONLY
    # -- elkjs carries elk.direction into nested compounds under
    # INCLUDE_CHILDREN (unlike the spacing/routing options above); the
    # toolbar's DirectionTool re-applies it live through the same helper
    apply_direction(root, direction)
    # every element ships to the browser with a REAL id (null ids kill the
    # elkjs worker; see _assign_ids) -- last, so it sees the whole tree
    _assign_ids(root, salt=id_salt)


def _finish(
    root: Node,
    style: dict | None = None,
    direction: str = "RIGHT",
    toolbar: bool = True,
    layout: dict[str, str] | None = None,
    routing: str = "orthogonal",
    height: str | None = None,
    id_salt: str = "",
) -> Any:
    _prepare_root(root, layout=layout, routing=routing, direction=direction, id_salt=id_salt)
    result = ipyelk.from_element(root)
    # browser-roundtrip budget: ipyelk's 30s pipe default classifies a slow
    # machine (a loaded, shared CI runner rendering two dozen diagrams
    # through one elkjs worker) as a layout FAILURE -- and error semantics
    # rightly stop retries, so every affected diagram dies visibly. Real
    # errors still surface immediately through the pipe's error messages;
    # the timeout exists only to catch LOST roundtrips, so generosity is
    # cheap. One knob for tests and slow environments.
    roundtrip_timeout = float(os.environ.get("LONGERON_BROWSER_TIMEOUT", "120"))
    for pipe in getattr(result.pipe, "pipes", ()):
        if hasattr(pipe, "timeout"):
            pipe.timeout = roundtrip_timeout
    result.symbols = _symbols()
    result.style = dict(SYSML_STYLE if style is None else style)
    if height is None:
        # bare-cell default: the widget's own height is 100% of an
        # auto-height output area (which computes to auto), so a minimum
        # floor gives plain display(widget) a usable canvas
        result.layout.min_height = "400px"
    else:
        # an explicit height is a contract: honor it exactly, even below
        # the default floor (CSS min-height would win over height), so
        # inline layouts can match a neighbor -- tutorial 7 sits a diagram
        # beside a 650px 3D viewer
        if not isinstance(height, str):
            raise ValueError(f"height must be a CSS length string or None, not {height!r}")
        result.layout.height = height
        result.layout.min_height = "0"
    # EVERY widget fits-and-centers itself: once when its first layout
    # arrives, and again whenever its own fit sentinel reports a fresh
    # view, a first reveal, or an untouched-viewport resize (registered
    # before the toolbar upgrade so the DirectionTool can queue re-fits)
    fit_tool = AutoFitTool(result)
    result.register_tool(fit_tool)
    # the sentinel rides INSIDE the widget's own DOM, a hidden child
    # beside the view + toolbar: plain display(widget) is self-fitting
    # with zero consumer wiring -- first reveal (background tab,
    # display:none lifted, lazy output rendering) and container resizes
    # (an HBox squeeze, a dock drag) re-fit, always respecting the
    # user's pan/zoom latch (longeron.toolbar._SENTINEL_ESM).  The
    # lgx-diagram class is the sentinel's DOM handle to the box it
    # measures.  Without anywidget the sentinel is None and the widget
    # keeps the first-layout fit only (graceful degradation).
    result.add_class("lgx-diagram")
    if fit_tool.sentinel is not None:
        result.children = (*result.children, fit_tool.sentinel)
    if toolbar:  # compact icon toolbar + search (longeron.toolbar)
        upgrade_toolbar(result)
    return result


def _stamp_view_state(
    widget: Any, element: M.Element, kind: str, options: Mapping[str, Any] | None = None
) -> Any:
    """Mark a built widget with what it draws: root element, diagram
    kind, and the non-default builder options.

    This is the seam view persistence reads (:mod:`longeron.views`
    duck-types diagram widgets through it): ``save_view(model, widget)``
    needs to know the widget's scope and kind without re-deriving them
    from ELK geometry.  Live presentation (direction, routing, collapse
    state) is deliberately NOT stamped -- it is read off the source tree
    at save time (:func:`longeron.views.capture_presentation`), so
    toolbar toggles after construction are captured too.
    """

    widget._lgn_view_state = {"element": element, "kind": kind, "options": dict(options or {})}
    return widget


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
    actor_style: str = "figure",
    parts: str = "nested",
    levels: Mapping[str, str] | None = None,
    folded: Mapping[str, Iterable[str]] | None = None,
    toolbar: bool = True,
    routing: str = "orthogonal",
    direction: str = "right",
    max_label_width: float | None = _MAX_LABEL_WIDTH,
    height: str | None = None,
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

    ``actor_style="figure"`` (the default) draws actor usages as the
    spec's stick figure (BNF printed p.244) -- head, body, arms, legs in
    the usage palette, name below the figure, no «actor» stereotype (the
    figure IS the stereotype); ``actor_style="box"`` keeps the «actor»
    keyword-box alternative (errata N17), which also shows compartments.
    Stakeholders always draw the «stakeholder» box -- the spec reserves
    the figure for actors.

    Textual members group into the spec's LABELED compartments (8.2.3.6
    printed p.199): every compartment opens with a full-width separator
    rule and its italic name -- 'attributes' (printed p.46), 'enums'
    (p.48), 'directed features' (p.62; 'parameters' on action/calc
    boxes, p.91), the constraint compartments (p.127), 'subject', and so
    on -- replacing the earlier unlabeled row blob.  Every row is a
    first-class SELECTABLE projection of its model element: it carries
    the element's qualified name as its id, clicking it in the browser
    feeds :func:`on_select` exactly like a node click, and kernel-side
    selection writes light it up.

    ``parts`` picks the presentation of nested usages (both are legal
    spec notation; the option only chooses): ``"nested"`` (the default)
    draws them as nested boxes -- the graphical compartment, required
    where children anchor edges (connections, flows, proxies) --
    while ``"rows"`` is the COLLAPSED presentation: parts, items, the
    occurrence family, actions, states, requirements, named satisfies
    and allocations, actors, stakeholders and views render as textual
    ``name : Type`` rows in their spec compartments ('parts' printed
    p.60, 'items' p.57, 'actions' p.89, 'states' p.117, ...).  Edges
    that would anchor on the collapsed children are not drawn -- the
    textual presentation trades them for compactness.

    ``levels`` names individual nodes (qualified names, or elements ->
    ``"partial"`` / ``"collapsed"``) whose rendition starts below the
    expanded default -- the state behind the toolbar's collapse button
    (which CYCLES the selected node: expanded -> partial -> collapsed ->
    expanded, each click one step less detail) and the :func:`level`
    kernel API (see :class:`CollapseTool`).  ``"partial"`` is the
    per-node version of ``parts="rows"``: the node's rowable members
    become textual rows.  ``"collapsed"`` is the smallest legal
    rendition: the name compartment alone -- kind chip + name, no
    compartment stack, no drawn children (boundary port squares stay:
    they are border interface points, the classic black-box view); a
    collapsed PACKAGE likewise draws its folder box alone, whatever the
    ``membership`` mode.  ``folded`` names per-node FOLDED compartments
    (qualified name -> compartment names): a folded compartment keeps
    its header -- with the closed twist -- and drops its rows while the
    node stays at its level (the header row's click affordance in the
    browser; the :func:`fold` kernel API).

    How collapse composes, level x presentation:

    * edges -- connector-family edges (connections, bindings,
      interfaces, flows, allocates) that anchored on a shrunken node's
      children re-anchor as the spec's proxy dots on the node itself
      (printed p.67) at BOTH shrunken levels; connectors living entirely
      inside one shrunken node are part of the collapsed content and are
      not drawn; the specialization/typing family from undrawn children
      is not drawn (at partial, the rows' ``: Type`` text carries it) --
      all exactly as under the diagram-wide ``parts="rows"``;
    * ``parts="rows"`` -- every node is already textual, so
      ``"partial"`` changes nothing there and the toolbar cycle skips it
      (expanded -> collapsed -> expanded); ``"collapsed"`` and ``folded``
      work unchanged;
    * folds -- independent of the level: they apply to whatever
      compartments the node currently shows (attributes at expanded,
      parts rows at partial, none at collapsed) and are remembered
      through level changes.

    ``toolbar=False`` keeps ipyelk's stock text-button toolbar instead of
    the compact icon+search one (:mod:`longeron.toolbar`).

    ``routing`` picks the ELK edge routing style -- ``"orthogonal"`` (the
    default), ``"polyline"`` or ``"splines"`` -- for headless renders and
    the initial widget; the toolbar's routing button cycles it live.
    ``direction`` picks the layout flow -- ``"right"`` (left-to-right,
    the default) or ``"down"`` (top-to-bottom); the toolbar's orientation
    button toggles it live.

    ``max_label_width`` caps how wide a compartment row may draw, in px
    (default 480): longer rows -- calculation/expression attributes are
    the usual offenders -- are end-ellipsized with the FULL text on the
    row's hover tooltip, so one absurd expression no longer makes the
    whole node absurd.  ``None`` lifts the cap (every row at full width).

    ``height`` pins the widget's rendered height to a CSS length (e.g.
    ``"480px"``) so inline compositions can match a neighbor exactly --
    tutorial 7 sits a diagram beside a 650px 3D viewer in an HBox.  The
    default ``None`` keeps the bare-cell behavior: content-driven height
    with a 400px minimum floor.  An explicit height always wins, even
    below that floor.
    """

    levels_map = {
        str(getattr(name, "qualified_name", None) or name): str(value)
        for name, value in (levels or {}).items()
    }
    for value in levels_map.values():
        if value not in _LEVELS:
            choices = ", ".join(_LEVELS)
            raise ValueError(f"a collapse level must be one of {choices}; not {value!r}")
    levels_map = dict(sorted((q, v) for q, v in levels_map.items() if v != "expanded"))
    folded_map = dict(
        sorted(
            (
                str(getattr(name, "qualified_name", None) or name),
                tuple(sorted({str(section) for section in sections})),
            )
            for name, sections in (folded or {}).items()
            if tuple(sections)
        )
    )
    root, builder = _build_structure_root(
        element,
        show_attributes=show_attributes,
        show_relationships=show_relationships,
        composition=composition,
        membership=membership,
        annotations=annotations,
        actor_style=actor_style,
        parts=parts,
        levels=levels_map,
        folded=folded_map,
        max_label_width=max_label_width,
    )
    # the sidecar tier persists only DEVIATIONS from these defaults
    options: dict[str, Any] = {}
    if not show_attributes:
        options["show_attributes"] = False
    if not show_relationships:
        options["show_relationships"] = False
    if composition != "defs":
        options["composition"] = composition
    if membership != "nested":
        options["membership"] = membership
    if annotations:
        options["annotations"] = True
    if actor_style != "figure":
        options["actor_style"] = actor_style
    if parts != "nested":
        options["parts"] = parts
    if max_label_width != _MAX_LABEL_WIDTH:
        options["max_label_width"] = max_label_width
    widget = _finish(
        root,
        toolbar=toolbar,
        layout={"elk.spacing.labelNode": "0"},
        routing=routing,
        direction=direction,
        height=height,
        id_salt=_collapse_salt(levels_map, folded_map),
    )
    # relationship edges carry SYNTHETIC transport ids (_assign_ids ran in
    # _finish); this kernel-side seam maps them back to the model elements
    # they draw, so consumers can select relationship edges (tree -> edge)
    # and resolve edge clicks (edge -> element) -- qualified-name machinery
    # cannot: anonymous relationships have no qualified name at all
    widget._lgn_rel_edges = {
        str(edge.id): rel for edge, rel in builder.rel_edges if edge.id is not None
    }
    _stamp_view_state(widget, element, "structure", options)
    # per-node collapse: the toolbar's collapse button, the browser's
    # header-fold clicks, and the level()/fold() kernel API all drive
    # rebuilds through this tool, which replays the FULL resolved builder
    # options with the live levels/folds
    _install_collapse_tool(
        widget,
        CollapseTool(
            widget,
            element=element,
            options={
                "show_attributes": show_attributes,
                "show_relationships": show_relationships,
                "composition": composition,
                "membership": membership,
                "annotations": annotations,
                "actor_style": actor_style,
                "parts": parts,
                "max_label_width": max_label_width,
            },
            builder=builder,
            selection=widget.view.selection,
            levels=levels_map,
            folded=folded_map,
        ),
        compact=toolbar,
    )
    return widget


def _build_structure_root(
    element: M.Model | M.Namespace,
    *,
    show_attributes: bool = True,
    show_relationships: bool = True,
    composition: str = "defs",
    membership: str = "nested",
    annotations: bool = False,
    actor_style: str = "figure",
    parts: str = "nested",
    levels: Mapping[str, str] | None = None,
    folded: Mapping[str, tuple[str, ...]] | None = None,
    max_label_width: float | None = _MAX_LABEL_WIDTH,
) -> tuple[Node, _StructureBuilder]:
    """Build a structure view's element tree: the shared front of
    :func:`structure_diagram` and the per-node collapse rebuilds
    (:meth:`CollapseTool.apply`), so a rebuilt tree is BY CONSTRUCTION
    the tree the builder would have produced at birth -- cycling a node
    back to expanded round-trips to a payload-identical tree."""

    if max_label_width is not None and max_label_width <= 0:
        raise ValueError(f"max_label_width must be positive or None, not {max_label_width!r}")
    if membership not in ("nested", "edges"):
        raise ValueError(f"membership must be 'nested' or 'edges', not {membership!r}")
    if actor_style not in ("figure", "box"):
        raise ValueError(f"actor_style must be 'figure' or 'box', not {actor_style!r}")
    if parts not in ("nested", "rows"):
        raise ValueError(f"parts must be 'nested' or 'rows', not {parts!r}")
    builder = _StructureBuilder(
        element,
        show_attributes,
        composition=composition,
        membership=membership,
        actor_style=actor_style,
        parts=parts,
        levels=levels or {},
        folded=folded or {},
    )
    root = builder.build()
    if show_relationships:
        builder.add_relationship_edges(root)
    if annotations:
        builder.add_annotations(root)
    builder.pack_components(root)
    if max_label_width is not None:
        _ellipsize_rows(root, max_label_width)
    _size_compartment_rows(root)
    # package tabs ride flush with the box top (outside icon labels; the
    # spacing option applies per hierarchy level, so EVERY container
    # restates it -- pack_components wraps loose packages in synthetic
    # groups, and a package behind such a group otherwise fell back to
    # the elkjs default 5px: the tab floated off its box)
    for node in _walk_nodes(root):
        if node.children:
            node.layoutOptions.setdefault("elk.spacing.labelNode", "0")
    return root, builder


def _ellipsize_rows(node: Node, max_width: float) -> None:
    """Cap compartment-row labels at ``max_width`` display pixels.

    Calculation/expression rows can be arbitrarily long in the model, and a
    compartment is as wide as its widest row -- one absurd expression made
    the whole node (and every fit computed from it) absurd.  Rows past the
    cap are END-ellipsized ('name : Real = if airframe.wing\u2026'), keeping the
    feature name -- the row's identity -- visible.

    Truncation happens HERE, kernel-side at construction time and BEFORE any
    measurement, so both pipelines see only the display string: the browser
    text sizer measures it, :func:`_size_compartment_rows` pre-sizes with it,
    and ``toolbar._fit_compound_labels`` / ``render._to_elk_json`` derive
    their compound minimum widths from it automatically.  The full original
    text rides ``label.properties.tooltip``: the browser label view renders
    it as the SVG ``<title>`` (the native hover tooltip) and the headless
    SVG writer emits the same element.  The label element itself is
    untouched otherwise -- css classes, selection and adornment behavior are
    exactly those of an untruncated row.
    """

    for label in node.labels or []:
        css = label.properties.cssClasses or ""
        if "sysml-attribute" not in css:
            continue
        text = label.text or ""
        if _measure(text, css)[0] <= max_width:
            continue
        lo, hi = 1, len(text)  # longest prefix whose 'prefix\u2026' still fits
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if _measure(text[:mid].rstrip() + "\u2026", css)[0] <= max_width:
                lo = mid
            else:
                hi = mid - 1
        label.properties.tooltip = text
        label.text = text[:lo].rstrip() + "\u2026"
    for child in node.children:
        _ellipsize_rows(child, max_width)


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
        actor_style: str = "figure",
        parts: str = "nested",
        levels: Mapping[str, str] | None = None,
        folded: Mapping[str, tuple[str, ...]] | None = None,
    ):
        self.element = element
        self.show_attributes = show_attributes
        self.composition = composition
        self.membership = membership
        self.actor_style = actor_style
        self.parts = parts
        #: PER-NODE collapse levels (qualified name -> "partial" |
        #: "collapsed"; absent = expanded): "partial" rows the node's
        #: rowable members exactly like parts="rows", "collapsed" draws
        #: the smallest legal rendition -- the name compartment alone
        #: (kind chip + name; boundary port squares stay, they are border
        #: interface points, not compartments) -- while the rest of the
        #: diagram keeps nested boxes
        self.levels = dict(levels or {})
        #: PER-COMPARTMENT folds (qualified name -> compartment names):
        #: a folded compartment keeps its header (closed twist), drops
        #: its rows; the node stays at its level
        self.folded = {qname: frozenset(sections) for qname, sections in (folded or {}).items()}
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
        # every relationship edge paired with the MODEL element it draws
        # (a connection/binding/flow/satisfy/allocate/dependency/alias):
        # the seam behind the widget's ``_lgn_rel_edges`` attribute, which
        # maps the edges' synthetic transport ids back to model elements
        # so consumers (longeron.widgets.explorer) can select edges and resolve
        # edge clicks -- edge ids are assigned late (_assign_ids), hence
        # the edge OBJECTS are recorded here and the ids read after
        self.rel_edges: list[tuple[Edge, M.Element]] = []

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

    def _level(self, element: M.Element) -> str:
        return self.levels.get(element.qualified_name or "", "expanded")

    def _shrunk(self, element: M.Element) -> bool:
        """Whether the element's nested members are UNDRAWN because of a
        per-node collapse level (partial rows them, collapsed drops them
        entirely) -- the gate for connector-end re-anchoring."""

        return self._level(element) in ("partial", "collapsed")

    def _visit(self, element: M.Element) -> Node | None:
        if isinstance(element, M.Package):
            node = _node(element, element.label, "sysml-package", "package")
            self._add_package_tab(node)
            members = [] if self._level(element) == "collapsed" else element.members
            for member in members:
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
            self._fill_node(node, element)
        elif (
            isinstance(element, M.Usage)
            and element.kind == "actor"
            and self.actor_style == "figure"
        ):
            # the spec's stick-figure actor (BNF printed p.244; crop
            # gt-actor.png), the DEFAULT presentation: name below the
            # figure, «actor» stereotype omitted (the figure IS the
            # stereotype).  actor_style="box" keeps the keyword-box
            # alternative (errata N17) -- the branch below.  Stakeholders
            # always draw the box (the spec reserves the figure for
            # actors).
            node = _actor_figure_node(element)
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
            # «view» usage boxes: a saved diagram's recipe is a model
            # element too, so it must be visible where it lives
            # (docs/design/view-persistence.md, gap-analysis finding 3)
            "view",
        ):
            if element.kind in ("satisfy", "allocation") and not element.name:
                # the anonymous shorthands (`satisfy R by sys;`,
                # `allocate a to b;`) draw as keyword edges, not boxes
                return None
            stereotype = _KIND_STEREOTYPES.get(element.kind, element.kind)
            node = _node(element, _usage_title(element), "sysml-usage", stereotype)
            self._fill_node(node, element)
        else:
            return None
        self.nodes[id(element)] = node
        return node

    def _fill_node(self, node: Node, element: M.Namespace) -> None:
        """Level dispatch for a definition/usage box: the full compartment
        fill, or -- at the "collapsed" level -- the smallest legal
        rendition, the name compartment alone (kind chip + name, no
        compartment stack, no drawn children).  Boundary port squares
        STAY: they are border interface points, not compartments (the
        classic black-box view), so port-anchored edges keep their
        anchors; edges to undrawn children re-anchor as proxy dots
        exactly like the partial level's."""

        if self._level(element) == "collapsed":
            for member in element.members:
                if isinstance(member, M.Usage) and member.kind == "port":
                    self._add_boundary_port(node, member)
            self._finalize_ports(node)
            return
        self._fill_features(node, element)

    def _fill_features(self, node: Node, element: M.Namespace) -> None:
        """Fill a definition/usage box: labeled compartments plus children.

        Textual members group into the spec's LABELED compartments
        (8.2.3.6 printed p.199): rows collect per compartment keyword,
        then emit in :data:`_SECTION_ORDER`, each compartment opened by
        its header label (separator rule + italic name, drawn by both
        pipelines from the header's position).  Every row is a
        first-class selectable projection of its model element
        (:func:`_row_label`).

        Member-kind coverage (the honest ledger):

        * always rows -- attributes ('attributes'), enum literals
          ('enums'), directed features ('directed features'; 'parameters'
          on action/calc boxes, printed p.91), constraints (grouped by
          declared kind: 'constraints' / 'assert constraints' / 'require
          constraints' / 'assume constraints'), subjects ('subject');
        * ports -- ALWAYS the spec's boundary squares (printed p.59),
          never rows: the square is the interconnection presentation and
          carries direction/conjugation the textual 'ports' compartment
          row would lose;
        * nested-box kinds (parts, items, occurrence family, actions,
          states, requirements, satisfies, allocations, actors,
          stakeholders, views) -- drawn nested boxes by default
          (``parts="nested"``), textual rows in their spec compartments
          under ``parts="rows"`` (:data:`_ROW_SECTIONS`); ``ref``
          members row into 'parts' with the ``ref`` prefix (printed
          p.60);
        * honest omissions -- connections/bindings/interfaces/flows/
          dependencies draw as EDGES (their spec node form is the edge),
          so no 'connections'/'interfaces'/'flows' compartments; usage
          kinds longeron never draws (calc, concern, verification,
          use_case, viewpoint, rendering, message, event, frame,
          objective, ...) stay undrawn in both presentations -- adding
          their compartments without their semantics would decorate,
          not inform; drawn nested children form the spec's GRAPHICAL
          compartment, whose view-usage header (7.26.5) is likewise
          omitted until view usages name them.
        """

        sections: dict[str, list[Label]] = {}

        def row(section: str, text: str, member: M.Usage) -> None:
            sections.setdefault(section, []).append(_row_label(text, member))

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
                row("attributes", text, member)
            elif member.kind == "enum_literal":
                row("enums", member.label, member)
            elif member.direction is not None and self.show_attributes:
                title = (
                    _usage_title(member)
                    if member.name
                    else (f": {member.types[0]}" if member.types else "")
                )
                # action/calc boxes call their directed features
                # 'parameters' (printed p.91); everything else uses the
                # 'directed features' compartment (printed p.62)
                section = (
                    "parameters"
                    if getattr(element, "kind", None) in ("action", "calc")
                    else "directed features"
                )
                row(section, f"{member.direction} {title}".strip(), member)
            elif member.kind == "constraint" and self.show_attributes:
                kind = member.constraint_kind or "constraint"
                text = f"{kind} {member.name}" if member.name else kind
                if member.result is not None:
                    expr = member.result.to_text()
                    if len(expr) > 30:
                        expr = expr[:29] + "\u2026"
                    text += f" {{{expr}}}"
                row(_CONSTRAINT_SECTIONS[member.constraint_kind], text, member)
            elif member.kind == "subject" and self.show_attributes:
                row("subject", f"subject {_usage_title(member)}", member)
            elif (
                (self.parts == "rows" or self._level(element) == "partial")
                and member.kind in _ROW_SECTIONS
                and (member.name or member.kind not in ("satisfy", "allocation"))
            ):
                # the PARTIAL (textual) presentation: the member as a
                # 'name : Type' row in its spec compartment instead of a
                # drawn nested box (anonymous satisfy/allocate shorthands
                # keep their keyword-edge form, exactly as under nesting)
                # -- diagram-wide under parts="rows", per-node at the
                # "partial" collapse level
                text = _usage_title(member)
                if member.is_ref or member.kind == "ref":
                    text = f"ref {text}"
                row(_ROW_SECTIONS[member.kind], text, member)
            else:
                child = self._visit(member)
                if child is not None:
                    node.children.append(child)
        node_folds = self.folded.get(element.qualified_name or "", frozenset())
        for section in sorted(sections, key=lambda name: _SECTION_RANK[name]):
            # a folded compartment keeps its header (closed twist, so the
            # affordance stays discoverable and clickable) and drops its
            # rows; the node stays at its level
            section_folded = section in node_folds
            node.labels.append(_section_header(section, folded=section_folded))
            if not section_folded:
                node.labels.extend(sections[section])
        self._finalize_ports(node)

    def _add_package_tab(self, node: Node) -> None:
        """The package folder tab (spec printed p.24): a fixed-size icon
        label pinned OUTSIDE at the top-left, flush with the box top (ELK
        reserves the space, so nothing overlaps in either pipeline).  The
        single-space text keeps ELK's label placement engaged (it skips
        empty labels); nothing renders it."""

        tab = _adornment_label("sysml-tab", "package-tab", _TAB_WIDTH, _TAB_HEIGHT, text=" ")
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
        port = _adornment_port(
            css,
            width=_PORT_SIZE,
            height=_PORT_SIZE,
            layout_options={"elk.port.borderOffset": f"{-_PORT_SIZE / 2:g}"},
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
        resolved: list[tuple[Node | Port, list[str]]] = []
        for end in ends:
            anchor, residual = self._resolve_end_anchor(end.target, element)
            if anchor is None:
                return  # an unresolvable end draws nothing (as before)
            resolved.append((anchor, residual))
        if self._swallowed([anchor for anchor, _ in resolved]):
            return  # every end collapsed into ONE node: not drawn
        for anchor, residual in resolved:
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
            self.rel_edges.append((edge, element))
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
        self.rel_edges.append((edge, element))
        root.edges.append(edge)
        for end, endpoint in rest:
            edge = _edge(_anchor(junction, "out"), endpoint, "sysml-edge-connect")
            if end.multiplicity is not None:
                _add_end_multiplicity(edge, end.multiplicity, "HEAD")
            self.rel_edges.append((edge, element))
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
        if self._swallowed(endpoints):
            return  # every end collapsed into ONE node: not drawn
        for source, target in itertools.pairwise(endpoints):
            edge = _edge(
                source,
                target,
                "sysml-edge-allocate",
                text="\u00aballocate\u00bb",
                text_css="sysml-stereotype",
            )
            self.rel_edges.append((edge, alloc))
            root.edges.append(edge)

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

        An end naming a PER-NODE-COLLAPSED child directly (the child is
        undrawn, its parent box is) anchors on that collapsed ancestor
        with the path below it as the residual -- the same proxy-dot
        presentation, reached from the other side.  Ends undrawn for any
        other reason stay unresolved, exactly as before.
        """

        parts = name.split(".")
        try:
            found = self.interp.resolver.resolve(parts[0], context.owner or self.model)
        except Exception:
            return None, []
        anchor = self._lookup(found)
        residual: list[str] = []
        if anchor is None and self.levels:
            anchor, residual = self._collapsed_ancestor(found)
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

    def _collapsed_ancestor(self, element: M.Element) -> tuple[Node | None, list[str]]:
        """The drawn node of a PER-NODE-collapsed (partial or fully
        collapsed) ancestor of an undrawn feature, plus the residual path
        segments down to the feature -- the anchor of the spec's
        proxy-connection presentation (printed p.67) when collapse
        undraws a connector end.  ``(None, [])`` when no drawn ancestor
        exists or the nearest drawn ancestor is NOT collapse-shrunk
        (undrawn ends then stay undrawn, exactly as before this
        feature)."""

        residual = [element.name or element.label]
        owner = element.owner
        while owner is not None:
            node = self.nodes.get(id(owner))
            if node is not None:
                if self._shrunk(owner):
                    return node, residual[::-1]
                return None, []
            residual.append(owner.name or owner.label)
            owner = owner.owner
        return None, []

    def _swallowed(self, anchors: Sequence[Node | Port]) -> bool:
        """True when a connector's every end anchors on the SAME collapsed
        node as the node ITSELF (an undrawn child re-anchored by
        :meth:`_collapsed_ancestor` or :meth:`_resolve_end_anchor`'s
        residual walk, before any proxy dot materializes) -- ends on real
        drawn port squares keep the edge drawing.  Such a connector lives
        entirely inside the collapsed graphical compartment; the textual
        presentation does not draw it, and materializing its proxy dots
        would orphan them on the border."""

        if not anchors:
            return False
        first = anchors[0]
        if not isinstance(first, Node):
            return False
        if self.levels.get(str(first.id or "")) not in ("partial", "collapsed"):
            return False
        return all(anchor is first for anchor in anchors[1:])

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
        port = _adornment_port(
            "sysml-port-proxy",
            width=_PROXY_SIZE,
            height=_PROXY_SIZE,
            layout_options={"elk.port.borderOffset": f"{-_PROXY_SIZE / 2:g}"},
            shape=PortShape(use="port-proxy"),
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
        self.rel_edges.append((edge, flow))
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
                edge = _edge(
                    source,
                    target,
                    "sysml-edge-satisfies",
                    text="\u00absatisfy\u00bb",
                    text_css="sysml-stereotype",
                )
                self.rel_edges.append((edge, satisfy))
                root.edges.append(edge)

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
            edge = _edge(clients[0], suppliers[0], "sysml-edge-dependency", text=label)
            self.rel_edges.append((edge, dep))
            root.edges.append(edge)
            return
        junction = _glyph_node(dep, label, "sysml-junction", _JUNCTION_SIZE, _JUNCTION_SIZE)
        _add_center_anchor(junction)
        # lay the dot out inside the namespace that owns the dependency
        # (falling back to the diagram root)
        owner_node = self.nodes.get(id(dep.owner)) if dep.owner is not None else None
        (owner_node or root).children.append(junction)
        for client in clients:
            edge = _edge(client, _anchor(junction, "in"), "sysml-edge-depclient")
            self.rel_edges.append((edge, dep))
            root.edges.append(edge)
        for supplier in suppliers:
            edge = _edge(_anchor(junction, "out"), supplier, "sysml-edge-dependency")
            self.rel_edges.append((edge, dep))
            root.edges.append(edge)

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
        edge = _edge(owner_node, target, "sysml-edge-alias", text=alias.name)
        self.rel_edges.append((edge, alias))
        root.edges.append(edge)

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
# per-node collapse (structure view): levels + per-compartment folds
# ---------------------------------------------------------------------------


class CollapseTool(Tool):
    """Per-node collapse through the THREE levels of a structure box,
    plus per-compartment folds.

    The structure view replaces ipyelk's stock ``ToggleCollapsedTool``
    with this one -- same toolbar slot, same select-then-click gesture
    (the affordance users already know).  Each click on the button
    CYCLES the selected node one step DOWN in detail, then wraps back to
    full (documented cycle: each click shows less, the click after the
    smallest form restores everything):

    * **expanded** -- nested child boxes (the full form, the default);
    * **partial** -- the children leave the canvas and reappear as
      selectable ``name : Type`` rows under their spec compartment
      headers ('parts' printed p.60) -- skipped when the node has no
      rowable members (packages, boxes of non-rowable children) and
      under the diagram-wide ``parts="rows"`` (everything is rows
      already);
    * **collapsed** -- the smallest legal rendition: the name
      compartment alone (kind chip + name, no compartment stack, no
      drawn children; boundary port squares stay -- the black-box view).

    Connector edges that anchored on undrawn children re-anchor as proxy
    dots on the box itself (printed p.67) at both shrunken levels.
    Selection survives level changes because rows carry the SAME id (the
    qualified name) their boxes carried.

    Independently of the level, every compartment header carries a FOLD
    affordance (the explorer tree's twist, part of the header text):
    clicking the header row in the browser folds that ONE compartment to
    its header while the node stays at its level.  Headers are
    presentation artifacts, not model elements -- the click is consumed
    before sprotty sees it (the toolbar fit-sentinel reports it on a
    dedicated channel), so it can never enter the model-selection seam.

    :attr:`levels` (qualified name -> level) and :attr:`folded`
    (qualified name -> folded compartment names) are the state seams:
    the toolbar button and header clicks toggle them, the
    :func:`level` / :func:`fold` kernel API edits them, view persistence
    captures them (:func:`longeron.views.capture_presentation`) and
    re-seeds them through ``structure_diagram(levels=..., folded=...)``.
    Every change REBUILDS the diagram's source tree through the same
    builder the constructor used (:func:`_build_structure_root`, then
    the :func:`_prepare_root` + loader-defaults preparation of the birth
    tree) and re-runs the pipeline with the birth flow -- so cycling a
    node back to expanded is payload-identical BY CONSTRUCTION.
    """

    levels = T.Dict(
        key_trait=T.Unicode(),
        value_trait=T.Unicode(),
        help="per-node collapse level (qualified name -> 'partial' | 'collapsed')",
    )
    folded = T.Dict(
        key_trait=T.Unicode(),
        help="per-node folded compartments (qualified name -> tuple of names)",
    )
    selection = T.Any(default_value=None, allow_none=True)

    def __init__(
        self,
        diagram: Any,
        element: M.Model | M.Namespace,
        options: Mapping[str, Any],
        builder: _StructureBuilder,
        **kwargs: Any,
    ) -> None:
        self._diagram = diagram
        self._element = element
        #: the FULL resolved builder options (not the sidecar deviations):
        #: rebuilds replay them verbatim, whatever the defaults become
        self._options = dict(options)
        self._ready = False  # the birth tree already reflects the state
        self._refresh_maps(diagram.source.value, builder)
        super().__init__(**kwargs)
        self.reports = (F.New,)
        self.ui = self._build_ui()
        self._ready = True

    async def run(self) -> None:  # Tool protocol; the button cycles sync
        pass

    # -- state normalization -------------------------------------------------

    @T.validate("levels")
    def _normalize_levels(self, proposal: Any) -> dict[str, str]:
        levels: dict[str, str] = {}
        for qname, value in dict(proposal["value"]).items():
            name = str(value)
            if name == "expanded":
                continue  # the default level is ABSENCE, so states compare
            if name not in _LEVELS:
                choices = ", ".join(_LEVELS)
                raise T.TraitError(f"a collapse level must be one of {choices}; not {value!r}")
            levels[str(qname)] = name
        return dict(sorted(levels.items()))

    @T.validate("folded")
    def _normalize_folded(self, proposal: Any) -> dict[str, tuple[str, ...]]:
        folded: dict[str, tuple[str, ...]] = {}
        for qname, sections in dict(proposal["value"]).items():
            names = tuple(sorted({str(section) for section in sections}))
            if names:
                folded[str(qname)] = names
        return dict(sorted(folded.items()))

    @T.observe("levels", "folded")
    def _on_state(self, change: Any = None) -> None:
        if self._ready:
            self.apply()

    # -- the rebuild ----------------------------------------------------------

    def apply(self) -> None:
        """Rebuild the diagram's source tree with the active collapse
        state and re-run the pipeline (the routing/direction tools'
        refresh path, with the birth ``new`` flow)."""

        root, builder = _build_structure_root(
            self._element, levels=dict(self.levels), folded=dict(self.folded), **self._options
        )
        # live presentation carries over: the CURRENT tree holds whatever
        # routing/direction the toolbar toggles left on it
        tree = getattr(self._diagram.source, "value", None)
        layout = (tree.layoutOptions or {}) if tree is not None else {}
        _prepare_root(
            root,
            layout={"elk.spacing.labelNode": "0"},
            routing=layout.get("elk.edgeRouting", "ORTHOGONAL"),
            direction=layout.get("elk.direction", "RIGHT"),
            id_salt=_collapse_salt(self.levels, self.folded),
        )
        # what ipyelk.from_element applied to the birth tree (label
        # placement defaults above all) -- the rebuilt tree must match it
        ipyelk.ElementLoader().apply_layout_defaults(root)
        self._diagram._lgn_rel_edges = {
            str(edge.id): rel for edge, rel in builder.rel_edges if edge.id is not None
        }
        self._refresh_maps(root, builder)
        source = self._diagram.source
        source.value = root
        # the WHOLE pipeline shares this one element index (ipyelk wires
        # every endpoint to the source's MarkIndex): built for the old
        # tree, it cannot be UPDATED with the rebuilt tree's ids -- a
        # mid-flight text-sizer persist() would die on the first new id.
        # Dropping it makes every persist()/build_index() rebuild from
        # whatever value is current, so racing browser roundtrips settle
        # instead of erroring.
        source.index.elements = None
        if self.tee is not None:
            # mark the inlet dirty and MERGE with the pending flow (see
            # EdgeRoutingTool.apply), then refresh through on_done
            tee_inlet = self.tee.inlet
            tee_inlet.flow = tuple(dict.fromkeys((*tee_inlet.flow, *self.reports)))
            if callable(self.on_done):
                self.on_done()

    def _refresh_maps(self, root: Node | None, builder: _StructureBuilder) -> None:
        """Rebuild the per-tree lookaside maps: which drawn nodes can row
        their members (the cycle skips 'partial' where it changes
        nothing), and which header LABEL ids belong to which (node,
        compartment) -- the browser reports fold clicks by header id."""

        self._rowable = {
            el.qualified_name: _collapsible(el)
            for el in builder.nodes_elements()
            if el.qualified_name
        }
        self._headers: dict[str, tuple[str, str]] = {}
        for node in _walk_nodes(root) if root is not None else ():
            if not node.id:
                continue
            for label in node.labels or []:
                if "sysml-comp-label" in (label.properties.cssClasses or "") and label.id:
                    self._headers[str(label.id)] = (str(node.id), _section_of(label.text or ""))

    # -- the toolbar button: cycle the selected node ---------------------------

    def _order(self, qname: str) -> tuple[str, ...]:
        """The level cycle for one node: partial participates only where
        it would CHANGE the rendition (the node rows something and the
        diagram is not already rows-wide)."""

        if self._options.get("parts") == "rows" or not self._rowable.get(qname, False):
            return ("expanded", "collapsed")
        return _LEVELS

    def cycle(self, *qnames: str) -> None:
        """Cycle each named node one level down (expanded -> partial ->
        collapsed -> expanded), skipping levels that change nothing.  A
        compartment ROW of a shrunken node cycles its owner (the row IS
        that child's collapsed presentation); nodes with nothing to
        collapse are no-ops."""

        tree = getattr(self._diagram.source, "value", None)
        if tree is None:
            return
        nodes = {str(node.id): node for node in _walk_nodes(tree) if node.id}
        levels = dict(self.levels)
        for qname in qnames:
            target = qname
            if target not in levels and target not in nodes:
                # a row under a shrunken node: cycle the owner instead
                owner = next((name for name in levels if target.startswith(f"{name}::")), None)
                if owner is None:
                    continue
                target = owner
            node = nodes.get(target)
            current = levels.get(target, "expanded")
            if current == "expanded" and (node is None or not self._has_content(node)):
                continue  # nothing to collapse
            order = self._order(target)
            position = order.index(current) if current in order else 0
            after = order[(position + 1) % len(order)]
            if after == "expanded":
                levels.pop(target, None)
            else:
                levels[target] = after
        if levels != dict(self.levels):
            self.levels = levels  # the observer applies

    @staticmethod
    def _has_content(node: Node) -> bool:
        """Whether the smallest rendition differs from what is drawn:
        the node shows children or a compartment stack.  (Boundary port
        squares do not count -- they survive every level.)"""

        if node.children:
            return True
        return any(
            "sysml-comp-label" in (label.properties.cssClasses or "") for label in node.labels or []
        )

    def _cycle_selected(self, *_: Any) -> None:
        ids = tuple(getattr(self.selection, "ids", None) or ())
        self.cycle(*(str(i) for i in ids if not str(i).startswith(_SYNTH_ID_PREFIX)))

    def _build_ui(self) -> Any:
        # the stock tool's look; structure_diagram compacts it to the
        # icon button when the longeron toolbar is active
        btn = W.Button(description="Toggle Collapsed")
        btn.on_click(self._cycle_selected)
        return btn

    # -- header clicks: per-compartment folds ----------------------------------

    def fold(self, qname: str, section: str, folded: bool = True) -> None:
        """Fold (or unfold) ONE compartment of one node: the rows leave,
        the header stays (closed twist).  The node keeps its level."""

        state = {name: set(sections) for name, sections in self.folded.items()}
        sections = state.setdefault(qname, set())
        if folded:
            sections.add(section)
        else:
            sections.discard(section)
        normalized = {name: tuple(sorted(secs)) for name, secs in state.items() if secs}
        if normalized != dict(self.folded):
            self.folded = normalized  # the observer applies

    def _on_fold_click(self, change: Any) -> None:
        """A header click reported by the diagram's fit sentinel (the
        browser consumes the click BEFORE sprotty, so the selection seam
        never sees it).  Resolve the clicked header to (node,
        compartment) by the header label's id -- sprotty DOM ids end
        with the element id -- and toggle that compartment's fold."""

        try:
            report = json.loads(change["new"] or "{}")
        except ValueError:
            return
        dom_id = str(report.get("header") or "")
        found = next((entry for hid, entry in self._headers.items() if dom_id.endswith(hid)), None)
        if found is None:
            return
        qname, section = found
        self.fold(qname, section, folded=section not in self.folded.get(qname, ()))


def _install_collapse_tool(widget: Any, tool: CollapseTool, compact: bool) -> None:
    """Swap ipyelk's stock ``ToggleCollapsedTool`` for the structure
    view's :class:`CollapseTool`, in the SAME toolbar slot (the
    affordance users already know); re-assigning ``tools`` rewires
    tee/on_done for every tool (``Diagram._update_tools``).  The fold
    channel is the fit sentinel's ``fold_click`` trait (the hidden
    anywidget every diagram carries; absent without anywidget, where
    header clicks simply degrade to no-ops)."""

    tools = list(widget.tools)
    index = next(
        (i for i, existing in enumerate(tools) if isinstance(existing, ToggleCollapsedTool)),
        None,
    )
    if index is None:
        tools.append(tool)
    else:
        tools[index] = tool
    widget.tools = tuple(tools)
    if compact:  # match the longeron toolbar's icon-button look
        _iconify(
            tool.ui,
            icon="sitemap",
            tooltip=(
                "Collapse or expand the children of the selected element "
                "(cycles boxes -> 'name : Type' rows -> name only -> boxes)"
            ),
        )
    sentinel = next(
        (t.sentinel for t in widget.tools if isinstance(t, AutoFitTool) and t.sentinel is not None),
        None,
    )
    if sentinel is not None:
        sentinel.observe(tool._on_fold_click, "fold_click")


def _collapse_tool(widget: Any) -> CollapseTool:
    for tool in getattr(widget, "tools", ()):
        if isinstance(tool, CollapseTool):
            return tool
    raise ValueError(
        "per-node collapse drives a structure-diagram widget's collapse tool; this widget has none"
    )


def _collapse_qname(tool: CollapseTool, element: Any) -> str:
    """Normalize a :func:`level`/:func:`fold` argument to a qualified
    name, validating that it names something this diagram can know about
    (typos should fail loudly, not silently draw nothing): a drawn node
    of the current tree first -- synthetic scopes like the requirements
    view keep REAL qualified names on nodes their model wrap cannot
    resolve -- then the diagram's model."""

    qname = str(getattr(element, "qualified_name", None) or element)
    tree = getattr(tool._diagram.source, "value", None)
    if tree is not None and any(str(node.id) == qname for node in _walk_nodes(tree) if node.id):
        return qname
    owner: M.Element = tool._element
    while owner.owner is not None:
        owner = owner.owner
    model = owner if isinstance(owner, M.Model) else M.Model()
    try:
        Interpreter(model).resolve(qname)
    except Exception as err:
        raise ValueError(f"{qname!r} names nothing in this diagram's model") from err
    return qname


def level(widget: Any, element: Any, to: str | None = None) -> str:
    """Get or set one node's collapse level on a structure diagram.

    ``to=None`` returns the current level (``"expanded"`` when the node
    was never collapsed).  Otherwise set it: ``"expanded"`` restores the
    nested child boxes, ``"partial"`` rows the node's parts under their
    compartment headers, ``"collapsed"`` draws the smallest legal
    rendition -- the name compartment alone (see :class:`CollapseTool`).
    Accepts a model element or a qualified name; returns the resulting
    level.  The kernel mirror of the toolbar's collapse button.
    """

    tool = _collapse_tool(widget)
    qname = _collapse_qname(tool, element)
    if to is None:
        return str(tool.levels.get(qname, "expanded"))
    if to not in _LEVELS:
        choices = ", ".join(_LEVELS)
        raise ValueError(f"a collapse level must be one of {choices}; not {to!r}")
    levels = dict(tool.levels)
    if to == "expanded":
        levels.pop(qname, None)
    else:
        levels[qname] = to
    tool.levels = levels
    return to


def fold(widget: Any, element: Any, section: str, folded: bool = True) -> None:
    """Fold (or unfold, with ``folded=False``) ONE compartment of one
    node on a structure diagram: the compartment's rows leave, its
    header stays with the closed twist, and the node keeps its collapse
    level.  ``section`` is the spec compartment name exactly as the
    header writes it ('attributes', 'parts', 'constraints', ...).  The
    kernel mirror of clicking the header row in the browser.
    """

    tool = _collapse_tool(widget)
    qname = _collapse_qname(tool, element)
    if section not in _SECTION_RANK:
        known = ", ".join(_SECTION_ORDER)
        raise ValueError(f"unknown compartment {section!r}; the spec compartments are: {known}")
    tool.fold(qname, section, folded=folded)


# ---------------------------------------------------------------------------
# state view
# ---------------------------------------------------------------------------


def state_diagram(
    machine: M.Definition | M.Usage,
    *,
    submachine_depth: int | None = None,
    toolbar: bool = True,
    routing: str = "orthogonal",
    direction: str = "right",
    max_label_width: float | None = _MAX_LABEL_WIDTH,
    height: str | None = None,
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
    picks the edge routing style (orthogonal / polyline / splines);
    ``direction`` the layout flow (``"right"`` or ``"down"``);
    ``max_label_width`` caps compartment-row display width exactly like
    :func:`structure_diagram` (state boxes carry no rows today, so the
    cap is future-proofing); ``height`` pins the widget's rendered height
    to a CSS length exactly like :func:`structure_diagram` (default: the
    400px-floor bare-cell behavior).

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
    if max_label_width is not None:
        _ellipsize_rows(root, max_label_width)
    widget = _finish(root, toolbar=toolbar, routing=routing, direction=direction, height=height)
    options: dict[str, Any] = (
        {} if submachine_depth is None else {"submachine_depth": submachine_depth}
    )
    if max_label_width != _MAX_LABEL_WIDTH:
        options["max_label_width"] = max_label_width
    return _stamp_view_state(widget, machine, "state", options)


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
    direction: str = "right",
    max_label_width: float | None = _MAX_LABEL_WIDTH,
    height: str | None = None,
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
    (orthogonal / polyline / splines); ``direction`` the layout flow
    (``"right"``, the flow-reading default, or ``"down"``).
    ``max_label_width`` caps compartment-row display width exactly like
    :func:`structure_diagram` (behavior boxes carry no rows today, so
    the cap is future-proofing); ``height`` pins the widget's rendered
    height to a CSS length exactly like :func:`structure_diagram`
    (default: the 400px-floor bare-cell behavior).
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

    if max_label_width is not None:
        _ellipsize_rows(root, max_label_width)
    widget = _finish(
        root, direction=direction, toolbar=toolbar, layout=layout, routing=routing, height=height
    )
    options: dict[str, Any] = (
        {} if lanes is None else {"lanes": dict(lanes) if isinstance(lanes, Mapping) else lanes}
    )
    if max_label_width != _MAX_LABEL_WIDTH:
        options["max_label_width"] = max_label_width
    return _stamp_view_state(widget, action, "action", options)


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
            # a thick filled bar, PERPENDICULAR to the flow -- built for
            # the horizontal default; toolbar._orient_glyphs transposes
            # the dimensions on every direction change; fork vs join is
            # topology, the glyph is identical; edges deliberately
            # distribute along the bar (no anchor ports)
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
    badge = _adornment_label(
        f"sysml-badge sysml-badge-{form}", f"{form}-badge", _BADGE_WIDTH, _BADGE_HEIGHT
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
    Compartment ROWS carry the same identity (the projected element's
    qualified name -- an attribute usage, a part usage, a constraint...),
    so a row click arrives here exactly like a node click; port squares
    likewise.  Synthetic transport ids (edges, markers) skip resolution
    -- relationship edges resolve through the widget's ``_lgn_rel_edges``
    seam instead.
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
