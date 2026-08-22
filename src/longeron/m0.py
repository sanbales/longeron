"""M0 interpretations: populations of identified individuals over a model.

Where :meth:`~longeron.interpreter.Interpreter.instantiate` produces one
anonymous deep instance, this module produces an :class:`Interpretation`:
a population of :class:`Individual` runtime instances with **stable
identities** (``qname#index`` paths), built under a **strategy**
(``"nominal"`` follows declared multiplicities and variant order;
``"random"`` draws seeded population sizes, variant choices, and unvalued
enum/Boolean attribute values), with KerML Annex A **sequence semantics**
(:meth:`Interpretation.sequences`) and **expression roll-ups over the
actual population** (:meth:`Interpretation.rollup` -- ``sum(rotors.mass)``
adds the four real rotor individuals instead of hand-encoding
``4.0 * rotorMass`` at M1).

The same representation covers *dynamic* semantics: every contiguous state
activation recorded by :func:`longeron.replay.record_timeline` is an
occurrence with a lifetime, and :func:`from_timeline` turns it into an
occurrence :class:`Individual` (``start``/``end``/``duration`` slots) in an
ordinary :class:`Interpretation` -- simulation traces and static
populations share one M0 story.  :func:`from_architecture` reads a trade
study's :class:`~longeron.analysis.trades.Architecture` as a *partial*
interpretation (the variant selection), so M0 roll-ups can be checked
against the metrics the trades machinery computes at M1.

Concepts follow pymbe's ``interpretation`` package (random interpretations,
Annex A atoms, calc roll-ups) but individuals stay runtime values -- the
M1 model is never mutated.

The OMG Systems Modeling API has no M0 payload; :meth:`Interpretation.
to_dict` is a deliberate longeron extension (JSON-able, ids included) and
is *not* part of ``to_api_json``.
"""

from __future__ import annotations

import random as _random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import ast as A
from . import model as M
from .errors import EvaluationError, ResolutionError
from .interpreter import Env, Instance, Interpreter, _LazyFrame

if TYPE_CHECKING:
    from .analysis.trades import Architecture, TradeStudy
    from .replay import Timeline

__all__ = ["Individual", "Interpretation", "from_architecture", "from_timeline", "interpret"]

#: random strategy: individuals drawn for an unbounded upper bound ``[n..*]``
#: are capped at ``lower + _UNBOUNDED_SPAN``
_UNBOUNDED_SPAN = 3

_MAX_DEPTH = 32


class _SelectionError(EvaluationError):
    """A bad variant pin: user input, never degraded to a gap."""


class Individual(Instance):
    """An M0 individual: a runtime :class:`Instance` with a stable identity.

    ``id`` is a ``qname#index`` path (``Pkg::Quad#0.rotors#2``); occurrence
    individuals from :func:`from_timeline` use ``qname@k`` and carry
    ``start``/``end``/``duration`` slots.
    """

    def __init__(self, id: str, type_name: str, definition: M.Definition | M.Usage | None = None):
        super().__init__(type_name, definition)
        self.id = id

    def to_dict(self) -> dict[str, Any]:
        return {"@id": self.id, **super().to_dict()}

    def __repr__(self) -> str:
        return f"<{self.id}: {self.type_name}>"


