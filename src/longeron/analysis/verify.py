"""Model-driven requirement-violation hunting: the model fights back.

Everything a property-based tester needs is already declared in the
``.sysml`` text: attribute types give value domains, ``assert constraint``
bodies give minable ranges, ``assume``/``require`` constraints give the
universal property *assumptions-hold implies requirements-satisfied*,
state machines give the event alphabet, and variation catalogs give the
discrete factors.  This module derives all of it, hunts, shrinks, proves,
and materializes every catch as re-checkable M0 individuals.

Four tiers over ONE oracle -- the interpreter.  Every verdict, in every
tier, comes from ``instantiate`` + ``check`` + ``check_requirement`` (or
``simulate`` for sequences), never from a solver's arithmetic; solvers
*propose*, the interpreter *decides* (the same honesty contract
:mod:`longeron.analysis.trades` keeps):

* :func:`hunt` -- Hypothesis sampling + shrinking: is there a *simple*
  violating configuration?  Strategies are derived from the model by the
  domain ladder (types -> direct constraint mining -> Z3 bounds through
  the reachability fixed point -> declared fallback), and every shrunk
  catch is paired with an oracle-bisected boundary.
* :func:`sequences` -- Hypothesis stateful testing over the *real*
  :class:`~longeron.interpreter.StateMachine`: is there a *minimal*
  violating event sequence?
* :func:`cover` -- in-house IPOG-F t-way covering arrays
  (:mod:`longeron.analysis._ipog`) with Z3 as the constraint engine:
  which discrete mixes violate, at t-way coverage?  Recall is *measured*
  against exhaustive ground truth whenever that stays feasible.
* :func:`prove` -- Z3 over :mod:`longeron.analysis.smt`'s encoding: is
  violation *impossible*?  Each check is negated one at a time under the
  assumption set; UNSAT is a proof of absence no sampling can deliver,
  SAT witnesses are re-checked by the interpreter before they are
  believed, and ``Optimize`` attributes exact rational feasibility bounds
  to the constraints that bind them.

:func:`verify` is the umbrella: it dispatches by what the scope *is* (a
state machine runs ``sequences``, an assembly with variation points runs
``cover``, any other part runs ``hunt`` + ``prove`` where encodable) and
returns one :class:`Report`.

Semantics worth pinning (normative): a violated ``assume`` constraint
makes a requirement *inapplicable* -- a **vacuous pass, never a
failure** (exactly :meth:`~longeron.interpreter.Interpreter.
check_requirement`'s existing contract).  A configuration is a violation
only when every assumption holds and a ``require`` constraint (or an
``assert constraint`` on the subject) is actually false.  Vacuous
outcomes are recorded on every report: a hunt that found *only* vacuous
ground is telling you your assumptions fence off the whole search space
-- a finding, not a pass.

Determinism policy (ratified): every Hypothesis run uses
``derandomize=True``, ``database=None``, and explicit generate/shrink
phases; seeds are accepted and echoed on every report, and reports are
reproducible from their own fields alone.

Requires the ``verify`` extra: ``pip install "longeron[verify]"``
(Hypothesis for ``hunt``/``sequences``; Z3 arrives via the bundled
``smt`` extra for ``cover``/``prove`` and the domain ladder's third
rung -- each is imported lazily, and tiers degrade to recorded ``gaps``
where an engine is missing).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from math import ceil, floor, prod
from typing import TYPE_CHECKING, Any, Literal

from .. import ast as A
from .. import m0
from .. import model as M
from ..errors import EvaluationError, MissingExtraError
from ..interpreter import Interpreter, StateMachine
from . import _ipog
from ._expr import AnalysisError, constraint_expr, is_scalar, named_members

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from ..m0 import Interpretation
    from .trades import TradeStudy

__all__ = [
    "Boundary",
    "Counterexample",
    "CounterexampleSource",
    "Coverage",
    "Domain",
    "Proof",
    "ProofStatus",
    "Report",
    "ReportStatus",
    "Verdict",
    "attribute_domains",
    "bisect_boundary",
    "counterexample_values",
    "cover",
    "events_of",
    "hunt",
    "prove",
    "sequences",
    "strategies_for",
    "verdict",
    "verify",
]

# ---------------------------------------------------------------------------
# closed vocabularies
# ---------------------------------------------------------------------------

#: which tier caught a counterexample
CounterexampleSource = Literal["hunt", "sequences", "cover", "prove"]

#: one negated check's verdict: UNSAT (nothing satisfying every other check
#: and assumption can violate it), a SAT witness the interpreter confirmed,
#: or the solver gave up / its witness did not survive the re-check
ProofStatus = Literal["proven-safe", "violation", "unknown"]

#: the whole report's outcome: nothing found, at least one confirmed
#: violation, or every negated check proven safe (``prove`` only)
ReportStatus = Literal["clean", "violated", "proven"]

#: bounds used when no range can be derived from the model (flagged on the
#: report -- never silent)
_FALLBACK_BOUNDS = (-1.0e6, 1.0e6)

#: clock advances offered to the sequence hunter when the machine under
#: test declares ``after``/``at`` time triggers
_CLOCK_ADVANCES = (1.0, 10.0, 60.0)

#: exhaustive ground truth for `cover` recall is measured up to this many
#: candidate mixes (interpreter evaluations run well under a millisecond)
_EXHAUSTIVE_CAP = 4096


def _hypothesis() -> Any:
    try:
        import hypothesis
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError("longeron.analysis.verify", "Hypothesis", "verify") from err
    return hypothesis


def _z3() -> Any:
    try:
        import z3
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError("longeron.analysis.verify", "Z3", "verify") from err
    return z3


# ---------------------------------------------------------------------------
# results: one report shape for every tier
# ---------------------------------------------------------------------------


@dataclass
class Domain:
    """The value domain of one free attribute, as derived from the model.

    ``mined_from`` records the derivation ladder's outcome rung by rung
    (types, mined constraints, Z3-derived assumption bounds, fallbacks),
    so the report always shows what was derived and what fell back.
    """

    name: str
    kind: str  # 'Real' | 'Integer' | 'Boolean' | enum qualified name
    lo: float | None = None  # derived lower bound (inclusive), if any
    hi: float | None = None  # derived upper bound (inclusive), if any
    mined_from: list[str] = field(default_factory=list)  # provenance, per rung
    literals: list[Any] = field(default_factory=list)  # enum values
    #: declared measurement annotation (``[SI::kg]``), informational only:
    #: unit-aware range derivation is a reserved rung of the ladder
    unit: str | None = None
    #: True when at least one side fell to the declared fallback range
    fallback: bool = False

    @property
    def bounded(self) -> bool:
        return self.lo is not None and self.hi is not None


@dataclass
class Verdict:
    """One configuration's outcome under the universal property."""

    bindings: dict[str, Any]
    violated: list[str] = field(default_factory=list)  # actually-false checks
    vacuous: list[str] = field(default_factory=list)  # assumption-violated reqs
    #: set when the oracle itself could not evaluate the configuration
    #: (physics outside its real domain: sqrt of a negative mass, ...)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """True when nothing applicable failed (vacuous passes count as OK)."""

        return not self.violated


