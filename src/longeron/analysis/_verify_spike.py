"""EXPERIMENTAL -- model-driven requirement-violation hunting (spike).

.. warning::
   This module is a **prototype** backing ``notebooks/spike_verify.ipynb``.
   It is not part of the public API, not exported from
   :mod:`longeron.analysis`, not covered by tests, and its shape is
   expected to change (or vanish) behind the ``longeron.analysis.verify``
   design doc.  It needs `hypothesis <https://hypothesis.readthedocs.io>`_,
   which is deliberately NOT a project dependency.

The idea: a SysML v2 model already declares everything a property-based
tester needs -- attribute types give value domains, ``assert constraint``
bodies give (minable) ranges, ``assume``/``require`` constraints give the
universal property *assumptions-hold implies requirements-satisfied*, and
state machines give the alphabet of adversarial event sequences.  This
module derives Hypothesis strategies from the model and hunts for the
minimal configuration that breaks a requirement.

Semantics note (load-bearing): a violated **assumption** makes a
requirement *inapplicable*, and :class:`~longeron.interpreter.
RequirementResult.satisfied` is ``None`` -- a VACUOUS pass, never a
failure.  The hunt only reports configurations where every assumption
holds and a ``require`` constraint (or an ``assert constraint`` on the
subject) is actually false.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .. import ast as A
from .. import model as M
from ..interpreter import Interpreter
from ._expr import constraint_expr, named_members

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from hypothesis.strategies import SearchStrategy

__all__ = [
    "Domain",
    "Verdict",
    "attribute_domains",
    "bisect_boundary",
    "events_of",
    "hunt",
    "strategies_for",
    "verdict",
]

#: bounds used when no range can be mined from the model's constraints
_FALLBACK_BOUNDS = (-1.0e6, 1.0e6)


# ---------------------------------------------------------------------------
# domains: what the model says an attribute may be
# ---------------------------------------------------------------------------


@dataclass
class Domain:
    """The value domain of one free attribute, as derived from the model."""

    name: str
    kind: str  # 'Real' | 'Integer' | 'Boolean' | enum qualified name
    lo: float | None = None  # mined lower bound (inclusive), if any
    hi: float | None = None  # mined upper bound (inclusive), if any
    mined_from: list[str] = field(default_factory=list)  # constraint names
    literals: list[Any] = field(default_factory=list)  # enum values

    @property
    def bounded(self) -> bool:
        return self.lo is not None and self.hi is not None


_COMPARE_LO = {">": "lo", ">=": "lo", "<": "hi", "<=": "hi"}


def _mine_comparison(dom: Domain, expr: A.Expr, label: str) -> None:
    """Fold ``attr <op> literal`` (either orientation) into ``dom``."""

    if isinstance(expr, A.Binary) and expr.op == "and":
        _mine_comparison(dom, expr.left, label)
        _mine_comparison(dom, expr.right, label)
        return
    if not (isinstance(expr, A.Binary) and expr.op in _COMPARE_LO):
        return
    left, right, op = expr.left, expr.right, expr.op
    if isinstance(right, A.FeatureRef) and isinstance(left, A.Literal):
        # literal <op> attr  ==  attr <flipped-op> literal
        flip = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}
        left, right, op = right, left, flip[op]
    if not (
        isinstance(left, A.FeatureRef)
        and left.parts == (dom.name,)
        and isinstance(right, A.Literal)
        and isinstance(right.value, (int, float))
        and not isinstance(right.value, bool)
    ):
        return
    value = float(right.value)
    side = _COMPARE_LO[op]
    if side == "lo" and (dom.lo is None or value > dom.lo):
        dom.lo = value
    if side == "hi" and (dom.hi is None or value < dom.hi):
        dom.hi = value
    dom.mined_from.append(label)


def attribute_domains(
    interp: Interpreter, defn: M.Definition | M.Usage, free: tuple[str, ...]
) -> dict[str, Domain]:
    """Domains for the named free attributes of ``defn``.

    Types come from the attribute declarations; numeric ranges are mined
    from the definition's own (and inherited) constraint bodies wherever
    the attribute is compared directly against a literal.  Ranges that
    only bind the attribute *through derived attributes* (``payloadMass``
    reached via ``totalMass``) are NOT found -- that reachability pass is
    the design-doc item, prototyped by :mod:`longeron.analysis.smt`'s
    symbolic-marking fixed point.
    """

    domains: dict[str, Domain] = {}
    attrs = {
        (m.name or m.short_name): m for m in named_members(interp, defn, ("attribute", "enum"))
    }
    for name in free:
        attr = attrs.get(name)
        if attr is None:
            raise ValueError(f"{defn.label} has no attribute {name!r}")
        kind = "Real"
        for type_name in attr.types:
            tail = type_name.split("::")[-1]
            if tail in ("Real", "Integer", "Natural", "Boolean"):
                kind = "Integer" if tail == "Natural" else tail
                break
        else:
            if attr.types:  # maybe an enum
                try:
                    typ = interp.resolver.resolve(attr.types[0], attr.owner or interp.model)
                except Exception:  # domain stays Real on resolution failure
                    typ = None
                if isinstance(typ, M.EnumerationDefinition) and typ.literals:
                    env_value = [
                        interp.evaluate(A.FeatureRef((lit.name,)), typ) for lit in typ.literals
                    ]
                    domains[name] = Domain(
                        name, typ.qualified_name or typ.label, literals=env_value
                    )
                    continue
        dom = Domain(name, kind)
        if kind == "Natural":
            dom.lo = 0.0
        for con in named_members(interp, defn, ("constraint",)):
            body = constraint_expr(interp, con)
            if body is not None:
                _mine_comparison(dom, body, con.name or con.label)
        domains[name] = dom
    return domains


def strategies_for(
    interp: Interpreter,
    defn: M.Definition | M.Usage,
    free: tuple[str, ...],
    fallback: tuple[float, float] = _FALLBACK_BOUNDS,
) -> dict[str, SearchStrategy[Any]]:
    """Hypothesis strategies for the free attributes (from their domains)."""

    from hypothesis import strategies as st

    out: dict[str, SearchStrategy[Any]] = {}
    for name, dom in attribute_domains(interp, defn, free).items():
        if dom.literals:
            out[name] = st.sampled_from(dom.literals)
        elif dom.kind == "Boolean":
            out[name] = st.booleans()
        elif dom.kind == "Integer":
            lo = int(dom.lo) if dom.lo is not None else int(fallback[0])
            hi = int(dom.hi) if dom.hi is not None else int(fallback[1])
            out[name] = st.integers(min_value=lo, max_value=hi)
        else:
            lo = dom.lo if dom.lo is not None else fallback[0]
            hi = dom.hi if dom.hi is not None else fallback[1]
            out[name] = st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)
    return out


# ---------------------------------------------------------------------------
# the property: assumptions hold => requirements satisfied
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    """One configuration's outcome under the universal property."""

    bindings: dict[str, Any]
    violated: list[str] = field(default_factory=list)  # actually-false checks
    vacuous: list[str] = field(default_factory=list)  # assumption-violated reqs

    @property
    def ok(self) -> bool:
        """True when nothing applicable failed (vacuous passes count as OK)."""

        return not self.violated


