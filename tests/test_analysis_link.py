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
    "motors": "Drone::QuadCopter::motors",
    "props": "Drone::QuadCopter::propellers",
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


# per-individual keying: the M0 ids of Drone::QuadCopter's population
# (see longeron.m0.interpret) as stamped on a split-instance mesh
MOTOR_IDS = [f"Drone::QuadCopter#0.motors#{i}" for i in range(4)]
PROP_IDS = [f"Drone::QuadCopter#0.propellers#{i}" for i in range(4)]
INDIVIDUAL_MAP = {
    "frame": "Drone::QuadCopter#0.chassis",
    "battery": "Drone::QuadCopter#0.battery",
    **{f"motor{i + 1}": MOTOR_IDS[i] for i in range(4)},
    **{f"prop{i + 1}": PROP_IDS[i] for i in range(4)},
}
INDIVIDUAL_KEYS = [*INDIVIDUAL_MAP.values(), "esc"]


def _split_mesh():
    return geometry.drone_geometry(
        prop_diameter_in=9.0,
        motor_mass=0.06,
        battery_mass=0.38,
        esc_mass=0.012,
        split_instances=True,
    )


class TestSelectionKeys:
    """The pure resolution semantics, no widgets involved."""

    def resolve(self, model, qnames):
        elements = [model.find(q) for q in qnames]
        assert all(e is not None for e in elements)
        return link.selection_keys(model, elements, SCENE_KEYS)

    def test_usage_matches_its_own_key(self, drone_model):
        assert self.resolve(drone_model, ["Drone::QuadCopter::motors"]) == {
            "Drone::QuadCopter::motors"
        }

    def test_container_matches_the_nested_keys(self, drone_model):
        assert self.resolve(drone_model, ["Drone::QuadCopter"]) == set(ALL_KEYS)
        assert self.resolve(drone_model, ["Drone"]) == set(ALL_KEYS)

    def test_definition_matches_every_usage_typed_by_it(self, drone_model):
        assert self.resolve(drone_model, ["Drone::Motor"]) == {"Drone::QuadCopter::motors"}
        assert self.resolve(drone_model, ["Drone::Frame"]) == {"Drone::QuadCopter::chassis"}
        assert isinstance(drone_model.find("Drone::Motor"), M.Definition)

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
        structure.view.selection.ids = ["Drone::Motor"]
        assert json.loads(viewer.highlight_json) == ["Drone::QuadCopter::motors"]
        structure.view.selection.ids = ["Drone::QuadCopter"]
        assert json.loads(viewer.highlight_json) == ALL_KEYS

    def test_no_match_clears_instead_of_dimming_everything(self, linked):
        structure, viewer, _unlink = linked
        structure.view.selection.ids = ["Drone::Motor"]
        structure.view.selection.ids = ["Drone::HoverTime"]
        assert viewer.highlight_json == "[]"
        structure.view.selection.ids = ["Drone::Motor"]
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
        structure.view.selection.ids = ["Drone::Motor"]
        unlink()
        assert viewer.highlight_json == "[]"  # cleared on disposal
        structure.view.selection.ids = ["Drone::QuadCopter::battery"]
        assert viewer.highlight_json == "[]"
        viewer.picked_json = json.dumps(["Drone::QuadCopter::motors"])
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


class TestIndividualQname:
    """The id-derivation rule: strip each dotted segment's ``#index``,
    join with ``::`` -- an individual belongs to its usage."""

    def test_indexed_individual_derives_its_usage(self):
        assert link.individual_qname("Drone::QuadCopter#0.motors#2") == (
            "Drone::QuadCopter::motors"
        )

    def test_singleton_and_root_derive_too(self):
        # a singleton feature has no index of its own; the root does
        assert link.individual_qname("Drone::QuadCopter#0.chassis") == (
            "Drone::QuadCopter::chassis"
        )
        assert link.individual_qname("Drone::QuadCopter#0") == "Drone::QuadCopter"

    def test_nested_populations_derive_the_nested_usage(self):
        assert link.individual_qname("P::Quad#0.rotors#1.blades#0") == "P::Quad::rotors::blades"

    def test_plain_keys_are_not_individual_ids(self):
        # pure-qname and bare-name keys keep their exact semantics
        assert link.individual_qname("Drone::QuadCopter::motors") is None
        assert link.individual_qname("esc") is None