@dataclass(frozen=True)
class Counterexample:
    """One catch: shrunk bindings, a minimal event sequence, or a bad mix."""

    bindings: dict[str, Any] = field(default_factory=dict)  # shrunk scalars
    events: tuple[str, ...] = ()  # minimal violating sequence
    violated: tuple[str, ...] = ()  # checks actually false
    source: CounterexampleSource = "hunt"
    selection: dict[str, str] = field(default_factory=dict)  # variant pins
    _materializer: Callable[[], Interpretation] | None = field(
        default=None, repr=False, compare=False
    )

    def materialize(self) -> Interpretation:
        """The catch as an M0 :class:`~longeron.m0.Interpretation` of
        identified individuals, re-checkable with the ordinary ``check`` /
        ``check_requirement`` machinery."""

        if self._materializer is None:
            raise AnalysisError("this counterexample carries no materialization context")
        return self._materializer()


@dataclass(frozen=True)
class Proof:
    """One negated check's verdict, with exact bounds where asked.

    ``status`` is ``'proven-safe'`` (UNSAT: no configuration satisfying
    every *other* check and every assumption can violate this one),
    ``'violation'`` (a SAT witness the interpreter confirmed), or
    ``'unknown'`` (the solver gave up, or its witness did not survive the
    interpreter re-check).  ``bound`` carries the exact rational supremum
    of a free attribute over the all-checks-hold region, attached to every
    proof of the query and attributed to ``binding_constraint`` -- the
    check whose exclusion moves that bound.
    """

    requirement: str
    status: ProofStatus
    bound: str = ""  # exact rational text when a bound query was asked
    binding_constraint: str = ""  # which check the bound is attributed to


@dataclass(frozen=True)
class Boundary:
    """One oracle-bisected edge: where ``violated`` flips along ``attribute``."""

    attribute: str
    value: float
    violated: str  # the check that flips at this edge


@dataclass
class Coverage:
    """A covering array's outcome: rows, and *measured* recall when feasible."""

    t: int
    rows: list[dict[str, str]] = field(default_factory=list)  # selection dicts
    #: violated-check recall vs interpreter-exact exhaustive ground truth;
    #: ``None`` when the exhaustive space was too large to enumerate (the
    #: honest guarantee is then: every valid t-tuple covered, violation
    #: coverage NOT guaranteed)
    recall: float | None = None
    exhaustive: int | None = None  # ground-truth size, when measured
    violated_rows: int = 0


@dataclass
class Report:
    """The one report shape every tier (and the umbrella) returns."""

    scope: str
    status: ReportStatus = "clean"
    violations: list[str] = field(default_factory=list)  # deduplicated names
    counterexamples: list[Counterexample] = field(default_factory=list)
    proofs: list[Proof] = field(default_factory=list)
    vacuous: list[str] = field(default_factory=list)
    domains: dict[str, Domain] = field(default_factory=dict)
    gaps: list[str] = field(default_factory=list)
    boundaries: list[Boundary] = field(default_factory=list)
    coverage: Coverage | None = None
    seed: int | None = None


def _record(seen: list[str], names: Any) -> None:
    """Ordered, deduplicated accumulation."""

    for name in names:
        if name not in seen:
            seen.append(name)


def _interpret_binder(
    interp: Interpreter,
    target: M.Definition | M.Usage,
    bindings: dict[str, Any],
    seed: int | None,
) -> Callable[[], Interpretation]:
    """A materializer closing over one catch's bindings (loop-safe)."""

    frozen = dict(bindings)

    def _materialize() -> Interpretation:
        return m0.interpret(interp.model, target, bindings=dict(frozen), seed=seed)

    return _materialize


def _architecture_binder(study: TradeStudy, arch: Any) -> Callable[[], Interpretation]:
    """A materializer closing over one covering-array row (loop-safe)."""

    def _materialize() -> Interpretation:
        return m0.from_architecture(study, arch)

    return _materialize


# ---------------------------------------------------------------------------
# the domain ladder: what the model says an attribute may be
# ---------------------------------------------------------------------------

_COMPARE_LO = {">": "lo", ">=": "lo", "<": "hi", "<=": "hi"}


def _literal_number(expr: A.Expr) -> float | None:
    """The numeric value of a literal, unary minus folded; ``None`` otherwise."""

    if (
        isinstance(expr, A.Unary)
        and expr.op == "-"
        and (inner := _literal_number(expr.operand)) is not None
    ):
        return -inner
    if (
        isinstance(expr, A.Literal)
        and isinstance(expr.value, (int, float))
        and not isinstance(expr.value, bool)
    ):
        return float(expr.value)
    return None


