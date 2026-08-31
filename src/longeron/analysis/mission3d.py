"""Mission flight tracks for the CesiumJS globe: synthesis and CZML baking.

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
  state's activation interval becomes one motion segment.
  :func:`track_from_timeline` is the same synthesis over an EXISTING
  :class:`~longeron.replay.Timeline`, so one recording can feed the
  diagram replay, the globe, and the time seam's scrubber without
  re-simulating (see :mod:`longeron.widgets.time`).  The mapping
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
  step then counts as ``seconds_per_step`` seconds of flight --  a
  scalar, or a per-step sequence/mapping when steps take unequal
  durations (:func:`longeron.widgets.time.step_seconds` states the
  exact ladder).

The trace-to-mission binding can ride the model itself:
:func:`model_waypoints` reads the route off a mission part's children,
and :func:`model_epoch` reads the mission epoch off an attribute typed
``Time::Iso8601DateTime`` (vendored; resolves), so the model states
WHERE and WHEN the sortie flies.  Both fall back honestly: no epoch
attribute means the deterministic default epoch.

:meth:`MissionTrack.to_czml` bakes the track as a CZML document: a
grey planned-route polyline, small waypoint pins, and a drone entity
that flies the samples with an orange trail, its label following the
ACTIVE STATE name through the mission (CZML interval text -- the state
machine is visibly driving the animation).  Pass the
drone's own analysis mesh (``mesh=``, the dict
:func:`longeron.analysis.geometry.drone_geometry` and its siblings
build) and the ACTUAL airframe geometry flies the route: the mesh
exports to a self-contained binary glTF through :func:`mesh_to_glb`
(in-house, stdlib-only -- see :mod:`longeron.analysis._glb` for the
exact container), embeds in the CZML as a ``data:`` URI (tens of kB for
the quad), flies with a MULTIROTOR ATTITUDE, and never shrinks below a
legible pixel size however far the camera sits; ``model_scale`` blows it
up beyond true scale when the route dwarfs the airframe.  Without a mesh
the drone stays the point entity.

Attitude: a multirotor moves vertically props-up and cruises with a
small forward tilt -- Cesium's ``VelocityOrientationProperty`` (which
points the nose along the velocity vector, so a climb renders the quad
VERTICAL) is deliberately NOT used.  Instead the track bakes a sampled
orientation into the CZML (``unitQuaternion`` keyframes, computed by
:meth:`MissionTrack.attitude`): yaw follows the track heading, pitch is
0 wherever there is no horizontal motion (climb, descent, hover,
ground) and the ``tilt_deg`` forward tilt while the drone advances
along the route, roll stays 0, and orientation changes blend over a few
seconds (Cesium slerps between adjacent quaternion samples).  A
CZML-sampled property is chosen over a front-end ``CallbackProperty``
because the module's whole design bakes the payload kernel-side: the
samples are deterministic, testable without a browser, and need no
front-end code.  The tilt itself should come FROM THE MODEL:
:func:`model_tilt` evaluates the airframe's own physics (e.g.
the DeepScout MultiRotor's ``cruiseTilt``: the arccos altitude-hold
ceiling at continuous thrust, capped by the operational comfort limit)
and feeds ``mission_track`` / ``from_replay`` ``tilt_deg=``, a plain
float override.  :func:`mission_values` completes the loop: it measures
the route's waypoint legs and evaluates the model's ``MissionTime``
calc at the model's own achievable cruise speed, producing the
scoreboard ``values=`` bindings for the mission-time requirement.

The viewer widget itself --
:func:`~longeron.widgets.mission3d.mission_viewer`, which plays the
baked CZML on a Cesium ``Viewer`` -- lives in
:mod:`longeron.widgets.mission3d`: this module is the kernel-side
synthesis, deterministic and testable without a browser.  Importing
``mission_viewer`` (or the ``CESIUM_*`` CDN pins) from here still
works but is deprecated.
"""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import TYPE_CHECKING, Any

from ..errors import SysMLError
from ._expr import AnalysisError
from ._glb import mesh_to_glb

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .. import model as M
    from ..interpreter import Interpreter
    from ..replay import Timeline

