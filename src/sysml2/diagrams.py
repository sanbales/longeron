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
    raise ImportError(
        "sysml2.diagrams needs ipyelk; install the vendored copy with "
        "'pip install -e vendor/ipyelk' (pixi environments include it)"
    ) from _err

from . import model as M
from .interpreter import Interpreter, _succession_plan

__all__ = [
    "SYSML_STYLE",
    "action_diagram",
    "diagram",
    "on_select",
    "state_diagram",
    "structure_diagram",
]

_KIND_STEREOTYPES = {"use_case": "use case", "enum_literal": "", "feature": ""}

SYSML_STYLE: dict[str, dict[str, str]] = {
    " rect": {"transition": "all 0.2s"},
    " .sysml-package > rect": {"fill": "#fbfbfb", "stroke": "#b0b0b0"},
    " .sysml-definition > rect": {"fill": "#eef4fb", "stroke": "#4878a8", "rx": "4"},
    " .sysml-usage > rect": {"fill": "#f4faee", "stroke": "#6a9a48", "rx": "4"},
    " .sysml-state > rect": {"fill": "#fdf6e3", "stroke": "#b58900", "rx": "12"},
    " .sysml-step > rect": {"fill": "#f2eefb", "stroke": "#6c56a8", "rx": "6"},
    " .sysml-marker > rect": {"fill": "#333333", "stroke": "#333333", "rx": "8"},
    " .sysml-stereotype > text": {"fill": "#888888", "font-size": "9px"},
    " .sysml-attribute > text": {"font-size": "10px", "fill": "#444444"},
    " .sysml-edge-specializes > path": {"stroke": "#4878a8", "stroke-dasharray": "none"},
    " .sysml-edge-typed > path": {"stroke": "#6a9a48", "stroke-dasharray": "4 2"},
    " .sysml-edge-connect > path": {"stroke": "#555555"},
    " .sysml-edge-transition > path": {"stroke": "#b58900"},
    " .sysml-edge-succession > path": {"stroke": "#6c56a8"},
    " .sysml-edge-guarded > path": {"stroke-dasharray": "6 2"},
    # arrowheads (the <use class="elkarrow"> child) must be recolored
    # separately: they inherit the theme gray from the edge <g>, not the
    # per-kind stroke we put on '> path' (see .handoff/edge-style-forensics)
    " .sysml-edge-specializes > .elkarrow": {"stroke": "#4878a8"},
    " .sysml-edge-typed > .elkarrow": {"stroke": "#6a9a48"},
    " .sysml-edge-connect > .elkarrow": {"stroke": "#555555"},
    " .sysml-edge-transition > .elkarrow": {"stroke": "#b58900"},
    " .sysml-edge-succession > .elkarrow": {"stroke": "#6c56a8"},
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
    if event:  # carried through to the SVG data-event (sysml2.replay)
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
        from .render import _measure

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
    return _finish(root)


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
