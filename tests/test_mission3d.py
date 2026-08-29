"""Mission-flight viewer tests (longeron.analysis.mission3d).

Track synthesis and payload wiring only: the Cesium front-end needs a
browser AND the pinned CDN, so there is deliberately no browser-tier
test here -- a Cesium scene cannot render without live CDN access, and
the flake policy (tests/browser/README.md) forbids network-dependent
assertions.  The ESM contracts (CDN URL, offline fallback, control
wiring) are asserted as structure; the in-house GLB exporter likewise
(container layout, scene shape, accessor bounds); rendered-globe and
rendered-model evidence is captured out-of-band against the same ESM.
"""

import base64
import json
import math
import struct
from datetime import datetime, timezone
from itertools import pairwise
from pathlib import Path
from typing import ClassVar

import pytest

import longeron
from longeron.analysis import geometry, mission3d
from longeron.analysis._expr import AnalysisError

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

WAYPOINTS = [
    (40.0100, -105.3000, 1750.0),
    (40.0180, -105.2900, 1820.0),
    (40.0240, -105.2760, 1860.0),
    (40.0300, -105.2700, 1800.0),
]

# the canonical mission machine: idle -> takingOff -> flying -> landing
# -> idle, with clock advances between events so states have durations
MISSION_MODEL = """
package Mission {
    state def FlightStates {
        entry; then idle;
        state idle;
        transition first idle accept launch then takingOff;
        state takingOff;
        transition first takingOff accept airborne then flying;
        state flying;
        transition first flying accept bingo then landing;
        state landing;
        transition first landing accept touchdown then idle;
    }
}
"""
EVENTS = ["launch", 20.0, "airborne", 120.0, "bingo", 30.0, "touchdown", 10.0]

WAYPOINT_MODEL = """
package Field {
    part mission {
        part wp1 { attribute lat : Real = 40.01; attribute lon : Real = -105.30;
                   attribute alt : Real = 1750.0; }
        part wp2 { attribute lat : Real = 40.02; attribute lon : Real = -105.29;
                   attribute alt : Real = 1820.0; }
        part camera;
    }
}
"""


@pytest.fixture(scope="module")
def interp():
    return longeron.Interpreter(longeron.loads(MISSION_MODEL))


@pytest.fixture(scope="module")
def track(interp):
    return mission3d.from_replay(
        interp, "Mission::FlightStates", EVENTS, waypoints=WAYPOINTS, ground_alt=1650.0
    )


@pytest.fixture(scope="module")
def mesh():
    """A real drone mesh (the geometry module's own dict shape)."""

    return geometry.drone_geometry(
        prop_diameter_in=10.0, motor_mass=0.048, battery_mass=0.30, esc_mass=0.012
    )


def parse_glb(blob):
    """(gltf json dict, bin bytes, declared total length) of a GLB."""

    magic, version, length = struct.unpack_from("<III", blob, 0)
    assert magic == 0x46546C67 and version == 2  # b"glTF", glTF 2.0
    json_length, json_type = struct.unpack_from("<II", blob, 12)
    assert json_type == 0x4E4F534A  # b"JSON"
    document = json.loads(blob[20 : 20 + json_length])
    bin_length, bin_type = struct.unpack_from("<II", blob, 20 + json_length)
    assert bin_type == 0x004E4942  # b"BIN\0"
    binary = blob[28 + json_length : 28 + json_length + bin_length]
    return document, binary, length


def sample_times(track):
    return [t for t, _lat, _lon, _alt in track.samples]


# -- waypoint tracks ----------------------------------------------------------


class TestMissionTrack:
    def test_explicit_times(self):
        track = mission3d.mission_track(
            [
                (40.0, -105.0, 1700.0, 0.0),
                (40.1, -105.0, 1800.0, 60.0),
                (40.2, -105.0, 1700.0, 90.0),
            ]
        )
        assert sample_times(track) == [0.0, 60.0, 90.0]
        assert track.duration == 90.0
        assert track.phases == [(0.0, 90.0, "route", "")]
        assert track.waypoints[0] == (40.0, -105.0, 1700.0)

    def test_times_derive_from_speed(self):
        track = mission3d.mission_track(WAYPOINTS, speed_mps=15.0)
        times = sample_times(track)
        assert times[0] == 0.0
        assert all(t1 > t0 for t0, t1 in pairwise(times))
        # duration ~ total 3D route length / speed
        length = sum(mission3d._leg_length_m(a, b) for a, b in pairwise(WAYPOINTS))
        assert track.duration == pytest.approx(length / 15.0, rel=1e-6)

    def test_epoch_is_deterministic_by_default(self):
        track = mission3d.mission_track(WAYPOINTS)
        assert track.epoch == mission3d._DEFAULT_EPOCH
        custom = datetime(2027, 6, 1, 8, 30, tzinfo=timezone.utc)
        assert mission3d.mission_track(WAYPOINTS, epoch=custom).epoch == custom

    def test_validation(self):
        with pytest.raises(AnalysisError, match="at least 2 waypoints"):
            mission3d.mission_track([(40.0, -105.0, 1700.0)])
        with pytest.raises(AnalysisError, match="off the globe"):
            mission3d.mission_track([(91.0, -105.0, 0.0), (40.0, -105.0, 0.0)])
        with pytest.raises(AnalysisError, match="every waypoint carries a time"):
            mission3d.mission_track([(40.0, -105.0, 0.0, 0.0), (40.1, -105.0, 0.0)])
        with pytest.raises(AnalysisError, match="strictly increasing"):
            mission3d.mission_track([(40.0, -105.0, 0.0, 5.0), (40.1, -105.0, 0.0, 5.0)])
        with pytest.raises(AnalysisError, match="speed_mps"):
            mission3d.mission_track(WAYPOINTS, speed_mps=0.0)
        with pytest.raises(AnalysisError, match="lat, lon, alt"):
            mission3d.mission_track([(40.0, -105.0), (40.1, -105.0)])