def _mine_comparison(dom: Domain, expr: A.Expr, label: str) -> None:
    """Fold ``attr <op> literal`` (either orientation) into ``dom``."""

    if isinstance(expr, A.Binary) and expr.op == "and":
        _mine_comparison(dom, expr.left, label)
        _mine_comparison(dom, expr.right, label)
        return
    if not (isinstance(expr, A.Binary) and expr.op in _COMPARE_LO):
        return
    left, right, op = expr.left, expr.right, expr.op
    if isinstance(right, A.FeatureRef) and _literal_number(left) is not None:
        # literal <op> attr  ==  attr <flipped-op> literal
        flip: dict[str, str] = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}
        left, right, op = right, left, flip[op]  # type: ignore[assignment]
    value = _literal_number(right)
    if not (isinstance(left, A.FeatureRef) and left.parts == (dom.name,) and value is not None):
        return
    side = _COMPARE_LO[op]
    if side == "lo" and (dom.lo is None or value > dom.lo):
        dom.lo = value
    if side == "hi" and (dom.hi is None or value < dom.hi):
        dom.hi = value
    dom.mined_from.append(f"mined: {label}")


def _declared_unit(interp: Interpreter, attr: M.Usage) -> str | None:
    """The attribute's measurement annotation, via the derived unit table."""

    if attr.value is None or not isinstance(attr.value.expr, A.QuantityOp):
        return None
    text = attr.value.expr.unit.to_text()
    try:
        from ..units import unit_table

        info = unit_table(interp.model).lookup(text)
    except Exception:  # pragma: no cover - table derivation misbehaving
        info = None
    return info.label if info is not None else text


def _rational_text(value: Any) -> float | None:
    """A Z3 optimum as a float; ``None`` when unbounded (``oo`` terms)."""

    text = str(value)
    if "oo" in text:
        return None
    token = text.split("+")[0].strip().lstrip("(").rstrip(")").strip()
    try:
        return float(Fraction(token))
    except (ValueError, ZeroDivisionError):
        return None


def _z3_window(
    interp: Interpreter,
    defn: M.Definition | M.Usage,
    requirements: tuple[str, ...],
    dom: Domain,
) -> None:
    """The ladder's third rung: exact bounds through the reachability
    fixed point.  :func:`longeron.analysis.smt.to_smt` is built with the
    attribute free; Z3 ``Optimize`` under the *assumption* set (value
    pins + ``assume`` bodies -- never the checks under test) yields
    provably tight sampling windows.  Refusals are honest and recorded."""

    try:
        z3 = _z3()
    except MissingExtraError:
        dom.mined_from.append("z3 bounds skipped: z3-solver not installed")
        return
    from .smt import to_smt

    try:
        system = to_smt(interp.model, defn, requirements=requirements, free=(dom.name,))
    except (AnalysisError, EvaluationError) as err:
        dom.mined_from.append(f"z3 bounds refused: {err}")
        return
    var = system.variables.get(dom.name)
    if var is None:
        dom.mined_from.append("z3 bounds refused: attribute not encodable")
        return
    keep = [
        expr
        for label, expr in system.assertions
        if label.endswith((".value", ".natural", " [assume]"))
    ]
    for side, maximize in (("lo", False), ("hi", True)):
        if getattr(dom, side) is not None:
            continue  # a mined direct bound is more specific; keep it
        opt = z3.Optimize()
        for expr in keep:
            opt.add(expr)
        handle = opt.maximize(var) if maximize else opt.minimize(var)
        if str(opt.check()) != "sat":
            dom.mined_from.append("z3 bounds: assumptions unsatisfiable or undecided")
            return
        exact = opt.upper(handle) if maximize else opt.lower(handle)
        value = _rational_text(exact)
        if value is None:
            dom.mined_from.append(f"z3 bounds: {side} unbounded under assumptions")
            continue
        setattr(dom, side, value)
        dom.mined_from.append(f"z3 bounds (assumption-derived): {side} = {exact}")


def _minable_constraints(
    interp: Interpreter, defn: M.Definition | M.Usage
) -> list[tuple[M.Usage, str]]:
    """The constraints rung 2 mines, with their provenance labels.

    Direct named constraint members (own + inherited), plus constraints
    nested one level inside ``objective`` members -- the spec's own home
    for a case's ``assume`` bounds (a case objective is usually anonymous,
    so the nested walk cannot ride ``named_members`` alone).  Labels are
    qualified names where the model provides them, so a report (and the
    surface engine's wiring map) can cite the exact constraint.
    """

    out = [
        (con, con.qualified_name or con.name or con.label)
        for con in named_members(interp, defn, ("constraint",))
    ]
    for member in interp.resolver.members_of(defn):
        if isinstance(member, M.Usage) and member.kind == "objective":
            out.extend(
                (con, con.qualified_name or con.name or con.label)
                for con in named_members(interp, member, ("constraint",))
            )
    return out


