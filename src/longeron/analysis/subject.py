"""The subject of the grand tour: one mission architecture and its preset.

A **subject** is one mission architecture. It names a mission (a key of
:data:`longeron.analysis.dashboard.DEFAULT_MISSIONS`), one variant of the
mission's airframe variation point, one variant for each remaining
variation point, and a set of transient attribute overrides. A bare
airframe is never a subject, because the subject parameter of a mission
requirement is a ``MissionUAV``.

The module has three pure functions over the model and the trade study
(:mod:`longeron.analysis.trades`). No function creates a widget.

* :func:`preset` pins the airframe and picks the trade study's best
  selection for it. A **verified mix** is a mix that violates none of the
  mission's constraints. The preset is the verified mix with the largest
  mission metric. If the airframe has no verified mix, the preset is the
  mix with the fewest violations, and :attr:`Preset.basis` says so.
* :func:`craft_variant` maps a clicked definition to its airframe
  variant. A build configuration such as ``Rotorcraft::QuadCopter`` is
  not a catalog airframe, so it maps to ``None``.
* :func:`requirement_set` pairs each requirement definition with the
  first instance of the subject where the requirement applies. The
  interpreter decides conformance to the subject parameter and
  applicability.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Literal

from .. import model as M
from ..interpreter import Instance, Interpreter
from ._expr import AnalysisError
from .dashboard import DEFAULT_MISSIONS
from .trades import Architecture, TradeStudy

__all__ = [
    "MissionName",
    "Preset",
    "PresetBasis",
    "Subject",
    "craft_variant",
    "preset",
    "requirement_set",
]

#: the keys of :data:`~longeron.analysis.dashboard.DEFAULT_MISSIONS`, one
#: per mission context of ``ScoutMissions`` (a test keeps the two equal)
MissionName = Literal["ISR", "logistics", "intercept"]

#: how :func:`preset` chose its mix: ``"verified"`` is the best verified
#: mix, ``"fewest_violations"`` is the fallback for an airframe with no
#: verified mix
PresetBasis = Literal["verified", "fewest_violations"]


@dataclass(frozen=True)
class Subject:
    """One mission architecture: the referent of every tour pane.

    ``selection`` maps each variation point except the airframe point to
    a variant name. ``overrides`` maps an attribute path to a transient
    value. A transient value replaces the model value for the analysis
    only and never writes the model.
    """

    mission: MissionName
    airframe: str  #: the variant name of the airframe variation point
    selection: dict[str, str]
    overrides: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mission not in DEFAULT_MISSIONS:
            raise AnalysisError(
                f"unknown mission {self.mission!r} (have: {sorted(DEFAULT_MISSIONS)})"
            )

    def mix(self, *, point: str = "airframe") -> dict[str, str]:
        """The full selection, in the form :meth:`TradeStudy.evaluate` takes."""

        return {point: self.airframe, **self.selection}


@dataclass(frozen=True)
class Preset:
    """The trade study's selection for one airframe in one mission."""

    architecture: Architecture  #: the chosen mix, its metrics and violations
    basis: PresetBasis

    def subject(self, mission: MissionName, *, point: str = "airframe") -> Subject:
        """The subject that this preset fills, with no overrides."""

        mix = self.architecture.selection
        return Subject(mission, mix[point], {p: v for p, v in mix.items() if p != point})


def preset(study: TradeStudy, airframe: str, metric: str, *, point: str = "airframe") -> Preset:
    """The best mix for ``airframe`` by ``metric``, larger values first.

    The function pins ``point`` to ``airframe`` and evaluates every mix of
    the other variation points with the interpreter. The result is the
    verified mix with the largest ``metric``. If no mix is verified, the
    result is the mix with the fewest violations, and the larger
    ``metric`` breaks a tie. The ``basis`` field tells the two cases
    apart. Every :data:`~longeron.analysis.dashboard.DEFAULT_MISSIONS`
    metric is larger-is-better.
    """

    if point not in study.points:
        raise AnalysisError(f"unknown variation point {point!r} (have: {sorted(study.points)})")
    if airframe not in study.points[point].variants:
        raise AnalysisError(
            f"unknown variant {airframe!r} for point {point!r} "
            f"(have: {sorted(study.points[point].variants)})"
        )
    if metric not in dict(study.derived_order):
        raise AnalysisError(f"{metric!r} is not a derived attribute of {study.assembly.label}")
    others = [name for name in study.points if name != point]
    mixes = [
        study.evaluate({point: airframe, **dict(zip(others, combo, strict=True))})
        for combo in product(*(study.points[name].variants for name in others))
    ]
    verified = [arch for arch in mixes if arch.verified]
    if verified:
        return Preset(max(verified, key=lambda arch: arch.metrics[metric]), "verified")
    fallback = min(mixes, key=lambda arch: (len(arch.violations), -arch.metrics[metric]))
    return Preset(fallback, "fewest_violations")


def craft_variant(study: TradeStudy, element: M.Element, *, point: str = "airframe") -> str | None:
    """The variant of ``point`` that ``element`` names, or ``None``.

    ``element`` is a variant usage of the point's variation definition,
    or the definition that types a variant. The match is exact: a
    specialization of a variant's type does not match that variant. A
    build configuration such as ``Rotorcraft::QuadCopter`` types no
    variant, so the function returns ``None`` for it.
    """

    resolver = study.interp.resolver
    if point not in study.points:
        raise AnalysisError(f"unknown variation point {point!r} (have: {sorted(study.points)})")
    choice = resolver.resolve(study._point_type(point), study.assembly)
    if not isinstance(choice, M.Namespace):
        raise AnalysisError(f"{point!r} is not typed by a variation definition")
    for variant in choice.members:
        if not (isinstance(variant, M.Usage) and variant.is_variant and variant.name):
            continue
        if element is variant or any(
            resolver.resolve(name, variant.owner or choice) is element for name in variant.types
        ):
            return variant.name
    return None


def requirement_set(
    mission: Instance, airframe: Instance, *, interp: Interpreter
) -> dict[str, Instance]:
    """Each applicable requirement definition, with the instance it scores.

    ``mission`` is an instance of the mission definition, and
    ``airframe`` is the airframe instance that ``mission`` holds. If
    ``mission`` or ``airframe`` conforms to the type of the subject
    parameter, the requirement definition is a candidate. The
    interpreter checks a candidate against ``mission`` first, then
    against ``airframe``. The first instance that satisfies every assume
    constraint is the pair. An assume constraint that the interpreter
    cannot evaluate does not hold. A requirement that applies to neither
    instance is not in the result. The keys are qualified names, in
    model order.
    """

    pairs: dict[str, Instance] = {}
    for req in interp.model.iter_tree():
        if not (isinstance(req, M.Definition) and req.kind == "requirement"):
            continue
        # the first subject member is the one check_requirement binds
        subjects = [
            m
            for m in interp.resolver.members_of(req)
            if isinstance(m, M.Usage) and m.kind == "subject"
        ]
        if not subjects or not subjects[0].types or req.qualified_name is None:
            continue
        needed = interp.resolver.resolve(subjects[0].types[0], subjects[0].owner or req)
        for candidate in (mission, airframe):
            if not interp._conforms(candidate.definition, needed):
                continue
            if interp.check_requirement(req, candidate).applicable:
                pairs[req.qualified_name] = candidate
                break
    return pairs
