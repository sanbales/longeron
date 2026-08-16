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

from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Union

from .ast import Expr, Literal

ENTRY_SOURCE = "<entry>"  # sentinel source for entry-transitions in states


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class Element:
    """Base class for every model element."""

    name: Optional[str] = None
    short_name: Optional[str] = None
    visibility: Optional[str] = None  # 'public' | 'private' | 'protected'
    metadata: List[str] = field(default_factory=list)  # '#keyword' prefixes
    owner: Optional["Element"] = field(default=None, repr=False, compare=False)

    @property
    def label(self) -> str:
        return self.name or self.short_name or f"<anonymous {type(self).__name__}>"

    @property
    def qualified_name(self) -> Optional[str]:
        if self.name is None and self.short_name is None:
            return None
        parts = [self.name or self.short_name]
        node = self.owner
        while node is not None:
            if node.name or node.short_name:
                parts.append(node.name or node.short_name)
            node = node.owner
        return "::".join(reversed(parts))

    def iter_tree(self) -> Iterator["Element"]:
        yield self
        for child in self.children():
            yield from child.iter_tree()

    def children(self) -> List["Element"]:
        return []


@dataclass(eq=False)
class Namespace(Element):
    """An element that owns other elements."""

    members: List[Element] = field(default_factory=list)

    def add(self, *elements: Element) -> "Namespace":
        for element in elements:
            element.owner = self
            self.members.append(element)
        return self

    def children(self) -> List[Element]:
        return list(self.members)

    def member_named(self, name: str) -> Optional[Element]:
        for member in self.members:
            if name in (member.name, member.short_name):
                return member
        for member in self.members:
            if isinstance(member, Alias) and member.name == name:
                return self.member_named(member.target.split("::")[-1])
        return None

    def find(self, qualified: str) -> Optional[Element]:
        """Naive descent through owned members by ``::``-separated path."""

        node: Optional[Element] = self
        for part in qualified.split("::"):
            if not isinstance(node, Namespace):
                return None
            node = node.member_named(part)
            if node is None:
                return None
        return node

    @property
    def doc(self) -> Optional[str]:
        texts = [m.text for m in self.members if isinstance(m, Documentation)]
        return "\n".join(texts) if texts else None


@dataclass(eq=False)
class Model(Namespace):
    """The root namespace of one or more parsed sources."""

    source_name: Optional[str] = None


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


@dataclass(eq=False)
class Alias(Element):
    target: str = ""


@dataclass(eq=False)
class Comment(Element):
    body: str = ""  # raw '/* ... */' text
    about: List[str] = field(default_factory=list)
    locale: Optional[str] = None

    @property
    def text(self) -> str:
        return _strip_comment_body(self.body)


@dataclass(eq=False)
class Documentation(Element):
    body: str = ""  # raw '/* ... */' text
    locale: Optional[str] = None

    @property
    def text(self) -> str:
        return _strip_comment_body(self.body)


@dataclass(eq=False)
class TextualRepresentation(Element):
    language: str = ""
    body: str = ""


@dataclass(eq=False)
class Dependency(Element):
    clients: List[str] = field(default_factory=list)
    suppliers: List[str] = field(default_factory=list)


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
    expr: Expr = field(default_factory=lambda: Literal(None))
    is_default: bool = False  # 'default ='
    is_initial: bool = False  # ':='


@dataclass
class Multiplicity:
    lower: Optional[Expr] = None
    upper: Optional[Expr] = None
    is_ordered: bool = False
    is_nonunique: bool = False


@dataclass
class ConnectorEnd:
    target: str = ""
    name: Optional[str] = None  # 'name ::> target' form


# ---------------------------------------------------------------------------
# Definitions and usages
# ---------------------------------------------------------------------------

#: definition/usage ``kind`` values map 1:1 to declaration keywords
DEFINITION_KINDS = (
    "part item attribute port action calc constraint requirement concern state "
    "occurrence individual enum connection flow allocation metadata rendering "
    "case analysis verification use_case view viewpoint interface"
).split()


@dataclass(eq=False)
class Definition(Namespace):
    kind: str = "part"
    is_abstract: bool = False
    is_variation: bool = False
    is_individual: bool = False
    is_parallel: bool = False  # state definitions
    supers: List[str] = field(default_factory=list)  # ':>' specializations
    result: Optional[Expr] = None  # calc/constraint/case result expression


@dataclass(eq=False)
class EnumerationDefinition(Definition):
    kind: str = "enum"

    @property
    def literals(self) -> List["Usage"]:
        return [m for m in self.members if isinstance(m, Usage) and m.kind == "enum_literal"]


