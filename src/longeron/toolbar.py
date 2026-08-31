"""A compact toolbar with live search for the interactive ipyelk diagrams.

Every widget built by :mod:`longeron.diagrams` gets this toolbar by
default (pass ``toolbar=False`` there to keep ipyelk's stock text
buttons).  It reworks ipyelk's hover-revealed toolbar in place:

* the stock ``Fit`` / ``Center`` / ``Toggle Collapsed`` text buttons
  become icon-only buttons with tooltips (the underlying
  :class:`~ipyelk.tools.Tool` instances are reused, so behavior is
  exactly ipyelk's; on STRUCTURE views ``longeron.diagrams`` then swaps
  the stock collapse tool for its three-level
  :class:`~longeron.diagrams.CollapseTool` in the same slot);
* an :class:`EdgeRoutingTool` button CYCLES the diagram's ELK edge
  routing style -- ORTHOGONAL (the default) -> POLYLINE -> SPLINES --
  and re-lays the live diagram out through the pipeline; the active
  style persists per widget on the tool's ``routing`` trait;
* a :class:`DirectionTool` button toggles the layout flow -- RIGHT
  (left-to-right, the default) <-> DOWN (top-to-bottom) -- through the
  same refresh path; the active direction persists per widget on the
  tool's ``direction`` trait (seeded by the ``direction=`` constructor
  kwarg), and the flip queues a one-shot re-fit so the new aspect ratio
  lands centered instead of keeping a viewport framed for the old one;
* an (invisible) :class:`AutoFitTool` fits-and-centers the diagram
  when its FIRST layout arrives from the browser, with a small padding
  and never zooming past 1:1 -- later relayouts (collapse, routing)
  keep the user's viewport.  Its hidden :class:`_FitSentinel` companion
  rides INSIDE the widget's own DOM and reports the browser-side
  moments a kernel-side re-fit must answer -- a fresh sprotty view
  materializing (the first-layout fit can be dropped while the view is
  still constructing: the cropped-diagram bug), the widget's first
  reveal (background tab, ``display:none`` lifted, lazy output
  rendering), and container resizes (an HBox squeeze, a dock drag) --
  always respecting the user's pan/zoom latch, so a viewport the user
  has touched is never re-framed behind their back;
* a :class:`DiagramSearch` tool is registered: typing in its text box
  live-highlights every diagram node whose *title* or *qualified name*
  contains the query (case-insensitive), shows a ``matches/total``
  count, and offers a clear button that restores the diagram.

Search highlighting is deliberately **not** selection.  Matches are
marked by pushing ``sysml-search-hit`` / ``sysml-search-dim`` fragments
onto the elements' ``properties.cssClasses`` and force-syncing the
viewer's source (``send_state``), which re-renders without re-running
layout.  ``view.selection.ids`` is never written, so callbacks attached
via :func:`longeron.diagrams.on_select` can never fire from a search.
"""

from __future__ import annotations

from typing import Any, Literal, NamedTuple

try:
    import ipywidgets as W
    import traitlets as T
    from ipyelk.exceptions import NotFoundError
    from ipyelk.pipes import flows as F
    from ipyelk.tools import PipelineProgressBar, ToggleCollapsedTool, Tool
except ImportError as _err:  # pragma: no cover - exercised without ipyelk
    from .errors import MissingExtraError

    raise MissingExtraError(
        "longeron.toolbar",
        "ipyelk (the vendored copy)",
        command="pip install -e vendor/ipyelk",
    ) from _err

from .render import _BAR_LONG, _BAR_SHORT, _SYNTH_ID_PREFIX, _measure

__all__ = [
    "DIRECTIONS",
    "FIT_PADDING",
    "ROUTING_STYLES",
    "SEARCH_ACTIVE_CSS",
    "SEARCH_DIM_CSS",
    "SEARCH_HIT_COLOR",
    "SEARCH_HIT_CSS",
    "TOOLBAR_STYLE",
    "AutoFitTool",
    "DiagramSearch",
    "DirectionTool",
    "EdgeRouting",
    "EdgeRoutingTool",
    "LayoutDirection",
    "apply_direction",
    "apply_routing",
    "upgrade_toolbar",
]

#: the edge-routing styles a diagram view accepts (``routing=`` on every
#: view constructor; the toolbar's routing button cycles the same set).
#: The lowercase spellings are the public vocabulary; :data:`ROUTING_STYLES`
#: holds the equivalent ``elk.edgeRouting`` option values, and
#: :func:`apply_routing` normalizes case between the two.
EdgeRouting = Literal["orthogonal", "polyline", "splines"]

#: the layout flow directions a diagram view accepts (``direction=`` on
#: every view constructor; the toolbar's orientation button toggles the
#: same pair).  Lowercase is the public vocabulary; :data:`DIRECTIONS`
#: holds the ``elk.direction`` option values, and :func:`apply_direction`
#: normalizes case between the two.
LayoutDirection = Literal["right", "down"]

#: the ELK layered edge routing styles the routing button cycles through
#: (spec figures mix straight and orthogonal connectors; SPLINES rounds
#: the corners): ORTHOGONAL is elkjs layered's default and longeron's
ROUTING_STYLES = ("ORTHOGONAL", "POLYLINE", "SPLINES")

#: the layout flow directions the orientation button toggles between
#: (``elk.direction``): RIGHT is elkjs layered's default and longeron's
DIRECTIONS = ("RIGHT", "DOWN")

#: human phrasing for the direction tooltips (current state + next click)
_DIRECTION_WORDS = {"RIGHT": "left-to-right", "DOWN": "top-to-bottom"}

#: FontAwesome-4 icons showing the ACTIVE flow direction on the button
_DIRECTION_ICONS = {"RIGHT": "long-arrow-right", "DOWN": "long-arrow-down"}

#: viewport padding (px) of the one-shot initial fit: the diagram never
#: touches the viewport limits
FIT_PADDING = 24.0

#: cssClasses fragment marking a search match (node box + its labels)
SEARCH_HIT_CSS = "sysml-search-hit"
#: cssClasses fragment dimming non-matches while a search is active
SEARCH_DIM_CSS = "sysml-search-dim"
#: DOM class pinning the (hover-revealed) toolbar while a search is active
SEARCH_ACTIVE_CSS = "sysml-search-active"

#: saturated raspberry, deliberately outside the muted diagram palette
#: (blues/greens/ambers/purples in longeron.render) so hits read as
#: *search state*, never as another element kind
SEARCH_HIT_COLOR = "#d81b60"
_SEARCH_HIT_GLOW = "rgba(216, 27, 96, 0.55)"

