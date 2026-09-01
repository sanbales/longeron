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
from longeron.widgets import viewer3d

EXAMPLES = Path(__file__).parent.parent / "examples"

QUAD_MAP = {
    # chassis and battery are shared equipment: since the TriCopter
    # split, their usages live on the abstract MultiRotor base (motors
    # and the propellers redefinition are the QuadCopter's own)
    "frame": "DeepScout::MultiRotor::chassis",
    "motors": "Rotorcraft::QuadCopter::motors",
    "props": "Rotorcraft::QuadCopter::propellers",
    "battery": "DeepScout::MultiRotor::battery",
}

ALL_KEYS = sorted(set(QUAD_MAP.values()))
SCENE_KEYS = [*QUAD_MAP.values(), "esc"]


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load(EXAMPLES / "deepscout")


def _quad_mesh():
    return geometry.drone_geometry(
        prop_diameter_in=9.0, motor_mass=0.06, battery_mass=0.38, esc_mass=0.012, fc_mass=0.039
    )


@pytest.fixture()
def linked(drone_model):
    structure = diagrams.structure_diagram(drone_model)
    viewer = viewer3d.mesh_viewer(_quad_mesh(), label="quad")
    unlink = link.link_selection(structure, viewer, drone_model, part_map=QUAD_MAP)
    return structure, viewer, unlink


# per-individual keying: the M0 ids of Rotorcraft::QuadCopter's population
# (see longeron.m0.interpret) as stamped on a split-instance mesh
MOTOR_IDS = [f"Rotorcraft::QuadCopter#0.motors#{i}" for i in range(4)]
PROP_IDS = [f"Rotorcraft::QuadCopter#0.propellers#{i}" for i in range(4)]
INDIVIDUAL_MAP = {
    "frame": "Rotorcraft::QuadCopter#0.chassis",
    "battery": "Rotorcraft::QuadCopter#0.battery",
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
        fc_mass=0.039,
        split_instances=True,
    )


class TestSelectionKeys:
    """The pure resolution semantics, no widgets involved."""

    def resolve(self, model, qnames):
        elements = [model.find(q) for q in qnames]
        assert all(e is not None for e in elements)
        return link.selection_keys(model, elements, SCENE_KEYS)

    def test_usage_matches_its_own_key(self, drone_model):
        assert self.resolve(drone_model, ["Rotorcraft::QuadCopter::motors"]) == {
            "Rotorcraft::QuadCopter::motors"
        }

    def test_container_matches_the_nested_keys(self, drone_model):
        # textual nesting: the configuration matches its OWN feature
        # keys, the abstract base matches the shared-equipment keys,
        # and the package matches everything
        assert self.resolve(drone_model, ["Rotorcraft::QuadCopter"]) == {
            "Rotorcraft::QuadCopter::motors",
            "Rotorcraft::QuadCopter::propellers",
        }
        assert self.resolve(drone_model, ["DeepScout::MultiRotor"]) == {
            "DeepScout::MultiRotor::chassis",
            "DeepScout::MultiRotor::battery",
        }
        assert self.resolve(drone_model, ["Rotorcraft"]) | self.resolve(
            drone_model, ["DeepScout"]
        ) == set(ALL_KEYS)

    def test_definition_matches_every_usage_typed_by_it(self, drone_model):
        assert self.resolve(drone_model, ["ScoutParts::F450Kit::Motor"]) == {
            "Rotorcraft::QuadCopter::motors"
        }
        assert self.resolve(drone_model, ["ScoutParts::F450Kit::Frame"]) == {
            "DeepScout::MultiRotor::chassis"
        }
        assert isinstance(drone_model.find("ScoutParts::F450Kit::Motor"), M.Definition)

    def test_unrelated_selection_matches_nothing(self, drone_model):
        assert self.resolve(drone_model, ["DeepScout::HoverTime"]) == set()
        assert link.selection_keys(drone_model, [], SCENE_KEYS) == set()

    def test_untagged_names_only_match_themselves(self, drone_model):
        # a bare part name is not a qualified name: model selections
        # never reach it, so an untagged scene stays inert
        assert self.resolve(drone_model, ["Rotorcraft"]) < set(ALL_KEYS)
        esc = link.selection_keys(drone_model, [drone_model.find("Rotorcraft")], ["esc"])
        assert esc == set()


