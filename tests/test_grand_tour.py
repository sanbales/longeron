"""The grand-tour dashboard composition: panes, wiring, live repaints.

Everything runs kernel-side (the house widgets are dumb painters over
synced traitlets), so the full reaction graph is testable headless:
containment tree <-> diagram <-> 3D <-> scoreboard selection, the subject
(mission selector, catalog craft clicks, the derived knobs) -> 3D, camera
and flight, the camera what-if -> occlusion -> scoreboard recolor chain,
the OpenMDAO loiter slider, the Z3 verdict strip, and the Cesium finale.
"""

import json
import time
from pathlib import Path

import pytest

import longeron
from longeron.analysis import AnalysisError, geometry, trades
from longeron.analysis.grand import (
    ATLANTA_LOOP,
    DEFAULT_SIZING_CONTEXTS,
    drone_scene,
    grand_dashboard,
    scene_for,
    view_cone_part,
)

pytest.importorskip("ipywidgets")
pytest.importorskip("openmdao")
pytest.importorskip("z3")

EXAMPLES = Path(__file__).parent.parent / "examples"

#: the default subject: the ISR mission's winner (PLAN section 8)
HOME = "FlyingWings::FlyingWingSingle"
TWIN = "ScoutMissions::Catalog::AirframeChoice::flyingWingTwin"


@pytest.fixture(scope="module")
def drone():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def missions():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def dash(drone, missions):
    return grand_dashboard(drone, missions, values={"answer": 42.0})


def _part_extent(mesh, part, axis):
    lo, hi = geometry._part_aabb(next(p for p in mesh["parts"] if p["name"] == part))
    return hi[axis] - lo[axis]


def _wing_span(mesh):
    return _part_extent(mesh, "wing", 2)


def _frame_width(mesh):
    return _part_extent(mesh, "frame", 0)


def _leaf(node, name):
    if node["label"] == name:
        return node
    for child in node["children"]:
        found = _leaf(child, name)
        if found:
            return found
    return None


class TestDroneScene:
    def test_mesh_is_tagged_with_m0_individual_ids(self, drone):
        mesh, part_map = drone_scene(drone)
        assert part_map["frame"] == "Rotorcraft::QuadCopter#0.chassis"
        assert part_map["motor3"] == "Rotorcraft::QuadCopter#0.motors#2"
        keys = {part.get("key") for part in mesh["parts"]}
        assert set(part_map.values()) <= keys
        assert mesh["camera"]  # the occlusion what-if seam

    def test_wrong_shape_is_loud(self, missions):
        with pytest.raises(AnalysisError, match="drone-assembly slot"):
            drone_scene(missions, "ScoutSizing::IsrPrime")


#: every configuration in the DeepScout program that scene_for must
#: resolve: the MultiRotor build family (rotor-disc counts prove the
#: right frame rendered) ...
BUILD_DISCS = {
    "Rotorcraft::TriCopter": 3,
    "Rotorcraft::QuadCopter": 4,
    "Rotorcraft::HexaCopter": 6,
    "Rotorcraft::OctoCopter": 8,
    "Rotorcraft::CoaxX8": 8,
}
#: ... and the fleet airframe shells (distinct part sets prove the
#: right family builder fired)
ROTOR_SHELL = ["frame", "motors", "props", "battery", "esc", "fc", "bay", "camera"]
HULL_SHELL = ["frame", "wing", "tail", "motors", "props", "bay", "battery", "fc", "camera"]
WING_SHELL = ["wing", "winglets", "motors", "props", "bay", "battery", "fc", "camera"]
FLEET_PARTS = {
    "Rotorcraft::BoxQuad": ROTOR_SHELL,
    "Rotorcraft::TeardropQuad": ["frame", "motors", "props", "bay", "battery", "fc", "camera"],
    "Rotorcraft::OpenTri": ROTOR_SHELL,
    "Rotorcraft::HexLifter": ROTOR_SHELL,
    "Rotorcraft::CoaxOcto": ROTOR_SHELL,
    "Rotorcraft::RingOcto": ROTOR_SHELL,
    "WingedVtol::VtolWing": HULL_SHELL,
    "WingedVtol::DartInterceptor": HULL_SHELL,
    "FlyingWings::FlyingWingSingle": WING_SHELL,
    "FlyingWings::FlyingWingTwin": WING_SHELL,
}
#: the wing-borne shells' nose: the body part whose forward extreme
#: carries the camera lens, and the scene axis that points forward (the
#: tail-sitter is baked nose-up in hover, so its nose is +y)
NOSE_BODY = {
    "WingedVtol::VtolWing": ("frame", 1),
    "WingedVtol::DartInterceptor": ("frame", 0),
    "FlyingWings::FlyingWingSingle": ("bay", 0),
    "FlyingWings::FlyingWingTwin": ("bay", 0),
    "FlyingWings::FlyingWingTwinTip": ("bay", 0),
    "TiltRotors::TiltTriWing": ("frame", 0),
}
#: the clickable internals: rendered part -> the shell's own part usage
INTERNAL_USAGES = {"battery": "battery", "fc": "flightController", "camera": "camera"}


