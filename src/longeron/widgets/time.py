"""The time seam: one clock, many views (the temporal selection seam).

The diagram replay player, the Cesium mission replay, and any future
time-aware view each expose a playhead as a widget trait.  This module
makes "when are we" one shared state with many subscribers, exactly as
the selection seam made "what is selected" one state (see
:doc:`/design/time`, the adopted contract).  Three toolkit pieces live
here:

* :class:`Clock` -- the shared playhead.  A small kernel-side object
  with no front-end, no timer, and no dependencies: views animate, the
  clock holds state and fans it out.  Seeks clamp into the span and
  coalesce within one JSON quantum (``1e-3``, the rounding
  :meth:`longeron.replay.Timeline.to_json` established), so every write
  settles at its first fixpoint -- the selection seam's no-echo
  discipline, restated for floats.
* :class:`Timebase` -- one recording, many views.  It aligns a
  :class:`~longeron.replay.Timeline` with its optional
  :class:`~longeron.analysis.mission3d.MissionTrack` binding, so every
  linked view plays the SAME recording.  The axis is the timeline's
  own: sim seconds, or the step index in step mode.  Step-only traces
  have no time axis, so a step-mode timebase REFUSES a track unless
  ``seconds_per_step`` states one -- a scalar, or a per-step
  sequence/mapping when steps take unequal durations.  Durations the
  caller states (for example from the model's own time triggers or
  occurrence durations) count as first-class; only the synthesized
  gaps are labeled synthetic (:meth:`Timebase.synthetic_intervals`).
* :func:`link_time` -- the temporal ``link_selection``.  It attaches
  each view through a small adapter that knows the view's ``time``
  trait and its axis mapping, wires ``playing``/``rate`` traits where
  the view has them, and returns an ``unlink()`` disposer.  A view
  holds ONE time link: linking it again unbinds the previous adapter
  first (the :func:`longeron.analysis.link.bind_config_view` handle
  pattern).

:func:`time_scrubber` is the fourth piece and the first new subscriber:
a standalone transport bar (play/pause, rate, the time axis with the
recording's event ticks and mission phase bands, a telemetry readout)
that subscribes to the clock like any other view.  It renders alone
under a dashboard, beside views that have no transport of their own.

Non-fighting rule (the Cesium bridge, phase 2 of the design): while
``playing``, every animating view integrates ``t`` locally at the
shared ``rate`` and reconciles against the clock at ~4 Hz; a follower
snaps only when its local time drifts past a bounded tolerance
(0.25 axis units, scaled by the rate), and on ``pause`` every view
converges exactly.  The scrubber's front-end and the mission viewer's
Cesium bridge (:mod:`longeron.widgets.mission3d`) both implement it.

The seam is LOSS-TOLERANT (:mod:`longeron.widgets._seam`): comm
messages get dropped under load and in-flight reports race kernel
seeks, so every kernel push carries a generation stamp, front-end
reports acknowledge the last stamp they saw, and the link REJECTS a
stale report (answering with an idempotent full-state re-push) instead
of letting it re-seek the clock.  The kernel clock is the source of
truth; front-ends reconcile to it.

Everything but the scrubber's front-end is pure kernel code: headless
tests drive ``clock.seek`` / ``clock.play`` and assert trait fan-out,
mirroring how the selection seam is tested without a browser.  The
playhead deliberately does NOT join the selection seam (decision Q7 of
the design), and the clock owns no wall-clock timer: a headless
``play()`` moves ``t`` only when a front-end or a test advances it.

Requires the ``replay`` extra (anywidget) for the scrubber widget only;
``Clock``, ``Timebase``, and ``link_time`` need nothing.
"""

from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..errors import MissingExtraError
from ._chrome import CONTROL_CSS
from ._seam import SEAM_ESM, SeamHost

if TYPE_CHECKING:
    import anywidget

    from ..analysis.mission3d import MissionTrack
    from ..replay import FiredTransition, Timeline

__all__ = [
    "Clock",
    "Timebase",
    "link_time",
    "step_seconds",
    "time_scrubber",
]

#: the coalescing tolerance: one JSON quantum (Timeline.to_json rounds
#: every key to 3 decimals, and the mission viewer's existing echo guard
#: uses the same number)
_TOLERANCE = 1e-3

#: the synthesized per-step duration where none is stated (the historic
#: ``seconds_per_step`` default of ``mission3d.from_replay``)
_DEFAULT_STEP_S = 10.0

#: the bounded-drift reconciliation tolerance while playing, in axis
#: units at rate 1.0 (the design's recommended number; followers scale
#: it by the rate)
_DRIFT = 0.25


# ---------------------------------------------------------------------------
# the step axis: steps -> seconds
# ---------------------------------------------------------------------------


