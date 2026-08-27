"""Hypothesis strategies and the mutation catalog for the generative tier.

Test infrastructure for ``tests/test_generative.py`` (design:
``docs/design/conformance.md``, "Generative tier").  Three exports:

- :func:`model_trees` -- a composite strategy generating *valid-by-
  construction* SysML v2 models as small IR trees (packages, definitions,
  usages, typings, subsettings, redefinitions, multiplicities, expressions,
  state machines, connections, requirements, calcs, enums, aliases, docs).
  Every reference points at a declared name, every sibling name is unique,
  and every construct was probed to parse + build + validate clean -- the
  guard property in the test file enforces this, so a strategy bug fails
  the suite, not the toolchain.
- :func:`render_model` -- deterministic IR -> textual-notation renderer.
  Generating *text* (rather than builder dataclasses) exercises the parser
  on every example.
- :data:`MUTATIONS` -- the invalidating-mutation catalog (property family
  C): each entry ties one tree-level mutation to the one spec/pilot rule
  it violates, with the toolchain's expected verdict.  ``gap`` entries are
  accepted silently today and are pinned as strict xfails in
  ``tests/test_rejection.py`` (``pinned_case`` names the case).

This module imports ``hypothesis`` at module level; it is only imported
from ``tests/test_generative.py`` *after* a ``pytest.importorskip``, so
environments without hypothesis (the CI default) skip cleanly.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from hypothesis import strategies as st

GHOST = "GhostName987"  # a name no generator ever declares

# ---------------------------------------------------------------------------
# The IR: a tiny tree the renderer turns into textual notation
# ---------------------------------------------------------------------------


@dataclass
class MultNode:
    lower: str  # rendered bound token: "0", "4", "1.5", a name...
    upper: str | None = None  # None => "[lower]"; "*" allowed

    def render(self) -> str:
        return f"[{self.lower}]" if self.upper is None else f"[{self.lower}..{self.upper}]"


@dataclass
class UsageNode:
    kind: str  # part | attribute | port | action | state | item | requirement
    name: str | None = None
    types: list[str] = field(default_factory=list)
    conjugated: bool = False  # ': ~T' (ports)
    subsets: list[str] = field(default_factory=list)
    redefines: list[str] = field(default_factory=list)
    mult: MultNode | None = None
    value: str | None = None  # rendered expression text
    direction: str | None = None  # in | out
    is_variant: bool = False
    is_ref: bool = False
    members: list[Node] = field(default_factory=list)


@dataclass
class DefNode:
    kind: str  # part | attribute | port | action | state | calc | requirement | item
    name: str = ""
    supers: list[str] = field(default_factory=list)
    members: list[Node] = field(default_factory=list)
    is_abstract: bool = False
    is_variation: bool = False


@dataclass
class EnumDefNode:
    name: str = ""
    literals: list[str] = field(default_factory=list)


@dataclass
class PackageNode:
    name: str = ""
    members: list[Node] = field(default_factory=list)


@dataclass
class DocNode:
    text: str = ""


@dataclass
class AliasNode:
    name: str = ""
    target: str = ""


@dataclass
class EntryNode:  # 'entry; then <target>;'
    target: str = ""


@dataclass
class TransitionNode:  # 'transition <name> first <source> then <target>;'
    name: str = ""
    source: str = ""
    target: str = ""


@dataclass
class SuccessionNode:  # 'first <source> then <target>;'
    source: str = ""
    target: str = ""


@dataclass
class ConnectNode:  # 'connect <source> to <target>;'
    source: str = ""
    target: str = ""


@dataclass
class PerformNode:  # 'perform <target>;'
    target: str = ""


@dataclass
class ExhibitNode:  # 'exhibit <target>;'
    target: str = ""


@dataclass
class SubjectNode:  # 'subject <name> : <type>;'
    name: str = ""
    type_: str = ""


@dataclass
class ConstraintNode:  # '<prefix> constraint <name> { <expr> }'
    prefix: str = "require"  # require | assert
    name: str | None = None
    expr: str = "1.0 > 0.0"


@dataclass
class ReturnNode:  # 'return : Real = <expr>;'
    expr: str = "1.0"


@dataclass
class ModelNode:
    members: list[PackageNode] = field(default_factory=list)


Node = (
    UsageNode
    | DefNode
    | EnumDefNode
    | PackageNode
    | DocNode
    | AliasNode
    | EntryNode
    | TransitionNode
    | SuccessionNode
    | ConnectNode
    | PerformNode
    | ExhibitNode
    | SubjectNode
    | ConstraintNode
    | ReturnNode
)


# ---------------------------------------------------------------------------
# Renderer: IR -> textual notation (deterministic)
# ---------------------------------------------------------------------------

_BASIC_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _fmt_name(name: str) -> str:
    if _BASIC_NAME.match(name):
        return name
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _decl(node: UsageNode) -> str:
    bits: list[str] = []
    if node.direction:
        bits.append(node.direction)
    if node.is_variant:
        bits.append("variant")
    if node.is_ref:
        bits.append("ref")
    bits.append(node.kind)
    if node.name is not None:
        bits.append(_fmt_name(node.name))
    if node.types:
        tilde = "~" if node.conjugated else ""
        bits.append(": " + tilde + ", ".join(_fmt_name(t) for t in node.types))
    for target in node.subsets:
        bits.append(f"subsets {_fmt_name(target)}")
    for target in node.redefines:
        bits.append(f":>> {_fmt_name(target)}")
    if node.mult is not None:
        bits.append(node.mult.render())
    if node.value is not None:
        bits.append(f"= {node.value}")
    return " ".join(bits)


def _render(node: Node, indent: int) -> list[str]:
    pad = "    " * indent
    if isinstance(node, PackageNode):
        head = f"{pad}package {_fmt_name(node.name)}"
        return _with_body(head, node.members, indent)
    if isinstance(node, DefNode):
        bits = []
        if node.is_abstract:
            bits.append("abstract")
        if node.is_variation:
            bits.append("variation")
        bits += [node.kind, "def", _fmt_name(node.name)]
        if node.supers:
            bits.append(":> " + ", ".join(_fmt_name(s) for s in node.supers))
        return _with_body(pad + " ".join(bits), node.members, indent)
    if isinstance(node, EnumDefNode):
        head = f"{pad}enum def {_fmt_name(node.name)}"
        literal_lines = [f"{'    ' * (indent + 1)}{_fmt_name(lit)};" for lit in node.literals]
        return [head + " {", *literal_lines, pad + "}"]
    if isinstance(node, UsageNode):
        return _with_body(pad + _decl(node), node.members, indent)
    if isinstance(node, DocNode):
        return [f"{pad}doc /* {node.text} */"]
    if isinstance(node, AliasNode):
        return [f"{pad}alias {_fmt_name(node.name)} for {_fmt_name(node.target)};"]
    if isinstance(node, EntryNode):
        return [f"{pad}entry; then {_fmt_name(node.target)};"]
    if isinstance(node, TransitionNode):
        return [
            f"{pad}transition {_fmt_name(node.name)} "
            f"first {_fmt_name(node.source)} then {_fmt_name(node.target)};"
        ]
    if isinstance(node, SuccessionNode):
        return [f"{pad}first {_fmt_name(node.source)} then {_fmt_name(node.target)};"]
    if isinstance(node, ConnectNode):
        return [f"{pad}connect {_fmt_name(node.source)} to {_fmt_name(node.target)};"]
    if isinstance(node, PerformNode):
        return [f"{pad}perform {_fmt_name(node.target)};"]
    if isinstance(node, ExhibitNode):
        return [f"{pad}exhibit {_fmt_name(node.target)};"]
    if isinstance(node, SubjectNode):
        return [f"{pad}subject {_fmt_name(node.name)} : {_fmt_name(node.type_)};"]
    if isinstance(node, ConstraintNode):
        name = f" {_fmt_name(node.name)}" if node.name else ""
        return [f"{pad}{node.prefix} constraint{name} {{ {node.expr} }}"]
    if isinstance(node, ReturnNode):
        return [f"{pad}return : Real = {node.expr};"]
    raise TypeError(f"unrenderable node: {node!r}")  # pragma: no cover - strategy bug


def _with_body(head: str, members: list[Node], indent: int) -> list[str]:
    if not members:
        return [head + ";"]
    lines = [head + " {"]
    for member in members:
        lines += _render(member, indent + 1)
    lines.append("    " * indent + "}")
    return lines


def render_model(model: ModelNode) -> str:
    lines: list[str] = []
    for pkg in model.members:
        lines += _render(pkg, 0)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Generation context: name freshness + declared-name pools
# ---------------------------------------------------------------------------


class _Ctx:
    """Fresh names plus *scoped* pools of declared names, keyed by def kind.

    Names are unique model-wide (a global counter), which keeps every
    generated model free of duplicate-name diagnostics by construction and
    makes the duplicate-name *mutation* the only source of collisions.
    Pools are a scope stack mirroring package nesting: bare-name references
    resolve lexically (current package chain only), so a pool entry from a
    sibling package must never be referenced -- that was measured to warn
    ``unresolved-reference``.
    """

    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self._scopes: list[dict[str, list[str]]] = [{}]
        self.def_attrs: dict[str, list[str]] = {}  # part def name -> Real attrs
        self.enums: dict[str, list[str]] = {}  # enum def name -> literals

    def push_scope(self) -> None:
        self._scopes.append({})

    def pop_scope(self) -> None:
        self._scopes.pop()

    def fresh(self, prefix: str, quoted: bool = False) -> str:
        n = next(self._counter)
        return f"{prefix} {n} q" if quoted else f"{prefix}{n}"

    def register(self, kind: str, name: str) -> None:
        self._scopes[-1].setdefault(kind, []).append(name)

    def pool(self, kind: str) -> list[str]:
        out: list[str] = []
        for scope in self._scopes:
            out += scope.get(kind, [])
        return out


# ---------------------------------------------------------------------------
# Expressions: a small closed vocabulary over Real-typed sibling names
# ---------------------------------------------------------------------------

_LITERALS = ["0.0", "1.0", "2.5", "10.0", "100.0", "3", "7"]
_OPS = ["+", "-", "*", "/"]


def _gen_expr(draw: st.DrawFn, names: list[str], depth: int = 2) -> str:
    choices = ["literal"]
    if names:
        choices.append("ref")
    if depth > 0:
        choices += ["binary", "paren"]
    kind = draw(st.sampled_from(choices))
    if kind == "literal":
        return draw(st.sampled_from(_LITERALS))
    if kind == "ref":
        return _fmt_name(draw(st.sampled_from(names)))
    if kind == "paren":
        return f"({_gen_expr(draw, names, depth - 1)})"
    op = draw(st.sampled_from(_OPS))
    return f"{_gen_expr(draw, names, depth - 1)} {op} {_gen_expr(draw, names, depth - 1)}"


# ---------------------------------------------------------------------------
# Construct generators
# ---------------------------------------------------------------------------


def _maybe(draw: st.DrawFn, p_tenths: int) -> bool:
    """True with probability ``p_tenths``/10."""

    return draw(st.integers(0, 9)) < p_tenths


def _gen_mult(draw: st.DrawFn) -> MultNode:
    form = draw(st.sampled_from(["single", "range", "star"]))
    if form == "single":
        return MultNode(str(draw(st.integers(0, 12))))
    if form == "star":
        return MultNode(str(draw(st.integers(0, 2))), "*")
    lower = draw(st.integers(0, 5))
    upper = draw(st.integers(lower, lower + 7))
    return MultNode(str(lower), str(upper))


def _gen_attribute(draw: st.DrawFn, ctx: _Ctx, real_pool: list[str]) -> UsageNode:
    """An attribute usage; Real-typed ones may carry a value expression."""

    name = ctx.fresh("a", quoted=_maybe(draw, 1))
    flavor = draw(st.sampled_from(["real", "real", "real", "bool", "string", "enum", "attrdef"]))
    if flavor == "enum" and ctx.pool("enum"):
        enum_name = draw(st.sampled_from(ctx.pool("enum")))
        node = UsageNode("attribute", name, types=[enum_name])
        if _maybe(draw, 5):
            node.value = (
                f"{_fmt_name(enum_name)}::{_fmt_name(draw(st.sampled_from(ctx.enums[enum_name])))}"
            )
        return node
    if flavor == "attrdef" and ctx.pool("attribute"):
        return UsageNode("attribute", name, types=[draw(st.sampled_from(ctx.pool("attribute")))])
    if flavor == "bool":
        node = UsageNode("attribute", name, types=["Boolean"])
        if _maybe(draw, 5):
            node.value = draw(st.sampled_from(["true", "false"]))
        return node
    if flavor == "string":
        node = UsageNode("attribute", name, types=["String"])
        if _maybe(draw, 5):
            node.value = '"' + draw(st.sampled_from(["abc", "x y z", "42"])) + '"'
        return node
    node = UsageNode("attribute", name, types=["Real"])
    if _maybe(draw, 6):
        node.value = _gen_expr(draw, real_pool)
    real_pool.append(name)
    return node


def _gen_part_body(draw: st.DrawFn, ctx: _Ctx, depth: int, super_name: str | None) -> list[Node]:
    """Body members for a part def (or nested part usage)."""

    members: list[Node] = []
    real_pool: list[str] = []
    part_names: list[str] = []
    state_names: list[str] = []
    action_names: list[str] = []
    if _maybe(draw, 1):
        members.append(DocNode(draw(st.sampled_from(["a doc", "body text", "notes and words"]))))
    for _ in range(draw(st.integers(0, 4))):
        pick = draw(st.sampled_from(["attribute", "part", "part", "state", "action", "port"]))
        if pick == "attribute":
            members.append(_gen_attribute(draw, ctx, real_pool))
        elif pick == "part":
            name = ctx.fresh("p")
            node = UsageNode("part", name)
            if ctx.pool("part") and _maybe(draw, 7):
                node.types = [draw(st.sampled_from(ctx.pool("part")))]
            if _maybe(draw, 4):
                node.mult = _gen_mult(draw)
            if part_names and _maybe(draw, 2):
                node.subsets = [draw(st.sampled_from(part_names))]
            if _maybe(draw, 1):
                node.is_ref = True
            if depth > 0 and _maybe(draw, 2):
                node.members = _gen_part_body(draw, ctx, depth - 1, None)
            members.append(node)
            part_names.append(name)
        elif pick == "state":
            name = ctx.fresh("s")
            members.append(UsageNode("state", name))
            state_names.append(name)
        elif pick == "action":
            name = ctx.fresh("act")
            node = UsageNode("action", name)
            if ctx.pool("action") and _maybe(draw, 5):
                node.types = [draw(st.sampled_from(ctx.pool("action")))]
            members.append(node)
            action_names.append(name)
        elif pick == "port" and ctx.pool("port"):
            node = UsageNode(
                "port", ctx.fresh("prt"), types=[draw(st.sampled_from(ctx.pool("port")))]
            )
            node.conjugated = _maybe(draw, 2)
            members.append(node)
    # redefinition of an inherited attribute (anonymous, valued)
    if super_name and ctx.def_attrs.get(super_name) and _maybe(draw, 5):
        target = draw(st.sampled_from(ctx.def_attrs[super_name]))
        members.append(UsageNode("attribute", None, redefines=[target], value=_gen_expr(draw, [])))
    # references between declared siblings
    if len(part_names) >= 2 and _maybe(draw, 5):
        members.append(ConnectNode(part_names[0], part_names[1]))
    if state_names and _maybe(draw, 3):
        members.append(ExhibitNode(draw(st.sampled_from(state_names))))
    if action_names and _maybe(draw, 3):
        members.append(PerformNode(draw(st.sampled_from(action_names))))
    if real_pool and _maybe(draw, 2):
        members.append(ConstraintNode("assert", ctx.fresh("c"), f"{_fmt_name(real_pool[0])} > 0.0"))
    return members


def _gen_part_def(draw: st.DrawFn, ctx: _Ctx, depth: int) -> DefNode:
    name = ctx.fresh("PartDef", quoted=_maybe(draw, 1))
    node = DefNode("part", name, is_abstract=_maybe(draw, 1))
    super_name: str | None = None
    if ctx.pool("part") and _maybe(draw, 3):
        super_name = draw(st.sampled_from(ctx.pool("part")))
        node.supers = [super_name]
    node.members = _gen_part_body(draw, ctx, depth, super_name)
    ctx.register("part", name)
    ctx.def_attrs[name] = [
        m.name
        for m in node.members
        if isinstance(m, UsageNode) and m.kind == "attribute" and m.types == ["Real"] and m.name
    ]
    return node


def _gen_state_def(draw: st.DrawFn, ctx: _Ctx) -> DefNode:
    name = ctx.fresh("StateDef")
    states = [ctx.fresh("st") for _ in range(draw(st.integers(1, 3)))]
    members: list[Node] = [EntryNode(states[0])]
    members += [UsageNode("state", s) for s in states]
    for _ in range(draw(st.integers(0, 2))):
        src = draw(st.sampled_from(states))
        tgt = draw(st.sampled_from(states))
        members.append(TransitionNode(ctx.fresh("t"), src, tgt))
    ctx.register("state", name)
    return DefNode("state", name, members=members)


def _gen_action_def(draw: st.DrawFn, ctx: _Ctx) -> DefNode:
    name = ctx.fresh("ActionDef")
    members: list[Node] = []
    param_pool: list[str] = []
    for _ in range(draw(st.integers(0, 2))):
        pname = ctx.fresh("x")
        members.append(UsageNode("attribute", pname, types=["Real"], direction="in"))
        param_pool.append(pname)
    if _maybe(draw, 3):
        members.append(
            UsageNode(
                "attribute",
                ctx.fresh("y"),
                types=["Real"],
                direction="out",
                value=_gen_expr(draw, param_pool),
            )
        )
    actions = [ctx.fresh("act") for _ in range(draw(st.integers(0, 2)))]
    members += [UsageNode("action", a) for a in actions]
    if len(actions) >= 2:
        members.append(SuccessionNode(actions[0], actions[1]))
    ctx.register("action", name)
    return DefNode("action", name, members=members)


def _gen_calc_def(draw: st.DrawFn, ctx: _Ctx) -> DefNode:
    name = ctx.fresh("CalcDef")
    members: list[Node] = []
    param_pool: list[str] = []
    for _ in range(draw(st.integers(0, 2))):
        pname = ctx.fresh("m")
        members.append(UsageNode("attribute", pname, types=["Real"], direction="in"))
        param_pool.append(pname)
    members.append(ReturnNode(_gen_expr(draw, param_pool)))
    ctx.register("calc", name)
    return DefNode("calc", name, members=members)


def _gen_requirement_def(draw: st.DrawFn, ctx: _Ctx) -> DefNode:
    name = ctx.fresh("ReqDef")
    members: list[Node] = []
    if ctx.pool("part") and _maybe(draw, 6):
        members.append(SubjectNode(ctx.fresh("subj"), draw(st.sampled_from(ctx.pool("part")))))
    attr = ctx.fresh("margin")
    members.append(UsageNode("attribute", attr, types=["Real"]))
    members.append(ConstraintNode("require", ctx.fresh("rc"), f"{_fmt_name(attr)} > 0.0"))
    ctx.register("requirement", name)
    return DefNode("requirement", name, members=members)


def _gen_enum_def(draw: st.DrawFn, ctx: _Ctx) -> EnumDefNode:
    name = ctx.fresh("EnumDef")
    literals = [ctx.fresh("lit") for _ in range(draw(st.integers(1, 3)))]
    ctx.enums[name] = literals
    ctx.register("enum", name)
    return EnumDefNode(name, literals)


def _gen_port_def(draw: st.DrawFn, ctx: _Ctx) -> DefNode:
    name = ctx.fresh("PortDef")
    members: list[Node] = []
    for _ in range(draw(st.integers(0, 2))):
        members.append(UsageNode("attribute", ctx.fresh("v"), types=["Real"]))
    ctx.register("port", name)
    return DefNode("port", name, members=members)


def _gen_variation(draw: st.DrawFn, ctx: _Ctx) -> DefNode:
    name = ctx.fresh("VarDef")
    members: list[Node] = []
    for _ in range(draw(st.integers(1, 2))):
        node = UsageNode("part", ctx.fresh("v"), is_variant=True)
        if ctx.pool("part") and _maybe(draw, 5):
            node.types = [draw(st.sampled_from(ctx.pool("part")))]
        members.append(node)
    ctx.register("part", name)  # a variation part def is still a part def
    return DefNode("part", name, members=members, is_variation=True)


_DEF_MENU = [
    "part",
    "part",
    "part",
    "attribute",
    "state",
    "action",
    "calc",
    "requirement",
    "enum",
    "port",
    "item",
    "variation",
]


def _gen_definition(draw: st.DrawFn, ctx: _Ctx, depth: int) -> Node:
    kind = draw(st.sampled_from(_DEF_MENU))
    if kind == "part":
        return _gen_part_def(draw, ctx, depth)
    if kind == "attribute":
        name = ctx.fresh("AttrDef")
        ctx.register("attribute", name)
        return DefNode("attribute", name)
    if kind == "state":
        return _gen_state_def(draw, ctx)
    if kind == "action":
        return _gen_action_def(draw, ctx)
    if kind == "calc":
        return _gen_calc_def(draw, ctx)
    if kind == "requirement":
        return _gen_requirement_def(draw, ctx)
    if kind == "enum":
        return _gen_enum_def(draw, ctx)
    if kind == "port":
        return _gen_port_def(draw, ctx)
    if kind == "item":
        name = ctx.fresh("ItemDef")
        ctx.register("item", name)
        return DefNode("item", name)
    return _gen_variation(draw, ctx)


def _gen_package(draw: st.DrawFn, ctx: _Ctx, depth: int) -> PackageNode:
    name = ctx.fresh("Pkg")
    ctx.push_scope()
    members: list[Node] = []
    if _maybe(draw, 2):
        members.append(DocNode("package doc"))
    for _ in range(draw(st.integers(1, 4))):
        members.append(_gen_definition(draw, ctx, depth))
    # package-level usages referencing the declared definitions
    for _ in range(draw(st.integers(0, 2))):
        pick = draw(st.sampled_from(["part", "requirement", "item"]))
        if pick == "part" and ctx.pool("part"):
            node = UsageNode(
                "part", ctx.fresh("p"), types=[draw(st.sampled_from(ctx.pool("part")))]
            )
            if _maybe(draw, 3):
                node.mult = _gen_mult(draw)
            members.append(node)
        elif pick == "requirement" and ctx.pool("requirement"):
            members.append(
                UsageNode(
                    "requirement",
                    ctx.fresh("r"),
                    types=[draw(st.sampled_from(ctx.pool("requirement")))],
                )
            )
        elif pick == "item" and ctx.pool("item"):
            members.append(
                UsageNode("item", ctx.fresh("i"), types=[draw(st.sampled_from(ctx.pool("item")))])
            )
    if ctx.pool("part") and _maybe(draw, 2):
        members.append(AliasNode(ctx.fresh("Alias"), draw(st.sampled_from(ctx.pool("part")))))
    if depth > 0 and _maybe(draw, 3):
        members.append(_gen_package(draw, ctx, depth - 1))
    ctx.pop_scope()
    return PackageNode(name, members)


# ---------------------------------------------------------------------------
# Guaranteed constructs (mutation sites): self-contained templates appended
# to one package, so every bare-name reference stays in lexical scope
# ---------------------------------------------------------------------------


def _ensure(ctx: _Ctx, pkg: PackageNode, key: str) -> None:
    if key == "part-def":
        pkg.members.append(DefNode("part", ctx.fresh("PartDef")))
    elif key == "two-part-defs":
        pkg.members.append(DefNode("part", ctx.fresh("PartDef")))
        pkg.members.append(DefNode("part", ctx.fresh("PartDef")))
    elif key == "def-with-super":
        base = ctx.fresh("PartDef")
        pkg.members.append(DefNode("part", base))
        pkg.members.append(DefNode("part", ctx.fresh("PartDef"), supers=[base]))
    elif key == "attribute-def":
        pkg.members.append(DefNode("attribute", ctx.fresh("AttrDef")))
    elif key == "part-attr":
        pkg.members.append(
            DefNode(
                "part",
                ctx.fresh("PartDef"),
                members=[UsageNode("attribute", ctx.fresh("a"), types=["Real"])],
            )
        )
    elif key == "typed-part":
        base = ctx.fresh("PartDef")
        pkg.members.append(DefNode("part", base))
        pkg.members.append(UsageNode("part", ctx.fresh("p"), types=[base], mult=MultNode("2")))
    elif key == "connect":
        base = ctx.fresh("PartDef")
        a, b = ctx.fresh("p"), ctx.fresh("p")
        pkg.members.append(DefNode("part", base))
        pkg.members.append(
            DefNode(
                "part",
                ctx.fresh("PartDef"),
                members=[
                    UsageNode("part", a, types=[base]),
                    UsageNode("part", b),
                    ConnectNode(a, b),
                ],
            )
        )
    elif key == "state-machine":
        s1, s2 = ctx.fresh("st"), ctx.fresh("st")
        pkg.members.append(
            DefNode(
                "state",
                ctx.fresh("StateDef"),
                members=[
                    EntryNode(s1),
                    UsageNode("state", s1),
                    UsageNode("state", s2),
                    TransitionNode(ctx.fresh("t"), s1, s2),
                ],
            )
        )
    elif key == "calc":
        pkg.members.append(
            DefNode(
                "calc",
                ctx.fresh("CalcDef"),
                members=[
                    UsageNode("attribute", ctx.fresh("m"), types=["Real"], direction="in"),
                    ReturnNode("1.0"),
                ],
            )
        )
    elif key == "requirement-subject":
        base = ctx.fresh("PartDef")
        pkg.members.append(DefNode("part", base))
        pkg.members.append(
            DefNode(
                "requirement",
                ctx.fresh("ReqDef"),
                members=[SubjectNode(ctx.fresh("subj"), base)],
            )
        )
    elif key == "action-def":
        pkg.members.append(DefNode("action", ctx.fresh("ActionDef")))
    elif key == "action-succession":
        a1, a2 = ctx.fresh("act"), ctx.fresh("act")
        pkg.members.append(
            DefNode(
                "action",
                ctx.fresh("ActionDef"),
                members=[UsageNode("action", a1), UsageNode("action", a2), SuccessionNode(a1, a2)],
            )
        )
    elif key == "package-attr":
        pkg.members.append(UsageNode("attribute", ctx.fresh("a"), types=["Real"]))
    else:  # pragma: no cover - catalog bug
        raise KeyError(f"unknown ensure key: {key}")


@st.composite
def model_trees(draw: st.DrawFn, include: tuple[str, ...] = ()) -> ModelNode:
    """A valid-by-construction model tree.

    ``include`` names constructs (mutation sites) that must be present;
    missing ones are appended as minimal template members so mutation
    properties rarely reject examples.
    """

    ctx = _Ctx()
    model = ModelNode([_gen_package(draw, ctx, depth=2)])
    if _maybe(draw, 2):
        model.members.append(_gen_package(draw, ctx, depth=1))
    for key in include:
        _ensure(ctx, model.members[-1], key)
    return model


# ---------------------------------------------------------------------------
# Tree walking (mutation sites)
# ---------------------------------------------------------------------------


def _iter_nodes(model: ModelNode) -> Iterator[tuple[list[Node], Node]]:
    """Yield ``(owning_members_list, node)`` for every node, depth-first."""

    def walk(members: list[Node]) -> Iterator[tuple[list[Node], Node]]:
        for node in members:
            yield members, node
            children = getattr(node, "members", None)
            if children:
                yield from walk(children)

    yield from walk(list(model.members))


def _first(model: ModelNode, pred: Callable[[Node], bool]) -> tuple[list[Node], Node] | None:
    for members, node in _iter_nodes(model):
        if pred(node):
            return members, node
    return None


def _packages(model: ModelNode) -> list[PackageNode]:
    return [n for _, n in _iter_nodes(model) if isinstance(n, PackageNode)]


# ---------------------------------------------------------------------------
# The mutation catalog (property family C)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Mutation:
    """One invalidating mutation, tied to the one rule it violates.

    ``expectation`` is longeron's verdict class for the mutant:

    - ``"error"``     -- must reject: ParseError/BuildError or an
      error-severity diagnostic (the rejection-suite bar).
    - ``"diagnosed"`` -- must at least diagnose (any severity).
    - ``"gap"``       -- accepted silently today although the reference
      rejects it; pinned as a strict xfail in ``tests/test_rejection.py``
      under ``pinned_case``.  The property asserts no-crash only -- the
      xfail pin is what forces promotion when a check lands.
    """

    id: str
    rule: str
    expectation: str  # "error" | "diagnosed" | "gap"
    apply: Callable[[ModelNode], bool]  # mutate in place; False if no site
    requires: tuple[str, ...] = ()
    pinned_case: str | None = None

    def __str__(self) -> str:  # pragma: no cover - pytest ids
        return self.id


def _is_def(node: Node) -> bool:
    return isinstance(node, DefNode)


def _named_usage(kind: str | None = None) -> Callable[[Node], bool]:
    def pred(node: Node) -> bool:
        return (
            isinstance(node, UsageNode)
            and node.name is not None
            and (kind is None or node.kind == kind)
        )

    return pred


def _mut_duplicate_names(model: ModelNode) -> bool:
    for members, _node in _iter_nodes(model):
        named = [m for m in members if isinstance(m, (DefNode, EnumDefNode)) and m.name]
        if len(named) >= 2:
            named[1].name = named[0].name
            return True
    return False


def _mut_self_specialization(model: ModelNode) -> bool:
    site = _first(model, _is_def)
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, DefNode)
    node.supers = [*node.supers, node.name]
    return True


def _mut_specialization_cycle(model: ModelNode) -> bool:
    # both ends of the new edge must live in the same namespace: a super
    # names its target by bare name, which only resolves lexically
    for members, _node in _iter_nodes(model):
        defs = {m.name: m for m in members if isinstance(m, DefNode)}
        for child in defs.values():
            for super_name in child.supers:
                parent = defs.get(super_name)
                if parent is not None and parent is not child:
                    parent.supers = [*parent.supers, child.name]
                    return True
    return False


def _mut_self_subsetting(model: ModelNode) -> bool:
    site = _first(model, _named_usage("part"))
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, UsageNode) and node.name is not None
    node.subsets = [node.name]
    return True


def _mut_transition_ghost(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, TransitionNode))
    if site is None:
        return False
    site[1].target = GHOST  # type: ignore[union-attr]
    return True


def _mut_entry_ghost(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, EntryNode))
    if site is None:
        return False
    site[1].target = GHOST  # type: ignore[union-attr]
    return True


def _mut_dangling_typing(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, UsageNode) and bool(n.types))
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, UsageNode)
    node.types = [GHOST]
    node.value = None  # an enum-literal value would dangle differently
    return True


def _mut_dangling_subsets(model: ModelNode) -> bool:
    site = _first(model, _named_usage("part"))
    if site is None:
        return False
    site[1].subsets = [GHOST]  # type: ignore[union-attr]
    return True


def _mut_dangling_redefines(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, DefNode) and n.kind == "part")
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, DefNode)
    node.members.append(UsageNode("attribute", None, redefines=[GHOST], value="1.0"))
    return True


def _mut_dangling_connect(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, ConnectNode))
    if site is None:
        return False
    site[1].target = GHOST  # type: ignore[union-attr]
    return True


def _mut_state_in_attribute_def(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, DefNode) and n.kind == "attribute")
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, DefNode)
    node.members.append(UsageNode("state", "ghostState1"))
    return True


def _retype(model: ModelNode, usage_kind: str, new_type: Callable[[ModelNode], str | None]) -> bool:
    target = new_type(model)
    if target is None:
        return False
    site = _first(
        model,
        lambda n: isinstance(n, UsageNode) and n.kind == usage_kind and bool(n.types),
    )
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, UsageNode)
    node.types = [target]
    node.value = None
    node.conjugated = False
    return True


def _def_name(model: ModelNode, kind: str) -> str | None:
    site = _first(model, lambda n: isinstance(n, DefNode) and n.kind == kind)
    if site is None:
        return None
    node = site[1]
    assert isinstance(node, DefNode)
    return node.name


def _mut_attribute_typed_by_part_def(model: ModelNode) -> bool:
    return _retype(model, "attribute", lambda m: _def_name(m, "part"))


def _mut_part_typed_by_attribute_def(model: ModelNode) -> bool:
    return _retype(model, "part", lambda m: _def_name(m, "attribute"))


def _mut_typed_by_package(model: ModelNode) -> bool:
    return _retype(model, "part", lambda m: _packages(m)[0].name if _packages(m) else None)


def _mut_subsets_package(model: ModelNode) -> bool:
    pkgs = _packages(model)
    site = _first(model, _named_usage("part"))
    if site is None or not pkgs:
        return False
    site[1].subsets = [pkgs[0].name]  # type: ignore[union-attr]
    return True


def _set_bound(model: ModelNode, bound: str) -> bool:
    site = _first(model, lambda n: isinstance(n, UsageNode) and n.mult is not None)
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, UsageNode)
    node.mult = MultNode(bound)
    return True


def _mut_real_bound(model: ModelNode) -> bool:
    return _set_bound(model, "1.5")


def _mut_dangling_bound(model: ModelNode) -> bool:
    return _set_bound(model, GHOST)


def _mut_variant_outside_variation(model: ModelNode) -> bool:
    for _members, node in _iter_nodes(model):
        if isinstance(node, DefNode) and not node.is_variation:
            usages = [m for m in node.members if isinstance(m, UsageNode) and m.kind == "part"]
            if usages:
                usages[0].is_variant = True
                return True
    return False


def _mut_second_entry(model: ModelNode) -> bool:
    for _members, node in _iter_nodes(model):
        if isinstance(node, DefNode) and node.kind == "state":
            entries = [m for m in node.members if isinstance(m, EntryNode)]
            if entries:
                node.members.append(EntryNode(entries[0].target))
                return True
    return False


def _mut_sibling_redefinition(model: ModelNode) -> bool:
    for _members, node in _iter_nodes(model):
        if isinstance(node, DefNode) and node.kind == "part":
            attrs = [
                m
                for m in node.members
                if isinstance(m, UsageNode) and m.kind == "attribute" and m.name
            ]
            if attrs:
                assert attrs[0].name is not None
                node.members.append(
                    UsageNode("attribute", None, redefines=[attrs[0].name], value="1.0")
                )
                return True
    return False


def _mut_package_level_redefinition(model: ModelNode) -> bool:
    for pkg in _packages(model):
        attrs = [
            m for m in pkg.members if isinstance(m, UsageNode) and m.kind == "attribute" and m.name
        ]
        if attrs:
            assert attrs[0].name is not None
            pkg.members.append(UsageNode("attribute", None, redefines=[attrs[0].name], value="1.0"))
            return True
    return False


def _mut_connector_end_to_def(model: ModelNode) -> bool:
    name = _def_name(model, "part")
    site = _first(model, lambda n: isinstance(n, ConnectNode))
    if site is None or name is None:
        return False
    site[1].target = name  # type: ignore[union-attr]
    return True


def _mut_second_subject(model: ModelNode) -> bool:
    for _members, node in _iter_nodes(model):
        if isinstance(node, DefNode) and node.kind == "requirement":
            subjects = [m for m in node.members if isinstance(m, SubjectNode)]
            if subjects:
                node.members.append(SubjectNode("ghostSubj1", subjects[0].type_))
                return True
    return False


def _mut_second_return(model: ModelNode) -> bool:
    for _members, node in _iter_nodes(model):
        if isinstance(node, DefNode) and node.kind == "calc":
            if any(isinstance(m, ReturnNode) for m in node.members):
                node.members.append(ReturnNode("2.0"))
                return True
    return False


def _respecialize(model: ModelNode, def_kind: str, super_kind: str) -> bool:
    super_name = _def_name(model, super_kind)
    site = _first(model, lambda n: isinstance(n, DefNode) and n.kind == def_kind)
    if site is None or super_name is None:
        return False
    node = site[1]
    assert isinstance(node, DefNode)
    if node.name == super_name:
        return False
    node.supers = [super_name]
    return True


def _mut_attr_def_specializes_part_def(model: ModelNode) -> bool:
    return _respecialize(model, "attribute", "part")


def _mut_action_def_specializes_part_def(model: ModelNode) -> bool:
    return _respecialize(model, "action", "part")


def _mut_parameter_in_part_def(model: ModelNode) -> bool:
    for _members, node in _iter_nodes(model):
        if isinstance(node, DefNode) and node.kind == "part":
            attrs = [m for m in node.members if isinstance(m, UsageNode) and m.kind == "attribute"]
            if attrs:
                attrs[0].direction = "in"
                return True
    return False


def _mut_succession_ghost(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, SuccessionNode))
    if site is None:
        return False
    site[1].target = GHOST  # type: ignore[union-attr]
    return True


def _mut_perform_ghost(model: ModelNode) -> bool:
    site = _first(model, lambda n: isinstance(n, DefNode) and n.kind == "part")
    if site is None:
        return False
    node = site[1]
    assert isinstance(node, DefNode)
    node.members.append(PerformNode(GHOST))
    return True


MUTATIONS: list[Mutation] = [
    # -- enforced today: must produce an error (or raise)
    Mutation(
        "duplicate-sibling-names",
        "KerML validateNamespaceDistinguishability: owned member names must be distinct",
        "error",
        _mut_duplicate_names,
        requires=("two-part-defs",),
    ),
    Mutation(
        "self-specialization",
        "KerML: specialization must be acyclic (Type::supertypes partial order)",
        "error",
        _mut_self_specialization,
        requires=("part-def",),
    ),
    Mutation(
        "specialization-cycle",
        "KerML: specialization must be acyclic (Type::supertypes partial order)",
        "error",
        _mut_specialization_cycle,
        requires=("def-with-super",),
    ),
    Mutation(
        "self-subsetting",
        "KerML: specialization (incl. Subsetting) must be acyclic",
        "error",
        _mut_self_subsetting,
        requires=("typed-part",),
    ),
    Mutation(
        "transition-to-ghost",
        "a transition's target must be a vertex of its own machine",
        "error",
        _mut_transition_ghost,
        requires=("state-machine",),
    ),
    Mutation(
        "entry-to-ghost",
        "an entry transition's target must be a vertex of its own machine",
        "error",
        _mut_entry_ghost,
        requires=("state-machine",),
    ),
    # -- diagnosed today (warning severity; the pilot errors)
    Mutation(
        "dangling-typing",
        "unresolved FeatureTyping target; the pilot reports an error",
        "diagnosed",
        _mut_dangling_typing,
        requires=("typed-part",),
    ),
    Mutation(
        "dangling-subsets",
        "unresolved Subsetting target; the pilot reports an error",
        "diagnosed",
        _mut_dangling_subsets,
        requires=("typed-part",),
    ),
    Mutation(
        "dangling-redefines",
        "unresolved Redefinition target; the pilot reports an error",
        "diagnosed",
        _mut_dangling_redefines,
        requires=("part-def",),
    ),
    Mutation(
        "dangling-connector-end",
        "unresolved connector end; the pilot reports an error",
        "diagnosed",
        _mut_dangling_connect,
        requires=("connect",),
    ),
    # -- known gaps at catalog creation; checks landed for all but one.
    #    'error' = the check always fires on the mutant; 'diagnosed' = the
    #    mutated reference may or may not resolve from the mutation site
    #    (the templates and organic trees span packages), so the verdict is
    #    an error diagnostic when it resolves and an unresolved-reference
    #    warning when it does not -- diagnosed either way.
    Mutation(
        "state-into-attribute-def",
        "validateAttributeDefinitionFeatures (spec p. 278)",
        "error",
        _mut_state_in_attribute_def,
        requires=("attribute-def",),
    ),
    Mutation(
        "attribute-typed-by-part-def",
        "checkAttributeUsageDataTypeSpecialization (spec p. 404)",
        "diagnosed",
        _mut_attribute_typed_by_part_def,
        requires=("part-attr",),
    ),
    Mutation(
        "part-typed-by-attribute-def",
        "validatePartUsagePartDefinition (spec p. 291)",
        "diagnosed",
        _mut_part_typed_by_attribute_def,
        requires=("typed-part", "attribute-def"),
    ),
    Mutation(
        "typed-by-package",
        "pilot:validateUsageType_: 'A usage must be typed by definitions'",
        "error",
        _mut_typed_by_package,
        requires=("typed-part",),
    ),
    Mutation(
        "subsets-a-package",
        "KerML 8.3: Subsetting::subsettedFeature must be a Feature",
        "error",
        _mut_subsets_package,
        requires=("typed-part",),
    ),
    Mutation(
        "real-multiplicity-bound",
        "KerML pilot:validateMultiplicityRangeResultTypes: 'Must have a Natural value'",
        "error",
        _mut_real_bound,
        requires=("typed-part",),
    ),
    Mutation(
        "variant-outside-variation",
        "validateVariantMembershipOwningNamespace (spec p. 277)",
        "error",
        _mut_variant_outside_variation,
        requires=("connect",),  # guarantees a part def owning part usages
    ),
    Mutation(
        "second-entry-transition",
        "validateStateDefinitionStateSubactionKind (spec p. 336)",
        "error",
        _mut_second_entry,
        requires=("state-machine",),
    ),
    # -- gaps found by this tier; checks landed for all but one
    Mutation(
        "sibling-redefinition",
        "pilot:validateRedefinitionFeaturingTypes: 'Featuring types of redefining "
        "feature and redefined feature cannot be the same'",
        "error",
        _mut_sibling_redefinition,
        requires=("part-attr",),
    ),
    Mutation(
        "package-level-redefinition",
        "pilot:validateRedefinitionFeaturingTypes: 'A package-level feature cannot be redefined'",
        "error",
        _mut_package_level_redefinition,
        requires=("package-attr",),
    ),
    Mutation(
        "connector-end-is-a-definition",
        "KerML 8.3: Connector::relatedFeature must be Features; a Definition is not",
        "diagnosed",
        _mut_connector_end_to_def,
        requires=("connect",),
    ),
    Mutation(
        "second-subject",
        "validateRequirementDefinitionOnlyOneSubject: 'Only one subject is allowed.'",
        "error",
        _mut_second_subject,
        requires=("requirement-subject",),
    ),
    Mutation(
        "second-return-parameter",
        "KerML validateFunctionResultParameterMembership: 'Only one return parameter is allowed'",
        "error",
        _mut_second_return,
        requires=("calc",),
    ),
    Mutation(
        "attribute-def-specializes-part-def",
        "KerML validateDataTypeSpecialization: 'Cannot specialize class or association'",
        "diagnosed",
        _mut_attr_def_specializes_part_def,
        requires=("attribute-def", "part-def"),
    ),
    Mutation(
        "action-def-specializes-part-def",
        "KerML validateBehaviorSpecialization: 'Cannot specialize structure'",
        "diagnosed",
        _mut_action_def_specializes_part_def,
        requires=("action-def", "part-def"),
    ),
    Mutation(
        "parameter-in-part-def",
        "KerML validateParameterMembershipOwningType: 'Parameter membership not allowed' "
        "-- still a gap: the pilot's own corpus puts directed features in part "
        "defs/usages, so no honest validation-time check exists (see the pinned case)",
        "gap",
        _mut_parameter_in_part_def,
        requires=("part-attr",),
        pinned_case="parameter-outside-behavior",
    ),
    Mutation(
        "unresolved-multiplicity-bound",
        "a multiplicity bound name must resolve; the pilot errors "
        "(cf. validateMultiplicityRangeResultTypes)",
        "diagnosed",
        _mut_dangling_bound,
        requires=("typed-part",),
    ),
    Mutation(
        "succession-end-to-ghost",
        "a succession's ends must resolve; the pilot reports an error",
        "diagnosed",
        _mut_succession_ghost,
        requires=("action-succession",),
    ),
    Mutation(
        "perform-of-ghost",
        "an unresolved PerformActionUsage target; the pilot reports an error",
        "diagnosed",
        _mut_perform_ghost,
        requires=("part-def",),
    ),
]


# ---------------------------------------------------------------------------
# Adversarial text mutations (property family A)
# ---------------------------------------------------------------------------

_NOISE_CHARS = "{}();:.=[]<>*'\"#@/\\,%^&|!?~$"
_KEYWORDS = [
    "part",
    "def",
    "state",
    "entry",
    "if",
    "import",
    "package",
    "connect",
    "first",
    "then",
    "subsets",
    "redefines",
    "attribute",
    "abstract",
    "variation",
    "variant",
    "enum",
    "doc",
    "alias",
    "transition",
    "in",
    "return",
]
_TEXT_OPS = [
    "del-char",
    "dup-char",
    "swap-chars",
    "replace-char",
    "insert-char",
    "del-token",
    "keyword-token",
    "insert-keyword",
    "del-open-brace",
    "del-close-brace",
    "extra-close-brace",
    "truncate",
    "unicode-noise",
]


def mutate_text(draw: st.DrawFn, text: str) -> str:
    """Apply one drawn character/token-level mutation to ``text``."""

    op = draw(st.sampled_from(_TEXT_OPS))
    if not text:
        return draw(st.sampled_from(_NOISE_CHARS))
    i = draw(st.integers(0, len(text) - 1))
    if op == "del-char":
        return text[:i] + text[i + 1 :]
    if op == "dup-char":
        return text[:i] + text[i] + text[i:]
    if op == "swap-chars" and i < len(text) - 1:
        return text[:i] + text[i + 1] + text[i] + text[i + 2 :]
    if op == "replace-char":
        return text[:i] + draw(st.sampled_from(_NOISE_CHARS)) + text[i + 1 :]
    if op == "insert-char":
        return text[:i] + draw(st.sampled_from(_NOISE_CHARS)) + text[i:]
    if op == "del-token":
        tokens = text.split()
        k = draw(st.integers(0, len(tokens) - 1))
        return " ".join(tokens[:k] + tokens[k + 1 :])
    if op == "keyword-token":
        tokens = text.split()
        k = draw(st.integers(0, len(tokens) - 1))
        tokens[k] = draw(st.sampled_from(_KEYWORDS))
        return " ".join(tokens)
    if op == "insert-keyword":
        return text[:i] + " " + draw(st.sampled_from(_KEYWORDS)) + " " + text[i:]
    if op == "del-open-brace":
        return text.replace("{", "", 1)
    if op == "del-close-brace":
        j = text.rfind("}")
        return text if j < 0 else text[:j] + text[j + 1 :]
    if op == "extra-close-brace":
        return text[:i] + "}" + text[i:]
    if op == "truncate":
        return text[:i]
    if op == "unicode-noise":
        return (
            text[:i]
            + draw(st.sampled_from(["\u03bb", "\x00", "\ufeff", "\u2028", "\U0001f600"]))
            + text[i:]
        )
    return text  # swap at last index: identity


@st.composite
def adversarial_texts(draw: st.DrawFn) -> str:
    """Valid generated text pushed through 1..3 corrupting text mutations."""

    text = render_model(draw(model_trees()))
    for _ in range(draw(st.integers(1, 3))):
        text = mutate_text(draw, text)
    return text