class TestModelWaypoints:
    def test_reads_parts_with_lat_lon(self):
        interp = longeron.Interpreter(longeron.loads(WAYPOINT_MODEL))
        waypoints = mission3d.model_waypoints(interp, "Field::mission")
        assert waypoints == [(40.01, -105.30, 1750.0), (40.02, -105.29, 1820.0)]
        # and they feed straight into a track ("camera" is skipped)
        track = mission3d.mission_track(waypoints)
        assert len(track.samples) == 2

    def test_no_waypoints_is_an_error(self):
        interp = longeron.Interpreter(longeron.loads(WAYPOINT_MODEL))
        with pytest.raises(AnalysisError, match="no waypoint children"):
            mission3d.model_waypoints(interp, "Field::mission::camera")


# -- replay-driven tracks ------------------------------------------------------


class TestFromReplay:
    def test_phases_follow_the_executed_machine(self, track):
        assert [(t0, t1, phase) for t0, t1, phase, _q in track.phases] == [
            (0.0, 20.0, "takeoff"),
            (20.0, 140.0, "route"),
            (140.0, 170.0, "landing"),
            (170.0, 180.0, "ground"),
        ]
        assert [q.rsplit("::", 1)[-1] for *_span, q in track.phases] == [
            "takingOff",
            "flying",
            "landing",
            "idle",
        ]
        assert track.duration == 180.0
        assert track.name == "FlightStates"

    def test_sample_times_strictly_monotonic(self, track):
        times = sample_times(track)
        assert all(t1 > t0 for t0, t1 in pairwise(times))

    def test_takeoff_is_a_vertical_climb_at_wp0(self, track):
        t0, lat0, lon0, alt0 = track.samples[0]
        assert (t0, lat0, lon0, alt0) == (0.0, 40.0100, -105.3000, 1650.0)  # ground_alt
        t1, lat1, lon1, alt1 = track.samples[1]
        assert (t1, lat1, lon1) == (20.0, 40.0100, -105.3000)  # no horizontal motion
        assert alt1 == WAYPOINTS[0][2]  # climbed to the route altitude

    def test_route_crosses_the_intermediate_waypoints(self, track):
        flown = {(lat, lon) for _t, lat, lon, _alt in track.samples}
        for lat, lon, _alt in WAYPOINTS[1:-1]:
            assert (lat, lon) in flown

    def test_landing_descends_in_place_then_holds(self, track):
        last_lat, last_lon, _alt = WAYPOINTS[-1]
        # landing start (route end), landing end, and the final ground hold
        for t, expected_alt in ((140.0, WAYPOINTS[-1][2]), (170.0, 1650.0), (180.0, 1650.0)):
            sample = next(s for s in track.samples if s[0] == t)
            assert sample[1:] == (last_lat, last_lon, expected_alt)

    def test_step_mode_scales_steps_to_seconds(self, interp):
        track = mission3d.from_replay(
            interp,
            "Mission::FlightStates",
            ["launch", "airborne", "bingo", "touchdown"],
            waypoints=WAYPOINTS,
            seconds_per_step=5.0,
        )
        phases = [phase for _t0, _t1, phase, _q in track.phases]
        assert phases == ["ground", "takeoff", "route", "landing"]
        assert track.duration == 20.0  # 4 steps x 5 s
        times = sample_times(track)
        assert all(t1 > t0 for t0, t1 in pairwise(times))

    def test_phase_overrides_win(self, interp):
        track = mission3d.from_replay(
            interp,
            "Mission::FlightStates",
            EVENTS,
            waypoints=WAYPOINTS,
            phases={"flying": "hold"},
        )
        assert "route" not in {phase for _t0, _t1, phase, _q in track.phases}
        # with no route phase the drone never leaves the first waypoint
        assert {(lat, lon) for _t, lat, lon, _alt in track.samples} == {WAYPOINTS[0][:2]}

    def test_replay_waypoints_must_not_carry_times(self, interp):
        with pytest.raises(AnalysisError, match="timing comes from"):
            mission3d.from_replay(
                interp,
                "Mission::FlightStates",
                EVENTS,
                waypoints=[(40.0, -105.0, 1700.0, 0.0), (40.1, -105.0, 1800.0, 60.0)],
            )

    def test_single_waypoint_hovers(self, interp):
        track = mission3d.from_replay(
            interp, "Mission::FlightStates", EVENTS, waypoints=[(40.0, -105.0, 1750.0)]
        )
        assert {(lat, lon) for _t, lat, lon, _alt in track.samples} == {(40.0, -105.0)}
        assert max(alt for *_tll, alt in track.samples) == 1750.0  # still climbs


