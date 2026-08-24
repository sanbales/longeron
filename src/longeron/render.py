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

#: prefix of the SYNTHETIC element ids :func:`longeron.diagrams._assign_ids`
#: stamps on every element the builders leave unnamed (labels, edges,
#: markers, anchor ports, the root).  The ipyelk browser transport
#: serializes ``element.id`` verbatim -- ``None`` reaches the elkjs worker
#: as ``"id": null`` and the layout dies with a JsonImportException -- so
#: every element must carry a REAL id.  Anything longeron treats as a
#: model qualified name (SVG ``data-qname``, the exported title, the
#: toolbar search index) recognizes the prefix and skips these ids.
_SYNTH_ID_PREFIX = "__lgn__:"

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
    # definitions draw SQUARE corners, usages rounded (spec Definition &
    # Usage convention; plan row N2, confirmed by the printed p.65 figures)
    "sysml-definition": {"fill": "#eef4fb", "stroke": "#4878a8", "rx": "0"},
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
    # the n-ary dependency junction dot (spec errata E8): a small filled
    # circle in the dependency family hue, dashed links radiating from it
    "sysml-junction": {"fill": "#a85c78", "stroke": "#a85c78", "rx": "4"},
    # the n-ary CONNECTION junction dot (spec printed p.66): the filled
    # ball where a 3+-end `connect` meets, in the connector family gray
    "sysml-connjunction": {"fill": "#555555", "stroke": "#555555", "rx": "4"},
    # comment / documentation notes (spec printed pp.20-21): the folded-
    # corner box, drawn only at annotations=True
    "sysml-note": {"fill": "#ffffff", "stroke": "#888888", "shape": "note"},
    # "Perform Actions Swimlanes" (spec printed p.90, BNF pp.231-232):
    # dashed-boundary «performer» lane containers in the action view
    "sysml-lane": {"fill": "#ffffff", "stroke": "#888888", "rx": "8", "stroke-dasharray": "4 3"},
    # actor usages in the spec's FIGURE form (BNF printed p.244; crop
    # gt-actor.png): the stick figure is line art in the usage-family
    # green -- an actor IS a usage -- with the name below; the «actor»
    # keyword box stays available via structure_diagram(actor_style="box")
    "sysml-actor": {"fill": "#ffffff", "stroke": "#6a9a48", "shape": "actor"},
}

