"""The model explorer: tree navigator + diagram pane (headless)."""

import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("ipyelk")
pytest.importorskip("anywidget")

import longeron
from longeron import explorer as explorer_module
from longeron import model as M
from longeron.errors import MissingExtraError
from longeron.explorer import (
    DIAGRAM_KINDS,
    Explorer,
    ModelTree,
    TreeView,
    _diagram_node_ids,
    _tree_data,
    applicable_kinds,
    explore,
    requirements_view,
)

ROOT = Path(__file__).resolve().parent.parent

ANON_SATISFY_MODEL = """
package P {
    requirement requirement1;
    part sys;
    satisfy requirement1 by sys;
}
"""

NAMED_SATISFY_MODEL = """
package Reqs { requirement requirement1; }
package Sys {
    part part1 {
        satisfy requirement requirement2 references Reqs::requirement1;
    }
}
"""

NO_REQUIREMENTS_MODEL = """
package Plain {
    part def Widget { attribute mass : Real = 1.0; }
    part widget : Widget;
}
"""


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load(str(ROOT / "examples" / "drone.sysml"))


@pytest.fixture(scope="module")
def uav_model():
    return longeron.load(str(ROOT / "examples" / "uav_missions.sysml"))


@pytest.fixture()
def ex(drone_model):
    return explore(drone_model, layout="inline")  # deterministic headless


def _reference_count(namespace) -> int:
    """Independent reference walk: the elements the tree must show."""

    total = 0
    for member in namespace.members:
        if isinstance(member, (M.Package, M.Definition, M.Usage)):
            total += 1 + _reference_count(member)
    return total


def _find(nodes, node_id):
    for node in nodes:
        if node["id"] == node_id:
            return node
        found = _find(node.get("children", ()), node_id)
        if found is not None:
            return found
    return None


# ---------------------------------------------------------------------------
# tree construction
# ---------------------------------------------------------------------------


class TestTreeData:
    def test_counts_match_the_owning_structure(self, drone_model, uav_model):
        for model in (drone_model, uav_model):
            nodes, index = _tree_data(model)
            top = [m for m in model.members if explorer_module._in_tree(m)]
            flattened = len(top) == 1  # single-package models drop the file row
            expected = _reference_count(model) + (0 if flattened else 1)
            assert len(index) == expected
            tree = ModelTree(nodes)
            assert tree.total_count == expected

    def test_uav_is_the_big_one(self, uav_model):
        _nodes, index = _tree_data(uav_model)
        assert len(index) > 400  # the biggest shipped example

    def test_nesting_follows_ownership(self, drone_model):
        nodes, _ = _tree_data(drone_model)
        drone = nodes[0]  # flattened: the lone package IS the root
        assert drone["id"] == "Drone"
        quad = _find(drone["children"], "Drone::QuadCopter")
        assert quad is not None
        battery = _find(quad["children"], "Drone::QuadCopter::battery")
        assert battery is not None
        # and NOT reachable as a sibling of the package
        siblings = [c for c in drone["children"] if c["id"] != "Drone::QuadCopter"]
        assert _find(siblings, "Drone::QuadCopter::battery") is None

    def test_node_ids_are_qualified_names(self, drone_model):
        _, index = _tree_data(drone_model)
        named = {nid for nid in index if not nid.startswith("~")}
        assert "Drone::FlightStates::idle" in named
        for nid in named:
            assert index[nid].qualified_name == nid

    def test_kind_badges_and_families(self, drone_model):
        nodes, _ = _tree_data(drone_model)
        cases = {
            "Drone": ("pkg", "package"),
            "Drone::QuadCopter": ("part def", "structure"),
            "Drone::FlightStates": ("state def", "behavior"),
            "Drone::PlanBattery": ("action def", "behavior"),
            "Drone::FlightEnvelope": ("requirement def", "requirement"),
            "Drone::FlightMode": ("enum def", "data"),
            "Drone::HoverTime": ("calc def", "behavior"),
            "Drone::QuadCopter::battery": ("part", "structure"),
            "Drone::QuadCopter::payloadMass": ("attribute", "data"),
        }
        for node_id, (badge, kind) in cases.items():
            node = _find(nodes, node_id)
            assert node is not None, node_id
            assert (node["badge"], node["kind"]) == (badge, kind), node_id

    def test_has_children_hints_lazy_loading(self, drone_model):
        nodes, _ = _tree_data(drone_model)
        quad = _find(nodes, "Drone::QuadCopter")
        assert quad["has_children"] is True and quad["children"]
        leaf = _find(nodes, "Drone::QuadCopter::payloadMass")
        assert leaf["has_children"] is False and "children" not in leaf

    def test_typed_usages_carry_a_type_suffix(self, drone_model):
        nodes, _ = _tree_data(drone_model)
        battery = _find(nodes, "Drone::QuadCopter::battery")
        assert battery["suffix"] == " : Battery"

    def test_anonymous_elements_get_unique_synthetic_ids(self):
        model = longeron.loads(ANON_SATISFY_MODEL)
        nodes, index = _tree_data(model)
        synthetic = [nid for nid in index if nid.startswith("~")]
        assert len(synthetic) == len(set(synthetic))
        assert len(index) == len(set(index))  # no id ever collides
        # the anonymous satisfy is in the tree, labeled by its target
        satisfy = next(el for el in index.values() if isinstance(el, M.SatisfyUsage))
        node = _find(nodes, next(nid for nid, el in index.items() if el is satisfy))
        assert node["label"] == "satisfy requirement1"
        assert node["kind"] == "requirement"

    def test_single_package_model_flattens_to_the_package(self, drone_model):
        # the language has no model-level name: the lone top-level
        # package IS the model's humanized name, so it is the tree root
        nodes, index = _tree_data(drone_model)
        assert len(nodes) == 1
        root = nodes[0]
        assert isinstance(index[root["id"]], M.Package)
        assert root["label"] == "Drone"
        assert root["tooltip"].endswith("drone.sysml \u2014 Drone") or (
            "drone.sysml" in root["tooltip"]
        )

    def test_multi_package_model_keeps_the_file_root(self):
        model = longeron.loads(
            "package A { part a; } package B { part b; }", source_name="dir/two.sysml"
        )
        nodes, index = _tree_data(model)
        assert len(nodes) == 1
        assert isinstance(index[nodes[0]["id"]], M.Model)
        assert nodes[0]["label"] == "two.sysml"
        assert nodes[0]["badge"] == "model"
        assert nodes[0]["tooltip"] == "dir/two.sysml"