@dataclass
class Interpretation:
    """A population of M0 individuals for one M1 element."""

    source: str  #: qualified name of the interpreted element
    strategy: str  #: 'nominal' | 'random' | 'trace' (from_timeline)
    seed: int | None
    root: Individual
    #: variant chosen per variation-typed feature path (per-index for
    #: heterogeneous random populations, e.g. ``motors#2``)
    selection: dict[str, str] = field(default_factory=dict)
    #: feature paths whose evaluation degraded to None (with the reason)
    gaps: list[str] = field(default_factory=list)
    _interpreter: Interpreter | None = field(default=None, repr=False)
    _bindings: dict[str, Any] = field(default_factory=dict, repr=False)
    #: the caller-provided variant pins (what sample() re-applies)
    _pins: dict[str, str] = field(default_factory=dict, repr=False)

    # -- queries -------------------------------------------------------------

    def individuals(self, classifier: str | None = None) -> list[Individual]:
        """All individuals (root first, depth-first), optionally filtered to
        those conforming to ``classifier`` (a resolvable qualified name;
        occurrence individuals match on their recorded type name)."""

        out: list[Individual] = []

        def walk(value: Any) -> None:
            if isinstance(value, Individual):
                out.append(value)
                for slot_value in value.slots.values():
                    walk(slot_value)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        walk(self.root)
        if classifier is None:
            return out
        target: M.Element | None = None
        if self._interpreter is not None:
            try:
                target = self._interpreter.resolver.resolve(classifier)
            except ResolutionError:
                target = None

        def matches(ind: Individual) -> bool:
            if ind.definition is not None and target is not None:
                assert self._interpreter is not None
                return self._interpreter._conforms(ind.definition, target)
            return ind.type_name == classifier

        return [ind for ind in out if matches(ind)]

    def sequences(self, feature_path: str) -> list[tuple[Any, ...]]:
        """KerML Annex A sequences for a (dotted) feature path.

        A feature is interpreted as a set of sequences whose prefix is an
        individual of the featuring type: ``sequences("rotors")`` yields
        ``(quad, rotor_i)`` tuples, ``sequences("rotors.mass")`` yields
        ``(quad, rotor_i, 0.06)`` -- nested features are longer sequences.
        """

        seqs: list[tuple[Any, ...]] = [(self.root,)]
        for part in feature_path.split("."):
            extended: list[tuple[Any, ...]] = []
            for seq in seqs:
                node = seq[-1]
                if not isinstance(node, Instance) or part not in node.slots:
                    continue
                value = node.slots[part]
                for item in value if isinstance(value, list) else [value]:
                    extended.append((*seq, item))
            seqs = extended
        return seqs

    def rollup(self, expr: str | A.Expr) -> Any:
        """Evaluate an expression over the actual population.

        Feature references resolve against the root individual's slots, so
        multi-individual features yield the real value sequences and
        aggregates aggregate over them: ``rollup("sum(rotors.mass)")`` adds
        the four rotor individuals' masses.  A plain feature name evaluates
        that feature's declared M1 expression instead (which fails, honestly,
        when the M1 expression leans on the homogeneous ``4.0 * x``
        convention).
        """

        if self._interpreter is None:
            raise EvaluationError("this interpretation has no interpreter to evaluate with")
        interp = self._interpreter
        context: M.Namespace | None = None
        if isinstance(self.root.definition, M.Namespace):
            context = self.root.definition
        if isinstance(expr, str):
            member = None
            if context is not None:
                member = interp.resolver._member(context, expr)
            if isinstance(member, M.Usage) and member.value is not None:
                expr = member.value.expr
            else:
                from .builder import parse_expression

                expr = parse_expression(expr)
        env = Env(interp, context or interp.model, [{}], instance=self.root)
        return interp.eval(expr, env)

    def sample(self, n: int) -> list[Interpretation]:
        """``n`` fresh interpretations of the same element under derived
        seeds (random strategy only)."""

        if self.strategy != "random":
            raise EvaluationError("sample() needs strategy='random'")
        if self._interpreter is None:
            raise EvaluationError("this interpretation has no interpreter to sample with")
        rng = _random.Random(self.seed)
        seeds = [rng.randrange(2**31) for _ in range(n)]
        return [
            interpret(
                self._interpreter.model,
                self.source,
                strategy="random",
                seed=s,
                bindings=self._bindings or None,
                selection=self._pins or None,
            )
            for s in seeds
        ]

    def to_dict(self) -> dict[str, Any]:
        """A JSON-able projection (a longeron extension -- the OMG API has
        no M0 representation; see the module docstring)."""

        return {
            "source": self.source,
            "strategy": self.strategy,
            "seed": self.seed,
            "selection": dict(self.selection),
            "gaps": list(self.gaps),
            "root": self.root.to_dict(),
        }


# ---------------------------------------------------------------------------
# population construction
# ---------------------------------------------------------------------------


