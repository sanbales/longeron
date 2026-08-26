"""Mission-flight viewer tests (longeron.analysis.mission3d).

Track synthesis and payload wiring only: the Cesium front-end needs a
browser AND the pinned CDN, so there is deliberately no browser-tier
test here -- a Cesium scene cannot render without live CDN access, and
the flake policy (tests/browser/README.md) forbids network-dependent
assertions.  The ESM contracts (CDN URL, offline fallback, control
wiring) are asserted as structure; rendered-globe evidence is captured
out-of-band against the same ESM.
"""

import json
import math
from datetime import datetime, timezone
from itertools import pairwise

import pytest

import longeron
from longeron.analysis import mission3d
from longeron.analysis._expr import AnalysisError

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


# -- the widget ----------------------------------------------------------------


class TestMissionViewer:
    def test_construction_and_traits(self, track):
        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        packets = json.loads(widget.czml_json)
        assert packets[0]["id"] == "document" and packets[-1]["id"] == "mission-drone"
        assert widget.height_px == 480  # the explicit-height discipline
        assert widget.label == "FlightStates"  # defaults to the track name
        assert widget.ion_token == ""  # no token required, ever
        assert widget.picked_json == "[]"
        assert widget.time == 0.0

    def test_overrides(self, track):
        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track, label="sortie 12", height_px=560, ion_token="tok")
        assert widget.label == "sortie 12"
        assert widget.height_px == 560
        assert widget.ion_token == "tok"

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
        dial on, open imagery by default, ion unlocks world terrain, the
        camera tracks the drone, and an idle globe renders on demand."""

        pytest.importorskip("anywidget")
        widget = mission3d.mission_viewer(track)
        for token in (
            "baseLayerPicker: false",
            "geocoder: false",
            "timeline: true",
            "animation: true",
            "shouldAnimate: false",
            "requestRenderMode: true",
            "OpenStreetMapImageryProvider",
            "defaultAccessToken",  # ion_token seam
            "fromWorldTerrain",
            "trackedEntity",
            "CzmlDataSource",
            "change:czml_json",  # in-place mission swap
            "change:height_px",
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
