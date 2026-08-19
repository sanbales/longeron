"""In-memory model of SysML v2 elements.

This is a pragmatic subset of the SysML v2 metamodel: enough structure to
faithfully capture the constructs commonly used in textual SysML v2 models
(packages, definitions, usages, expressions, actions, states, requirements)
while staying small.  Anything the builder does not understand is preserved
verbatim as an :class:`Unsupported` element so that exports do not silently
drop content.

All elements can also be constructed programmatically::

    pkg = Package(name="Vehicles")
    part = Definition(kind="part", name="Vehicle")
    part.add(Usage(kind="attribute", name="mass", types=["Real"],
                   value=FeatureValue(Literal(1500.0))))
    pkg.add(part)
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal, get_args

from .ast import Expr
from .ast import Literal as LiteralExpr

ENTRY_SOURCE = "<entry>"  # sentinel source for entry-transitions in states

# ---------------------------------------------------------------------------
# Closed vocabularies
# ---------------------------------------------------------------------------

Visibility = Literal["public", "private", "protected"]
Direction = Literal["in", "out", "inout", "return"]
PortionKind = Literal["snapshot", "timeslice"]
ConstraintKind = Literal["assume", "require", "assert"]
TriggerKind = Literal["at", "after", "when"]
ControlNodeKind = Literal["merge", "decision", "join", "fork"]
StateActionKind = Literal["entry", "do", "exit"]

#: definition ``kind`` values map 1:1 to declaration keywords
DefinitionKind = Literal[
    "part", "item", "attribute", "port", "action", "calc", "constraint",
    "requirement", "concern", "state", "occurrence", "individual", "enum",
    "connection", "flow", "allocation", "metadata", "rendering", "case",
    "analysis", "verification", "use_case", "view", "viewpoint", "interface",
    "extended",
]

#: usage ``kind`` values; mostly declaration keywords plus a few synthetic
#: ones (``feature`` for keyword-less usages, ``enum_literal``, ...)
UsageKind = Literal[
    "part", "item", "attribute", "port", "ref", "feature", "enum",
    "enum_literal", "occurrence", "individual", "snapshot", "timeslice",
    "event", "event_occurrence", "action", "calc", "constraint",
    "requirement", "concern", "state", "case", "analysis", "verification",
    "use_case", "subject", "actor", "stakeholder", "objective",
    "connection", "binding", "interface", "allocation", "flow", "message",
    "view", "viewpoint", "rendering", "render", "satisfy", "verify",
    "frame", "include", "extended",
]

DEFINITION_KINDS: tuple[str, ...] = get_args(DefinitionKind)
USAGE_KINDS: tuple[str, ...] = get_args(UsageKind)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class Element:
    """Base class for every model element."""

    name: str | None = None
    short_name: str | None = None
    visibility: Visibility | None = None
    metadata: list[str] = field(default_factory=list)  # '#keyword' prefixes
    owner: Element | None = field(default=None, repr=False, compare=False)

    @property
    def label(self) -> str:
        return self.name or self.short_name or f"<anonymous {type(self).__name__}>"

    @property
    def qualified_name(self) -> str | None:
        own = self.name or self.short_name
        if own is None:
            return None
        parts = [own]
        node = self.owner
        while node is not None:
            node_name = node.name or node.short_name
            if node_name:
                parts.append(node_name)
            node = node.owner
        return "::".join(reversed(parts))

    def iter_tree(self) -> Iterator[Element]:
        yield self
        for child in self.children():
            yield from child.iter_tree()

    def children(self) -> list[Element]:
        return []


@dataclass(eq=False)
class Namespace(Element):
    """An element that owns other elements."""

    members: list[Element] = field(default_factory=list)

    def add(self, *elements: Element) -> Namespace:
        for element in elements:
            element.owner = self
            self.members.append(element)
        return self

    def children(self) -> list[Element]:
        return list(self.members)

    def member_named(self, name: str) -> Element | None:
        for member in self.members:
            if name in (member.name, member.short_name):
                return member
        for member in self.members:
            if isinstance(member, Alias) and member.name == name:
                return self.member_named(member.target.split("::")[-1])
        return None

    def find(self, qualified: str) -> Element | None:
        """Naive descent through owned members by ``::``-separated path."""

        node: Element | None = self
        for part in qualified.split("::"):
            if not isinstance(node, Namespace):
                return None
            node = node.member_named(part)
            if node is None:
                return None
        return node

    @property
    def doc(self) -> str | None:
        texts = [m.text for m in self.members if isinstance(m, Documentation)]
        return "\n".join(texts) if texts else None


@dataclass(eq=False)
class Model(Namespace):
    """The root namespace of one or more parsed sources."""

    source_name: str | None = None


@dataclass(eq=False)
class Package(Namespace):
    is_library: bool = False
    is_standard: bool = False


# ---------------------------------------------------------------------------
# Relationships & annotations
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class Import(Element):
    target: str = ""
    is_namespace: bool = False  # 'X::*'
    is_recursive: bool = False  # '::**'
    is_import_all: bool = False  # 'import all ...'
    filters: list[Expr] = field(default_factory=list)  # 'import X::*[@F];'


@dataclass(eq=False)
class Alias(Element):
    target: str = ""


@dataclass(eq=False)
class Comment(Element):
    body: str = ""  # raw '/* ... */' text
    about: list[str] = field(default_factory=list)
    locale: str | None = None

    @property
    def text(self) -> str:
        return _strip_comment_body(self.body)


@dataclass(eq=False)
class Documentation(Element):
    body: str = ""  # raw '/* ... */' text
    locale: str | None = None

    @property
    def text(self) -> str:
        return _strip_comment_body(self.body)


@dataclass(eq=False)
class TextualRepresentation(Element):
    language: str = ""
    body: str = ""


@dataclass(eq=False)
class Dependency(Element):
    clients: list[str] = field(default_factory=list)
    suppliers: list[str] = field(default_factory=list)


@dataclass(eq=False)
class Unsupported(Element):
    """A construct the builder does not model; ``text`` is verbatim source."""

    text: str = ""
    rule: str = ""


def _strip_comment_body(body: str) -> str:
    text = body.strip()
    if text.startswith("/*"):
        text = text[2:]
    if text.endswith("*/"):
        text = text[:-2]
    lines = [line.strip().lstrip("*").strip() for line in text.strip().splitlines()]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Values & multiplicity
# ---------------------------------------------------------------------------


@dataclass
class FeatureValue:
    expr: Expr = field(default_factory=lambda: LiteralExpr(None))
    is_default: bool = False  # 'default ='
    is_initial: bool = False  # ':='


@dataclass
class Multiplicity:
    lower: Expr | None = None
    upper: Expr | None = None
    is_ordered: bool = False
    is_nonunique: bool = False


@dataclass
class ConnectorEnd:
    target: str = ""
    name: str | None = None  # 'name ::> target' form


# ---------------------------------------------------------------------------
# Definitions and usages
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class Definition(Namespace):
    kind: DefinitionKind = "part"
    is_abstract: bool = False
    is_variation: bool = False
    is_individual: bool = False
    is_parallel: bool = False  # state definitions
    supers: list[str] = field(default_factory=list)  # ':>' specializations
    result: Expr | None = None  # calc/constraint/case result expression


@dataclass(eq=False)
class EnumerationDefinition(Definition):
    kind: DefinitionKind = "enum"

    @property
    def literals(self) -> list[Usage]:
        return [m for m in self.members if isinstance(m, Usage) and m.kind == "enum_literal"]


@dataclass(eq=False)
class Usage(Namespace):
    kind: UsageKind = "part"
    direction: Direction | None = None
    is_abstract: bool = False
    is_variation: bool = False
    is_variant: bool = False
    is_readonly: bool = False  # 'constant'
    is_derived: bool = False
    is_ref: bool = False
    is_end: bool = False
    is_individual: bool = False
    is_parallel: bool = False  # state usages
    is_negated: bool = False  # 'assert not'
    is_exhibit: bool = False  # 'exhibit state ...'
    portion_kind: PortionKind | None = None
    types: list[str] = field(default_factory=list)  # ': T'
    subsets: list[str] = field(default_factory=list)  # ':> f'
    redefines: list[str] = field(default_factory=list)  # ':>> f'
    references: str | None = None  # '::> f'
    crosses: str | None = None  # '=> f'
    multiplicity: Multiplicity | None = None
    value: FeatureValue | None = None
    result: Expr | None = None  # calc/constraint usage result expression
    constraint_kind: ConstraintKind | None = None


@dataclass(eq=False)
class ConnectionUsage(Usage):
    kind: UsageKind = "connection"
    ends: list[ConnectorEnd] = field(default_factory=list)


@dataclass(eq=False)
class BindingConnector(Usage):
    kind: UsageKind = "binding"
    source_end: ConnectorEnd | None = None
    target_end: ConnectorEnd | None = None


@dataclass(eq=False)
class SatisfyUsage(Usage):
    """``satisfy R by system;`` / ``assert not satisfy ...``"""

    kind: UsageKind = "satisfy"
    is_assert: bool = False
    by: str | None = None


# ---------------------------------------------------------------------------
# Behavior: action statements
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class AssignmentAction(Element):
    target: str = ""  # dotted feature path
    expr: Expr = field(default_factory=lambda: LiteralExpr(None))


@dataclass(eq=False)
class IfAction(Element):
    condition: Expr = field(default_factory=lambda: LiteralExpr(True))
    then_body: list[Element] = field(default_factory=list)
    else_body: list[Element] | IfAction | None = None

    def children(self) -> list[Element]:
        extra: list[Element] = []
        if isinstance(self.else_body, IfAction):
            extra = [self.else_body]
        elif self.else_body:
            extra = list(self.else_body)
        return list(self.then_body) + extra


@dataclass(eq=False)
class WhileLoop(Element):
    condition: Expr | None = None  # None => 'loop'
    body: list[Element] = field(default_factory=list)
    until: Expr | None = None

    def children(self) -> list[Element]:
        return list(self.body)


@dataclass(eq=False)
class ForLoop(Element):
    var: str = ""
    seq: Expr = field(default_factory=lambda: LiteralExpr(None))
    body: list[Element] = field(default_factory=list)

    def children(self) -> list[Element]:
        return list(self.body)


@dataclass(eq=False)
class SendAction(Element):
    payload: Expr = field(default_factory=lambda: LiteralExpr(None))
    via: Expr | None = None
    to: Expr | None = None


@dataclass(eq=False)
class AcceptAction(Element):
    payload_name: str | None = None
    payload_types: list[str] = field(default_factory=list)
    trigger_kind: TriggerKind | None = None
    trigger: Expr | None = None
    via: Expr | None = None


@dataclass(eq=False)
class PerformAction(Element):
    target: str | None = None  # referenced action
    action: Usage | None = None  # inline 'perform action x { ... }'

    def children(self) -> list[Element]:
        return [self.action] if self.action is not None else []


@dataclass(eq=False)
class TerminateAction(Element):
    target: Expr | None = None


@dataclass(eq=False)
class ControlNode(Element):
    kind: ControlNodeKind = "merge"


@dataclass(eq=False)
class InitialNode(Element):
    target: str = ""  # 'first <target>;'


@dataclass(eq=False)
class Succession(Element):
    source: str | None = None  # None => attached to previous member
    target: str = ""
    guard: Expr | None = None
    is_else: bool = False


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class StateAction(Element):
    """``entry ...;`` / ``do ...;`` / ``exit ...;`` inside a state."""

    kind: StateActionKind = "entry"
    action: Element | None = None  # Perform/Assignment/Send/Accept or None

    def children(self) -> list[Element]:
        return [self.action] if self.action is not None else []


@dataclass(eq=False)
class TransitionUsage(Element):
    source: str | None = None
    trigger: AcceptAction | None = None
    guard: Expr | None = None
    effect: Element | None = None
    target: str = ""

    def children(self) -> list[Element]:
        out: list[Element] = []
        if self.trigger is not None:
            out.append(self.trigger)
        if self.effect is not None:
            out.append(self.effect)
        return out


# ---------------------------------------------------------------------------
# Interfaces, views, flows, metadata
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class InterfaceUsage(Usage):
    """``interface i : I connect a.p to b.q { ... }``"""

    kind: UsageKind = "interface"
    ends: list[ConnectorEnd] = field(default_factory=list)


@dataclass(eq=False)
class AllocationUsage(Usage):
    """``allocate a to b`` / ``allocation al allocate a to b``"""

    kind: UsageKind = "allocation"
    ends: list[ConnectorEnd] = field(default_factory=list)


@dataclass(eq=False)
class FlowUsage(Usage):
    """``flow of Payload from a.out to b.in`` (also message / succession flow)."""

    kind: UsageKind = "flow"
    payload: str | None = None  # payload feature rendering
    source: str | None = None
    target_end: str | None = None
    is_succession: bool = False  # 'succession flow'


@dataclass(eq=False)
class ElementFilter(Element):
    """``filter <expr>;`` in packages and views."""

    condition: Expr = field(default_factory=lambda: LiteralExpr(True))


@dataclass(eq=False)
class Expose(Element):
    """``expose X::*;`` inside a view."""

    target: str = ""
    is_namespace: bool = False
    is_recursive: bool = False
    filters: list[Expr] = field(default_factory=list)  # 'expose X::**[@F];'


@dataclass(eq=False)
class MetadataUsage(Namespace):
    """``@Safety { level = 3; }`` annotating usage (also ``metadata ...``)."""

    typed_by: str = ""
    about: list[str] = field(default_factory=list)


@dataclass(eq=False)
class MetadataValue(Element):
    """A body member of a metadata usage: ``level = 3;`` or ``:>> f = v;``."""

    redefines: str = ""
    value: FeatureValue | None = None
    nested: list[MetadataValue] = field(default_factory=list)

    def children(self) -> list[Element]:
        return list(self.nested)


__all__ = [name for name in dir() if not name.startswith("_")]