__all__ = [
    "MissionTrack",
    "from_replay",
    "mesh_to_glb",
    "mission_track",
    "mission_values",
    "model_epoch",
    "model_tilt",
    "model_waypoints",
    "track_from_timeline",
]

#: names that moved to :mod:`longeron.widgets.mission3d`; forwarded with
#: a DeprecationWarning by module ``__getattr__``
_MOVED = (
    "mission_viewer",
    "CESIUM_VERSION",
    "CESIUM_BASE_URL",
    "CESIUM_JS_URL",
    "CESIUM_CSS_URL",
    "_viewer_class",
    "_IMAGERY_BASES",
    "_ESM",
    "_CSS",
)


def __getattr__(name: str) -> Any:
    if name in _MOVED:
        import warnings

        warnings.warn(
            f"longeron.analysis.mission3d.{name} moved to "
            f"longeron.widgets.mission3d.{name}; the longeron.analysis.mission3d "
            "alias will be removed in a future release",
            DeprecationWarning,
            stacklevel=2,
        )
        from ..widgets import mission3d as _home

        return getattr(_home, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


#: the drone model never shrinks below this on-screen size, so it stays
#: findable with the camera zoomed out to frame the whole route
_MODEL_MIN_PIXELS = 48

#: deterministic default epoch (identical CZML across runs; midday UTC
#: lights the default camera view) -- pass ``epoch=`` for real dates
_DEFAULT_EPOCH = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

_EARTH_RADIUS_M = 6_371_008.8

#: orientation changes blend over this many seconds (half before the
#: motion change, half after) -- a multirotor takes a moment to rotate
_ATTITUDE_BLEND_S = 3.0

#: horizontal ground speed below this is a vertical/hover motion
#: segment: props level, heading held (m/s)
_ATTITUDE_MOVING_MPS = 0.2

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
    of the driving leaf state (empty for plain waypoint tracks);
    ``tilt_deg`` is the forward cruise tilt the airframe holds while it
    moves along the route (degrees nose-down; ideally the MODEL's own
    number -- see :func:`model_tilt`).
    """

    name: str
    epoch: datetime
    samples: list[tuple[float, float, float, float]]
    waypoints: list[tuple[float, float, float]]
    phases: list[tuple[float, float, str, str]]
    tilt_deg: float = 0.0

    @property
    def duration(self) -> float:
        """Track length in seconds (the last phase end / sample time)."""

        if self.phases:
            return self.phases[-1][1]
        return self.samples[-1][0] if self.samples else 0.0

    def to_czml(
        self, *, mesh: Mapping[str, Any] | None = None, model_scale: float = 1.0
    ) -> list[dict[str, Any]]:
        """The CZML document the widget plays.

        Packets: a document packet whose clock spans the mission
        (CLAMPED, multiplier sized so playback takes ~40 s of wall
        clock), the planned-route polyline, one pin per waypoint, and
        the ``mission-drone`` entity -- sampled positions with linear
        interpolation, an orange trail, a ``viewFrom`` camera offset
        sized from the route span, and a label whose text follows the
        active state name through the phases.  With ``mesh`` (a
        geometry-module mesh dict) the drone entity is the airframe's
        own glTF model -- :func:`mesh_to_glb` output on a ``data:``
        URI, nose steered along the track heading with the multirotor
        attitude (see :meth:`attitude`), scaled by ``model_scale`` and
        clamped to a legible minimum pixel size -- instead of the
        fallback point.
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
        drone: dict[str, Any] = {
            "id": "mission-drone",
            "name": self.name,
            "availability": availability,
            # camera offset for tracked-entity mode: behind and above the
            # drone, sized from the route span (with a model, the entity's
            # velocity orientation makes this a chase-camera offset)
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
        if mesh is not None:
            if model_scale <= 0:
                raise AnalysisError(f"model_scale must be positive (got {model_scale!r})")
            glb = mesh_to_glb(mesh)
            drone["model"] = {
                "gltf": "data:model/gltf-binary;base64," + base64.b64encode(glb).decode("ascii"),
                "scale": model_scale,
                "minimumPixelSize": _MODEL_MIN_PIXELS,
            }
            # the multirotor attitude, baked as sampled quaternions: yaw
            # follows the track heading, pitch 0 in vertical/hover motion
            # (props up), the model-derived forward tilt along the route,
            # roll 0; Cesium slerps between adjacent samples.  NOT a
            # velocityReference: VelocityOrientationProperty would pitch
            # the quad vertical during climb and descent.
            quaternions: list[float] = []
            previous: tuple[float, float, float, float] | None = None
            for t, heading, pitch in self.attitude():
                lat, lon = self._position_at(t)
                q = _attitude_quaternion(lat, lon, heading, pitch)
                if (
                    previous is not None
                    and sum(a * b for a, b in zip(q, previous, strict=True)) < 0.0
                ):
                    q = (-q[0], -q[1], -q[2], -q[3])  # same hemisphere: short-way slerp
                previous = q
                quaternions.append(round(t, 3))
                quaternions.extend(round(component, 6) for component in q)
            drone["orientation"] = {
                "epoch": start,
                "unitQuaternion": quaternions,
                "interpolationAlgorithm": "LINEAR",
                "interpolationDegree": 1,
            }
        else:
            drone["point"] = {
                "pixelSize": 10,
                "color": {"rgba": [63, 122, 31, 255]},  # the replay active green
                "outlineColor": {"rgba": [255, 255, 255, 255]},
                "outlineWidth": 2,
            }
        packets.append(drone)
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

    def attitude(self, *, blend_s: float = _ATTITUDE_BLEND_S) -> list[tuple[float, float, float]]:
        """The orientation keyframes: ``(t, heading_deg, pitch_deg)``.

        Heading follows the track's direction of travel (great-circle
        initial bearing per motion segment, degrees clockwise from true
        north); hover/vertical segments hold the last heading flown (or
        face the first leg before anything has moved).  Pitch is 0
        wherever the drone has no horizontal motion -- a multirotor
        climbs, descends, and hovers props-up -- and ``-tilt_deg``
        (nose-down forward tilt) while it advances along the route.
        Roll is always 0.  Orientation changes blend over ``blend_s``
        seconds, half on each side of the motion change, clamped to the
        neighboring segments' midpoints so keyframe times stay strictly
        increasing.
        """

        if len(self.samples) < 2:
            raise AnalysisError("a mission track needs at least two samples")
        spans: list[list[float]] = []  # [t0, t1, heading|nan, pitch]
        for (t0, lat0, lon0, _a0), (t1, lat1, lon1, _a1) in pairwise(self.samples):
            horizontal = _haversine_m(lat0, lon0, lat1, lon1)
            if horizontal / (t1 - t0) >= _ATTITUDE_MOVING_MPS:
                heading = _initial_bearing_deg(lat0, lon0, lat1, lon1)
                pitch = -self.tilt_deg
            else:
                heading, pitch = math.nan, 0.0
            spans.append([t0, t1, heading, pitch])
        last = math.nan
        for span in spans:  # hover holds the last heading flown
            if math.isnan(span[2]):
                span[2] = last
            else:
                last = span[2]
        ahead = 0.0  # leading hovers face the first leg; a still track faces north
        for span in reversed(spans):
            if math.isnan(span[2]):
                span[2] = ahead
            else:
                ahead = span[2]
        merged = [spans[0]]
        for span in spans[1:]:  # merge same-orientation neighbors
            if span[2] == merged[-1][2] and span[3] == merged[-1][3]:
                merged[-1][1] = span[1]
            else:
                merged.append(span)
        keys: list[tuple[float, float, float]] = [(merged[0][0], merged[0][2], merged[0][3])]

        def append(t: float, heading: float, pitch: float) -> None:
            if t > keys[-1][0] + 1e-9:
                keys.append((t, heading, pitch))

        for (a0, a1, ah, ap), (b0, b1, bh, bp) in pairwise(merged):
            append(a1 - min(blend_s / 2.0, (a1 - a0) / 2.0), ah, ap)
            append(b0 + min(blend_s / 2.0, (b1 - b0) / 2.0), bh, bp)
        append(merged[-1][1], merged[-1][2], merged[-1][3])
        return keys

    def _position_at(self, t: float) -> tuple[float, float]:
        """(lat, lon) linearly interpolated on the samples at time t."""

        samples = self.samples
        if t <= samples[0][0]:
            return samples[0][1], samples[0][2]
        for (t0, lat0, lon0, _a0), (t1, lat1, lon1, _a1) in pairwise(samples):
            if t <= t1:
                f = (t - t0) / (t1 - t0)
                return lat0 + f * (lat1 - lat0), lon0 + f * (lon1 - lon0)
        return samples[-1][1], samples[-1][2]

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


def _initial_bearing_deg(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    """Great-circle initial bearing a->b, degrees clockwise from north."""

    phi_a, phi_b = math.radians(lat_a), math.radians(lat_b)
    d_lam = math.radians(lon_b - lon_a)
    x = math.sin(d_lam) * math.cos(phi_b)
    y = math.cos(phi_a) * math.sin(phi_b) - math.sin(phi_a) * math.cos(phi_b) * math.cos(d_lam)
    return math.degrees(math.atan2(x, y)) % 360.0


def _attitude_quaternion(
    lat: float, lon: float, heading_deg: float, pitch_deg: float
) -> tuple[float, float, float, float]:
    """The ECEF unit quaternion ``(x, y, z, w)`` for a zero-roll attitude.

    Rotates the entity's body axes (+X nose, +Y left, +Z top -- the
    frame Cesium gives glTF models, our GLB exporter included) into the
    Earth-fixed frame at ``lat``/``lon``: ``heading_deg`` clockwise from
    true north, ``pitch_deg`` nose-up (so a multirotor's forward tilt is
    a NEGATIVE pitch).
    """

    phi, lam = math.radians(lat), math.radians(lon)
    east = (-math.sin(lam), math.cos(lam), 0.0)
    north = (-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi))
    up = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))
    a, p = math.radians(heading_deg), math.radians(pitch_deg)
    # body axes in the local east-north-up frame (zero roll)
    nose = (math.sin(a) * math.cos(p), math.cos(a) * math.cos(p), math.sin(p))
    right = (math.cos(a), -math.sin(a), 0.0)
    top = _cross(right, nose)
    left = _cross(top, nose)

    def ecef(v: tuple[float, float, float]) -> tuple[float, float, float]:
        return (
            v[0] * east[0] + v[1] * north[0] + v[2] * up[0],
            v[0] * east[1] + v[1] * north[1] + v[2] * up[1],
            v[0] * east[2] + v[1] * north[2] + v[2] * up[2],
        )

    x_axis, y_axis, z_axis = ecef(nose), ecef(left), ecef(top)
    # rotation matrix (columns = body axes in ECEF) -> quaternion, the
    # standard trace-max branch selection for numerical stability
    m00, m01, m02 = x_axis[0], y_axis[0], z_axis[0]
    m10, m11, m12 = x_axis[1], y_axis[1], z_axis[1]
    m20, m21, m22 = x_axis[2], y_axis[2], z_axis[2]
    trace = m00 + m11 + m22
    if trace > 0.0:
        s = 2.0 * math.sqrt(trace + 1.0)
        q = ((m21 - m12) / s, (m02 - m20) / s, (m10 - m01) / s, 0.25 * s)
    elif m00 >= m11 and m00 >= m22:
        s = 2.0 * math.sqrt(1.0 + m00 - m11 - m22)
        q = (0.25 * s, (m01 + m10) / s, (m02 + m20) / s, (m21 - m12) / s)
    elif m11 >= m22:
        s = 2.0 * math.sqrt(1.0 + m11 - m00 - m22)
        q = ((m01 + m10) / s, 0.25 * s, (m12 + m21) / s, (m02 - m20) / s)
    else:
        s = 2.0 * math.sqrt(1.0 + m22 - m00 - m11)
        q = ((m02 + m20) / s, (m12 + m21) / s, 0.25 * s, (m10 - m01) / s)
    norm = math.hypot(*q)
    return (q[0] / norm, q[1] / norm, q[2] / norm, q[3] / norm)