def attribute_domains(
    interp: Interpreter,
    defn: M.Definition | M.Usage,
    free: tuple[str, ...],
    requirements: tuple[str, ...] = (),
) -> dict[str, Domain]:
    """Value domains for the named free attributes of ``defn``.

    The derivation ladder, most specific source first, every rung recorded
    in :attr:`Domain.mined_from`:

    1. attribute types (``Real``/``Integer``/``Natural``/``Boolean``;
       enum types become literal lists; ``Natural`` adds a ``>= 0`` floor);
    2. direct constraint mining -- ``assert constraint`` bodies comparing
       the attribute against a literal (unary-minus literals folded),
       ``and``-conjunctions folded, and constraints nested in a case's
       ``objective`` included (the spec's home for ``assume`` bounds);
    3. Z3-derived bounds through :mod:`~longeron.analysis.smt`'s
       reachability fixed point, under the assumption set (bounds that
       live only on *derived* attributes are found here);
    4. the declared fallback (applied by :func:`strategies_for`, flagged).

    A reserved rung (unit-aware ranges from the model's measurement
    annotations) records the declared unit informationally only.
    """

    domains: dict[str, Domain] = {}
    attrs = {
        (m.name or m.short_name): m for m in named_members(interp, defn, ("attribute", "enum"))
    }
    for name in free:
        attr = attrs.get(name)
        if attr is None:
            raise AnalysisError(f"{defn.label} has no attribute {name!r}")
        kind = "Real"
        for type_name in attr.types:
            tail = type_name.split("::")[-1]
            if tail in ("Real", "Integer", "Natural", "Boolean"):
                kind = tail
                break
        else:
            if attr.types:  # maybe an enum
                try:
                    typ = interp.resolver.resolve(attr.types[0], attr.owner or interp.model)
                except Exception:  # domain stays Real on resolution failure
                    typ = None
                if isinstance(typ, M.EnumerationDefinition) and typ.literals:
                    literals = [
                        interp.evaluate(A.FeatureRef((lit.name or lit.label,)), typ)
                        for lit in typ.literals
                    ]
                    domains[name] = Domain(
                        name,
                        typ.qualified_name or typ.label,
                        literals=literals,
                        mined_from=[f"type: enum {typ.label} ({len(literals)} literals)"],
                    )
                    continue
        dom = Domain(name, "Integer" if kind == "Natural" else kind)
        dom.mined_from.append(f"type: {kind}")
        dom.unit = _declared_unit(interp, attr)
        if kind == "Natural":
            dom.lo = 0.0
            dom.mined_from.append("type: Natural >= 0")
        for con, label in _minable_constraints(interp, defn):
            body = constraint_expr(interp, con)
            if body is not None:
                _mine_comparison(dom, body, label)
        if dom.kind not in ("Boolean",) and not dom.bounded:
            _z3_window(interp, defn, requirements, dom)
        domains[name] = dom
    return domains


def strategies_for(
    interp: Interpreter,
    defn: M.Definition | M.Usage,
    free: tuple[str, ...],
    requirements: tuple[str, ...] = (),
    fallback: tuple[float, float] = _FALLBACK_BOUNDS,
    domains: dict[str, Domain] | None = None,
) -> dict[str, Any]:
    """Hypothesis strategies for the free attributes (from their domains).

    The values are ``hypothesis.strategies.SearchStrategy`` objects,
    annotated ``Any`` at this lazy-import boundary.  Sides the ladder
    could not bound take the ``fallback`` range and are flagged on the
    domain (:attr:`Domain.fallback`) -- never silent.
    """

    _hypothesis()
    from hypothesis import strategies as st

    if domains is None:
        domains = attribute_domains(interp, defn, free, requirements)
    out: dict[str, Any] = {}
    for name, dom in domains.items():
        if dom.literals:
            out[name] = st.sampled_from(dom.literals)
            continue
        if dom.kind == "Boolean":
            out[name] = st.booleans()
            continue
        lo, hi = dom.lo, dom.hi
        if lo is None:
            lo, dom.fallback = fallback[0], True
            dom.mined_from.append(f"fallback: lo = {fallback[0]:g}")
        if hi is None:
            hi, dom.fallback = fallback[1], True
            dom.mined_from.append(f"fallback: hi = {fallback[1]:g}")
        if lo > hi:
            raise AnalysisError(
                f"{name}: the derived domain is empty (lo {lo:g} > hi {hi:g}) -- "
                "the model's assumptions admit no value in the sampling window"
            )
        if dom.kind == "Integer":
            out[name] = st.integers(min_value=ceil(lo), max_value=floor(hi))
        else:
            out[name] = st.floats(min_value=lo, max_value=hi, allow_nan=False, allow_infinity=False)
    return out


