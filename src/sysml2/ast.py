"""Expression AST for SysML v2 / KerML owned expressions.

The model builder converts the ANTLR parse tree of ``ownedExpression`` into
these compact nodes; the interpreter evaluates them and the exporters render
them back to text / JSON.  Qualified names are stored as tuples of (unquoted)
name parts, e.g. ``("ISQ", "mass")`` for ``ISQ::mass``.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Literal as L

INF = float("inf")

QName = tuple[str, ...]

UnaryOp = L["+", "-", "~", "not"]
BinaryOp = L[
    "??",
    "or",
    "and",
    "implies",  # conditional-binary
    "|",
    "&",
    "xor",  # bitwise
    "==",
    "!=",
    "===",
    "!==",  # equality
    "<",
    ">",
    "<=",
    ">=",  # relational
    "..",  # range
    "+",
    "-",
    "*",
    "/",
    "%",
    "**",
    "^",  # arithmetic
]
ClassificationOp = L["istype", "hastype", "@", "@@"]
CastOp = L["as", "meta"]


@dataclass
class Expr:
    """Base class for all expression nodes."""

    def to_text(self) -> str:
        return expr_to_text(self)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.to_text()


@dataclass
class Literal(Expr):
    """``true`` / ``42`` / ``3.14`` / ``"hi"`` / ``null`` / ``*`` (infinity)."""

    value: bool | int | float | str | None


@dataclass
class FeatureRef(Expr):
    """A (possibly qualified) reference: ``x``, ``engine.power``, ``P::c``.

    ``parts`` are the ``::``-separated segments; a leading ``"$"`` denotes a
    root-relative reference.  Feature chains written with dots inside a single
    reference come through :class:`ChainAccess` instead when they follow a
    primary expression.
    """

    parts: QName


@dataclass
class ChainAccess(Expr):
    """``<primary> . a.b.c`` -- member access on the result of an expression."""

    base: Expr
    parts: QName


@dataclass
class Unary(Expr):
    op: UnaryOp
    operand: Expr


@dataclass
class Binary(Expr):
    op: BinaryOp
    left: Expr
    right: Expr


@dataclass
class Conditional(Expr):
    """``if test ? then else orelse``"""

    test: Expr
    then: Expr
    orelse: Expr


@dataclass
class Classification(Expr):
    """``x istype T`` / ``x hastype T`` / ``x @ T`` (operand may be implied)."""

    op: ClassificationOp
    type: QName
    operand: Expr | None = None


@dataclass
class Cast(Expr):
    """``x as T`` (operand may be implied) or ``x meta T``."""

    type: QName
    operand: Expr | None = None
    op: CastOp = "as"


@dataclass
class AllOf(Expr):
    """``all T`` -- the extent of a type (not evaluable in this interpreter)."""

    type: QName


@dataclass
class SequenceExpr(Expr):
    """``(a, b, c)`` -- sequence construction."""

    items: tuple[Expr, ...]


@dataclass
class IndexOp(Expr):
    """``seq#(i)`` -- 1-based indexing."""

    base: Expr
    index: tuple[Expr, ...]


@dataclass
class QuantityOp(Expr):
    """``10 [SI::m]`` -- a value annotated with a measurement reference."""

    base: Expr
    unit: Expr


@dataclass
class Param(Expr):
    """A parameter of a body expression, e.g. ``in x``."""

    name: str
    direction: L["in", "out", "inout"] | None = None


@dataclass
class BodyExpr(Expr):
    """``{ in x; x + 1 }`` -- an anonymous function body.

    ``lets`` are valued members declared in the body (name, expression).
    """

    params: tuple[Param, ...] = ()
    lets: tuple[tuple[str, Expr], ...] = ()
    result: Expr | None = None


@dataclass
class Invocation(Expr):
    """``Foo(a, b)`` or ``Foo(x = a, y = b)``."""

    target: QName
    args: tuple[Expr, ...] = ()
    named: tuple[tuple[str, Expr], ...] = ()


@dataclass
class Constructor(Expr):
    """``new Foo(a, b)``"""

    type: QName
    args: tuple[Expr, ...] = ()
    named: tuple[tuple[str, Expr], ...] = ()