# ---------------------------------------------------------------------------
# the tree widget's search idiom (kernel-side mirror of the browser filter)
# ---------------------------------------------------------------------------


class TestTreeSearch:
    def test_name_match_is_case_insensitive(self, drone_model):
        tree = ModelTree(_tree_data(drone_model)[0])
        tree.query = "ROTOR"
        by_name = tree.match_count
        tree.query = "rotor"
        assert tree.match_count == by_name > 0

    def test_qualified_name_matches_too(self, drone_model):
        tree = ModelTree(_tree_data(drone_model)[0])
        tree.query = "flightstates::"
        assert tree.match_count == 5  # launches + the four states

    def test_clearing_resets_the_count(self, drone_model):
        tree = ModelTree(_tree_data(drone_model)[0])
        tree.query = "battery"
        assert tree.match_count > 0
        tree.query = ""
        assert tree.match_count == 0

    def test_whitespace_query_is_inactive(self, drone_model):
        tree = ModelTree(_tree_data(drone_model)[0])
        tree.query = "   "
        assert tree.match_count == 0

    def test_zero_matches_is_zero_not_error(self, drone_model):
        tree = ModelTree(_tree_data(drone_model)[0])
        tree.query = "no such element anywhere"
        assert tree.match_count == 0

    def test_filter_method_mirrors_the_query(self, drone_model):
        tree = ModelTree(_tree_data(drone_model)[0])
        count = tree.filter("rotor")
        assert count == tree.match_count > 0
        assert tree.query == "rotor"
        assert tree.filter("") == 0

    def test_set_nodes_replaces_the_tree(self, drone_model, uav_model):
        tree = ModelTree(_tree_data(drone_model)[0])
        small = tree.total_count
        tree.set_nodes(_tree_data(uav_model)[0])
        assert tree.total_count > small


# ---------------------------------------------------------------------------
# applicable diagram kinds
# ---------------------------------------------------------------------------


