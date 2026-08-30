"""The time seam (longeron.widgets.time): one clock, many views.

Everything here is kernel-side truth: the clock's fixpoint discipline,
the timebase's alignment ladder (scalar / per-step / model-stated
durations, and the honest step-only refusal), and ``link_time``'s
no-echo fan-out over real widget traits -- mirroring how the selection
seam is tested without a browser.  The scrubber's and the Cesium
bridge's front-end halves (local integration, bounded-drift snapping)
are proven in the browser tier (tests/browser/test_browser_timeseam.py).
"""

import json
from datetime import datetime, timezone

import pytest

import longeron
from longeron import replay
from longeron.analysis import mission3d
from longeron.widgets.time import (
    _TOLERANCE,
    Clock,
    Timebase,
    link_time,
    step_seconds,
    time_scrubber,
)

WAYPOINTS = [
    (33.7813, -84.3833, 350.0),
    (33.7885, -84.3785, 390.0),
    (33.7900, -84.3695, 380.0),
]

# the flagship recording: the go-around sortie (SortieStates re-enters
# airborne past the launch guard; each climb-out burns 30% battery)
SORTIE_MODEL = """
package Sortie {
    state def SortieStates {
        attribute battery : Integer := 100;
        entry; then idle;
        state idle;
        transition first idle accept launch if battery >= 30 then airborne;
        state airborne {
            entry assign battery := battery - 30;
        }
        transition first airborne accept land then idle;
        transition first airborne accept goAround then airborne;
    }
}
"""
TIMED_EVENTS = ["launch", 45.0, "goAround", 45.0, "goAround", 45.0, "goAround", 30.0, "land", 5.0]
STEP_EVENTS = ["launch", "goAround", "goAround", "goAround"]


@pytest.fixture(scope="module")
def interp():
    return longeron.Interpreter(longeron.loads(SORTIE_MODEL))


@pytest.fixture(scope="module")
def timed_timeline(interp):
    return replay.record_timeline(interp, "Sortie::SortieStates", TIMED_EVENTS)


@pytest.fixture(scope="module")
def step_timeline(interp):
    return replay.record_timeline(interp, "Sortie::SortieStates", STEP_EVENTS)


@pytest.fixture(scope="module")
def timed_track(timed_timeline):
    return mission3d.track_from_timeline(
        timed_timeline, waypoints=WAYPOINTS, phases={"airborne": "route"}
    )


# ---------------------------------------------------------------------------
# the clock
# ---------------------------------------------------------------------------


class TestClock:
    def test_defaults(self):
        clock = Clock(span=(0.0, 170.0))
        assert clock.t == 0.0
        assert clock.playing is False
        assert clock.rate == 1.0
        assert clock.span == (0.0, 170.0)
        assert clock.step_mode is False

    def test_span_must_be_ordered(self):
        with pytest.raises(ValueError, match="ordered"):
            Clock(span=(10.0, 0.0))

    def test_seek_clamps_into_the_span(self):
        clock = Clock(span=(0.0, 100.0))
        clock.seek(-5.0)
        assert clock.t == 0.0
        clock.seek(250.0)
        assert clock.t == 100.0

    def test_initial_t_clamps_too(self):
        assert Clock(span=(10.0, 20.0), t=5.0).t == 10.0
        assert Clock(span=(10.0, 20.0), t=15.0).t == 15.0

    def test_seek_coalesces_within_the_json_quantum(self):
        clock = Clock(span=(0.0, 100.0))
        clock.seek(50.0)
        changes: list = []
        clock.observe(changes.append)
        clock.seek(50.0 + _TOLERANCE / 2)  # inside the quantum: no fan-out
        assert changes == []
        clock.seek(50.5)
        assert [c["name"] for c in changes] == ["t"]

    def test_observe_delivers_traitlets_shaped_changes(self):
        clock = Clock(span=(0.0, 100.0))
        changes: list = []
        clock.observe(changes.append)
        clock.seek(10.0)
        assert changes == [{"name": "t", "old": 0.0, "new": 10.0, "owner": clock}]

    def test_unobserve_detaches(self):
        clock = Clock(span=(0.0, 100.0))
        changes: list = []
        unobserve = clock.observe(changes.append)
        unobserve()
        unobserve()  # idempotent
        clock.seek(10.0)
        assert changes == []

    def test_play_pause_are_idempotent_and_fan_out_on_the_flip(self):
        clock = Clock(span=(0.0, 100.0))
        changes: list = []
        clock.observe(changes.append)
        clock.play()
        clock.play()
        clock.pause()
        clock.pause()
        assert [(c["name"], c["new"]) for c in changes] == [("playing", True), ("playing", False)]

    def test_rate_changes_mid_play(self):
        clock = Clock(span=(0.0, 100.0))
        clock.play()
        changes: list = []
        clock.observe(changes.append)
        clock.set_rate(4.0)
        assert clock.playing is True  # a rate change never touches transport
        assert clock.rate == 4.0
        clock.set_rate(4.0)  # equal: coalesced
        assert [c["name"] for c in changes] == ["rate"]

    def test_rate_must_be_nonzero_and_finite(self):
        clock = Clock(span=(0.0, 100.0))
        with pytest.raises(ValueError, match="nonzero"):
            clock.set_rate(0.0)
        with pytest.raises(ValueError, match="nonzero"):
            clock.set_rate(float("nan"))
        clock.set_rate(-2.0)  # the Cesium shuttle plays backwards
        assert clock.rate == -2.0

    def test_property_setters_delegate(self):
        clock = Clock(span=(0.0, 100.0))
        clock.t = 42.0
        clock.playing = True
        clock.rate = 8.0
        assert (clock.t, clock.playing, clock.rate) == (42.0, True, 8.0)
        clock.playing = False
        assert clock.playing is False


