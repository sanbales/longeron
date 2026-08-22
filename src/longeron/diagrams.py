"""Interactive SysML v2 diagrams for Jupyter, rendered with ipyelk/ELK.

Requires the vendored ipyelk (``pip install -e vendor/ipyelk``; the pixi
environments install it automatically).  Three views, one dispatcher:

* :func:`structure_diagram` -- packages, definitions (with attribute
  compartments), nested usages; specialization / typing / connection edges.
* :func:`state_diagram` -- hierarchical states, entry markers, transitions
  labeled ``trigger [guard] / effect``.
* :func:`action_diagram` -- the succession control-flow graph (the same one
  the interpreter executes), including start/done markers.
* :func:`diagram` -- picks a view based on the element's kind.

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
    from ipyelk.contrib.molds.connectors import StraightArrow, ThinArrow
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
    from ipyelk.elements.symbol import SymbolSpec
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
    _EDGE_STYLES,
    _GUARDED_DASHARRAY,
    _LABEL_STYLES,
    _NODE_STYLES,
    _measure,
)

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
    for css, node_style in _NODE_STYLES.items():
        style[f" .{css} > rect"] = dict(node_style)
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
        style[f" .{css} > .elkarrow"] = {"stroke": edge_style["stroke"]}
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
            # fill is never touched -- unfilled heads stay unfilled, filled stay
            # filled (user rule)
            " .elkedge.sysml-edge.selected > path": {"stroke": "var(--jp-elk-color-selected)"},
            " .elkedge.sysml-edge.selected > .elkarrow": {
                "stroke": "var(--jp-elk-color-selected)",
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


_MARKER_LAYOUT = {
    # place the 'start'/'done'/entry text below the dot, not on top of it
    "nodeLabels.placement": "OUTSIDE H_CENTER V_BOTTOM",
}


def _marker_node(text: str | None = None) -> Node:
    labels = []
    if text:
        label = _label(text, "sysml-stereotype")
        # ipyelk's Loader.apply_layout_defaults injects an INSIDE placement
        # onto every label without layoutOptions, and the per-LABEL value
        # overrides the node-level option -- so the outside placement must
        # live on the label itself or the text lands on top of the dot
        label.layoutOptions = dict(_MARKER_LAYOUT)
        labels.append(label)
    return Node(
        width=14,
        height=14,
        labels=labels,
        layoutOptions=dict(_MARKER_LAYOUT),
        properties=NodeProperties(cssClasses="sysml-marker"),
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


def _edge(
    source: Node,
    target: Node,
    css: str,
    text: str | None = None,
    end: str | None = None,
    event: str | None = None,
) -> Edge:
    edge = Edge(
        source=source, target=target, properties=EdgeProperties(cssClasses=f"sysml-edge {css}")
    )
    if end:
        edge.properties.shape = EdgeShape(end=end)
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


def _symbols() -> SymbolSpec:
    return SymbolSpec().add(
        StraightArrow("generalization", closed=True),
        ThinArrow("arrow"),
    )


def _finish(root: Node, style: dict | None = None, direction: str | None = None) -> Any:
    root.layoutOptions = dict(_ROOT_LAYOUT)
    if direction:
        root.layoutOptions["elk.direction"] = direction
    result = ipyelk.from_element(root)
    result.symbols = _symbols()
    result.style = dict(SYSML_STYLE if style is None else style)
    result.layout.min_height = "400px"
    return result


# ---------------------------------------------------------------------------
# structure view
# ---------------------------------------------------------------------------


def structure_diagram(
    element: M.Model | M.Namespace, *, show_attributes: bool = True, show_relationships: bool = True
) -> Any:
    """Containment structure with specialization/typing/connection edges."""

    builder = _StructureBuilder(element, show_attributes)
    root = builder.build()
    if show_relationships:
        builder.add_relationship_edges(root)
    builder.pack_components(root)
    _size_compartment_rows(root)
    return _finish(root)


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
    def __init__(self, element: M.Model | M.Namespace, show_attributes: bool):
        self.element = element
        self.show_attributes = show_attributes
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
                        root.edges.append(
                            _edge(node, target, "sysml-edge-specializes", end="generalization")
                        )
            if isinstance(element, M.Usage):
                for type_name in element.types:
                    target = self._resolve_node(type_name.lstrip("~"), element)
                    if target is not None:
                        root.edges.append(_edge(node, target, "sysml-edge-typed", end="arrow"))
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
            for source, target in itertools.pairwise(resolved):
                root.edges.append(_edge(source, target, "sysml-edge-connect", text=label))

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


# ---------------------------------------------------------------------------
# state view
# ---------------------------------------------------------------------------


def state_diagram(machine: M.Definition | M.Usage) -> Any:
    """A hierarchical state machine: states, entry markers, transitions."""

    root = Node(properties=NodeProperties(cssClasses="sysml-root"))
    _fill_states(root, machine, root)
    return _finish(root)


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


def _fill_states(container_node: Node, container: M.Definition | M.Usage, root: Node) -> None:
    states: dict[str, Node] = {}
    for member in container.members:
        if isinstance(member, M.Usage) and member.kind == "state" and member.name:
            node = _node(member, member.label, "sysml-state", "state")
            if any(isinstance(m, M.Usage) and m.kind == "state" for m in member.members):
                _fill_states(node, member, root)
            states[member.name] = node
            container_node.children.append(node)
    marker: Node | None = None
    for member in container.members:
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
                    end="arrow",
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
                    end="arrow",
                    text=_transition_text(member),
                    event=_transition_event(member),
                )
            )


# ---------------------------------------------------------------------------
# action view
# ---------------------------------------------------------------------------


def action_diagram(action: M.Definition | M.Usage) -> Any:
    """The succession control-flow graph the interpreter executes."""

    root = Node(properties=NodeProperties(cssClasses="sysml-root"))

    plan = _succession_plan(list(action.members))
    steps: dict[str, Node] = {}

    def marker(name: str) -> Node:
        node = _marker_node(name)
        root.children.append(node)
        return node

    if plan is not None:
        for name, element in plan.steps.items():
            kind = getattr(element, "kind", type(element).__name__)
            node = _node(element, name, "sysml-step", str(kind))
            steps[name] = node
            root.children.append(node)
        steps["start"] = marker("start")
        steps["done"] = marker("done")
        if plan.initial in steps:
            root.edges.append(
                _edge(steps["start"], steps[plan.initial], "sysml-edge-succession", end="arrow")
            )
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
            root.edges.append(_edge(source, target, css, end="arrow", text=text))
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
                node = _node(
                    member, title, "sysml-step", type(member).__name__.replace("Action", "")
                )
                root.children.append(node)
                root.edges.append(_edge(previous, node, "sysml-edge-succession", end="arrow"))
                previous = node
        root.edges.append(_edge(previous, marker("done"), "sysml-edge-succession", end="arrow"))

    return _finish(root, direction="RIGHT")


def _statement_title(member: M.Element) -> str:
    return _stmt_text(member)


# ---------------------------------------------------------------------------
# dispatcher & interactivity
# ---------------------------------------------------------------------------


def diagram(element: M.Model | M.Element, **kwargs: Any) -> Any:
    """Pick a view by element kind: state machines, actions, else structure."""

    kind = getattr(element, "kind", None)
    if kind == "state":
        return state_diagram(element)  # type: ignore[arg-type]
    if kind == "action":
        return action_diagram(element)  # type: ignore[arg-type]
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