# ---------------------------------------------------------------------------
# the universal property: assumptions hold => requirements satisfied
# ---------------------------------------------------------------------------


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
    recorded, never failed).  The interpreter is the sole oracle here;
    configurations its physics cannot evaluate (a sampled negative mass
    reaching a real ``sqrt``) come back with :attr:`Verdict.error` set --
    not a violation, not a pass, and never silently dropped.
    """

    out = Verdict(bindings=dict(bindings))
    try:
        instance = interp.instantiate(part, dict(bindings))
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
    except (EvaluationError, ArithmeticError, ValueError) as err:
        out.violated.clear()
        out.vacuous.clear()
        out.error = f"{type(err).__name__}: {err}"
    return out


# ---------------------------------------------------------------------------
# hunt: sampling + shrinking (+ oracle-bisected boundaries)
# ---------------------------------------------------------------------------


def bisect_boundary(
    predicate: Callable[[float], bool],
    lo: float,
    hi: float,
    tol: float = 1e-9,
) -> float:
    """The threshold where ``predicate`` flips from False (at ``lo``) to
    True (at ``hi``) -- refine a shrunk counterexample to the exact edge,
    against the same oracle that produced it."""

    if predicate(lo) or not predicate(hi):
        raise AnalysisError("expected predicate(lo)=False and predicate(hi)=True")
    while abs(hi - lo) > tol:
        mid = (lo + hi) / 2.0
        if predicate(mid):
            hi = mid
        else:
            lo = mid
    return hi


def hunt(
    model: M.Model,
    part: str | M.Definition | M.Usage,
    requirements: tuple[str, ...] = (),
    free: tuple[str, ...] = (),
    max_examples: int = 200,
    seed: int | None = None,
    fallback: tuple[float, float] = _FALLBACK_BOUNDS,
) -> Report:
    """Search for -- and shrink to -- a simple violating configuration.

    Strategies are derived from the model (:func:`attribute_domains`);
    Hypothesis's ``find`` locates and SHRINKS the simplest bindings whose
    :func:`verdict` reports a violation.  The shrunk catch is *simplest,
    not smallest*: per free scalar and violated check, the report pairs it
    with the oracle-bisected edge in :attr:`Report.boundaries` (and
    :func:`prove` supplies the exact algebraic edge where the model
    encodes).  Derandomized; ``seed`` is echoed on the report.
    """

    interp = Interpreter(model)
    target = interp.resolve(part) if isinstance(part, str) else part
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{part!r} is not a part definition")
    report = Report(scope=target.qualified_name or target.label, seed=seed)
    requirements = tuple(requirements)
    if not free:
        report.gaps.append("hunt needs free= attribute names; none were given")
        return report
    report.domains = attribute_domains(interp, target, tuple(free), requirements)

    _hypothesis()
    from hypothesis import HealthCheck, Phase, find, settings
    from hypothesis import strategies as st
    from hypothesis.errors import NoSuchExample

    strategies = strategies_for(
        interp, target, tuple(free), requirements, fallback, domains=report.domains
    )
    spec = st.fixed_dictionaries(strategies)
    vacuous_seen: list[str] = []
    errors_seen: list[str] = []
    witnesses: dict[str, dict[str, Any]] = {}  # first witness per violated check

    def failing(bindings: dict[str, Any]) -> bool:
        v = verdict(interp, target, requirements, bindings)
        _record(vacuous_seen, v.vacuous)
        if v.error is not None:
            _record(errors_seen, [v.error])
            return False  # unevaluable is not a violation (recorded as a gap)
        for name in v.violated:
            witnesses.setdefault(name, dict(bindings))
        return not v.ok

    options = settings(
        max_examples=max_examples,
        database=None,
        derandomize=True,
        phases=(Phase.generate, Phase.shrink),
        suppress_health_check=list(HealthCheck),
    )
    try:
        worst = find(spec, failing, settings=options)
    except NoSuchExample:
        worst = None
    report.vacuous = list(vacuous_seen)
    for error in errors_seen[:3]:
        report.gaps.append(f"hunt: some configurations were not evaluable ({error})")
    if worst is None:
        if vacuous_seen:
            report.gaps.append(
                "vacuous ground encountered: some sampled configurations "
                "violated an assumption (see report.vacuous)"
            )
        return report

    caught = verdict(interp, target, requirements, worst)
    report.status = "violated"
    _record(report.violations, caught.violated)
    _record(report.violations, witnesses)
    report.counterexamples.append(
        Counterexample(
            bindings=dict(worst),
            violated=tuple(caught.violated),
            source="hunt",
            _materializer=_interpret_binder(interp, target, worst, seed),
        )
    )
    # boundaries: the shrunk catch's checks bisect from the shrunk bindings;
    # checks seen violated only elsewhere in the search bisect from their
    # first recorded witness
    for check in caught.violated:
        witnesses[check] = dict(worst)
    for check, witness in witnesses.items():
        report.boundaries.extend(_boundaries(interp, target, requirements, witness, [check]))
    return report


def _boundaries(
    interp: Interpreter,
    target: M.Definition | M.Usage,
    requirements: tuple[str, ...],
    worst: dict[str, Any],
    violated: list[str],
) -> list[Boundary]:
    """Bisect, per free scalar and violated check, the edge between the
    part's declared baseline and the counterexample -- other free values
    held at the counterexample's."""

    baseline = interp.instantiate(target)
    out: list[Boundary] = []
    for name, bad in worst.items():
        default = baseline.slots.get(name)
        if not (is_scalar(bad) and is_scalar(default)) or bad == default:
            continue
        for check in violated:

            def hits(x: float, name: str = name, check: str = check) -> bool:
                probe = verdict(interp, target, requirements, {**worst, name: float(x)})
                return check in probe.violated

            if hits(default) or not hits(bad):
                continue  # this check does not flip along this attribute
            if default < bad:
                edge = bisect_boundary(hits, float(default), float(bad))
            else:
                edge = bisect_boundary(lambda x: not hits(x), float(bad), float(default))
            out.append(Boundary(attribute=name, value=edge, violated=check))
    return out


# ---------------------------------------------------------------------------
# sequences: adversarial events against the real state machine
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

    if isinstance(target, (M.Definition, M.Usage)):
        visit(target)
    return sorted(events)


def _has_time_triggers(interp: Interpreter, target: M.Definition | M.Usage) -> bool:
    found = False

    def visit(container: M.Definition | M.Usage) -> None:
        nonlocal found
        for member in interp.resolver.members_of(container):
            if isinstance(member, M.TransitionUsage):
                trigger = member.trigger
                if trigger is not None and trigger.trigger_kind in ("after", "at"):
                    found = True
            elif isinstance(member, M.Usage) and member.kind == "state":
                visit(member)

    visit(target)
    return found


class _SequenceViolation(AssertionError):
    def __init__(self, events: tuple[Any, ...], violated: tuple[str, ...]):
        super().__init__(f"{', '.join(violated)} violated after {list(events)}")
        self.events = events
        self.violated = violated