#: keep the toolbar on screen: the labextension slides it away unless the
#: pointer hovers the widget (vendor/ipyelk/style/app.css); '!important'
#: outranks the equal-specificity ':hover' opacity rules either way
_PINNED_TOOLBAR = {
    "visibility": "visible",
    "opacity": "1 !important",
    "transform": "translateY(0)",
}

#: style rules :func:`upgrade_toolbar` merges into the diagram's scoped
#: stylesheet (ipyelk StyledWidget: keys with a leading space are
#: namespaced to this widget only)
TOOLBAR_STYLE: dict[str, dict[str, str]] = {
    # stay visible while the user types in the search box ...
    " .jp-ElkToolbar:focus-within": dict(_PINNED_TOOLBAR),
    # ... and while a search is active (match count + highlights persist)
    f" .jp-ElkToolbar.{SEARCH_ACTIVE_CSS}": dict(_PINNED_TOOLBAR),
    # hits pop: saturated outline + glow on the node box (rects already
    # transition, so highlights fade in/out smoothly)
    f" .{SEARCH_HIT_CSS} > rect": {
        "stroke": SEARCH_HIT_COLOR,
        "stroke-width": "2",
        "filter": f"drop-shadow(0 0 4px {_SEARCH_HIT_GLOW})",
    },
    # non-matches drop back subtly: the class sits on the node AND its
    # labels, so a container dims only its own chrome (box + title text)
    # while nested children keep their own hit/dim state
    f" .{SEARCH_DIM_CSS} > rect": {"opacity": "0.35"},
    f" .{SEARCH_DIM_CSS} > text": {"opacity": "0.35"},
    # edges fade as a group (path + arrowhead + label halo)
    f" .sysml-edge.{SEARCH_DIM_CSS}": {"opacity": "0.25"},
}

_BUTTON_LAYOUT = {"width": "30px", "padding": "0"}


class _SearchEntry(NamedTuple):
    """One searchable diagram node: its id plus pre-lowered haystacks."""

    node_id: str
    title: str  # lowercased node title (the un-classed label)
    qname: str  # lowercased node id (a model qualified name)


def _iter_nodes(node: Any):
    yield node
    for child in node.children:
        yield from _iter_nodes(child)


def _iter_edges(node: Any):
    yield from node.edges
    for child in node.children:
        yield from _iter_edges(child)


def apply_routing(root: Any, routing: str) -> str:
    """Set ``elk.edgeRouting`` on a diagram source tree; returns the
    normalized style name.

    The option goes on the root AND on every compound node: ELK does not
    inherit it through ``INCLUDE_CHILDREN`` hierarchy levels (elkjs routes
    a container's edges with the CONTAINER's option, so a root-only value
    leaves every nested edge orthogonal) -- restated per level, exactly
    like the edge-node clearance in :func:`longeron.diagrams._finish`.

    Any already-computed edge routes are dropped: a routing change makes
    them stale, and elkjs writes new routes INTO the old section objects
    without clearing leftover keys (an orthogonal re-route of a polyline
    section keeps the polyline ``bendPoints``), so re-laying out a laid-out
    tree would not be idempotent otherwise.
    """

    style = str(routing).strip().upper()
    if style not in ROUTING_STYLES:
        choices = ", ".join(name.lower() for name in ROUTING_STYLES)
        raise ValueError(f"routing must be one of {choices}; not {routing!r}")
    for node in _iter_nodes(root):
        if node is root or node.children:
            node.layoutOptions["elk.edgeRouting"] = style
    for edge in _iter_edges(root):
        edge.sections = None
    return style


def apply_direction(root: Any, direction: str) -> str:
    """Set ``elk.direction`` on a diagram source tree; returns the
    normalized direction name.

    ROOT-ONLY, unlike :func:`apply_routing`: elkjs DOES carry the layout
    direction into nested compounds under ``INCLUDE_CHILDREN`` (verified
    empirically -- a root-only ``DOWN`` stacks nested children vertically,
    and restating the option per level changes nothing), while the
    ``SEPARATE_CHILDREN`` packing grids keep their own default flow (they
    stay wide either way, which is what the pack-aspect chains assume).

    The per-node companions are :func:`_fit_compound_labels` (elkjs
    sizes EXPANDED compound nodes on the wrong axis under vertical flows,
    so the compartment-bearing containers get their width pinned or
    their horizontal defaults restored alongside every direction change)
    and :func:`_orient_glyphs` (direction-sensitive glyph geometry --
    fork/join bar dimensions and the fixed-side convergence anchors --
    is re-derived for the new flow axis).

    Already-computed edge routes are dropped for the same reason
    :func:`apply_routing` drops them: a direction change makes them stale,
    and elkjs writes new routes INTO old section objects without clearing
    leftover keys, so re-laying out a laid-out tree would not be
    idempotent otherwise.
    """

    name = str(direction).strip().upper()
    if name not in DIRECTIONS:
        choices = " or ".join(word.lower() for word in DIRECTIONS)
        raise ValueError(f"direction must be {choices}; not {direction!r}")
    root.layoutOptions["elk.direction"] = name
    transposed = name in ("DOWN", "UP")
    _fit_compound_labels(root, transposed=transposed)
    _orient_glyphs(root, transposed=transposed)
    for edge in _iter_edges(root):
        edge.sections = None
    return name


#: convergence-anchor port sides per flow axis: incoming edges join where
#: the flow ENTERS the glyph (west for horizontal flows, north for
#: vertical), outgoing leave where it EXITS (east/south)
_ANCHOR_SIDES = {"in": ("WEST", "NORTH"), "out": ("EAST", "SOUTH")}

#: glyph-caption placement per flow axis: the name hangs BELOW the glyph
#: for horizontal flows (edges leave east; below is clear -- the
#: ``diagrams._MARKER_LAYOUT`` construction default) and moves BESIDE it
#: (east, vertically centered) for vertical flows, where the outgoing
#: edges now leave south -- a below-hanging caption would sit exactly on
#: the fan-out.  ``render._to_elk_json`` derives the headless caption
#: x/y from the same per-label value, so both pipelines follow.
_CAPTION_PLACEMENTS = ("OUTSIDE H_CENTER V_BOTTOM", "OUTSIDE H_RIGHT V_CENTER")