# -- attitude ------------------------------------------------------------------


def recover_attitude(q, lat, lon):
    """(heading_deg, pitch_deg, left_z) implied by an ECEF quaternion.

    Rotates the body axes by ``q`` and projects them onto the local
    east-north-up frame; ``left_z`` is the vertical component of the
    body +Y axis -- zero for a roll-free attitude.
    """

    x, y, z, w = q

    def rotate(v):
        t = (2 * (y * v[2] - z * v[1]), 2 * (z * v[0] - x * v[2]), 2 * (x * v[1] - y * v[0]))
        cross = (y * t[2] - z * t[1], z * t[0] - x * t[2], x * t[1] - y * t[0])
        return tuple(v[i] + w * t[i] + cross[i] for i in range(3))

    phi, lam = math.radians(lat), math.radians(lon)
    east = (-math.sin(lam), math.cos(lam), 0.0)
    north = (-math.sin(phi) * math.cos(lam), -math.sin(phi) * math.sin(lam), math.cos(phi))
    up = (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))

    def enu(v):
        return tuple(sum(v[i] * basis[i] for i in range(3)) for basis in (east, north, up))

    nose = enu(rotate((1.0, 0.0, 0.0)))
    left = enu(rotate((0.0, 1.0, 0.0)))
    heading = math.degrees(math.atan2(nose[0], nose[1])) % 360.0
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, nose[2]))))
    return heading, pitch, left[2]


@pytest.fixture(scope="module")
def tilted(interp):
    return mission3d.from_replay(
        interp,
        "Mission::FlightStates",
        EVENTS,
        waypoints=WAYPOINTS,
        ground_alt=1650.0,
        tilt_deg=25.0,
    )


class TestAttitude:
    def test_keyframes_strictly_increasing(self, tilted):
        times = [t for t, _h, _p in tilted.attitude()]
        assert times == sorted(times) and len(set(times)) == len(times)
        assert times[0] == 0.0 and times[-1] == tilted.duration

    def test_pitch_zero_in_climb_and_descent_tilt_on_route(self, tilted):
        # phases: takeoff 0-20, route 20-140, landing 140-170, ground 170-180
        for t, _heading, pitch in tilted.attitude():
            if t <= 20.0 or t >= 140.0:  # vertical/ground: props up
                assert pitch == 0.0, (t, pitch)
            elif 25.0 <= t <= 135.0:  # cruise, clear of the blends
                assert pitch == -25.0, (t, pitch)

    def test_heading_follows_the_track_legs(self, tilted):
        legs = [
            mission3d._initial_bearing_deg(a[0], a[1], b[0], b[1]) for a, b in pairwise(WAYPOINTS)
        ]
        keys = tilted.attitude()
        # the drone faces the first leg from the ground up
        assert keys[0][1] == pytest.approx(legs[0])
        headings = [heading for _t, heading, _p in keys]
        for leg in legs:  # every leg heading is flown
            assert any(h == pytest.approx(leg) for h in headings), leg
        # landing and the final ground hold keep the last leg's heading
        assert keys[-1][1] == pytest.approx(legs[-1])

    def test_blends_are_short_and_monotonic(self, tilted):
        keys = tilted.attitude()
        changes = 0
        for (t0, h0, p0), (t1, h1, p1) in pairwise(keys):
            if p0 == p1 and h0 == h1:
                continue
            changes += 1
            assert t1 - t0 <= 3.0 + 1e-9  # the blend window
            # slerp between the two keyframes moves pitch monotonically:
            # the midpoint attitude lies between the endpoints
            lat, lon = tilted._position_at((t0 + t1) / 2.0)
            qa = mission3d._attitude_quaternion(lat, lon, h0, p0)
            qb = mission3d._attitude_quaternion(lat, lon, h1, p1)
            if sum(a * b for a, b in zip(qa, qb, strict=True)) < 0.0:
                qb = tuple(-c for c in qb)
            mid = tuple((a + b) / 2.0 for a, b in zip(qa, qb, strict=True))
            norm = math.hypot(*mid)
            _h, pitch, roll = recover_attitude(tuple(c / norm for c in mid), lat, lon)
            assert min(p0, p1) - 1e-6 <= pitch <= max(p0, p1) + 1e-6
            assert abs(roll) < 1e-6  # roll stays 0 through the blend
        assert changes >= 2  # at least the climb->route and route->landing blends

    def test_hover_only_track_keeps_props_level(self, interp):
        track = mission3d.from_replay(
            interp,
            "Mission::FlightStates",
            EVENTS,
            waypoints=[(40.0, -105.0, 1750.0)],
            tilt_deg=25.0,
        )
        # no horizontal motion anywhere: the tilt never engages
        assert {pitch for _t, _h, pitch in track.attitude()} == {0.0}

    def test_plain_route_track_holds_the_tilt(self):
        track = mission3d.mission_track(WAYPOINTS, tilt_deg=10.0)
        assert {pitch for _t, _h, pitch in track.attitude()} == {-10.0}

    def test_tilt_validation(self, interp):
        with pytest.raises(AnalysisError, match="tilt_deg"):
            mission3d.mission_track(WAYPOINTS, tilt_deg=-1.0)
        with pytest.raises(AnalysisError, match="tilt_deg"):
            mission3d.from_replay(
                interp, "Mission::FlightStates", EVENTS, waypoints=WAYPOINTS, tilt_deg=90.0
            )

    def test_quaternion_is_unit_and_roll_free(self, tilted):
        for t, heading, pitch in tilted.attitude():
            lat, lon = tilted._position_at(t)
            q = mission3d._attitude_quaternion(lat, lon, heading, pitch)
            assert math.hypot(*q) == pytest.approx(1.0)
            got_heading, got_pitch, roll = recover_attitude(q, lat, lon)
            assert got_pitch == pytest.approx(pitch, abs=1e-9)
            assert abs(roll) < 1e-12
            assert got_heading == pytest.approx(heading % 360.0, abs=1e-9)


