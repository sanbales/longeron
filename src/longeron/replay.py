"""Replay state-machine and action executions over rendered diagrams.

:func:`record_timeline` drives a :class:`~longeron.interpreter.StateMachine`
through the same event protocol as ``Interpreter.simulate`` while observing
every step through the machine's ``on_step`` hook, producing a
:class:`Timeline`: per-state activation keyframes plus fired-transition
instants, addressed by model *qualified names* (the same ``::`` ids the
diagrams and headless SVG use).  :func:`record_action_timeline` does the
same for action executions via the executor's step observer: the active
node is the currently-executing named action step, fired records are the
traversed successions, and the axis is always the step index.

:func:`replay_widget` bakes the matching diagram to SVG
(:mod:`longeron.render`) and animates the timeline over it in the notebook
front-end (anywidget, optional -- install with ``pip install
"longeron[replay]"``): active states light up green, fired transitions
pulse orange, with play/pause, speed, and scrubbing controls, plus a
scalar-env readout that follows the playhead.  Pure event cascades (no
clock advance) replay in *step mode*, scrubbing over the step index
instead of sim time.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from . import model as M
from .errors import ExecutionError
from .interpreter import (
    Interpreter,
    SentEvent,
    StateMachine,
    TransitionFired,
    _ActionExecutor,
    _succession_plan,
)

if TYPE_CHECKING:
    import anywidget

    from .interpreter import _ActiveState

__all__ = [
    "FiredTransition",
    "Timeline",
    "record_action_timeline",
    "record_timeline",
    "replay_widget",
]


# ---------------------------------------------------------------------------
# timeline recording
# ---------------------------------------------------------------------------


@dataclass
class FiredTransition:
    """A fired transition, addressed by model qualified names."""

    t: float  # sim time; the step index in step mode
    source: str  # qualified names ("::"), matching SVG data-qname/data-edge
    target: str
    event: str | None


@dataclass
class Timeline:
    """A recorded simulation, keyed for replay over the state diagram.

    Track keyframes and ``fired`` times use sim time, except in *step mode*
    (``t_end == t_start``, a pure event cascade): then the key is the step
    index, and the front-end scrubs over steps instead of time (see the
    matching ``stepMode`` logic in the widget's ``_ESM``).
    """

    t_start: float
    t_end: float
    step_mode: bool
    n_steps: int
    #: per-state keyframes [(t_or_index, active)], recorded on change only
    tracks: dict[str, list[tuple[float, bool]]]
    fired: list[FiredTransition]
    # SimulationResult-equivalent fields
    final_state: str | None
    trace: list[TransitionFired] | list[str]
    ignored_events: list[str]
    env: dict[str, Any]
    sends: list[SentEvent]
    time: float = 0.0
    active_states: list[str] = field(default_factory=list)
    #: parent relation between recorded nodes (child qname -> parent qname);
    #: lets the front-end tint composite ancestors without guessing from
    #: "::" prefixes -- which breaks for typed submachines, whose inner
    #: states live under the *definition's* qualified name
    parents: dict[str, str] = field(default_factory=dict)
    #: per-step scalar env snapshots [(t_or_index, {name: value})], shown
    #: as the readout line under the widget's controls (step semantics,
    #: like tracks)
    env_steps: list[tuple[float, dict[str, Any]]] = field(default_factory=list)

    def to_json(self) -> str:
        """The replay payload (times and float values rounded to 3
        decimals)."""

        return json.dumps(
            {
                "t_start": round(self.t_start, 3),
                "t_end": round(self.t_end, 3),
                "step_mode": self.step_mode,
                "n_steps": self.n_steps,
                "final_state": self.final_state,
                "tracks": {
                    qname: [[round(t, 3), active] for t, active in keyframes]
                    for qname, keyframes in self.tracks.items()
                },
                "fired": [
                    {"t": round(f.t, 3), "source": f.source, "target": f.target, "event": f.event}
                    for f in self.fired
                ],
                "parents": self.parents,
                "env_steps": [
                    [
                        round(t, 3),
                        {
                            name: round(value, 3) if isinstance(value, float) else value
                            for name, value in values.items()
                        },
                    ]
                    for t, values in self.env_steps
                ],
            }
        )


def record_timeline(
    interpreter: Interpreter,
    state_machine: str | M.Definition | M.Usage,
    events: list[Any] | None = None,
    *,
    inputs: dict[str, Any] | None = None,
    max_steps: int = 1000,
) -> Timeline:
    """Simulate a state machine and record a replayable :class:`Timeline`.

    Mirrors ``Interpreter.simulate`` semantics: ``events`` entries are event
    names or ``(name, payload)`` tuples; plain numbers advance the clock.
    """

    target = (
        interpreter.resolver.resolve(state_machine)
        if isinstance(state_machine, str)
        else state_machine
    )
    if not isinstance(target, (M.Definition, M.Usage)):
        raise ExecutionError(f"{state_machine!r} is not a state machine")
    machine = StateMachine(interpreter, target, dict(inputs or {}))

    steps: list[tuple[float, TransitionFired | None, list[str], dict[str, Any]]] = []
    # dotted active-state paths (TransitionFired.source/target format) to
    # qualified names, learned from live configurations rather than parsed
    path_to_qname: dict[str, str] = {}
    parents: dict[str, str] = {}

    def observe(now: float, fired: TransitionFired | None) -> None:
        # snapshot the FULL active configuration (composites and leaves) as
        # model qualified names -- the addressing the diagrams/SVG use
        active: list[str] = []

        def visit(node: _ActiveState) -> None:
            qname = node.usage.qualified_name
            if qname is None:
                raise ExecutionError(
                    f"replay needs named states: active state {node.path()!r} has no qualified name"
                )
            path_to_qname[node.path()] = qname
            if node.parent is not None:  # recorded, not prefix-guessed
                parents.setdefault(qname, path_to_qname[node.parent.path()])
            active.append(qname)
            for child in node.children:
                visit(child)

        for root in machine.roots:
            visit(root)
        steps.append((now, fired, active, _scalar_env(machine.env.frames[0])))

    machine.on_step = observe
    machine.start()
    for event in events or []:
        if isinstance(event, (int, float)) and not isinstance(event, bool):
            machine.advance(event)  # numbers advance the clock (simulate())
        else:
            machine.send(event)
        if len(machine.trace) > max_steps:
            raise ExecutionError("state machine exceeded max_steps")
    return _build_timeline(machine, steps, path_to_qname, parents)


def _scalar_env(frame: dict[str, Any]) -> dict[str, Any]:
    """The scalar (str/int/float/bool) slice of an env frame."""

    return {
        name: value for name, value in frame.items() if isinstance(value, (str, int, float, bool))
    }


def _build_timeline(
    machine: StateMachine,
    steps: list[tuple[float, TransitionFired | None, list[str], dict[str, Any]]],
    path_to_qname: dict[str, str],
    parents: dict[str, str],
) -> Timeline:
    t_end = machine.now
    step_mode = t_end == 0.0  # no clock advance: scrub over step index

    tracks: dict[str, list[tuple[float, bool]]] = {}
    previously_active: set[str] = set()
    fired_records: list[FiredTransition] = []
    env_steps: list[tuple[float, dict[str, Any]]] = []
    for index, (now, fired, active, env) in enumerate(steps):
        key = float(index) if step_mode else now
        env_steps.append((key, env))
        current = set(active)
        for qname in active:  # newly active states
            if qname not in previously_active:
                tracks.setdefault(qname, []).append((key, True))
        for qname in previously_active - current:  # exited states
            tracks[qname].append((key, False))
        previously_active = current
        if fired is None:  # the initial-entry step
            continue
        try:
            source, target = (path_to_qname[fired.source], path_to_qname[fired.target])
        except KeyError as err:
            raise ExecutionError(
                f"replay could not map transition {fired!r} to qualified "
                f"names (unknown state path {err.args[0]!r})"
            ) from err
        fired_records.append(FiredTransition(key, source, target, fired.event))

    return Timeline(
        t_start=0.0,
        t_end=t_end,
        step_mode=step_mode,
        n_steps=len(steps),
        tracks=tracks,
        fired=fired_records,
        final_state=machine.current,
        trace=list(machine.trace),
        ignored_events=list(machine.ignored),
        env=dict(machine.env.frames[0]),
        sends=list(machine.sends),
        time=machine.now,
        active_states=machine.active_states(),
        parents=parents,
        env_steps=env_steps,
    )


def record_action_timeline(
    interpreter: Interpreter,
    action: str | M.Definition | M.Usage,
    events: list[Any] | None = None,
    *,
    inputs: dict[str, Any] | None = None,
) -> Timeline:
    """Run an action and record a replayable :class:`Timeline`.

    Mirrors ``Interpreter.run_action`` semantics (``events`` feed
    ``accept`` statements), observing every *named* action step through
    the executor's ``on_step`` hook.  The axis is always the step index
    (``step_mode`` is ``True``): step *k* is the k-th named step entered,
    active while it executes (nested steps nest, like composite states),
    and consecutive same-depth steps yield fired records for the
    traversed successions -- routed through intermediate control nodes
    (decide/merge/fork/join), so each drawn edge on the path pulses.
    Fired records are matched against the action diagram's edges by the
    front-end; records with no matching edge (e.g. across fork branches)
    are inert.
    """

    target = interpreter.resolver.resolve(action) if isinstance(action, str) else action
    if not isinstance(target, (M.Definition, M.Usage)):
        raise ExecutionError(f"{action!r} is not an action")
    executor = _ActionExecutor(interpreter, target, dict(inputs or {}), deque(events or []))

    # the top-level succession plan (the graph action_diagram draws):
    # used to route fired records through control-node intermediates
    plan = _succession_plan(list(target.members))
    qname_of: dict[str, str] = {}
    control: set[str] = set()
    successors: dict[str, list[str]] = {}
    if plan is not None:
        for name, element in plan.steps.items():
            if element.qualified_name:
                qname_of[name] = element.qualified_name
            if isinstance(element, M.ControlNode):
                control.add(name)
        for edge in plan.edges:
            successors.setdefault(edge.source, []).append(edge.target)
    name_of = {qname: name for name, qname in qname_of.items()}

    def succession_hops(prev_qname: str, qname: str) -> list[tuple[str, str]]:
        """The drawn edges from ``prev_qname`` to ``qname``: the shortest
        plan path whose intermediate nodes are all control nodes (BFS),
        else the direct pair (inert unless the diagram has that edge)."""

        prev, current = name_of.get(prev_qname), name_of.get(qname)
        if prev is not None and current is not None:
            queue = deque([[prev]])
            seen = {prev}
            while queue:
                path = queue.popleft()
                for successor in successors.get(path[-1], []):
                    if successor == current:
                        hops = [qname_of[n] for n in (*path, successor)]
                        return list(pairwise(hops))
                    if successor in control and successor not in seen:
                        seen.add(successor)
                        queue.append([*path, successor])
        return [(prev_qname, qname)]

    tracks: dict[str, list[tuple[float, bool]]] = {}
    parents: dict[str, str] = {}
    fired_records: list[FiredTransition] = []
    env_steps: list[tuple[float, dict[str, Any]]] = []
    stack: list[str] = []  # qnames of the steps currently executing
    last_at_depth: dict[int, str] = {}  # last completed step per depth
    n_keys = 0  # highest step key seen + 1

    def add_keyframe(qname: str, key: float, active: bool) -> None:
        track = tracks.setdefault(qname, [])
        if track and track[-1][0] == key:  # same-instant flip (loops):
            track.pop()  # the latest value wins
        if track:
            if track[-1][1] != active:
                track.append((key, active))
        elif active:  # tracks start with an activation
            track.append((key, active))

    def observe(index: int, element: M.Element, phase: str) -> None:
        nonlocal n_keys
        qname = element.qualified_name
        if qname is None:
            raise ExecutionError(
                f"replay needs named steps: {element.label!r} has no qualified name"
            )
        key = float(index)
        n_keys = max(n_keys, index + 1)
        if phase == "enter":
            depth = len(stack)
            if stack:
                parents.setdefault(qname, stack[-1])
            previous = last_at_depth.get(depth)
            if previous is not None and previous != qname:
                fired_records.extend(
                    FiredTransition(key, source, hop_target, None)
                    for source, hop_target in succession_hops(previous, qname)
                )
            for deeper in [d for d in last_at_depth if d > depth]:
                del last_at_depth[deeper]  # stale once a new step opens
            stack.append(qname)
            add_keyframe(qname, key, True)
        else:  # complete
            if stack and stack[-1] == qname:
                stack.pop()
            last_at_depth[len(stack)] = qname
            add_keyframe(qname, key, False)
        env = _scalar_env(executor.env.frames[0])
        if env_steps and env_steps[-1][0] == key:
            env_steps[-1] = (key, env)
        else:
            env_steps.append((key, env))

    executor.on_step = observe
    result = executor.run()
    if not env_steps:  # no named steps: still expose the final env
        env_steps.append((0.0, _scalar_env(executor.env.frames[0])))
    return Timeline(
        t_start=0.0,
        t_end=0.0,
        step_mode=True,
        n_steps=max(n_keys, 1),
        tracks=tracks,
        fired=fired_records,
        final_state=None,
        trace=list(result.trace),
        ignored_events=[],
        env=dict(result.env),
        sends=list(result.sends),
        time=result.time,
        active_states=[],
        parents=parents,
        env_steps=env_steps,
    )


# ---------------------------------------------------------------------------
# anywidget front-end (vanilla JS, no bundler)
# ---------------------------------------------------------------------------

# Conventions (see .handoff/scene-viewer-mechanics.md): the SVG is injected
# once and nodes/edges are indexed by data-qname/data-edge; per frame only
# classes toggle.  Keyframe lookup is a binary search with left-keyframe
# (step) semantics, matching how Timeline.tracks records changes.  Strokes
# use vector-effect: non-scaling-stroke with pixel widths.
_ESM = r"""
function render({ model, el }) {
  const timeline = JSON.parse(model.get("timeline_json"));
  const stepMode = timeline.step_mode;
  // parent relation recorded by replay.py (child qname -> parent qname);
  // older payloads lack it and fall back to "::"-prefix guessing
  const parents = timeline.parents || null;
  const envSteps = timeline.env_steps || [];
  // step mode (Timeline.step_mode in replay.py): the axis is the step
  // index -- pure event cascades collapse to one instant of sim time
  const axisStart = stepMode ? 0 : timeline.t_start;
  const axisEnd = stepMode ? Math.max(timeline.n_steps - 1, 0)
                           : timeline.t_end;
  const span = axisEnd - axisStart;
  // fired transitions pulse for ~4% of the span (one step in step mode)
  const pulse = stepMode ? 1 : Math.max(span * 0.04, 1e-9);

  el.classList.add("longeron-replay");
  el.innerHTML = "";

  // --- stage: inject the baked SVG once, index it, never rebuild it
  const stage = document.createElement("div");
  stage.className = "longeron-replay-stage";
  stage.style.maxWidth = model.get("width_px") + "px";
  stage.innerHTML = model.get("svg");
  const svg = stage.querySelector("svg");
  if (svg) {  // scale to the stage; the viewBox keeps proportions
    svg.removeAttribute("width");
    svg.removeAttribute("height");
  }
  const nodes = [];  // [qname, element] for every addressable box
  stage.querySelectorAll("[data-qname]").forEach((n) => {
    n.setAttribute("vector-effect", "non-scaling-stroke");
    nodes.push([n.getAttribute("data-qname"), n]);
  });
  const groups = [];  // edge groups: data-edge key + accepted events
  stage.querySelectorAll("[data-edge]").forEach((g) => {
    g.querySelectorAll("path").forEach(
      (p) => p.setAttribute("vector-effect", "non-scaling-stroke"));
    groups.push({
      el: g,
      key: g.getAttribute("data-edge"),
      events: (g.getAttribute("data-event") || "").split(",")
        .filter(Boolean),
    });
  });
  // pre-match fired records to edge groups; data-event disambiguates
  // parallel edges between the same pair of states
  const fired = timeline.fired.map((f) => {
    const key = f.source + "->" + f.target;
    const matches = groups.filter((g) => g.key === key);
    const exact = matches.find((g) => (f.event
      ? g.events.includes(f.event) : g.events.length === 0));
    return { t: f.t, el: (exact || matches[0] || { el: null }).el };
  });

  // --- controls row: play/pause, speed, scrub, clock
  const bar = document.createElement("div");
  bar.className = "longeron-replay-bar";
  const button = document.createElement("button");
  button.textContent = "\u25b6";
  const speed = document.createElement("select");
  for (const s of [0.5, 1, 2, 4, 8, 16, 32]) {
    const option = document.createElement("option");
    option.value = String(s);
    option.textContent = s + "\u00d7";
    if (s === 1) option.selected = true;
    speed.appendChild(option);
  }
  const scrub = document.createElement("input");
  scrub.type = "range";
  scrub.min = String(axisStart);
  scrub.max = String(axisEnd);
  scrub.step = span > 0 ? String(span / 500) : "1";
  scrub.value = String(axisStart);
  const clock = document.createElement("span");
  clock.className = "longeron-replay-clock";
  bar.append(button, speed, scrub, clock);

  // --- env readout: scalar env values that follow the playhead
  const env = document.createElement("div");
  env.className = "longeron-replay-env";

  const trackEntries = Object.entries(timeline.tracks);

  function lastIndexAt(entries, t) {
    // last entry with key <= t (left/step semantics), -1 if none
    if (!entries.length || t < entries[0][0]) return -1;
    let lo = 0;
    let hi = entries.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (entries[mid][0] <= t) lo = mid;
      else hi = mid - 1;
    }
    return lo;
  }

  function activeAt(keyframes, t) {
    const index = lastIndexAt(keyframes, t);
    return index >= 0 && keyframes[index][1];
  }

  function draw(t) {
    const active = new Set();
    for (const [qname, keyframes] of trackEntries) {
      if (activeAt(keyframes, t)) active.add(qname);
    }
    // composite ancestors of an active node get the branch tint: from
    // the recorded parents map when present (correct for typed
    // submachines), else the legacy "::"-prefix guess
    let branches = null;
    if (parents) {
      branches = new Set();
      for (const qname of active) {
        const parent = parents[qname];
        if (parent !== undefined) branches.add(parent);
      }
    }
    for (const [qname, n] of nodes) {
      const isActive = active.has(qname);
      let isBranch = false;
      if (isActive) {
        if (branches) {
          isBranch = branches.has(qname);
        } else {
          for (const other of active) {
            if (other !== qname && other.startsWith(qname + "::")) {
              isBranch = true;
              break;
            }
          }
        }
      }
      n.classList.toggle("longeron-active", isActive && !isBranch);
      n.classList.toggle("longeron-active-branch", isBranch);
    }
    for (const f of fired) {
      if (f.el) {
        f.el.classList.toggle("longeron-fired",
                              t >= f.t && t < f.t + pulse);
      }
    }
    if (envSteps.length) {
      const index = lastIndexAt(envSteps, t);
      env.textContent = index < 0 ? ""
        : Object.entries(envSteps[index][1])
            .map(([name, value]) => name + " = " + value)
            .join("   ");
    }
    clock.textContent = stepMode
      ? "step " + Math.round(t) + " / " + axisEnd
      : t.toFixed(2) + " / " + axisEnd.toFixed(2) + " s";
  }

  // --- playback: requestAnimationFrame loop; `time` is the synced
  // bidirectional traitlet (JS writes ~4 Hz while playing; Python
  // writes seek the playhead)
  let t = axisStart;
  let playing = false;
  let raf = 0;
  let last = 0;
  let lastSync = 0;

  function syncModel(force) {
    const now = performance.now();
    if (!force && now - lastSync < 250) return;  // ~4 Hz
    lastSync = now;
    model.set("time", t);
    model.save_changes();
  }
  function stop() {
    playing = false;
    button.textContent = "\u25b6";
    cancelAnimationFrame(raf);
    syncModel(true);
  }
  function tick(now) {
    const dt = (now - last) / 1000;
    last = now;
    t += dt * parseFloat(speed.value);  // step mode: 1x = 1 step/s
    if (t >= axisEnd) {
      t = axisEnd;
      playing = false;
      button.textContent = "\u25b6";
    }
    scrub.value = String(t);
    draw(t);
    syncModel(!playing);
    if (playing) raf = requestAnimationFrame(tick);
  }
  function play() {
    if (span <= 0) return;
    if (t >= axisEnd) t = axisStart;  // replay from the top
    playing = true;
    button.textContent = "\u275a\u275a";
    last = performance.now();
    raf = requestAnimationFrame(tick);
  }
  button.addEventListener("click", () => (playing ? stop() : play()));
  scrub.addEventListener("input", () => {
    if (playing) stop();
    t = parseFloat(scrub.value);
    draw(t);
    syncModel(true);
  });
  model.on("change:time", () => {  // Python-side seek
    const value = model.get("time");
    if (Math.abs(value - t) < 1e-9) return;  // echo of our own set
    if (playing) stop();
    t = Math.min(Math.max(value, axisStart), axisEnd);
    scrub.value = String(t);
    draw(t);
  });
  model.on("change:width_px", () => {
    stage.style.maxWidth = model.get("width_px") + "px";
  });

  el.append(stage, bar);
  if (envSteps.length) el.append(env);
  draw(t);
}
export default { render };
"""

# Highlight colors track diagrams.SYSML_STYLE: active states use the usage
# green family, fired transitions pulse orange.  Plain class selectors
# override the SVG's baked presentation attributes (no inline styles).
_CSS = """
.longeron-replay { font-family: Helvetica, Arial, sans-serif; }
.longeron-replay-stage {
  border: 1px solid #e2e2e2; border-radius: 8px; overflow: hidden;
  background: #ffffff;
}
.longeron-replay-stage svg { display: block; width: 100%; height: auto; }
.longeron-replay-bar {
  display: flex; gap: 10px; align-items: center; margin-top: 8px;
}
.longeron-replay-bar button {
  appearance: none; -webkit-appearance: none;
  border: 1px solid #d4d4d4; border-radius: 6px; background: #ffffff;
  color: #333333; font-size: 13px; line-height: 1;
  padding: 6px 12px; cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}