def _orient_glyphs(root: Any, transposed: bool) -> None:
    """Re-derive direction-sensitive glyph geometry for the active flow.

    Three glyph families encode the flow axis in their geometry and must
    transpose with every direction change (all are built for the
    horizontal default by :mod:`longeron.diagrams`):

    * **fork/join bars** (``sysml-ctrl-bar``) are thick filled bars
      PERPENDICULAR to the flow (spec action-flow figures, printed
      pp.92/97/227): tall-and-thin for horizontal flows, wide-and-flat
      for vertical ones.  Without the transpose a T->D toggle bunches
      every edge along the bar's 6px SHORT side.

    * **convergence anchors** -- the invisible zero-size fixed-side
      ports carrying ``properties.key`` ``in``/``out`` (decision/merge
      diamonds, start/done/terminate glyphs, n-ary junction dots; see
      ``diagrams._add_anchor_ports`` / ``_add_center_anchor``) -- must
      follow the flow axis: in at west/east for horizontal flows, at
      north/south for vertical ones (edges otherwise detour around the
      glyph to reach the stale side).  A center-pulling
      ``elk.port.anchor`` (the junction dots) is re-derived on the same
      axis.  REAL drawn ports (SysML port squares) are model notation,
      not flow geometry: they carry cssClasses and no in/out key, and
      are deliberately left alone.

    * **glyph captions** (the ``_glyph_node`` name labels: fork/join
      bars, decision/merge diamonds, start/done markers, terminate,
      junction dots, actor figures) hang BELOW the glyph in horizontal
      flows but must move BESIDE it (east, centered) in vertical ones:
      with the anchors now at north/south, a below-hanging caption sits
      exactly on the outgoing fan (the maintainer repro: f/j/d/g over
      the edges after a T->D toggle).  The placement is re-derived per
      label from :data:`_CAPTION_PLACEMENTS`.

    Geometry is re-DERIVED from the constants each call (never swapped
    in place), so any toggle sequence is idempotent and a round trip
    restores the constructed tree exactly.
    """

    axis = 1 if transposed else 0
    caption = _CAPTION_PLACEMENTS[axis]
    for node in _iter_nodes(root):
        if "sysml-ctrl-bar" in (node.properties.cssClasses or ""):
            size = (_BAR_LONG, _BAR_SHORT) if transposed else (_BAR_SHORT, _BAR_LONG)
            node.width, node.height = size
        if node.layoutOptions.get("nodeLabels.placement") in _CAPTION_PLACEMENTS:
            node.layoutOptions["nodeLabels.placement"] = caption
        for label in node.labels or []:
            if (label.layoutOptions or {}).get("nodeLabels.placement") in _CAPTION_PLACEMENTS:
                label.layoutOptions["nodeLabels.placement"] = caption
        for port in node.ports:
            sides = _ANCHOR_SIDES.get(port.properties.key or "")
            if sides is None or port.properties.cssClasses:
                continue  # a real drawn port, not a convergence anchor
            port.layoutOptions["elk.port.side"] = sides[axis]
            if "elk.port.anchor" in port.layoutOptions:
                # center anchors (junction dots): pull the attachment to
                # the glyph midpoint along the NEW flow axis
                half = (node.width or 0) / 2
                offset = half if port.properties.key == "in" else -half
                port.layoutOptions["elk.port.anchor"] = (
                    f"(0,{offset:g})" if transposed else f"({offset:g},0)"
                )


#: the node-box defaults the compound-label fit restores/derives from --
#: MUST mirror ``diagrams._NODE_LAYOUT`` (``elk.nodeSize.minimum`` and the
#: left+right ``elk.padding``); pinned against it by tests/test_toolbar.py
_NODE_MINIMUM = (60.0, 44.0)
_NODE_SIDE_PADDING = 16.0  # elk.padding left=8 + right=8


def _label_width(label: Any) -> float:
    """A label's box width: the pre-sized shape when one is pinned (edge
    labels, compartment rows -- see ``diagrams._size_compartment_rows``),
    else the headless Helvetica estimate (``render._measure``) that the
    browser measurement tracks because the stylesheet pins the fonts
    (``text.elklabel`` !important).  Icon composites (a label carrying
    sub-labels) add their parts like ipyelk's ``size_nested_label``."""

    shape = label.properties.shape
    width = float(shape.width) if shape is not None and shape.width else None
    if width is None:
        width = _measure(label.text or "", label.properties.cssClasses or "")[0]
    for sublabel in label.labels or []:
        spacing = float((sublabel.layoutOptions or {}).get("org.eclipse.elk.spacing.labelLabel", 0))
        width += _label_width(sublabel) + spacing
    return width


def _inside_label_widths(node: Any) -> list[float]:
    """Box widths of the node's INSIDE-placed labels (title, stereotype,
    compartment rows).  OUTSIDE labels (package tabs, glyph captions) and
    pinned labels (empty placement -- geometry computed in diagrams) never
    drive the box width."""

    default = (node.layoutOptions or {}).get("nodeLabels.placement", "INSIDE")
    widths = []
    for label in node.labels or []:
        options = label.layoutOptions or {}
        placement = options.get(
            "org.eclipse.elk.nodeLabels.placement", options.get("nodeLabels.placement", default)
        )
        if "INSIDE" in placement:
            widths.append(_label_width(label))
    return widths


def _fit_compound_labels(root: Any, transposed: bool) -> None:
    """Keep EXPANDED compound nodes at least as wide as their compartments.

    elkjs (0.9.3) sizes a compound node under ``INCLUDE_CHILDREN`` in its
    internal left-to-right coordinate system and only transposes the
    CONTENT for vertical flows: with ``elk.direction`` DOWN/UP the
    ``NODE_LABELS`` size contribution lands on the wrong axis (the widest
    row inflates the HEIGHT while the width collapses to children +
    padding), and ``elk.nodeSize.minimum`` is applied swapped, as
    ``(height, width)``.  Leaves are sized after the transposition and
    are unaffected -- which is why a COLLAPSED node fit while the
    expanded one overflowed (the maintainer repro: QuadCopter's
    ``totalMass`` row past the border after a T->D toggle).

    So, for every node with children AND inside labels:

    * vertical flow -- drop the ``NODE_LABELS`` token (its transposed
      contribution is pure height inflation) and pin the width through
      the swapped minimum ``(min-height, widest label + side padding)``;
    * horizontal flow -- restore the ``diagrams._NODE_LAYOUT`` defaults
      (``NODE_LABELS`` sizes the box correctly there), so direction
      toggles are lossless round trips.

    The ``SEPARATE_CHILDREN`` containers (packing grids, and any node
    inheriting the option inside one) are sized by their OWN sub-run,
    which keeps the elkjs DEFAULT (horizontal) flow whatever the root
    direction (see :func:`apply_direction`) -- so they take the
    horizontal defaults even under a vertical root flow, and honor their
    own ``elk.direction`` should one ever be set.
    """

    min_width, min_height = _NODE_MINIMUM

    def fit(node: Any, run_transposed: bool, inherited_separate: bool) -> None:
        # the run that SIZES this node: its own sub-run when its effective
        # hierarchyHandling is SEPARATE_CHILDREN (elkjs resizes such a
        # compound from within, at the sub-run's flow), the enclosing
        # INCLUDE_CHILDREN run otherwise.  hierarchyHandling is inherited.
        own = node.layoutOptions.get("elk.hierarchyHandling")
        separate = own == "SEPARATE_CHILDREN" if own else inherited_separate
        if separate:
            transposed = node.layoutOptions.get("elk.direction") in ("DOWN", "UP")
        else:
            transposed = run_transposed
        widths = _inside_label_widths(node) if node.children else []
        if widths:
            options = node.layoutOptions
            constraints = (options.get("nodeSize.constraints") or "").split()
            if transposed:
                fit_width = max(min_width, max(widths) + _NODE_SIDE_PADDING)
                options["elk.nodeSize.minimum"] = f"({min_height:g}, {fit_width:g})"
                constraints = [token for token in constraints if token != "NODE_LABELS"]
            else:
                options["elk.nodeSize.minimum"] = f"({min_width:g}, {min_height:g})"
                if "NODE_LABELS" not in constraints:
                    constraints.insert(0, "NODE_LABELS")
            options["nodeSize.constraints"] = " ".join(constraints)
        # this node's run lays out its children in both cases
        for child in node.children:
            fit(child, transposed, separate)

    for child in root.children:
        fit(child, transposed, inherited_separate=False)