#: fixed-size glyph nodes: no title box, labels hang below the glyph
_GLYPH_NODE_CLASSES = (
    "sysml-marker",
    "sysml-ctrl-bar",
    "sysml-ctrl-diamond",
    "sysml-final",
    "sysml-terminate",
    "sysml-junction",
    "sysml-connjunction",
    "sysml-actor",
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
    # 'connection (with direction indication)' (spec printed p.66): the
    # connector line grows an open-V head at the target end when the
    # connection DEFINITION declares directed (sourceEnd/targetEnd) ends
    "sysml-edge-directed": {"stroke": "#555555"},
    # flow connections (errata E16/M1): solid connector-family line between
    # the border pins, small filled arrowhead at the target pin
    "sysml-edge-flow": {"stroke": "#555555"},
    # flows whose ends resolve to DRAWN port squares (spec printed p.77):
    # the port is the pin, so the line runs square-to-square with only the
    # small filled arrowhead at the target port
    "sysml-edge-portflow": {"stroke": "#555555"},
    # binding connectors (errata E15): plain solid line, '=' rides mid-span
    "sysml-edge-binding": {"stroke": "#555555"},
    # membership circles (errata E18): owned member -- solid line, TRUE
    # circle-plus at the OWNING namespace end (structure_diagram
    # membership="edges"); alias/unowned member -- solid line, hollow
    # circle at the referencing end, alias name as the edge label
    "sysml-edge-owned": {"stroke": "#555555"},
    "sysml-edge-alias": {"stroke": "#555555"},
    # portion membership (errata new row): solid line, filled ball with an
    # open-V notch at the WHOLE-occurrence end
    "sysml-edge-portion": {"stroke": "#555555"},
    # the dependency/requirement family shares ONE muted hue (plan §2.0):
    # dependency dashed client->supplier (errata E8), satisfy keyword edges
    # solid (spec keyword-arrow convention, BNF pdf 263/276)
    "sysml-edge-dependency": {"stroke": "#a85c78", "stroke-dasharray": "4 2"},
    "sysml-edge-depclient": {"stroke": "#a85c78", "stroke-dasharray": "4 2"},
    "sysml-edge-satisfies": {"stroke": "#a85c78"},
    # anonymous `allocate a to b` (spec printed p.79): solid line, open-V
    # arrow source->target, «allocate» keyword -- the keyword-arrow family
    "sysml-edge-allocate": {"stroke": "#a85c78"},
    # comment/doc anchors (spec printed pp.20-21): dashed, NO endpoint
    # glyph, neutral note gray (annotations=True only)
    "sysml-edge-anchor": {"stroke": "#888888", "stroke-dasharray": "4 2"},
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
#: * ``open`` -- two-stroke V: transitions, successions, dependency,
#:   satisfy and allocate keyword edges, and directed connections.
#: * ``pin-arrow`` -- flow connections (errata E16): a small square
#:   target-input pin straddling the border with a small FILLED arrowhead
#:   tight against it.
#: * ``filled`` -- flows attached to DRAWN port squares: the filled
#:   arrowhead alone (the port already is the pin; spec printed p.77).
#: * ``ball-notch`` -- portion membership: a filled ball with an open-V
#:   notch on the line side, at the whole-occurrence end.
#: * ``none`` -- connectors (connect/interface/binding), comment anchors,
#:   and the membership
#:   edges (whose glyphs -- diamonds and membership circles -- ride the
#:   START end) carry no head.
_EDGE_ENDS: dict[str, str] = {
    "sysml-edge-specializes": "hollow",
    "sysml-edge-typed": "hollow-colon",
    "sysml-edge-redefines": "hollow-tick",
    "sysml-edge-subsets": "hollow",
    "sysml-edge-references": "hollow-dcolon",
    "sysml-edge-member": "none",
    "sysml-edge-refmember": "none",
    "sysml-edge-connect": "none",
    "sysml-edge-directed": "open",
    "sysml-edge-flow": "pin-arrow",
    "sysml-edge-portflow": "filled",
    "sysml-edge-binding": "none",
    "sysml-edge-owned": "none",
    "sysml-edge-alias": "none",
    "sysml-edge-portion": "ball-notch",
    "sysml-edge-dependency": "open",
    "sysml-edge-depclient": "none",
    "sysml-edge-satisfies": "open",
    "sysml-edge-allocate": "open",
    "sysml-edge-anchor": "none",
    "sysml-edge-transition": "open",
    "sysml-edge-succession": "open",
}

#: cssClasses fragment -> glyph form at the SOURCE end (marker-start).
#: Membership edges put a diamond at the whole/type end (spec 8.2.3 printed
#: pp.200-201): filled black for composite part membership, hollow for
#: referential (``ref``) membership.  Flow connections put a small square
#: source-output ``pin`` on the source border (errata E16); alias edges a
#: small hollow ``circle`` at the referencing end and owned-membership
#: edges a ``circle-plus`` at the OWNING namespace end (errata E18).
_EDGE_STARTS: dict[str, str] = {
    "sysml-edge-member": "filled-diamond",
    "sysml-edge-refmember": "hollow-diamond",
    "sysml-edge-flow": "pin",
    "sysml-edge-owned": "circle-plus",
    "sysml-edge-alias": "circle",
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

#: arrowhead slenderness: every head keeps a 2:1 length:half-width ratio
#: (half-angle ~27 degrees) -- the spec figures draw slender heads, never
#: the 45-degree stocky ones (measured on gt-zoom-*.png).  The browser
#: EndpointSymbol paths derive from THESE constants too, so the pipelines
#: cannot diverge.
_HEAD_LENGTH, _HEAD_HALF = 10.0, 5.0  # closed hollow triangle family
_V_LENGTH, _V_HALF = 9.0, 4.0  # open two-stroke V
_FLOW_HEAD_LENGTH, _FLOW_HEAD_HALF = 6.0, 3.0  # small filled flow arrowhead

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

#: badge inset from the box's top-left corner: x clears the step box's
#: rounded corner (sysml-step rx = 6 -- the badge polygon must never
#: protrude past the corner arc) and the text rows start below the badge
#: strip so the «accept»/«send» keyword row is never covered.  BOTH
#: pipelines pin this same geometry (diagrams._badged_step_box pins the
#: labels for the browser; _to_elk_json passes pinned labels through).
_BADGE_INSET_X, _BADGE_INSET_Y = 6.0, 4.0
_BADGE_STRIP = _BADGE_INSET_Y + _BADGE_HEIGHT + 2.0  # first text row y

#: flow-connection pins (errata E16): small squares straddling the border
_PIN_SIZE = 8.0
_PIN_RX = 1.5

#: interconnection port squares (spec Ports, printed p.59): drawn ON the
#: owning node's border (elk.port.borderOffset straddles it); the arrow
#: inside a directed square uses the same box
_PORT_SIZE = 10.0
_PORT_RX = 2.0

#: proxy connector ends (spec printed p.67): a filled ball on the border
#: of the shallowest drawn ancestor, '.residual' path as its label
_PROXY_SIZE = 8.0

#: comment/doc note boxes: folded top-right corner depth
_NOTE_FOLD = 10.0

#: package tab (spec printed p.24): the folder tab riding the top-left of
#: the package box, flush with its top edge
_TAB_WIDTH, _TAB_HEIGHT = 30.0, 8.0

#: actor stick figure (spec BNF printed p.244; crop gt-actor.png):
#: bounding box of the figure itself (the name label hangs below);
#: proportions measured off the spec crop -- width:height = 0.45
_ACTOR_WIDTH, _ACTOR_HEIGHT = 18.0, 40.0

#: portion-membership ball (filled, open-V notch on the line side)
_BALL_RADIUS = 5.5
_BALL_MOUTH_DEG = 40.0  # notch half-angle

#: membership circles (errata E18): the owned-member circle-plus at the
#: owning end and the alias hollow circle at the referencing end share one
#: radius (the spec's p.26 figures draw both glyphs the same size)
_CIRCLE_RADIUS = 5.0

#: n-ary dependency junction dot (drawn as a tiny glyph node)
_JUNCTION_SIZE = 8.0

#: minimum straight run an orthogonally routed edge keeps before entering
#: a node, so no bend can fall within an endpoint glyph's footprint (the
#: shaft must stay collinear under the head or it visibly enters the
#: triangle's SIDE, and shaft adornments float off the turned line).  The
#: longest reach is the dcolon-adorned specialization head:
#: _HEAD_LENGTH + _ADORN_TAIL["hollow-dcolon"] = 21.2; 24 adds margin and
#: also covers every start glyph (diamonds, pins, circles).  ELK does NOT
#: inherit spacing options through INCLUDE_CHILDREN hierarchy levels, so
#: diagrams._finish restates this as elk.layered.spacing.edgeNodeBetweenLayers
#: on every compound node (elkjs otherwise falls back to its 10px default
#: inside containers -- the last bend then sits inside the 10px head).
_EDGE_END_CLEARANCE = 24.0


# ---------------------------------------------------------------------------
# endpoint-symbol tangents: pinned reference for the vendored browser view
# ---------------------------------------------------------------------------

#: mirror of ``MIN_TANGENT_LENGTH`` in the vendored browser edge view
#: (vendor/ipyelk js/sprotty/views/edge_views.tsx).  Zero-length route
#: chords make ``atan2(0, 0) == 0``: elkjs SPLINES sections duplicate
#: control points at the section knots, so a naive "adjacent segment"
#: tangent flips end symbols 180 degrees on any right-to-left end (the
#: browser drew satisfy heads pointing INTO the requirement box).  Points
#: closer together than this never serve as a tangent reference.
_MIN_TANGENT_LENGTH = 1e-3


def _route_end_angle(route: list[tuple[float, float]], end: str, reach: float) -> float:
    """Angle (radians) of a route at one end, pointing from that end point
    INTO the edge.

    PINNED REFERENCE implementation of ``routeEndAngle`` in the vendored
    browser edge view (vendor/ipyelk ``js/sprotty/views/edge_views.tsx``,
    compiled into the shipped labextension): the two must stay identical,
    and the tests exercise this copy against real elkjs section data.  The
    headless SVG renderer itself needs no angles -- its markers auto-orient
    (``orient="auto-start-reverse"``) -- so this function exists for the
    contract, not for drawing.

    Instead of the adjacent route segment -- which may be a zero-length
    spline chord (:data:`_MIN_TANGENT_LENGTH`) or a stub shorter than the
    symbol riding it (elk POLYLINE bends within a few px of the node: a
    12px membership diamond then straddles the bend, drawn axis-aligned
    while the visible shaft leaves diagonally) -- the tangent is the chord
    from the end point to the route point ``reach`` px along the route.
    Exact on straight and orthogonal ends (:data:`_EDGE_END_CLEARANCE`
    keeps bends out of a symbol's footprint there), the symbol's average
    direction otherwise.

    ``end`` is ``"source"`` or ``"target"``; ``reach`` is the symbol's
    footprint along the shaft (the length of its ipyelk ``path_offset``).
    """

    points = route if end == "source" else route[::-1]
    origin = points[0]
    distance = max(reach, _MIN_TANGENT_LENGTH)
    travelled = 0.0
    for i in range(1, len(points)):
        segment = math.dist(points[i - 1], points[i])
        if segment >= _MIN_TANGENT_LENGTH and travelled + segment >= distance:
            t = min((distance - travelled) / segment, 1.0)
            ref = (
                points[i - 1][0] + (points[i][0] - points[i - 1][0]) * t,
                points[i - 1][1] + (points[i][1] - points[i - 1][1]) * t,
            )
            return math.atan2(ref[1] - origin[1], ref[0] - origin[0])
        travelled += segment
    # route shorter than the reach: fall back to the farthest distinct point
    for point in reversed(points[1:]):
        if math.dist(origin, point) >= _MIN_TANGENT_LENGTH:
            return math.atan2(point[1] - origin[1], point[0] - origin[0])
    return 0.0


def _covered_route_points(route: list[tuple[float, float]], end: str, reach: float) -> int:
    """Number of interior route points within ``reach`` (arc length) of the
    given route end.

    PINNED REFERENCE of ``coveredRoutePoints`` in the vendored browser edge
    view (see :func:`_route_end_angle`): the browser trims the shaft by the
    end symbols' path offsets, so bends this close to an end would make the
    drawn path double back beneath the symbol (elk polyline stubs, elkjs
    spline knot duplicates); the view drops them from the path.
    """

    points = route if end == "source" else route[::-1]
    travelled = 0.0
    covered = 0
    for i in range(1, len(points) - 1):
        travelled += math.dist(points[i - 1], points[i])
        if travelled >= reach:
            break
        covered += 1
    return covered


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


def _note_points(
    width: float, height: float, fold: float = _NOTE_FOLD
) -> list[tuple[float, float]]:
    """Corner points of a comment/doc note box: the top-right corner is
    cut off (the folded corner, spec printed pp.20-21)."""

    fold = min(fold, width / 3, height / 3)
    return [
        (0, 0),
        (width - fold, 0),
        (width, fold),
        (width, height),
        (0, height),
    ]


def _note_path_d(width: float, height: float) -> str:
    """The note silhouette as ONE path: the folded-corner pentagon plus
    the crease 'L' outlining the fold triangle (the UML/SysML dog-ear).
    The browser pipeline draws this path verbatim (the vendored ipyelk
    ``Comment`` view knows only the plain 5-sided polygon -- no crease);
    the headless renderer draws the same two pieces in ``draw_node``."""

    pts = _note_points(width, height)
    fold = width - pts[1][0]
    outline = " L ".join(f"{px:g},{py:g}" for px, py in pts)
    return f"M {outline} Z M {width - fold:g},0 L {width - fold:g},{fold:g} L {width:g},{fold:g}"


def _actor_geometry(
    width: float = _ACTOR_WIDTH, height: float = _ACTOR_HEIGHT
) -> tuple[float, float, float, str]:
    """The actor stick figure (spec BNF printed p.244; crop gt-actor.png):
    head-circle parameters ``(cx, cy, r)`` plus the limbs path ``d`` (body,
    arms, legs), in the figure's local space.

    Proportions are measured off the spec crop: head center at 12.5% of
    the height with an 11.4% radius, arms crossing at 34%, crotch at
    68%, arms and leg tips spanning the full width.  Single source for
    BOTH pipelines: the browser symbol body
    (:func:`longeron.diagrams._actor_svg`) and the headless ``actor``
    shape branch draw exactly this geometry.
    """

    cx = width / 2
    cy = 0.125 * height
    r = 0.114 * height
    shoulders = cy + r  # the body hangs straight off the head
    arms = 0.34 * height
    crotch = 0.68 * height
    limbs = (
        f"M {cx:g},{shoulders:g} L {cx:g},{crotch:g} "
        f"M 0,{arms:g} L {width:g},{arms:g} "
        f"M 0,{height:g} L {cx:g},{crotch:g} L {width:g},{height:g}"
    )
    return cx, cy, r, limbs


def _port_arrow_d(direction: str, size: float = _PORT_SIZE, side: str = "WEST") -> str:
    """Path ``d`` for the direction arrow INSIDE a port square (spec Ports
    figures, printed p.59), in the square's local space.

    The arrow reads relative to the NODE INTERIOR, never absolutely: for
    a square riding the given border ``side``, ``in`` points across the
    border INTO the node, ``out`` points OUT through it, and ``inout``
    adds the second head (spec-p90: p1's in-arrow points at the node
    body, p2's out-arrow away from it).  Both pipelines draw this same
    geometry: the browser registers one symbol per (direction, side)
    (:func:`longeron.diagrams._port_symbol`), the headless renderer
    derives the side from the laid-out port position -- so the arrow
    stays correct on whatever border the port ends up on.
    """

    lo, hi, mid = 0.25 * size, 0.75 * size, size / 2
    head = 0.22 * size
    horizontal = side in ("WEST", "EAST")
    inward = 1.0 if side in ("WEST", "NORTH") else -1.0
    # the inout double-head is side-symmetric; single heads point along
    # (in) or against (out) the interior direction
    forward = 1.0 if direction == "inout" else (inward if direction == "in" else -inward)

    def pt(along: float, across: float) -> str:
        x, y = (along, across) if horizontal else (across, along)
        return f"{x:g},{y:g}"

    tip, tail = (hi, lo) if forward > 0 else (lo, hi)
    back = tip - forward * head
    d = (
        f"M {pt(tail, mid)} L {pt(tip, mid)} "
        f"M {pt(back, mid - head)} L {pt(tip, mid)} L {pt(back, mid + head)}"
    )
    if direction == "inout":
        barb = tail + forward * head
        d += f" M {pt(barb, mid - head)} L {pt(tail, mid)} L {pt(barb, mid + head)}"
    return d


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


def _start_marker_id(form: str, stroke: str) -> str:
    """Marker-start ids per _EDGE_STARTS form."""

    if form in ("filled-diamond", "hollow-diamond"):
        return _diamond_id(stroke, hollow=form == "hollow-diamond")
    return f"start-{form}-{stroke.lstrip('#')}"  # pin / circle


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
    Head geometry derives from the shared slenderness constants
    (``_HEAD_LENGTH``/``_HEAD_HALF``, 2:1 like the spec figures).
    """

    tail = _ADORN_TAIL[form]
    height = 2 * _HEAD_HALF + 2
    mid = _HEAD_HALF + 1
    width = _HEAD_LENGTH + 2 + tail
    back, tip = 1 + tail, 1 + tail + _HEAD_LENGTH
    bits = [
        f'<marker id="{_marker_id(form, stroke)}" viewBox="0 0 {width:g} {height:g}" '
        f'refX="{tip:g}" refY="{mid:g}" markerWidth="{width:g}" markerHeight="{height:g}" '
        f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        f'<path d="M {back:g} 1 L {tip:g} {mid:g} L {back:g} {height - 1:g} z" fill="#ffffff" '
        f'stroke="{stroke}" stroke-width="1.2"/>'
    ]
    if form in ("hollow-colon", "hollow-dcolon"):
        near = back - _ADORN_GAP - _DOT_RADIUS
        columns = [near] if form == "hollow-colon" else [near, near - _DCOLON_SPACING]
        bits += [
            f'<circle cx="{cx:g}" cy="{cy:g}" r="{_DOT_RADIUS:g}" fill="{stroke}"/>'
            for cx in columns
            for cy in (mid - _DOT_OFFSET, mid + _DOT_OFFSET)
        ]
    elif form == "hollow-tick":
        x = back - _ADORN_GAP - 0.7
        bits.append(
            f'<path d="M {x:g} {mid - _TICK_HALF:g} L {x:g} {mid + _TICK_HALF:g}" '
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


def _pin_marker(stroke: str) -> str:
    """The flow source-output pin (errata E16): a small hollow square whose
    center rides the line START -- the line starts ON the node border, so
    the square straddles it."""

    size = _PIN_SIZE
    box = size + 2
    mid = box / 2
    return (
        f'<marker id="{_start_marker_id("pin", stroke)}" viewBox="0 0 {box:g} {box:g}" '
        f'refX="{mid:g}" refY="{mid:g}" markerWidth="{box:g}" markerHeight="{box:g}" '
        f'markerUnits="userSpaceOnUse" orient="auto">'
        f'<rect x="1" y="1" width="{size:g}" height="{size:g}" rx="{_PIN_RX:g}" '
        f'fill="#ffffff" stroke="{stroke}" stroke-width="1.2"/></marker>'
    )


def _pin_arrow_marker(stroke: str) -> str:
    """The flow target-input pin + direction arrowhead (errata E16): the
    square's center rides the line END (the target border) and a small
    FILLED arrowhead sits tight against the square's outer edge."""

    size, alen, ahalf = _PIN_SIZE, _FLOW_HEAD_LENGTH, _FLOW_HEAD_HALF
    width = size + alen + 2
    height = size + 2
    mid = height / 2
    sq = 1 + alen  # square's near (outer) edge
    return (
        f'<marker id="{_marker_id("pin-arrow", stroke)}" '
        f'viewBox="0 0 {width:g} {height:g}" '
        f'refX="{sq + size / 2:g}" refY="{mid:g}" markerWidth="{width:g}" '
        f'markerHeight="{height:g}" markerUnits="userSpaceOnUse" '
        f'orient="auto-start-reverse">'
        f'<path d="M 1 {mid - ahalf:g} L {sq:g} {mid:g} L 1 {mid + ahalf:g} z" '
        f'fill="{stroke}" stroke="none"/>'
        f'<rect x="{sq:g}" y="1" width="{size:g}" height="{size:g}" rx="{_PIN_RX:g}" '
        f'fill="#ffffff" stroke="{stroke}" stroke-width="1.2"/></marker>'
    )


def _filled_v_marker(stroke: str) -> str:
    """The filled flow arrowhead for port-attached flows (spec printed
    p.77): the drawn port square already is the pin, so the marker is the
    small filled triangle alone, tight against the square."""

    v_l, v_h = _V_LENGTH, _V_HALF
    return (
        f'<marker id="{_marker_id("filled", stroke)}" viewBox="0 0 {v_l + 1:g} {2 * v_h + 2:g}" '
        f'refX="{v_l:g}" refY="{v_h + 1:g}" markerWidth="{v_l + 1:g}" '
        f'markerHeight="{2 * v_h + 2:g}" markerUnits="userSpaceOnUse" '
        f'orient="auto-start-reverse">'
        f'<path d="M 0 1 L {v_l:g} {v_h + 1:g} L 0 {2 * v_h + 1:g} z" '
        f'fill="{stroke}" stroke="none"/></marker>'
    )


def _ball_marker(stroke: str) -> str:
    """Portion membership (errata new row): a FILLED ball with an open-V
    notch on the line side, at the whole-occurrence end.  The notch vertex
    sits at the ball center; the line runs under the open mouth and reads
    as ending at the vertex (gt-portion.png)."""

    r = _BALL_RADIUS
    box = 2 * r + 2
    cx = cy = r + 1
    rad = math.radians(_BALL_MOUTH_DEG)
    px = cx - r * math.cos(rad)
    py = r * math.sin(rad)
    return (
        f'<marker id="{_marker_id("ball-notch", stroke)}" viewBox="0 0 {box:g} {box:g}" '
        f'refX="{cx + r:g}" refY="{cy:g}" markerWidth="{box:g}" markerHeight="{box:g}" '
        f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        f'<path d="M {cx:g} {cy:g} L {px:.2f} {cy - py:.2f} '
        f'A {r:g} {r:g} 0 1 1 {px:.2f} {cy + py:.2f} z" '
        f'fill="{stroke}" stroke="none"/></marker>'
    )


def _circle_marker(stroke: str) -> str:
    """Alias/unowned membership (errata E18): a small HOLLOW circle at the
    referencing end, touching the node border (marker-start)."""

    r = _CIRCLE_RADIUS
    box = 2 * r + 2
    mid = r + 1
    return (
        f'<marker id="{_start_marker_id("circle", stroke)}" viewBox="0 0 {box:g} {box:g}" '
        f'refX="1" refY="{mid:g}" markerWidth="{box:g}" markerHeight="{box:g}" '
        f'markerUnits="userSpaceOnUse" orient="auto">'
        f'<circle cx="{mid:g}" cy="{mid:g}" r="{r:g}" '
        f'fill="#ffffff" stroke="{stroke}" stroke-width="1.2"/></marker>'
    )


def _circle_plus_marker(stroke: str) -> str:
    """Owned membership (errata E18): a small hollow circle-plus at the
    OWNING namespace end, touching the node border (marker-start).  A TRUE
    circled plus (spec printed p.26): both cross strokes span the FULL
    diameter, so each stroke endpoint sits exactly ON the circle -- never
    a floating '+' inside the circle."""

    r = _CIRCLE_RADIUS
    box = 2 * r + 2
    mid = r + 1
    return (
        f'<marker id="{_start_marker_id("circle-plus", stroke)}" '
        f'viewBox="0 0 {box:g} {box:g}" '
        f'refX="1" refY="{mid:g}" markerWidth="{box:g}" markerHeight="{box:g}" '
        f'markerUnits="userSpaceOnUse" orient="auto">'
        f'<circle cx="{mid:g}" cy="{mid:g}" r="{r:g}" '
        f'fill="#ffffff" stroke="{stroke}" stroke-width="1.2"/>'
        f'<path d="M 1 {mid:g} L {box - 1:g} {mid:g} M {mid:g} 1 L {mid:g} {box - 1:g}" '
        f'fill="none" stroke="{stroke}" stroke-width="1.2"/></marker>'
    )


def _arrow_defs() -> str:
    """Markers per glyph form and edge color (see ``_EDGE_ENDS`` /
    ``_EDGE_STARTS``).

    Open V heads for every edge color (plus the default gray and the
    replay fired-edge orange -- longeron.replay swaps fired edges to that
    marker id, so it must stay defined); closed hollow triangles -- plain
    and shaft-adorned, white-filled so they occlude the line underneath --
    for the specialization family; flow pin(+arrowhead) squares and the
    portion ball at the target end; filled/hollow diamonds, source pins,
    alias circles and owned-membership circle-pluses at the START end.
    ``userSpaceOnUse`` keeps heads a
    constant size when a stylesheet widens the path stroke (e.g. the
    replay fired-edge highlight).
    """

    open_strokes = sorted(
        {style["stroke"] for style in _EDGE_STYLES.values()} | {"#666666", _FIRED_STROKE}
    )
    v_l, v_h = _V_LENGTH, _V_HALF
    markers = [
        f'<marker id="{_arrow_id(stroke)}" viewBox="0 0 {v_l + 1:g} {2 * v_h + 2:g}" '
        f'refX="{v_l:g}" '
        f'refY="{v_h + 1:g}" markerWidth="{v_l + 1:g}" markerHeight="{2 * v_h + 2:g}" '
        f'markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
        f'<path d="M 0 1 L {v_l:g} {v_h + 1:g} L 0 {2 * v_h + 1:g}" fill="none" '
        f'stroke="{stroke}" '
        f'stroke-width="1.4"/></marker>'
        for stroke in open_strokes
    ]
    for form in ("hollow", "hollow-colon", "hollow-tick", "hollow-dcolon"):
        strokes = sorted(
            {style["stroke"] for css, style in _EDGE_STYLES.items() if _EDGE_ENDS.get(css) == form}
        )
        markers += [_hollow_marker(form, stroke) for stroke in strokes]
    end_factories = {
        "pin-arrow": _pin_arrow_marker,
        "ball-notch": _ball_marker,
        "filled": _filled_v_marker,
    }
    for form, factory in end_factories.items():
        strokes = sorted(
            {style["stroke"] for css, style in _EDGE_STYLES.items() if _EDGE_ENDS.get(css) == form}
        )
        markers += [factory(stroke) for stroke in strokes]
    for start_form, hollow in (("filled-diamond", False), ("hollow-diamond", True)):
        strokes = sorted(
            {
                style["stroke"]
                for css, style in _EDGE_STYLES.items()
                if _EDGE_STARTS.get(css) == start_form
            }
        )
        markers += [_diamond_marker(stroke, hollow) for stroke in strokes]
    start_factories = {
        "pin": _pin_marker,
        "circle": _circle_marker,
        "circle-plus": _circle_plus_marker,
    }
    for start_form, start_factory in start_factories.items():
        strokes = sorted(
            {
                style["stroke"]
                for css, style in _EDGE_STYLES.items()
                if _EDGE_STARTS.get(css) == start_form
            }
        )
        markers += [start_factory(stroke) for stroke in strokes]
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
        # synthetic transport ids (stamped for the BROWSER pipeline, see
        # _SYNTH_ID_PREFIX) stay out of the headless ELK JSON: the compact
        # _n# ids keep it byte-identical to the pre-stamping output
        if node.id and not str(node.id).startswith(_SYNTH_ID_PREFIX):
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
        # nodes with DRAWN ports (css-bearing squares/proxy dots) are sized
        # by ELK like containers: their port labels place INSIDE the box
        # (spec Ports figures), so the box must grow around them
        # (PORT_LABELS) -- a snug pre-sized leaf cannot know that width
        drawn_ports = any(
            (port.properties.cssClasses or "") for port in getattr(node, "ports", None) or []
        )
        elk_sized = has_children or drawn_ports

        # place labels manually: a snug vertical stack (the browser pipeline
        # measures real glyphs; headless we control the geometry ourselves)
        labels = []
        cursor = 5.0
        measured = []
        for label in node.labels or []:
            text = label.text or ""
            label_css = label.properties.cssClasses or ""
            shape = label.properties.shape
            pre_sized = "sysml-badge" in label_css or "sysml-tab" in label_css
            if pre_sized and shape is not None and shape.width:
                # accept/send badges + the package tab: pre-sized glyph
                # labels, no text
                measured.append((text, label_css, float(shape.width), float(shape.height or 12)))
            else:
                measured.append((text, label_css, *_measure(text, label_css)))
        max_width = max((m[2] for m in measured), default=0.0)
        for index, ((text, label_css, width, height), label) in enumerate(
            zip(measured, node.labels or [], strict=True)
        ):
            is_attribute = "sysml-attribute" in label_css
            entry: dict[str, Any] = {
                "id": f"{identifier}.l{index}",
                "text": text,
                "width": width,
                "height": height,
                "properties": {"cssClasses": label_css},
            }
            if "sysml-tab" in label_css:
                # the package folder tab (spec printed p.24): containers
                # carry the OUTSIDE placement through to ELK, which
                # reserves the space above the box; fixed-size leaves pin
                # it manually, flush with the top-left corner (ELK leaves
                # constraint-free leaf labels untouched)
                if elk_sized:
                    entry["layoutOptions"] = dict(label.layoutOptions or {})
                else:
                    entry["x"], entry["y"] = 0.0, -height
                labels.append(entry)
                continue  # rides the border; never advances the text stack
            if label.x is not None and label.y is not None:
                # pinned labels (the accept/send badge and its text rows):
                # the geometry is computed ONCE in diagrams._badged_step_box
                # and serves both pipelines verbatim -- badge inset clear of
                # the rounded corner, text rows below the badge strip
                entry["x"], entry["y"] = float(label.x), float(label.y)
                labels.append(entry)
                continue
            if is_marker:  # keep the dot small; hang the label below it
                entry["x"] = ((node.width or 14) - width) / 2
                entry["y"] = (node.height or 14) + 2 + index * height
            elif elk_sized:
                # containers (and ported boxes): leave x/y to ELK, which
                # centers the title against the FINAL box (children and
                # inside port labels decide the width).
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
        ports = []
        for port in getattr(node, "ports", None) or []:
            port_data: dict[str, Any] = {
                "id": node_id(port),
                "width": port.width or 0,
                "height": port.height or 0,
                "layoutOptions": dict(port.layoutOptions or {}),
            }
            # boundary port squares (interconnection ports, proxy dots)
            # carry css + pre-sized labels; the invisible convergence
            # anchors keep their bare three-key form (byte-identical ELK
            # JSON for diagrams without drawn ports)
            port_css = port.properties.cssClasses or ""
            if port_css:
                port_data["properties"] = {"cssClasses": port_css}
            port_labels = []
            for lindex, label in enumerate(port.labels or []):
                text = label.text or ""
                label_css = label.properties.cssClasses or ""
                width, height = _measure(text, label_css)
                port_labels.append(
                    {
                        "id": f"{node_id(port)}.l{lindex}",
                        "text": text,
                        "width": width,
                        "height": height,
                        "properties": {"cssClasses": label_css},
                    }
                )
            if port_labels:
                port_data["labels"] = port_labels
            ports.append(port_data)
        if ports:
            # boundary squares and invisible anchor points (e.g. the
            # control-glyph convergence ports): elkjs places them; only
            # the css-bearing ones are drawn
            data["ports"] = ports
        if is_marker or node.width:
            data["width"] = node.width or 14
            data["height"] = node.height or 14
        elif elk_sized:
            # reserve the label block, then let ELK size around the children
            # and center the title labels; a minimum width keeps wide labels
            # inside the box.  Ported boxes additionally grow around their
            # INSIDE port labels (PORT_LABELS; spec Ports figures write the
            # ``name : Type`` labels within the part body)
            data["layoutOptions"]["elk.nodeLabels.placement"] = "H_CENTER V_TOP INSIDE"
            data["layoutOptions"]["elk.padding"] = "[top=8,left=12,bottom=12,right=12]"
            data["layoutOptions"]["elk.nodeSize.constraints"] = (
                "NODE_LABELS PORTS PORT_LABELS MINIMUM_SIZE"
                if drawn_ports
                else "NODE_LABELS MINIMUM_SIZE"
            )
            data["layoutOptions"]["elk.nodeSize.minimum"] = (
                f"({max_width + 20:.0f},{cursor + 20:.0f})"
            )
        else:  # leaf: snug width, uniform height (aligned boxes route
            # straighter: edges between equal-height siblings stay level)
            data["width"] = max(max_width + 16, 40.0)
            data["height"] = max(cursor + 5, 44.0)
            if "sysml-note" in css:  # notes hug their text
                data["height"] = cursor + 5.0
        edges = []
        for index, edge in enumerate(node.edges):
            edge_id = f"{identifier}.e{index}"
            # `event` rides through elkjs untouched (like cssClasses) and
            # becomes the SVG data-event attribute (longeron.replay matches
            # fired transitions against it).  Edges may anchor on invisible
            # convergence PORTS; identity (data-edge, replay keys) always
            # uses the owning NODE's id, so the replay contract is
            # port-blind.
            source_anchor, source_node = endpoint_ids(edge.source)
            target_anchor, target_node = endpoint_ids(edge.target)
            edges.append(
                {
                    "id": edge_id,
                    "sources": [source_anchor],
                    "targets": [target_anchor],
                    "labels": convert_edge_labels(edge, edge_id),
                    "properties": {
                        "cssClasses": edge.properties.cssClasses or "",
                        "event": getattr(edge.metadata, "event", None) or "",
                        "sourceNode": source_node,
                        "targetNode": target_node,
                    },
                }
            )
        if edges:
            data["edges"] = edges
        return data

    def endpoint_ids(endpoint: Any) -> tuple[str, str]:
        """(anchor id, owning-node id) for an edge endpoint: a Node is its
        own anchor; a Port anchors the edge but identity stays with its
        parent node."""

        if hasattr(endpoint, "children"):  # a Node
            identifier = node_id(endpoint)
            return identifier, identifier
        return node_id(endpoint), node_id(endpoint.get_parent())

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
                    f'fill="{style["fill"]}" stroke="none"/></g>'
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
            elif shape == "actor":
                # actor stick figure (spec BNF printed p.244; crop
                # gt-actor.png): unfilled head circle + line-art limbs, in
                # the usage-family stroke; the name label hangs below (the
                # glyph-node label path).  Geometry single-sourced with the
                # browser symbol via _actor_geometry.
                cx, cy, r, limbs = _actor_geometry(width, height)
                parts.append(
                    f"<g {qname}>"
                    f'<circle cx="{x + cx:.1f}" cy="{y + cy:.1f}" r="{r:.1f}" '
                    f'fill="{style["fill"]}" stroke="{style["stroke"]}"/>'
                    f'<path d="{limbs}" transform="translate({x:.1f},{y:.1f})" '
                    f'fill="none" stroke="{style["stroke"]}"/></g>'
                )
            elif shape == "note":
                # comment/doc note: rectangle with the top-right corner
                # folded (same polygon the browser Comment shape draws),
                # plus the fold crease
                pts = _note_points(width, height)
                fold = width - pts[1][0]
                rendered = " ".join(f"{x + px:.1f},{y + py:.1f}" for px, py in pts)
                parts.append(
                    f"<g {qname}>"
                    f'<polygon points="{rendered}" fill="{style["fill"]}" '
                    f'stroke="{style["stroke"]}" stroke-width="1.2"/>'
                    f'<path d="M {x + width - fold:.1f} {y:.1f} '
                    f'L {x + width - fold:.1f} {y + fold:.1f} L {x + width:.1f} {y + fold:.1f}" '
                    f'fill="none" stroke="{style["stroke"]}" stroke-width="1.2"/></g>'
                )
            else:
                dash_attr = ""
                node_dash = style.get("stroke-dasharray")
                if node_dash and node_dash != "none":
                    # dashed-boundary containers (the «performer» swim lanes)
                    dash_attr = f' stroke-dasharray="{node_dash}"'
                parts.append(
                    f"<rect {qname} "
                    f'x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
                    f'height="{height:.1f}" rx="{style["rx"]}" '
                    f'fill="{style["fill"]}" stroke="{style["stroke"]}"{dash_attr}/>'
                )
            for port in node.get("ports", []):
                draw_port(port, x, y, style["stroke"], width, height)
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

    def draw_port(
        port: dict, ox: float, oy: float, stroke: str, owner_w: float, owner_h: float
    ) -> None:
        """A boundary port (spec Ports, printed p.59): the square straddling
        the owner's border in the owner's stroke color, the direction arrow
        inside it -- oriented relative to the node interior, from the side
        the port was actually laid out on -- the proxy dot (printed p.67)
        as a filled ball, and the ELK-placed labels (INSIDE the owner).
        Invisible convergence anchors (no css) are never drawn."""

        css = port.get("properties", {}).get("cssClasses", "")
        if not css:
            return
        x, y = ox + port.get("x", 0), oy + port.get("y", 0)
        pw, ph = port.get("width", _PORT_SIZE), port.get("height", _PORT_SIZE)
        qname = f'data-qname="{_escape_attr(str(port.get("id")))}"'
        if "sysml-port-proxy" in css:
            parts.append(
                f'<circle {qname} cx="{x + pw / 2:.1f}" cy="{y + ph / 2:.1f}" '
                f'r="{pw / 2:.1f}" fill="{stroke}" stroke="none"/>'
            )
        else:
            bits = [
                f"<rect {qname} "
                f'x="{x:.1f}" y="{y:.1f}" width="{pw:.1f}" height="{ph:.1f}" '
                f'rx="{_PORT_RX:g}" fill="#ffffff" stroke="{stroke}" stroke-width="1.2"/>'
            ]
            for direction in ("inout", "in", "out"):  # inout first: substrings
                if f"sysml-port-{direction}" in css:
                    # which border the port landed on decides the arrow's
                    # orientation (in = INTO the node from THAT side)
                    cx = port.get("x", 0) + pw / 2
                    cy = port.get("y", 0) + ph / 2
                    reach = {
                        "WEST": abs(cx),
                        "EAST": abs(owner_w - cx),
                        "NORTH": abs(cy),
                        "SOUTH": abs(owner_h - cy),
                    }
                    side = min(reach, key=reach.__getitem__)
                    d = _port_arrow_d(direction, pw, side)
                    bits.append(
                        f'<path d="{d}" transform="translate({x:.1f},{y:.1f})" '
                        f'fill="none" stroke="{stroke}" stroke-width="1.2"/>'
                    )
                    break
            parts.append("".join(bits))
        for label in port.get("labels", []):
            draw_label(label, x, y)

    def draw_label(label: dict, ox: float, oy: float, on_edge: bool = False) -> None:
        css = label.get("properties", {}).get("cssClasses", "")
        if "sysml-tab" in css:
            # the package folder tab (spec printed p.24): a small rectangle
            # riding the top-left, flush with the box's top border
            bx, by = ox + label.get("x", 0), oy + label.get("y", 0)
            style = _NODE_STYLES["sysml-package"]
            parts.append(
                f'<rect x="{bx:.1f}" y="{by:.1f}" width="{label.get("width", _TAB_WIDTH):.1f}" '
                f'height="{label.get("height", _TAB_HEIGHT):.1f}" '
                f'fill="{style["fill"]}" stroke="{style["stroke"]}"/>'
            )
            return
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
        # "<source id>-><target id>" (qualified names for model nodes; the
        # OWNING node even when the edge anchors on a convergence port),
        # data-event the comma-joined accepted event names (or "")
        sources, targets = edge.get("sources", []), edge.get("targets", [])
        source_id = edge.get("properties", {}).get("sourceNode") or (sources[0] if sources else "")
        target_id = edge.get("properties", {}).get("targetNode") or (targets[0] if targets else "")
        data_edge = f"{source_id}->{target_id}" if sources and targets else ""
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
        if start is not None:  # source-end glyph (diamond / pin / circle)
            marker += f' marker-start="url(#{_start_marker_id(start, style["stroke"])})"'
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
    root_id = getattr(root, "id", None)
    if root_id and not str(root_id).startswith(_SYNTH_ID_PREFIX):
        return str(root_id)
    ids = [
        str(child.id)
        for child in getattr(root, "children", []) or []
        if child.id and not str(child.id).startswith(_SYNTH_ID_PREFIX)
    ]
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
