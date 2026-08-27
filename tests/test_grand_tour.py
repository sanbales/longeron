"""The grand-tour dashboard composition: panes, wiring, live repaints.

Everything runs kernel-side (the house widgets are dumb painters over
synced traitlets), so the full reaction graph is testable headless:
diagram <-> 3D <-> scoreboard selection, the camera what-if -> occlusion
-> scoreboard recolor chain, the OpenMDAO loiter slider, the Z3 verdict
strip, and the Cesium finale's presence.
"""

import json
from pathlib import Path

import pytest

import longeron
from longeron.analysis import AnalysisError, geometry
from longeron.analysis.grand import ATLANTA_LOOP, drone_scene, grand_dashboard, view_cone_part

pytest.importorskip("ipywidgets")
pytest.importorskip("openmdao")
pytest.importorskip("z3")

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def drone():
    return longeron.load(EXAMPLES / "drone.sysml", cache=False)


@pytest.fixture(scope="module")
def missions():
    return longeron.load(EXAMPLES / "uav_missions.sysml", cache=False)


@pytest.fixture(scope="module")
def dash(drone, missions):
    return grand_dashboard(drone, missions, values={"answer": 42.0})


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
        assert part_map["frame"] == "Drone::QuadCopter#0.chassis"
        assert part_map["motor3"] == "Drone::QuadCopter#0.motors#2"
        keys = {part.get("key") for part in mesh["parts"]}
        assert set(part_map.values()) <= keys
        assert mesh["camera"]  # the occlusion what-if seam

    def test_wrong_shape_is_loud(self, missions):
        with pytest.raises(AnalysisError, match="drone-assembly slot"):
            drone_scene(missions, "UavMissions::IsrPrime")


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
        assert dash.track.duration > 0
        assert json.loads(dash.mission.czml_json)  # the finale pane is baked

    def test_defaults_are_the_demo_mission(self, dash):
        assert dash.camera["elevation"] == -15.0
        assert ATLANTA_LOOP[0][0] == pytest.approx(33.7813)
        assert dash.report["occludedFraction"] == 0.0  # stock camera: clear

    def test_scene_carries_the_view_cone_but_analysis_mesh_does_not(self, dash):
        scene = json.loads(dash.viewer.mesh_json)
        assert scene["parts"][-1]["name"] == "viewCone"
        assert all(part["name"] != "viewCone" for part in dash.mesh["parts"])

    def test_base_values_flow_into_the_scoreboard(self, dash):
        assert dash.scoreboard.values["answer"] == 42.0

    def test_header_names_model_and_score(self, dash):
        assert "Drone::QuadCopter" in dash.header.value
        assert "requirements score" in dash.header.value


class TestSelectionWiring:
    def test_diagram_click_highlights_the_meshes(self, dash):
        dash.diagram.view.selection.ids = ["Drone::QuadCopter::propellers"]
        expected = sorted(dash.part_map[f"prop{i}"] for i in (1, 2, 3, 4))
        assert json.loads(dash.viewer.highlight_json) == expected
        dash.diagram.view.selection.ids = []

    def test_requirement_click_selects_the_scoreboard_cell(self, dash):
        dash.diagram.view.selection.ids = ["Drone::installation::propClearance"]
        assert list(dash.board.selected) == ["Drone::installation::propClearance"]
        # a non-requirement selection clears the board again
        dash.diagram.view.selection.ids = ["Drone::QuadCopter::motors"]
        assert list(dash.board.selected) == []
        dash.diagram.view.selection.ids = []

    def test_scoreboard_click_selects_the_diagram_node(self, dash):
        dash.board.selected = ["Drone::installation::clearView"]
        assert list(dash.diagram.view.selection.ids) == ["Drone::installation::clearView"]
        dash.board.selected = []
        dash.diagram.view.selection.ids = []


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
        dash.azimuth.value = 180.0
        dash.elevation.value = -20.0
        assert dash.report["occludedFraction"] > 0.0
        assert "battery" in dash.report["obstructions"]
        clear_view = _leaf(json.loads(dash.board.nodes_json), "clearView")
        assert clear_view["raw"] == pytest.approx(dash.report["occludedFraction"])
        assert clear_view["utility"] == 0.0  # red
        assert dash.part_map["battery"] in json.loads(dash.viewer.highlight_json)
        assert "occludedFraction" in dash.readout.value and "battery" in dash.readout.value
        # ... and back: the stock camera is clear, the highlight releases
        dash.azimuth.value = 0.0
        dash.elevation.value = -15.0
        assert dash.report["occludedFraction"] == 0.0
        assert json.loads(dash.viewer.highlight_json) == []
        assert _leaf(json.loads(dash.board.nodes_json), "clearView")["utility"] == 1.0

    def test_cone_follows_the_boresight(self, dash):
        dash.elevation.value = -90.0  # straight down
        cone = json.loads(dash.viewer.mesh_json)["parts"][-1]
        apex_y, base_y = cone["vertices"][1], cone["vertices"][-2]
        assert base_y < apex_y  # the base dropped below the apex
        dash.elevation.value = -15.0


class TestSizingStrip:
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
        assert station == pytest.approx(202.9, abs=0.5)
        dash.loiter.value = 15.0

    def test_margin_rows_render(self, dash):
        assert "stationFloor" in dash.sizing_card.value


class TestVerdictStrip:
    def test_design_point_is_sat_with_witness(self, dash):
        assert dash.smt_sat.status == "sat"
        assert dash.smt_sat.witness["stationMinutes"] == pytest.approx(147.4, abs=0.1)
        assert "SAT" in dash.verdicts.value

    def test_what_if_is_unsat_and_names_the_blockers(self, dash):
        assert dash.smt_what_if.status == "unsat"
        assert "IsrPrime::aboveStall" in dash.smt_what_if.core
        assert "aboveStall" in dash.verdicts.value
        assert "240" in dash.verdicts.value

    def test_camera_missing_is_loud(self, drone, missions):
        cameraless = longeron.loads(longeron.to_sysml(drone).replace("part camera : Camera;", ""))
        with pytest.raises(AnalysisError, match="camera"):
            grand_dashboard(cameraless, missions)