# -- the drone model's own attitude/mission physics ----------------------------

#: hand-computed stock design point of examples/deepscout (EMAX MT2213
#: on APC 10x4.5MR, PropThrust's calibrated Ct = 0.097)
THRUST_N = 0.097 * 1.225 * (0.75 * 935.0 * 11.1 / 60.0) ** 2.0 * 0.254**4.0
USABLE_N = 4.0 * THRUST_N * 0.59  # continuousThrustFraction (65%-throttle cap)
#: F450 frame + bay (pack, ESC, FC, GPS, RX, telemetry, gear, harness)
#: + 4 x (motor + prop) + payload
BAY_KG = 0.39 + 0.012 + 0.039 + 0.032 + 0.017 + 0.028 + 0.08 + 0.05
MASS_KG = 0.282 + BAY_KG + 4.0 * 0.055 + 4.0 * 0.015 + 0.2
CDA_M2 = 0.024 * 1.1  # frontalArea x bluff-body Cd
MAX_TILT_DEG = math.degrees(math.acos(MASS_KG * 9.81 / USABLE_N))
CRUISE_SPEED = math.sqrt(MASS_KG * 9.81 * math.tan(math.radians(25.0)) / (0.5 * 1.225 * CDA_M2))

#: tutorial 10's mission: a loop over Piedmont Park, ~300 m MSL ground
ATLANTA = [
    (33.7813, -84.3833, 350.0),
    (33.7885, -84.3785, 390.0),
    (33.7900, -84.3695, 380.0),
    (33.7838, -84.3690, 360.0),
    (33.7770, -84.3825, 350.0),
]


@pytest.fixture(scope="module")
def drone_interp():
    return longeron.Interpreter(longeron.load(EXAMPLES / "deepscout", cache=False))