class TestLinkSelection:
    def test_part_map_tags_the_viewer_mesh_in_place(self, linked):
        _structure, viewer, _unlink = linked
        keys = [p.get("key") for p in json.loads(viewer.mesh_json)["parts"]]
        assert keys == [*QUAD_MAP.values(), None, None]  # esc + fc stay untagged

    def test_selection_drives_the_highlight(self, linked):
        structure, viewer, _unlink = linked
        structure.view.selection.ids = ["ScoutParts::F450Kit::Motor"]
        assert json.loads(viewer.highlight_json) == ["Rotorcraft::QuadCopter::motors"]
        structure.view.selection.ids = ["Rotorcraft::QuadCopter"]
        assert json.loads(viewer.highlight_json) == [
            "Rotorcraft::QuadCopter::motors",
            "Rotorcraft::QuadCopter::propellers",
        ]

    def test_no_match_clears_instead_of_dimming_everything(self, linked):
        structure, viewer, _unlink = linked
        structure.view.selection.ids = ["ScoutParts::F450Kit::Motor"]
        structure.view.selection.ids = ["DeepScout::HoverTime"]
        assert viewer.highlight_json == "[]"
        structure.view.selection.ids = ["ScoutParts::F450Kit::Motor"]
        structure.view.selection.ids = []
        assert viewer.highlight_json == "[]"

    def test_pick_selects_the_diagram_node_and_round_trips(self, linked):
        structure, viewer, _unlink = linked
        viewer.picked_json = json.dumps(["DeepScout::MultiRotor::battery"])
        assert list(structure.view.selection.ids) == ["DeepScout::MultiRotor::battery"]
        # the diagram selection then drives the forward path back to 3D
        assert json.loads(viewer.highlight_json) == ["DeepScout::MultiRotor::battery"]

    def test_pick_of_untagged_or_background_clears(self, linked):
        structure, viewer, _unlink = linked
        viewer.picked_json = json.dumps(["DeepScout::MultiRotor::battery"])
        viewer.picked_json = json.dumps(["esc"])  # no model identity
        assert list(structure.view.selection.ids) == []
        assert viewer.highlight_json == "[]"

    def test_unlink_stops_both_directions(self, linked):
        structure, viewer, unlink = linked
        structure.view.selection.ids = ["ScoutParts::F450Kit::Motor"]
        unlink()
        assert viewer.highlight_json == "[]"  # cleared on disposal
        structure.view.selection.ids = ["DeepScout::MultiRotor::battery"]
        assert viewer.highlight_json == "[]"
        viewer.picked_json = json.dumps(["Rotorcraft::QuadCopter::motors"])
        assert list(structure.view.selection.ids) == ["DeepScout::MultiRotor::battery"]
        unlink()  # idempotent

    def test_link_without_part_map_leaves_the_scene_inert(self, drone_model):
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(_quad_mesh())
        unlink = link.link_selection(structure, viewer, drone_model)
        assert all("key" not in p for p in json.loads(viewer.mesh_json)["parts"])
        structure.view.selection.ids = ["Rotorcraft::QuadCopter"]
        assert viewer.highlight_json == "[]"
        unlink()

    def test_compare_mode_tags_both_meshes(self, drone_model):
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(_quad_mesh(), _quad_mesh(), label="a", label_b="b")
        unlink = link.link_selection(structure, viewer, drone_model, part_map=QUAD_MAP)
        for trait in ("mesh_json", "mesh_b_json"):
            parts = json.loads(getattr(viewer, trait))["parts"]
            assert [p.get("key") for p in parts] == [*QUAD_MAP.values(), None, None]
        structure.view.selection.ids = ["DeepScout::MultiRotor::battery"]
        assert json.loads(viewer.highlight_json) == ["DeepScout::MultiRotor::battery"]
        unlink()


