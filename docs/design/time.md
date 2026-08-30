# The time seam: one clock across the views (design)

> **Status: adopted 2026-08-30.** Nothing below is implemented; this
> is the contract for the arc. Decisions: a dedicated dependency-free
> `Clock` object owns the state, with the scrubber one subscriber
> among equals (Q1); the Cesium bridge runs shared-rate local
> integration with bounded-drift reconciliation (~4 Hz) and exact
> convergence on pause (Q2); step-only traces refuse the globe by
> default -- `seconds_per_step` opts in, accepts a SCALAR or a
> PER-STEP sequence/mapping (steps take unequal durations), durations
> the model itself states (time triggers, occurrence durations) are
> used first-class and never counted as synthetic, and the scrubber
> labels only the synthetic segments (Q3); the trace-to-mission
> binding rides the existing seams now -- `model_waypoints` plus an
> epoch attribute typed `Time::Iso8601DateTime` -- with `MissionPhase`
> metadata arriving in phase 3 to retire the name heuristics (Q4);
> `Clock`, `link_time`, and the scrubber live in `longeron.widgets`,
> the Cesium bridge stays in `mission3d` (Q5); phase 1 lands after
> provenance layers 1-2 within 0.12, phase 2 immediately behind it,
> phase 3 rides the 0.13 geometry arc (Q6); the playhead does not
> join the selection seam in this design -- recorded as the natural
> follow-on once both seams are stable (Q7).

Goal: make time a shared, linkable state across every time-aware view.
The diagram replay player, the Cesium mission replay, and any future
time-aware view each keep a private clock today, and nothing links
them. The time seam gives them one clock, so scrubbing one view scrubs
them all. A state machine's transitions then fire in the diagram at
the same moments the craft moves on the globe.

The seam is the temporal analogue of the selection seam. The selection
seam made "what is selected" one state with many subscribers. The time
seam makes "when are we" the same kind of state. The design mirrors
the selection contract clause for clause, and it reuses the same
wiring discipline (kernel-side observers, first-fixpoint writes, an
`unlink()` disposer).

All empirical claims below were verified against longeron 0.10.0 at
commit `ad27a8b` (the DeepScout examples, the shipped stdlib, and the
live widget sources).

## The pattern to mirror: the selection seam

Tutorial 3 states the selection contract, and every linked surface
obeys it:

- Each surface exposes its selection as a widget trait.
- Selecting in one surface writes the same qualified name into the
  others.
- Each write settles at its first fixpoint, so no echo loops back.
- Switching the diagram kind preserves the selection.

The mechanics behind the contract are worth naming, because the time
seam copies them. There is no central hub. `link.link_selection`
composes existing per-view seams pairwise: the diagrams' `on_select`
callback, the 3D viewer's `highlight_json` and `picked_json` traits,
the scoreboard's `selected` trait. Echo suppression is equality
coalescing (a write of an equal value does not re-fire) plus explicit
reentrancy guards where two directions meet (the `syncing` flag in
`grand_dashboard`). The wiring runs kernel-side through traitlets
observers, so it works headless, and every link returns an `unlink()`
callable.

The temporal restatement of the contract:

- Each time-aware view exposes its playhead as a widget trait.
- Scrubbing one view writes the same instant into the others.
- Each write settles at its first fixpoint, so no echo loops back.
- Swapping a view (or its payload) preserves the playhead.

## What longeron has today

Three representations of one execution exist, each with its own clock
surface. Nothing links them at view time.

### The trace clock

`StateMachine` (interpreter.py) owns the simulation clock: `self.now`,
a float starting at `0.0`. Only two things advance it. A plain number
in the event feed calls `advance(duration)`, and `advance` fires due
time triggers (`accept after d` / `accept at t`) in deadline order,
computing each deadline as `node.entered_at + offset` (for `after`) or
`offset` (for `at`). The floats are unitless. Seconds are a
convention, stated in docstrings and honored by every consumer, never
stated in the model.

`replay.record_timeline` observes a simulation through the machine's
`on_step` hook and produces a `Timeline`:

- `t_start` / `t_end` -- the recorded span (always `t_start == 0.0`);
- `step_mode` -- `True` when `t_end == 0.0` (a pure event cascade with
  no clock advance); then every key below is a **step index**, not a
  time;