class TestModelPhysics:
    def test_max_tilt_is_the_continuous_thrust_arccos(self, drone_interp):
        quad = drone_interp.instantiate("Rotorcraft::QuadCopter")
        assert quad.slots["thrustPerRotor"] == pytest.approx(THRUST_N)
        assert quad.slots["usableThrust"] == pytest.approx(USABLE_N)
        assert quad.slots["maxTilt"] == pytest.approx(MAX_TILT_DEG)  # ~45.2 deg
        # ...but the COMMANDED tilt is ops-capped: min(physics, 25 deg)
        assert quad.slots["cruiseTilt"] == 25.0

    def test_max_cruise_speed_is_the_drag_balance(self, drone_interp):
        quad = drone_interp.instantiate("Rotorcraft::QuadCopter")
        assert quad.slots["maxCruiseSpeed"] == pytest.approx(CRUISE_SPEED)  # ~20.0 m/s

    def test_tilt_for_speed_inverts_max_cruise_speed(self, drone_interp):
        quad = drone_interp.instantiate("Rotorcraft::QuadCopter")
        tilt = drone_interp.call(
            "DeepScout::TiltForSpeed",
            speed=quad.slots["maxCruiseSpeed"],
            massKg=quad.slots["totalMass"],
            dragArea=quad.slots["dragArea"],
        )
        assert tilt == pytest.approx(25.0)

    def test_overloaded_airframe_reads_zero_not_domain_error(self, drone_interp):
        assert drone_interp.call("DeepScout::MaxTilt", massKg=3.0, thrustN=USABLE_N) == 0.0

    def test_mission_time_calc(self, drone_interp):
        minutes = drone_interp.call(
            "DeepScout::MissionTime", routeM=3600.0, climbM=50.0, descentM=45.0, cruiseSpeed=12.0
        )
        assert minutes == pytest.approx((3600.0 / 12.0 + 50.0 / 2.0 + 45.0 / 1.5) / 60.0)

    def test_model_tilt_reads_the_model(self, drone_interp):
        assert mission3d.model_tilt(drone_interp, "Rotorcraft::QuadCopter") == 25.0

    def test_model_tilt_missing_attribute_is_loud(self, drone_interp):
        with pytest.raises(AnalysisError, match="did not evaluate to a number"):
            mission3d.model_tilt(drone_interp, "Rotorcraft::QuadCopter", attribute="nope")
        with pytest.raises(AnalysisError, match="cannot instantiate"):
            mission3d.model_tilt(drone_interp, "Rotorcraft::Nope")

    def test_mission_values_design_point(self, drone_interp):
        values = mission3d.mission_values(drone_interp, ATLANTA, ground_alt=300.0)
        route = sum(mission3d._haversine_m(a[0], a[1], b[0], b[1]) for a, b in pairwise(ATLANTA))
        expected = (route / CRUISE_SPEED + 50.0 / 2.0 + 50.0 / 1.5) / 60.0
        assert values["routeM"] == pytest.approx(route)  # ~3.9 km
        assert values["cruiseTiltDeg"] == 25.0
        assert values["cruiseSpeedMps"] == pytest.approx(CRUISE_SPEED)
        assert values["missionMinutes"] == pytest.approx(expected)  # ~4.2 min
        assert values["missionMinutes"] < 6.0  # inside the model's budget

    def test_mission_values_payload_what_if_busts_the_budget(self, drone_interp):
        # a 0.78 kg payload eats the continuous-thrust margin: the tilt
        # ceiling collapses below the ops cap, cruise slows, budget busts
        bust = mission3d.mission_values(drone_interp, ATLANTA, ground_alt=300.0, payload_mass=0.78)
        mass = MASS_KG + 0.58
        tilt = math.degrees(math.acos(mass * 9.81 / USABLE_N))
        speed = math.sqrt(mass * 9.81 * math.tan(math.radians(tilt)) / (0.5 * 1.225 * CDA_M2))
        assert bust["cruiseTiltDeg"] == pytest.approx(tilt)  # ~6.4 deg
        assert bust["cruiseSpeedMps"] == pytest.approx(speed)  # ~11.6 m/s
        assert bust["missionMinutes"] > 6.0  # budget bust (~6.6 min)
        # past the continuous-thrust ceiling: infinite, not a crash
        over = mission3d.mission_values(drone_interp, ATLANTA, ground_alt=300.0, payload_mass=0.85)
        assert over["cruiseSpeedMps"] == 0.0
        assert math.isinf(over["missionMinutes"])

    def test_mission_values_unknown_assembly_is_loud(self, drone_interp):
        with pytest.raises(AnalysisError, match="mission physics"):
            mission3d.mission_values(
                drone_interp, ATLANTA, ground_alt=300.0, assembly="ScoutParts::F450Kit::Battery"
            )

    def test_requirement_scoring(self, drone_interp):
        from longeron.analysis.scoreboard import scoreboard

        model = drone_interp.model
        green = scoreboard(
            model, values=mission3d.mission_values(drone_interp, ATLANTA, ground_alt=300.0)
        )
        row = {r.name: r for r in green.table()}["missionTime"]
        assert row.unit == "min"
        assert row.raw == pytest.approx(4.238, abs=0.01)
        # smaller-is-better between ramp0=6 (budget) and ramp1=4
        assert row.utility == pytest.approx((6.0 - row.raw) / 2.0)
        bust = scoreboard(
            model,
            values=mission3d.mission_values(
                drone_interp, ATLANTA, ground_alt=300.0, payload_mass=0.78
            ),
        )
        assert {r.name: r for r in bust.table()}["missionTime"].utility == 0.0

    def test_tricopter_busts_the_budget_the_quad_meets(self, drone_interp):
        """The sub-architecture difference, measured: same route, same
        physics chain, but the TriCopter's 11-deg yaw-authority tilt cap
        drops cruise speed enough to bust the 6-minute mission budget
        the QuadCopter meets at 4.24 min."""
        from longeron.analysis.scoreboard import scoreboard

        quad = mission3d.mission_values(drone_interp, ATLANTA, ground_alt=300.0)
        tri = mission3d.mission_values(
            drone_interp, ATLANTA, ground_alt=300.0, assembly="Rotorcraft::TriCopter"
        )
        assert quad["missionMinutes"] == pytest.approx(4.238, abs=0.01)
        assert tri["cruiseTiltDeg"] == pytest.approx(11.0)  # the servo's cap
        assert tri["cruiseSpeedMps"] == pytest.approx(12.43, abs=0.01)
        assert tri["missionMinutes"] == pytest.approx(6.22, abs=0.01)  # > budget
        model = drone_interp.model
        tri_row = {r.name: r for r in scoreboard(model, values=tri).table()}["missionTime"]
        assert tri_row.utility == 0.0  # red: past ramp0 = the 6-min budget
        quad_row = {r.name: r for r in scoreboard(model, values=quad).table()}["missionTime"]
        assert quad_row.utility > 0.7  # green, with headroom