.longeron-replay-bar button:hover { background: #f5f5f5; }
.longeron-replay-bar button:active { background: #ececec; }
.longeron-replay-bar select {
  border: 1px solid #d4d4d4; border-radius: 6px; background: #ffffff;
  color: #333333; font-size: 12px; padding: 5px 8px; cursor: pointer;
}
.longeron-replay-bar input[type="range"] {
  flex: 1; accent-color: #3f7a1f; cursor: pointer;
}
.longeron-replay-clock {
  font-variant-numeric: tabular-nums; font-size: 12px; color: #555555;
  white-space: nowrap;
}
.longeron-replay-env {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 11px; color: #555555; margin-top: 4px;
  font-variant-numeric: tabular-nums; white-space: pre-wrap;
  min-height: 14px;
}
.longeron-replay [data-qname] { transition: fill 0.15s, stroke 0.15s; }
.longeron-replay .longeron-active {
  fill: #d9efc2; stroke: #3f7a1f; stroke-width: 2px;
}
.longeron-replay .longeron-active-branch {
  fill: #eef7e2; stroke: #6a9a48; stroke-width: 1.6px;
}
/* fired transitions: recolor stroke AND the arrowhead (marker swap; the
   markers use userSpaceOnUse so the wider stroke does not scale them) */
.longeron-replay .longeron-fired path {
  stroke: #e05a00; stroke-width: 2.4px;
  marker-end: url(#arrow-e05a00);
}
"""

_WIDGET_CLS: type[anywidget.AnyWidget] | None = None


def _widget_class() -> type[anywidget.AnyWidget]:
    """Define ReplayWidget lazily -- anywidget is an optional extra."""

    global _WIDGET_CLS
    if _WIDGET_CLS is not None:
        return _WIDGET_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise ImportError(
            "the replay widget needs anywidget; install the extra with "
            "'pip install \"longeron[replay]\"'"
        ) from err

    class ReplayWidget(_anywidget.AnyWidget):
        """Animated replay of a recorded Timeline over the state SVG."""

        _esm = _ESM
        _css = _CSS
        svg = traitlets.Unicode("").tag(sync=True)
        timeline_json = traitlets.Unicode("").tag(sync=True)
        width_px = traitlets.Int(760).tag(sync=True)
        #: bidirectional playhead (sim time, or step index in step mode)
        time = traitlets.Float(0.0).tag(sync=True)

    _WIDGET_CLS = ReplayWidget
    return ReplayWidget


def replay_widget(
    interpreter: Interpreter,
    element: str | M.Definition | M.Usage,
    events: list[Any] | None = None,
    *,
    inputs: dict[str, Any] | None = None,
    width_px: int = 760,
    kind: str | None = None,
) -> anywidget.AnyWidget:
    """Simulate ``element`` and replay it over its diagram.

    ``kind`` picks the view and recorder: ``"state"``
    (:func:`record_timeline` over the state diagram) or ``"action"``
    (:func:`record_action_timeline` over the action diagram).  The
    default (``None``) auto-detects: elements whose ``kind`` is
    ``"action"`` replay as actions, everything else as a state machine.

    Needs the ``replay`` extra (anywidget) plus the diagram toolchain
    (vendored ipyelk and a ``node`` executable, as for ``render.to_svg``).
    """

    cls = _widget_class()
    target = interpreter.resolver.resolve(element) if isinstance(element, str) else element
    if not isinstance(target, (M.Definition, M.Usage)):
        raise ExecutionError(f"{element!r} is not a state machine or action")
    if kind is None:
        kind = "action" if target.kind == "action" else "state"
    if kind not in ("state", "action"):
        raise ExecutionError(f"unknown replay kind {kind!r} (expected 'state' or 'action')")
    from . import diagrams, render  # need ipyelk + node; import late

    if kind == "action":
        timeline = record_action_timeline(interpreter, target, events, inputs=inputs)
        svg = render.to_svg(diagrams.action_diagram(target))
    else:
        timeline = record_timeline(interpreter, target, events, inputs=inputs)
        svg = render.to_svg(diagrams.state_diagram(target))
    return cls(svg=svg, timeline_json=timeline.to_json(), width_px=width_px)