# ---------------------------------------------------------------------------
# the step axis (the alignment ladder)
# ---------------------------------------------------------------------------


class TestStepSeconds:
    def test_scalar_is_uniform_and_synthetic(self):
        seconds, stated = step_seconds(5, 10.0)
        assert seconds == [0.0, 10.0, 20.0, 30.0, 40.0]
        assert stated == [False] * 4

    def test_sequence_is_per_step_and_stated(self):
        seconds, stated = step_seconds(4, [45.0, 45.0, 30.0])
        assert seconds == [0.0, 45.0, 90.0, 120.0]
        assert stated == [True] * 3

    def test_sequence_extras_are_ignored(self):
        seconds, _stated = step_seconds(3, [1.0, 2.0, 99.0, 99.0])
        assert seconds == [0.0, 1.0, 3.0]

    def test_short_sequence_is_refused(self):
        with pytest.raises(ValueError, match="at least 3 durations"):
            step_seconds(4, [45.0, 45.0])

    def test_mapping_states_some_and_synthesizes_the_gaps(self):
        seconds, stated = step_seconds(4, {0: 45.0, 2: 30.0})
        assert seconds == [0.0, 45.0, 55.0, 85.0]  # the gap gets the 10 s default
        assert stated == [True, False, True]

    def test_mapping_stray_keys_are_refused(self):
        with pytest.raises(ValueError, match="interval indices"):
            step_seconds(4, {7: 45.0})

    def test_nonpositive_durations_are_refused(self):
        with pytest.raises(ValueError, match="positive"):
            step_seconds(3, 0.0)
        with pytest.raises(ValueError, match="positive"):
            step_seconds(3, [10.0, -1.0])

    def test_degenerate_step_counts(self):
        assert step_seconds(1, 10.0) == ([0.0], [])
        assert step_seconds(0, 10.0) == ([0.0], [])


# ---------------------------------------------------------------------------
# the timebase
# ---------------------------------------------------------------------------