# -- CZML payload --------------------------------------------------------------


class TestCzml:
    def test_document_clock_spans_the_mission(self, track):
        czml = track.to_czml()
        document = czml[0]
        assert document["id"] == "document" and document["version"] == "1.0"
        clock = document["clock"]
        assert clock["interval"] == "2026-01-01T12:00:00Z/2026-01-01T12:03:00Z"
        assert clock["currentTime"] == "2026-01-01T12:00:00Z"
        assert clock["range"] == "CLAMPED"
        assert clock["multiplier"] >= 1

    def test_packet_ids(self, track):
        ids = [packet["id"] for packet in track.to_czml()]
        assert ids == [
            "document",
            "mission-route",
            "waypoint-0",
            "waypoint-1",
            "waypoint-2",
            "waypoint-3",
            "mission-drone",
        ]

    def test_drone_position_samples(self, track):
        drone = track.to_czml()[-1]
        position = drone["position"]
        assert position["epoch"] == "2026-01-01T12:00:00Z"
        assert position["interpolationDegree"] == 1
        degrees = position["cartographicDegrees"]
        assert len(degrees) == 4 * len(track.samples)
        times = degrees[0::4]
        assert times == sorted(times) and len(set(times)) == len(times)
        assert drone["availability"] == "2026-01-01T12:00:00Z/2026-01-01T12:03:00Z"

    def test_drone_label_follows_the_active_state(self, track):
        text = track.to_czml()[-1]["label"]["text"]
        assert [entry["string"] for entry in text] == ["takingOff", "flying", "landing", "idle"]
        # intervals tile the whole mission
        assert text[0]["interval"].startswith("2026-01-01T12:00:00Z/")
        assert text[-1]["interval"].endswith("/2026-01-01T12:03:00Z")

    def test_camera_offset_scales_with_the_route(self, track):
        cartesian = track.to_czml()[-1]["viewFrom"]["cartesian"]
        assert len(cartesian) == 3
        assert cartesian[2] > 0  # above the drone
        assert math.hypot(*cartesian) >= 400.0

    def test_route_and_waypoint_packets(self, track):
        czml = track.to_czml()
        route = czml[1]
        assert len(route["polyline"]["positions"]["cartographicDegrees"]) == 3 * len(WAYPOINTS)
        waypoint = czml[2]
        assert waypoint["point"]["pixelSize"] == 5
        assert waypoint["label"]["text"] == "WP0"

    def test_static_label_for_plain_tracks(self):
        track = mission3d.mission_track(WAYPOINTS, name="survey")
        assert track.to_czml()[-1]["label"]["text"] == "survey"

    def test_degenerate_tracks_refused(self):
        empty = mission3d.MissionTrack(
            name="x", epoch=mission3d._DEFAULT_EPOCH, samples=[], waypoints=[], phases=[]
        )
        with pytest.raises(AnalysisError, match="at least two samples"):
            empty.to_czml()
        flat = mission3d.MissionTrack(
            name="x",
            epoch=mission3d._DEFAULT_EPOCH,
            samples=[(0.0, 40.0, -105.0, 0.0), (0.0, 40.0, -105.0, 1.0)],
            waypoints=[],
            phases=[],
        )
        with pytest.raises(AnalysisError, match="positive duration"):
            flat.to_czml()


# -- the GLB exporter ----------------------------------------------------------