def _collect_entries(root: Any) -> tuple[_SearchEntry, ...]:
    """Index the element-backed nodes of a diagram source tree.

    Only nodes with an explicit ``id`` participate: :mod:`longeron.diagrams`
    assigns ids (qualified names; instance-qualified for expanded
    submachine states) to model-backed nodes only, so markers and packing
    groups never match, dim, or count.  The title is the node's un-classed
    label -- stereotype and attribute-compartment rows are not titles.
    """

    if root is None:
        return ()
    entries = []
    for node in _iter_nodes(root):
        node_id = node.id
        if not node_id or str(node_id).startswith(_SYNTH_ID_PREFIX):
            continue  # markers/packing groups: synthetic transport ids only
        title = ""
        for label in node.labels:
            if label.text and not (label.properties.cssClasses or "").strip():
                title = label.text
                break
        entries.append(_SearchEntry(node_id, title.lower(), node_id.lower()))
    return tuple(entries)


def _set_fragment(element: Any, css: str, present: bool) -> bool:
    """Add/remove one cssClasses fragment, preserving order; True if changed."""

    classes = (element.properties.cssClasses or "").split()
    if (css in classes) == present:
        return False
    if present:
        classes.append(css)
    else:
        classes.remove(css)
    element.properties.cssClasses = " ".join(classes)
    return True


def _apply_highlight(root: Any, known: frozenset[str], hits: set[str], active: bool) -> bool:
    """Mark hits / dim the rest on one element tree; True if anything changed.

    Works on both the builder's source tree (ids only on model-backed
    nodes) and the browser's post-layout tree (every element has an id,
    but only ids in ``known`` are touched).  Classes go on the node and
    its labels -- never on ``view.selection`` -- so user ``on_select``
    callbacks cannot fire.
    """

    changed = False
    for node in _iter_nodes(root):
        if not node.id or node.id not in known:
            continue  # markers, packing groups, the root, foreign nodes
        hit = active and node.id in hits
        dim = active and not hit
        for element in (node, *node.labels):
            changed |= _set_fragment(element, SEARCH_HIT_CSS, hit)
            changed |= _set_fragment(element, SEARCH_DIM_CSS, dim)
    for edge in _iter_edges(root):
        if "sysml-edge" in (edge.properties.cssClasses or "").split():
            changed |= _set_fragment(edge, SEARCH_DIM_CSS, active)
    return changed


class DiagramSearch(Tool):
    """Live search-and-highlight over a diagram's model-backed nodes.

    Typing (or setting :attr:`query`) matches a case-insensitive
    substring against every node's *title* and *qualified name* (node
    ids, so instance-qualified expanded-submachine states match too).
    All matches light up at once; everything else dims; a ``3/41``
    counter reports matches over searchable nodes.  Clearing the query
    restores the diagram exactly.

    The highlight mechanism is css-only: ``sysml-search-hit`` /
    ``sysml-search-dim`` fragments on ``properties.cssClasses``, pushed
    to the browser with ``send_state`` on the viewer's source (a
    re-render, not a re-layout).  The selection tool is never touched,
    so :func:`longeron.diagrams.on_select` callbacks cannot fire from a
    search; and if the browser replaces the view tree (e.g. after a
    collapse/relayout), the active search is re-applied automatically.
    """

    query = T.Unicode("", help="live search text; empty clears the highlight")
    match_count = T.Int(0, help="how many searchable nodes match the query")
    total_count = T.Int(0, help="how many searchable nodes the diagram has")

    def __init__(self, diagram: Any, **kwargs: Any) -> None:
        self._diagram = diagram
        self._entries = _collect_entries(diagram.source.value)
        self._known = frozenset(entry.node_id for entry in self._entries)
        super().__init__(**kwargs)
        self.total_count = len(self._entries)
        self.ui = self._build_ui()
        # the browser replaces the view tree after every relayout: keep an
        # active search applied to whatever tree is actually displayed
        diagram.view.source.observe(self._on_view_tree, "value")

    async def run(self) -> None:  # Tool protocol; search reacts to typing
        pass

    # -- matching ----------------------------------------------------------

    def _matches(self) -> tuple[bool, set[str], int]:
        query = self.query.strip().lower()
        if not query:
            return False, set(), 0
        ids: set[str] = set()
        count = 0
        for entry in self._entries:
            if query in entry.title or query in entry.qname:
                ids.add(entry.node_id)
                count += 1
        return True, ids, count

    @property
    def hit_ids(self) -> frozenset[str]:
        """The ids of the nodes the current query highlights."""

        return frozenset(self._matches()[1])

    # -- highlight application ---------------------------------------------

    def _trees(self):
        """The distinct element trees to keep in sync (source, then view)."""

        source = self._diagram.source.value
        if source is not None:
            yield source, False
        view_source = self._diagram.view.source
        if view_source is not None and view_source.value is not None:
            if view_source.value is not source:
                yield view_source.value, True

    def refresh_highlights(self) -> None:
        """Recompute matches and apply/clear highlight classes everywhere."""

        active, hits, count = self._matches()
        self.match_count = count
        view_changed = False
        for tree, is_view in self._trees():
            if _apply_highlight(tree, self._known, hits, active) and is_view:
                view_changed = True
        if view_changed:
            self._push_view()
        self._update_ui(active)

    def _push_view(self) -> None:
        """Force-sync the displayed tree: re-render without re-layout.

        ``send_state`` serializes the trait as-is and messages the
        frontend, which re-renders from the (already laid out) value --
        no pipeline run, no selection change, no layout roundtrip.
        """

        view_source = self._diagram.view.source
        if view_source is not None and view_source.value is not None:
            view_source.send_state("value")

    def _on_view_tree(self, change: Any) -> None:
        """A new (post-layout) tree arrived from the browser: re-apply."""

        tree = change["new"]
        if tree is None:
            return
        try:
            active, hits, _ = self._matches()
            if _apply_highlight(tree, self._known, hits, active):
                self._push_view()
        except Exception:  # never break the render pipeline's callback
            self.log.exception("re-applying search highlight failed")

    # -- ui ------------------------------------------------------------------

    def _build_ui(self) -> Any:
        box = W.Text(
            placeholder="search\u2026",
            tooltip=(
                "Highlight every element whose name or qualified name "
                "contains this text (case-insensitive); never changes the selection"
            ),
            continuous_update=True,
            layout={"width": "150px"},
        )
        T.link((self, "query"), (box, "value"))
        self._count_html = W.HTML(tooltip="Matching elements / searchable elements")
        self._clear_btn = W.Button(
            icon="times",
            tooltip="Clear the search and restore the diagram",
            layout={"width": "24px", "padding": "0"},
        )
        self._clear_btn.on_click(lambda *_: setattr(self, "query", ""))
        self._update_ui(active=False)
        return W.HBox(
            [box, self._count_html, self._clear_btn],
            layout={"align_items": "center", "margin": "0 0 0 8px"},
        )

    def _update_ui(self, active: bool) -> None:
        color = "var(--jp-ui-font-color2, #666)"
        if active and not self.match_count:
            color = "var(--jp-warn-color0, #9a6700)"
        self._count_html.value = (
            f'<span style="font-size: 11px; color: {color}; padding: 0 4px; '
            f'white-space: nowrap;">{self.match_count}/{self.total_count}</span>'
            if active
            else ""
        )
        self._clear_btn.layout.visibility = "visible" if active else "hidden"
        toolbar = getattr(self._diagram, "toolbar", None)
        if toolbar is not None:  # pin the hover-revealed toolbar while active
            if active:
                toolbar.add_class(SEARCH_ACTIVE_CSS)
            else:
                toolbar.remove_class(SEARCH_ACTIVE_CSS)

    @T.observe("query")
    def _on_query(self, change: Any = None) -> None:
        self.refresh_highlights()


