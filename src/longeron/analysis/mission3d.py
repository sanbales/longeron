"""Mission flight replay on a CesiumJS globe (anywidget).

Turns MODEL-level mission data into a timestamped geodetic track and
animates a drone flying it over a real globe.  Two builders produce the
same :class:`MissionTrack`:

* :func:`mission_track` -- explicit waypoints ``(lat, lon, alt[, t])``
  (degrees, meters above the ellipsoid, seconds).  Missing times derive
  from a cruise speed over the 3D leg lengths.  :func:`model_waypoints`
  reads the same tuples off a mission part's children (attributes named
  ``lat``/``lon``/``alt``, optional ``t``) through the interpreter, so
  the waypoints can live in the model itself.
* :func:`from_replay` -- the state-machine timeline: the interpreter
  executes the machine through :func:`longeron.replay.record_timeline`
  (the same recorder the diagram replay widget uses) and each leaf
  state's activation interval becomes one motion segment.  The mapping
  is deliberately simple and name-driven -- the point is model-driven
  animation (the globe shows the ACTUAL executed behavior: state
  durations, interleavings, reentries), not flight-sim fidelity.  A
  state's phase comes from substring hints on its name, overridable per
  state name via ``phases=``:

  ``ground`` (idle, standby, parked, ...)
      hold the current position; the mission starts at the first
      waypoint at ``ground_alt``.
  ``takeoff`` (takingOff, launch, climb, ...)
      vertical climb, in place, to the route altitude at the current
      route position.
  ``route`` (flying, cruise, loiter, hover, survey, ...)
      advance along the waypoint polyline; each segment covers a
      distance proportional to its share of the total route-phase
      time, so several flying/loiter states spend the one route
      between them and the drone lands wherever the machine stopped
      flying.
  ``landing`` (landing, descend, ...)
      vertical descent, in place, to ``ground_alt``.
  ``hold`` (anything unrecognized)
      hover in place.

  Pure event cascades (no clock advance) record in *step mode*; each
  step then counts as ``seconds_per_step`` seconds of flight.

:func:`mission_viewer` renders the track as a CZML document on a Cesium
``Viewer``: a grey planned-route polyline, small waypoint pins, and a
drone point entity that flies the samples with an orange trail, its
label following the ACTIVE STATE name through the mission (CZML interval
text -- the state machine is visibly driving the animation).  The camera
tracks the drone with an offset sized from the route (CZML ``viewFrom``).
Cesium's native timeline + animation dial are the mission-playback UI
(play/pause/scrub); the chrome that needs Cesium ion (base-layer picker,
geocoder) stays off.  Clicking the drone (or any mission entity) reports
its CZML id on the ``picked_json`` trait -- the same pick seam as
:mod:`longeron.analysis.viewer3d` -- and the bidirectional ``time`` trait
(seconds past the track epoch) lets kernel code scrub or follow the
playhead.  The stage keeps a fixed explicit height (``height_px``,
default 480) at 98% width, so it never overflows a notebook cell or the
sidebar.

No Cesium ion token is required: the default globe is OpenStreetMap
tiles on the plain WGS84 ellipsoid, both tokenless.  Passing
``ion_token=`` upgrades to Cesium World Terrain + imagery.

Offline tradeoff: the front-end loads CesiumJS (~6 MB plus workers and
assets) from the pinned jsDelivr CDN at view time -- the same judgment
as :mod:`longeron.analysis.viewer3d`'s three.js (~630 kB was already too
big to vendor; Cesium is ~10x that, a fortiori).  On an offline
front-end the widget degrades to a printed notice instead of a globe,
and a later re-render retries the load.  This is also why there is no
browser-tier test for this widget: rendering truth would hard-depend on
live CDN access (see ``tests/test_mission3d.py``).

Requires the ``viz`` extra for anywidget:
``pip install "longeron[viz]"``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from ..errors import MissingExtraError, SysMLError
from ._expr import AnalysisError

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import anywidget

    from .. import model as M
    from ..interpreter import Interpreter
    from ..replay import Timeline

__all__ = [
    "CESIUM_BASE_URL",
    "CESIUM_CSS_URL",
    "CESIUM_JS_URL",
    "CESIUM_VERSION",
    "MissionTrack",
    "from_replay",
    "mission_track",
    "mission_viewer",
    "model_waypoints",
]

#: pinned CDN release (monthly Cesium train); bump deliberately, with the
#: evidence capture re-run -- never float a `latest` tag
CESIUM_VERSION = "1.144.0"
#: workers/assets/widgets resolve against this base (window.CESIUM_BASE_URL)
CESIUM_BASE_URL = f"https://cdn.jsdelivr.net/npm/cesium@{CESIUM_VERSION}/Build/Cesium/"
CESIUM_JS_URL = CESIUM_BASE_URL + "Cesium.js"
CESIUM_CSS_URL = CESIUM_BASE_URL + "Widgets/widgets.css"

#: deterministic default epoch (identical CZML across runs; midday UTC
#: lights the default camera view) -- pass ``epoch=`` for real dates
_DEFAULT_EPOCH = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

_EARTH_RADIUS_M = 6_371_008.8

# state-name substring hints -> motion phase, checked in order (takeoff
# before ground, so "takingOff" never matches the "off" ground hint)
_PHASE_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("takingoff", "takeoff", "launch", "liftoff", "ascend", "climb"), "takeoff"),
    (("landing", "land", "descen", "touchdown", "recover", "rtl", "return"), "landing"),
    (
        (
            "fly",
            "cruise",
            "transit",
            "enroute",
            "route",
            "ingress",
            "egress",
            "loiter",
            "hover",
            "survey",
            "station",
            "search",
            "orbit",
            "patrol",
        ),
        "route",
    ),
    (("idle", "ground", "standby", "parked", "stowed", "charging", "off"), "ground"),
)


# ---------------------------------------------------------------------------
# track synthesis
# ---------------------------------------------------------------------------


@dataclass
class MissionTrack:
    """A timestamped geodetic flight path synthesized from the model.

    ``samples`` are ``(t, lat, lon, alt)`` keyframes (seconds past
    ``epoch``, degrees, meters above the ellipsoid) with strictly
    increasing times; ``waypoints`` is the planned route the samples fly;
    ``phases`` records the motion segments as ``(t0, t1, phase, qname)``
    -- for replay-built tracks ``qname`` is the instance-qualified name
    of the driving leaf state (empty for plain waypoint tracks).
    """

    name: str
    epoch: datetime
    samples: list[tuple[float, float, float, float]]
    waypoints: list[tuple[float, float, float]]
    phases: list[tuple[float, float, str, str]]

    @property
    def duration(self) -> float:
        """Track length in seconds (the last phase end / sample time)."""

        if self.phases:
            return self.phases[-1][1]
        return self.samples[-1][0] if self.samples else 0.0

    def to_czml(self) -> list[dict[str, Any]]:
        """The CZML document the widget plays.

        Packets: a document packet whose clock spans the mission
        (CLAMPED, multiplier sized so playback takes ~40 s of wall
        clock), the planned-route polyline, one pin per waypoint, and
        the ``mission-drone`` entity -- sampled positions with linear
        interpolation, an orange trail, a ``viewFrom`` camera offset
        sized from the route span, and a label whose text follows the
        active state name through the phases.
        """

        if len(self.samples) < 2:
            raise AnalysisError("a mission track needs at least two samples")
        if self.duration <= 0:
            raise AnalysisError("a mission track needs a positive duration")
        start = _iso(self.epoch)
        stop = _iso(self.epoch + timedelta(seconds=self.duration))
        availability = f"{start}/{stop}"
        packets: list[dict[str, Any]] = [
            {
                "id": "document",
                "name": self.name,
                "version": "1.0",
                "clock": {
                    "interval": availability,
                    "currentTime": start,
                    "multiplier": max(1, round(self.duration / 40.0)),
                    "range": "CLAMPED",
                    "step": "SYSTEM_CLOCK_MULTIPLIER",
                },
            }
        ]
        if len(self.waypoints) >= 2:
            route: list[float] = []
            for lat, lon, alt in self.waypoints:
                route.extend((round(lon, 6), round(lat, 6), round(alt, 2)))
            packets.append(
                {
                    "id": "mission-route",
                    "name": f"{self.name} route",
                    "polyline": {
                        "positions": {"cartographicDegrees": route},
                        "width": 2,
                        "material": {"solidColor": {"color": {"rgba": [138, 143, 152, 200]}}},
                        "arcType": "GEODESIC",
                    },
                }
            )
        for index, (lat, lon, alt) in enumerate(self.waypoints):
            packets.append(
                {
                    "id": f"waypoint-{index}",
                    "name": f"WP{index}",
                    "position": {
                        "cartographicDegrees": [round(lon, 6), round(lat, 6), round(alt, 2)]
                    },
                    "point": {
                        "pixelSize": 5,
                        "color": {"rgba": [90, 95, 104, 255]},
                        "outlineColor": {"rgba": [255, 255, 255, 255]},
                        "outlineWidth": 1,
                    },
                    "label": {
                        "text": f"WP{index}",
                        "font": "10px Helvetica, Arial, sans-serif",
                        "pixelOffset": {"cartesian2": [0, -12]},
                        "fillColor": {"rgba": [255, 255, 255, 235]},
                        "outlineColor": {"rgba": [11, 21, 34, 235]},
                        "outlineWidth": 2,
                        "style": "FILL_AND_OUTLINE",
                        "verticalOrigin": "BOTTOM",
                    },
                }
            )
        positions: list[float] = []
        for t, lat, lon, alt in self.samples:
            positions.extend((round(t, 3), round(lon, 6), round(lat, 6), round(alt, 2)))
        offset = self._camera_offset_m()
        packets.append(
            {
                "id": "mission-drone",
                "name": self.name,
                "availability": availability,
                # camera offset for tracked-entity mode: behind (south of)
                # and above the drone, sized from the route span (ENU meters)
                "viewFrom": {
                    "cartesian": [
                        round(-0.4 * offset),
                        round(-offset),
                        round(0.45 * offset),
                    ]
                },
                "position": {
                    "epoch": start,
                    "cartographicDegrees": positions,
                    "interpolationAlgorithm": "LAGRANGE",
                    "interpolationDegree": 1,
                },
                "point": {
                    "pixelSize": 10,
                    "color": {"rgba": [63, 122, 31, 255]},  # the replay active green
                    "outlineColor": {"rgba": [255, 255, 255, 255]},
                    "outlineWidth": 2,
                },
                "path": {
                    "leadTime": 0,
                    "trailTime": round(self.duration, 3),
                    "width": 2.5,
                    "material": {
                        # the replay fired orange: the trail is what has happened
                        "solidColor": {"color": {"rgba": [224, 90, 0, 200]}}
                    },
                },
                "label": {
                    "text": self._label_text(),
                    "font": "12px Helvetica, Arial, sans-serif",
                    "pixelOffset": {"cartesian2": [0, -16]},
                    "fillColor": {"rgba": [255, 255, 255, 235]},
                    "outlineColor": {"rgba": [11, 21, 34, 235]},
                    "outlineWidth": 3,
                    "style": "FILL_AND_OUTLINE",
                    "verticalOrigin": "BOTTOM",
                },
            }
        )
        return packets

    def _label_text(self) -> str | list[dict[str, str]]:
        """The drone label: interval text following the active state
        name for replay-built tracks, the static name otherwise."""

        if not any(qname for *_span, qname in self.phases):
            return self.name
        intervals: list[dict[str, str]] = []
        for t0, t1, phase, qname in self.phases:
            leaf = qname.rsplit("::", 1)[-1] if qname else phase
            intervals.append(
                {
                    "interval": (
                        f"{_iso(self.epoch + timedelta(seconds=t0))}/"
                        f"{_iso(self.epoch + timedelta(seconds=t1))}"
                    ),
                    "string": leaf,
                }
            )
        return intervals

    def _camera_offset_m(self) -> float:
        """A tracked-camera range that frames the whole route."""

        lats = [lat for _t, lat, _lon, _alt in self.samples]
        lons = [lon for _t, _lat, lon, _alt in self.samples]
        alts = [alt for _t, _lat, _lon, alt in self.samples]
        mid = math.radians((min(lats) + max(lats)) / 2)
        dx = (max(lons) - min(lons)) * 111_320.0 * math.cos(mid)
        dy = (max(lats) - min(lats)) * 110_540.0
        span = max(math.hypot(dx, dy), max(alts) - min(alts))
        return min(80_000.0, max(400.0, 1.6 * span))


def _iso(when: datetime) -> str:
    """ISO-8601 in UTC with a Z suffix (CZML's time format)."""

    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _haversine_m(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle distance in meters (mean-radius haversine)."""

    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_phi = phi_b - phi_a
    d_lam = math.radians(lon_b - lon_a)
    h = math.sin(d_phi / 2) ** 2 + math.cos(phi_a) * math.cos(phi_b) * math.sin(d_lam / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _leg_length_m(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    """3D leg length: great-circle horizontal plus altitude change."""

    return math.hypot(_haversine_m(a[0], a[1], b[0], b[1]), b[2] - a[2])


def _parse_waypoints(
    waypoints: Sequence[Sequence[float]],
    *,
    minimum: int,
    allow_times: bool,
) -> tuple[list[tuple[float, float, float]], list[float] | None]:
    """Validated ``(lat, lon, alt)`` points plus explicit times, if any."""

    points: list[tuple[float, float, float]] = []
    times: list[float] = []
    entries = [tuple(float(value) for value in entry) for entry in waypoints]
    if len(entries) < minimum:
        raise AnalysisError(f"a mission needs at least {minimum} waypoints (got {len(entries)})")
    for index, entry in enumerate(entries):
        if len(entry) not in (3, 4):
            raise AnalysisError(
                f"waypoint {index} must be (lat, lon, alt) or (lat, lon, alt, t): got {entry!r}"
            )
        lat, lon, alt = entry[0], entry[1], entry[2]
        if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
            raise AnalysisError(f"waypoint {index} is off the globe: lat={lat!r}, lon={lon!r}")
        points.append((lat, lon, alt))
        if len(entry) == 4:
            if not allow_times:
                raise AnalysisError(
                    f"waypoint {index} carries a time, but replay timing comes from "
                    "the state machine: pass (lat, lon, alt) waypoints to from_replay"
                )
            times.append(entry[3])
    if not times:
        return points, None
    if len(times) != len(points):
        raise AnalysisError("either every waypoint carries a time or none does")
    if any(t1 - t0 <= 0 for t0, t1 in pairwise(times)):
        raise AnalysisError("waypoint times must be strictly increasing")
    return points, times


def mission_track(
    waypoints: Sequence[Sequence[float]],
    *,
    speed_mps: float = 12.0,
    epoch: datetime | None = None,
    name: str = "mission",
) -> MissionTrack:
    """A track that flies explicit waypoints, one route phase.

    ``waypoints`` are ``(lat, lon, alt)`` or ``(lat, lon, alt, t)``
    tuples (degrees, meters above the ellipsoid, seconds past
    ``epoch``); either every waypoint carries a time or none does, in
    which case times derive from ``speed_mps`` over the 3D leg lengths.
    ``epoch`` defaults to a fixed instant so the CZML is deterministic.
    """

    points, times = _parse_waypoints(waypoints, minimum=2, allow_times=True)
    if times is None:
        if speed_mps <= 0:
            raise AnalysisError(f"speed_mps must be positive (got {speed_mps!r})")
        times = [0.0]
        for a, b in pairwise(points):
            # a zero-length leg still needs a strictly increasing clock
            times.append(times[-1] + max(_leg_length_m(a, b) / speed_mps, 1e-3))
    samples = [(t, lat, lon, alt) for t, (lat, lon, alt) in zip(times, points, strict=True)]
    return MissionTrack(
        name=name,
        epoch=epoch if epoch is not None else _DEFAULT_EPOCH,
        samples=samples,
        waypoints=points,
        phases=[(times[0], times[-1], "route", "")],
    )


def model_waypoints(
    interpreter: Interpreter,
    mission: str | M.Definition | M.Usage,
    *,
    lat: str = "lat",
    lon: str = "lon",
    alt: str = "alt",
    time: str = "t",
) -> list[tuple[float, ...]]:
    """Waypoints read off the model: ``mission``'s child parts that
    carry ``lat``/``lon`` attributes, evaluated through the interpreter
    in declaration order (``alt`` defaults to 0 where absent; an
    optional ``time`` attribute becomes the explicit timestamp)."""

    target = interpreter.resolver.resolve(mission) if isinstance(mission, str) else mission
    waypoints: list[tuple[float, ...]] = []
    for member in getattr(target, "members", []):
        names = {child.name for child in getattr(member, "members", [])}
        if lat not in names or lon not in names:
            continue
        try:
            entry = [
                float(interpreter.evaluate(lat, context=member)),
                float(interpreter.evaluate(lon, context=member)),
                float(interpreter.evaluate(alt, context=member)) if alt in names else 0.0,
            ]
            if time in names:
                entry.append(float(interpreter.evaluate(time, context=member)))
        except (SysMLError, TypeError, ValueError) as err:
            raise AnalysisError(
                f"waypoint {member.qualified_name or member.label!r} did not "
                f"evaluate to numbers: {err}"
            ) from err
        waypoints.append(tuple(entry))
    if not waypoints:
        label = mission if isinstance(mission, str) else (mission.qualified_name or mission.label)
        raise AnalysisError(
            f"{label!r} has no waypoint children (parts with {lat!r}/{lon!r} attributes)"
        )
    return waypoints


def _classify(qname: str, overrides: Mapping[str, str] | None) -> str:
    """The motion phase for a leaf state, by name hints or override."""

    leaf = qname.rsplit("::", 1)[-1]
    if overrides and leaf in overrides:
        return overrides[leaf]
    low = leaf.lower()
    for hints, phase in _PHASE_RULES:
        if any(hint in low for hint in hints):
            return phase
    return "hold"


def _leaf_segments(timeline: Timeline, seconds_per_step: float) -> list[tuple[float, float, str]]:
    """The ordered, non-overlapping leaf-state activation segments.

    Composite states (anything recorded as a parent) are dropped; in
    parallel regions the earliest-activated leaf wins and later
    overlapping intervals are clipped to keep one motion driver at a
    time.  Step-mode timelines scale the step axis by
    ``seconds_per_step``.
    """

    scale = seconds_per_step if timeline.step_mode else 1.0
    axis_end = float(max(timeline.n_steps - 1, 0)) if timeline.step_mode else timeline.t_end
    composites = set(timeline.parents.values())
    intervals: list[tuple[float, float, str]] = []
    for qname, keyframes in timeline.tracks.items():
        if qname in composites:
            continue
        on: float | None = None
        for key, active in keyframes:
            if active and on is None:
                on = key
            elif not active and on is not None:
                intervals.append((on * scale, key * scale, qname))
                on = None
        if on is not None:
            intervals.append((on * scale, axis_end * scale, qname))
    intervals.sort()
    segments: list[tuple[float, float, str]] = []
    cursor = 0.0
    for t0, t1, qname in intervals:
        start = max(t0, cursor)
        if t1 <= start:  # zero-duration flip or fully shadowed (parallel)
            continue
        segments.append((start, t1, qname))
        cursor = t1
    return segments


def from_replay(
    interpreter: Interpreter,
    state_machine: str | M.Definition | M.Usage,
    events: list[Any] | None = None,
    *,
    waypoints: Sequence[Sequence[float]],
    inputs: dict[str, Any] | None = None,
    phases: Mapping[str, str] | None = None,
    ground_alt: float = 0.0,
    seconds_per_step: float = 10.0,
    epoch: datetime | None = None,
    name: str | None = None,
) -> MissionTrack:
    """A track driven by the state machine's ACTUAL execution.

    Simulates ``state_machine`` with ``events`` (the
    ``Interpreter.simulate`` protocol: event names or ``(name,
    payload)`` tuples, plain numbers advance the clock) via
    :func:`longeron.replay.record_timeline`, then maps every leaf
    state's activation interval onto a motion segment along
    ``waypoints`` -- see the module docstring for the phase table and
    ``phases=`` for per-state-name overrides.  ``waypoints`` are
    ``(lat, lon, alt)`` tuples (no times -- timing comes from the
    machine); the mission starts at the first waypoint at
    ``ground_alt``.  Pure event cascades (step mode) count each step as
    ``seconds_per_step`` seconds.
    """

    from ..replay import record_timeline  # imports interpreter+render; keep module import light

    points, _times = _parse_waypoints(waypoints, minimum=1, allow_times=False)
    timeline = record_timeline(interpreter, state_machine, events, inputs=inputs)
    segments = _leaf_segments(timeline, seconds_per_step)
    if not segments:
        raise AnalysisError(
            "the replay recorded no state activity with duration: nothing to animate "
            "(did the event list advance the clock, or is the machine a pure cascade "
            "with a single step?)"
        )
    classified = [(t0, t1, _classify(qname, phases), qname) for t0, t1, qname in segments]
    route_time = sum(t1 - t0 for t0, t1, phase, _qname in classified if phase == "route")

    legs: list[tuple[float, float, tuple[float, float, float], tuple[float, float, float]]] = []
    cum = 0.0
    for a, b in pairwise(points):
        length = _leg_length_m(a, b)
        if length <= 0:
            continue
        legs.append((cum, length, a, b))
        cum += length
    total_length = cum

    def route_point(dist: float) -> tuple[float, float, float]:
        if not legs:
            return points[0]
        d = min(max(dist, 0.0), total_length)
        for cum0, length, a, b in legs:
            if d <= cum0 + length:
                f = (d - cum0) / length
                return (
                    a[0] + f * (b[0] - a[0]),
                    a[1] + f * (b[1] - a[1]),
                    a[2] + f * (b[2] - a[2]),
                )
        return points[-1]

    samples: list[tuple[float, float, float, float]] = []

    def append(t: float, position: tuple[float, float, float]) -> None:
        # strictly increasing times; a same-instant update keeps the
        # latest position (mirrors replay's same-instant flip handling)
        lat, lon, alt = position
        if samples and t <= samples[-1][0] + 1e-9:
            samples[-1] = (samples[-1][0], lat, lon, alt)
            return
        samples.append((t, lat, lon, alt))

    position = (points[0][0], points[0][1], ground_alt)
    route_cursor = 0.0
    phase_records: list[tuple[float, float, str, str]] = []
    for t0, t1, phase, qname in classified:
        if phase == "takeoff":
            append(t0, position)
            position = (position[0], position[1], route_point(route_cursor)[2])
            append(t1, position)
        elif phase == "landing":
            append(t0, position)
            position = (position[0], position[1], ground_alt)
            append(t1, position)
        elif phase == "route" and route_time > 0 and total_length > 0:
            d0 = route_cursor
            d1 = min(total_length, d0 + total_length * ((t1 - t0) / route_time))
            if total_length - d1 < 1e-6:
                d1 = total_length
            append(t0, route_point(d0))
            for cum0, _length, _a, _b in legs:  # waypoint crossings inside the span
                if d0 < cum0 < d1:
                    append(t0 + (t1 - t0) * (cum0 - d0) / (d1 - d0), route_point(cum0))
            position = route_point(d1)
            append(t1, position)
            route_cursor = d1
        else:  # ground / hold / route with nowhere to go
            append(t0, position)
            append(t1, position)
        phase_records.append((t0, t1, phase, qname))

    if name is None:  # default to the machine's own name
        target = (
            interpreter.resolver.resolve(state_machine)
            if isinstance(state_machine, str)
            else state_machine
        )
        name = getattr(target, "name", None) or "mission"
    return MissionTrack(
        name=name,
        epoch=epoch if epoch is not None else _DEFAULT_EPOCH,
        samples=samples,
        waypoints=points,
        phases=phase_records,
    )


# ---------------------------------------------------------------------------
# anywidget front-end (vanilla JS, no bundler)
# ---------------------------------------------------------------------------

# Conventions per viewer3d/replay: the DOM is built once, Python bakes the
# whole payload (the CZML document) into a JSON traitlet, and the front-end
# only plays it.  Cesium ships no single-file ESM build, so the pinned IIFE
# bundle is injected as a classic <script> (plus its widgets.css) with the
# load promise cached on `window` -- many viewers share one ~6 MB load, and
# a failed load clears the cache so a later render can retry.
_ESM = (
    r"""
async function loadCesium() {
  if (window.Cesium) return window.Cesium;
  if (!window._longeronCesiumLoad) {
    window.CESIUM_BASE_URL = "%CESIUM_BASE_URL%";
    if (!document.querySelector("link[data-longeron-cesium]")) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "%CESIUM_CSS_URL%";
      link.setAttribute("data-longeron-cesium", "1");
      document.head.appendChild(link);
    }
    window._longeronCesiumLoad = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "%CESIUM_JS_URL%";
      script.onload = () => resolve();
      script.onerror = () => {
        delete window._longeronCesiumLoad;  // let a later render retry
        script.remove();
        reject(new Error("CesiumJS failed to load"));
      };
      document.head.appendChild(script);
    });
  }
  await window._longeronCesiumLoad;
  return window.Cesium;
}