- `n_steps` -- the number of observed steps;
- `tracks` -- per-state keyframes `{qname: [(t, active)]}`, recorded
  on change only;
- `fired` -- `FiredTransition(t, source, target, event)` instants;
- `env_steps` -- per-step scalar env snapshots `[(t, {name: value})]`
  (the telemetry: `SortieStates.battery` lands here);
- `parents` -- the composite-state relation the front-end tints with.

`record_action_timeline` produces the same shape for action
executions, always in step mode. `Timeline.to_json` rounds every key
to 3 decimals.

`replay_widget` bakes the state (or action) diagram to SVG and
animates the timeline over it. Its widget traits: `svg`,
`timeline_json`, `width_px`, and `time` -- a **bidirectional
playhead** (sim time, or step index in step mode). The front-end
writes `time` at ~4 Hz while playing (a 250 ms throttle). A
kernel-side write seeks the playhead, and it **stops playback**
first. The front-end ignores an echo of its own write (`|delta| <
1e-9`). Playback is a `requestAnimationFrame` loop; the speed select
multiplies wall time (1x = 1 step/s in step mode).

### The mission clock

`analysis.mission3d` synthesizes a `MissionTrack` from the model:

- `epoch` -- a `datetime`; the default is the fixed instant
  2026-01-01T12:00:00Z, so the CZML is deterministic;
- `samples` -- `(t, lat, lon, alt)` keyframes, `t` in **seconds past
  `epoch`**;
- `waypoints` -- the planned route;
- `phases` -- motion segments `(t0, t1, phase, qname)`, where `qname`
  is the instance-qualified leaf state that drove the segment;
- `duration` -- the last phase end.

`from_replay` builds the track from a state-machine execution: it
calls `record_timeline` itself, classifies each leaf state's
activation interval into a motion phase by **name substrings**
(`_PHASE_RULES`, overridable per state name via `phases=`), and maps
route-phase intervals onto the waypoint polyline proportionally.
Timed timelines map onto track seconds **1:1** (scale 1.0). Step-mode
timelines scale by `seconds_per_step` (default 10.0).

`MissionTrack.to_czml` bakes a CZML document whose first packet is the
clock: `interval` (epoch to epoch+duration), `currentTime`,
`multiplier = max(1, round(duration / 40.0))` (playback takes ~40 s of
wall clock), `range: CLAMPED`, `step: SYSTEM_CLOCK_MULTIPLIER`.
Cesium's own timeline bar and animation dial are the playback UI.

`mission_viewer`'s widget traits: `czml_json`, `label`, `height_px`,
`ion_token`, `imagery`, `picked_json` (the pick seam, shared with
`viewer3d`), and `time` -- a **bidirectional playhead in seconds past
the track epoch**. The front-end converts with
`JulianDate.secondsDifference(currentTime, startTime)` and writes at
~4 Hz on the Cesium clock's `onTick`. A kernel-side write seeks
`viewer.clock.currentTime`; it does **not** pause a playing Cesium
clock. The echo tolerance is `1e-3`.

### The third representation: occurrences at M0

`m0.from_timeline` reads a `Timeline` as an interpretation: every
contiguous state activation becomes an occurrence `Individual`
(id `qname@k`) with `start` / `end` / `duration` slots, owned by a
root that spans the recording. Tutorial 5 teaches this as
traces-are-interpretations. The occurrence slots live on the same
axis as the timeline keys, so a playhead `t` selects "the occurrences
alive at `t`" by a slot comparison. The time seam does not touch M0,
but the shared axis is what makes that future query coherent.

### What links them today: nothing

The two widgets' `time` traits are private. `grand_dashboard` composes
the mission pane beside the diagram, scoreboard, and 3D panes and
wires every selection seam, but no time wiring exists (verified by
reading the wiring map: no observer touches either `time` trait).
Tutorial 7 aligns the two clocks **by hand**: it computes `cruise_s =
routeM / cruiseSpeedMps` from `mission_values` and authors that number
into the event feed, so the simulated flying interval matches the
physical route time. The correspondence lives in a notebook cell, not
in the model and not in any shared object. And the diagram replay and
the globe each record their **own** simulation: `replay_widget` calls
`record_timeline`, `from_replay` calls it again. The runs are
deterministic and therefore equal, but the invariant is fragile and
the work is duplicated.