def _iconify(button: Any, icon: str, tooltip: str) -> None:
    """Turn a stock text ToolButton into a compact icon button."""

    button.description = ""
    button.icon = icon
    button.tooltip = tooltip
    for key, value in _BUTTON_LAYOUT.items():
        setattr(button.layout, key, value)


class EdgeRoutingTool(Tool):
    """Cycle the diagram's ELK edge routing style and re-lay it out.

    SysML tools (and the spec's own figures) mix straight and orthogonal
    connectors; ELK layered supports both plus splines.  The button
    cycles ORTHOGONAL -> POLYLINE -> SPLINES -> ... and the choice
    persists per widget on the :attr:`routing` trait (default ORTHOGONAL,
    initialized from the diagram root's ``elk.edgeRouting`` so the
    ``routing=`` constructor kwarg carries through).  Setting the trait
    directly works too: either way the style lands on the root and every
    compound node (:func:`apply_routing`), the pipeline inlet is marked
    dirty with the layout-options flow, and the diagram refreshes through
    the SAME pipeline the other tools use -- a true re-layout, not a
    re-render.  Endpoint glyphs survive non-orthogonal paths in both
    pipelines: the browser rotates symbols to the endpoint segment's
    angle, the headless markers orient with ``auto-start-reverse``.
    """

    routing = T.Unicode(ROUTING_STYLES[0], help="active elk.edgeRouting style")

    def __init__(self, diagram: Any, **kwargs: Any) -> None:
        self._diagram = diagram
        self._btn: Any = None
        root = diagram.source.value
        if root is not None:
            kwargs.setdefault(
                "routing", (root.layoutOptions or {}).get("elk.edgeRouting", ROUTING_STYLES[0])
            )
        super().__init__(**kwargs)
        self.reports = (F.Node.layout_options,)
        self.ui = self._build_ui()

    async def run(self) -> None:  # Tool protocol; the button sets the trait
        pass

    @T.validate("routing")
    def _normalize_routing(self, proposal: Any) -> str:
        style = str(proposal["value"]).strip().upper()
        if style not in ROUTING_STYLES:
            choices = ", ".join(name.lower() for name in ROUTING_STYLES)
            raise T.TraitError(f"routing must be one of {choices}; not {proposal['value']!r}")
        return style

    @T.observe("routing")
    def _on_routing(self, change: Any = None) -> None:
        self.apply()

    def apply(self) -> None:
        """Push the active style onto the diagram's trees and re-lay out."""

        seen: set[int] = set()
        inlet = getattr(getattr(self._diagram, "pipe", None), "inlet", None)
        for tree in (self._diagram.source.value, getattr(inlet, "value", None)):
            if tree is None or id(tree) in seen:
                continue
            seen.add(id(tree))
            apply_routing(tree, self.routing)
        self._update_ui()
        if seen and self.tee is not None:
            # the collapse tool's refresh path: mark the inlet dirty, then
            # run the pipeline (Diagram wires on_done to Diagram.refresh).
            # MERGE with the pending flow instead of replacing it: clicking
            # while the initial ``("new",)`` flow is still unconsumed (the
            # first layout is a browser roundtrip) must not clobber it --
            # "new" is what wakes ipyelk's ValidationPipe, and a pipeline
            # that loses it can re-run forever without ever recovering
            tee_inlet = self.tee.inlet
            tee_inlet.flow = tuple(dict.fromkeys((*tee_inlet.flow, *self.reports)))
            if callable(self.on_done):
                self.on_done()

    def _cycle(self, *_: Any) -> None:
        index = ROUTING_STYLES.index(self.routing)
        self.routing = ROUTING_STYLES[(index + 1) % len(ROUTING_STYLES)]

    def _build_ui(self) -> Any:
        self._btn = W.Button(icon="share-alt", layout=dict(_BUTTON_LAYOUT))
        self._btn.on_click(self._cycle)
        self._update_ui()
        return self._btn

    def _update_ui(self) -> None:
        if self._btn is None:
            return
        upcoming = ROUTING_STYLES[(ROUTING_STYLES.index(self.routing) + 1) % len(ROUTING_STYLES)]
        self._btn.tooltip = (
            f"Edge routing: {self.routing.lower()} "
            f"(click to re-route the edges as {upcoming.lower()})"
        )