def interpret(
    model: M.Model | M.Definition | M.Usage,
    element: str | M.Definition | M.Usage | None = None,
    *,
    strategy: str = "nominal",
    seed: int | None = None,
    bindings: dict[str, Any] | None = None,
    selection: dict[str, str] | None = None,
) -> Interpretation:
    """Build an M0 interpretation of a part/item definition or usage.

    ``strategy="nominal"`` follows declared multiplicities (exact bounds
    expand fully, ranges take their lower bound -- matching
    ``Interpreter.instantiate``) and picks the first declared variant at
    unresolved variation points.  ``strategy="random"`` draws population
    sizes uniformly within multiplicity bounds (unbounded uppers capped at
    ``lower + 3``), chooses variants per individual, and samples unvalued
    enum/Boolean attributes from their literal domains -- all from one
    seeded generator, so equal seeds reproduce equal populations.

    ``bindings`` override root feature values by name; ``selection`` pins
    variation-typed feature paths (``{"motors": "emax2306"}``) under any
    strategy.  Evaluation failures degrade to ``None`` and are recorded in
    :attr:`Interpretation.gaps`.
    """

    if strategy not in ("nominal", "random"):
        raise EvaluationError(f"unknown strategy {strategy!r} (use 'nominal' or 'random')")
    if isinstance(model, M.Model):
        root_model = model
        if element is None:
            raise EvaluationError("interpret(model, ...) needs an element to interpret")
    else:
        if element is not None:
            raise EvaluationError("pass either (model, element) or a definition/usage alone")
        element = model
        node: M.Element | None = model
        while node is not None and not isinstance(node, M.Model):
            node = node.owner
        if not isinstance(node, M.Model):
            raise EvaluationError(f"{model.label} is not owned by a Model")
        root_model = node
    interp = Interpreter(root_model)
    target = interp.resolver.resolve(element) if isinstance(element, str) else element
    if not isinstance(target, (M.Definition, M.Usage)):
        raise EvaluationError(f"cannot interpret {element!r}")
    populator = _Populator(interp, strategy, seed, selection or {})
    root_id = f"{target.qualified_name or target.label}#0"
    root = populator.populate(target, root_id, dict(bindings or {}), "", 0, ())
    return Interpretation(
        source=target.qualified_name or target.label,
        strategy=strategy,
        seed=seed,
        root=root,
        selection=populator.chosen,
        gaps=populator.gaps,
        _interpreter=interp,
        _bindings=dict(bindings or {}),
        _pins=dict(selection or {}),
    )