class TestSceneFor:
    """The one dispatcher over both craft families -- the config-keyed
    rendering seam behind bind_config_view."""

    @pytest.mark.parametrize(("qname", "discs"), sorted(BUILD_DISCS.items()))
    def test_build_family_bakes_from_its_population(self, drone, qname, discs):
        mesh, part_map = scene_for(drone, qname)
        assert len(mesh["discs"]) == discs
        assert part_map["frame"] == f"{qname}#0.chassis"  # M0 individual keys

    @pytest.mark.parametrize(("qname", "parts"), sorted(FLEET_PARTS.items()))
    def test_fleet_shell_bakes_from_its_attributes(self, drone, qname, parts):
        mesh, part_map = scene_for(drone, qname)
        assert [part["name"] for part in mesh["parts"]] == parts
        # whole-craft identity for the shell, per-usage identity for the
        # clickable internals (battery / flightController / camera)
        expected = {
            name: f"{qname}::{INTERNAL_USAGES[name]}" if name in INTERNAL_USAGES else qname
            for name in parts
        }
        assert part_map == expected
        assert all(part["key"] == expected[part["name"]] for part in mesh["parts"])

    @pytest.mark.parametrize("qname", sorted({*FLEET_PARTS, *NOSE_BODY}))
    def test_fleet_shell_stamps_its_declared_camera(self, drone, qname):
        # every family, not only the multirotor builder, carries the
        # declared camera, so the occlusion measure needs no camera= argument;
        # at the declared boresight no shell sees its own airframe
        mesh, _ = scene_for(drone, qname)
        assert mesh["camera"]["fieldOfView"] > 0.0
        report = geometry.occlusion_report(mesh, engine="mesh")
        assert report["occludedFraction"] == 0.0, report["obstructions"]

    @pytest.mark.parametrize("qname", sorted(NOSE_BODY))
    def test_wing_borne_camera_sits_at_the_nose(self, drone, qname):
        # the lens at the body's forward extreme, on the centreline: the
        # model derives the station from the shell's own geometry
        mesh, _ = scene_for(drone, qname)
        part, axis = NOSE_BODY[qname]
        forward = next(p for p in mesh["parts"] if p["name"] == part)["vertices"][axis::3]
        assert mesh["camera"]["xyz"[axis]] >= max(forward) - 1e-3
        assert mesh["camera"]["z"] == 0.0

    def test_definition_object_and_qname_agree(self, drone):
        by_name, _ = scene_for(drone, "Rotorcraft::TeardropQuad")
        by_def, _ = scene_for(drone, drone.find("Rotorcraft::TeardropQuad"))
        assert by_name == by_def

    def test_unbakeable_shapes_stay_loud(self, drone):
        with pytest.raises(AnalysisError, match="drone-assembly slot"):
            scene_for(drone, "DeepScout::HoverTime")  # a calc def
        with pytest.raises(AnalysisError, match="named definition"):
            scene_for(drone, "Rotorcraft::QuadCopter::motors")  # a usage


class TestViewConePart:
    def test_apex_axis_and_size(self):
        camera = {
            "x": 0.06,
            "y": 0.0,
            "z": 0.0,
            "azimuth": 0.0,
            "elevation": 0.0,
            "fieldOfView": 60.0,
        }
        part = view_cone_part(camera, length=0.5, segments=8)
        assert part["vertices"][:3] == [0.06, 0.0, 0.0]  # apex at the camera
        assert part["vertices"][-3:] == [0.56, 0.0, 0.0]  # base centre down +x
        assert part["opacity"] < 1.0 and "key" not in part  # translucent, inert
        assert len(part["faces"]) == 8 * 2 * 3

    def test_positive_length_required(self):
        with pytest.raises(AnalysisError, match="positive"):
            view_cone_part({"azimuth": 0, "elevation": 0, "fieldOfView": 50}, length=0.0)