class TestIndividualQname:
    """The id-derivation rule: strip each dotted segment's ``#index``,
    join with ``::`` -- an individual belongs to its usage."""

    def test_indexed_individual_derives_its_usage(self):
        assert link.individual_qname("Rotorcraft::QuadCopter#0.motors#2") == (
            "Rotorcraft::QuadCopter::motors"
        )

    def test_singleton_and_root_derive_too(self):
        # a singleton feature has no index of its own; the root does
        assert link.individual_qname("Rotorcraft::QuadCopter#0.chassis") == (
            "Rotorcraft::QuadCopter::chassis"
        )
        assert link.individual_qname("Rotorcraft::QuadCopter#0") == "Rotorcraft::QuadCopter"

    def test_nested_populations_derive_the_nested_usage(self):
        assert link.individual_qname("P::Quad#0.rotors#1.blades#0") == "P::Quad::rotors::blades"

    def test_plain_keys_are_not_individual_ids(self):
        # pure-qname and bare-name keys keep their exact semantics
        assert link.individual_qname("Rotorcraft::QuadCopter::motors") is None
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
        assert self.resolve(drone_model, ["Rotorcraft::QuadCopter::motors"]) == set(MOTOR_IDS)
        assert self.resolve(drone_model, ["Rotorcraft::QuadCopter::propellers"]) == set(PROP_IDS)

    def test_definition_matches_through_the_usage(self, drone_model):
        assert self.resolve(drone_model, ["ScoutParts::F450Kit::Motor"]) == set(MOTOR_IDS)
        assert self.resolve(drone_model, ["ScoutParts::F450Kit::Propeller"]) == set(PROP_IDS)

    def test_container_matches_the_whole_population(self, drone_model):
        assert self.resolve(drone_model, ["Rotorcraft::QuadCopter"]) == set(INDIVIDUAL_MAP.values())

    def test_unrelated_selection_still_matches_nothing(self, drone_model):
        assert self.resolve(drone_model, ["DeepScout::HoverTime"]) == set()


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
        structure.view.selection.ids = ["Rotorcraft::QuadCopter::motors"]
        assert json.loads(viewer.highlight_json) == sorted(MOTOR_IDS)

    def test_pick_projects_to_the_usage_and_surfaces_the_individual(self, individual_linked):
        structure, viewer, picks, _unlink = individual_linked
        viewer.picked_json = json.dumps(["Rotorcraft::QuadCopter#0.motors#2"])
        # M0 -> M1 is many-to-one: the diagram selects the one usage ...
        assert list(structure.view.selection.ids) == ["Rotorcraft::QuadCopter::motors"]
        # ... whose fan-out re-lights all four instance meshes ...
        assert json.loads(viewer.highlight_json) == sorted(MOTOR_IDS)
        # ... while on_pick preserves which individual was hit
        assert picks == [["Rotorcraft::QuadCopter#0.motors#2"]]

    def test_background_pick_reports_empty_and_clears(self, individual_linked):
        structure, viewer, picks, _unlink = individual_linked
        viewer.picked_json = json.dumps(["Rotorcraft::QuadCopter#0.battery"])
        viewer.picked_json = json.dumps([])
        assert picks == [["Rotorcraft::QuadCopter#0.battery"], []]
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
        viewer.picked_json = json.dumps(["Rotorcraft::QuadCopter#0.motors#0"])
        assert picks == [["Rotorcraft::QuadCopter#0.motors#0"]]
        assert list(structure.view.selection.ids) == []  # projection stays off
        unlink()

    def test_unlink_silences_on_pick(self, individual_linked):
        _structure, viewer, picks, unlink = individual_linked
        unlink()
        viewer.picked_json = json.dumps(["Rotorcraft::QuadCopter#0.motors#1"])
        assert picks == []