class _Populator:
    """Mirrors ``Interpreter._instantiate`` with identity + strategy."""

    def __init__(
        self, interp: Interpreter, strategy: str, seed: int | None, selection: dict[str, str]
    ):
        self.interp = interp
        self.strategy = strategy
        self.rng = _random.Random(seed)
        self.selection = selection
        self.chosen: dict[str, str] = {}
        self.gaps: list[str] = []

    def populate(
        self,
        defn: M.Definition | M.Usage,
        ident: str,
        bindings: dict[str, Any],
        path: str,
        depth: int,
        active: tuple[int, ...],
    ) -> Individual:
        if depth > _MAX_DEPTH:
            raise EvaluationError("population recursion limit exceeded (cyclic composition?)")
        active = (*active, id(defn))
        individual = Individual(ident, defn.qualified_name or defn.label, defn)
        interp = self.interp
        members = [
            m
            for m in interp.resolver.members_of(defn)
            if isinstance(m, M.Usage)
            and m.kind not in Interpreter._NON_SLOT_KINDS
            and not m.is_abstract
            and not m.is_variant  # variation points are choices, not compositions
        ]
        pending: dict[str, M.Usage] = {}
        for member in members:
            name = member.name or (
                member.redefines[0].split("::")[-1] if member.redefines else None
            )
            if name is None or name in individual.slots or name in pending:
                continue
            pending[name] = member

        for name, value in bindings.items():
            if name not in pending:
                raise EvaluationError(f"{defn.label} has no feature {name!r} to bind")
            individual.slots[name] = value

        in_progress: set[str] = set()

        def materialize(name: str) -> Any:
            if name in individual.slots:
                return individual.slots[name]
            member = pending.get(name)
            if member is None:
                raise EvaluationError(f"{defn.label} has no feature {name!r}")
            if name in in_progress:
                raise EvaluationError(f"cyclic value dependency on {name!r} in {defn.label}")
            in_progress.add(name)
            try:
                value = compute(member, name)
            except _SelectionError:
                raise
            except EvaluationError as exc:
                if member.owner is defn:
                    # own features degrade too, but leave a trail (unlike
                    # _instantiate, which raises: an interpretation should
                    # report the whole population with honest holes)
                    self.gaps.append(f"{_join(path, name)}: {exc}")
                value = None
            finally:
                in_progress.discard(name)
            individual.slots[name] = value
            return value

        lazy_env = Env(interp, defn, [_LazyFrame(materialize, pending)], instance=individual)

        def compute(member: M.Usage, name: str) -> Any:
            if member.value is not None:
                return interp.eval(member.value.expr, lazy_env)
            if member.kind in ("part", "item", "occurrence") and member.types:
                return self._compose(member, name, ident, path, lazy_env, depth, active)
            if member.kind in ("part", "item") and member.members:
                return self.populate(
                    member, f"{ident}.{name}", {}, _join(path, name), depth + 1, active
                )
            if self.strategy == "random":
                return self._sample_attribute(member)
            return None

        for name in list(pending):
            if name not in individual.slots:
                materialize(name)
        return individual

    def _compose(
        self,
        member: M.Usage,
        name: str,
        owner_id: str,
        path: str,
        env: Env,
        depth: int,
        active: tuple[int, ...],
    ) -> Any:
        interp = self.interp
        try:
            target = interp.resolver.resolve(member.types[0], member.owner or interp.model)
        except ResolutionError:
            return None
        if not isinstance(target, (M.Definition, M.Usage)):
            return None
        if id(target) in active:
            return None  # self-referential composition (Part in Part)
        feature_path = _join(path, name)
        overrides = self._inline_overrides(member, env)
        count = self._count(member, env)

        def build(index: int | None) -> Individual:
            record = feature_path if index is None else f"{feature_path}#{index}"
            concrete = self._pick_variant(target, feature_path, record)
            suffix = f"{owner_id}.{name}" if index is None else f"{owner_id}.{name}#{index}"
            return self.populate(concrete, suffix, dict(overrides), feature_path, depth + 1, active)

        if count is None:
            return build(None)
        return [build(i) for i in range(count)]

    def _count(self, member: M.Usage, env: Env) -> int | None:
        """Population size for one feature (``None`` = a single individual)."""

        mult = member.multiplicity
        if mult is None or mult.upper is None:
            return None
        try:
            upper = self.interp.eval(mult.upper, env)
            lower = self.interp.eval(mult.lower, env) if mult.lower is not None else upper
        except EvaluationError:
            return 0
        lo = lower if isinstance(lower, int) else 0
        if isinstance(upper, int):
            if self.strategy == "random" and lo != upper:
                return self.rng.randint(lo, upper)
            return upper if lo == upper else lo
        # unbounded upper ('*')
        if self.strategy == "random":
            return self.rng.randint(lo, lo + _UNBOUNDED_SPAN)
        return lo

    def _pick_variant(
        self, target: M.Definition | M.Usage, feature_path: str, record: str | None = None
    ) -> M.Definition | M.Usage:
        """Resolve a variation-typed feature to one concrete variant.

        Pins are looked up by ``feature_path`` (homogeneous); the choice is
        recorded under ``record`` (per-index for populations, so a random
        heterogeneous draw stays inspectable).
        """

        if not target.is_variation:
            return target
        variants = [m for m in target.members if isinstance(m, M.Usage) and m.is_variant and m.name]
        if not variants:
            return target
        pinned = self.selection.get(feature_path)
        if pinned is not None:
            usage = next((v for v in variants if v.name == pinned), None)
            if usage is None:
                raise _SelectionError(
                    f"unknown variant {pinned!r} for {feature_path!r} "
                    f"(have: {sorted(v.name or '' for v in variants)})"
                )
        elif self.strategy == "random":
            usage = self.rng.choice(variants)
        else:
            usage = variants[0]
        homogeneous = pinned is not None or self.strategy != "random"
        self.chosen[feature_path if homogeneous else (record or feature_path)] = (
            usage.name or usage.label
        )
        if usage.types:
            resolved = self.interp.resolver.resolve(usage.types[0], target)
            if isinstance(resolved, (M.Definition, M.Usage)):
                return resolved
        return usage

    def _sample_attribute(self, member: M.Usage) -> Any:
        """Random strategy: sample an unvalued attribute from its domain
        (enum literals, Boolean); other domains stay ``None``."""

        if member.kind not in ("attribute", "enum") or not member.types:
            return None
        if member.types[0].split("::")[-1] == "Boolean":
            return self.rng.choice([False, True])
        try:
            typ = self.interp.resolver.resolve(member.types[0], member.owner or self.interp.model)
        except ResolutionError:
            return None
        if isinstance(typ, M.EnumerationDefinition) and typ.literals:
            literal = self.rng.choice(typ.literals)
            return self.interp._element_value(literal, Env(self.interp, self.interp.model, [{}]))
        return None

    def _inline_overrides(self, member: M.Usage, env: Env) -> dict[str, Any]:
        overrides: dict[str, Any] = {}
        for sub in member.members:
            if isinstance(sub, M.Usage) and sub.value is not None:
                name = sub.name or (sub.redefines[0].split("::")[-1] if sub.redefines else None)
                if name:
                    overrides[name] = self.interp.eval(sub.value.expr, env)
        return overrides


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