class TestComposition:
    def test_panes_present(self, dash):
        assert len(dash.children) == 5  # css + header + linked row + strips + mission
        assert dash.header is dash.children[1]
        assert [type(w).__name__ for w in (dash.diagram, dash.viewer, dash.board)] == [
            "Diagram",
            "MeshViewer",
            "ScoreboardWidget",
        ]
        assert type(dash.mission).__name__ == "MissionViewer"
        assert type(dash.tree).__name__ == "ModelTree"
        row1 = dash.children[2]
        assert list(row1.children) == [dash.tree, dash.diagram, dash.viewer, dash.board]
        assert dash.tree.layout.width == "240px"  # fixed
        # the rest is shared 2 : 1 : 1 from a zero basis.  The side panes keep
        # their aspect, so their width is bounded on both sides
        bounds = [
            (w.layout.flex, w.layout.min_width, w.layout.max_width) for w in row1.children[1:]
        ]
        assert bounds == [
            ("2 1 0", "240px", None),
            ("1 1 0", "280px", "300px"),
            ("1 1 0", "280px", "300px"),
        ]
        # the side panes draw at 1:1 at their floor: the 3D aspect, the viewBox
        assert (dash.viewer.width_px, dash.board.width_px) == (280, 280)
        assert dash.track.duration > 0
        assert json.loads(dash.mission.czml_json)  # the finale pane is baked

    def test_defaults_are_the_demo_mission(self, dash):
        assert dash.camera["elevation"] == -15.0  # the subject's declared camera
        assert ATLANTA_LOOP[0][0] == pytest.approx(33.7813)
        # the declared camera sits at the wing's nose: measured and clear
        assert dash.report["occludedFraction"] == 0.0
        assert _leaf(json.loads(dash.board.nodes_json), "clearView")["utility"] == 1.0

    def test_track_flies_the_subject(self, dash):
        # a fleet shell declares no cruiseTilt, so the subject flies level;
        # the CZML carries the subject's own mesh
        assert dash.track.tilt_deg == 0.0
        assert json.loads(dash.mission.czml_json) == json.loads(
            json.dumps(dash.track.to_czml(mesh=dash.mesh))
        )

    def test_flight_profile_follows_the_subject_shell(self, dash):
        # the rail-launched flying wing banks through its turns ...
        assert dash.track.profile == "wing" and dash.track.turns
        takeoff = dash.track.samples[1:3]
        assert takeoff[0][1:3] != takeoff[1][1:3]  # it climbs out along the first leg
        dash.diagram.view.selection.ids = ["Rotorcraft::TeardropQuad"]
        try:  # ... a quad subject climbs vertically and turns on the spot
            assert dash.track.profile == "rotorcraft" and dash.track.turns == []
            (_t0, *ground), (_t1, *top) = dash.track.samples[1:3]
            assert ground[:2] == top[:2] and top[2] > ground[2]
            assert json.loads(dash.mission.czml_json) == json.loads(
                json.dumps(dash.track.to_czml(mesh=dash.mesh))
            )
        finally:
            dash.diagram.view.selection.ids = [HOME]
            dash.diagram.view.selection.ids = []
        assert dash.track.profile == "wing"

    def test_scene_carries_the_view_cone_but_analysis_mesh_does_not(self, dash):
        scene = json.loads(dash.viewer.mesh_json)
        assert scene["parts"][-1]["name"] == "viewCone"
        assert all(part["name"] != "viewCone" for part in dash.mesh["parts"])

    def test_track_starts_and_ends_on_the_ground(self, dash):
        # heights are above ground: the default flight leaves the surface
        # and comes back to it (the owner saw it start 300 m up in the air)
        first, last = dash.track.samples[0], dash.track.samples[-1]
        assert (first[3], last[3]) == (0.0, 0.0)
        assert [alt for _lat, _lon, alt in ATLANTA_LOOP] == [50.0, 90.0, 80.0, 60.0, 50.0]
        assert max(alt for *_t, alt in dash.track.samples) == 90.0

    def test_base_values_flow_into_the_scoreboard(self, dash):
        assert dash.scoreboard.values["answer"] == 42.0

    def test_header_names_the_subject_and_score(self, dash):
        assert "<b>ISR</b>" in dash.header.value
        assert "<b>flyingWingSingle</b>" in dash.header.value
        assert "battery liion6s6p" in dash.header.value
        assert "requirements score" in dash.header.value
        assert "visiting" not in dash.header.value


class TestSelectionWiring:
    def test_diagram_click_highlights_the_meshes(self, dash):
        dash.diagram.view.selection.ids = [f"{HOME}::battery"]
        assert json.loads(dash.viewer.highlight_json) == [dash.part_map["battery"]]
        assert dash.config_view.current == HOME  # inside the subject: no swap
        dash.diagram.view.selection.ids = []

    def test_click_another_craft_swaps_the_3d_pane(self, dash):
        dash.diagram.view.selection.ids = ["Rotorcraft::HexaCopter::motors"]
        assert dash.config_view.current == "Rotorcraft::HexaCopter"
        assert len(json.loads(dash.viewer.mesh_json)["discs"]) == 6
        dash.diagram.view.selection.ids = ["Rotorcraft::TeardropQuad"]  # a catalog shell
        assert dash.subject.airframe == "teardropQuad"  # ... becomes the subject
        parts = [p for p in json.loads(dash.viewer.mesh_json)["parts"] if "key" in p]
        # the shell carries the craft identity; the clickable internals
        # carry their own part-usage identities
        assert all(part["key"].startswith("Rotorcraft::TeardropQuad") for part in parts)
        assert {p["key"] for p in parts if p["name"] == "fc"} == {
            "Rotorcraft::TeardropQuad::flightController"
        }
        # home again: the subject returns WITH its view cone
        dash.diagram.view.selection.ids = [HOME]
        assert dash.config_view.current == HOME
        assert json.loads(dash.viewer.mesh_json)["parts"][-1]["name"] == "viewCone"
        dash.diagram.view.selection.ids = []

    def test_camera_what_if_never_clobbers_a_visiting_craft(self, dash):
        dash.diagram.view.selection.ids = ["Rotorcraft::HexaCopter"]
        shown = dash.viewer.mesh_json
        dash.elevation.value = -30.0  # measures the SUBJECT craft ...
        assert dash.report["occludedFraction"] >= 0.0  # ... report still updates
        assert dash.viewer.mesh_json is shown  # ... the visiting craft stays
        dash.elevation.value = -15.0
        dash.diagram.view.selection.ids = [HOME]
        dash.diagram.view.selection.ids = []

    def test_requirement_click_selects_the_scoreboard_cell(self, dash):
        dash.diagram.view.selection.ids = ["DeepScout::installation::propClearance"]
        assert list(dash.board.selected) == ["DeepScout::installation::propClearance"]
        # a non-requirement selection clears the board again
        dash.diagram.view.selection.ids = ["Rotorcraft::QuadCopter::motors"]
        assert list(dash.board.selected) == []
        dash.diagram.view.selection.ids = []

    def test_scoreboard_click_selects_the_diagram_node(self, dash):
        dash.board.selected = ["DeepScout::installation::clearView"]
        assert list(dash.diagram.view.selection.ids) == ["DeepScout::installation::clearView"]
        dash.board.selected = []
        dash.diagram.view.selection.ids = []