async function render({ model, el }) {
  el.classList.add("longeron-mission3d");
  el.innerHTML = "";
  let Cesium;
  try {
    Cesium = await loadCesium();
  } catch (err) {
    const note = document.createElement("div");
    note.className = "longeron-mission3d-offline";
    note.textContent = "Mission view unavailable: CesiumJS could not " +
      "be loaded from the CDN (offline front-end?).";
    el.appendChild(note);
    return;
  }

  const stage = document.createElement("div");
  stage.className = "longeron-mission3d-stage";
  stage.style.height = model.get("height_px") + "px";
  const caption = document.createElement("div");
  caption.className = "longeron-mission3d-caption";
  el.append(stage, caption);

  // no ion token required: the default globe is OpenStreetMap tiles on
  // the plain WGS84 ellipsoid (both tokenless); a token upgrades to
  // Cesium World Terrain + imagery.  The ion-backed chrome (base-layer
  // picker, geocoder) stays off either way -- the timeline + animation
  // dial ARE the mission-playback UI.
  const token = model.get("ion_token");
  if (token) Cesium.Ion.defaultAccessToken = token;
  const options = {
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    animation: true,
    timeline: true,
    shouldAnimate: false,
    requestRenderMode: true,       // an idle globe costs nothing...
    maximumRenderTimeChange: 0.0,  // ...but every clock tick paints
  };
  if (token) {
    options.baseLayer = Cesium.ImageryLayer.fromWorldImagery();
    options.terrain = Cesium.Terrain.fromWorldTerrain();
  } else {
    options.baseLayer = new Cesium.ImageryLayer(
      new Cesium.OpenStreetMapImageryProvider(
        { url: "https://tile.openstreetmap.org/" }));
  }
  const viewer = new Cesium.Viewer(stage, options);

  const hint = document.createElement("div");
  hint.className = "longeron-mission3d-hint";
  hint.textContent = "\u25b6 plays the mission \u00b7 drag the timeline " +
    "to scrub \u00b7 click the drone to pick";
  stage.appendChild(hint);

  async function load() {
    viewer.trackedEntity = undefined;
    viewer.dataSources.removeAll(true);
    let packets;
    try { packets = JSON.parse(model.get("czml_json") || "[]"); }
    catch (err) { packets = []; }
    if (!packets.length) return;
    const source = await viewer.dataSources.add(
      Cesium.CzmlDataSource.load(packets));
    // the camera follows the drone; the CZML viewFrom sets the offset
    viewer.trackedEntity = source.entities.getById("mission-drone");
    viewer.timeline.zoomTo(viewer.clock.startTime, viewer.clock.stopTime);
    viewer.scene.requestRender();
  }

  // --- playhead sync: `time` is seconds past the track epoch; the
  // front-end writes ~4 Hz while the clock animates, Python writes seek
  const seconds = () => Cesium.JulianDate.secondsDifference(
    viewer.clock.currentTime, viewer.clock.startTime);
  let lastSync = 0;
  const unTick = viewer.clock.onTick.addEventListener(() => {
    const now = performance.now();
    if (now - lastSync < 250) return;
    lastSync = now;
    const s = seconds();
    if (Math.abs(s - model.get("time")) > 1e-3) {
      model.set("time", s);
      model.save_changes();
    }
  });
  model.on("change:time", () => {
    const value = model.get("time");
    if (Math.abs(value - seconds()) < 1e-3) return;  // echo of our set
    viewer.clock.currentTime = Cesium.JulianDate.addSeconds(
      viewer.clock.startTime, value, new Cesium.JulianDate());
    viewer.scene.requestRender();
  });

  // --- picking: a click reports the hit entity's CZML id on
  // picked_json (the same pick seam as viewer3d.picked_json)
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((movement) => {
    const hit = viewer.scene.pick(movement.position);
    const id = hit && hit.id && hit.id.id;
    model.set("picked_json", JSON.stringify(id ? [String(id)] : []));
    model.save_changes();
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  function recaption() {
    caption.textContent = model.get("label");
    caption.style.display = model.get("label") ? "" : "none";
  }
  model.on("change:label", recaption);
  model.on("change:czml_json", load);
  model.on("change:height_px", () => {
    stage.style.height = model.get("height_px") + "px";
    viewer.scene.requestRender();
  });
  recaption();
  await load();
  return () => { unTick(); handler.destroy(); viewer.destroy(); };
}
export default { render };
""".replace("%CESIUM_BASE_URL%", CESIUM_BASE_URL)
    .replace("%CESIUM_CSS_URL%", CESIUM_CSS_URL)
    .replace("%CESIUM_JS_URL%", CESIUM_JS_URL)
)

# 98%-width stage with an explicit fixed height: Cesium's own chrome
# (timeline, animation dial, credits) lives INSIDE the container, so the
# widget never overflows a notebook cell or the sidebar.
_CSS = """
.longeron-mission3d { font-family: Helvetica, Arial, sans-serif; }
.longeron-mission3d-stage {
  width: 98%; box-sizing: border-box; position: relative;
  border: 1px solid #e2e2e2; border-radius: 8px; overflow: hidden;
  background: #0b1522;
}
.longeron-mission3d-hint {
  position: absolute; right: 8px; top: 6px; font-size: 10px;
  color: #d5d9de; background: rgba(11, 21, 34, 0.55);
  padding: 2px 8px; border-radius: 9px; pointer-events: none;
  user-select: none; z-index: 1;
}
.longeron-mission3d-caption {
  margin-top: 6px; font-size: 12px; color: #555555;
  font-variant-numeric: tabular-nums;
}
.longeron-mission3d-offline {
  border: 1px dashed #d4d4d4; border-radius: 8px; padding: 14px;
  font-size: 12px; color: #777777;
}
"""

_VIEWER_CLS: type[anywidget.AnyWidget] | None = None


def _viewer_class() -> type[anywidget.AnyWidget]:
    """Define MissionViewer lazily -- anywidget is an optional extra."""

    global _VIEWER_CLS
    if _VIEWER_CLS is not None:
        return _VIEWER_CLS
    try:
        import anywidget as _anywidget
        import traitlets
    except ImportError as err:
        raise MissingExtraError("the mission viewer", "anywidget", "viz") from err

    class MissionViewer(_anywidget.AnyWidget):
        """CesiumJS playback of a MissionTrack's CZML document."""

        _esm = _ESM
        _css = _CSS
        #: the baked CZML document (JSON text); assign to swap missions
        czml_json = traitlets.Unicode("").tag(sync=True)
        label = traitlets.Unicode("").tag(sync=True)
        #: fixed stage height (the width fills 98% of the host)
        height_px = traitlets.Int(480).tag(sync=True)
        #: optional Cesium ion token (world terrain/imagery); applied at
        #: render time -- set it before displaying the widget
        ion_token = traitlets.Unicode("").tag(sync=True)
        #: JSON array with the CZML id of the last clicked entity
        #: ("[]" for a background click); written by the front-end
        picked_json = traitlets.Unicode("[]").tag(sync=True)
        #: bidirectional playhead, seconds past the track epoch
        time = traitlets.Float(0.0).tag(sync=True)

    _VIEWER_CLS = MissionViewer
    return MissionViewer


def mission_viewer(
    track: MissionTrack,
    *,
    label: str | None = None,
    height_px: int = 480,
    ion_token: str = "",
) -> anywidget.AnyWidget:
    """Fly ``track`` on a Cesium globe in the notebook.

    The viewer starts paused at the track epoch with the camera
    tracking the drone; Cesium's native timeline and animation dial
    play, pause, scrub, and re-speed the mission.  Click the drone (or
    a waypoint pin) to report its CZML id on ``picked_json``; drive or
    observe the playhead through the bidirectional ``time`` trait.  No
    Cesium ion token is needed for the default OpenStreetMap globe;
    pass ``ion_token`` to upgrade to Cesium World Terrain + imagery.
    Assign a new JSON string to ``czml_json`` to swap the mission in
    place.
    """

    cls = _viewer_class()
    return cls(
        czml_json=json.dumps(track.to_czml()),
        label=track.name if label is None else label,
        height_px=height_px,
        ion_token=ion_token,
    )