def _cross(
    a: tuple[float, float, float], b: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


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


def _validate_tilt(tilt_deg: float) -> float:
    """A forward cruise tilt must be a sane multirotor attitude."""

    tilt = float(tilt_deg)
    if not 0.0 <= tilt < 90.0:
        raise AnalysisError(f"tilt_deg must be in [0, 90) degrees (got {tilt_deg!r})")
    return tilt


def mission_track(
    waypoints: Sequence[Sequence[float]],
    *,
    speed_mps: float = 12.0,
    tilt_deg: float = 0.0,
    epoch: datetime | None = None,
    name: str = "mission",
) -> MissionTrack:
    """A track that flies explicit waypoints, one route phase.

    ``waypoints`` are ``(lat, lon, alt)`` or ``(lat, lon, alt, t)``
    tuples (degrees, meters above the ellipsoid, seconds past
    ``epoch``); either every waypoint carries a time or none does, in
    which case times derive from ``speed_mps`` over the 3D leg lengths.
    ``tilt_deg`` is the forward cruise tilt the airframe holds along
    the route (degrees nose-down; derive it from the model with
    :func:`model_tilt`, or pass any plain float).
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
        tilt_deg=_validate_tilt(tilt_deg),
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


def model_epoch(
    interpreter: Interpreter,
    mission: str | M.Definition | M.Usage,
    *,
    attribute: str = "epoch",
) -> datetime | None:
    """The mission's stated epoch, read off the model.

    Evaluates ``attribute`` on ``mission`` -- an attribute typed
    ``Time::Iso8601DateTime`` (the vendored standard time package's UTC
    instant, carried as an ISO 8601 string) -- and returns it as an
    aware UTC :class:`~datetime.datetime`, ready for the track
    builders' ``epoch=``.  Returns ``None`` when the mission states no
    such attribute, so callers fall back to the deterministic default
    epoch honestly; a stated value that is not ISO 8601 is a loud
    :class:`AnalysisError`.
    """

    from .. import model as M  # runtime narrow; the top-level M import is typing-only

    target = interpreter.resolver.resolve(mission) if isinstance(mission, str) else mission
    if not isinstance(target, (M.Definition, M.Usage)):
        raise AnalysisError(f"{mission!r} is not a mission part")
    names = {child.name for child in getattr(target, "members", [])}
    if attribute not in names:
        return None
    label = mission if isinstance(mission, str) else (target.qualified_name or target.label)
    try:
        value = interpreter.evaluate(attribute, context=target)
    except SysMLError as err:
        raise AnalysisError(f"{label}::{attribute} did not evaluate: {err}") from err
    if not isinstance(value, str):
        raise AnalysisError(
            f"{label}::{attribute} must be an ISO 8601 string "
            f"(Time::Iso8601DateTime); got {value!r}"
        )
    try:
        # datetime.fromisoformat only learned the Z suffix in 3.11
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as err:
        raise AnalysisError(f"{label}::{attribute} is not ISO 8601: {value!r}") from err
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def model_tilt(
    interpreter: Interpreter,
    assembly: str | M.Definition | M.Usage,
    *,
    attribute: str = "cruiseTilt",
) -> float:
    """The airframe's own cruise tilt, degrees, read off the model.

    Instantiates ``assembly`` and evaluates ``attribute`` -- for
    the DeepScout MultiRotor family that is ``cruiseTilt``, the CruiseTilt calc:
    the altitude-hold ceiling ``arccos(m g / T)`` at continuous thrust,
    capped by the operational comfort limit.  Feed the result to
    :func:`mission_track` / :func:`from_replay` ``tilt_deg=`` so the
    globe animation flies the MODEL's physics (any plain float still
    works as an override).
    """

    try:
        instance = interpreter.instantiate(assembly)
    except SysMLError as err:
        raise AnalysisError(f"cannot instantiate {assembly!r}: {err}") from err
    value = instance.slots.get(attribute)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        label = assembly if isinstance(assembly, str) else (assembly.qualified_name or "")
        raise AnalysisError(f"{label}::{attribute} did not evaluate to a number (got {value!r})")
    return _validate_tilt(float(value))


def mission_values(
    interpreter: Interpreter,
    waypoints: Sequence[Sequence[float]],
    *,
    ground_alt: float,
    assembly: str | M.Definition | M.Usage = "Rotorcraft::QuadCopter",
    mission_calc: str | M.Definition | M.Usage = "DeepScout::MissionTime",
    payload_mass: float | None = None,
) -> dict[str, float]:
    """Scoreboard ``values=`` bindings for the mission-time requirement.

    The kernel measures the GEOMETRY -- the waypoint legs' great-circle
    lengths, the climb from ``ground_alt`` to the first waypoint, and
    the descent home from the last (the same phase mapping
    :func:`from_replay` flies) -- and the MODEL computes the physics:
    an ``assembly`` instance supplies the achievable cruise speed
    (``maxCruiseSpeed`` at ``cruiseTilt``) and the ``mission_calc``
    calc def turns distances and speed into minutes.  The returned dict
    (``missionMinutes`` plus the ``cruiseTiltDeg`` / ``cruiseSpeedMps``
    / ``routeM`` it derives from) injects straight into
    ``scoreboard(model, values=...)``, exactly like the geometry
    module's occlusion measures.

    ``payload_mass`` overrides the instance's ``payloadMass`` -- the
    one-line what-if: a heavier payload eats the continuous-thrust
    margin, the tilt ceiling and cruise speed collapse, and the mission
    budget busts.  An airframe that cannot hold altitude at continuous
    thrust at all (cruise speed 0) reports an INFINITE mission time.
    """

    points, _times = _parse_waypoints(waypoints, minimum=2, allow_times=True)
    route_m = sum(_haversine_m(a[0], a[1], b[0], b[1]) for a, b in pairwise(points))
    climb_m = max(points[0][2] - ground_alt, 0.0)
    descent_m = max(points[-1][2] - ground_alt, 0.0)
    overrides = {} if payload_mass is None else {"payloadMass": float(payload_mass)}
    try:
        instance = interpreter.instantiate(assembly, **overrides)
        speed = float(instance.slots["maxCruiseSpeed"])
        tilt = float(instance.slots["cruiseTilt"])
        if speed > 0.0:
            minutes = float(
                interpreter.call(
                    mission_calc,
                    routeM=route_m,
                    climbM=climb_m,
                    descentM=descent_m,
                    cruiseSpeed=speed,
                )
            )
        else:
            minutes = math.inf
    except (SysMLError, KeyError, TypeError, ValueError) as err:
        raise AnalysisError(
            f"{assembly!r} did not yield the mission physics "
            f"(cruiseTilt / maxCruiseSpeed / {mission_calc!r}): {err}"
        ) from err
    return {
        "missionMinutes": minutes,
        "cruiseTiltDeg": tilt,
        "cruiseSpeedMps": speed,
        "routeM": route_m,
    }


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


def _leaf_segments(
    timeline: Timeline,
    seconds_per_step: float | Sequence[float] | Mapping[int, float],
) -> list[tuple[float, float, str]]:
    """The ordered, non-overlapping leaf-state activation segments.

    Composite states (anything recorded as a parent) are dropped; in
    parallel regions the earliest-activated leaf wins and later
    overlapping intervals are clipped to keep one motion driver at a
    time.  Step-mode timelines map the step axis onto seconds through
    ``seconds_per_step`` -- a scalar, or a per-step sequence/mapping
    (:func:`longeron.widgets.time.step_seconds`).
    """

    if timeline.step_mode:
        from ..widgets.time import step_seconds  # the one shared step-axis ladder

        seconds, _stated = step_seconds(timeline.n_steps, seconds_per_step)

        def key_s(key: float) -> float:
            return seconds[min(round(key), len(seconds) - 1)]

        axis_end = seconds[-1]
    else:

        def key_s(key: float) -> float:
            return key

        axis_end = timeline.t_end
    composites = set(timeline.parents.values())
    intervals: list[tuple[float, float, str]] = []
    for qname, keyframes in timeline.tracks.items():
        if qname in composites:
            continue
        on: float | None = None
        for key, active in keyframes:
            if active and on is None:
                on = key_s(key)
            elif not active and on is not None:
                intervals.append((on, key_s(key), qname))
                on = None
        if on is not None:
            intervals.append((on, axis_end, qname))
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


def track_from_timeline(
    timeline: Timeline,
    *,
    waypoints: Sequence[Sequence[float]],
    phases: Mapping[str, str] | None = None,
    ground_alt: float = 0.0,
    tilt_deg: float = 0.0,
    seconds_per_step: float | Sequence[float] | Mapping[int, float] = 10.0,
    epoch: datetime | None = None,
    name: str = "mission",
) -> MissionTrack:
    """A track synthesized from an EXISTING recording.

    The synthesis half of :func:`from_replay`: it maps every leaf
    state's activation interval in ``timeline`` (a
    :func:`longeron.replay.record_timeline` product) onto a motion
    segment along ``waypoints`` -- see the module docstring for the
    phase table and ``phases=`` for per-state-name overrides.  Because
    the timeline arrives prebuilt, the diagram replay widget and the
    globe can play the SAME recording (the time seam's timebase
    discipline, :class:`longeron.widgets.time.Timebase`).

    ``waypoints`` are ``(lat, lon, alt)`` tuples (no times -- timing
    comes from the recording); the mission starts at the first waypoint
    at ``ground_alt``.  Timed timelines keep their instants 1:1 (track
    seconds ARE trace seconds).  Step-mode timelines have no time axis,
    so ``seconds_per_step`` states one: a scalar, or a per-step
    sequence/mapping when steps take unequal durations
    (:func:`longeron.widgets.time.step_seconds`).  ``epoch`` anchors
    the track in UTC (:func:`model_epoch` reads it off the model;
    ``None`` keeps the deterministic default).
    """

    points, _times = _parse_waypoints(waypoints, minimum=1, allow_times=False)
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

    return MissionTrack(
        name=name,
        epoch=epoch if epoch is not None else _DEFAULT_EPOCH,
        samples=samples,
        waypoints=points,
        phases=phase_records,
        tilt_deg=_validate_tilt(tilt_deg),
    )


def from_replay(
    interpreter: Interpreter,
    state_machine: str | M.Definition | M.Usage,
    events: list[Any] | None = None,
    *,
    waypoints: Sequence[Sequence[float]],
    inputs: dict[str, Any] | None = None,
    phases: Mapping[str, str] | None = None,
    ground_alt: float = 0.0,
    tilt_deg: float = 0.0,
    seconds_per_step: float | Sequence[float] | Mapping[int, float] = 10.0,
    epoch: datetime | None = None,
    name: str | None = None,
) -> MissionTrack:
    """A track driven by the state machine's ACTUAL execution.

    Simulates ``state_machine`` with ``events`` (the
    ``Interpreter.simulate`` protocol: event names or ``(name,
    payload)`` tuples, plain numbers advance the clock) via
    :func:`longeron.replay.record_timeline`, then synthesizes the track
    with :func:`track_from_timeline` -- see there for ``waypoints``,
    ``phases``, ``ground_alt``, ``seconds_per_step``, and ``epoch``.
    ``tilt_deg`` is the forward cruise tilt the airframe holds while it
    advances along the route (degrees nose-down; derive it from the
    model with :func:`model_tilt`, or pass any plain float).  ``name``
    defaults to the machine's own name.  To share one recording across
    the diagram replay and the globe, record once and call
    :func:`track_from_timeline` instead.
    """

    from ..replay import record_timeline  # imports interpreter+render; keep module import light

    timeline = record_timeline(interpreter, state_machine, events, inputs=inputs)
    if name is None:  # default to the machine's own name
        target = (
            interpreter.resolver.resolve(state_machine)
            if isinstance(state_machine, str)
            else state_machine
        )
        name = getattr(target, "name", None) or "mission"
    return track_from_timeline(
        timeline,
        waypoints=waypoints,
        phases=phases,
        ground_alt=ground_alt,
        tilt_deg=tilt_deg,
        seconds_per_step=seconds_per_step,
        epoch=epoch,
        name=name,
    )