@dataclass(eq=False)
class Usage(Namespace):
    kind: str = "part"
    direction: Optional[str] = None  # 'in' | 'out' | 'inout' | 'return'
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
    portion_kind: Optional[str] = None  # 'snapshot' | 'timeslice'
    types: List[str] = field(default_factory=list)  # ': T'
    subsets: List[str] = field(default_factory=list)  # ':> f'
    redefines: List[str] = field(default_factory=list)  # ':>> f'
    references: Optional[str] = None  # '::> f'
    crosses: Optional[str] = None  # '=> f'
    multiplicity: Optional[Multiplicity] = None
    value: Optional[FeatureValue] = None
    result: Optional[Expr] = None  # calc/constraint usage result expression
    constraint_kind: Optional[str] = None  # 'assume'|'require'|'assert'


@dataclass(eq=False)
class ConnectionUsage(Usage):
    kind: str = "connection"
    ends: List[ConnectorEnd] = field(default_factory=list)


@dataclass(eq=False)
class BindingConnector(Usage):
    kind: str = "binding"
    source_end: Optional[ConnectorEnd] = None
    target_end: Optional[ConnectorEnd] = None


# ---------------------------------------------------------------------------
# Behavior: action statements
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class AssignmentAction(Element):
    target: str = ""  # dotted feature path
    expr: Expr = field(default_factory=lambda: Literal(None))


@dataclass(eq=False)
class IfAction(Element):
    condition: Expr = field(default_factory=lambda: Literal(True))
    then_body: List[Element] = field(default_factory=list)
    else_body: Optional[Union[List[Element], "IfAction"]] = None

    def children(self) -> List[Element]:
        extra = []
        if isinstance(self.else_body, IfAction):
            extra = [self.else_body]
        elif self.else_body:
            extra = list(self.else_body)
        return list(self.then_body) + extra


@dataclass(eq=False)
class WhileLoop(Element):
    condition: Optional[Expr] = None  # None => 'loop'
    body: List[Element] = field(default_factory=list)
    until: Optional[Expr] = None

    def children(self) -> List[Element]:
        return list(self.body)


@dataclass(eq=False)
class ForLoop(Element):
    var: str = ""
    seq: Expr = field(default_factory=lambda: Literal(None))
    body: List[Element] = field(default_factory=list)

    def children(self) -> List[Element]:
        return list(self.body)


@dataclass(eq=False)
class SendAction(Element):
    payload: Expr = field(default_factory=lambda: Literal(None))
    via: Optional[Expr] = None
    to: Optional[Expr] = None


@dataclass(eq=False)
class AcceptAction(Element):
    payload_name: Optional[str] = None
    payload_types: List[str] = field(default_factory=list)
    trigger_kind: Optional[str] = None  # 'at' | 'after' | 'when'
    trigger: Optional[Expr] = None
    via: Optional[Expr] = None


@dataclass(eq=False)
class PerformAction(Element):
    target: Optional[str] = None  # referenced action
    action: Optional[Usage] = None  # inline 'perform action x { ... }'

    def children(self) -> List[Element]:
        return [self.action] if self.action is not None else []


@dataclass(eq=False)
class TerminateAction(Element):
    target: Optional[Expr] = None


@dataclass(eq=False)
class ControlNode(Element):
    kind: str = "merge"  # 'merge' | 'decision' | 'join' | 'fork'


@dataclass(eq=False)
class InitialNode(Element):
    target: str = ""  # 'first <target>;'


@dataclass(eq=False)
class Succession(Element):
    source: Optional[str] = None  # None => attached to previous member
    target: str = ""
    guard: Optional[Expr] = None
    is_else: bool = False


# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class StateAction(Element):
    """``entry ...;`` / ``do ...;`` / ``exit ...;`` inside a state."""

    kind: str = "entry"
    action: Optional[Element] = None  # Perform/Assignment/Send/Accept or None

    def children(self) -> List[Element]:
        return [self.action] if self.action is not None else []


@dataclass(eq=False)
class TransitionUsage(Element):
    source: Optional[str] = None
    trigger: Optional[AcceptAction] = None
    guard: Optional[Expr] = None
    effect: Optional[Element] = None
    target: str = ""

    def children(self) -> List[Element]:
        out: List[Element] = []
        if self.trigger is not None:
            out.append(self.trigger)
        if self.effect is not None:
            out.append(self.effect)
        return out


__all__ = [name for name in dir() if not name.startswith("_")]