class TestTimebase:
    def test_timed_span_is_the_recorded_span(self, timed_timeline):
        base = Timebase(timed_timeline)
        assert base.span == (0.0, 170.0)
        assert base.step_mode is False

    def test_step_span_is_the_step_index(self, step_timeline):
        base = Timebase(step_timeline)
        assert base.step_mode is True
        assert base.span == (0.0, float(step_timeline.n_steps - 1))

    def test_step_track_without_seconds_refuses_the_globe(self, step_timeline, timed_track):
        with pytest.raises(ValueError, match="refusing the globe"):
            Timebase(step_timeline, track=timed_track)

    def test_step_track_with_seconds_opts_in(self, step_timeline):
        track = mission3d.track_from_timeline(
            step_timeline, waypoints=WAYPOINTS, phases={"airborne": "route"}, seconds_per_step=10.0
        )
        base = Timebase(step_timeline, track=track, seconds_per_step=10.0)
        assert base.seconds_at(2.0) == 20.0
        assert base.axis_at(20.0) == 2.0

    def test_timed_with_seconds_per_step_is_refused(self, timed_timeline):
        with pytest.raises(ValueError, match="already has a seconds axis"):
            Timebase(timed_timeline, seconds_per_step=10.0)

    def test_per_step_mapping_is_piecewise(self, step_timeline):
        base = Timebase(step_timeline, seconds_per_step={0: 45.0, 1: 45.0})
        # intervals: 45 (stated), 45 (stated), then 10 s synthetic gaps
        assert base.seconds_at(1.0) == 45.0
        assert base.seconds_at(1.5) == 67.5
        assert base.axis_at(67.5) == 1.5
        assert base.seconds_at(3.0) == 100.0

    def test_seconds_at_identity_when_timed(self, timed_timeline):
        base = Timebase(timed_timeline)
        assert base.seconds_at(123.4) == 123.4
        assert base.axis_at(123.4) == 123.4

    def test_step_only_has_no_seconds_axis(self, step_timeline):
        base = Timebase(step_timeline)
        with pytest.raises(ValueError, match="no seconds axis"):
            base.seconds_at(1.0)

    def test_events_at_is_closed_on_both_ends(self, timed_timeline):
        base = Timebase(timed_timeline)
        events = base.events_at(45.0, 135.0)
        assert [fired.t for fired in events] == [45.0, 90.0, 135.0]
        assert all(fired.event == "goAround" for fired in events)

    def test_env_at_uses_step_semantics(self, timed_timeline):
        base = Timebase(timed_timeline)
        assert base.env_at(-1.0) == {}
        assert base.env_at(0.0) == {"battery": 70}  # the same-instant flip: latest wins
        assert base.env_at(100.0) == {"battery": 10}
        assert base.env_at(170.0) == {"battery": -20}

    def test_phase_at_names_the_driving_state(self, timed_timeline, timed_track):
        base = Timebase(timed_timeline, track=timed_track)
        assert base.phase_at(100.0) == ("route", "Sortie::SortieStates::airborne")
        assert base.phase_at(168.0) == ("ground", "Sortie::SortieStates::idle")
        assert base.phase_at(170.0) == ("ground", "Sortie::SortieStates::idle")  # the last end
        assert base.phase_at(999.0) is None

    def test_phase_at_without_a_track_is_none(self, timed_timeline):
        assert Timebase(timed_timeline).phase_at(10.0) is None

    def test_synthetic_intervals_label_only_the_gaps(self, step_timeline):
        # scalar: everything synthetic, merged into one run
        assert Timebase(step_timeline, seconds_per_step=10.0).synthetic_intervals() == [
            (0.0, float(step_timeline.n_steps - 1))
        ]
        # stated everywhere: nothing synthetic
        stated = [10.0] * (step_timeline.n_steps - 1)
        assert Timebase(step_timeline, seconds_per_step=stated).synthetic_intervals() == []
        # mapping: only the gaps
        base = Timebase(step_timeline, seconds_per_step={0: 45.0, 1: 45.0})
        assert base.synthetic_intervals() == [(2.0, float(step_timeline.n_steps - 1))]
        # timed: never synthetic
        assert Timebase(step_timeline).synthetic_intervals() == []


# ---------------------------------------------------------------------------
# per-step durations reach the track builder
# ---------------------------------------------------------------------------


class TestTrackFromTimeline:
    def test_track_shares_the_timeline_axis_when_timed(self, timed_timeline, timed_track):
        assert timed_track.duration == timed_timeline.t_end
        assert timed_track.phases[0][:3] == (0.0, 165.0, "route")

    def test_step_mode_scalar_scales_uniformly(self, step_timeline):
        track = mission3d.track_from_timeline(
            step_timeline, waypoints=WAYPOINTS, phases={"airborne": "route"}, seconds_per_step=10.0
        )
        assert track.duration == 10.0 * (step_timeline.n_steps - 1)

    def test_step_mode_per_step_durations_are_honored(self, step_timeline):
        per_step = [45.0] * (step_timeline.n_steps - 1)
        track = mission3d.track_from_timeline(
            step_timeline,
            waypoints=WAYPOINTS,
            phases={"airborne": "route"},
            seconds_per_step=per_step,
        )
        assert track.duration == 45.0 * (step_timeline.n_steps - 1)

    def test_from_replay_still_records_and_matches(self, interp, timed_track):
        track = mission3d.from_replay(
            interp,
            "Sortie::SortieStates",
            TIMED_EVENTS,
            waypoints=WAYPOINTS,
            phases={"airborne": "route"},
        )
        assert track.samples == timed_track.samples
        assert track.phases == timed_track.phases
        assert track.name == "SortieStates"