def sequences(
    model: M.Model,
    state_machine: str | M.Definition | M.Usage,
    requirements: tuple[str, ...] = (),
    inputs: dict[str, Any] | None = None,
    max_examples: int = 100,
    max_steps: int = 20,
    seed: int | None = None,
) -> Report:
    """Search for -- and shrink to -- a minimal violating event sequence.

    One generic rule sends an arbitrary event from the alphabet read off
    the model's transitions (:func:`events_of`; a clock-advance rule is
    added when the machine declares ``after``/``at`` triggers), and one
    invariant checks the ``requirements`` against the live simulation
    environment.  ``StateMachine.send`` records non-matching events as
    *ignored*, so the rule needs no preconditions and shrinking strips
    every irrelevant event from the reported sequence.
    """

    interp = Interpreter(model)
    target = interp.resolve(state_machine) if isinstance(state_machine, str) else state_machine
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{state_machine!r} is not a state machine")
    qname = target.qualified_name or target.label
    report = Report(scope=qname, seed=seed)
    requirements = tuple(requirements)
    alphabet = events_of(interp, target)
    if not alphabet:
        report.gaps.append(f"{qname} declares no event triggers; nothing to send")
        return report

    _hypothesis()
    from hypothesis import HealthCheck, Phase, settings
    from hypothesis import strategies as st
    from hypothesis.stateful import (
        RuleBasedStateMachine,
        invariant,
        rule,
        run_state_machine_as_test,
    )

    vacuous_seen: list[str] = []

    def _init(self: Any) -> None:
        RuleBasedStateMachine.__init__(self)
        self.sim = StateMachine(interp, target, dict(inputs or {}))
        self.sim.start()
        self.log = []

    def _send(self: Any, ev: str) -> None:
        self.sim.send(ev)
        self.log.append(ev)

    def _advance(self: Any, dt: float) -> None:
        self.sim.advance(dt)
        self.log.append(dt)

    def _requirements_hold(self: Any) -> None:
        env = dict(self.sim.env.frames[0])
        violated: list[str] = []
        for req_name in requirements:
            result = interp.check_requirement(req_name, bindings=env)
            if not result.applicable:
                _record(vacuous_seen, [result.name])
            elif result.satisfied is False:
                violated.extend(
                    f"{result.name}::{c.name}" for c in result.requirements if c.passed is False
                )
        if violated:
            raise _SequenceViolation(tuple(self.log), tuple(dict.fromkeys(violated)))

    namespace: dict[str, Any] = {
        "__init__": _init,
        "send": rule(ev=st.sampled_from(alphabet))(_send),
        "requirements_hold": invariant()(_requirements_hold),
    }
    if _has_time_triggers(interp, target):
        namespace["advance"] = rule(dt=st.sampled_from(_CLOCK_ADVANCES))(_advance)
    harness = type("_SequenceHunt", (RuleBasedStateMachine,), namespace)

    options = settings(
        max_examples=max_examples,
        stateful_step_count=max_steps,
        database=None,
        derandomize=True,
        phases=(Phase.generate, Phase.shrink),
        suppress_health_check=list(HealthCheck),
    )
    try:
        run_state_machine_as_test(harness, settings=options)
    except _SequenceViolation as caught:
        raw = list(caught.events)
        report.status = "violated"
        _record(report.violations, caught.violated)

        def _materialize() -> Interpretation:
            from .. import replay

            timeline = replay.record_timeline(interp, target, list(raw), inputs=dict(inputs or {}))
            return m0.from_timeline(timeline, interp, source=qname)

        report.counterexamples.append(
            Counterexample(
                events=tuple(str(e) for e in raw),
                violated=caught.violated,
                source="sequences",
                _materializer=_materialize,
            )
        )
    report.vacuous = list(vacuous_seen)
    return report


# ---------------------------------------------------------------------------
# cover: t-way covering arrays over the variation catalog
# ---------------------------------------------------------------------------


class _CatalogEngine:
    """Z3 as the covering-array constraint engine, for the *assumed* rules.

    Selection literals per variant, attribute channels per variation
    point, and the assembly's derived attributes plus the **named**
    ``assume`` constraints encoded through
    :class:`longeron.analysis.smt._Builder` -- the *model's own*
    constraint bodies, no parallel constraint DSL.  Only the assumed
    (build-rule) constraints are enforced: the checks under test can
    never be generation constraints, or the array could catch nothing by
    construction.  Bodies that refuse to encode (nonlinear physics over
    free channels) are recorded in ``gaps``; the array is then generated
    unconstrained with respect to them, and every row is settled by the
    interpreter anyway.

    ``extendable`` answers whether a partial selection can extend to a
    full row satisfying every *encoded* assumed constraint (``unknown``
    counts as extendable: the interpreter re-check is the safety net).
    """

    def __init__(self, study: TradeStudy, assume: tuple[str, ...]):
        from . import smt as smt_mod

        z3 = _z3()
        self.z3 = z3
        self.gaps: list[str] = []
        self.solver = z3.Solver()
        self.sel: dict[str, dict[str, Any]] = {}
        system = smt_mod.SmtSystem()
        builder = smt_mod._Builder(study.interp, system, frozenset())
        for pname, point in study.points.items():
            variants = list(point.variants)
            literals = {v: z3.Bool(f"{pname}={v}") for v in variants}
            self.sel[pname] = literals
            self.solver.add(z3.PbEq([(lit, 1) for lit in literals.values()], 1))
            shared = set(point.variants[variants[0]])
            for v in variants[1:]:
                shared &= set(point.variants[v])
            for attr in sorted(shared):
                if not all(is_scalar(point.variants[v][attr]) for v in variants):
                    continue  # string specs (e.g. wingSection) are not z3 reals
                const = z3.Real(f"{pname}.{attr}")
                system.variables[f"{pname}.{attr}"] = const
                for v in variants:
                    value = float(point.variants[v][attr])
                    self.solver.add(z3.Implies(literals[v], const == z3.RealVal(str(value))))
        for name, expr in study.derived_order:
            try:
                encoded = builder._encode(expr, study.assembly, "", {})
            except AnalysisError as err:
                self.gaps.append(f"{name}: {err}")
                continue
            const = z3.Real(name)
            system.variables[name] = const
            self.solver.add(const == encoded)
        matched: set[str] = set()
        for con in named_members(study.interp, study.assembly, ("constraint",)):
            label = con.name or con.label
            if label not in assume:
                continue
            matched.add(label)
            body = constraint_expr(study.interp, con)
            if body is None:
                self.gaps.append(f"{label}: no evaluable expression")
                continue
            try:
                encoded = builder._encode(body, study.assembly, "", {})
            except AnalysisError as err:
                self.gaps.append(f"{label}: {err}")
                continue
            if con.is_negated:
                encoded = z3.Not(encoded)
            self.solver.add(encoded)
        unknown = set(assume) - matched
        if unknown:
            raise AnalysisError(
                f"assume= names no assembly constraint(s): {sorted(unknown)} "
                f"(have: {study.constraint_names})"
            )

    def extendable(self, assignment: dict[str, str]) -> bool:
        pins = [self.sel[p][v] for p, v in assignment.items()]
        return str(self.solver.check(*pins)) != "unsat"


