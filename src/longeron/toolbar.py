"""A compact toolbar with live search for the interactive ipyelk diagrams.

Every widget built by :mod:`longeron.diagrams` gets this toolbar by
default (pass ``toolbar=False`` there to keep ipyelk's stock text
buttons).  It reworks ipyelk's hover-revealed toolbar in place:

* the stock ``Fit`` / ``Center`` / ``Toggle Collapsed`` text buttons
  become icon-only buttons with tooltips (the underlying
  :class:`~ipyelk.tools.Tool` instances are reused, so behavior is
  exactly ipyelk's);
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
  exactly once, when its FIRST layout arrives from the browser, with a
  small padding and never zooming past 1:1 -- later relayouts
  (collapse, routing) keep the user's viewport;
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

from typing import Any, NamedTuple

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

from .render import _SYNTH_ID_PREFIX

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
    "EdgeRoutingTool",
    "apply_direction",
    "apply_routing",
    "upgrade_toolbar",
]

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
    for edge in _iter_edges(root):
        edge.sections = None
    return name


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


class AutoFitTool(Tool):
    """Fit-and-center the diagram exactly once, when its FIRST layout
    arrives from the browser.

    Diagrams used to first paint at 1:1 anchored top-left, so anything
    larger than the viewport started half off-screen until the user
    clicked Fit.  This tool watches the viewer's post-layout source tree
    (``view.source.value`` -- set by the browser-side elkjs pipe, i.e.
    exactly when the first layout settles) and answers the first arrival
    with one ``FitToScreenAction`` request: :attr:`padding` px of margin,
    zoom capped at :attr:`max_zoom` (small diagrams center at natural
    size instead of blowing up), no animation (a snap, not a glide).

    It fires ONCE: collapse/routing relayouts keep the user's viewport.
    :meth:`request_refit` queues exactly one more fit for the NEXT layout
    arrival -- the direction toggle uses it, because a viewport framed
    for a left-to-right layout reads wrong on the top-to-bottom flip.

    Headless renders never construct tools, so they are unaffected.  The
    fit request is a widget message: if a frontend view does not exist
    yet when the first layout lands (a slow display), the message is
    dropped and the diagram simply renders as before -- a graceful
    degradation, never an error.
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

    async def run(self) -> None:  # Tool protocol; the tool is event-driven
        pass

    def request_refit(self) -> None:
        """Queue exactly one more fit, for the next layout arrival."""

        self.pending = True

    def _on_view_tree(self, change: Any) -> None:
        if change["new"] is None or not self.pending:
            return
        self.pending = False
        self.fit_count += 1
        try:
            self._diagram.view.fit(animate=False, max_zoom=self.max_zoom, padding=self.padding)
        except Exception:  # never break the render pipeline's callback
            self.log.exception("auto-fit request failed")


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