## The standards boundary: what the language states about time

The seam's vocabulary should come from what the model already states,
per the model-derived posture. The inventory:

**Time triggers are grammar- and interpreter-real.** The grammar
carries `TriggerExpression` with `kind = ('at' | 'after' | 'when')`
(SysML.g4, under the spec's §8.2.2.17.4 send-and-accept rules), `model.py` carries `TriggerKind
= Literal["at", "after", "when"]`, and `StateMachine.advance`
implements the deadline semantics. This is the one place the language
already drives the trace clock.

**The `Time` package is vendored and resolves.** Longeron ships
`Time.sysml` in `src/longeron/_stdlib/quantities/`. Verified against
0.10.0 with the standard library attached: `Time::Clock` (a part def
whose `currentTime : TimeInstantValue` "advances monotonically over
its lifetime"), `Time::universalClock`, `Time::TimeOf` and
`Time::DurationOf` (calcs from an `Occurrence` and a `Clock` to an
instant and a duration), `Time::TimeScale` (an `IntervalScale` with a
`definitionalEpoch`), `Time::TimeInstantValue`, `Time::UTC` (the UTC
time scale, epoch 1958-01-01), and `Time::Iso8601DateTime` (a UTC
instant carried as an ISO 8601 string) all resolve. The package hands
the seam its vocabulary: a clock, an instant, a scale with an epoch.

**The kernel underneath dangles, as expected.** `Time` references
`Clocks::Clock` and `ISQSpaceTime::TimeValue`; both dangle (verified),
because the KerML kernel libraries are not vendored and `ISQSpaceTime`
awaits the units design's vendoring decision. The posture from the
units and geometry designs applies unchanged: resolution is good where
the library ships, and the seam never depends on the dangling parts.

**KerML's ordering substrate is parse-only.** Occurrences and
successions are the spec's ordering machinery. Longeron's `Occurrences`
shim declares the abstract `Occurrence`, `kerml.py` parses occurrence
declarations, and `model.py` carries `Succession` elements (the action
executor's `_succession_plan` already walks them). The seam's ordering
claims (events indexed by `t`, occurrences with lifetimes) are the
executable shadow of that substrate, not a new theory of time.

**What the model could state and does not.** No shipped model states
the unit of sim time (the floats are bare), no model states a mission
epoch, and no model states which motion phase a flight state drives
(the name heuristics in `_PHASE_RULES` guess it). Each gap has a
standard-vocabulary fix, taken up in the binding section below.

## The alignment verdict

| clock | axis | zero | advanced by | kernel surface |
| --- | --- | --- | --- | --- |
| trace | sim seconds (bare floats; step index in step mode) | machine start | numbers in the event feed; `after`/`at` deadlines | `StateMachine.now` -> `Timeline` keys -> `ReplayWidget.time` |
| mission | seconds past epoch | `MissionTrack.epoch` | sample interpolation | `MissionTrack.samples` -> `MissionViewer.time` |
| Cesium | `JulianDate` | CZML `interval` start | `multiplier` x wall clock | `viewer.clock`, converted back to seconds by the widget |

The verdict is friendlier than the three-clock table suggests. For a
timed trace, trace seconds and track seconds are **already the same
number**: `from_replay` copies timeline keys onto sample times at
scale 1.0. Verified end to end on the shipped flight demo: the
`FLIGHT_EVENTS` feed yields `t_end = 168.0`, the track's `duration =
168.0`, the phases carry the same instants
(`(2.0, 8.0, 'takeoff', ...)`, `(8.0, 158.0, 'route', ...)`), and the
CZML clock spans 12:00:00Z to 12:02:48Z. The Cesium clock is the track
clock plus an epoch, and `MissionViewer` already divides the epoch
back out: both widgets' `time` traits speak seconds on the same axis
today.

So the seam needs no conversion layer for the timed case. It needs
shared state, wiring, and honesty about three real gaps:

1. **Step-mode traces have no time axis.** The replay widget scrubs
   the step index; the globe fabricates seconds via
   `seconds_per_step`. One playhead cannot silently mean both.
2. **The sim clock's unit is a convention.** Nothing in the model says
   the bare floats are seconds. The units design keeps runtime values
   as floats, so this stays an annotation problem, not a runtime one.
3. **The trace-to-mission correspondence is authored by hand.** The
   event feed must be written so the flying interval matches the route
   time (tutorial 7's `cruise_s`), the waypoints arrive as a Python
   argument, and the phase mapping guesses from state names.

## The design

### The clock contract

One small kernel-side object holds the shared state. It has no
front-end, no timer, and no dependencies (plain Python callbacks, so
the core package stays dependency-free; the widgets already bring
traitlets for their own traits):

```python
class Clock:
    """The shared playhead for one linked group of views."""

    t: float                    # the playhead, in axis units
    playing: bool               # someone is animating
    rate: float                 # axis units per wall second (1.0 = real time)
    span: tuple[float, float]   # (t0, t1); seeks clamp into it
    step_mode: bool             # the axis is a step index

    def seek(self, t: float) -> None    # clamps, fans out, coalesces equals
    def play(self) -> None
    def pause(self) -> None
    def set_rate(self, rate: float) -> None
    def observe(self, callback) -> Callable[[], None]   # returns unobserve
```

The no-echo discipline is the selection seam's, restated for floats:
a `seek` to a value within the coalescing tolerance of the current
`t` does not fan out, every subscriber applies the same rule before
writing back, and each write therefore settles at its first fixpoint.
The tolerance is one JSON quantum (`1e-3`, matching
`Timeline.to_json`'s 3-decimal rounding and the mission widget's
existing echo guard).

The clock owns no wall-clock timer. Views animate (the replay widget's
`requestAnimationFrame` loop, Cesium's clock); the kernel holds state
and fans it out. While `playing`, every animating view integrates `t`
locally at the shared `rate` and reconciles against the clock at the
sync rate: a follower whose local time drifts past a bounded tolerance
snaps to the clock's `t`. On `pause`, every view converges exactly.
This is the non-fighting rule: no view is the permanent owner, drift
is bounded while playing, and equality holds at rest.

### The timebase: one recording, many views

One object aligns a trace with its optional mission binding, so every
view plays the **same recording**:

```python
@dataclass
class Timebase:
    timeline: Timeline               # the recorded truth (replay.py)
    track: MissionTrack | None       # the optional globe binding
    seconds_per_step: float | None   # step-mode globe binding only

    @property
    def span(self) -> tuple[float, float]   # the shared axis
    def events_at(self, t0, t1) -> list[FiredTransition]
    def env_at(self, t) -> dict[str, Any]   # the telemetry row
    def phase_at(self, t) -> tuple[str, str] | None
```

Building it requires one kernel refactor, small and honest:
`from_replay`'s track synthesis splits into a function over an
existing `Timeline` (`track_from_timeline(timeline, waypoints=...,
phases=..., ...)`), with `from_replay` kept as the recording
convenience. `replay_widget` and `mission_viewer` gain `timeline=` /
`track=` parameters so they accept the prebuilt recording instead of
re-simulating. The axis is the timeline's own axis: sim seconds, or
the step index in step mode. The track, when present, shares that axis
by construction (the 1:1 mapping the verdict established); its `epoch`
stays a track property that only the Cesium bridge touches.

### The wiring: `link_time`

The temporal `link_selection`:

```python
clock = Clock(span=timebase.span, step_mode=timebase.step_mode)
unlink = link_time(clock, player, mission, scrubber)
```

`link_time` attaches each view through a small adapter that knows the
view's trait name and its axis mapping:

| view | trait | mapping |
| --- | --- | --- |
| replay widget | `time` | identity (both modes) |
| mission viewer | `time` | identity (timed); `t * seconds_per_step` (step mode, explicit opt-in) |
| scrubber widget | `time` | identity |

Each adapter observes the view's trait and calls `clock.seek`, and
observes the clock and writes the trait, both sides applying the
coalescing tolerance. `link_time` returns an `unlink()` that detaches
every adapter, mirroring `link_selection`. The wiring is kernel-side
traitlets observers, so a headless test drives `clock.seek(42.0)` and
asserts both traits moved without a browser.

### The Cesium bridge

Cesium has its own clock, multiplier, timeline bar, and animation
dial, and users will keep using them. The bridge must be bidirectional
and non-fighting:

- **Kernel -> Cesium.** A clock seek writes the `time` trait; the
  existing front-end handler already sets `currentTime` and requests a
  render. `play`/`pause`/`set_rate` need three small front-end
  additions: set `viewer.clock.shouldAnimate` and
  `viewer.clock.multiplier = rate` from matching traits.
- **Cesium -> kernel.** The existing `onTick` reporter already writes
  `time` at ~4 Hz. Two additions: report `shouldAnimate` flips (the
  user pressed the Cesium dial) and `multiplier` changes, so the
  clock's `playing`/`rate` follow the dial.
- **Non-fighting.** While playing, Cesium integrates its own clock at
  `multiplier = rate` and the bridge only reconciles drift beyond the
  tolerance. The CZML document clock keeps its baked `multiplier` as
  the initial rate; the bridge overrides it at link time.

`rate` semantics are fixed across views: axis units per wall second.
For a timed trace `rate = 1.0` is real time, and the Cesium multiplier
equals `rate` exactly. The replay widget's speed select maps to the
same number (its step mode already defines 1x as one step per second).

### The scrubber widget

A small anywidget: a play/pause button, a rate select, a range slider
over the span, a readout clock, and tick marks at `timebase` event
instants (`fired` transitions), with the `env_at` telemetry row as an
optional readout line. It is the replay widget's control bar promoted
to a standalone surface, and it subscribes to the clock like any other
view. It renders alone under a dashboard, beside views that have no
chrome of their own (the state-highlight SVG, a future strip chart).

### Step-only traces: the honest degradation

A pure event cascade records in step mode, and steps are not seconds.
The degradation:

- The clock's axis **is the step index**: `span = (0, n_steps - 1)`,
  `step_mode = True`, and the scrubber labels the readout
  `step k / N` (the replay widget already does).
- The globe binding is **refused by default**: `link_time` raises when
  a step-mode timebase carries a track built without an explicit
  `seconds_per_step`. Passing one opts in; the adapter scales, and the
  scrubber labels the axis synthetic (`step k / N (x10 s)`).
- Everything else works unchanged: step-scrubbing the diagram, the
  telemetry readout, the tick marks.

This mirrors the house posture on honest reporting: a fabricated
second is displayed as fabricated, never silently blended with a real
one.

### The model-stated binding

Three Python-side conventions can migrate into the model, each on
standard or precedented vocabulary, none blocking the seam:

1. **Waypoints** already migrate today: `model_waypoints` reads
   `(lat, lon, alt[, t])` off a mission part's children through the
   interpreter. The seam's demos should use it instead of the
   `ATLANTA_LOOP` constant.
2. **The epoch** becomes a mission attribute typed
   `Time::Iso8601DateTime` (vendored, resolves). The track builder
   reads it when present and falls back to the deterministic default.
   The model then states when the sortie flies, in the standard's own
   ISO 8601 form.
3. **The phase mapping** becomes metadata: a `MissionPhase` metadata
   def in `analysis_conventions.sysml` (the established home for
   tool-facing conventions), applied per flight state
   (`@MissionPhase { phase = "route"; }`), read by the track builder
   before the name heuristics. The heuristics stay as the fallback,
   and the model-derived posture gains the truth where it matters.

The sim-time unit gap stays an annotation: the units design keeps
runtime values as floats, so the seam documents seconds-by-convention
and leaves bracket-checking of `after` arguments to the units arc.

### Subscriber inventory

| subscriber | seam surface | status |
| --- | --- | --- |
| diagram replay player | `ReplayWidget.time` | exists; wire only |
| state-diagram active-state highlight | the replay widget's SVG stage (tracks + parents drive it) | exists inside the player; no separate wiring needed |
| Cesium mission replay | `MissionViewer.time` + the bridge additions | trait exists; bridge is phase 2 |
| scrubber widget | its own `time` trait | new, phase 1 |
| telemetry strip chart | `env_steps` series + a cursor at `t` | future; the data already rides every `Timeline` |
| dashboard what-if over time | `grand_dashboard` gains a clock row | future |
| deployment-pose animation (geometry design, phase 3) | poses keyed by the same recorded timeline | future consumer, not a dependency |

## The flagship demo: the go-around sortie

The demo composes the seam's whole story from shipped parts, verified
against 0.10.0. `DeepScout::SortieStates` carries the go-around trap:
each entry to `airborne` burns 30% battery, and the go-around
transition re-enters `airborne` past the launch guard. With a timed
feed (`launch`, 45.0, `goAround`, 45.0, `goAround`, 45.0, `goAround`,
30.0, `land`, 5.0):

- the recorded battery telemetry steps 100 -> 70 -> 40 -> 10 -> -20,
  crossing the `SafeSortie` floor between t = 90 and t = 135;
- the track flies the loop for 165 s and lands (verified:
  `duration = 170.0`, phases `route` then `ground`);
- one clock scrubs all three surfaces: the state diagram pulses the
  `airborne -> airborne` edge at t = 45, 90, 135 while the craft loops
  on the globe, and the scrubber's telemetry readout shows the pack
  going negative.

Two honest details the demo teaches. First, the name heuristics do not
classify `airborne` (no `_PHASE_RULES` hint matches), so the demo
passes `phases={"airborne": "route"}` -- exactly the gap the
`MissionPhase` metadata closes. Second, the sequence exactly as
`verify.sequences` finds it (`launch, goAround, goAround, goAround`,
no clock advances) is a pure cascade: it records in step mode and
exercises the degradation path (step-scrubbing, no globe), which the
demo shows deliberately before the timed feed.

## Performance envelope

- **Sync rate.** Both existing widgets throttle trait writes to ~4 Hz
  (250 ms), and the seam keeps that number for reconciliation.
  Followers animate locally at frame rate, so the 4 Hz bound governs
  drift correction, not smoothness. The recommended drift tolerance is
  0.25 axis units.
- **Scrub granularity.** Timeline keys round to 3 decimals (1 ms), the
  replay slider steps at `span / 500`, and the clock's coalescing
  tolerance is `1e-3`. A 168 s mission scrubs at ~0.3 s per slider
  step.
- **Per-seek cost.** The replay draw is one binary search per state
  track plus CSS class toggles (the shipped machines have 4-6 tracks);
  the Cesium seek is one `requestRender` under `requestRenderMode`.
  Both are already interactive at slider rate.
- **Event density.** The shipped demos are tiny (3-4 fired records,
  4-5 env steps). The structures scale: keyframe lookup is
  logarithmic, fired-record matching precomputes once at render, and
  timelines with thousands of keyframes stay within the payload
  discipline `to_json`'s rounding established. The scrubber's tick
  marks should thin above ~100 events (draw a density band instead).
- **Headless truth.** The clock and `link_time` are pure kernel code.
  Tests drive `seek`/`play` and assert trait fan-out, mirroring how
  the selection seam is tested without a browser.

## What we deliberately do not build

- **No kernel-side timer.** The kernel never runs a wall-clock loop
  (no asyncio scheduler in a notebook kernel); views animate, the
  kernel holds state. A headless `play()` therefore moves `t` only
  when a front-end or a test advances it.
- **No implicit global clock.** Linking is explicit and scoped, like
  `link_selection`. Two dashboards in one notebook keep two clocks.
- **No cross-recording synchronization.** One clock serves one
  timebase. Comparing two sorties under one playhead is a later
  design, and it starts from this one's axis discipline.
- **No playhead persistence.** The view-persistence design's decision
  5 (selection is transient focus, not configuration) applies verbatim
  to the playhead.
- **No timezone machinery.** Epochs are UTC datetimes, as
  `mission3d._iso` already enforces.
- **No Cesium vendoring change.** The bridge is a few lines in the
  existing ESM; the CDN posture stands.

## Phasing

The finish-then-tag posture holds, and the seam yields to the standing
arcs: the curriculum owns the 0.12 headline, provenance layers 1-2
follow it, and geometry phase 1 opens 0.13.

- **Phase 1 -- the kernel and the player (the smallest honest
  slice).** `Timebase` + the `track_from_timeline` split, `Clock`,
  `link_time`, the scrubber widget, and `timeline=`/`track=`
  parameters on the two builders. Deliverable: the diagram replay and
  the scrubber scrub together, headless tests prove the fixpoint
  discipline, and the go-around demo runs in step mode.
- **Phase 2 -- the globe.** The Cesium bridge additions
  (`shouldAnimate`/`multiplier` traits, drift reconciliation), the
  timed go-around demo, a clock row in `grand_dashboard`, and the
  tutorial 9 epilogue that scrubs the diagram and the globe together.
- **Phase 3 -- the model binding and telemetry.** `MissionPhase`
  metadata, the model epoch, demos on `model_waypoints`, and the
  telemetry strip chart over `env_steps`. The geometry design's
  deployment animation arrives later as a consumer.

Each phase is independently shippable. Phase 1 alone delivers the
seam's core: one clock, many views, no echo.

## Open questions

1. **Clock ownership: a dedicated kernel object, or traits on a hub
   widget (the scrubber)?** A hub widget would conflate state with
   chrome and die with its DOM node. *Recommendation: the dedicated
   dependency-free `Clock`; the scrubber is one subscriber among
   equals.*
2. **Cesium bridge direction-of-truth: single driver, or bounded
   drift?** A single-driver rule (whoever pressed play owns `t`) is
   simpler but fights the Cesium dial, which users will press.
   *Recommendation: shared-rate local integration with bounded-drift
   reconciliation at ~4 Hz and exact convergence on pause.*
3. **Step-only traces: refuse the globe, or fabricate seconds?**
   *Recommendation: refuse by default; an explicit `seconds_per_step`
   opts in and the scrubber labels the axis synthetic. Never blend a
   fabricated second silently.*
4. **Where does the model state the trace-to-mission binding?**
   *Recommendation: waypoints via `model_waypoints` and an epoch
   attribute typed `Time::Iso8601DateTime` now (both on existing
   seams); `MissionPhase` metadata in `analysis_conventions.sysml` in
   phase 3 to retire the name heuristics.*
5. **Toolkit placement: where do `Clock`, `link_time`, and the
   scrubber live?** Candidates: grow `longeron.replay`, a sibling of
   `analysis/link.py`, or a new module. *Recommendation: a new
   `longeron.widgets` module for the three toolkit pieces (they serve
   core replay and analysis alike, and neither existing home covers
   both); the Cesium bridge stays in `mission3d` with its ESM.*
6. **Timing against the 0.12 arcs?** The seam is small but touches
   two widget front-ends. *Recommendation: phase 1 lands as a short
   arc after provenance layers 1-2 within 0.12, phase 2 immediately
   behind it; phase 3 rides the 0.13 geometry arc, whose deployment
   animation wants the clock anyway.*
7. **Does the playhead join the selection seam?** A playhead `t`
   selects the occurrence individuals alive at `t`, which could drive
   the inspector. *Recommendation: not in this design; record it as
   the natural follow-on once both seams are stable.*

## References

- Longeron surfaces: {mod}`longeron.replay` (`Timeline`,
  `record_timeline`, `replay_widget`),
  {mod}`longeron.analysis.mission3d` (`MissionTrack`, `from_replay`,
  `mission_viewer`), {mod}`longeron.interpreter` (`StateMachine.now`,
  `advance`, trigger deadlines), {mod}`longeron.m0` (`from_timeline`),
  {mod}`longeron.analysis.link` and
  {func}`longeron.diagrams.on_select` (the selection seam's
  mechanics), {mod}`longeron.analysis.grand` (the composed dashboard,
  `FLIGHT_EVENTS`, `ATLANTA_LOOP`).
- Vendored stdlib: `src/longeron/_stdlib/quantities/Time.sysml`
  (`Clock`, `TimeOf`, `TimeScale`, `UTC`, `Iso8601DateTime`),
  `KernelShim.sysml` (`Occurrences`), grammar rule
  `triggerExpression` (SysML.g4).
- OMG Systems Modeling Language (SysML) v2.0, Part 1: state machines
  and accept triggers (`at`/`after`/`when`), §9.8 Quantities and Units
  (the `Time` package, `TimeScale`, ISO 8601 representations).
- Sibling designs: [units](units.md) (floats-only invariant, vendoring
  posture), [geometry](geometry.md) (phasing precedent, the
  deployment-animation consumer), [provenance](provenance.md) (the
  0.12 arc it queues behind),
  [view persistence](view-persistence.md) (decision 5, transient
  focus), [the notebooks rebuild](notebooks.md) (tutorial ownership of
  the seams).
- Verified versions: longeron 0.10.0 at `ad27a8b`; CesiumJS 1.144.0
  (the pinned CDN release `mission3d` loads).
