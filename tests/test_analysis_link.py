"""The diagram <-> 3D-viewer selection glue: identity resolution and the
traitlets wiring, all headless (browser clicks are simulated by writing
the same traitlets the front-ends write)."""

import json
from pathlib import Path

import pytest

import longeron
from longeron import model as M
from longeron.analysis import geometry, link

pytest.importorskip("anywidget")
pytest.importorskip("ipyelk")

from longeron import diagrams
from longeron.analysis import viewer3d

EXAMPLES = Path(__file__).parent.parent / "examples"

QUAD_MAP = {
    "frame": "Drone::QuadCopter::chassis",
    "motors": "Drone::QuadCopter::rotors",
    "props": "Drone::QuadCopter::rotors",
    "battery": "Drone::QuadCopter::battery",
}

ALL_KEYS = sorted(set(QUAD_MAP.values()))
SCENE_KEYS = [*QUAD_MAP.values(), "esc"]


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load(EXAMPLES / "drone.sysml")


def _quad_mesh():
    return geometry.drone_geometry(
        prop_diameter_in=9.0, motor_mass=0.06, battery_mass=0.38, esc_mass=0.012
    )


@pytest.fixture()
def linked(drone_model):
    structure = diagrams.structure_diagram(drone_model)
    viewer = viewer3d.mesh_viewer(_quad_mesh(), label="quad")
    unlink = link.link_selection(structure, viewer, drone_model, part_map=QUAD_MAP)
    return structure, viewer, unlink


class TestSelectionKeys:
    """The pure resolution semantics, no widgets involved."""

    def resolve(self, model, qnames):
        elements = [model.find(q) for q in qnames]
        assert all(e is not None for e in elements)
        return link.selection_keys(model, elements, SCENE_KEYS)

    def test_usage_matches_its_own_key(self, drone_model):
        assert self.resolve(drone_model, ["Drone::QuadCopter::rotors"]) == {
            "Drone::QuadCopter::rotors"
        }

    def test_container_matches_the_nested_keys(self, drone_model):
        assert self.resolve(drone_model, ["Drone::QuadCopter"]) == set(ALL_KEYS)
        assert self.resolve(drone_model, ["Drone"]) == set(ALL_KEYS)

    def test_definition_matches_every_usage_typed_by_it(self, drone_model):
        assert self.resolve(drone_model, ["Drone::Rotor"]) == {"Drone::QuadCopter::rotors"}
        assert self.resolve(drone_model, ["Drone::Frame"]) == {"Drone::QuadCopter::chassis"}
        assert isinstance(drone_model.find("Drone::Rotor"), M.Definition)

    def test_unrelated_selection_matches_nothing(self, drone_model):
        assert self.resolve(drone_model, ["Drone::HoverTime"]) == set()
        assert link.selection_keys(drone_model, [], SCENE_KEYS) == set()

    def test_untagged_names_only_match_themselves(self, drone_model):
        # a bare part name is not a qualified name: model selections
        # never reach it, so an untagged scene stays inert
        assert self.resolve(drone_model, ["Drone::QuadCopter"]) == set(ALL_KEYS)
        esc = link.selection_keys(drone_model, [drone_model.find("Drone")], ["esc"])
        assert esc == set()


class TestLinkSelection:
    def test_part_map_tags_the_viewer_mesh_in_place(self, linked):
        _structure, viewer, _unlink = linked
        keys = [p.get("key") for p in json.loads(viewer.mesh_json)["parts"]]
        assert keys == [*QUAD_MAP.values(), None]  # esc stays untagged

    def test_selection_drives_the_highlight(self, linked):
        structure, viewer, _unlink = linked
        structure.view.selection.ids = ["Drone::Rotor"]
        assert json.loads(viewer.highlight_json) == ["Drone::QuadCopter::rotors"]
        structure.view.selection.ids = ["Drone::QuadCopter"]
        assert json.loads(viewer.highlight_json) == ALL_KEYS

    def test_no_match_clears_instead_of_dimming_everything(self, linked):
        structure, viewer, _unlink = linked
        structure.view.selection.ids = ["Drone::Rotor"]
        structure.view.selection.ids = ["Drone::HoverTime"]
        assert viewer.highlight_json == "[]"
        structure.view.selection.ids = ["Drone::Rotor"]
        structure.view.selection.ids = []
        assert viewer.highlight_json == "[]"

    def test_pick_selects_the_diagram_node_and_round_trips(self, linked):
        structure, viewer, _unlink = linked
        viewer.picked_json = json.dumps(["Drone::QuadCopter::battery"])
        assert list(structure.view.selection.ids) == ["Drone::QuadCopter::battery"]
        # the diagram selection then drives the forward path back to 3D
        assert json.loads(viewer.highlight_json) == ["Drone::QuadCopter::battery"]

    def test_pick_of_untagged_or_background_clears(self, linked):
        structure, viewer, _unlink = linked
        viewer.picked_json = json.dumps(["Drone::QuadCopter::battery"])
        viewer.picked_json = json.dumps(["esc"])  # no model identity
        assert list(structure.view.selection.ids) == []
        assert viewer.highlight_json == "[]"

    def test_unlink_stops_both_directions(self, linked):
        structure, viewer, unlink = linked
        structure.view.selection.ids = ["Drone::Rotor"]
        unlink()
        assert viewer.highlight_json == "[]"  # cleared on disposal
        structure.view.selection.ids = ["Drone::QuadCopter::battery"]
        assert viewer.highlight_json == "[]"
        viewer.picked_json = json.dumps(["Drone::QuadCopter::rotors"])
        assert list(structure.view.selection.ids) == ["Drone::QuadCopter::battery"]
        unlink()  # idempotent

    def test_link_without_part_map_leaves_the_scene_inert(self, drone_model):
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(_quad_mesh())
        unlink = link.link_selection(structure, viewer, drone_model)
        assert all("key" not in p for p in json.loads(viewer.mesh_json)["parts"])
        structure.view.selection.ids = ["Drone::QuadCopter"]
        assert viewer.highlight_json == "[]"
        unlink()

    def test_compare_mode_tags_both_meshes(self, drone_model):
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(_quad_mesh(), _quad_mesh(), label="a", label_b="b")
        unlink = link.link_selection(structure, viewer, drone_model, part_map=QUAD_MAP)
        for trait in ("mesh_json", "mesh_b_json"):
            parts = json.loads(getattr(viewer, trait))["parts"]
            assert [p.get("key") for p in parts] == [*QUAD_MAP.values(), None]
        structure.view.selection.ids = ["Drone::QuadCopter::battery"]
        assert json.loads(viewer.highlight_json) == ["Drone::QuadCopter::battery"]
        unlink()