class TestTreeWiring:
    """The containment tree joins the selection hub in both directions."""

    @staticmethod
    def _home(dash):
        dash.diagram.view.selection.ids = [HOME]
        dash.diagram.view.selection.ids = []
        dash.tree.selected = []

    def test_tree_selection_drives_the_diagram_and_the_3d_pane(self, dash):
        dash.tree.selected = ["Rotorcraft::TeardropQuad"]
        assert list(dash.diagram.view.selection.ids) == ["Rotorcraft::TeardropQuad"]
        assert dash.config_view.current == "Rotorcraft::TeardropQuad"
        assert dash.subject.airframe == "teardropQuad"  # a catalog craft
        self._home(dash)
        assert dash.subject.airframe == "flyingWingSingle"

    def test_tree_selection_of_a_requirement_reaches_the_scoreboard(self, dash):
        dash.tree.selected = ["DeepScout::installation::propClearance"]
        assert list(dash.board.selected) == ["DeepScout::installation::propClearance"]
        self._home(dash)

    def test_diagram_requirement_click_selects_and_reveals_its_tree_row(self, dash, monkeypatch):
        revealed = []
        monkeypatch.setattr(dash.tree, "reveal", revealed.append)
        dash.diagram.view.selection.ids = ["DeepScout::installation::propClearance"]
        assert list(dash.tree.selected) == ["DeepScout::installation::propClearance"]
        assert revealed == ["DeepScout::installation::propClearance"]
        self._home(dash)

    def test_scoreboard_click_selects_the_tree_row(self, dash):
        dash.board.selected = ["DeepScout::installation::clearView"]
        assert list(dash.tree.selected) == ["DeepScout::installation::clearView"]
        dash.board.selected = []
        self._home(dash)

    def test_selection_echo_stops_after_one_hop(self, dash, monkeypatch):
        revealed = []
        monkeypatch.setattr(dash.tree, "reveal", revealed.append)
        tree_writes, diagram_writes = [], []

        def count_tree(change):
            tree_writes.append(list(change["new"]))

        def count_diagram(change):
            diagram_writes.append(list(change["new"]))

        dash.tree.observe(count_tree, "selected")
        dash.diagram.view.selection.observe(count_diagram, "ids")
        try:
            # the diagram draws no row for the harness connection: the
            # diagram selects the owner, and the echo must not move the
            # tree selection to the owner
            dash.tree.selected = ["DeepScout::MultiRotor::powerHarness"]
            assert diagram_writes == [["DeepScout::MultiRotor"]]
            assert tree_writes == [["DeepScout::MultiRotor::powerHarness"]]
            assert revealed == []
            # the other direction: one tree write, one reveal, no second
            # diagram write
            dash.diagram.view.selection.ids = ["Rotorcraft::HexaCopter"]
            assert diagram_writes[1:] == [["Rotorcraft::HexaCopter"]]
            assert tree_writes[1:] == [["Rotorcraft::HexaCopter"]]
            assert revealed == ["Rotorcraft::HexaCopter"]
        finally:
            dash.tree.unobserve(count_tree, "selected")
            dash.diagram.view.selection.unobserve(count_diagram, "ids")
        self._home(dash)


