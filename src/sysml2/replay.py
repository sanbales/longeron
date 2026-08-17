"""Replay state-machine simulations over the rendered state diagram.

:func:`record_timeline` drives a :class:`~sysml2.interpreter.StateMachine`
through the same event protocol as ``Interpreter.simulate`` while observing
every step through the machine's ``on_step`` hook, producing a
:class:`Timeline`: per-state activation keyframes plus fired-transition
instants, addressed by model *qualified names* (the same ``::`` ids the
diagrams and headless SVG use).

:func:`replay_widget` bakes the state diagram to SVG (:mod:`sysml2.render`)
and animates the timeline over it in the notebook front-end (anywidget,
optional -- install with ``pip install "sysml2[replay]"``): active states
light up green, fired transitions pulse orange, with play/pause, speed,
and scrubbing controls.  Pure event cascades (no clock advance) replay in
*step mode*, scrubbing over the step index instead of sim time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from . import model as M
from .errors import ExecutionError
from .interpreter import Interpreter, SentEvent, StateMachine, TransitionFired

if TYPE_CHECKING:
    import anywidget

    from .interpreter import _ActiveState

__all__ = ["FiredTransition", "Timeline", "record_timeline", "replay_widget"]


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
    trace: list[TransitionFired]
    ignored_events: list[str]
    env: dict[str, Any]
    sends: list[SentEvent]
    time: float = 0.0
    active_states: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        """The replay payload (times rounded to 3 decimals)."""

        return json.dumps({
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
                {"t": round(f.t, 3), "source": f.source, "target": f.target,
                 "event": f.event}
                for f in self.fired
            ],
        })


def record_timeline(interpreter: Interpreter,
                    state_machine: str | M.Definition | M.Usage,
                    events: list[Any] | None = None, *,
                    inputs: dict[str, Any] | None = None,
                    max_steps: int = 1000) -> Timeline:
    """Simulate a state machine and record a replayable :class:`Timeline`.

    Mirrors ``Interpreter.simulate`` semantics: ``events`` entries are event
    names or ``(name, payload)`` tuples; plain numbers advance the clock.
    """

    target = (interpreter.resolver.resolve(state_machine)
              if isinstance(state_machine, str) else state_machine)
    if not isinstance(target, (M.Definition, M.Usage)):
        raise ExecutionError(f"{state_machine!r} is not a state machine")
    machine = StateMachine(interpreter, target, dict(inputs or {}))

    steps: list[tuple[float, TransitionFired | None, list[str]]] = []
    # dotted active-state paths (TransitionFired.source/target format) to
    # qualified names, learned from live configurations rather than parsed
    path_to_qname: dict[str, str] = {}

    def observe(now: float, fired: TransitionFired | None) -> None:
        # snapshot the FULL active configuration (composites and leaves) as
        # model qualified names -- the addressing the diagrams/SVG use
        active: list[str] = []

        def visit(node: _ActiveState) -> None:
            qname = node.usage.qualified_name
            if qname is None:
                raise ExecutionError(
                    f"replay needs named states: active state "
                    f"{node.path()!r} has no qualified name")
            path_to_qname[node.path()] = qname
            active.append(qname)
            for child in node.children:
                visit(child)

        for root in machine.roots:
            visit(root)
        steps.append((now, fired, active))

    machine.on_step = observe
    machine.start()
    for event in events or []:
        if isinstance(event, (int, float)) and not isinstance(event, bool):
            machine.advance(event)  # numbers advance the clock (simulate())
        else:
            machine.send(event)
        if len(machine.trace) > max_steps:
            raise ExecutionError("state machine exceeded max_steps")
    return _build_timeline(machine, steps, path_to_qname)


def _build_timeline(machine: StateMachine,
                    steps: list[tuple[float, TransitionFired | None,
                                      list[str]]],
                    path_to_qname: dict[str, str]) -> Timeline:
    t_end = machine.now
    step_mode = t_end == 0.0  # no clock advance: scrub over step index

    tracks: dict[str, list[tuple[float, bool]]] = {}
    previously_active: set[str] = set()
    fired_records: list[FiredTransition] = []
    for index, (now, fired, active) in enumerate(steps):
        key = float(index) if step_mode else now
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
            source, target = (path_to_qname[fired.source],
                              path_to_qname[fired.target])
        except KeyError as err:
            raise ExecutionError(
                f"replay could not map transition {fired!r} to qualified "
                f"names (unknown state path {err.args[0]!r})") from err
        fired_records.append(FiredTransition(key, source, target,
                                             fired.event))

    return Timeline(
        t_start=0.0, t_end=t_end, step_mode=step_mode, n_steps=len(steps),
        tracks=tracks, fired=fired_records,
        final_state=machine.current, trace=list(machine.trace),
        ignored_events=list(machine.ignored),
        env=dict(machine.env.frames[0]), sends=list(machine.sends),
        time=machine.now, active_states=machine.active_states())


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
  // step mode (Timeline.step_mode in replay.py): the axis is the step
  // index -- pure event cascades collapse to one instant of sim time
  const axisStart = stepMode ? 0 : timeline.t_start;
  const axisEnd = stepMode ? Math.max(timeline.n_steps - 1, 0)
                           : timeline.t_end;
  const span = axisEnd - axisStart;
  // fired transitions pulse for ~4% of the span (one step in step mode)
  const pulse = stepMode ? 1 : Math.max(span * 0.04, 1e-9);

  el.classList.add("sysml2-replay");
  el.innerHTML = "";

  // --- stage: inject the baked SVG once, index it, never rebuild it
  const stage = document.createElement("div");
  stage.className = "sysml2-replay-stage";
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
  bar.className = "sysml2-replay-bar";
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
  clock.className = "sysml2-replay-clock";
  bar.append(button, speed, scrub, clock);

  const trackEntries = Object.entries(timeline.tracks);

  function activeAt(keyframes, t) {
    if (!keyframes.length || t < keyframes[0][0]) return false;
    let lo = 0;
    let hi = keyframes.length - 1;
    while (lo < hi) {  // last keyframe with time <= t (left/step semantics)
      const mid = (lo + hi + 1) >> 1;
      if (keyframes[mid][0] <= t) lo = mid;
      else hi = mid - 1;
    }
    return keyframes[lo][1];
  }

  function draw(t) {
    const active = new Set();
    for (const [qname, keyframes] of trackEntries) {
      if (activeAt(keyframes, t)) active.add(qname);
    }
    for (const [qname, n] of nodes) {
      // leaves light up fully; composite ancestors (a "::"-prefix of a
      // deeper active state -- qualified names nest) get the branch tint
      const isActive = active.has(qname);
      let isBranch = false;
      if (isActive) {
        for (const other of active) {
          if (other !== qname && other.startsWith(qname + "::")) {
            isBranch = true;
            break;
          }
        }
      }
      n.classList.toggle("sysml2-active", isActive && !isBranch);
      n.classList.toggle("sysml2-active-branch", isBranch);
    }
    for (const f of fired) {
      if (f.el) {
        f.el.classList.toggle("sysml2-fired",
                              t >= f.t && t < f.t + pulse);
      }
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
  draw(t);
}
export default { render };
"""