class _StubTree:
    """The explorer protocol's selection surface, headless (on_select +
    a plain-assignable ``selected``)."""

    def __init__(self):
        self.selected: list[str] = []
        self._callbacks = []

    def on_select(self, callback):
        self._callbacks.append(callback)

    def fire(self, ids):
        self.selected = list(ids)
        for callback in self._callbacks:
            callback(list(ids))


class TestBindConfigView:
    """The config-keyed rendering seam: a selection decides WHICH craft
    the viewer shows.  Scenes bake through grand.scene_for (dispatching
    the MultiRotor build family AND the fleet airframe shells); swaps
    happen only when the resolved configuration changes."""

    @pytest.fixture()
    def bound(self, drone_model):
        from longeron.analysis.grand import scene_for

        mesh, _part_map = scene_for(drone_model, "Rotorcraft::QuadCopter")
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(mesh, label="the quad")
        binding = link.bind_config_view(
            structure, viewer, drone_model, showing="Rotorcraft::QuadCopter"
        )
        return structure, viewer, binding

    def test_selection_inside_the_shown_craft_never_rewrites_the_scene(self, bound):
        structure, viewer, binding = bound
        before = viewer.mesh_json
        structure.view.selection.ids = ["Rotorcraft::QuadCopter::motors"]
        assert viewer.mesh_json is before  # no swap, no flicker
        assert binding.current == "Rotorcraft::QuadCopter"
        assert json.loads(viewer.highlight_json) == sorted(MOTOR_IDS)  # M0 fan-out

    def test_selecting_another_build_config_renders_it(self, bound):
        structure, viewer, binding = bound
        structure.view.selection.ids = ["Rotorcraft::TriCopter::tailMotor"]
        assert binding.current == "Rotorcraft::TriCopter"
        assert viewer.label == "Rotorcraft::TriCopter"
        assert len(json.loads(viewer.mesh_json)["discs"]) == 3  # THE TRICOPTER
        assert json.loads(viewer.highlight_json) == ["Rotorcraft::TriCopter#0.tailMotor"]

    def test_selecting_a_fleet_shell_renders_it(self, bound):
        structure, viewer, binding = bound
        structure.view.selection.ids = ["Rotorcraft::TeardropQuad"]
        assert binding.current == "Rotorcraft::TeardropQuad"
        parts = json.loads(viewer.mesh_json)["parts"]
        internals = {
            "battery": "Rotorcraft::TeardropQuad::battery",
            "fc": "Rotorcraft::TeardropQuad::flightController",
            "camera": "Rotorcraft::TeardropQuad::camera",
        }
        assert parts and all(
            part["key"] == internals.get(part["name"], "Rotorcraft::TeardropQuad") for part in parts
        )
        # the def selection lights every part: the shell AND the
        # clickable internals nested under it
        assert json.loads(viewer.highlight_json) == sorted(
            {"Rotorcraft::TeardropQuad", *internals.values()}
        )

    def test_a_variant_usage_renders_the_definition_that_types_it(self, bound):
        structure, _viewer, binding = bound
        structure.view.selection.ids = ["ScoutMissions::Catalog::AirframeChoice::hexLifter"]
        assert binding.current == "Rotorcraft::HexLifter"

    def test_unbakeable_selections_keep_the_scene_and_clear_the_highlight(self, bound):
        structure, viewer, binding = bound
        structure.view.selection.ids = ["Rotorcraft::TeardropQuad"]
        shown = viewer.mesh_json
        structure.view.selection.ids = ["DeepScout::HoverTime"]  # a calc def
        assert viewer.mesh_json is shown and binding.current == "Rotorcraft::TeardropQuad"
        assert viewer.highlight_json == "[]"
        assert binding.scenes["DeepScout::HoverTime"] is None  # the miss is cached

    def test_mesh_pick_selects_the_source_node(self, bound):
        structure, viewer, _binding = bound
        structure.view.selection.ids = ["Rotorcraft::TeardropQuad"]
        viewer.picked_json = json.dumps(["Rotorcraft::TeardropQuad"])
        assert list(structure.view.selection.ids) == ["Rotorcraft::TeardropQuad"]
        viewer.picked_json = json.dumps([])  # background: clears
        assert list(structure.view.selection.ids) == []

    def test_unbind_is_idempotent_and_silences_both_directions(self, bound):
        structure, viewer, binding = bound
        structure.view.selection.ids = ["Rotorcraft::QuadCopter::motors"]
        binding.unbind()
        assert viewer.highlight_json == "[]"
        structure.view.selection.ids = ["Rotorcraft::TriCopter::tailMotor"]
        assert binding.current == "Rotorcraft::QuadCopter"  # inert: no swap
        viewer.picked_json = json.dumps(["Rotorcraft::TeardropQuad"])
        assert list(structure.view.selection.ids) == ["Rotorcraft::TriCopter::tailMotor"]
        binding.unbind()  # idempotent

    def test_rebinding_replaces_the_previous_binding(self, bound, drone_model):
        structure, viewer, binding = bound
        rebound = link.bind_config_view(
            structure, viewer, drone_model, showing="Rotorcraft::QuadCopter"
        )
        structure.view.selection.ids = ["Rotorcraft::QuadCopter::motors"]
        highlight = viewer.highlight_json
        assert json.loads(highlight) == sorted(MOTOR_IDS)  # ONE binding drove this
        binding.unbind()  # the replaced binding is inert: must not clear
        assert viewer.highlight_json == highlight
        rebound.unbind()
        assert viewer.highlight_json == "[]"

    def test_decorate_hook_shapes_the_swap_in_one_write(self, drone_model):
        from longeron.analysis.grand import scene_for

        mesh, _part_map = scene_for(drone_model, "Rotorcraft::QuadCopter")
        structure = diagrams.structure_diagram(drone_model)
        viewer = viewer3d.mesh_viewer(mesh)
        writes = []
        viewer.observe(lambda change: writes.append(change["new"]), names="mesh_json")
        halo = {"name": "halo", "vertices": [], "faces": []}
        link.bind_config_view(
            structure,
            viewer,
            drone_model,
            showing="Rotorcraft::QuadCopter",
            decorate=lambda qname, scene: {**scene, "parts": [*scene["parts"], halo]},
        )
        structure.view.selection.ids = ["Rotorcraft::TriCopter"]
        assert len(writes) == 1  # decorated swap, one traitlet write
        assert json.loads(writes[0])["parts"][-1]["name"] == "halo"

    def test_explorer_protocol_source(self, drone_model):
        from longeron.analysis.grand import scene_for

        mesh, _part_map = scene_for(drone_model, "Rotorcraft::QuadCopter")
        tree = _StubTree()
        viewer = viewer3d.mesh_viewer(mesh)
        binding = link.bind_config_view(tree, viewer, drone_model, showing="Rotorcraft::QuadCopter")
        tree.fire(["Rotorcraft::HexLifter"])  # a tree row click, by qualified name
        assert binding.current == "Rotorcraft::HexLifter"
        assert json.loads(viewer.highlight_json) == [
            "Rotorcraft::HexLifter",
            "Rotorcraft::HexLifter::battery",
            "Rotorcraft::HexLifter::camera",
            "Rotorcraft::HexLifter::flightController",
        ]
        viewer.picked_json = json.dumps(["Rotorcraft::HexLifter"])  # pick flows OUT
        assert tree.selected == ["Rotorcraft::HexLifter"]
        binding.unbind()

    def test_source_without_a_selection_surface_is_loud(self, drone_model):
        from longeron.analysis import AnalysisError

        viewer = viewer3d.mesh_viewer(_quad_mesh())
        with pytest.raises(AnalysisError, match="selection"):
            link.bind_config_view(object(), viewer, drone_model)