class TestApplicableKinds:
    def test_all_kinds_are_known(self):
        assert DIAGRAM_KINDS == ("structure", "state", "action", "requirements")

    def test_per_element_kind(self, drone_model):
        cases = {
            "Drone": ("structure", "requirements"),
            "Drone::QuadCopter": ("structure", "requirements"),
            "Drone::QuadCopter::battery": ("structure", "requirements"),
            "Drone::FlightStates": ("structure", "state", "requirements"),
            "Drone::FlightStates::idle": ("structure", "state", "requirements"),
            "Drone::PlanBattery": ("structure", "action", "requirements"),
            "Drone::FlightEnvelope": ("structure", "requirements"),
        }
        for qname, expected in cases.items():
            assert applicable_kinds(drone_model.find(qname)) == expected, qname

    def test_requirements_only_when_the_package_has_some(self):
        model = longeron.loads(NO_REQUIREMENTS_MODEL)
        assert applicable_kinds(model.find("Plain")) == ("structure",)
        assert applicable_kinds(model.find("Plain::Widget")) == ("structure",)

    def test_satisfy_alone_enables_the_requirements_view(self):
        model = longeron.loads(ANON_SATISFY_MODEL)
        assert "requirements" in applicable_kinds(model.find("P::sys"))

    def test_requirements_scope_is_the_owning_package(self, uav_model):
        # Catalog owns no requirements: the kind is not offered there,
        # even though a SIBLING package (MissionRequirements) has plenty
        assert applicable_kinds(uav_model.find("UavMissions::Catalog")) == ("structure",)
        kinds = applicable_kinds(uav_model.find("UavMissions::MissionRequirements"))
        assert "requirements" in kinds


# ---------------------------------------------------------------------------
# the requirements view
# ---------------------------------------------------------------------------


class TestRequirementsView:
    def test_anonymous_satisfy_keyword_edge(self):
        model = longeron.loads(ANON_SATISFY_MODEL)
        widget = requirements_view(model)
        ids = _diagram_node_ids(widget)
        assert {"P::requirement1", "P::sys"} <= ids
        edge = next(
            e
            for e in widget.source.value.edges
            if "sysml-edge-satisfies" in e.properties.cssClasses
        )
        assert (edge.source.id, edge.target.id) == ("P::sys", "P::requirement1")

    def test_named_satisfy_reference_subsetting(self):
        model = longeron.loads(NAMED_SATISFY_MODEL)
        widget = requirements_view(model)
        ids = _diagram_node_ids(widget)
        assert {"Reqs::requirement1", "Sys::part1::requirement2"} <= ids
        edge = next(
            e
            for e in widget.source.value.edges
            if "sysml-edge-references" in e.properties.cssClasses
        )
        assert (edge.source.id, edge.target.id) == (
            "Sys::part1::requirement2",
            "Reqs::requirement1",
        )

    def test_view_is_a_read_only_projection(self):
        model = longeron.loads(ANON_SATISFY_MODEL)
        before = {id(el): el.qualified_name for el in model.iter_tree()}
        requirements_view(model)
        # owners (and therefore qualified names) are untouched
        assert {id(el): el.qualified_name for el in model.iter_tree()} == before
        assert model.find("P::sys").owner is model.find("P")

    def test_requirement_defs_draw_with_typing_edges(self, drone_model):
        widget = requirements_view(drone_model)
        ids = _diagram_node_ids(widget)
        assert "Drone::FlightEnvelope" in ids
        # non-requirement structure stays out of the projection
        assert "Drone::QuadCopter" not in ids

    def test_nested_candidates_never_duplicate_node_ids(self, uav_model):
        widget = requirements_view(uav_model)
        counted: dict[str, int] = {}
        from longeron.explorer import _walk_source

        for node in _walk_source(widget.source.value):
            if node.id:
                counted[node.id] = counted.get(node.id, 0) + 1
        duplicates = {nid: n for nid, n in counted.items() if n > 1}
        assert duplicates == {}


# ---------------------------------------------------------------------------
# the explorer widget: selection round trips, no echo, caching
# ---------------------------------------------------------------------------