def cover(
    model: M.Model,
    assembly: str | M.Definition | M.Usage,
    t: int = 2,
    assume: tuple[str, ...] = (),
    seed: int | None = None,
    exhaustive_cap: int = _EXHAUSTIVE_CAP,
) -> Report:
    """A t-way covering array over the assembly's variation points, every
    row evaluated interpreter-exact.

    Factors come from :class:`~longeron.analysis.trades.TradeStudy`'s
    variation points (homogeneous selection per point); rows are ordinary
    selection dicts, evaluated via the same path ``TradeStudy.evaluate``
    uses.  By default the array ranges over the WHOLE candidate space:
    the assembly's constraints are the checks under test, and an array
    constrained by the checks it hunts could catch nothing by
    construction.  ``assume=`` names the constraints that are *build
    rules* rather than checks (component compatibility: matching cell
    counts, prop fit); those are enforced during generation through the
    Z3 constraint engine, and violations are hunted among the rest --
    the covering-array reading of the universal property.

    When the exhaustive space fits under ``exhaustive_cap`` candidate
    mixes, :attr:`Coverage.recall` *measures* violated-check recall
    against interpreter-exact ground truth (assumed constraints excluded
    on both sides); when it does not, the report states the honest
    guarantee instead -- every valid t-tuple covered, violation coverage
    not guaranteed.
    """

    from .trades import TradeStudy

    study = TradeStudy(model, assembly)
    report = Report(scope=study.assembly.qualified_name or study.assembly.label, seed=seed)
    factors = [(name, tuple(point.variants)) for name, point in study.points.items()]
    assume = tuple(assume)
    engine: _CatalogEngine | None = None
    if assume:
        try:
            engine = _CatalogEngine(study, assume)
            report.gaps.extend(
                f"cover (assumed rule not encoded; rows may violate it): {g}" for g in engine.gaps
            )
        except MissingExtraError:
            report.gaps.append(
                "cover: z3-solver not installed; assume= rules not enforced "
                "during generation (every row still settled by the interpreter)"
            )
    rows = _ipog.generate(factors, t, engine.extendable if engine is not None else None)

    found: list[str] = []
    violated_rows = 0
    for row in rows:
        arch = study.evaluate(row)
        under_test = [v for v in arch.violations if v not in assume]
        if arch.violations:
            violated_rows += 1
            _record(found, arch.violations)
        if under_test:
            report.counterexamples.append(
                Counterexample(
                    selection=dict(row),
                    violated=tuple(arch.violations),
                    source="cover",
                    _materializer=_architecture_binder(study, arch),
                )
            )
    _record(report.violations, (v for v in found if v not in assume))

    recall: float | None = None
    exhaustive_size: int | None = None
    total = prod(len(levels) for _, levels in factors)
    if total <= exhaustive_cap:
        truth: list[str] = []
        for arch in study.all_architectures():
            if any(v in assume for v in arch.violations):
                continue  # outside the assumed build rules: not ground truth
            _record(truth, (v for v in arch.violations if v not in assume))
        exhaustive_size = total
        recall = (len([v for v in truth if v in found]) / len(truth)) if truth else 1.0
    else:
        report.gaps.append(
            f"cover: exhaustive ground truth infeasible ({total} mixes > "
            f"{exhaustive_cap}); guarantee is t={t} tuple coverage, "
            "violation coverage not guaranteed"
        )
    report.coverage = Coverage(
        t=t,
        rows=rows,
        recall=recall,
        exhaustive=exhaustive_size,
        violated_rows=violated_rows,
    )
    if report.violations:
        report.status = "violated"
    return report


# ---------------------------------------------------------------------------
# prove: absence proofs and exact bounds (thin orchestration of smt)
# ---------------------------------------------------------------------------


def prove(
    model: M.Model,
    part: str | M.Definition | M.Usage,
    requirements: tuple[str, ...] = (),
    free: tuple[str, ...] = (),
    seed: int | None = None,
) -> Report:
    """Negate each check one at a time under the assumption set.

    Every ``require`` constraint of the named requirements and every
    ``assert constraint`` of the part is negated in turn, with the value
    pins, assumptions, and all *other* checks held: UNSAT is a **proof of
    absence** no sampling can deliver; SAT witnesses are re-checked by
    the interpreter before they are believed (the solver proposes, the
    interpreter decides).  Per free attribute, ``Optimize`` computes the
    exact rational supremum over the all-checks-hold region and
    attributes it to the check whose exclusion moves it (the *binding*
    constraint) -- carried on every :class:`Proof` of the query.

    Encodability is per-query, not per-model: where a free path reaches
    nonlinear algebra the encoder refuses honestly, the refusal lands in
    :attr:`Report.gaps`, and the signal is to fall back to :func:`hunt`
    over the same scope.
    """

    z3 = _z3()
    from .smt import to_smt

    interp = Interpreter(model)
    target = interp.resolve(part) if isinstance(part, str) else part
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{part!r} is not a part definition")
    report = Report(scope=target.qualified_name or target.label, seed=seed)
    requirements = tuple(requirements)
    system = to_smt(model, target, requirements=requirements, free=tuple(free))
    report.gaps.extend(f"prove: {g}" for g in system.gaps)

    base = [
        (label, expr)
        for label, expr in system.assertions
        if label.endswith((".value", ".natural", " [assume]"))
    ]
    checks = [
        (label, expr)
        for label, expr in system.assertions
        if not label.endswith((".value", ".natural", " [assume]"))
    ]
    if not checks:
        report.gaps.append("prove: no encodable checks to negate")
        return report

    statuses: list[tuple[str, ProofStatus]] = []
    for label, expr in checks:
        solver = z3.Solver()
        for _, keep in base:
            solver.add(keep)
        for other_label, other in checks:
            if other_label != label:
                solver.add(other)
        solver.add(z3.Not(expr))
        outcome = str(solver.check())
        if outcome == "unsat":
            statuses.append((label, "proven-safe"))
            continue
        if outcome != "sat":
            statuses.append((label, "unknown"))
            report.gaps.append(f"prove: solver returned {outcome} for {label}")
            continue
        witness = system._witness(solver.model())
        bindings = {name: witness[name] for name in free if name in witness}
        confirmed = verdict(interp, target, requirements, bindings)
        _record(report.vacuous, confirmed.vacuous)
        if confirmed.error is not None:
            statuses.append((label, "unknown"))
            report.gaps.append(
                f"prove: Z3's witness for {label} was not evaluable by the "
                f"interpreter ({confirmed.error}); treated as unknown"
            )
        elif any(_same_check(label, v) for v in confirmed.violated):
            statuses.append((label, "violation"))
            _record(report.violations, confirmed.violated)
            report.counterexamples.append(
                Counterexample(
                    bindings=dict(bindings),
                    violated=tuple(confirmed.violated),
                    source="prove",
                    _materializer=_interpret_binder(interp, target, bindings, seed),
                )
            )
        else:
            statuses.append((label, "unknown"))
            report.gaps.append(
                f"prove: Z3's witness for {label} was not confirmed by the "
                "interpreter (vacuous or numeric-edge); treated as unknown"
            )

    bound_text, binding = "", ""
    if len(free) == 1 and free[0] in system.variables:
        bound_text, binding = _binding_bound(z3, system, base, checks, free[0])
    for label, status in statuses:
        report.proofs.append(
            Proof(requirement=label, status=status, bound=bound_text, binding_constraint=binding)
        )
    if any(status == "violation" for _, status in statuses):
        report.status = "violated"
    elif statuses and all(status == "proven-safe" for _, status in statuses):
        report.status = "proven"
    return report


