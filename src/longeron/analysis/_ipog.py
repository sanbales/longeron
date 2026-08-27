"""In-house t-way covering arrays: IPOG-F on the stdlib, nothing else.

The generator behind :func:`longeron.analysis.verify.cover`.  It builds a
t-way covering array (every valid combination of values of every t factors
appears in at least one row) with the IPOG family's *in-parameter-order*
strategy (Lei et al., "IPOG: A General Strategy for T-Way Software
Testing"), F-style: horizontal growth chooses each new cell greedily by
uncovered-tuple gain and leaves the cell a **don't-care** when nothing is
gained, which the vertical-growth phase then reuses for free.

Constraints enter through one seam: ``extendable(assignment) -> bool``
answers whether a *partial* assignment (a ``{factor: level}`` dict) can be
extended to at least one full constraint-satisfying row (existential
semantics).  :mod:`longeron.analysis.verify` supplies a Z3-backed engine
built from the model's own constraints; ``None`` means unconstrained.
With existential semantics every greedy step preserves extendability, so
generation never paints itself into a corner.

Deliberate ceilings (refused loudly, never degraded quietly):

* strength ``t`` in 2..6 -- IPOG-D-style doubling constructions for
  higher strengths / hundreds of factors were ruled out (longeron's
  catalogs are dozens of factors at most);
* at most 64 factors, each with at least one level;
* ``t`` at most the number of factors.

Array-size optimality is explicitly secondary (one longeron "test
execution" is one sub-millisecond interpreter evaluation), but the sizes
are honest.  Measured on this implementation (dev-time comparison, never
a CI dependency) against the published IPOG results in Lei et al. 2007
for the TCAS module (10^2 4^1 3^2 2^7, twelve factors) and the standard
small benchmarks -- generation times on Apple Silicon, single process:

======================== ==== =========== ============== =========
benchmark                  t   this module  published IPOG  generate
======================== ==== =========== ============== =========
TCAS                       2       100          100          <0.01 s
TCAS                       3       405          400           0.1 s
TCAS                       4      1374         1361           0.7 s
TCAS                       5      4226         4219           4.5 s
TCAS                       6     10955        10919            51 s
3^4                        2        10            9 (opt.)  <0.01 s
3^13                       2        21           20          <0.01 s
3^13                       3        77           n/a          0.03 s
======================== ==== =========== ============== =========

Every array above passes :func:`check_cover` -- zero missing tuples, zero
invalid rows -- via the independent checker, not the generator's own
bookkeeping.

The self-validating coverage checker (:func:`check_cover`) is deliberately
*independent* code -- plain tuple enumeration against the rows, no IPOG
arithmetic -- so a generator bug cannot hide behind its own bookkeeping.
It backs the CI property tests in ``tests/test_verify.py``.
"""

from __future__ import annotations

from itertools import combinations, product
from typing import TYPE_CHECKING

from ._expr import AnalysisError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Sequence

    #: one factor: (name, levels); levels are opaque strings
    Factor = tuple[str, tuple[str, ...]]
    Extendable = Callable[[dict[str, str]], bool]

__all__ = ["MAX_FACTORS", "MAX_STRENGTH", "check_cover", "generate"]

MAX_STRENGTH = 6
MAX_FACTORS = 64


def _validate(factors: Sequence[Factor], t: int) -> None:
    if not 2 <= t <= MAX_STRENGTH:
        raise AnalysisError(
            f"covering-array strength t={t} is outside the supported 2..{MAX_STRENGTH} "
            "(higher strengths need doubling constructions -- IPOG-D -- which "
            "this implementation deliberately refuses; see the module docstring)"
        )
    if len(factors) > MAX_FACTORS:
        raise AnalysisError(
            f"{len(factors)} factors exceed the documented {MAX_FACTORS}-factor ceiling "
            "(IPOG-F is sized for catalog-scale problems; refusing rather than degrading)"
        )
    if t > len(factors):
        raise AnalysisError(f"strength t={t} exceeds the {len(factors)} available factors")
    names = set()
    for name, levels in factors:
        if not levels:
            raise AnalysisError(f"factor {name!r} has no levels")
        if name in names:
            raise AnalysisError(f"duplicate factor name {name!r}")
        names.add(name)


def _key(assignment: dict[str, str]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted(assignment.items()))