class TestExplorer:
    def test_initial_state_shows_the_whole_model(self, ex, drone_model):
        # single-package model: the root row (and thus the initial
        # selection) is the package itself, a real diagram element
        assert isinstance(ex.element, M.Package)
        assert ex.element.name == "Drone"
        assert ex.kind == "structure"
        assert type(ex.diagram).__name__ == "Diagram"
        assert ex.tree.selected  # the model root node is selected
        assert tuple(ex.kind_switcher.options) == ("structure", "requirements")

    def test_tree_selection_renders_and_highlights(self, ex, drone_model):
        ex.tree.selected = ["Drone::QuadCopter"]
        assert ex.element is drone_model.find("Drone::QuadCopter")
        assert tuple(ex.diagram.view.selection.ids) == ("Drone::QuadCopter",)

    def test_kind_switcher_offers_only_applicable_kinds(self, ex):
        ex.select("Drone::FlightStates")
        assert tuple(ex.kind_switcher.options) == ("structure", "state", "requirements")
        ex.select("Drone::PlanBattery")
        assert tuple(ex.kind_switcher.options) == ("structure", "action", "requirements")

    def test_kind_switch_preserves_the_selection(self, ex):
        ex.select("Drone::FlightStates")
        structure = ex.diagram
        ex.kind = "state"
        assert ex.diagram is not structure
        assert ex.tree.selected == ["Drone::FlightStates"]
        assert ex.element.qualified_name == "Drone::FlightStates"
        ex.kind = "structure"
        assert ex.diagram is structure  # cached: same widget object

    def test_inapplicable_kind_is_rejected(self, ex):
        ex.select("Drone::QuadCopter")
        with pytest.raises(ValueError, match="kind must be one of"):
            ex.kind = "state"

    def test_nested_state_scopes_to_its_machine(self, ex):
        ex.select("Drone::FlightStates::idle")
        ex.kind = "state"
        ids = _diagram_node_ids(ex.diagram)
        assert "Drone::FlightStates::flying" in ids  # the whole machine
        assert tuple(ex.diagram.view.selection.ids) == ("Drone::FlightStates::idle",)

    def test_undrawn_selection_highlights_nearest_drawn_ancestor(self, ex):
        # attributes render as compartment rows, not nodes
        ex.select("Drone::Battery::capacity")
        assert tuple(ex.diagram.view.selection.ids) == ("Drone::Battery",)

    def test_diagrams_are_cached_per_scope_and_kind(self, ex):
        ex.select("Drone::Battery")
        first = ex.diagram
        ex.select("Drone::Rotor")
        assert ex.diagram is first  # same package scope, same widget

    def test_diagram_click_selects_and_reveals_in_the_tree(self, ex):
        ex.select("Drone::QuadCopter")
        widget = ex.diagram
        widget.view.selection.ids = ["Drone::PlanBattery"]  # a browser click
        assert ex.tree.selected == ["Drone::PlanBattery"]
        assert "action" in ex.kind_switcher.options
        assert ex.diagram is widget  # the clicked diagram is NOT rebuilt

    def test_no_selection_echo(self, ex):
        """One hop each way; every trait settles after a single write."""

        ex.select("Drone::QuadCopter")
        widget = ex.diagram
        tree_writes: list = []
        diagram_writes: list = []
        ex.tree.observe(lambda ch: tree_writes.append(ch["new"]), "selected")
        widget.view.selection.observe(lambda ch: diagram_writes.append(ch["new"]), "ids")

        widget.view.selection.ids = ["Drone::PlanBattery"]  # diagram -> tree
        assert tree_writes == [["Drone::PlanBattery"]]
        assert diagram_writes == [("Drone::PlanBattery",)]  # only the click itself

        ex.tree.selected = ["Drone::Frame"]  # tree -> diagram
        assert tree_writes == [["Drone::PlanBattery"], ["Drone::Frame"]]
        assert diagram_writes == [("Drone::PlanBattery",), ("Drone::Frame",)]

    def test_reselecting_the_same_element_is_a_fixpoint(self, ex):
        ex.select("Drone::QuadCopter")
        widget = ex.diagram
        tree_writes: list = []
        diagram_writes: list = []
        ex.tree.observe(lambda ch: tree_writes.append(ch["new"]), "selected")
        widget.view.selection.observe(lambda ch: diagram_writes.append(ch["new"]), "ids")
        ex.select("Drone::QuadCopter")
        assert ex.diagram is widget
        assert tree_writes == [] and diagram_writes == []

    def test_diagram_click_on_undrawn_element_reveals_the_ancestor(self, ex):
        # expanded-submachine ids resolve through typing hops: the tree
        # reveals the nearest element it knows
        ex.select("Drone::FlightStates")
        ex.kind = "state"
        ex.diagram.view.selection.ids = ["Drone::FlightStates::flying"]
        assert ex.tree.selected == ["Drone::FlightStates::flying"]

    def test_select_by_element(self, ex, drone_model):
        ex.select(drone_model.find("Drone::HoverTime"))
        assert ex.tree.selected == ["Drone::HoverTime"]

    def test_select_unknown_raises(self, ex):
        from longeron.errors import ResolutionError

        with pytest.raises(ResolutionError):
            ex.select("No::Such::Thing")

    def test_requirements_kind_renders_the_requirements_view(self, ex):
        ex.select("Drone::FlightEnvelope")
        ex.kind = "requirements"
        ids = _diagram_node_ids(ex.diagram)
        assert "Drone::FlightEnvelope" in ids
        assert "Drone::QuadCopter" not in ids

    def test_structure_scope_element_mode(self, drone_model):
        ex = explore(drone_model, structure_scope="element")
        ex.select("Drone::QuadCopter")
        ids = _diagram_node_ids(ex.diagram)
        assert "Drone::QuadCopter" in ids
        assert "Drone::FlightStates" not in ids  # siblings stay out

    def test_bad_structure_scope_rejected(self, drone_model):
        with pytest.raises(ValueError, match="structure_scope"):
            Explorer(drone_model, structure_scope="galaxy")

    def test_uav_selection_is_one_cheap_hop(self, uav_model):
        """No O(n^2) rebuilds: re-selecting inside one package reuses the
        cached diagram, and only the selection trait changes."""

        ex = explore(uav_model)
        ex.select("UavMissions::Catalog")
        widget = ex.diagram
        built = len(ex._diagrams)
        for qname in (
            "UavMissions::Catalog::AirframeChoice",
            "UavMissions::Catalog::MotorChoice",
            "UavMissions::Catalog::AirframeChoice",
        ):
            ex.select(qname)
            assert ex.diagram is widget
        assert len(ex._diagrams) == built  # nothing new was built

    def test_layout_split(self, ex):
        assert ex.tree.layout.width == "28%"
        assert ex.children[1].layout.width == "72%"
        assert ex.layout.width == "100%"