# ---------------------------------------------------------------------------
# the model-stated epoch
# ---------------------------------------------------------------------------


EPOCH_MODEL = """
package Field {
    part mission {
        attribute epoch : Time::Iso8601DateTime = "2026-06-21T14:30:00Z";
        part wp0 { attribute lat : Real = 33.7813; attribute lon : Real = -84.3833;
                   attribute alt : Real = 350.0; }
    }
    part bare {
        part wp0 { attribute lat : Real = 33.7813; attribute lon : Real = -84.3833;
                   attribute alt : Real = 350.0; }
    }
    part broken {
        attribute epoch : Time::Iso8601DateTime = "not a date";
    }
}
"""


@pytest.fixture(scope="module")
def field_interp():
    return longeron.Interpreter(longeron.loads(EPOCH_MODEL))


class TestModelEpoch:
    def test_reads_the_stated_epoch_as_aware_utc(self, field_interp):
        epoch = mission3d.model_epoch(field_interp, "Field::mission")
        assert epoch == datetime(2026, 6, 21, 14, 30, tzinfo=timezone.utc)

    def test_absent_epoch_is_none_not_an_error(self, field_interp):
        assert mission3d.model_epoch(field_interp, "Field::bare") is None

    def test_unparseable_epoch_is_loud(self, field_interp):
        from longeron.analysis._expr import AnalysisError

        with pytest.raises(AnalysisError, match="not ISO 8601"):
            mission3d.model_epoch(field_interp, "Field::broken")

    def test_epoch_anchors_the_czml_clock(self, timed_timeline, field_interp):
        epoch = mission3d.model_epoch(field_interp, "Field::mission")
        track = mission3d.track_from_timeline(
            timed_timeline, waypoints=WAYPOINTS, phases={"airborne": "route"}, epoch=epoch
        )
        packets = track.to_czml()
        assert packets[0]["clock"]["interval"] == "2026-06-21T14:30:00Z/2026-06-21T14:32:50Z"


# ---------------------------------------------------------------------------
# link_time: the no-echo fan-out (real widget traits, headless)
# ---------------------------------------------------------------------------

anywidget = pytest.importorskip("anywidget")


def _player(timed_timeline):
    """A ReplayWidget without the diagram bake (traits are the seam)."""

    cls = replay._widget_class()
    return cls(svg="<svg></svg>", timeline_json=timed_timeline.to_json())


@pytest.fixture()
def seam(timed_timeline, timed_track):
    """A linked trio: player + scrubber + globe on one clock."""

    base = Timebase(timed_timeline, track=timed_track)
    player = _player(timed_timeline)
    scrubber = time_scrubber(base)
    globe = mission3d.mission_viewer(timed_track, imagery="plain")
    clock = Clock(span=base.span)
    unlink = link_time(clock, player, scrubber, globe)
    return clock, player, scrubber, globe, unlink