def generate(
    factors: Sequence[Factor],
    t: int = 2,
    extendable: Extendable | None = None,
) -> list[dict[str, str]]:
    """A t-way covering array over ``factors`` as full assignment dicts.

    Every Z3-decidably valid t-tuple (one ``extendable`` says extends to a
    full satisfying row) is covered by at least one row, and every emitted
    row is itself ``extendable``-valid.  Deterministic: no randomness, ties
    broken by declaration order.
    """

    _validate(factors, t)
    ext = extendable if extendable is not None else (lambda _a: True)
    # in-parameter-order: widest factors first shrinks the array
    ordered = sorted(factors, key=lambda f: -len(f[1]))
    names = [name for name, _ in ordered]
    levels = dict(ordered)

    # seed: every valid combination of the first t factors
    rows: list[dict[str, str]] = []
    for combo in product(*(levels[n] for n in names[:t])):
        asg = dict(zip(names[:t], combo, strict=True))
        if ext(asg):
            rows.append(asg)

    for i in range(t, len(names)):
        new = names[i]
        # the valid, yet-uncovered t-tuples that involve the new factor
        uncovered: set[tuple[tuple[str, str], ...]] = set()
        for old_combo in combinations(names[:i], t - 1):
            for values in product(*(levels[n] for n in old_combo)):
                base = dict(zip(old_combo, values, strict=True))
                for v in levels[new]:
                    asg = {**base, new: v}
                    if ext(asg):
                        uncovered.add(_key(asg))

        # horizontal growth (F-style greedy, don't-care when gain is zero)
        for row in rows:
            if not uncovered:
                break  # remaining cells stay don't-care
            present = [n for n in names[:i] if n in row]
            best_v: str | None = None
            best_gain = -1
            best_covered: list[tuple[tuple[str, str], ...]] = []
            for v in levels[new]:
                if not ext({**row, new: v}):
                    continue
                covered = [
                    key
                    for combo in combinations(present, t - 1)
                    if (key := _key({**{n: row[n] for n in combo}, new: v})) in uncovered
                ]
                if len(covered) > best_gain:
                    best_v, best_gain, best_covered = v, len(covered), covered
            if best_v is not None and best_gain > 0:
                row[new] = best_v
                uncovered.difference_update(best_covered)

        # vertical growth: place leftovers into don't-cares, else new rows
        for key in sorted(uncovered):
            asg = dict(key)
            for row in rows:
                if all(row.get(n, v) == v for n, v in asg.items()):
                    merged = {**row, **asg}
                    if ext(merged):
                        row.update(asg)
                        break
            else:
                rows.append(dict(asg))

    # fill the remaining don't-cares (existential extendability guarantees
    # a valid completion is always greedily reachable); prefer the least-used
    # level per factor so filled cells keep the array diverse rather than
    # piling onto the first level
    used: dict[str, dict[str, int]] = {n: dict.fromkeys(levels[n], 0) for n in names}
    for row in rows:
        for name, value in row.items():
            used[name][value] += 1
    for row in rows:
        for name in names:
            if name in row:
                continue
            for v in sorted(levels[name], key=lambda v: used[name][v]):
                if ext({**row, name: v}):
                    row[name] = v
                    used[name][v] += 1
                    break
            else:  # pragma: no cover - unreachable with a sound engine
                raise AnalysisError(
                    f"constraint engine refused every level of {name!r} while "
                    "completing a row it previously called extendable"
                )
    original = [name for name, _ in factors]
    return [{n: row[n] for n in original} for row in rows]


def check_cover(
    factors: Sequence[Factor],
    rows: Sequence[dict[str, str]],
    t: int,
    extendable: Extendable | None = None,
) -> tuple[list[dict[str, str]], list[int]]:
    """The independent coverage checker: ``(missing_tuples, invalid_rows)``.

    Plain enumeration, no IPOG bookkeeping: every valid t-tuple (per
    ``extendable``) must appear in some row, and every row must be a full,
    ``extendable``-valid assignment.  Both lists empty == the array holds
    its guarantee.
    """

    _validate(factors, t)
    ext = extendable if extendable is not None else (lambda _a: True)
    levels = dict(factors)
    names = [name for name, _ in factors]

    invalid = [
        idx
        for idx, row in enumerate(rows)
        if set(row) != set(names)
        or any(row[n] not in levels[n] for n in names)
        or not ext(dict(row))
    ]
    missing: list[dict[str, str]] = []
    for combo in combinations(names, t):
        for values in product(*(levels[n] for n in combo)):
            asg = dict(zip(combo, values, strict=True))
            if not ext(asg):
                continue  # invalid tuple: not required to be covered
            if not any(all(row.get(n) == v for n, v in asg.items()) for row in rows):
                missing.append(asg)
    return missing, invalid