# ---------------------------------------------------------------------------
# the TreeView seam: any conforming engine can replace the tree pane
# ---------------------------------------------------------------------------


class StubTree:
    """A headless TreeView engine: the swap-ability contract, minimally.

    Not a widget on purpose -- the explorer must drive it strictly
    through the protocol (any other attribute access would raise).
    """

    def __init__(self):
        self.nodes: list = []
        self.revealed: list = []
        self.selected_writes = 0
        self._selected: list = []
        self._callbacks: list = []

    @property
    def selected(self):
        return self._selected

    @selected.setter
    def selected(self, ids):
        self._selected = list(ids)
        self.selected_writes += 1

    def set_nodes(self, nodes):
        self.nodes = list(nodes)

    def on_select(self, callback):
        self._callbacks.append(callback)

    def reveal(self, node_id):
        self.revealed.append(node_id)

    def filter(self, text):
        return 0

    def click(self, ids):
        """What a user click does in a real engine: select, then notify."""

        self._selected = list(ids)
        for callback in list(self._callbacks):
            callback(list(ids))


class TestSaveViewSeam:
    """Explorer.save_view: the chrome affordance for view persistence
    (longeron.views).  Minimal by design -- the full chrome is a later
    tranche; here the seam captures the CURRENT pane's diagram kind and
    shown root into save_view() plus a sidecar entry."""

    @pytest.fixture()
    def model(self):
        return longeron.loads(
            """
            package Rig {
                part def Axle { part hub : Hub [2]; }
                part def Hub;
                part axle : Axle;
                state def Machine { entry; then idle; state idle; }
            }
            """
        )

    def test_header_carries_a_compact_save_button(self, model):
        ex = explore(model, layout="inline")
        header = ex._pane.children[0]
        assert ex.save_button in header.children
        assert ex.save_button.icon == "save"
        assert ex.save_button.layout.width == "30px"  # the toolbar idiom

    def test_saves_the_current_panes_kind_and_root(self, model, tmp_path):
        from longeron import views

        ex = explore(model, layout="inline")
        ex.select("Rig::axle")  # structure pane, scoped to package Rig
        view = ex.save_view("axle structure", sidecar=tmp_path)
        assert view.owner is model.find("Rig")
        assert view.types == ["StandardViewDefinitions::InterconnectionView"]
        exposes = [m for m in view.members if isinstance(m, M.Expose)]
        assert [(e.target, e.is_recursive) for e in exposes] == [("Rig", True)]
        entry = views.load_sidecar(tmp_path)["Rig::axle structure"]
        assert entry["kind"] == "structure"

    def test_state_pane_saves_a_state_view(self, model, tmp_path):
        from longeron import views

        ex = explore(model, layout="inline")
        ex.select("Rig::Machine")
        ex.kind = "state"
        view = ex.save_view(sidecar=tmp_path)
        assert view.types == ["StandardViewDefinitions::StateTransitionView"]
        exposes = [m for m in view.members if isinstance(m, M.Expose)]
        assert [e.target for e in exposes] == ["Rig::Machine"]
        assert views.load_sidecar(tmp_path)[str(view.qualified_name)]["kind"] == "state"

    def test_saved_view_appears_in_the_refreshed_tree(self, model):
        ex = explore(model, layout="inline")
        ex.select("Rig")
        view = ex.save_view("fresh view", sidecar=False)
        assert "Rig::fresh view" in ex._index
        assert ex._index["Rig::fresh view"] is view
        # the selection survives the tree rebuild
        assert list(ex.tree.selected) == ["Rig"]

    def test_sidecar_false_skips_the_file(self, model, tmp_path, monkeypatch):
        from longeron import views as views_module

        monkeypatch.setattr(views_module, "sidecar_path", lambda source: tmp_path / "views.json")
        ex = explore(model, layout="inline")
        ex.select("Rig")
        ex.save_view("no sidecar", sidecar=False)
        assert not (tmp_path / "views.json").exists()

    def test_in_memory_model_skips_the_sidecar_silently(self, model):
        # loads() text has no workspace: model edit only, no error
        ex = explore(model, layout="inline")
        ex.select("Rig")
        view = ex.save_view()
        assert view.owner is model.find("Rig")

    def test_save_then_restore_round_trip(self, model, tmp_path):
        from longeron import views

        ex = explore(model, layout="inline")
        ex.select("Rig::axle")
        ex.save_view("axle structure", sidecar=tmp_path)
        widget = views.restore_view(model, "Rig::axle structure", sidecar=tmp_path)
        assert widget._lgn_view_state["kind"] == "structure"
        assert widget._lgn_view_state["element"] is model.find("Rig")