class TestLinkTime:
    def test_clock_seek_fans_out_to_every_view(self, seam):
        clock, player, scrubber, globe, _unlink = seam
        clock.seek(42.0)
        assert player.time == 42.0
        assert scrubber.time == 42.0
        assert globe.time == 42.0

    def test_no_echo_one_hop_each_way(self, seam):
        """One write settles every trait at its first fixpoint."""

        clock, player, scrubber, globe, _unlink = seam
        writes: dict[str, list] = {"player": [], "scrubber": [], "globe": [], "clock": []}
        player.observe(lambda ch: writes["player"].append(ch["new"]), "time")
        scrubber.observe(lambda ch: writes["scrubber"].append(ch["new"]), "time")
        globe.observe(lambda ch: writes["globe"].append(ch["new"]), "time")
        clock.observe(lambda ch: writes["clock"].append(ch["new"]))

        player.time = 60.0  # a front-end scrub on the player
        assert writes == {
            "player": [60.0],  # only the scrub itself: no echo write-back
            "scrubber": [60.0],
            "globe": [60.0],
            "clock": [60.0],
        }

        clock.seek(60.0)  # the fixpoint: nothing moves again
        assert writes["clock"] == [60.0]

    def test_playing_and_rate_ride_the_same_seam(self, seam):
        clock, player, scrubber, globe, _unlink = seam
        scrubber.playing = True
        assert clock.playing is True
        assert globe.playing is True
        assert not player.has_trait("playing")  # the player wires time only
        globe.playing = False  # the Cesium dial pauses
        assert clock.playing is False
        assert scrubber.playing is False
        scrubber.rate = 4.0
        assert clock.rate == 4.0
        assert globe.rate == 4.0

    def test_globe_zero_rate_is_not_a_statement(self, seam):
        clock, _player, _scrubber, globe, _unlink = seam
        globe.rate = 0.0  # "no stated rate": must not reach the clock
        assert clock.rate == 1.0

    def test_link_fans_the_clock_state_out_at_link_time(self, timed_timeline, timed_track):
        base = Timebase(timed_timeline, track=timed_track)
        clock = Clock(span=base.span, rate=2.0)
        clock.seek(50.0)
        globe = mission3d.mission_viewer(timed_track, imagery="plain")
        link_time(clock, globe)
        assert globe.time == 50.0
        assert globe.rate == 2.0
        assert globe.drift_s == 0.25

    def test_unlink_detaches_and_is_idempotent(self, seam):
        clock, player, scrubber, globe, unlink = seam
        unlink()
        unlink()
        clock.seek(99.0)
        assert player.time == 0.0
        assert scrubber.time == 0.0
        assert globe.time == 0.0
        player.time = 33.0
        assert clock.t == 99.0

    def test_rebinding_replaces_the_previous_link(self, timed_timeline):
        player = _player(timed_timeline)
        first = Clock(span=(0.0, 170.0))
        second = Clock(span=(0.0, 170.0))
        link_time(first, player)
        link_time(second, player)  # replaces: a view holds ONE link
        player.time = 25.0
        assert second.t == 25.0
        assert first.t == 0.0  # the replaced link is inert
        second.seek(80.0)
        assert player.time == 80.0

    def test_views_need_a_time_trait(self):
        with pytest.raises(TypeError, match="'time' trait"):
            link_time(Clock(), object())

    def test_kernel_seek_writes_the_player_trait(self, seam):
        """The replay subscription: a clock seek lands on ``time`` (the
        front-end stops its own playback on that write; browser-proven)."""

        clock, player, *_rest = seam
        clock.seek(45.0)
        assert player.time == 45.0


class TestStepModeGlobeBinding:
    def test_refused_without_seconds_per_step(self, step_timeline):
        track = mission3d.track_from_timeline(
            step_timeline, waypoints=WAYPOINTS, phases={"airborne": "route"}, seconds_per_step=10.0
        )
        globe = mission3d.mission_viewer(track, imagery="plain")
        base = Timebase(step_timeline, track=track, seconds_per_step=10.0)
        clock = Clock(span=base.span, step_mode=True)
        with pytest.raises(ValueError, match="refusing the globe"):
            link_time(clock, globe)

    def test_opt_in_scales_the_axis_rate_and_drift(self, step_timeline):
        track = mission3d.track_from_timeline(
            step_timeline, waypoints=WAYPOINTS, phases={"airborne": "route"}, seconds_per_step=10.0
        )
        globe = mission3d.mission_viewer(track, imagery="plain")
        base = Timebase(step_timeline, track=track, seconds_per_step=10.0)
        clock = Clock(span=base.span, step_mode=True)
        link_time(clock, globe, seconds_per_step=10.0)
        clock.seek(2.0)
        assert globe.time == 20.0  # steps -> track seconds
        globe.time = 30.0  # the globe scrubs back in seconds
        assert clock.t == 3.0
        clock.set_rate(2.0)  # 2 steps per wall second
        assert globe.rate == 20.0  # = 20 track seconds per wall second
        assert globe.drift_s == 0.25 * 10.0

    def test_per_step_mapping_is_piecewise_through_the_link(self, step_timeline):
        per_step = {0: 45.0, 1: 45.0}
        track = mission3d.track_from_timeline(
            step_timeline,
            waypoints=WAYPOINTS,
            phases={"airborne": "route"},
            seconds_per_step=per_step,
        )
        globe = mission3d.mission_viewer(track, imagery="plain")
        clock = Clock(span=(0.0, float(step_timeline.n_steps - 1)), step_mode=True)
        link_time(clock, globe, seconds_per_step=per_step)
        clock.seek(1.5)
        assert globe.time == 67.5  # 45 + half of the second 45 s interval
        globe.time = 95.0  # inside the synthetic 10 s tail
        assert clock.t == pytest.approx(2.5)

    def test_non_globe_views_keep_the_step_axis(self, step_timeline):
        base = Timebase(step_timeline)
        scrubber = time_scrubber(base)
        clock = Clock(span=base.span, step_mode=True)
        link_time(clock, scrubber)  # no track, no seconds: steps all the way
        clock.seek(2.0)
        assert scrubber.time == 2.0


