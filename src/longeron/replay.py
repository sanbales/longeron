"""Replay state-machine and action executions over rendered diagrams.

:func:`record_timeline` drives a :class:`~longeron.interpreter.StateMachine`
through the same event protocol as ``Interpreter.simulate`` while observing
every step through the machine's ``on_step`` hook, producing a
:class:`Timeline`: per-state activation keyframes plus fired-transition
instants, addressed by *instance-qualified* names -- the machine's
qualified name extended along the active-state path (the same ``::`` ids
the diagrams and headless SVG use, unique per typed-submachine expansion
site).  :func:`record_action_timeline` does the
same for action executions via the executor's step observer: the active
node is the currently-executing named action step, fired records are the
traversed successions, and the axis is always the step index.

The replay widget itself lives in :mod:`longeron.widgets.replay`
(:func:`~longeron.widgets.replay.replay_widget` bakes the matching
diagram to SVG and animates the timeline over it); this module is the
kernel-side recorder and needs no widget toolkit.  Importing
``replay_widget`` from here still works but is deprecated.
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
    from .interpreter import _ActiveState

__all__ = [
    "FiredTransition",
    "Timeline",
    "record_action_timeline",
    "record_timeline",
]

#: names that moved to :mod:`longeron.widgets.replay`; forwarded with a
#: DeprecationWarning by module ``__getattr__``
_MOVED = ("replay_widget", "_widget_class", "_ESM", "_CSS")


def __getattr__(name: str) -> Any:
    if name in _MOVED:
        import warnings

        warnings.warn(
            f"longeron.replay.{name} moved to longeron.widgets.replay.{name}; "
            "the longeron.replay alias will be removed in a future release",
            DeprecationWarning,
            stacklevel=2,
        )
        from .widgets import replay as _home

        return getattr(_home, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    #: parent relation between recorded nodes (child qname -> parent qname):
    #: the recorded truth the front-end tints composite ancestors with --
    #: keys are instance-qualified, so it now agrees with the "::" prefix
    #: relation, but it stays authoritative (and keeps older front-end
    #: payload handling honest)
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
    machine_qname = target.qualified_name
    if machine_qname is None:
        raise ExecutionError(
            f"replay needs a named state machine: {target.label!r} has no qualified name"
        )
    machine = StateMachine(interpreter, target, dict(inputs or {}))

    steps: list[tuple[float, TransitionFired | None, list[str], dict[str, Any]]] = []
    # dotted active-state paths (TransitionFired.source/target format) to
    # instance-qualified names, learned from live configurations
    path_to_qname: dict[str, str] = {}
    parents: dict[str, str] = {}

    def observe(now: float, fired: TransitionFired | None) -> None:
        # snapshot the FULL active configuration (composites and leaves) as
        # INSTANCE-qualified names: the machine's qualified name extended
        # along the active path -- the addressing the diagrams/SVG use.
        # Deliberately NOT the usage's own qualified name: for typed
        # submachines (state swap : ToteSwap) the active usages are the
        # DEFINITION's members, and two expansion sites sharing one
        # definition must never share a replay key (the double-highlight
        # aliasing defect)
        active: list[str] = []

        def visit(node: _ActiveState, base: str) -> None:
            if node.usage.name is None:
                raise ExecutionError(
                    f"replay needs named states: active state {node.path()!r} has no name"
                )
            qname = f"{base}::{node.usage.name}"
            path_to_qname[node.path()] = qname
            if node.parent is not None:  # recorded, not prefix-guessed
                parents.setdefault(qname, path_to_qname[node.parent.path()])
            active.append(qname)
            for child in node.children:
                visit(child, qname)

        for root in machine.roots:
            visit(root, machine_qname)
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