class TestMeshToGlb:
    _COMPONENT_BYTES: ClassVar = {5123: 2, 5125: 4, 5126: 4}
    _TYPE_COUNTS: ClassVar = {"SCALAR": 1, "VEC3": 3}

    def test_container_layout(self, mesh):
        """Header + JSON chunk + BIN chunk tile the file exactly, both
        chunks 4-byte aligned (the glTF 2.0 GLB container contract)."""

        blob = mission3d.mesh_to_glb(mesh)
        document, binary, length = parse_glb(blob)
        assert length == len(blob)
        json_length = struct.unpack_from("<I", blob, 12)[0]
        assert json_length % 4 == 0 and len(binary) % 4 == 0
        assert 28 + json_length + len(binary) == len(blob)
        assert document["asset"]["version"] == "2.0"

    def test_scene_one_node_per_part_under_a_rotated_root(self, mesh):
        document, _binary, _length = parse_glb(mission3d.mesh_to_glb(mesh))
        names = [part["name"] for part in mesh["parts"]]
        nodes = document["nodes"]
        assert document["scenes"][document["scene"]]["nodes"] == [0]
        assert nodes[0]["children"] == list(range(1, len(names) + 1))
        assert [node["name"] for node in nodes[1:]] == names
        assert [document["meshes"][node["mesh"]]["name"] for node in nodes[1:]] == names
        # the -90 degree yaw: mesh +X (forward) -> glTF +Z (forward)
        x, y, z, w = nodes[0]["rotation"]
        assert (x, z) == (0.0, 0.0)
        assert y == pytest.approx(-math.sqrt(0.5))
        assert w == pytest.approx(math.sqrt(0.5))

    def test_accessors_stay_inside_the_buffer(self, mesh):
        """Every accessor fits its bufferView, every view fits the one
        buffer, and the buffer's declared length is the BIN chunk's."""

        document, binary, _length = parse_glb(mission3d.mesh_to_glb(mesh))
        assert len(document["buffers"]) == 1
        assert document["buffers"][0]["byteLength"] == len(binary)
        for view in document["bufferViews"]:
            assert view["buffer"] == 0
            assert view["byteOffset"] % 4 == 0
            assert view["byteOffset"] + view["byteLength"] <= len(binary)
        for accessor in document["accessors"]:
            view = document["bufferViews"][accessor["bufferView"]]
            size = self._COMPONENT_BYTES[accessor["componentType"]]
            span = accessor["count"] * size * self._TYPE_COUNTS[accessor["type"]]
            assert span <= view["byteLength"]

    def test_position_bounds_match_the_packed_data(self, mesh):
        document, binary, _length = parse_glb(mission3d.mesh_to_glb(mesh))
        for gltf_mesh in document["meshes"]:
            accessor = document["accessors"][gltf_mesh["primitives"][0]["attributes"]["POSITION"]]
            view = document["bufferViews"][accessor["bufferView"]]
            floats = struct.unpack_from(f"<{accessor['count'] * 3}f", binary, view["byteOffset"])
            assert accessor["min"] == [min(floats[i::3]) for i in range(3)]
            assert accessor["max"] == [max(floats[i::3]) for i in range(3)]

    def test_flat_shading_unwelds_triangles(self, mesh):
        """Three vertices per face (POSITION == NORMAL == face-index
        count), trivial indices, unit flat normals."""

        document, binary, _length = parse_glb(mission3d.mesh_to_glb(mesh))
        for part, gltf_mesh in zip(mesh["parts"], document["meshes"], strict=True):
            primitive = gltf_mesh["primitives"][0]
            position = document["accessors"][primitive["attributes"]["POSITION"]]
            normal = document["accessors"][primitive["attributes"]["NORMAL"]]
            indices = document["accessors"][primitive["indices"]]
            assert position["count"] == normal["count"] == indices["count"] == len(part["faces"])
            view = document["bufferViews"][normal["bufferView"]]
            nx, ny, nz = struct.unpack_from("<3f", binary, view["byteOffset"])
            assert math.hypot(nx, ny, nz) == pytest.approx(1.0, abs=1e-5)

    def test_materials_carry_the_part_colors(self, mesh):
        document, _binary, _length = parse_glb(mission3d.mesh_to_glb(mesh))
        for part, material in zip(mesh["parts"], document["materials"], strict=True):
            factor = material["pbrMetallicRoughness"]["baseColorFactor"]
            assert factor[3] == part["opacity"]
            # sRGB hex -> linear (the baseColorFactor color space)
            red = int(part["color"][1:3], 16) / 255.0
            expected = red / 12.92 if red <= 0.04045 else ((red + 0.055) / 1.055) ** 2.4
            assert factor[0] == pytest.approx(expected, abs=1e-4)
            assert material["doubleSided"] is True
            assert (material.get("alphaMode") == "BLEND") == (part["opacity"] < 1.0)

    def test_validation(self):
        with pytest.raises(AnalysisError, match="no parts"):
            mission3d.mesh_to_glb({"parts": []})
        with pytest.raises(AnalysisError, match="out of range"):
            mission3d.mesh_to_glb(
                {
                    "parts": [
                        {
                            "name": "x",
                            "color": "#333333",
                            "opacity": 1.0,
                            "vertices": [0.0] * 9,
                            "faces": [0, 1, 7],
                        }
                    ]
                }
            )
        with pytest.raises(AnalysisError, match="rrggbb"):
            mission3d.mesh_to_glb(
                {
                    "parts": [
                        {
                            "name": "x",
                            "color": "red",
                            "opacity": 1.0,
                            "vertices": [0.0] * 9,
                            "faces": [0, 1, 2],
                        }
                    ]
                }
            )


class TestDroneModelPacket:
    def test_mesh_swaps_the_point_for_the_model(self, track, mesh):
        drone = track.to_czml(mesh=mesh, model_scale=2.5)[-1]
        assert "point" not in drone
        model = drone["model"]
        assert model["gltf"].startswith("data:model/gltf-binary;base64,")
        assert model["scale"] == 2.5
        assert model["minimumPixelSize"] >= 1  # visible however far the camera
        # the embedded payload is the mesh's own GLB, byte for byte
        payload = base64.b64decode(model["gltf"].split(",", 1)[1])
        assert payload == mission3d.mesh_to_glb(mesh)
        # the multirotor attitude rides as SAMPLED quaternions -- NOT a
        # velocityReference (VelocityOrientationProperty pitches the quad
        # vertical during climb/descent)
        orientation = drone["orientation"]
        assert "velocityReference" not in orientation
        assert orientation["epoch"] == "2026-01-01T12:00:00Z"
        assert orientation["interpolationAlgorithm"] == "LINEAR"
        packed = orientation["unitQuaternion"]
        assert len(packed) % 5 == 0 and len(packed) >= 10
        times = packed[0::5]
        assert times == sorted(times) and len(set(times)) == len(times)
        for x, y, z, w in zip(packed[1::5], packed[2::5], packed[3::5], packed[4::5], strict=True):
            assert math.hypot(x, y, z, w) == pytest.approx(1.0, abs=1e-4)
        # the state-machine label and the trail survive the swap
        assert "label" in drone and "path" in drone

    def test_point_is_the_fallback_without_a_mesh(self, track):
        drone = track.to_czml()[-1]
        assert "model" not in drone and "orientation" not in drone
        assert drone["point"]["pixelSize"] == 10

    def test_model_scale_must_be_positive(self, track, mesh):
        with pytest.raises(AnalysisError, match="model_scale"):
            track.to_czml(mesh=mesh, model_scale=0.0)