class TestSelectionKeysOverIndividuals:
    """M1 -> M0 fan-out in the pure resolution semantics: one usage
    (or its typing definition) matches every individual key derived
    from it."""

    def resolve(self, model, qnames):
        elements = [model.find(q) for q in qnames]
        assert all(e is not None for e in elements)
        return link.selection_keys(model, elements, INDIVIDUAL_KEYS)

    def test_usage_matches_all_four_individuals(self, drone_model):
        assert self.resolve(drone_model, ["Drone::QuadCopter::motors"]) == set(MOTOR_IDS)
        assert self.resolve(drone_model, ["Drone::QuadCopter::propellers"]) == set(PROP_IDS)

    def test_definition_matches_through_the_usage(self, drone_model):
        assert self.resolve(drone_model, ["Drone::Motor"]) == set(MOTOR_IDS)
        assert self.resolve(drone_model, ["Drone::Propeller"]) == set(PROP_IDS)

    def test_container_matches_the_whole_population(self, drone_model):
        assert self.resolve(drone_model, ["Drone::QuadCopter"]) == set(INDIVIDUAL_MAP.values())

    def test_unrelated_selection_still_matches_nothing(self, drone_model):
        assert self.resolve(drone_model, ["Drone::HoverTime"]) == set()


class TestPerIndividualLink:
    """The full loop over a split-instance mesh keyed by M0 ids:
    M1 clicks fan out to every individual, M0 picks project back to
    the one M1 node while ``on_pick`` surfaces the individual."""

    @pytest.fixture()
    def individual_linked(self, drone_model):
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(_split_mesh(), label="quad")
        picks: list[list[str]] = []
        unlink = link.link_selection(
            structure, viewer, drone_model, part_map=INDIVIDUAL_MAP, on_pick=picks.append
        )
        return structure, viewer, picks, unlink

    def test_m1_usage_click_lights_all_four_instances(self, individual_linked):
        structure, viewer, _picks, _unlink = individual_linked
        structure.view.selection.ids = ["Drone::QuadCopter::motors"]
        assert json.loads(viewer.highlight_json) == sorted(MOTOR_IDS)

    def test_pick_projects_to_the_usage_and_surfaces_the_individual(self, individual_linked):
        structure, viewer, picks, _unlink = individual_linked
        viewer.picked_json = json.dumps(["Drone::QuadCopter#0.motors#2"])
        # M0 -> M1 is many-to-one: the diagram selects the one usage ...
        assert list(structure.view.selection.ids) == ["Drone::QuadCopter::motors"]
        # ... whose fan-out re-lights all four instance meshes ...
        assert json.loads(viewer.highlight_json) == sorted(MOTOR_IDS)
        # ... while on_pick preserves which individual was hit
        assert picks == [["Drone::QuadCopter#0.motors#2"]]

    def test_background_pick_reports_empty_and_clears(self, individual_linked):
        structure, viewer, picks, _unlink = individual_linked
        viewer.picked_json = json.dumps(["Drone::QuadCopter#0.battery"])
        viewer.picked_json = json.dumps([])
        assert picks == [["Drone::QuadCopter#0.battery"], []]
        assert list(structure.view.selection.ids) == []
        assert viewer.highlight_json == "[]"

    def test_on_pick_fires_without_bidirectional_selection(self, drone_model):
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(_split_mesh())
        picks: list[list[str]] = []
        unlink = link.link_selection(
            structure,
            viewer,
            drone_model,
            part_map=INDIVIDUAL_MAP,
            bidirectional=False,
            on_pick=picks.append,
        )
        viewer.picked_json = json.dumps(["Drone::QuadCopter#0.motors#0"])
        assert picks == [["Drone::QuadCopter#0.motors#0"]]
        assert list(structure.view.selection.ids) == []  # projection stays off
        unlink()

    def test_unlink_silences_on_pick(self, individual_linked):
        _structure, viewer, picks, unlink = individual_linked
        unlink()
        viewer.picked_json = json.dumps(["Drone::QuadCopter#0.motors#1"])
        assert picks == []
