"""Shared expression-AST helpers for the analysis bridges.

These utilities walk the :mod:`sysml2.ast` nodes without evaluating them:
collecting the feature paths an expression references, rewriting selected
references to flat names, and pulling the boolean body out of constraint
usages.  They deliberately depend only on the core package (no solvers).
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any, TypeGuard

from .. import ast as A
from .. import model as M
from ..errors import SysMLError
from ..interpreter import Instance, Interpreter

QName = tuple[str, ...]


class AnalysisError(SysMLError):
    """Raised when a model construct cannot be mapped onto a solver."""


def sanitize(parts: QName) -> str:
    """A solver-safe flat name for a dotted/qualified feature path."""

    return "_".join(p.replace("::", "_") for p in parts)


# ---------------------------------------------------------------------------
# reference collection / rewriting
# ---------------------------------------------------------------------------


def free_refs(expr: A.Expr, bound: frozenset[str] = frozenset()) -> set[QName]:
    """Feature paths referenced by ``expr`` (invocation targets excluded).

    ``bound`` names (body-expression parameters) are skipped.  A
    ``ChainAccess`` whose base is a plain ``FeatureRef`` is reported as one
    combined path (``drone.totalMass`` -> ``("drone", "totalMass")``).
    """

    out: set[QName] = set()

    def visit(node: Any, bound: frozenset[str]) -> None:
        if isinstance(node, A.FeatureRef):
            if node.parts and node.parts[0] not in bound:
                out.add(node.parts)
            return
        if isinstance(node, A.ChainAccess) and isinstance(node.base, A.FeatureRef):
            base = node.base.parts
            if base and base[0] not in bound:
                out.add((*base, *node.parts))
            return
        if isinstance(node, A.BodyExpr):
            inner = bound | {p.name for p in node.params}
            for _, let_expr in node.lets:
                visit(let_expr, inner)
            if node.result is not None:
                visit(node.result, inner)
            return
        if isinstance(node, A.Expr):
            for f in fields(node):
                visit(getattr(node, f.name), bound)
            return
        if isinstance(node, tuple):
            for item in node:
                visit(item, bound)

    visit(expr, bound)
    return out


def rewrite_refs(expr: A.Expr, mapping: dict[QName, str | QName]) -> A.Expr:
    """Replace referenced paths with new (usually flat) names.

    Used to turn ``chassis.mass + payloadMass`` into
    ``chassis_mass + payloadMass`` so the interpreter can evaluate it against
    a flat frame of solver-supplied values.
    """

    def target(key: QName) -> A.FeatureRef:
        value = mapping[key]
        return A.FeatureRef((value,) if isinstance(value, str) else value)

    def visit(node: Any) -> Any:
        if isinstance(node, A.FeatureRef):
            if node.parts in mapping:
                return target(node.parts)
            return node
        if isinstance(node, A.ChainAccess) and isinstance(node.base, A.FeatureRef):
            combined = (*node.base.parts, *node.parts)
            if combined in mapping:
                return target(combined)
            return node
        if isinstance(node, A.Expr):
            changes = {f.name: visit(getattr(node, f.name)) for f in fields(node)}
            return replace(node, **changes)
        if isinstance(node, tuple):
            return tuple(visit(item) for item in node)
        return node

    return visit(expr)  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# model introspection
# ---------------------------------------------------------------------------


def constraint_expr(interp: Interpreter, usage: M.Usage) -> A.Expr | None:
    """The boolean body of a constraint usage (own or from its typing def)."""

    if usage.result is not None:
        return usage.result
    for name in [*usage.types, *usage.subsets]:
        try:
            target = interp.resolver.resolve(name, usage.owner or interp.model)
        except SysMLError:
            continue
        if isinstance(target, (M.Definition, M.Usage)) and target.result is not None:
            return target.result
    return None


def named_members(
    interp: Interpreter, defn: M.Definition | M.Usage, kinds: tuple[str, ...]
) -> list[M.Usage]:
    """Named usages of the given kinds, own + inherited."""

    return [
        m
        for m in interp.resolver.members_of(defn)
        if isinstance(m, M.Usage) and m.kind in kinds and (m.name or m.short_name)
    ]


def instance_path(instance: Instance, parts: QName) -> Any:
    """Walk ``parts`` through instance slots; ``None`` when any hop misses."""

    node: Any = instance
    for part in parts:
        if not isinstance(node, Instance) or part not in node.slots:
            return None
        node = node.slots[part]
    return node


def is_scalar(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)