@dataclass
class ArrowOp(Expr):
    """``seq->select { in x; x > 2 }`` / ``seq->size()`` / ``seq->reduce f``."""

    base: Expr
    name: QName
    args: tuple[Expr, ...] = ()
    body: BodyExpr | None = None
    func: QName | None = None  # function-reference argument form


@dataclass
class CollectOp(Expr):
    """``seq.{ in x; x * 2 }``"""

    base: Expr
    body: BodyExpr


@dataclass
class SelectOp(Expr):
    """``seq.?{ in x; x > 2 }``"""

    base: Expr
    body: BodyExpr


@dataclass
class MetadataAccess(Expr):
    """``Element.metadata``"""

    target: QName


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

# Binding strength, mirroring the precedence encoded by alternative order in
# the ``ownedExpression`` rule of the grammars (higher binds tighter).
_PREC_TERNARY = 1
_PREC_CLASSIFICATION = 2
_PREC_CONDITIONAL_BINARY = 3  # '??' | 'or' | 'and' | 'implies'
_PREC_BITWISE = 4  # '|' | '&' | 'xor'
_PREC_EQUALITY = 5
_PREC_RELATIONAL = 6
_PREC_RANGE = 7
_PREC_ADDITIVE = 8
_PREC_MULTIPLICATIVE = 9
_PREC_EXPONENTIAL = 10
_PREC_UNARY = 11
_PREC_PRIMARY = 12

_BINARY_PREC = {
    "??": _PREC_CONDITIONAL_BINARY,
    "or": _PREC_CONDITIONAL_BINARY,
    "and": _PREC_CONDITIONAL_BINARY,
    "implies": _PREC_CONDITIONAL_BINARY,
    "|": _PREC_BITWISE,
    "&": _PREC_BITWISE,
    "xor": _PREC_BITWISE,
    "==": _PREC_EQUALITY,
    "!=": _PREC_EQUALITY,
    "===": _PREC_EQUALITY,
    "!==": _PREC_EQUALITY,
    "<": _PREC_RELATIONAL,
    ">": _PREC_RELATIONAL,
    "<=": _PREC_RELATIONAL,
    ">=": _PREC_RELATIONAL,
    "..": _PREC_RANGE,
    "+": _PREC_ADDITIVE,
    "-": _PREC_ADDITIVE,
    "*": _PREC_MULTIPLICATIVE,
    "/": _PREC_MULTIPLICATIVE,
    "%": _PREC_MULTIPLICATIVE,
    "^": _PREC_EXPONENTIAL,
    "**": _PREC_EXPONENTIAL,
}

_RESERVED_FOR_NAMES = None  # populated lazily from export to avoid a cycle


def _fmt_name(name: str) -> str:
    """Quote a single name part if it is not a plain basic name."""

    from .export import name_needs_quotes  # local import to avoid cycle

    if name == "$" or not name_needs_quotes(name):
        return name
    escaped = name.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def fmt_qname(parts: QName) -> str:
    return "::".join(_fmt_name(p) for p in parts)


def _escape_string(value: str) -> str:
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return out