# The fit sentinel: a hidden child INSIDE every built diagram widget's
# own DOM (mounted by ``diagrams._finish`` beside the view + toolbar, so
# plain ``display(widget)`` gets it with zero consumer wiring).  It
# reports the browser-side moments a kernel-side re-fit must answer:
#
# * ``fresh`` -- a NEW sprotty view materialized as the widget's visible
#   diagram, with its layout rendered.  A fresh view paints at sprotty's
#   identity transform (top-left, 1:1), and the kernel-side auto-fit
#   that answers the first layout arrival can be DROPPED: the viewer
#   view registers its message handler asynchronously (initSprotty),
#   after the layout pipe has already reported back, so a wide diagram
#   used to come up unfitted -- CROPPED to its top-left corner.
#   Watching the DOM for the view's laid-out nodes is the reliable
#   signal that the handler exists and a fit will land.  Detection: the
#   visible sprotty host div's id changed (each view mints
#   ``sprotty_N``) and it holds ``.elknode``s; a hidden widget
#   (display:none, a background tab) is skipped until it can be
#   measured.
# * ``resized`` -- the widget changed size while visible (an HBox
#   squeezed, a dock split handle dragged, a hidden tab re-revealed,
#   lazy output rendering), debounced, and ONLY while the user has not
#   panned or zoomed since the last kernel-side auto-fit: the viewport
#   is the user's the moment they touch it (wheel = zoom, pointer drag
#   = pan; plain clicks are selection, not panning, and do not latch).
#   The kernel bumps ``fit_stamp`` after every auto-fit, which clears
#   the latch -- an untouched-since-fit viewport is exactly the fitted
#   one, so re-fitting it on resize corrects the frame without fighting
#   anyone.  A widget FIRST observed hidden re-fits on its reveal (any
#   fit that ran while it was hidden aimed at a zero-sized viewport);
#   a widget first observed visible treats that observation as the
#   baseline, not a resize.
#
# One ResizeObserver + one MutationObserver per widget -- no polling
# loops, so a notebook full of diagrams (the notation gallery renders
# ~24) stays cheap.  The sentinel also carries the diagram's FOLD
# channel: capture-phase listeners consume clicks on compartment header
# labels (text.sysml-comp-label) before sprotty can select anything and
# report them on the fold_click trait -- headers are presentation
# artifacts, and folding must never enter the model-selection seam
# (longeron.diagrams.CollapseTool resolves the reports).
_SENTINEL_ESM = """
function render({ model, el }) {
  el.style.display = "none";
  let box = null;
  let sprottyId = "";
  let interacted = false;
  let baseline = null; // last acknowledged {w, h} of the visible widget
  let hidden = false; // the widget was 0x0 on the previous observation
  let debounce = null;
  let retry = null;
  let mutations = null;
  let sizer = null;
  let downAt = null;
  let foldSeq = 0;

  const bump = (name) => {
    model.set(name, model.get(name) + 1);
    model.save_changes();
  };

  // -- fold: compartment-header clicks (CollapseTool's fold channel) --
  // Headers (text.sysml-comp-label) are presentation artifacts, not
  // model elements: their click folds ONE compartment and must never
  // reach sprotty's selection machinery.  Capture-phase listeners on
  // the widget box run before any descendant handler, so stopping
  // propagation consumes the gesture entirely (mousedown/mouseup are
  // what sprotty selects on; click is what reports the fold).
  const headerOf = (ev) =>
    ev.target instanceof Element ? ev.target.closest("text.sysml-comp-label") : null;
  const onHeaderPress = (ev) => {
    if (headerOf(ev)) {
      ev.stopPropagation();
      ev.preventDefault();
    }
  };
  const onHeaderClick = (ev) => {
    const header = headerOf(ev);
    if (!header) return;
    ev.stopPropagation();
    ev.preventDefault();
    const g = header.closest("g[id]");
    model.set(
      "fold_click",
      JSON.stringify({
        header: header.id || "",
        node: g ? g.id : "",
        text: header.textContent || "",
        n: ++foldSeq,
      }),
    );
    model.save_changes();
  };

  // -- fresh: the widget's VISIBLE sprotty view is a new one, with
  // laid-out nodes (div.sprotty is the view's HOST node -- its
  // sprotty-root CHILD shares the id prefix, so the class guard keeps
  // the match unique)
  const checkFresh = () => {
    for (const div of box.querySelectorAll('div.sprotty[id^="sprotty"]')) {
      if (!div.querySelector(".elknode")) continue; // not laid out yet
      const rect = div.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) continue; // hidden widget
      if (div.id !== sprottyId) {
        sprottyId = div.id;
        bump("fresh");
      }
      return; // one visible host per widget
    }
  };

  // -- resized: debounced, guarded by the user-viewport latch ----------
  const onResize = () => {
    const rect = box.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) {
      hidden = true; // display:none / a background tab: nothing to fit
      return;
    }
    const revealed = hidden;
    const first = baseline === null;
    const changed =
      revealed ||
      first ||
      Math.abs(rect.width - baseline.w) >= 2 ||
      Math.abs(rect.height - baseline.h) >= 2;
    baseline = { w: rect.width, h: rect.height };
    hidden = false;
    // the initial VISIBLE observation is a baseline, not a resize; but a
    // widget first seen HIDDEN re-fits on its reveal -- any fit that ran
    // while it was hidden aimed at a zero-sized viewport
    if ((first && !revealed) || !changed) return;
    clearTimeout(debounce);
    debounce = setTimeout(() => {
      if (!interacted) bump("resized");
    }, 200);
  };

  // -- the user's viewport is theirs: wheel = zoom, drag = pan ---------
  const onWheel = () => {
    interacted = true;
  };
  const onDown = (ev) => {
    downAt = { x: ev.clientX, y: ev.clientY };
  };
  const onMove = (ev) => {
    if (downAt && Math.hypot(ev.clientX - downAt.x, ev.clientY - downAt.y) > 3) {
      interacted = true; // moved while down: a pan, not a click
    }
  };
  const onUp = () => {
    downAt = null;
  };
  model.on("change:fit_stamp", () => {
    interacted = false; // the viewport is the fitted one again
  });

  const attach = () => {
    box = el.closest(".lgx-diagram");
    if (!box) {
      retry = setTimeout(attach, 200); // widget views attach asynchronously
      return;
    }
    mutations = new MutationObserver(checkFresh);
    mutations.observe(box, { childList: true, subtree: true });
    sizer = new ResizeObserver(onResize);
    sizer.observe(box);
    box.addEventListener("wheel", onWheel, { capture: true, passive: true });
    box.addEventListener("pointerdown", onDown, true);
    box.addEventListener("pointermove", onMove, true);
    box.addEventListener("pointerup", onUp, true);
    box.addEventListener("mousedown", onHeaderPress, true);
    box.addEventListener("mouseup", onHeaderPress, true);
    box.addEventListener("click", onHeaderClick, true);
    checkFresh();
    onResize();
  };
  attach();
  return () => {
    clearTimeout(debounce);
    clearTimeout(retry);
    if (mutations) mutations.disconnect();
    if (sizer) sizer.disconnect();
    if (box) {
      box.removeEventListener("wheel", onWheel, { capture: true });
      box.removeEventListener("pointerdown", onDown, true);
      box.removeEventListener("pointermove", onMove, true);
      box.removeEventListener("pointerup", onUp, true);
      box.removeEventListener("mousedown", onHeaderPress, true);
      box.removeEventListener("mouseup", onHeaderPress, true);
      box.removeEventListener("click", onHeaderClick, true);
    }
  };
}
export default { render };
"""