class TestCameraWhatIf:
    def test_slider_calls_the_geometry_measure(self, dash, monkeypatch):
        calls = []
        real = geometry.occlusion_report

        def spy(mesh, camera=None, **kwargs):
            calls.append(dict(camera))
            return real(mesh, camera=camera, **kwargs)

        monkeypatch.setattr(geometry, "occlusion_report", spy)
        dash.elevation.value = -30.0
        assert calls and calls[-1]["elevation"] == -30.0
        assert calls[-1]["azimuth"] == dash.azimuth.value
        dash.elevation.value = -15.0
        assert calls[-1]["elevation"] == -15.0

    def test_occlusion_flips_the_scoreboard_and_paints_offenders(self, dash):
        dash.azimuth.value = 180.0  # looking aft through the wing
        dash.elevation.value = -15.0
        assert dash.report["occludedFraction"] > 0.0
        assert "wing" in dash.report["obstructions"]
        clear_view = _leaf(json.loads(dash.board.nodes_json), "clearView")
        assert clear_view["raw"] == pytest.approx(dash.report["occludedFraction"])
        assert clear_view["utility"] == 0.0  # red
        assert dash.part_map["wing"] in json.loads(dash.viewer.highlight_json)
        assert "occludedFraction" in dash.readout.value and "wing" in dash.readout.value
        # ... and clear: looking up and forward, the highlight releases
        dash.azimuth.value = 0.0
        dash.elevation.value = 30.0
        assert dash.report["occludedFraction"] == 0.0
        assert json.loads(dash.viewer.highlight_json) == []
        assert _leaf(json.loads(dash.board.nodes_json), "clearView")["utility"] == 1.0
        dash.elevation.value = -15.0

    def test_onboard_view_shares_the_camera(self, dash):
        """The Cesium pane's onboard view looks through the subject's
        declared camera at the slider angles; the view mode stays 'follow'."""

        assert dash.mission.view_mode == "follow"
        declared = geometry._camera_params(dash.camera)
        angles = {"elevation": dash.elevation.value, "azimuth": dash.azimuth.value}
        assert dash.mission.onboard_camera == {**declared, **angles}
        dash.elevation.value = 30.0
        dash.azimuth.value = 45.0
        assert dash.mission.onboard_camera == {**declared, "elevation": 30.0, "azimuth": 45.0}
        dash.azimuth.value, dash.elevation.value = angles["azimuth"], angles["elevation"]
        assert dash.mission.onboard_camera == {**declared, **angles}

    def test_cone_follows_the_boresight(self, dash):
        dash.elevation.value = -90.0  # straight down
        cone = json.loads(dash.viewer.mesh_json)["parts"][-1]
        apex_y, base_y = cone["vertices"][1], cone["vertices"][-2]
        assert base_y < apex_y  # the base dropped below the apex
        dash.elevation.value = -15.0


class TestSubjectScoreboard:
    """The scoreboard scores the subject's requirement set, each requirement
    for the instance where it applies."""

    def test_board_scores_the_requirement_set(self, dash):
        assert list(dash.requirements) == [
            "DeepScout::installation",
            "ScoutMissions::MissionRequirements::IsrTasking",
            "ScoutMissions::MissionRequirements::PayloadBayFit",
            "ScoutMissions::StabilityRequirements::PitchStability",
            "ScoutMissions::StabilityRequirements::PitchRollAuthority",
            "ScoutMissions::StabilityRequirements::YawStability",
        ]
        roots = [row.qname for row in dash.scoreboard.table() if row.depth == 1]
        assert roots == list(dash.requirements)

    def test_the_isr_winner_measures_its_tasking(self, dash):
        # holding station needs no hover: the tasking applies to the wing
        tasking = _leaf(json.loads(dash.board.nodes_json), "IsrTasking")
        assert tasking["measured"] is True and tasking["utility"] == 1.0

    def test_a_dropdown_change_rescores_the_board(self, dash):
        dash.knobs["minStationMinutes"].value = 240.0
        assert _leaf(json.loads(dash.board.nodes_json), "IsrTasking")["utility"] == 1.0
        dash.knobs["battery"].value = "tattu3s"  # far below 240 min on station
        assert _leaf(json.loads(dash.board.nodes_json), "IsrTasking")["utility"] == 0.0
        dash.knobs["battery"].value = "liion6s6p"
        dash.knobs["minStationMinutes"].value = 25.0
        assert _leaf(json.loads(dash.board.nodes_json), "IsrTasking")["utility"] == 1.0

    def test_the_mission_toggle_rescores_the_board(self, dash):
        dash.mission_toggle.value = "logistics"
        assert "ScoutMissions::MissionRequirements::LogisticsTasking" in dash.requirements
        assert _leaf(json.loads(dash.board.nodes_json), "LogisticsTasking") is not None
        dash.mission_toggle.value = "ISR"
        dash.diagram.view.selection.ids = [HOME]
        dash.diagram.view.selection.ids = []
        assert _leaf(json.loads(dash.board.nodes_json), "IsrTasking") is not None