class TestTreeViewProtocol:
    def test_modeltree_conforms(self):
        assert isinstance(ModelTree(), TreeView)

    def test_stub_conforms(self):
        assert isinstance(StubTree(), TreeView)

    def test_stub_tree_drives_the_explorer(self, drone_model):
        stub = StubTree()
        ex = Explorer(drone_model, tree=stub, layout="inline")
        # the engine received protocol-schema nodes
        assert stub.nodes
        assert set(stub.nodes[0]) >= {"id", "label", "kind", "badge", "has_children"}
        # the initial selection reached the stub, with a reveal
        root_id = stub.nodes[0]["id"]
        assert stub.selected == [root_id]
        assert stub.revealed[-1] == root_id
        # explorer -> engine
        ex.select("Drone::FlightStates")
        assert stub.selected == ["Drone::FlightStates"]
        assert stub.revealed[-1] == "Drone::FlightStates"
        assert "state" in ex.kind_switcher.options
        # engine -> explorer (a user click in the engine); no echo write-back
        writes = stub.selected_writes
        stub.click(["Drone::PlanBattery"])
        assert ex.element.qualified_name == "Drone::PlanBattery"
        assert "action" in ex.kind_switcher.options
        assert stub.selected_writes == writes

    def test_diagram_click_reaches_a_stub_engine(self, drone_model):
        stub = StubTree()
        ex = Explorer(drone_model, tree=stub, layout="inline")
        ex.select("Drone::QuadCopter")
        writes = stub.selected_writes
        ex.diagram.view.selection.ids = ["Drone::Battery"]  # a browser click
        assert stub.selected == ["Drone::Battery"]
        assert stub.selected_writes == writes + 1  # exactly one write
        assert stub.revealed[-1] == "Drone::Battery"

    def test_headless_engine_is_not_displayed(self, drone_model):
        ex = Explorer(drone_model, tree=StubTree(), layout="inline")
        assert len(ex.children) == 1  # just the diagram pane, full width
        assert ex.children[0] is ex._pane
        assert ex._pane.layout.width == "100%"


# ---------------------------------------------------------------------------
# the layout seam: inline HBox vs ipylab docking, same panes either way
# ---------------------------------------------------------------------------


class _StubShell:
    def __init__(self):
        self.added = []

    def add(self, panel, area, options=None):
        self.added.append((panel, area, options))


class _StubFrontEnd:
    def __init__(self):
        self.shell = _StubShell()


class _StubTitle:
    def __init__(self):
        self.label = ""
        self.dataset = {}


class _StubSplitPanel:
    def __init__(self):
        self.children = ()
        self.orientation = ""
        self.title = _StubTitle()
        self.classes = []
        self.closed = False

    def add_class(self, name):
        self.classes.append(name)

    def close(self):
        self.closed = True