# ---------------------------------------------------------------------------
# integrations
# ---------------------------------------------------------------------------


def from_architecture(study: TradeStudy, architecture: Architecture) -> Interpretation:
    """Read a trade-study :class:`~longeron.analysis.trades.Architecture` as
    the partial M0 interpretation it is: the architecture pins every
    variation point's variant, the multiplicities populate the individuals
    (``motors : MotorChoice[4]`` becomes four individuals of the selected
    variant), and roll-ups over those individuals reproduce the metrics the
    trades machinery computed at M1.
    """

    return interpret(
        study.interp.model,
        study.assembly,
        strategy="nominal",
        selection=dict(architecture.selection),
    )


def from_timeline(
    timeline: Timeline,
    interpreter: Interpreter | None = None,
    *,
    source: str = "<execution>",
) -> Interpretation:
    """Turn a recorded :class:`~longeron.replay.Timeline` into an
    interpretation of occurrence individuals.

    Every contiguous activation of a state becomes one occurrence
    :class:`Individual` (id ``qname@k``) with ``start``/``end``/``duration``
    slots; the root individual spans the whole execution and owns them in
    activation order under ``occurrences``.  Roll-ups work as usual:
    ``rollup("sum(occurrences.duration)")``.
    """

    interp = interpreter if interpreter is not None else Interpreter(M.Model())
    root = Individual(f"{source}#0", source)
    root.slots["start"] = timeline.t_start
    root.slots["end"] = timeline.t_end
    root.slots["duration"] = timeline.t_end - timeline.t_start
    occurrences: list[Individual] = []
    for qname, keyframes in timeline.tracks.items():
        start: float | None = None
        k = 0
        for t, is_active in keyframes:
            if is_active and start is None:
                start = t
            elif not is_active and start is not None:
                occurrences.append(_occurrence(qname, k, start, t))
                start = None
                k += 1
        if start is not None:  # still active at the end of the recording
            occurrences.append(_occurrence(qname, k, start, timeline.t_end))
    occurrences.sort(key=lambda ind: (ind.slots["start"], ind.id))
    root.slots["occurrences"] = occurrences
    return Interpretation(
        source=source,
        strategy="trace",
        seed=None,
        root=root,
        _interpreter=interp,
    )


def _occurrence(qname: str, k: int, start: float, end: float) -> Individual:
    ind = Individual(f"{qname}@{k}", qname)
    ind.slots["start"] = start
    ind.slots["end"] = end
    ind.slots["duration"] = end - start
    return ind