class TestSizingStrip:
    def test_the_history_waits_for_maximize(self, dash):
        # first in the class: no maximize click has run on this fixture yet
        assert "run maximize to see the driver's path" in dash.sizing_history.value
        assert "active flags appear after maximize" in dash.sizing_table.value

    def test_the_table_follows_the_slider(self, dash):
        dash.loiter.value = 21.0
        table = dash.sizing_table.value
        # loiterSpeed between its model bounds, aboveStall's margin 21 - 11
        assert "<b>21.0</b>" in table and ">11<" in table and ">24<" in table
        assert "<b>+10.0</b>" in table and "stationFloor" in table
        dash.loiter.value = 15.0
        assert "<b>15.0</b>" in dash.sizing_table.value

    def test_loiter_slider_reruns_the_problem(self, dash):
        dash.loiter.value = 15.0
        at_15 = float(dash.problem.problem.get_val("stationMinutes")[0])
        dash.loiter.value = 21.0
        at_21 = float(dash.problem.problem.get_val("stationMinutes")[0])
        assert at_21 < at_15  # loitering at transit speed burns the battery
        assert f"{at_21:.1f}" in dash.sizing_card.value
        dash.loiter.value = 15.0

    def test_optimize_snaps_the_slider_to_the_optimum(self, dash):
        dash.loiter.value = 16.0
        dash.optimize.click()
        assert dash.loiter.value == pytest.approx(11.0)  # the stall floor binds
        station = float(dash.problem.problem.get_val("stationMinutes")[0])
        assert station == pytest.approx(279.7, abs=0.5)
        dash.loiter.value = 15.0

    def test_maximize_fills_the_history_and_the_active_flags(self, dash):
        dash.loiter.value = 16.0
        dash.optimize.click()
        history = dash.sizing_history.value
        assert "driver iterations" in history and "stationMinutes (maximized)" in history
        assert "<b>279.7</b>" in history and "<polyline" in history
        assert "aboveStall: margin +0.00" in history  # the bound it reaches
        table = dash.sizing_table.value
        rows = {row.split("</td>")[0]: row for row in table.split('<tr><td title="')[1:]}
        assert "&#9679;" in rows['loiterSpeed">loiterSpeed'] and "<b>11.0</b>" in table
        assert "&#9679;" in rows['aboveStall">aboveStall']
        assert "&#9679;" not in rows['belowCruise">belowCruise']
        dash.loiter.value = 15.0

    def test_the_n2_matrix_marks_the_connections(self, dash):
        n2 = dash.sizing_n2.value
        assert "12 components" in n2 and "<svg" in n2
        # the drag feeds the cruise power: a mark titled with the variable
        assert "dragArea: Aerodynamics.dragArea_comp -&gt; Propulsion.loiterPowerW_comp" in n2
        for group in ("Aerodynamics", "Structures", "Propulsion", "Performance"):
            assert f"&#9632; {group}</span>" in n2

    def test_margin_rows_render(self, dash):
        assert "stationFloor" in dash.sizing_card.value

    def test_bounds_come_from_the_sizing_context(self, dash):
        # IsrPrime's aboveStall / belowCruise asserts: the model states 11..24
        assert (dash.loiter.min, dash.loiter.max) == (11.0, 24.0)
        design_vars = dash.optimum.problem.model.get_design_vars()
        (bounds,) = design_vars.values()
        assert (float(bounds["lower"]), float(bounds["upper"])) == (11.0, 24.0)
        assert "ScoutSizing::IsrPrime" in dash.sizing_title.value
        assert "ScoutSizing::IsrStation" in dash.verdict_title.value

    def test_a_mission_without_a_context_shows_an_honest_absence(self, dash):
        isr_problem = dash.problem
        dash.mission_toggle.value = "logistics"
        assert dash.problem is None and dash.loiter is None and dash.smt_sat is None
        assert dash.sizing_history is None and dash.sizing_table is None and dash.sizing_n2 is None
        assert "no context for logistics" in dash.sizing_title.value
        assert "no context for logistics" in dash.verdict_title.value
        assert dash.sizing_contexts == {"ISR": DEFAULT_SIZING_CONTEXTS["ISR"]}
        dash.mission_toggle.value = "ISR"
        assert dash.problem is isr_problem  # built once per mission
        dash.diagram.view.selection.ids = [HOME]
        dash.diagram.view.selection.ids = []


class TestVerdictStrip:
    def test_design_point_is_sat_with_witness(self, dash):
        assert dash.smt_sat.status == "sat"
        assert dash.smt_sat.witness["stationMinutes"] == pytest.approx(200.4, abs=0.1)
        assert "SAT" in dash.verdicts.value

    def test_what_if_is_unsat_and_names_the_blockers(self, dash):
        assert dash.smt_what_if.status == "unsat"
        assert "IsrPrime::aboveStall" in dash.smt_what_if.core
        assert "aboveStall" in dash.verdicts.value
        assert "420" in dash.verdicts.value

    def test_camera_missing_is_an_honest_absence(self, drone):
        # the open tri declares `part camera : Camera;`: without it the
        # camera card says so and the occlusion leaf stays unmeasured
        cameraless = longeron.loads(longeron.to_sysml(drone).replace("part camera : Camera;", ""))
        dash = grand_dashboard(cameraless, airframe="openTri")
        assert dash.camera is None and dash.report == {}
        assert "declares no camera" in dash.readout.value
        assert "no camera" in dash.header.value
        assert _leaf(json.loads(dash.board.nodes_json), "clearView")["measured"] is False