def _install_stub_ipylab(monkeypatch):
    """A minimal fake ipylab so the 'lab' composition runs headless."""

    module = types.ModuleType("ipylab")
    module.SplitPanel = _StubSplitPanel
    module.Panel = _StubSplitPanel
    module.JupyterFrontEnd = _StubFrontEnd
    monkeypatch.setitem(sys.modules, "ipylab", module)
    return module


class TestLayoutStrategies:
    def test_auto_falls_back_inline_headless(self, drone_model, monkeypatch):
        monkeypatch.delitem(sys.modules, "ipylab", raising=False)
        monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
        ex = explore(drone_model)  # layout="auto" is the default
        assert ex.layout_strategy == "inline"
        assert ex.lab_panel is None

    def test_lab_without_ipylab_raises_the_house_error(self, drone_model, monkeypatch):
        # None in sys.modules makes 'import ipylab' raise ImportError even
        # when the package is installed (the delitem form only forced a
        # re-import, which succeeds in envs carrying the [explorer] extra)
        monkeypatch.setitem(sys.modules, "ipylab", None)
        with pytest.raises(MissingExtraError) as err:
            explore(drone_model, layout="lab")
        assert 'pip install "longeron[explorer]"' in str(err.value)

    def test_unknown_layout_rejected(self, drone_model):
        with pytest.raises(ValueError, match="layout must be one of"):
            explore(drone_model, layout="galaxy")

    def test_lab_composes_the_same_panes(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab")
        assert ex.layout_strategy == "lab"
        panel = ex.lab_panel
        assert panel.orientation == "horizontal"
        # the SAME pane objects the inline strategy uses, recomposed
        assert list(panel.children) == [ex.tree, ex._pane]
        assert ex._diagram_box.children  # the diagram pane still renders
        # docked into the main area through the frontend shell: a NEW
        # background tab by default -- never a forced split, never focused
        ((added, area, options),) = ex._lab_app.shell.added
        assert added is panel and area == "main"
        assert options == {"mode": "tab-after", "activate": False}
        # the cell output is just a placeholder hint
        assert len(ex.children) == 1 and "placeholder" in ex.children[0].value

    def test_lab_selection_plumbing_is_layout_independent(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab")
        ex.select("Drone::FlightStates")
        assert ex.tree.selected == ["Drone::FlightStates"]
        assert tuple(ex.diagram.view.selection.ids) == ("Drone::FlightStates",)

    def test_auto_uses_lab_when_frontend_detected(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        monkeypatch.setenv("JPY_SESSION_NAME", "notebooks/demo.ipynb")
        ex = explore(drone_model)
        assert ex.layout_strategy == "lab"

    def test_auto_with_ipylab_but_no_frontend_stays_inline(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        monkeypatch.delenv("JPY_SESSION_NAME", raising=False)
        ex = explore(drone_model)
        assert ex.layout_strategy == "inline"

    def test_inline_composes_the_same_panes(self, drone_model):
        ex = explore(drone_model, layout="inline")
        assert list(ex.children) == [ex.tree, ex._pane]
        assert ex.tree.layout.width == "28%"
        assert ex._pane.layout.width == "72%"


# ---------------------------------------------------------------------------
# lab docking is a well-behaved citizen: mode plumbing + replace-not-stack
# ---------------------------------------------------------------------------


class TestDocking:
    @pytest.fixture(autouse=True)
    def _fresh_registry(self, monkeypatch):
        # the registry is module-level state (that is the point: it must
        # outlive any one Explorer); isolate it per test
        monkeypatch.setattr(explorer_module, "_DOCKED_PANELS", {})

    def test_mode_defaults_to_tab_after_without_activation(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab")
        ((_, _, options),) = ex._lab_app.shell.added
        # tab-after: a full-width main-area tab -- the notebook keeps its
        # width; activate=False: run-all never yanks focus off the notebook
        assert options == {"mode": "tab-after", "activate": False}
        assert ex.dock_mode == "tab-after"

    def test_mode_passes_through_to_the_shell(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab", mode="split-right")
        ((_, _, options),) = ex._lab_app.shell.added
        assert options == {"mode": "split-right", "activate": False}

    @pytest.mark.parametrize("bad", ["", None, 42])
    def test_mode_must_be_a_nonempty_string(self, drone_model, bad):
        with pytest.raises(ValueError, match="mode must be"):
            explore(drone_model, layout="inline", mode=bad)

    def test_mode_is_inert_inline(self, drone_model):
        ex = explore(drone_model, layout="inline", mode="split-bottom")
        assert ex.dock_mode == "split-bottom"  # stored, unused
        assert ex.lab_panel is None and ex._dock_sweeper is None

    def test_redocking_the_same_model_replaces_the_panel(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        first = explore(drone_model, layout="lab")
        second = explore(drone_model, layout="lab")
        assert first.lab_panel.closed  # same kernel: closed, not orphaned
        assert not second.lab_panel.closed
        key = explorer_module._dock_key(drone_model)
        assert explorer_module._DOCKED_PANELS == {key: second.lab_panel}

    def test_different_models_coexist(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        other = longeron.loads("package Solo { part s; }", source_name="solo")
        ex1 = explore(drone_model, layout="lab")
        ex2 = explore(other, layout="lab")
        assert not ex1.lab_panel.closed and not ex2.lab_panel.closed
        assert len(explorer_module._DOCKED_PANELS) == 2

    def test_panel_carries_its_dock_identity(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab")
        key = explorer_module._dock_key(drone_model)
        panel = ex.lab_panel
        # the tab dataset is the cross-kernel handle; the classes are the
        # DOM selector (browser tests + the sweeper's own panel)
        assert panel.title.dataset["lgxkey"] == key
        assert panel.title.dataset["lgxstamp"].isdigit()
        assert panel.classes == ["lgx-explorer", f"lgx-explorer-{key}"]
        assert panel.title.label.startswith("Explorer: ")

    def test_stamps_strictly_increase(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        first = explore(drone_model, layout="lab")
        second = explore(drone_model, layout="lab")
        older = int(first.lab_panel.title.dataset["lgxstamp"])
        newer = int(second.lab_panel.title.dataset["lgxstamp"])
        assert older < newer  # the sweeper only ever closes OLDER stamps

    def test_sweeper_rides_hidden_inside_the_pane(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab")
        sweeper = ex._dock_sweeper
        assert sweeper is ex._pane.children[-1]  # ships INSIDE the panel
        assert sweeper.layout.display == "none"
        assert sweeper.key == explorer_module._dock_key(drone_model)
        assert sweeper.stamp == ex.lab_panel.title.dataset["lgxstamp"]
        assert sweeper.swept == 0

    def test_first_reveal_refits_the_visible_diagram(self, drone_model, monkeypatch):
        # a background tab renders hidden: the initial auto-fit aimed at a
        # zero-sized viewport, so the browser's first-reveal report must
        # trigger exactly one immediate re-fit of the current diagram
        from longeron.toolbar import AutoFitTool

        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab")
        tool = ex.diagram.get_tool(AutoFitTool)
        before = tool.fit_count
        ex._dock_sweeper.shown = True  # what the sweeper reports on reveal
        assert tool.fit_count == before + 1


# ---------------------------------------------------------------------------
# the demo notebook (gitignored; skipped where it does not exist)
# ---------------------------------------------------------------------------

NOTEBOOK = ROOT / "notebooks" / "private" / "04_explorer.ipynb"


@pytest.mark.skipif(not NOTEBOOK.exists(), reason="private demo notebook not present")
def test_demo_notebook_executes():
    nbformat = pytest.importorskip("nbformat")
    nbclient = pytest.importorskip("nbclient")
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    client = nbclient.NotebookClient(
        notebook,
        timeout=600,
        kernel_name="python3",
        resources={"metadata": {"path": str(NOTEBOOK.parent)}},
    )
    client.execute()  # the notebook asserts its own expectations


class TestRootLabelAndTooltip:
    """The tree root: short label, full-path tooltip (never a bare ~N)."""

    def test_flattened_root_shows_package_with_path_tooltip(self):
        model = longeron.loads(
            "package P { part p; }", source_name="examples/deep/dir/uav_missions.sysml"
        )
        nodes, _ = explorer_module._tree_data(model)
        assert nodes[0]["label"] == "P"
        assert nodes[0]["tooltip"] == "examples/deep/dir/uav_missions.sysml \u2014 P"

    def test_multi_package_path_source_collapses_to_file_name(self):
        model = longeron.loads(
            "package P { part p; } package Q { part q; }",
            source_name="examples/deep/dir/uav_missions.sysml",
        )
        nodes, _ = explorer_module._tree_data(model)
        assert nodes[0]["label"] == "uav_missions.sysml"
        assert nodes[0]["tooltip"] == "examples/deep/dir/uav_missions.sysml"

    def test_sourceless_model_has_no_tooltip(self):
        nodes, _ = explorer_module._tree_data(M.Model())
        assert "tooltip" not in nodes[0]
        assert nodes[0]["label"] == "model"
