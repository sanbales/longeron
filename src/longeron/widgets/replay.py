"""The replay widget: animate a recorded Timeline over its baked diagram.

:func:`replay_widget` simulates an element (or takes a prebuilt
:class:`~longeron.replay.Timeline`), bakes the matching diagram to SVG
(:mod:`longeron.render`), and animates the run over it in the notebook
front-end (anywidget, optional -- install with ``pip install
"longeron[replay]"``): active states light up green, fired transitions
pulse orange, with play/pause, speed, and scrubbing controls, plus a
scalar-env readout that follows the playhead.  Pure event cascades (no
clock advance) replay in *step mode*, scrubbing over the step index
instead of sim time.

The timeline recorders themselves (:func:`~longeron.replay.record_timeline`,
:func:`~longeron.replay.record_action_timeline`) live in
:mod:`longeron.replay`: recording is simulation, not presentation, and
needs no widget toolkit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from .. import model as M
from ..errors import ExecutionError, MissingExtraError
from ..render import _FIRED_STROKE, _NODE_STYLES, _arrow_id
from ..replay import record_action_timeline, record_timeline
from ._seam import SEAM_ESM, SeamHost

if TYPE_CHECKING:
    import anywidget

    from ..interpreter import Interpreter
    from ..replay import Timeline

__all__ = ["ReplayKind", "replay_widget"]

#: which view and recorder :func:`replay_widget` uses: the state diagram
#: with :func:`~longeron.replay.record_timeline`, or the action diagram
#: with :func:`~longeron.replay.record_action_timeline`
ReplayKind = Literal["state", "action"]


# Conventions (shared with longeron.widgets.viewer3d): the SVG is injected
# once and nodes/edges are indexed by data-qname/data-edge; per frame only
# classes toggle.  Keyframe lookup is a binary search with left-keyframe
# (step) semantics, matching how Timeline.tracks records changes.  Strokes
# use vector-effect: non-scaling-stroke with pixel widths.  Playhead
# reports ride the loss-tolerance seam client (widgets/_seam.py).
_ESM = (
    SEAM_ESM
    + r"""