class TestSubject:
    """The subject (mission, airframe, selection, overrides) drives the 3D
    pane, the camera what-if, the knobs and the flight."""

    @staticmethod
    def _home(dash):
        dash.mission_toggle.value = "ISR"
        dash.diagram.view.selection.ids = [HOME]
        dash.diagram.view.selection.ids = []

    def test_default_subject_is_the_isr_winner(self, dash):
        assert (dash.subject.mission, dash.subject.airframe) == ("ISR", "flyingWingSingle")
        assert dash.craft == HOME and dash.config_view.current == HOME
        assert dash.architecture.verified
        assert dash.architecture.metrics["stationMinutes"] == pytest.approx(274.6, abs=0.05)
        assert "stationMinutes" in dash.subject_card.value

    def test_knobs_come_from_the_model(self, dash):
        assert list(dash.knobs) == [
            "sensor",
            "motors",
            "props",
            "battery",
            "material",
            "minStationMinutes",
            # the flying wing's own range asserts, each an input that
            # reaches stationMinutes (rule 8 of analysis.knobs)
            "airframe.wingSpan",
            "airframe.wingChord",
            "airframe.loiterSpeed",
        ]
        assert dash.knob_set.skipped == ()
        # every airframe slider moves the mission metric, measured off the model
        study, mix = dash.studies["ISR"], dash.subject.mix()
        base = study.evaluate(mix).metrics["stationMinutes"]
        for knob in dash.knob_set.sliders[1:]:
            moved = study.evaluate(mix, {knob.name: knob.high}).metrics["stationMinutes"]
            assert moved != pytest.approx(base, rel=1e-6), knob.name
        assert dash.knobs["battery"].value == dash.subject.selection["battery"]
        slider = dash.knobs["minStationMinutes"]
        assert (slider.min, slider.max, slider.value) == (25.0, 240.0, 25.0)

    def test_catalog_click_changes_subject_mesh_and_remeasures_the_camera(self, dash, monkeypatch):
        measured = []
        real = geometry.occlusion_report

        def spy(mesh, camera=None, **kwargs):
            measured.append(mesh)
            return real(mesh, camera=camera, **kwargs)

        monkeypatch.setattr(geometry, "occlusion_report", spy)
        mesh0 = dash.viewer.mesh_json
        dash.diagram.view.selection.ids = [TWIN]
        assert dash.subject.airframe == "flyingWingTwin"
        assert dash.craft == "FlyingWings::FlyingWingTwin"
        assert dash.config_view.current == dash.craft
        assert dash.viewer.mesh_json != mesh0
        assert "view cone clear of the airframe" in dash.readout.value  # the twin's nose camera
        assert measured[-1] is dash.mesh  # the camera what-if measures the subject
        angles = {"elevation": dash.elevation.value, "azimuth": dash.azimuth.value}
        twin_camera = {**geometry._camera_params(dash.camera), **angles}
        assert dash.mission.onboard_camera == twin_camera  # ... and the onboard view
        # the preset filled the other points; the old subject scene is gone
        assert dash.knobs["battery"].value == dash.subject.selection["battery"]
        assert HOME not in dash.config_view.scenes
        assert dash.config_view.scenes[dash.craft][0] is dash.mesh
        self._home(dash)
        assert dash.subject.airframe == "flyingWingSingle"

    def test_dropdown_change_rewrites_the_mesh_and_keeps_the_others(self, dash):
        before = dict(dash.subject.selection)
        mesh0, czml0 = dash.viewer.mesh_json, dash.mission.czml_json
        dash.knobs["battery"].value = "tattu16000"
        assert dash.subject.selection == {**before, "battery": "tattu16000"}
        assert dash.subject.airframe == "flyingWingSingle"
        assert dash.viewer.mesh_json != mesh0
        assert dash.mission.czml_json != czml0  # the flight flies the new mesh
        assert dash.architecture.selection["battery"] == "tattu16000"
        dash.knobs["battery"].value = before["battery"]
        assert dash.subject.selection == before

    def test_build_configuration_click_only_visits(self, dash):
        subject = dash.subject
        dash.diagram.view.selection.ids = ["Rotorcraft::QuadCopter"]
        assert dash.subject == subject
        assert dash.config_view.current == "Rotorcraft::QuadCopter"
        assert "visiting <b>Rotorcraft::QuadCopter</b>" in dash.header.value
        assert "The subject did not change." in dash.header.value
        self._home(dash)
        assert "visiting" not in dash.header.value

    def test_slider_change_reaches_the_trade_study_override(self, dash, monkeypatch):
        calls = []
        real = trades.TradeStudy.evaluate

        def spy(study, selection, overrides=None):
            calls.append(dict(overrides or {}))
            return real(study, selection, overrides)

        monkeypatch.setattr(trades.TradeStudy, "evaluate", spy)
        dash.knobs["minStationMinutes"].value = 240.0
        assert calls[-1] == {"minStationMinutes": 240.0}
        assert dash.subject.overrides == {"minStationMinutes": 240.0}
        assert dash.architecture.verified  # 274.6 min clears the 240 min floor
        dash.knobs["battery"].value = "tattu3s"  # ... a small pack does not
        assert calls[-1] == {"minStationMinutes": 240.0}  # the override survives
        assert "stationReq" in dash.architecture.violations
        dash.knobs["battery"].value = "liion6s6p"
        dash.knobs["minStationMinutes"].value = 25.0
        assert dash.architecture.verified

    def test_span_slider_widens_the_mesh_the_cone_and_the_flight(self, dash, monkeypatch):
        measured, cones = [], []
        real_report, real_cone = geometry.occlusion_report, view_cone_part

        def report_spy(mesh, camera=None, **kwargs):
            measured.append(mesh)
            return real_report(mesh, camera=camera, **kwargs)

        def cone_spy(camera, *, length, **kwargs):
            cones.append(length)
            return real_cone(camera, length=length, **kwargs)

        monkeypatch.setattr(geometry, "occlusion_report", report_spy)
        monkeypatch.setattr("longeron.analysis.grand.view_cone_part", cone_spy)
        span = dash.knobs["airframe.wingSpan"]
        default = span.value
        mesh0, czml0, wing0 = dash.viewer.mesh_json, dash.mission.czml_json, _wing_span(dash.mesh)
        span.value = span.max
        assert dash.subject.overrides["airframe.wingSpan"] == span.max
        assert _wing_span(dash.mesh) / wing0 == pytest.approx(span.max / default)
        shown = json.loads(dash.viewer.mesh_json)
        assert _wing_span(shown) == pytest.approx(_wing_span(dash.mesh))  # the 3D pane
        assert dash.mission.czml_json != czml0  # the Cesium glTF flies the wider wing
        # the camera what-if measures the new mesh, and its cone scales with it
        assert measured[-1] is dash.mesh
        assert cones[-1] == pytest.approx(0.45 * geometry._bounds_diagonal(dash.mesh))
        assert "view cone clear of the airframe" in dash.readout.value
        span.value = default
        assert dash.viewer.mesh_json == mesh0 and dash.mission.czml_json == czml0
        assert len(cones) >= 2 and cones[-1] < cones[-2]

    def test_chord_slider_moves_the_planform_and_the_nose_camera(self, dash):
        chord = dash.knobs["airframe.wingChord"]
        default, camera0 = chord.value, dict(dash.camera)
        chord.value = chord.max
        study = dash.studies["ISR"]
        airframe = study.instance(dash.subject.mix(), dash.subject.overrides).get("airframe")
        assert airframe.slots["wingArea"] == pytest.approx(airframe.slots["wingSpan"] * chord.max)
        root = airframe.slots["rootChord"]
        assert root == pytest.approx(2.0 * chord.max / (1.0 + airframe.slots["taper"]))
        # the camera sits at the nose, which the deeper root chord moves forward
        assert dash.camera["x"] == pytest.approx(0.25 * root + 0.03)
        assert dash.camera["x"] > camera0["x"]
        assert "view cone clear of the airframe" in dash.readout.value
        chord.value = default
        assert dash.camera == camera0

    def test_fuselage_slider_reshapes_the_vtol_hull(self, dash):
        dash.diagram.view.selection.ids = ["ScoutMissions::Catalog::AirframeChoice::vtolWing"]
        try:
            assert dash.subject.airframe == "vtolWing"
            hull = dash.knobs["airframe.fuselageDiameter"]
            assert _frame_width(dash.mesh) == pytest.approx(hull.value)  # the declared hull
            mesh0 = dash.viewer.mesh_json
            hull.value = hull.max
            assert _frame_width(dash.mesh) == pytest.approx(hull.max)
            assert dash.viewer.mesh_json != mesh0
        finally:
            self._home(dash)

    def test_a_build_configuration_visit_ignores_the_subject_overrides(self, dash):
        span = dash.knobs["airframe.wingSpan"]
        default = span.value
        dash.diagram.view.selection.ids = ["Rotorcraft::QuadCopter"]
        quad = dash.viewer.mesh_json
        self._home(dash)
        span.value = span.max
        dash.diagram.view.selection.ids = ["Rotorcraft::QuadCopter"]
        assert dash.viewer.mesh_json == quad  # the visited craft draws its own shell
        self._home(dash)
        assert _wing_span(dash.mesh) == pytest.approx(span.max)  # the subject keeps its what-if
        span.value = default

    def test_mission_toggle_keeps_the_airframe(self, dash):
        dash.mission_toggle.value = "logistics"
        assert dash.subject.mission == "logistics"
        assert dash.subject.airframe == "flyingWingSingle"
        assert "cargo" in dash.knobs and "sensor" not in dash.knobs
        # logistics flies the cruise, not the loiter: the loiter slider goes
        assert "airframe.loiterSpeed" not in dash.knobs
        assert {s.name: s.reason for s in dash.knob_set.skipped} == {
            "airframe.loiterSpeed": "unreachable"
        }
        assert "<b>logistics</b>" in dash.header.value
        self._home(dash)
        assert dash.subject.mission == "ISR" and "sensor" in dash.knobs

    def test_camera_bounds_come_from_the_camera_case(self, dash):
        # ScoutSurfaces::CameraWhatIf's assume constraints
        assert (dash.elevation.min, dash.elevation.max) == (-90.0, 90.0)
        assert (dash.azimuth.min, dash.azimuth.max) == (-180.0, 180.0)

    def test_each_reaction_stays_under_the_continuous_update_budget(self, dash):
        # PLAN risk: a reaction over 300 ms needs continuous_update=False
        reactions = {
            "dropdown": lambda: setattr(dash.knobs["props"], "value", "apc13x65"),
            "slider": lambda: setattr(dash.knobs["minStationMinutes"], "value", 30.0),
            "camera": lambda: setattr(dash.elevation, "value", -20.0),
        }
        for name, react in reactions.items():
            start = time.perf_counter()
            react()
            assert time.perf_counter() - start < 1.0, name  # CI slack over the 300 ms budget
        dash.elevation.value = -15.0
        dash.knobs["minStationMinutes"].value = 25.0
        dash.knobs["props"].value = "apc11x55"