def step_seconds(
    n_steps: int,
    seconds_per_step: float | Sequence[float] | Mapping[int, float],
) -> tuple[list[float], list[bool]]:
    """Map a step-mode axis onto seconds.

    A recording with ``n_steps`` steps has ``n_steps - 1`` intervals
    (interval ``i`` runs from step ``i`` to step ``i + 1``).
    ``seconds_per_step`` states their durations:

    * a scalar -- every interval lasts that many seconds, and every
      interval counts as SYNTHETIC (the tool fabricated the number);
    * a sequence -- interval ``i`` lasts ``seconds_per_step[i]``; all
      stated, none synthetic (at least ``n_steps - 1`` entries; extras
      are ignored);
    * a mapping ``{interval: seconds}`` -- stated where present; gaps
      synthesize the 10-second default and count as synthetic.

    Returns ``(seconds, stated)``: ``seconds[k]`` is the second at step
    ``k`` (``seconds[0] == 0.0``, one entry per step), and ``stated[i]``
    tells whether interval ``i``'s duration was stated by the caller.
    Every duration must be positive; a mapping key outside the interval
    range is refused loudly.
    """

    count = max(int(n_steps), 1)
    intervals = count - 1
    durations: list[float]
    stated: list[bool]
    if isinstance(seconds_per_step, bool):
        raise ValueError(f"seconds_per_step must be a number (got {seconds_per_step!r})")
    if isinstance(seconds_per_step, (int, float)):
        scale = float(seconds_per_step)
        if scale <= 0:
            raise ValueError(f"seconds_per_step must be positive (got {seconds_per_step!r})")
        durations = [scale] * intervals
        stated = [False] * intervals
    elif isinstance(seconds_per_step, Mapping):
        stray = sorted(key for key in seconds_per_step if not 0 <= int(key) < intervals)
        if stray:
            raise ValueError(
                f"seconds_per_step mapping keys must be interval indices in "
                f"[0, {intervals}) (got {stray})"
            )
        durations, stated = [], []
        for index in range(intervals):
            if index in seconds_per_step:
                durations.append(float(seconds_per_step[index]))
                stated.append(True)
            else:
                durations.append(_DEFAULT_STEP_S)
                stated.append(False)
    else:
        entries = [float(duration) for duration in seconds_per_step]
        if len(entries) < intervals:
            raise ValueError(
                f"seconds_per_step needs at least {intervals} durations, one per "
                f"step interval (got {len(entries)})"
            )
        durations = entries[:intervals]
        stated = [True] * intervals
    bad = [d for d in durations if not d > 0]
    if bad:
        raise ValueError(f"step durations must be positive (got {bad[0]!r})")
    seconds = [0.0]
    for duration in durations:
        seconds.append(seconds[-1] + duration)
    return seconds, stated


def _axis_seconds(seconds: list[float], k: float) -> float:
    """Seconds at fractional step ``k`` (linear inside each interval)."""

    last = len(seconds) - 1
    if k <= 0 or last == 0:
        return seconds[0]
    if k >= last:
        return seconds[-1]
    index = int(k)
    return seconds[index] + (k - index) * (seconds[index + 1] - seconds[index])


def _seconds_axis(seconds: list[float], s: float) -> float:
    """Fractional step at second ``s`` (the inverse of _axis_seconds)."""

    last = len(seconds) - 1
    if s <= 0 or last == 0:
        return 0.0
    if s >= seconds[-1]:
        return float(last)
    index = bisect_right(seconds, s) - 1
    return index + (s - seconds[index]) / (seconds[index + 1] - seconds[index])


# ---------------------------------------------------------------------------
# the clock
# ---------------------------------------------------------------------------