def _same_check(smt_label: str, verdict_name: str) -> bool:
    """Match an SMT assertion label against a Verdict violation name."""

    def bare(text: str) -> str:
        return text.split(" [")[0].split("::")[-1]

    return bare(smt_label) == bare(verdict_name)


def _sup(z3: Any, assertions: list[tuple[str, Any]], var: Any) -> str:
    opt = z3.Optimize()
    for _, expr in assertions:
        opt.add(expr)
    handle = opt.maximize(var)
    if str(opt.check()) != "sat":
        return ""
    return str(opt.upper(handle))


def _binding_bound(
    z3: Any,
    system: Any,
    base: list[tuple[str, Any]],
    checks: list[tuple[str, Any]],
    name: str,
) -> tuple[str, str]:
    """The free attribute's exact supremum under every check, attributed to
    the first check whose exclusion moves it."""

    var = system.variables[name]
    bound = _sup(z3, base + checks, var)
    if not bound or "oo" in bound:
        return "", ""
    binding = ""
    for label, _ in checks:
        without = base + [(lbl, e) for lbl, e in checks if lbl != label]
        if _sup(z3, without, var) != bound:
            binding = label
            break
    return bound, binding


# ---------------------------------------------------------------------------
# the umbrella
# ---------------------------------------------------------------------------


def verify(
    model: M.Model,
    scope: str | M.Definition | M.Usage,
    requirements: tuple[str, ...] = (),
    free: tuple[str, ...] = (),
    seed: int | None = None,
    t: int = 2,
    max_examples: int = 200,
    max_steps: int = 20,
) -> Report:
    """Every applicable tier for one scope, one report.

    Dispatch is by what the scope *is*: a state machine runs
    :func:`sequences`; an assembly with variation points runs
    :func:`cover`; any other part definition/usage runs :func:`hunt` plus
    :func:`prove` where encodable.  Tiers that do not apply are skipped
    silently; tiers that apply but cannot run (missing extra, no free
    attributes) are recorded in :attr:`Report.gaps`.
    """

    interp = Interpreter(model)
    target = interp.resolve(scope) if isinstance(scope, str) else scope
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{scope!r} is not verifiable (need a part or state machine)")

    if target.kind == "state":
        return sequences(
            model, target, requirements, max_examples=max_examples, max_steps=max_steps, seed=seed
        )
    if target.kind not in ("part", "item"):
        raise AnalysisError(
            f"{target.label} ({target.kind}) is not verifiable "
            "(need a part/item definition or a state machine)"
        )

    if _has_variation_points(interp, target):
        report = cover(model, target, t=t, seed=seed)
        if requirements:
            report.gaps.append(
                "cover checks the assembly's own constraints; requirements= "
                "was ignored for this scope"
            )
        return report

    report = Report(scope=target.qualified_name or target.label, seed=seed)
    try:
        hunted = hunt(model, target, requirements, free, max_examples=max_examples, seed=seed)
        _merge(report, hunted)
    except MissingExtraError as err:
        report.gaps.append(f"hunt skipped: {err}")
    proven: Report | None = None
    try:
        proven = prove(model, target, requirements, free, seed=seed)
        _merge(report, proven)
    except MissingExtraError as err:
        report.gaps.append(f"prove skipped: {err}")
    if report.violations:
        report.status = "violated"
    elif proven is not None and proven.status == "proven":
        report.status = "proven"
    return report


def _has_variation_points(interp: Interpreter, target: M.Definition | M.Usage) -> bool:
    for member in named_members(interp, target, ("part", "item")):
        if not member.types:
            continue
        try:
            typ = interp.resolver.resolve(member.types[0], member.owner or target)
        except Exception:
            continue
        if isinstance(typ, (M.Definition, M.Usage)) and typ.is_variation:
            return True
    return False


def _merge(into: Report, tier: Report) -> None:
    _record(into.violations, tier.violations)
    into.counterexamples.extend(tier.counterexamples)
    into.proofs.extend(tier.proofs)
    _record(into.vacuous, tier.vacuous)
    into.domains.update(tier.domains)
    into.gaps.extend(tier.gaps)
    into.boundaries.extend(tier.boundaries)
    if tier.coverage is not None:
        into.coverage = tier.coverage


# ---------------------------------------------------------------------------
# integration: the scoreboard bridge
# ---------------------------------------------------------------------------


def counterexample_values(counterexample: Counterexample) -> dict[str, Any]:
    """A ``values=`` dict for the scoreboard from a materialized catch.

    The trade-study bridge (:func:`longeron.analysis.scoreboard.
    architecture_values`) generalized to counterexamples: the violator is
    materialized to M0 and its root individual's measured scalar slots
    become scoreboard bindings -- the requirement it drives below its ramp
    floor renders as the red cell.
    """

    interpretation = counterexample.materialize()
    return {
        name: value
        for name, value in interpretation.root.slots.items()
        if is_scalar(value) or isinstance(value, bool)
    }