# -- the widget ----------------------------------------------------------------


class TestMissionViewer:
    def test_construction_and_traits(self, track):
        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        packets = json.loads(widget.czml_json)
        assert packets[0]["id"] == "document" and packets[-1]["id"] == "mission-drone"
        assert widget.height_px == 480  # the explicit-height discipline
        assert widget.label == "FlightStates"  # defaults to the track name
        assert widget.imagery == "satellite"  # keyless Esri World Imagery
        assert widget.ion_token == ""  # no token required, ever
        assert widget.picked_json == "[]"
        assert widget.time == 0.0

    def test_overrides(self, track):
        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track, label="sortie 12", height_px=560, ion_token="tok")
        assert widget.label == "sortie 12"
        assert widget.height_px == 560
        assert widget.ion_token == "tok"

    def test_mesh_flies_the_airframe_model(self, track, mesh):
        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track, mesh=mesh, model_scale=3.0)
        drone = json.loads(widget.czml_json)[-1]
        assert drone["model"]["gltf"].startswith("data:model/gltf-binary;base64,")
        assert drone["model"]["scale"] == 3.0
        assert "point" not in drone

    def test_imagery_choices(self, track):
        pytest.importorskip("anywidget")
        for base in ("satellite", "plain", "osm"):
            assert mission3d.mission_viewer(track, imagery=base).imagery == base
        with pytest.raises(AnalysisError, match="imagery must be one of"):
            mission3d.mission_viewer(track, imagery="street")

    def test_esm_cdn_contract(self, track):
        """The documented offline tradeoff, encoded: the pinned CDN URLs
        are baked into the ESM, a failed load prints the offline notice
        (and clears the cached promise so a re-render retries)."""

        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        assert mission3d.CESIUM_VERSION in mission3d.CESIUM_JS_URL
        for url in (mission3d.CESIUM_JS_URL, mission3d.CESIUM_CSS_URL, mission3d.CESIUM_BASE_URL):
            assert url in widget._esm, url
        for token in (
            "CESIUM_BASE_URL",  # workers/assets resolve against the CDN base
            "longeron-mission3d-offline",
            "offline front-end",
            "delete window._longeronCesiumLoad",  # a later render can retry
        ):
            assert token in widget._esm, token

    def test_esm_viewer_contract(self, track):
        """The playback UI, encoded: ion chrome off, timeline + animation
        dial on, tokenless imagery bases, ion unlocks world terrain, the
        camera tracks the drone, and an idle globe renders on demand."""

        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        for token in (
            "baseLayerPicker: false",
            "geocoder: false",
            "sceneModePicker: false",
            "timeline: true",
            "animation: true",
            "shouldAnimate: false",
            "requestRenderMode: true",
            "defaultAccessToken",  # ion_token seam
            "fromWorldTerrain",
            "trackedEntity",
            "CzmlDataSource",
            "change:czml_json",  # in-place mission swap
            "change:height_px",
        ):
            assert token in widget._esm, token

    def test_esm_imagery_contract(self, track):
        """The three tokenless bases, encoded: Esri World Imagery is the
        satellite default (with its required attribution), plain skips
        the base layer and paints a dark-slate globe, osm keeps the
        street tiles."""

        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        for token in (
            "UrlTemplateImageryProvider",
            "services.arcgisonline.com",
            "World_Imagery",
            "Esri, Maxar, Earthstar Geographics",  # the required credit
            "options.baseLayer = false",  # plain: no imagery at all
            "globe.baseColor",
            "fromCssColorString",
            "showGroundAtmosphere = false",
            "OpenStreetMapImageryProvider",  # 'osm' stays available
        ):
            assert token in widget._esm, token

    def test_esm_pick_and_time_seams(self, track):
        """The pick seam (viewer3d idiom) and the bidirectional playhead."""

        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        for token in (
            "ScreenSpaceEventHandler",
            "LEFT_CLICK",
            "picked_json",
            "save_changes",
            "change:time",
            "secondsDifference",
        ):
            assert token in widget._esm, token

    def test_css_height_discipline(self, track):
        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        assert "width: 98%" in widget._css  # never overflows the cell
        assert "box-sizing: border-box" in widget._css
        assert 'model.get("height_px") + "px"' in widget._esm  # explicit height