class Clock:
    """The shared playhead for one linked group of views.

    ``t`` is the playhead in axis units (sim seconds, or the step index
    when ``step_mode``), ``playing`` says someone is animating, ``rate``
    is axis units per wall second (1.0 = real time; negative plays
    backwards, as Cesium's shuttle ring does), and ``span`` is the
    ``(t0, t1)`` window seeks clamp into.  The clock owns no wall-clock
    timer: views animate, the clock holds state and fans it out through
    plain callbacks, so the core package stays dependency-free.

    The no-echo discipline is the selection seam's, restated for
    floats: a :meth:`seek` within ``1e-3`` of the current ``t`` does
    not fan out, ``playing``/``rate`` coalesce on equality, and every
    subscriber applies the same rule before writing back, so each write
    settles at its first fixpoint.  Linking is explicit and scoped
    (:func:`link_time`); two dashboards in one notebook keep two
    clocks.
    """

    def __init__(
        self,
        span: tuple[float, float] = (0.0, 0.0),
        *,
        step_mode: bool = False,
        rate: float = 1.0,
        t: float | None = None,
    ) -> None:
        t0, t1 = float(span[0]), float(span[1])
        if t1 < t0:
            raise ValueError(f"span must be ordered (got {span!r})")
        self._span = (t0, t1)
        self._step_mode = bool(step_mode)
        self._t = t0 if t is None else min(max(float(t), t0), t1)
        self._playing = False
        self._rate = self._checked_rate(rate)
        self._observers: list[Callable[[dict[str, Any]], None]] = []

    @staticmethod
    def _checked_rate(rate: float) -> float:
        value = float(rate)
        if not math.isfinite(value) or value == 0.0:
            raise ValueError(f"rate must be a nonzero finite number (got {rate!r})")
        return value

    @property
    def span(self) -> tuple[float, float]:
        """The ``(t0, t1)`` window; seeks clamp into it."""

        return self._span

    @property
    def step_mode(self) -> bool:
        """True when the axis is a step index, not seconds."""

        return self._step_mode

    @property
    def t(self) -> float:
        """The playhead, in axis units.  Assigning delegates to seek."""

        return self._t

    @t.setter
    def t(self, value: float) -> None:
        self.seek(value)

    @property
    def playing(self) -> bool:
        """True while some view animates.  Assigning plays or pauses."""

        return self._playing

    @playing.setter
    def playing(self, value: bool) -> None:
        if value:
            self.play()
        else:
            self.pause()

    @property
    def rate(self) -> float:
        """Axis units per wall second.  Assigning delegates to set_rate."""

        return self._rate

    @rate.setter
    def rate(self, value: float) -> None:
        self.set_rate(value)

    def seek(self, t: float) -> None:
        """Move the playhead: clamp into the span, coalesce, fan out."""

        t0, t1 = self._span
        value = min(max(float(t), t0), t1)
        if abs(value - self._t) <= _TOLERANCE:
            return
        old, self._t = self._t, value
        self._notify("t", old, value)

    def play(self) -> None:
        """Mark the group playing (idempotent; fans out on the flip)."""

        if self._playing:
            return
        self._playing = True
        self._notify("playing", False, True)

    def pause(self) -> None:
        """Mark the group paused (idempotent; fans out on the flip)."""

        if not self._playing:
            return
        self._playing = False
        self._notify("playing", True, False)

    def set_rate(self, rate: float) -> None:
        """Change the playback rate (coalesces equal values)."""

        value = self._checked_rate(rate)
        if math.isclose(value, self._rate, rel_tol=1e-9, abs_tol=1e-12):
            return
        old, self._rate = self._rate, value
        self._notify("rate", old, value)

    def observe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Subscribe to changes; returns the matching unobserve.

        ``callback`` receives a traitlets-shaped change dict:
        ``{"name", "old", "new", "owner"}`` with ``name`` one of
        ``"t"``, ``"playing"``, ``"rate"``.
        """

        self._observers.append(callback)

        def unobserve() -> None:
            try:
                self._observers.remove(callback)
            except ValueError:
                pass

        return unobserve

    def _notify(self, name: str, old: Any, new: Any) -> None:
        for callback in list(self._observers):
            callback({"name": name, "old": old, "new": new, "owner": self})


# ---------------------------------------------------------------------------
# the timebase
# ---------------------------------------------------------------------------


@dataclass
class Timebase:
    """One recording, many views: a trace plus its optional mission
    binding, aligned on one axis.

    ``timeline`` is the recorded truth (:mod:`longeron.replay`);
    ``track`` is the optional globe binding, built FROM that timeline
    (:func:`longeron.analysis.mission3d.track_from_timeline`), so the
    two views replay one execution.  The shared axis is the timeline's
    own: sim seconds for a timed trace (track seconds are then the same
    numbers, the 1:1 mapping the design verified), or the step index in
    step mode.

    Step-only traces have no time axis, so a step-mode timebase refuses
    a ``track`` unless ``seconds_per_step`` states one (a scalar, or a
    per-step sequence/mapping -- see :func:`step_seconds`); the same
    value must then have built the track.  Stated durations count as
    first-class; only the synthesized gaps show up in
    :meth:`synthetic_intervals`, which is what the scrubber labels.
    """

    timeline: Timeline
    track: MissionTrack | None = None
    seconds_per_step: float | Sequence[float] | Mapping[int, float] | None = None
    #: cumulative seconds at each step index (step mode with a stated axis)
    _seconds: list[float] | None = field(init=False, default=None, repr=False)
    #: per-interval flags: True where the duration was stated by the caller
    _stated: list[bool] | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.timeline.step_mode:
            if self.seconds_per_step is not None:
                raise ValueError(
                    "a timed timeline already has a seconds axis; seconds_per_step "
                    "applies to step-mode recordings only"
                )
            return
        if self.seconds_per_step is None:
            if self.track is not None:
                raise ValueError(
                    "a step-only trace has no time axis: refusing the globe binding. "
                    "Pass seconds_per_step (a scalar, or a per-step sequence/mapping) "
                    "to opt in; the scrubber labels the synthetic segments."
                )
            return
        self._seconds, self._stated = step_seconds(self.timeline.n_steps, self.seconds_per_step)

    @property
    def step_mode(self) -> bool:
        """True when the shared axis is the step index."""

        return self.timeline.step_mode

    @property
    def span(self) -> tuple[float, float]:
        """The shared axis window: ``(t_start, t_end)``, or
        ``(0, n_steps - 1)`` in step mode."""

        if self.step_mode:
            return (0.0, float(max(self.timeline.n_steps - 1, 0)))
        return (self.timeline.t_start, self.timeline.t_end)

    def seconds_at(self, t: float) -> float:
        """Track seconds at axis position ``t`` (identity when timed)."""

        if not self.step_mode:
            return float(t)
        if self._seconds is None:
            raise ValueError("a step-only timebase has no seconds axis (pass seconds_per_step)")
        return _axis_seconds(self._seconds, float(t))

    def axis_at(self, s: float) -> float:
        """Axis position at track second ``s`` (the seconds_at inverse)."""

        if not self.step_mode:
            return float(s)
        if self._seconds is None:
            raise ValueError("a step-only timebase has no seconds axis (pass seconds_per_step)")
        return _seconds_axis(self._seconds, float(s))

    def events_at(self, t0: float, t1: float) -> list[FiredTransition]:
        """The fired transitions inside ``[t0, t1]`` (axis units, closed)."""

        lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
        return [fired for fired in self.timeline.fired if lo <= fired.t <= hi]

    def env_at(self, t: float) -> dict[str, Any]:
        """The telemetry row at ``t``: the last scalar-env snapshot at or
        before it (step semantics, like the tracks); ``{}`` before the
        first."""

        rows = self.timeline.env_steps
        index = bisect_right([key for key, _values in rows], float(t)) - 1
        return dict(rows[index][1]) if index >= 0 else {}

    def phase_at(self, t: float) -> tuple[str, str] | None:
        """The ``(phase, qname)`` of the track segment under ``t``
        (axis units); ``None`` without a track or outside every
        segment.  The final segment includes its end instant."""

        if self.track is None or not self.track.phases:
            return None
        s = self.seconds_at(t)
        for p0, p1, phase, qname in self.track.phases:
            if p0 <= s < p1:
                return (phase, qname)
        last = self.track.phases[-1]
        if s == last[1]:
            return (last[2], last[3])
        return None

    def synthetic_intervals(self) -> list[tuple[float, float]]:
        """The axis intervals whose seconds were synthesized (merged
        runs of unstated step durations); ``[]`` for timed traces and
        for step-only timebases that state no seconds axis at all."""

        if self._stated is None:
            return []
        merged: list[tuple[float, float]] = []
        start: float | None = None
        for index, stated in enumerate(self._stated):
            if not stated and start is None:
                start = float(index)
            elif stated and start is not None:
                merged.append((start, float(index)))
                start = None
        if start is not None:
            merged.append((start, float(len(self._stated))))
        return merged


# ---------------------------------------------------------------------------
# the wiring: link_time
# ---------------------------------------------------------------------------


class _TimeLink:
    """One view's attachment to a clock (disposable, idempotent).

    A view holds ONE time link: attaching it again unbinds the previous
    link first, mirroring the ``bind_config_view`` handle pattern.  The
    adapter observes the view's ``time`` trait into :meth:`Clock.seek`
    and fans clock changes back onto the trait, both sides under the
    coalescing tolerance; views that also carry ``playing``/``rate``
    traits (the scrubber, the mission viewer's Cesium bridge) get those
    wired the same way.

    Views that opt into the loss-tolerance seam (the house widgets; see
    :mod:`longeron.widgets._seam`) additionally get generation-stamped
    idempotent full-state pushes, stale-report rejection with full
    re-pushes, and resync answers -- dropped comm messages heal, and
    the clock (kernel truth) cannot be re-seeked by a report that
    predates its latest push.  Foreign views keep the plain transport.
    """

    def __init__(
        self,
        clock: Clock,
        view: Any,
        seconds_per_step: float | Sequence[float] | Mapping[int, float] | None,
    ) -> None:
        if not (hasattr(view, "has_trait") and view.has_trait("time")):
            raise TypeError(
                f"link_time needs views with a 'time' trait (got {type(view).__name__})"
            )
        previous = getattr(view, "_lgn_time_link", None)
        if isinstance(previous, _TimeLink):
            previous.unbind()
        self._clock = clock
        self._view = view
        self._active = True
        # the axis mapping: identity for every view, except the globe
        # under a step-mode clock -- steps are not seconds, so the
        # binding is refused unless seconds_per_step opts in
        self._seconds: list[float] | None = None
        self._scale = 1.0  # mean axis -> view scale (sizes rate + drift)
        if clock.step_mode and view.has_trait("czml_json"):
            if seconds_per_step is None:
                raise ValueError(
                    "a step-only trace has no time axis: refusing the globe binding. "
                    "Pass link_time(..., seconds_per_step=...) to opt in; the "
                    "scrubber labels the synthetic segments."
                )
            n_steps = round(clock.span[1] - clock.span[0]) + 1
            self._seconds, _stated = step_seconds(n_steps, seconds_per_step)
            steps = clock.span[1] - clock.span[0]
            self._scale = self._seconds[-1] / steps if steps > 0 else _DEFAULT_STEP_S
        view._lgn_time_link = self
        self._wire_playing = bool(view.has_trait("playing"))
        self._wire_rate = bool(view.has_trait("rate"))
        # the loss-tolerance seam (widgets/_seam.py): views carrying the
        # stamp traits get generation-stamped idempotent pushes, stale-
        # report rejection, and resync answers; foreign views keep the
        # plain trait transport unchanged
        self._reconciles = bool(view.has_trait("_seam_gen")) and isinstance(view, SeamHost)
        self._seam_keys = (
            "_seam_gen",
            "time",
            *(("playing",) if self._wire_playing else ()),
            *(("rate",) if self._wire_rate else ()),
        )
        self._suppress = False  # an accepted report needs no echo push
        self._healing = False  # a re-push must not observe itself
        self._unobserve_clock = clock.observe(self._on_clock)
        view.observe(self._on_view_time, names="time")
        if self._wire_playing:
            view.observe(self._on_view_playing, names="playing")
        if self._wire_rate:
            view.observe(self._on_view_rate, names="rate")
        if self._reconciles:
            view.on_msg(self._on_view_msg)
        # first fan-out: the clock is the state, the view follows it now
        # (swapping a view preserves the playhead, per the contract)
        if self._reconciles:
            self._push()
        else:
            self._write_time(clock.t)
            if self._wire_playing:
                view.playing = clock.playing
            if self._wire_rate:
                view.rate = clock.rate * self._scale
        if view.has_trait("drift_s"):
            # the bounded-drift reconciliation tolerance, in view units
            view.drift_s = _DRIFT * self._scale

    # -- the axis mapping --------------------------------------------------

    def _to_view(self, t: float) -> float:
        if self._seconds is None:
            return float(t)
        return _axis_seconds(self._seconds, float(t))

    def _to_clock(self, value: float) -> float:
        if self._seconds is None:
            return float(value)
        return _seconds_axis(self._seconds, float(value))

    def _write_time(self, t: float) -> None:
        mapped = self._to_view(t)
        if abs(float(self._view.time) - mapped) > 1e-9:
            self._view.time = mapped

    # -- the loss-tolerance guard (see widgets/_seam.py) --------------------

    def _is_report(self, name: str) -> bool:
        """True when ``name``'s change arrived FROM the front-end."""

        return name in getattr(self._view, "_lgn_from_frontend", frozenset())

    def _is_stale(self) -> bool:
        """True when the front-end's report predates the latest push.

        Only MACHINE reports (playback integration) are guarded: a
        report carrying a bumped ``_seam_intent`` in the same message
        is a user action -- new truth, not an echo of old state -- and
        outranks any push it may have raced.
        """

        view = self._view
        if not self._reconciles or "_seam_intent" in view._lgn_from_frontend:
            return False
        return int(view._seam_ack) != int(view._seam_gen)

    # -- view -> clock -----------------------------------------------------

    def _on_view_time(self, change: Any) -> None:
        if not self._active or self._healing:
            return
        report = self._is_report("time")
        if report and self._is_stale():
            self._repush()  # the report predates the seek: truth wins
            return
        self._suppress = report
        try:
            self._clock.seek(self._to_clock(change["new"]))
        finally:
            self._suppress = False

    def _on_view_playing(self, change: Any) -> None:
        if not self._active or self._healing:
            return
        report = self._is_report("playing")
        if report and self._is_stale():
            self._repush()
            return
        self._suppress = report
        try:
            if change["new"]:
                self._clock.play()
            else:
                self._clock.pause()
        finally:
            self._suppress = False

    def _on_view_rate(self, change: Any) -> None:
        if not self._active or self._healing:
            return
        rate = float(change["new"])
        if rate == 0.0:
            return  # the mission viewer's 0 means "no stated rate"
        report = self._is_report("rate")
        if report and self._is_stale():
            self._repush()
            return
        self._suppress = report
        try:
            self._clock.set_rate(rate / self._scale)
        finally:
            self._suppress = False

    def _on_view_msg(self, _view: Any, content: Any, _buffers: Any) -> None:
        """The front-end's resync request: answer with full truth."""

        if self._active and isinstance(content, dict) and content.get("lgn_seam") == "resync":
            self._repush()

    # -- clock -> view -----------------------------------------------------

    def _on_clock(self, change: dict[str, Any]) -> None:
        if not self._active or self._suppress:
            return
        if self._reconciles:
            self._push()
            return
        name = change["name"]
        if name == "t":
            self._write_time(change["new"])
        elif name == "playing" and self._wire_playing:
            self._view.playing = change["new"]
        elif name == "rate" and self._wire_rate:
            self._view.rate = change["new"] * self._scale

    def _push(self) -> None:
        """One stamped, idempotent push of the full clock state.

        The stamp always changes, so a message always goes out even
        when every mirrored value coalesces -- any NEXT push heals the
        LAST dropped one.  ``hold_sync`` folds the stamp and the
        mirrors into one comm message.
        """

        view = self._view
        with view.hold_sync():
            view._seam_gen = int(view._seam_gen) + 1
            self._write_time(self._clock.t)
            if self._wire_playing and bool(view.playing) is not self._clock.playing:
                view.playing = self._clock.playing
            if self._wire_rate:
                rate = self._clock.rate * self._scale
                if abs(float(view.rate) - rate) > 1e-12:
                    view.rate = rate

    def _repush(self) -> None:
        """Reassert clock truth unconditionally.

        A stale report was rejected (its arrival already poisoned the
        kernel-side mirrors, so realign them first), or the front-end
        asked for a resync.  ``send_state`` re-sends UNCHANGED values
        too -- the healing property plain trait sync lacks.
        """

        self._healing = True
        try:
            self._push()
        finally:
            self._healing = False
        self._view.send_state(self._seam_keys)

    def unbind(self) -> None:
        """Detach the adapter (idempotent); the view keeps its playhead."""

        if not self._active:
            return
        self._active = False
        self._unobserve_clock()
        self._view.unobserve(self._on_view_time, names="time")
        if self._wire_playing:
            self._view.unobserve(self._on_view_playing, names="playing")
        if self._wire_rate:
            self._view.unobserve(self._on_view_rate, names="rate")
        if self._reconciles:
            self._view.on_msg(self._on_view_msg, remove=True)
        if getattr(self._view, "_lgn_time_link", None) is self:
            self._view._lgn_time_link = None


def link_time(
    clock: Clock,
    *views: Any,
    seconds_per_step: float | Sequence[float] | Mapping[int, float] | None = None,
) -> Callable[[], None]:
    """Wire time-aware views to one clock (the temporal ``link_selection``).

    Each ``view`` is any widget with a ``time`` trait on the clock's
    axis: the replay player, the mission viewer, the scrubber, or a
    future subscriber.  The adapter observes the trait into
    :meth:`Clock.seek` and fans clock changes back, both sides under
    the ``1e-3`` coalescing tolerance, so scrubbing one view scrubs
    them all and no write echoes.  Views that also carry ``playing``
    and ``rate`` traits (the scrubber; the mission viewer's Cesium
    bridge) get those wired the same way, and the clock's current
    state fans out to every view at link time.

    The one non-identity mapping is the globe under a step-mode clock:
    steps are not seconds, so the binding is REFUSED unless
    ``seconds_per_step`` opts in (a scalar, or a per-step
    sequence/mapping matching the track's own build -- see
    :func:`step_seconds`); the adapter then maps step positions through
    the stated durations, scales ``rate`` to track seconds per wall
    second, and sizes the viewer's drift tolerance to match.

    A view holds ONE time link; linking it again replaces the previous
    adapter.  Returns an idempotent ``unlink()`` that detaches every
    adapter, mirroring ``link_selection``.
    """

    links = [_TimeLink(clock, view, seconds_per_step) for view in views]

    def unlink() -> None:
        for link in links:
            link.unbind()

    return unlink


# ---------------------------------------------------------------------------
# the scrubber widget (anywidget front-end, vanilla JS, no bundler)
# ---------------------------------------------------------------------------

# Conventions per replay/mission3d: the kernel bakes the whole payload
# (spec_json) and the front-end only plays it.  The playback loop is the
# replay widget's requestAnimationFrame pattern with the same ~4 Hz trait
# throttle; the drift-tolerant `change:time` handler implements the
# non-fighting rule (see the module docstring).  Reports ride the
# loss-tolerance seam client (widgets/_seam.py).
_SCRUBBER_ESM = (
    SEAM_ESM
    + r"""
function render({ model, el }) {
  const seam = lgnSeam(model);
  el.classList.add("lgw", "lgn-scrub");
  el.innerHTML = "";

  const button = document.createElement("button");
  button.className = "lgn-scrub-btn";
  button.title = "play / pause";
  const select = document.createElement("select");
  select.className = "lgn-scrub-rate";
  select.title = "rate (axis units per second)";
  const wrap = document.createElement("div");
  wrap.className = "lgn-scrub-track";
  const band = document.createElement("div");
  band.className = "lgn-scrub-band";
  const ticks = document.createElement("div");
  ticks.className = "lgn-scrub-ticks";
  const scrub = document.createElement("input");
  scrub.type = "range";
  scrub.className = "lgw-slider";
  wrap.append(band, ticks, scrub);
  const readout = document.createElement("span");
  readout.className = "lgn-scrub-clock";
  const bar = document.createElement("div");
  bar.className = "lgn-scrub-bar";
  bar.append(button, select, wrap, readout);
  const env = document.createElement("div");
  env.className = "lgn-scrub-env";
  el.append(bar, env);

  const RATES = [0.25, 0.5, 1, 2, 4, 8, 16, 32];
  function rateOptions(current) {
    select.innerHTML = "";
    const values = RATES.includes(current) ? RATES
      : [...RATES, current].sort((a, b) => a - b);
    for (const value of values) {
      const option = document.createElement("option");
      option.value = String(value);
      option.textContent = value + "\u00d7";
      if (value === current) option.selected = true;
      select.appendChild(option);
    }
  }

  // phase band tints: one restrained accent family (motion phases lean
  // on the accent, rest phases on the ink), per the chrome's strategy
  const PHASE_TINT = {
    route: "color-mix(in srgb, var(--lgw-accent) 30%, transparent)",
    takeoff: "color-mix(in srgb, var(--lgw-accent) 15%, transparent)",
    landing: "color-mix(in srgb, var(--lgw-accent) 15%, transparent)",
    ground: "color-mix(in srgb, var(--lgw-ink) 10%, transparent)",
    hold: "color-mix(in srgb, var(--lgw-ink) 5%, transparent)",
  };

  let spec = { span: [0, 0], step_mode: false, ticks: [], phases: [],
               env_steps: [], synthetic: [], seconds: null };
  let t = 0;
  let playing = false;
  let rate = model.get("rate") || 1;
  let raf = 0;
  let last = 0;
  let lastSync = 0;

  const span = () => spec.span[1] - spec.span[0];
  const frac = (x) => (span() > 0 ? (x - spec.span[0]) / span() : 0);

  function secondsAt(x) {
    const seconds = spec.seconds;
    const lastIndex = seconds.length - 1;
    if (x <= 0 || lastIndex === 0) return seconds[0];
    if (x >= lastIndex) return seconds[lastIndex];
    const index = Math.floor(x);
    return seconds[index] + (x - index) * (seconds[index + 1] - seconds[index]);
  }

  function syntheticAt(x) {
    for (const [a, b] of spec.synthetic) {
      if (x >= a && x <= b) return true;
    }
    return false;
  }

  function lastIndexAt(entries, x) {
    if (!entries.length || x < entries[0][0]) return -1;
    let lo = 0;
    let hi = entries.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (entries[mid][0] <= x) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  function clockText(x) {
    if (!spec.step_mode) {
      return x.toFixed(2) + " / " + spec.span[1].toFixed(2) + " s";
    }
    const step = Math.round(x);
    let text = "step " + step + " / " + Math.round(spec.span[1]);
    if (spec.seconds) {
      if (syntheticAt(x)) {
        // an honest label: these seconds are fabricated, not recorded
        const index = Math.min(Math.floor(x), spec.seconds.length - 2);
        const per = spec.seconds[index + 1] - spec.seconds[index];
        text += " (\u00d7" + (per % 1 ? per.toFixed(1) : per) + " s)";
      } else {
        text += " \u00b7 " + secondsAt(x).toFixed(1) + " s";
      }
    }
    return text;
  }

  function draw() {
    scrub.value = String(t);
    scrub.style.setProperty("--p", String(Math.min(Math.max(frac(t), 0), 1)));
    readout.textContent = clockText(t);
    if (spec.env_steps.length) {
      const index = lastIndexAt(spec.env_steps, t);
      env.textContent = index < 0 ? ""
        : Object.entries(spec.env_steps[index][1])
            .map(([name, value]) => name + " = " + value)
            .join("   ");
    }
  }

  function syncTime(force) {
    const now = performance.now();
    if (!force && now - lastSync < 250) return;  // ~4 Hz, like the peers
    lastSync = now;
    seam.report({ time: t });
  }

  function setPlaying(value, write) {
    if (playing !== value) {
      playing = value;
      if (value) {
        last = performance.now();
        raf = requestAnimationFrame(tick);
      } else {
        cancelAnimationFrame(raf);
      }
    }
    button.textContent = playing ? "\u275a\u275a" : "\u25b6";
    if (write) {
      seam.report({ playing });
    }
  }

  function tick(now) {
    const dt = (now - last) / 1000;
    last = now;
    t += dt * rate;
    if (rate > 0 && t >= spec.span[1]) {
      t = spec.span[1];
      syncTime(true);  // the stopper owns the final t: write it first
      setPlaying(false, true);
    } else if (rate < 0 && t <= spec.span[0]) {
      t = spec.span[0];
      syncTime(true);
      setPlaying(false, true);
    } else {
      syncTime(false);
    }
    draw();
    if (playing) raf = requestAnimationFrame(tick);
  }

  button.addEventListener("click", () => {
    if (playing) {
      // the pauser owns the final t: one INTENT report carries the
      // settled time with the flip, so the pause cannot be split from
      // its playhead by a drop
      setPlaying(false, false);
      seam.intent({ time: t, playing: false });
    } else {
      if (span() <= 0) return;
      if (rate > 0 && t >= spec.span[1]) t = spec.span[0];
      setPlaying(true, false);
      seam.intent({ playing: true });
    }
  });
  scrub.addEventListener("input", () => {
    const fields = { time: parseFloat(scrub.value) };
    if (playing) {
      setPlaying(false, false);
      fields.playing = false;
    }
    t = fields.time;
    draw();
    seam.intent(fields);
  });
  select.addEventListener("change", () => {
    rate = parseFloat(select.value);
    seam.intent({ rate });
  });

  model.on("change:time", () => {
    const value = model.get("time");
    if (playing) {
      // bounded-drift reconciliation: while playing, peer integration
      // inside the tolerance is not a seek -- ignore it (non-fighting)
      const tolerance = 0.25 * Math.max(1, Math.abs(rate));
      if (Math.abs(value - t) <= tolerance) return;
    } else if (Math.abs(value - t) < 1e-9) {
      return;  // echo of our own write
    }
    t = Math.min(Math.max(value, spec.span[0]), spec.span[1]);
    draw();
  });
  model.on("change:playing", () => {
    const value = model.get("playing");
    setPlaying(value, false);
    if (!value) {
      // exact convergence on pause: adopt the settled clock t (the
      // pauser force-wrote it alongside the flip)
      const settled = model.get("time");
      if (Math.abs(settled - t) > 1e-9) {
        t = Math.min(Math.max(settled, spec.span[0]), spec.span[1]);
      }
      draw();
    }
  });
  model.on("change:rate", () => {
    rate = model.get("rate") || 1;
    rateOptions(rate);
  });

  function rebuild() {
    try { spec = JSON.parse(model.get("spec_json") || "{}"); }
    catch (err) { spec = { span: [0, 0] }; }
    spec.span = spec.span || [0, 0];
    spec.ticks = spec.ticks || [];
    spec.phases = spec.phases || [];
    spec.env_steps = spec.env_steps || [];
    spec.synthetic = spec.synthetic || [];
    scrub.min = String(spec.span[0]);
    scrub.max = String(spec.span[1]);
    scrub.step = span() > 0 ? String(span() / 500) : "1";
    // phase bands (mission binding) + synthetic stripes + event ticks
    band.innerHTML = "";
    for (const [a, b, phase, qname] of spec.phases) {
      const segment = document.createElement("div");
      segment.className = "lgn-scrub-phase";
      segment.style.left = (frac(a) * 100) + "%";
      segment.style.width = (Math.max(frac(b) - frac(a), 0) * 100) + "%";
      segment.style.background = PHASE_TINT[phase] || PHASE_TINT.hold;
      segment.title = phase + (qname ? " \u00b7 " + qname : "");
      band.appendChild(segment);
    }
    for (const [a, b] of spec.synthetic) {
      const stripe = document.createElement("div");
      stripe.className = "lgn-scrub-synthetic";
      stripe.style.left = (frac(a) * 100) + "%";
      stripe.style.width = (Math.max(frac(b) - frac(a), 0) * 100) + "%";
      stripe.title = "synthetic seconds (stated by the tool, not the model)";
      band.appendChild(stripe);
    }
    ticks.innerHTML = "";
    if (spec.ticks.length > 100) {
      // event density band instead of unreadable individual marks
      const density = document.createElement("div");
      density.className = "lgn-scrub-density";
      density.title = spec.ticks.length + " events";
      ticks.appendChild(density);
    } else {
      for (const record of spec.ticks) {
        const mark = document.createElement("div");
        mark.className = "lgn-scrub-tick";
        mark.style.left = (frac(record.t) * 100) + "%";
        mark.title = (record.label || "event") + " @ " + record.t;
        ticks.appendChild(mark);
      }
    }
    env.style.display = spec.env_steps.length ? "" : "none";
    t = Math.min(Math.max(model.get("time"), spec.span[0]), spec.span[1]);
    draw();
  }

  model.on("change:spec_json", rebuild);
  model.on("change:width_px", () => {
    el.style.maxWidth = model.get("width_px") + "px";
  });
  el.style.maxWidth = model.get("width_px") + "px";
  rateOptions(rate);
  setPlaying(model.get("playing"), false);
  rebuild();
}
export default { render };
"""
)

# The scrubber's own chrome rides the shared lgw tokens: neutral
# surface, the one JupyterLab accent, tabular numerals for the clock --
# strategy(restrained), cadence(restrained), per widgets/_chrome.py.
_SCRUBBER_CSS = (
    CONTROL_CSS
    + """
.lgn-scrub {
  font-family: var(--jp-ui-font-family, Helvetica, Arial, sans-serif);
  color: var(--lgw-ink);
}
.lgn-scrub-bar { display: flex; align-items: center; gap: 10px; }
.lgn-scrub-btn {
  appearance: none; -webkit-appearance: none; flex: none;
  border: 1px solid var(--lgw-line); border-radius: 6px;
  background: var(--lgw-bg); color: var(--lgw-ink);
  font-size: 12px; line-height: 1; padding: 6px 11px; cursor: pointer;
  transition: background 120ms var(--lgw-ease),
    border-color 120ms var(--lgw-ease);
}
.lgn-scrub-btn:hover {
  border-color: color-mix(in srgb, var(--lgw-ink) 35%, var(--lgw-line));
}
.lgn-scrub-btn:active {
  background: color-mix(in srgb, var(--lgw-ink) 8%, var(--lgw-bg));
}
.lgn-scrub-btn:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: 1px;
}
.lgn-scrub-rate {
  flex: none; border: 1px solid var(--lgw-line); border-radius: 6px;
  background: var(--lgw-bg); color: var(--lgw-ink);
  font-size: 11px; padding: 5px 6px; cursor: pointer;
}
.lgn-scrub-rate:focus-visible {
  outline: 2px solid var(--lgw-accent); outline-offset: 1px;
}
.lgn-scrub-track { position: relative; flex: 1; min-width: 120px; }
.lgn-scrub-track .lgw-slider {
  display: block; width: 100%; position: relative; z-index: 2;
  margin: 8px 0 10px;
}
.lgn-scrub-band {
  position: absolute; left: 0; right: 0; bottom: 2px; height: 5px;
  border-radius: 3px; overflow: hidden; z-index: 1;
  background: color-mix(in srgb, var(--lgw-ink) 4%, transparent);
}
.lgn-scrub-phase { position: absolute; top: 0; bottom: 0; }
.lgn-scrub-synthetic {
  position: absolute; top: 0; bottom: 0;
  background: repeating-linear-gradient(135deg,
    color-mix(in srgb, var(--lgw-ink) 25%, transparent) 0 2px,
    transparent 2px 5px);
}
.lgn-scrub-ticks {
  position: absolute; left: 0; right: 0; top: 1px; height: 7px;
  pointer-events: none; z-index: 1;
}
.lgn-scrub-tick {
  position: absolute; top: 0; bottom: 0; width: 2px;
  margin-left: -1px; border-radius: 1px;
  background: color-mix(in srgb, var(--lgw-accent) 75%, transparent);
  pointer-events: auto;
}
.lgn-scrub-density {
  position: absolute; left: 0; right: 0; top: 2px; height: 3px;
  border-radius: 2px;
  background: color-mix(in srgb, var(--lgw-accent) 45%, transparent);
  pointer-events: auto;
}
.lgn-scrub-clock {
  flex: none; font-size: 11px; color: var(--lgw-mute);
  font-variant-numeric: tabular-nums; white-space: nowrap;
  min-width: 11ch; text-align: right;
}
.lgn-scrub-env {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px; color: var(--lgw-mute); margin-top: 2px;
  font-variant-numeric: tabular-nums; white-space: pre-wrap;
  min-height: 14px;
}
"""
)

_SCRUBBER_CLS: type[anywidget.AnyWidget] | None = None


def _scrubber_class() -> type[anywidget.AnyWidget]:
    """Define TimeScrubber lazily -- anywidget is an optional extra."""

    global _SCRUBBER_CLS
    if _SCRUBBER_CLS is not None:
        return _SCRUBBER_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the time scrubber", "anywidget", "replay") from err

    class TimeScrubber(SeamHost, _anywidget.AnyWidget):
        """The transport bar for one linked clock group."""

        _esm = _SCRUBBER_ESM
        _css = _SCRUBBER_CSS
        #: the baked axis payload (span, ticks, phases, telemetry, the
        #: synthetic-segment labels); assign to swap recordings
        spec_json = traitlets.Unicode("").tag(sync=True)
        width_px = traitlets.Int(760).tag(sync=True)
        #: bidirectional playhead, in the timebase's axis units
        time = traitlets.Float(0.0).tag(sync=True)
        #: bidirectional transport state (the play/pause button)
        playing = traitlets.Bool(False).tag(sync=True)
        #: bidirectional playback rate, axis units per wall second
        rate = traitlets.Float(1.0).tag(sync=True)
        #: the loss-tolerance stamps (widgets/_seam.py): the kernel's
        #: push generation, the front-end's last-applied acknowledgement,
        #: and the front-end's user-action counter
        _seam_gen = traitlets.Int(0).tag(sync=True)
        _seam_ack = traitlets.Int(0).tag(sync=True)
        _seam_intent = traitlets.Int(0).tag(sync=True)

    _SCRUBBER_CLS = TimeScrubber
    return TimeScrubber


def _scrubber_spec(timebase: Timebase) -> dict[str, Any]:
    """The scrubber payload (times rounded to the JSON quantum)."""

    def q(value: float) -> float:
        return round(float(value), 3)

    t0, t1 = timebase.span
    spec: dict[str, Any] = {
        "span": [q(t0), q(t1)],
        "step_mode": timebase.step_mode,
        "ticks": [
            {"t": q(fired.t), "label": fired.event or ""} for fired in timebase.timeline.fired
        ],
        "env_steps": [
            [
                q(key),
                {
                    name: q(value) if isinstance(value, float) else value
                    for name, value in row.items()
                },
            ]
            for key, row in timebase.timeline.env_steps
        ],
        "phases": [],
        "synthetic": [[q(a), q(b)] for a, b in timebase.synthetic_intervals()],
        "seconds": None,
    }
    if timebase._seconds is not None:
        spec["seconds"] = [q(second) for second in timebase._seconds]
    if timebase.track is not None:
        spec["phases"] = [
            [q(timebase.axis_at(p0)), q(timebase.axis_at(p1)), phase, qname]
            for p0, p1, phase, qname in timebase.track.phases
        ]
    return spec


def time_scrubber(timebase: Timebase, *, width_px: int = 760) -> anywidget.AnyWidget:
    """The standalone transport bar for a recording.

    A play/pause button, a rate select, a slim slider over the
    timebase's span with tick marks at the recorded transition instants
    (a density band above ~100 events), the mission phase bands where a
    track binding exists, a readout clock, and the scalar-telemetry
    line that follows the playhead.  Step-mode recordings read
    ``step k / N``; where a seconds axis was stated per step the stated
    seconds show plainly and the synthesized segments carry an explicit
    ``(xN s)`` tag plus a striped band -- a fabricated second is always
    displayed as fabricated.

    The scrubber is one subscriber among equals: pass it to
    :func:`link_time` beside the replay player and the mission viewer.
    While playing it animates locally at the shared rate and syncs its
    ``time`` trait at ~4 Hz, exactly like its peers.

    Needs the ``replay`` extra (anywidget).
    """

    cls = _scrubber_class()
    return cls(
        spec_json=json.dumps(_scrubber_spec(timebase)),
        width_px=width_px,
        time=timebase.span[0],
    )