# Highlight colors track diagrams.SYSML_STYLE: active states use the usage
# green family, fired transitions pulse orange.  Plain class selectors
# override the SVG's baked presentation attributes (no inline styles).
_CSS = """
.sysml2-replay { font-family: Helvetica, Arial, sans-serif; }
.sysml2-replay-stage { border: 1px solid #dddddd; }
.sysml2-replay-stage svg { display: block; width: 100%; height: auto; }
.sysml2-replay-bar {
  display: flex; gap: 8px; align-items: center; margin-top: 6px;
}
.sysml2-replay-bar input[type="range"] { flex: 1; }
.sysml2-replay-clock {
  font-variant-numeric: tabular-nums; font-size: 12px; color: #333333;
  white-space: nowrap;
}
.sysml2-replay [data-qname] { transition: fill 0.15s, stroke 0.15s; }
.sysml2-replay .sysml2-active {
  fill: #d9efc2; stroke: #3f7a1f; stroke-width: 2px;
}
.sysml2-replay .sysml2-active-branch {
  fill: #eef7e2; stroke: #6a9a48; stroke-width: 1.6px;
}
.sysml2-replay .sysml2-fired path {
  stroke: #e05a00; stroke-width: 2.4px;
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
            "'pip install \"sysml2[replay]\"'") from err

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


def replay_widget(interpreter: Interpreter,
                  state_machine: str | M.Definition | M.Usage,
                  events: list[Any] | None = None, *,
                  inputs: dict[str, Any] | None = None,
                  width_px: int = 760) -> anywidget.AnyWidget:
    """Simulate ``state_machine`` and replay it over its state diagram.

    Needs the ``replay`` extra (anywidget) plus the diagram toolchain
    (vendored ipyelk and a ``node`` executable, as for ``render.to_svg``).
    """

    cls = _widget_class()
    target = (interpreter.resolver.resolve(state_machine)
              if isinstance(state_machine, str) else state_machine)
    if not isinstance(target, (M.Definition, M.Usage)):
        raise ExecutionError(f"{state_machine!r} is not a state machine")
    timeline = record_timeline(interpreter, target, events, inputs=inputs)
    from . import diagrams, render  # need ipyelk + node; import late

    svg = render.to_svg(diagrams.state_diagram(target))
    return cls(svg=svg, timeline_json=timeline.to_json(), width_px=width_px)