def verdict(
    interp: Interpreter,
    part: str | M.Definition | M.Usage,
    requirements: tuple[str, ...],
    bindings: dict[str, Any],
) -> Verdict:
    """Instantiate ``part`` under ``bindings`` and check everything.

    ``assert constraint`` members of the part are violations when false;
    requirement ``require`` constraints are violations only when every
    ``assume`` constraint holds (otherwise the requirement is VACUOUS --
    recorded, never failed).
    """

    instance = interp.instantiate(part, dict(bindings))
    out = Verdict(bindings=dict(bindings))
    for con in interp.check(instance):
        if con.passed is False:
            out.violated.append(f"{con.name} [{con.kind}]")
    for req_name in requirements:
        result = interp.check_requirement(req_name, subject=instance)
        if not result.applicable:
            out.vacuous.append(result.name)
        elif result.satisfied is False:
            out.violated.extend(
                f"{result.name}::{c.name}" for c in result.requirements if c.passed is False
            )
    return out


def hunt(
    interp: Interpreter,
    part: str | M.Definition | M.Usage,
    requirements: tuple[str, ...] = (),
    free: tuple[str, ...] = (),
    max_examples: int = 200,
    fallback: tuple[float, float] = _FALLBACK_BOUNDS,
) -> Verdict | None:
    """Search for the minimal configuration violating the property.

    Derives strategies from the model, then uses ``hypothesis.find`` to
    locate -- and SHRINK to -- the simplest bindings for which
    :func:`verdict` reports a violation.  Returns ``None`` when
    ``max_examples`` configurations found nothing.
    """

    from hypothesis import HealthCheck, Phase, find, settings
    from hypothesis import strategies as st
    from hypothesis.errors import NoSuchExample

    target = interp.resolve(part) if isinstance(part, str) else part
    strats = strategies_for(interp, target, free, fallback)
    spec = st.fixed_dictionaries(strats)
    opts = settings(
        max_examples=max_examples,
        database=None,
        derandomize=True,
        phases=(Phase.generate, Phase.shrink),
        suppress_health_check=list(HealthCheck),
    )
    try:
        worst = find(
            spec,
            lambda b: not verdict(interp, target, requirements, b).ok,
            settings=opts,
        )
    except NoSuchExample:
        return None
    return verdict(interp, target, requirements, worst)


def bisect_boundary(
    predicate: Callable[[float], bool],
    lo: float,
    hi: float,
    tol: float = 1e-9,
) -> float:
    """The threshold where ``predicate`` flips from False (at ``lo``) to
    True (at ``hi``) -- refine a shrunk counterexample to the exact edge."""

    if predicate(lo) or not predicate(hi):
        raise ValueError("expected predicate(lo)=False and predicate(hi)=True")
    while hi - lo > tol:
        mid = (lo + hi) / 2.0
        if predicate(mid):
            hi = mid
        else:
            lo = mid
    return hi


# ---------------------------------------------------------------------------
# state machines: the event alphabet
# ---------------------------------------------------------------------------


def events_of(interp: Interpreter, state_machine: str | M.Definition | M.Usage) -> list[str]:
    """Event names accepted anywhere in a state machine definition.

    Walks own + inherited members (nested states included) for event
    triggers -- the alphabet a stateful hunt draws its rules from.
    """

    target = interp.resolve(state_machine) if isinstance(state_machine, str) else state_machine
    events: set[str] = set()

    def visit(container: M.Definition | M.Usage) -> None:
        for member in interp.resolver.members_of(container):
            if isinstance(member, M.TransitionUsage):
                trigger = member.trigger
                if trigger is None or trigger.trigger_kind is not None:
                    continue  # completion / time / when triggers: not events
                for type_name in trigger.payload_types:
                    events.add(type_name.split("::")[-1])
                if trigger.payload_name and not trigger.payload_types:
                    events.add(trigger.payload_name)
            elif isinstance(member, M.Usage) and member.kind == "state":
                visit(member)

    visit(target)
    return sorted(events)