#: the lazily defined :class:`_FitSentinel` (anywidget is optional)
_SENTINEL_CLS: type | None = None


def _sentinel_class() -> type | None:
    """The ``_FitSentinel`` anywidget class, or ``None`` without anywidget.

    Defined lazily because anywidget is an optional extra (``replay``)
    and diagram building must keep working without it: the widgets then
    simply lose the browser-side fit-on-reveal/resize reports (the
    first-layout auto-fit still runs) -- graceful degradation, never an
    ImportError.

    Frontend -> kernel traits: ``fresh`` counts new sprotty views
    materializing as the widget's visible diagram; ``resized`` counts
    debounced widget resizes (including the first reveal of a widget
    born hidden) that happened while the user had NOT panned/zoomed
    since the last auto-fit.  :class:`AutoFitTool` answers both with one
    :meth:`AutoFitTool.refit_now`.  Kernel -> frontend: ``fit_stamp`` is
    bumped after every kernel-side auto-fit and clears the browser's
    user-interaction latch.  See :data:`_SENTINEL_ESM`.
    """

    global _SENTINEL_CLS
    if _SENTINEL_CLS is not None:
        return _SENTINEL_CLS
    try:
        import anywidget
    except ImportError:  # pragma: no cover - exercised without anywidget
        return None

    class _FitSentinel(anywidget.AnyWidget):
        """A hidden fit reporter inside the diagram widget's own DOM
        (see :func:`_sentinel_class` and :data:`_SENTINEL_ESM`)."""

        _esm = _SENTINEL_ESM

        fresh = T.Int(0, help="how many fresh diagram views appeared in the widget").tag(sync=True)
        resized = T.Int(0, help="debounced widget resizes with an untouched viewport").tag(
            sync=True
        )
        fit_stamp = T.Int(0, help="bumped per kernel auto-fit; clears the user latch").tag(
            sync=True
        )
        fold_click = T.Unicode(
            "",
            help=(
                "the last compartment-header click, as JSON {header, node, text, n} "
                "(the CollapseTool fold channel; consumed before sprotty sees the click)"
            ),
        ).tag(sync=True)

    _SENTINEL_CLS = _FitSentinel
    return _FitSentinel


class AutoFitTool(Tool):
    """Keep the diagram fitted-and-centered until the user takes over.

    Diagrams used to first paint at 1:1 anchored top-left, so anything
    larger than the viewport started half off-screen until the user
    clicked Fit.  This tool watches the viewer's post-layout source tree
    (``view.source.value`` -- set by the browser-side elkjs pipe, i.e.
    exactly when the first layout settles) and answers the first arrival
    with one ``FitToScreenAction`` request: :attr:`padding` px of margin,
    zoom capped at :attr:`max_zoom` (small diagrams center at natural
    size instead of blowing up), no animation (a snap, not a glide).

    The layout watcher fires ONCE: collapse/routing relayouts keep the
    user's viewport.  :meth:`request_refit` queues exactly one more fit
    for the NEXT layout arrival -- the direction toggle uses it, because
    a viewport framed for a left-to-right layout reads wrong on the
    top-to-bottom flip.

    The first-layout fit request is a widget message: if a frontend view
    does not exist yet when the first layout lands (a slow display, a
    lazily rendered output), the message is dropped.  That is what the
    tool's :attr:`sentinel` exists for -- a hidden anywidget the builder
    mounts INSIDE the diagram widget's own DOM whose browser half
    reports ``fresh`` views, first reveals, and untouched-viewport
    resizes (see :func:`_sentinel_class`); each report is answered with
    :meth:`refit_now`, which also bumps the sentinel's ``fit_stamp`` to
    clear the browser-side user-interaction latch.  Without anywidget
    the sentinel is ``None`` and only the first-layout fit remains.

    Headless renders never construct tools, so they are unaffected.
    """

    padding = T.Float(FIT_PADDING, help="viewport margin (px) around the fitted diagram")
    max_zoom = T.Float(1.0, help="never zoom in past this to fit (1.0 = natural size)")
    pending = T.Bool(True, help="whether the next layout arrival triggers a fit")
    fit_count = T.Int(0, help="how many fit requests this tool has sent")

    def __init__(self, diagram: Any, **kwargs: Any) -> None:
        self._diagram = diagram
        super().__init__(**kwargs)
        # the browser-side elkjs pipe writes the laid-out tree onto the
        # viewer's source; its kernel-side sync is the 'first layout
        # settled' signal (the same event DiagramSearch re-applies on)
        diagram.view.source.observe(self._on_view_tree, "value")
        # the browser-side reporter (mounted into the widget's DOM by
        # diagrams._finish); None without anywidget -- degrade gracefully
        sentinel_cls = _sentinel_class()
        self.sentinel: Any = (
            None if sentinel_cls is None else sentinel_cls(layout=W.Layout(display="none"))
        )
        if self.sentinel is not None:
            self.sentinel.observe(self._on_sentinel_report, ["fresh", "resized"])

    async def run(self) -> None:  # Tool protocol; the tool is event-driven
        pass

    def request_refit(self) -> None:
        """Queue exactly one more fit, for the next layout arrival."""

        self.pending = True

    def refit_now(self) -> None:
        """Fit immediately, without waiting for a layout arrival.

        For fits that happened into a USELESS viewport (a hidden widget
        has a zero-sized one: a docked background tab, a display:none'd
        cached diagram) or that were dropped outright (no frontend view
        yet).  Bumping the sentinel's ``fit_stamp`` afterwards clears the
        browser-side user-interaction latch: the viewport is the fitted
        one again, so a later resize may re-frame it without fighting
        anyone.
        """

        self.fit_count += 1
        try:
            self._diagram.view.fit(animate=False, max_zoom=self.max_zoom, padding=self.padding)
        except Exception:  # never break the caller's observer chain
            self.log.exception("refit request failed")
        if self.sentinel is not None:
            self.sentinel.fit_stamp += 1

    def _on_sentinel_report(self, change: Any) -> None:
        """A browser report from the widget's own DOM: re-fit, now.

        ``fresh``: a newly built diagram view materialized with its
        layout rendered -- the reliable moment to fit it (the
        first-layout auto-fit can be dropped while the view is still
        constructing).  ``resized``: the widget changed size -- or was
        revealed -- and the user has not panned/zoomed since the last
        auto-fit (guarded browser-side).
        """

        self.refit_now()

    def _on_view_tree(self, change: Any) -> None:
        if change["new"] is None or not self.pending:
            return
        self.pending = False
        self.refit_now()