def _literal_text(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return f'"{_escape_string(value)}"'
    if isinstance(value, float):
        if value == INF:
            return "*"
        return repr(value)
    return repr(value)


def _body_text(body: BodyExpr) -> str:
    bits = []
    for param in body.params:
        direction = f"{param.direction} " if param.direction else "in "
        bits.append(f"{direction}{_fmt_name(param.name)};")
    for name, expr in body.lets:
        bits.append(f"attribute {_fmt_name(name)} = {expr_to_text(expr)};")
    if body.result is not None:
        bits.append(expr_to_text(body.result))
    inner = " ".join(bits)
    return "{ " + inner + " }" if inner else "{}"


def _args_text(args, named) -> str:
    rendered = [expr_to_text(a) for a in args]
    rendered += [f"{_fmt_name(n)} = {expr_to_text(e)}" for n, e in named]
    return "(" + ", ".join(rendered) + ")"


def expr_to_text(expr: Expr, min_prec: int = 0) -> str:
    """Render an expression AST back to SysML textual notation."""

    text, prec = _render(expr)
    if prec < min_prec:
        return f"({text})"
    return text


def _render(expr: Expr) -> tuple[str, int]:
    if isinstance(expr, Param):
        direction = f"{expr.direction} " if expr.direction else ""
        return f"{direction}{_fmt_name(expr.name)}", _PREC_PRIMARY
    if isinstance(expr, Literal):
        return _literal_text(expr.value), _PREC_PRIMARY
    if isinstance(expr, FeatureRef):
        return fmt_qname(expr.parts), _PREC_PRIMARY
    if isinstance(expr, ChainAccess):
        base = expr_to_text(expr.base, _PREC_PRIMARY)
        return f"{base}.{'.'.join(_fmt_name(p) for p in expr.parts)}", _PREC_PRIMARY
    if isinstance(expr, Unary):
        op = expr.op if expr.op in {"+", "-", "~"} else expr.op + " "
        return f"{op}{expr_to_text(expr.operand, _PREC_UNARY)}", _PREC_UNARY
    if isinstance(expr, Binary):
        prec = _BINARY_PREC[expr.op]
        left = expr_to_text(expr.left, prec)
        right = expr_to_text(expr.right, prec + 1)
        return f"{left} {expr.op} {right}", prec
    if isinstance(expr, Conditional):
        test = expr_to_text(expr.test, _PREC_TERNARY + 1)
        then = expr_to_text(expr.then, _PREC_TERNARY + 1)
        orelse = expr_to_text(expr.orelse, _PREC_TERNARY)
        return f"if {test} ? {then} else {orelse}", _PREC_TERNARY
    if isinstance(expr, Classification):
        type_text = fmt_qname(expr.type)
        if expr.operand is None:
            if expr.op == "@":
                return f"@{type_text}", _PREC_CLASSIFICATION
            return f"{expr.op} {type_text}", _PREC_CLASSIFICATION
        operand = expr_to_text(expr.operand, _PREC_CLASSIFICATION + 1)
        if expr.op == "@":
            return f"{operand} @ {type_text}", _PREC_CLASSIFICATION
        return f"{operand} {expr.op} {type_text}", _PREC_CLASSIFICATION
    if isinstance(expr, Cast):
        type_text = fmt_qname(expr.type)
        if expr.operand is None:
            return f"{expr.op} {type_text}", _PREC_CLASSIFICATION
        operand = expr_to_text(expr.operand, _PREC_CLASSIFICATION + 1)
        return f"{operand} {expr.op} {type_text}", _PREC_CLASSIFICATION
    if isinstance(expr, AllOf):
        return f"all {fmt_qname(expr.type)}", _PREC_CLASSIFICATION
    if isinstance(expr, SequenceExpr):
        inner = ", ".join(expr_to_text(item) for item in expr.items)
        if len(expr.items) == 1:
            inner += ","
        return f"({inner})", _PREC_PRIMARY
    if isinstance(expr, IndexOp):
        base = expr_to_text(expr.base, _PREC_PRIMARY)
        inner = ", ".join(expr_to_text(item) for item in expr.index)
        return f"{base}#({inner})", _PREC_PRIMARY
    if isinstance(expr, QuantityOp):
        base = expr_to_text(expr.base, _PREC_PRIMARY)
        return f"{base} [{expr_to_text(expr.unit)}]", _PREC_PRIMARY
    if isinstance(expr, Invocation):
        return f"{fmt_qname(expr.target)}{_args_text(expr.args, expr.named)}", _PREC_PRIMARY
    if isinstance(expr, Constructor):
        return f"new {fmt_qname(expr.type)}{_args_text(expr.args, expr.named)}", _PREC_PRIMARY
    if isinstance(expr, ArrowOp):
        base = expr_to_text(expr.base, _PREC_PRIMARY)
        name = fmt_qname(expr.name)
        if expr.body is not None:
            return f"{base}->{name} {_body_text(expr.body)}", _PREC_PRIMARY
        if expr.func is not None:
            return f"{base}->{name} {fmt_qname(expr.func)}", _PREC_PRIMARY
        return f"{base}->{name}{_args_text(expr.args, ())}", _PREC_PRIMARY
    if isinstance(expr, CollectOp):
        base = expr_to_text(expr.base, _PREC_PRIMARY)
        return f"{base}.{_body_text(expr.body)}", _PREC_PRIMARY
    if isinstance(expr, SelectOp):
        base = expr_to_text(expr.base, _PREC_PRIMARY)
        return f"{base}.?{_body_text(expr.body)}", _PREC_PRIMARY
    if isinstance(expr, BodyExpr):
        return _body_text(expr), _PREC_PRIMARY
    if isinstance(expr, MetadataAccess):
        return f"{fmt_qname(expr.target)}.metadata", _PREC_PRIMARY
    raise TypeError(f"cannot render expression node {expr!r}")


def expr_to_dict(expr: Expr):
    """Serialize an expression AST node to plain JSON-able data."""

    if expr is None:
        return None
    result = {"@expr": type(expr).__name__}
    for f in fields(expr):
        value = getattr(expr, f.name)
        result[f.name] = _value_to_data(value)
    result["text"] = expr_to_text(expr)
    return result


def _value_to_data(value):
    if isinstance(value, Expr):
        return expr_to_dict(value)
    if isinstance(value, tuple):
        if value and all(isinstance(v, str) for v in value):
            if any("::" in v for v in value):
                return list(value)  # keep segments distinct (feature chains)
            return "::".join(value)
        return [_value_to_data(v) for v in value]
    if isinstance(value, float) and value == INF:
        return "*"
    return value


# ---------------------------------------------------------------------------
# JSON -> AST
# ---------------------------------------------------------------------------

_NODE_TYPES: dict[str, type[Expr]] = {}

#: fields that hold qualified names (serialized as "A::B" or a list of parts)
_QNAME_FIELDS: dict[str, frozenset[str]] = {
    "FeatureRef": frozenset({"parts"}),
    "ChainAccess": frozenset({"parts"}),
    "Classification": frozenset({"type"}),
    "Cast": frozenset({"type"}),
    "AllOf": frozenset({"type"}),
    "Invocation": frozenset({"target"}),
    "Constructor": frozenset({"type"}),
    "ArrowOp": frozenset({"name", "func"}),
    "MetadataAccess": frozenset({"target"}),
}

#: fields that hold (name, expression) pairs
_PAIR_FIELDS = frozenset({"named", "lets"})


def _decode_qname(value: str | list[str]) -> QName:
    if isinstance(value, str):
        return tuple(value.split("::"))
    return tuple(value)


def _decode_value(value: object) -> object:
    if isinstance(value, dict) and "@expr" in value:
        return expr_from_dict(value)
    if isinstance(value, list):
        return tuple(_decode_value(v) for v in value)
    return value


def expr_from_dict(data: dict | None) -> Expr | None:
    """Rebuild an expression AST from :func:`expr_to_dict` output."""

    if data is None:
        return None
    if not isinstance(data, dict) or "@expr" not in data:
        raise ValueError(f"not a serialized expression: {data!r}")
    type_name = data["@expr"]
    cls = _NODE_TYPES.get(type_name)
    if cls is None:
        raise ValueError(f"unknown expression node type {type_name!r}")
    qname_fields = _QNAME_FIELDS.get(type_name, frozenset())
    kwargs: dict[str, object] = {}
    for f in fields(cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if value is None:
            kwargs[f.name] = None
        elif f.name in qname_fields:
            kwargs[f.name] = _decode_qname(value)
        elif f.name in _PAIR_FIELDS:
            kwargs[f.name] = tuple((n, expr_from_dict(e)) for n, e in value)
        else:
            kwargs[f.name] = _decode_value(value)
    if type_name == "Literal" and kwargs.get("value") == "*" and data.get("text") == "*":
        kwargs["value"] = INF  # bare '*' is infinity; '"*"' is a string
    return cls(**kwargs)


_NODE_TYPES.update(
    {
        cls.__name__: cls
        for cls in (
            Literal,
            FeatureRef,
            ChainAccess,
            Unary,
            Binary,
            Conditional,
            Classification,
            Cast,
            AllOf,
            SequenceExpr,
            IndexOp,
            QuantityOp,
            Param,
            BodyExpr,
            Invocation,
            Constructor,
            ArrowOp,
            CollectOp,
            SelectOp,
            MetadataAccess,
        )
    }
)