function render({ model, el }) {
  const seam = lgnSeam(model);
  const timeline = JSON.parse(model.get("timeline_json"));
  const stepMode = timeline.step_mode;
  // parent relation recorded by replay.py (child qname -> parent qname);
  // the recorded truth for tinting composite ancestors -- older payloads
  // lack it and fall back to "::"-prefix guessing
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
  // NOTE: edge paths deliberately do NOT get vector-effect:
  // non-scaling-stroke -- Chromium skips painting markers (arrowheads)
  // on paths carrying it (crbug 528196 family). Strokes scale with
  // zoom instead, which matches the userSpaceOnUse marker geometry.
  stage.querySelectorAll("[data-edge]").forEach((g) => {
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
    // the recorded parents map when present, else the legacy
    // "::"-prefix guess
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
  // writes seek the playhead).  The playhead may have been seeked
  // before this view rendered (the time seam's link fan-out), so the
  // initial t comes from the model, not from axisStart.
  let t = Math.min(Math.max(model.get("time") || axisStart, axisStart), axisEnd);
  scrub.value = String(t);
  let playing = false;
  let raf = 0;
  let last = 0;
  let lastSync = 0;

  function syncModel(force) {
    const now = performance.now();
    if (!force && now - lastSync < 250) return;  // ~4 Hz
    lastSync = now;
    seam.report({ time: t });
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
    seam.intent({ time: t });  // user intent outranks a raced push
  });
  model.on("change:time", () => {  // Python-side seek
    const value = model.get("time");
    if (Math.abs(value - t) < 1e-9) return;  // echo of our own set
    // adopt the seek BEFORE stopping: stop() force-syncs t, and syncing
    // the pre-seek playhead would revert the kernel's write (the time
    // seam's scrub-while-playing fight)
    t = Math.min(Math.max(value, axisStart), axisEnd);
    if (playing) stop();
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
)

# Highlight colors track the shared palette in longeron.render (V3): active
# states use the usage green family, fired transitions pulse the replay
# orange (render._FIRED_STROKE) -- the fired rule below is derived from it,
# so the marker reference cannot silently desync from render._arrow_defs.
# Plain class selectors override the SVG's baked presentation attributes
# (no inline styles).
_CSS = (
    """
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
"""
    + f"""
.longeron-replay .longeron-active-branch {{
  fill: #eef7e2; stroke: {_NODE_STYLES["sysml-usage"]["stroke"]}; stroke-width: 1.6px;
}}
/* fired transitions: recolor stroke AND the arrowhead (marker swap; the
   markers use userSpaceOnUse so the wider stroke does not scale them) */
.longeron-replay .longeron-fired path {{
  stroke: {_FIRED_STROKE}; stroke-width: 2.4px;
  marker-end: url(#{_arrow_id(_FIRED_STROKE)});
}}
"""
)

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
        raise MissingExtraError("the replay widget", "anywidget", "replay") from err

    class ReplayWidget(SeamHost, _anywidget.AnyWidget):
        """Animated replay of a recorded Timeline over the state SVG."""

        _esm = _ESM
        _css = _CSS
        svg = traitlets.Unicode("").tag(sync=True)
        timeline_json = traitlets.Unicode("").tag(sync=True)
        width_px = traitlets.Int(760).tag(sync=True)
        #: bidirectional playhead (sim time, or step index in step mode)
        time = traitlets.Float(0.0).tag(sync=True)
        #: the loss-tolerance stamps (widgets/_seam.py): the kernel's
        #: push generation, the front-end's last-applied acknowledgement,
        #: and the front-end's user-action counter
        _seam_gen = traitlets.Int(0).tag(sync=True)
        _seam_ack = traitlets.Int(0).tag(sync=True)
        _seam_intent = traitlets.Int(0).tag(sync=True)

    _WIDGET_CLS = ReplayWidget
    return ReplayWidget


def replay_widget(
    interpreter: Interpreter,
    element: str | M.Definition | M.Usage,
    events: list[Any] | None = None,
    *,
    inputs: dict[str, Any] | None = None,
    width_px: int = 760,
    kind: ReplayKind | None = None,
    timeline: Timeline | None = None,
) -> anywidget.AnyWidget:
    """Simulate ``element`` and replay it over its diagram.

    ``kind`` picks the view and recorder: ``"state"``
    (:func:`record_timeline` over the state diagram) or ``"action"``
    (:func:`record_action_timeline` over the action diagram).  The
    default (``None``) auto-detects: elements whose ``kind`` is
    ``"action"`` replay as actions, everything else as a state machine.

    ``timeline`` skips the recording and replays a PREBUILT
    :class:`Timeline` instead, so one recording can feed this widget,
    the mission globe, and the time seam's scrubber (see
    :mod:`longeron.widgets.time`); it excludes ``events``/``inputs``.
    The widget's bidirectional ``time`` trait is its seam surface: a
    kernel-side write seeks the playhead (stopping any front-end
    playback first), and the front-end reports the playhead at ~4 Hz
    while playing -- :func:`longeron.widgets.link_time` subscribes it
    to a shared clock.

    Needs the ``replay`` extra (anywidget) plus the diagram toolchain
    (vendored ipyelk and a ``node`` executable, as for ``render.to_svg``).
    """

    cls = _widget_class()
    target = interpreter.resolver.resolve(element) if isinstance(element, str) else element
    if not isinstance(target, (M.Definition, M.Usage)):
        raise ExecutionError(f"{element!r} is not a state machine or action")
    if timeline is not None and (events is not None or inputs is not None):
        raise ExecutionError("pass a prebuilt timeline OR events/inputs to record, not both")
    if kind is None:
        kind = "action" if target.kind == "action" else "state"
    if kind not in ("state", "action"):
        raise ExecutionError(f"unknown replay kind {kind!r} (expected 'state' or 'action')")
    from .. import diagrams, render  # need ipyelk + node; import late

    # the diagram widget here is disposable (baked straight to SVG), so
    # skip the interactive toolbar upgrade
    if kind == "action":
        if timeline is None:
            timeline = record_action_timeline(interpreter, target, events, inputs=inputs)
        svg = render.to_svg(diagrams.action_diagram(target, toolbar=False))
    else:
        if timeline is None:
            timeline = record_timeline(interpreter, target, events, inputs=inputs)
        svg = render.to_svg(diagrams.state_diagram(target, toolbar=False))
    return cls(svg=svg, timeline_json=timeline.to_json(), width_px=width_px)