class DirectionTool(Tool):
    """Toggle the diagram's layout flow and re-lay it out.

    The button toggles ``elk.direction`` RIGHT (left-to-right, the
    default) <-> DOWN (top-to-bottom) and the choice persists per widget
    on the :attr:`direction` trait (initialized from the diagram root's
    ``elk.direction``, so the ``direction=`` constructor kwarg carries
    through).  Setting the trait directly works too: either way the
    option lands on the ROOT only (:func:`apply_direction` -- unlike edge
    routing, elkjs carries the direction into nested compounds under
    ``INCLUDE_CHILDREN``), the pipeline inlet is marked dirty with the
    layout-options flow, and the diagram refreshes through the SAME
    pipeline the routing tool uses.  The flip also queues a ONE-SHOT
    re-fit (:class:`AutoFitTool`): the aspect ratio inverts, so keeping a
    viewport framed for the old flow reads worse than re-centering once.
    """

    direction = T.Unicode(DIRECTIONS[0], help="active elk.direction flow")

    def __init__(self, diagram: Any, **kwargs: Any) -> None:
        self._diagram = diagram
        self._btn: Any = None
        root = diagram.source.value
        if root is not None:
            kwargs.setdefault(
                "direction", (root.layoutOptions or {}).get("elk.direction", DIRECTIONS[0])
            )
        super().__init__(**kwargs)
        self.reports = (F.Node.layout_options,)
        self.ui = self._build_ui()

    async def run(self) -> None:  # Tool protocol; the button sets the trait
        pass

    @T.validate("direction")
    def _normalize_direction(self, proposal: Any) -> str:
        name = str(proposal["value"]).strip().upper()
        if name not in DIRECTIONS:
            choices = " or ".join(word.lower() for word in DIRECTIONS)
            raise T.TraitError(f"direction must be {choices}; not {proposal['value']!r}")
        return name

    @T.observe("direction")
    def _on_direction(self, change: Any = None) -> None:
        self.apply()

    def apply(self) -> None:
        """Push the active direction onto the diagram's trees and re-lay out."""

        seen: set[int] = set()
        inlet = getattr(getattr(self._diagram, "pipe", None), "inlet", None)
        for tree in (self._diagram.source.value, getattr(inlet, "value", None)):
            if tree is None or id(tree) in seen:
                continue
            seen.add(id(tree))
            apply_direction(tree, self.direction)
        self._update_ui()
        if seen and self.tee is not None:
            # a flip inverts the aspect ratio: queue ONE re-fit for the
            # relayout about to land (collapse/routing changes never do)
            for tool in getattr(self._diagram, "tools", ()):
                if isinstance(tool, AutoFitTool):
                    tool.request_refit()
            # the routing tool's refresh path: mark the inlet dirty and
            # MERGE with the pending flow (see EdgeRoutingTool.apply)
            tee_inlet = self.tee.inlet
            tee_inlet.flow = tuple(dict.fromkeys((*tee_inlet.flow, *self.reports)))
            if callable(self.on_done):
                self.on_done()

    def _toggle(self, *_: Any) -> None:
        index = DIRECTIONS.index(self.direction)
        self.direction = DIRECTIONS[(index + 1) % len(DIRECTIONS)]

    def _build_ui(self) -> Any:
        self._btn = W.Button(icon=_DIRECTION_ICONS[self.direction], layout=dict(_BUTTON_LAYOUT))
        self._btn.on_click(self._toggle)
        self._update_ui()
        return self._btn

    def _update_ui(self) -> None:
        if self._btn is None:
            return
        upcoming = DIRECTIONS[(DIRECTIONS.index(self.direction) + 1) % len(DIRECTIONS)]
        self._btn.icon = _DIRECTION_ICONS[self.direction]
        self._btn.tooltip = (
            f"Layout direction: {_DIRECTION_WORDS[self.direction]} "
            f"(click to re-lay out {_DIRECTION_WORDS[upcoming]})"
        )


def upgrade_toolbar(diagram: Any) -> Any:
    """Swap the stock ipyelk toolbar contents for the compact longeron one.

    Idempotent, and composed entirely from the outside: the existing
    Fit/Center/Toggle-Collapsed tools keep their behavior but lose the
    text labels (icon + tooltip instead), an :class:`EdgeRoutingTool`
    (cycles orthogonal/polyline/splines edge routing), a
    :class:`DirectionTool` (toggles left-to-right/top-to-bottom flow) and
    a
    :class:`DiagramSearch` tool are registered, and :data:`TOOLBAR_STYLE`
    is merged into the widget's scoped stylesheet (search-hit/dim rules +
    keeping the toolbar pinned while it is being used).
    """

    if any(isinstance(tool, DiagramSearch) for tool in diagram.tools):
        return diagram
    _iconify(
        diagram.view.fit_tool.ui,
        icon="expand",
        tooltip="Fit the diagram to the view (fits the selection, if any)",
    )
    _iconify(
        diagram.view.center_tool.ui,
        icon="crosshairs",
        tooltip="Center the diagram (on the selection, if any)",
    )
    try:
        toggle = diagram.get_tool(ToggleCollapsedTool)
    except NotFoundError:
        pass
    else:
        _iconify(
            toggle.ui,
            icon="sitemap",
            tooltip="Collapse or expand the children of the selected element",
        )
    try:
        progress = diagram.get_tool(PipelineProgressBar)
    except NotFoundError:
        pass
    else:
        progress.bar.tooltip = "Diagram layout pipeline progress"
        progress.bar.layout.width = "80px"
    diagram.toolbar.close_btn.tooltip = "Close"
    diagram.style = {**diagram.style, **TOOLBAR_STYLE}
    diagram.register_tool(EdgeRoutingTool(diagram))
    diagram.register_tool(DirectionTool(diagram))
    diagram.register_tool(DiagramSearch(diagram))
    return diagram