# ---------------------------------------------------------------------------
# the scrubber payload
# ---------------------------------------------------------------------------


class TestScrubberSpec:
    def test_timed_spec_carries_ticks_phases_and_telemetry(self, timed_timeline, timed_track):
        scrubber = time_scrubber(Timebase(timed_timeline, track=timed_track))
        spec = json.loads(scrubber.spec_json)
        assert spec["span"] == [0.0, 170.0]
        assert spec["step_mode"] is False
        assert [tick["label"] for tick in spec["ticks"]] == [
            "launch",
            "goAround",
            "goAround",
            "goAround",
            "land",
        ]
        assert spec["phases"][0] == [0.0, 165.0, "route", "Sortie::SortieStates::airborne"]
        assert spec["synthetic"] == []
        assert spec["seconds"] is None
        assert spec["env_steps"][-1] == [165.0, {"battery": -20}]

    def test_step_spec_labels_the_synthetic_segments(self, step_timeline):
        base = Timebase(step_timeline, seconds_per_step={0: 45.0, 1: 45.0})
        spec = json.loads(time_scrubber(base).spec_json)
        assert spec["step_mode"] is True
        assert spec["span"] == [0.0, float(step_timeline.n_steps - 1)]
        assert spec["seconds"][:3] == [0.0, 45.0, 90.0]
        assert spec["synthetic"] == [[2.0, float(step_timeline.n_steps - 1)]]

    def test_widget_trait_defaults(self, timed_timeline):
        scrubber = time_scrubber(Timebase(timed_timeline))
        assert scrubber.time == 0.0
        assert scrubber.playing is False
        assert scrubber.rate == 1.0
        assert scrubber.width_px == 760

    def test_missing_extra_is_loud(self, monkeypatch, timed_timeline):
        import sys

        from longeron.errors import MissingExtraError
        from longeron.widgets import time as time_module

        monkeypatch.setitem(sys.modules, "anywidget", None)
        monkeypatch.setattr(time_module, "_SCRUBBER_CLS", None)
        with pytest.raises(MissingExtraError, match=r"longeron\[replay\]"):
            time_scrubber(Timebase(timed_timeline))


# ---------------------------------------------------------------------------
# the Cesium bridge, kernel side
# ---------------------------------------------------------------------------


class TestCesiumBridgeKernelSide:
    def test_viewer_bridge_traits_default_honestly(self, timed_track):
        globe = mission3d.mission_viewer(timed_track, imagery="plain")
        assert globe.playing is False
        assert globe.rate == 0.0  # "no stated rate": the CZML multiplier rules
        assert globe.drift_s == 0.25

    def test_czml_clock_derives_from_the_clock_span_and_epoch(self, timed_timeline):
        epoch = datetime(2026, 6, 21, 14, 30, tzinfo=timezone.utc)
        track = mission3d.track_from_timeline(
            timed_timeline, waypoints=WAYPOINTS, phases={"airborne": "route"}, epoch=epoch
        )
        clock = Clock(span=Timebase(timed_timeline, track=track).span)
        packets = track.to_czml()
        interval = packets[0]["clock"]["interval"]
        start, stop = interval.split("/")
        assert start == "2026-06-21T14:30:00Z"
        parsed = datetime.fromisoformat(stop.replace("Z", "+00:00"))
        assert (parsed - epoch).total_seconds() == clock.span[1] - clock.span[0]

    def test_bridge_esm_contracts(self):
        """The front-end contracts the kernel relies on, as structure."""

        esm = mission3d._ESM
        assert "change:playing" in esm
        assert "change:rate" in esm
        assert "shouldAnimate" in esm and "multiplier" in esm
        assert "drift_s" in esm
        assert "stage.longeronViewer = viewer" in esm
        assert "setInterval" in esm and "clearInterval" in esm
