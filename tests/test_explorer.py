"""The model explorer: tree navigator + diagram pane (headless)."""

import sys
import types
import typing
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

# one of every relationship kind the tree classifies (satisfy, verify,
# connections in every arity, interface, dependency, allocate, binding,
# flow, message, import, filter, expose, alias) plus documentation --
# which must stay OUT of the tree
RELATIONSHIPS_MODEL = """
package Rels {
    part def A { attribute x : Real; }
    part a1 : A;
    part b1 : A;
    part c1 : A;
    requirement massBudget;
    satisfy massBudget by a1;
    verification def CheckMass {
        subject rig : A;
        objective { verify massBudget; }
    }
    connect a1 to b1;
    connection namedConn connect (a1, b1, c1);
    interface plug connect a1 to b1;
    dependency Dep from a1 to b1;
    allocate a1 to b1;
    bind a1.x = b1.x;
    flow from a1.x to b1.x;
    message msg from a1 to b1;
    import Other::*;
    filter @Safety;
    view rig { expose Rels::**; }
    alias also for a1;
    doc /* documentation stays out */
}
package Other { part def C; metadata def Safety; }
"""


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load(str(ROOT / "examples" / "deepscout"))


@pytest.fixture(scope="module")
def uav_model():
    return longeron.load(str(ROOT / "examples" / "deepscout"))


@pytest.fixture()
def ex(drone_model):
    return explore(drone_model, layout="inline")  # deterministic headless


def _reference_count(namespace) -> int:
    """Independent reference walk: the elements the tree must show."""

    total = 0
    for member in namespace.members:
        if isinstance(
            member,
            (
                M.Package,
                M.Definition,
                M.Usage,
                M.Import,
                M.Alias,
                M.Expose,
                M.Dependency,
                M.ElementFilter,
            ),
        ):
            total += 1
            if isinstance(member, M.Namespace):
                total += _reference_count(member)
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
        root = nodes[0]  # the multi-package program keeps the model root
        packages = {child["id"] for child in root["children"]}
        assert {"DeepScout", "Rotorcraft", "ScoutParts", "ScoutMissions"} <= packages
        # the shared equipment lives on the abstract base...
        base = _find(nodes, "DeepScout::MultiRotor")
        assert base is not None
        battery = _find(base["children"], "DeepScout::MultiRotor::battery")
        assert battery is not None
        # ...and each configuration owns its rotor population
        quad = _find(nodes, "Rotorcraft::QuadCopter")
        assert _find(quad["children"], "Rotorcraft::QuadCopter::motors") is not None
        # and NOT reachable outside the abstract base
        rotorcraft = _find(nodes, "Rotorcraft")
        assert _find(rotorcraft["children"], "DeepScout::MultiRotor::battery") is None

    def test_node_ids_are_qualified_names(self, drone_model):
        _, index = _tree_data(drone_model)
        named = {nid for nid in index if not nid.startswith("~")}
        assert "DeepScout::FlightStates::idle" in named
        for nid in named:
            assert index[nid].qualified_name == nid

    def test_kind_badges_and_families(self, drone_model):
        nodes, _ = _tree_data(drone_model)
        cases = {
            "Rotorcraft": ("pkg", "package"),
            "Rotorcraft::QuadCopter": ("part def", "structure"),
            "DeepScout::FlightStates": ("state def", "behavior"),
            "DeepScout::PlanBattery": ("action def", "behavior"),
            "DeepScout::FlightEnvelope": ("requirement def", "requirement"),
            "DeepScout::FlightMode": ("enum def", "data"),
            "DeepScout::HoverTime": ("calc def", "behavior"),
            "DeepScout::MultiRotor::battery": ("part", "structure"),
            "DeepScout::MultiRotor::payloadMass": ("attribute", "data"),
        }
        for node_id, (badge, kind) in cases.items():
            node = _find(nodes, node_id)
            assert node is not None, node_id
            assert (node["badge"], node["kind"]) == (badge, kind), node_id

    def test_has_children_hints_lazy_loading(self, drone_model):
        nodes, _ = _tree_data(drone_model)
        quad = _find(nodes, "Rotorcraft::QuadCopter")
        assert quad["has_children"] is True and quad["children"]
        leaf = _find(nodes, "DeepScout::MultiRotor::payloadMass")
        assert leaf["has_children"] is False and "children" not in leaf

    def test_typed_usages_carry_a_type_suffix(self, drone_model):
        nodes, _ = _tree_data(drone_model)
        battery = _find(nodes, "DeepScout::MultiRotor::battery")
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
        assert node["kind"] == "relationship"

    def test_single_package_model_flattens_to_the_package(self):
        # the language has no model-level name: the lone top-level
        # package IS the model's humanized name, so it is the tree root
        model = longeron.loads("package Solo { part def S; }", source_name="dir/solo.sysml")
        nodes, index = _tree_data(model)
        assert len(nodes) == 1
        root = nodes[0]
        assert isinstance(index[root["id"]], M.Package)
        assert root["label"] == "Solo"
        assert root["tooltip"].endswith("solo.sysml \u2014 Solo") or (
            "solo.sysml" in root["tooltip"]
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

    def test_set_nodes_replaces_the_tree(self, drone_model):
        small_model = longeron.loads("package Solo { part def S; }")
        tree = ModelTree(_tree_data(small_model)[0])
        small = tree.total_count
        tree.set_nodes(_tree_data(drone_model)[0])
        assert tree.total_count > small


# ---------------------------------------------------------------------------
# relationships: classification, the toggle, and selection mapping
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def rels_model():
    return longeron.loads(RELATIONSHIPS_MODEL, source_name="rels.sysml")


def _node_for(nodes, index, predicate):
    element = next(el for el in index.values() if predicate(el))
    return _find(nodes, next(nid for nid, el in index.items() if el is element)), element


class TestRelationshipClassification:
    """The classification table: every relationship kind is a tree row
    under its owner, kind='relationship', with the pinned chip + label."""

    #: (finder, expected label, expected badge) -- the classification table
    TABLE: typing.ClassVar[dict] = {
        "satisfy": (lambda el: isinstance(el, M.SatisfyUsage), "satisfy massBudget", "satisfy"),
        "verify": (
            lambda el: isinstance(el, M.Usage) and el.kind == "verify",
            "verify massBudget",
            "verify",
        ),
        "connection (anonymous)": (
            lambda el: isinstance(el, M.ConnectionUsage) and not el.name,
            "connect a1 to b1",
            "connection",
        ),
        "connection (named, n-ary)": (
            lambda el: isinstance(el, M.ConnectionUsage) and el.name == "namedConn",
            "namedConn",
            "connection",
        ),
        "interface": (lambda el: isinstance(el, M.InterfaceUsage), "plug", "interface"),
        "dependency": (lambda el: isinstance(el, M.Dependency), "Dep", "dependency"),
        "allocation": (
            lambda el: isinstance(el, M.AllocationUsage),
            "allocate a1 to b1",
            "allocation",
        ),
        "binding": (
            lambda el: isinstance(el, M.BindingConnector),
            "bind a1.x = b1.x",
            "binding",
        ),
        "flow": (
            lambda el: isinstance(el, M.FlowUsage) and el.kind == "flow",
            "flow a1.x to b1.x",
            "flow",
        ),
        "message": (
            lambda el: isinstance(el, M.FlowUsage) and el.kind == "message",
            "msg",
            "message",
        ),
        "import": (lambda el: isinstance(el, M.Import), "import Other::*", "import"),
        "filter": (lambda el: isinstance(el, M.ElementFilter), "filter @Safety", "filter"),
        "expose": (lambda el: isinstance(el, M.Expose), "expose Rels::**", "expose"),
        "alias": (lambda el: isinstance(el, M.Alias), "also", "alias"),
    }

    def test_every_relationship_kind_is_classified(self, rels_model):
        nodes, index = _tree_data(rels_model)
        for name, (finder, label, badge) in self.TABLE.items():
            node, _ = _node_for(nodes, index, finder)
            assert node is not None, name
            assert node["kind"] == "relationship", name
            assert node["label"] == label, name
            assert node["badge"] == badge, name

    def test_relationships_sit_under_their_owner(self, rels_model):
        nodes, index = _tree_data(rels_model)
        rels = _find(nodes, "Rels")
        satisfy_node, satisfy = _node_for(nodes, index, lambda el: isinstance(el, M.SatisfyUsage))
        assert satisfy.owner is rels_model.find("Rels")
        assert any(child is satisfy_node for child in rels["children"])
        # the expose is owned by the VIEW usage, so it nests under it
        view = _find(nodes, "Rels::rig")
        expose_node, expose = _node_for(nodes, index, lambda el: isinstance(el, M.Expose))
        assert expose.owner is rels_model.find("Rels::rig")
        assert any(child is expose_node for child in view["children"])

    def test_relationship_tooltips_carry_the_full_declaration(self, rels_model):
        nodes, index = _tree_data(rels_model)
        cases = {
            M.SatisfyUsage: "satisfy massBudget by a1;",
            M.Expose: "expose Rels::**;",
            M.Import: "import Other::*;",
            M.Dependency: "dependency Dep from a1 to b1;",
        }
        for cls, expected in cases.items():
            node, _ = _node_for(nodes, index, lambda el, c=cls: isinstance(el, c))
            assert node["tooltip"] == expected, cls.__name__

    def test_documentation_and_comments_stay_out(self, rels_model):
        _nodes, index = _tree_data(rels_model)
        assert not any(isinstance(el, (M.Documentation, M.Comment)) for el in index.values())

    def test_annotations_are_not_relationships(self, rels_model):
        # metadata / documentation annotate, they do not relate
        doc = next(el for el in rels_model.iter_tree() if isinstance(el, M.Documentation))
        assert not explorer_module._is_relationship(doc)
        safety = rels_model.find("Other::Safety")
        assert not explorer_module._is_relationship(safety)

    def test_non_relationship_families_are_untouched(self, rels_model):
        nodes, _ = _tree_data(rels_model)
        assert _find(nodes, "Rels::a1")["kind"] == "structure"
        assert _find(nodes, "Rels::massBudget")["kind"] == "requirement"
        assert _find(nodes, "Rels::rig")["kind"] == "structure"  # the view usage


def test_relationships_present_in_tree_REGRESSION_GUARD(rels_model):
    """THE TRIPWIRE: relationship rows must never silently vanish from
    the tree again.

    Forensic note (2026-08-30): a 'tree relationships vanished' regression
    was reported against the drone example.  The feature (6ca066f) was in
    fact INTACT -- at the time ``examples/deepscout`` simply declared no
    relationships, so its tree honestly showed none.  (The drone model has
    since gained real declarations -- satisfy/connect/flow/allocate/
    dependency -- pinned by ``test_drone_tree_shows_its_relationships``.)
    This guard pins the feature itself, loudly, on a model that HAS one of
    every kind: if a merge ever drops the ``_is_relationship`` /
    ``_in_tree`` / ``_tree_data`` hunks, this fails by NAME.
    """

    nodes, _index = _tree_data(rels_model)

    def walk(items):
        for node in items:
            yield node
            yield from walk(node.get("children", []))

    rows = [node for node in walk(nodes) if node["kind"] == "relationship"]
    assert len(rows) > 0, "the tree-relationships feature is GONE (see 6ca066f)"
    # ...and the WHOLE classification table is present, kind by kind
    badges = {node["badge"] for node in rows}
    expected = {badge for _f, _l, badge in TestRelationshipClassification.TABLE.values()}
    assert badges == expected, f"missing relationship kinds: {expected - badges}"


def test_drone_tree_shows_its_relationships(drone_model):
    """The flagship example now DECLARES relationships (the 2026-08-30
    finding's real fix): the explorer tree carries a row for each --
    the power/control wiring, the satisfy edges, the state-machine
    allocation, and the planning dependency."""

    nodes, _index = _tree_data(drone_model)

    def walk(items):
        for node in items:
            yield node
            yield from walk(node.get("children", []))

    rows = [node for node in walk(nodes) if node["kind"] == "relationship"]
    from collections import Counter

    badges = Counter(node["badge"] for node in rows)
    assert badges["connection"] == 10  # powerHarness, controlLink,
    #   phaseLeads (quad + hexa + octo), frontLeads, tailLead,
    #   tiltLinkage, upperLeads, lowerLeads
    assert badges["satisfy"] == 13  # FlightEnvelope x5, mission x4,
    #   installation (quad only), FailSafeHover x3 (hexa + octo + X8)
    assert badges["flow"] == 1  # dcBus: battery.voltage -> esc.busVoltage
    assert badges["allocation"] == 1  # FlightStates -> FlightController
    assert badges["dependency"] == 1  # PlanBattery -> HoverTime
    assert badges["import"] == 34  # the program's cross-file wiring
    #   (25 + the 6 imports of surfaces.sysml's ScoutSurfaces package)
    labels = {node["label"] for node in rows}
    assert "satisfy mission" in labels  # by the quad; the tri busts it


class TestRelationshipToggle:
    """ModelTree.show_relationships: the tree-toolbar toggle's trait."""

    def test_defaults_on(self, rels_model):
        tree = ModelTree(_tree_data(rels_model)[0])
        assert tree.show_relationships is True

    def test_toggle_off_drops_relationships_from_the_total(self, rels_model):
        nodes, index = _tree_data(rels_model)
        tree = ModelTree(nodes)
        every = tree.total_count
        rels = sum(1 for el in index.values() if explorer_module._is_relationship(el))
        assert rels == len(TestRelationshipClassification.TABLE)
        tree.show_relationships = False
        assert tree.total_count == every - rels
        tree.show_relationships = True
        assert tree.total_count == every

    def test_match_count_respects_the_toggle(self, rels_model):
        tree = ModelTree(_tree_data(rels_model)[0])
        tree.query = "satisfy massBudget"
        assert tree.match_count == 1
        tree.show_relationships = False
        assert tree.match_count == 0
        # non-relationship matches are untouched by the toggle
        tree.query = "massBudget"
        assert tree.match_count == 1  # the requirement row itself
        tree.show_relationships = True
        assert tree.match_count == 3  # ... plus the satisfy and verify rows

    def test_toggle_filters_presentation_not_payload(self, rels_model):
        # rows vanish browser-side; the nodes payload keeps them, so
        # flipping the trait back never rebuilds the tree data
        import json as json_module

        tree = ModelTree(_tree_data(rels_model)[0])
        payload = tree.nodes_json
        tree.show_relationships = False
        assert tree.nodes_json == payload
        assert "satisfy massBudget" in json_module.dumps(json_module.loads(payload))


class TestRelationshipSelection:
    """Tree <-> diagram selection for relationship rows: drawn edges map
    both ways through the widget's ``_lgn_rel_edges`` seam; undrawn
    relationships fall back to the owner's diagram + nearest drawn
    ancestor."""

    @pytest.fixture()
    def rex(self, rels_model):
        return explore(rels_model, layout="inline")

    def _element(self, rex, predicate):
        return next(el for el in rex._index.values() if predicate(el))

    def test_structure_widgets_carry_the_edge_seam(self, rex):
        rex.select("Rels")
        seam = rex.diagram._lgn_rel_edges
        assert seam  # satisfy + connections + dependency + allocate + ...
        for edge_id, element in seam.items():
            assert edge_id.startswith("__lgn__:")  # synthetic transport ids
            assert explorer_module._is_relationship(element)

    def test_tree_selection_highlights_the_drawn_edge(self, rex, rels_model):
        satisfy = self._element(rex, lambda el: isinstance(el, M.SatisfyUsage))
        rex.select(satisfy)
        assert rex.element is satisfy
        ids = tuple(rex.diagram.view.selection.ids)
        assert len(ids) == 1
        assert rex.diagram._lgn_rel_edges[ids[0]] is satisfy

    def test_nary_connection_selects_every_leg(self, rex):
        nary = self._element(
            rex, lambda el: isinstance(el, M.ConnectionUsage) and el.name == "namedConn"
        )
        rex.select(nary)
        ids = tuple(rex.diagram.view.selection.ids)
        assert len(ids) == 3  # a junction edge per end
        assert all(rex.diagram._lgn_rel_edges[i] is nary for i in ids)

    def test_edge_click_selects_and_reveals_the_row(self, rex):
        rex.select("Rels")
        widget = rex.diagram
        connect = self._element(rex, lambda el: isinstance(el, M.ConnectionUsage) and not el.name)
        edge_id = next(i for i, el in widget._lgn_rel_edges.items() if el is connect)
        widget.view.selection.ids = [edge_id]  # a browser edge click
        assert rex.element is connect
        assert rex.tree.selected == [rex._ids[id(connect)]]
        assert rex.diagram is widget  # the clicked diagram is NOT rebuilt

    def test_edge_click_echo_settles(self, rex):
        rex.select("Rels")
        widget = rex.diagram
        satisfy = self._element(rex, lambda el: isinstance(el, M.SatisfyUsage))
        edge_id = next(i for i, el in widget._lgn_rel_edges.items() if el is satisfy)
        tree_writes: list = []
        diagram_writes: list = []
        rex.tree.observe(lambda ch: tree_writes.append(ch["new"]), "selected")
        widget.view.selection.observe(lambda ch: diagram_writes.append(ch["new"]), "ids")
        widget.view.selection.ids = [edge_id]
        assert tree_writes == [[rex._ids[id(satisfy)]]]
        assert diagram_writes == [(edge_id,)]  # only the click itself

    def test_undrawn_relationship_falls_back_to_the_ancestor(self, rex, rels_model):
        expose = self._element(rex, lambda el: isinstance(el, M.Expose))
        rex.select(expose)
        assert rex.element is expose
        assert rex.kind == "structure"
        # the owning view usage is the nearest DRAWN ancestor
        assert tuple(rex.diagram.view.selection.ids) == ("Rels::rig",)

    def test_relationship_scope_is_the_owning_package(self, rex, rels_model):
        # spec: selecting a relationship shows the OWNER's diagram
        rex.select("Rels")
        package_widget = rex.diagram
        satisfy = self._element(rex, lambda el: isinstance(el, M.SatisfyUsage))
        rex.select(satisfy)
        assert rex.diagram is package_widget  # same scope: cached widget

    def test_relationship_scope_pins_to_owner_in_element_mode(self, rels_model):
        rex = explore(rels_model, layout="inline", structure_scope="element")
        connect = next(
            el for el in rex._index.values() if isinstance(el, M.ConnectionUsage) and not el.name
        )
        rex.select(connect)
        ids = _diagram_node_ids(rex.diagram)
        # the OWNER package is the scope (a connection usage is a
        # namespace, but it is not a drawable scope of its own)
        assert {"Rels::a1", "Rels::b1"} <= ids


# ---------------------------------------------------------------------------
# compartment rows in the linked views
# ---------------------------------------------------------------------------

ROWS_MODEL = """
package Rig {
    item def Pulse;
    part def Axle {
        attribute len : Real = 1.5;
        port tap : Tap;
    }
    port def Tap { in item x : Pulse; }
    part axle : Axle;
}
"""


class TestRowSelection:
    """Compartment rows are first-class linked-view citizens: they carry
    their element's identity (qualified-name ids, the ipyelk selectable
    flag), a tree selection highlights the ROW itself -- not just the
    owning box -- and a row click selects and reveals the element in the
    tree through the SAME seam as node and edge clicks.  Port squares
    ride the same contract."""

    @pytest.fixture()
    def rex(self):
        return explore(longeron.loads(ROWS_MODEL), layout="inline")

    def test_diagram_ids_include_rows_and_ports(self, rex):
        rex.select("Rig::Axle")
        ids = _diagram_node_ids(rex.diagram)
        assert "Rig::Axle::len" in ids  # the attribute ROW
        assert "Rig::Axle::tap" in ids  # the boundary port square

    def test_tree_selection_highlights_the_row(self, rex):
        rex.select("Rig::Axle::len")
        assert rex.element is rex._index["Rig::Axle::len"]
        assert tuple(rex.diagram.view.selection.ids) == ("Rig::Axle::len",)

    def test_tree_selection_highlights_the_port_square(self, rex):
        rex.select("Rig::Axle::tap")
        assert tuple(rex.diagram.view.selection.ids) == ("Rig::Axle::tap",)

    def test_row_click_selects_and_reveals_the_element(self, rex):
        rex.select("Rig")
        widget = rex.diagram
        widget.view.selection.ids = ["Rig::Axle::len"]  # a browser row click
        assert rex.element is rex._index["Rig::Axle::len"]
        assert rex.tree.selected == ["Rig::Axle::len"]
        assert rex.diagram is widget  # the clicked diagram is NOT rebuilt

    def test_row_click_echo_settles(self, rex):
        rex.select("Rig")
        widget = rex.diagram
        tree_writes: list = []
        diagram_writes: list = []
        rex.tree.observe(lambda ch: tree_writes.append(ch["new"]), "selected")
        widget.view.selection.observe(lambda ch: diagram_writes.append(ch["new"]), "ids")
        widget.view.selection.ids = ["Rig::Axle::len"]
        assert tree_writes == [["Rig::Axle::len"]]
        assert diagram_writes == [("Rig::Axle::len",)]  # only the click itself


# ---------------------------------------------------------------------------
# applicable diagram kinds
# ---------------------------------------------------------------------------


class TestApplicableKinds:
    def test_all_kinds_are_known(self):
        assert DIAGRAM_KINDS == ("structure", "state", "action", "requirements")

    def test_per_element_kind(self, drone_model):
        cases = {
            "Rotorcraft": ("structure", "requirements"),
            "Rotorcraft::QuadCopter": ("structure", "requirements"),
            "DeepScout::MultiRotor::battery": ("structure", "requirements"),
            "DeepScout::FlightStates": ("structure", "state", "requirements"),
            "DeepScout::FlightStates::idle": ("structure", "state", "requirements"),
            "DeepScout::PlanBattery": ("structure", "action", "requirements"),
            "DeepScout::FlightEnvelope": ("structure", "requirements"),
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
        assert applicable_kinds(uav_model.find("ScoutMissions::Catalog")) == ("structure",)
        kinds = applicable_kinds(uav_model.find("ScoutMissions::MissionRequirements"))
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
        assert "DeepScout::FlightEnvelope" in ids
        # the satisfying configurations are pulled in through their
        # satisfy edges; UNwired structure stays out of the projection
        assert "Rotorcraft::QuadCopter" in ids
        assert "Rotorcraft::TriCopter" in ids
        assert "ScoutParts::F450Kit::Battery" not in ids

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
        # multi-package program: the root row (and thus the initial
        # selection) is the model root spanning every package
        assert isinstance(ex.element, M.Model)
        assert ex.kind == "structure"
        assert type(ex.diagram).__name__ == "Diagram"
        assert ex.tree.selected  # the model root node is selected
        assert tuple(ex.kind_switcher.options) == ("structure", "requirements")

    def test_tree_selection_renders_and_highlights(self, ex, drone_model):
        ex.tree.selected = ["Rotorcraft::QuadCopter"]
        assert ex.element is drone_model.find("Rotorcraft::QuadCopter")
        assert tuple(ex.diagram.view.selection.ids) == ("Rotorcraft::QuadCopter",)

    def test_kind_switcher_offers_only_applicable_kinds(self, ex):
        ex.select("DeepScout::FlightStates")
        assert tuple(ex.kind_switcher.options) == ("structure", "state", "requirements")
        ex.select("DeepScout::PlanBattery")
        assert tuple(ex.kind_switcher.options) == ("structure", "action", "requirements")

    def test_kind_switch_preserves_the_selection(self, ex):
        ex.select("DeepScout::FlightStates")
        structure = ex.diagram
        ex.kind = "state"
        assert ex.diagram is not structure
        assert ex.tree.selected == ["DeepScout::FlightStates"]
        assert ex.element.qualified_name == "DeepScout::FlightStates"
        ex.kind = "structure"
        assert ex.diagram is structure  # cached: same widget object

    def test_inapplicable_kind_is_rejected(self, ex):
        ex.select("Rotorcraft::QuadCopter")
        with pytest.raises(ValueError, match="kind must be one of"):
            ex.kind = "state"

    def test_nested_state_scopes_to_its_machine(self, ex):
        ex.select("DeepScout::FlightStates::idle")
        ex.kind = "state"
        ids = _diagram_node_ids(ex.diagram)
        assert "DeepScout::FlightStates::flying" in ids  # the whole machine
        assert tuple(ex.diagram.view.selection.ids) == ("DeepScout::FlightStates::idle",)

    def test_attribute_selection_highlights_its_row(self, ex):
        # attributes render as compartment ROWS -- first-class selection
        # targets: the row itself highlights, not just the owning box
        # (the ancestor fallback for genuinely undrawn elements keeps its
        # coverage in test_undrawn_relationship_falls_back_to_the_ancestor)
        ex.select("ScoutParts::F450Kit::Battery::capacity")
        assert tuple(ex.diagram.view.selection.ids) == ("ScoutParts::F450Kit::Battery::capacity",)

    def test_diagrams_are_cached_per_scope_and_kind(self, ex):
        ex.select("ScoutParts::F450Kit::Battery")
        first = ex.diagram
        ex.select("ScoutParts::F450Kit::Motor")
        assert ex.diagram is first  # same package scope, same widget

    def test_diagram_click_selects_and_reveals_in_the_tree(self, ex):
        # scope inside the program root, where the action def lives
        ex.select("DeepScout::MultiRotor")
        widget = ex.diagram
        widget.view.selection.ids = ["DeepScout::PlanBattery"]  # a browser click
        assert ex.tree.selected == ["DeepScout::PlanBattery"]
        assert "action" in ex.kind_switcher.options
        assert ex.diagram is widget  # the clicked diagram is NOT rebuilt

    def test_no_selection_echo(self, ex):
        """One hop each way; every trait settles after a single write."""

        ex.select("DeepScout::MultiRotor")
        widget = ex.diagram
        tree_writes: list = []
        diagram_writes: list = []
        ex.tree.observe(lambda ch: tree_writes.append(ch["new"]), "selected")
        widget.view.selection.observe(lambda ch: diagram_writes.append(ch["new"]), "ids")

        widget.view.selection.ids = ["DeepScout::PlanBattery"]  # diagram -> tree
        assert tree_writes == [["DeepScout::PlanBattery"]]
        assert diagram_writes == [("DeepScout::PlanBattery",)]  # only the click itself

        ex.tree.selected = ["DeepScout::FlightStates"]  # tree -> diagram
        assert tree_writes == [["DeepScout::PlanBattery"], ["DeepScout::FlightStates"]]
        assert diagram_writes == [("DeepScout::PlanBattery",), ("DeepScout::FlightStates",)]

    def test_reselecting_the_same_element_is_a_fixpoint(self, ex):
        ex.select("Rotorcraft::QuadCopter")
        widget = ex.diagram
        tree_writes: list = []
        diagram_writes: list = []
        ex.tree.observe(lambda ch: tree_writes.append(ch["new"]), "selected")
        widget.view.selection.observe(lambda ch: diagram_writes.append(ch["new"]), "ids")
        ex.select("Rotorcraft::QuadCopter")
        assert ex.diagram is widget
        assert tree_writes == [] and diagram_writes == []

    def test_diagram_click_on_undrawn_element_reveals_the_ancestor(self, ex):
        # expanded-submachine ids resolve through typing hops: the tree
        # reveals the nearest element it knows
        ex.select("DeepScout::FlightStates")
        ex.kind = "state"
        ex.diagram.view.selection.ids = ["DeepScout::FlightStates::flying"]
        assert ex.tree.selected == ["DeepScout::FlightStates::flying"]

    def test_select_by_element(self, ex, drone_model):
        ex.select(drone_model.find("DeepScout::HoverTime"))
        assert ex.tree.selected == ["DeepScout::HoverTime"]

    def test_select_unknown_raises(self, ex):
        from longeron.errors import ResolutionError

        with pytest.raises(ResolutionError):
            ex.select("No::Such::Thing")

    def test_requirements_kind_renders_the_requirements_view(self, ex):
        # scope from the branch package, where the satisfy edges live
        ex.select("Rotorcraft::QuadCopter")
        ex.kind = "requirements"
        ids = _diagram_node_ids(ex.diagram)
        assert "DeepScout::FlightEnvelope" in ids
        # wired in by its satisfy edges; unwired structure stays out
        assert "Rotorcraft::QuadCopter" in ids
        assert "ScoutParts::F450Kit::Battery" not in ids

    def test_structure_scope_element_mode(self, drone_model):
        ex = explore(drone_model, structure_scope="element")
        ex.select("Rotorcraft::QuadCopter")
        ids = _diagram_node_ids(ex.diagram)
        assert "Rotorcraft::QuadCopter" in ids
        assert "DeepScout::FlightStates" not in ids  # siblings stay out

    def test_bad_structure_scope_rejected(self, drone_model):
        with pytest.raises(ValueError, match="structure_scope"):
            Explorer(drone_model, structure_scope="galaxy")

    def test_uav_selection_is_one_cheap_hop(self, uav_model):
        """No O(n^2) rebuilds: re-selecting inside one package reuses the
        cached diagram, and only the selection trait changes."""

        ex = explore(uav_model)
        ex.select("ScoutMissions::Catalog")
        widget = ex.diagram
        built = len(ex._diagrams)
        for qname in (
            "ScoutMissions::Catalog::AirframeChoice",
            "ScoutMissions::Catalog::MotorChoice",
            "ScoutMissions::Catalog::AirframeChoice",
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
        ex.select("DeepScout::FlightStates")
        assert stub.selected == ["DeepScout::FlightStates"]
        assert stub.revealed[-1] == "DeepScout::FlightStates"
        assert "state" in ex.kind_switcher.options
        # engine -> explorer (a user click in the engine); no echo write-back
        writes = stub.selected_writes
        stub.click(["DeepScout::PlanBattery"])
        assert ex.element.qualified_name == "DeepScout::PlanBattery"
        assert "action" in ex.kind_switcher.options
        assert stub.selected_writes == writes

    def test_diagram_click_reaches_a_stub_engine(self, drone_model):
        stub = StubTree()
        ex = Explorer(drone_model, tree=stub, layout="inline")
        ex.select("Rotorcraft::QuadCopter")
        writes = stub.selected_writes
        ex.diagram.view.selection.ids = ["ScoutParts::F450Kit::Battery"]  # a browser click
        assert stub.selected == ["ScoutParts::F450Kit::Battery"]
        assert stub.selected_writes == writes + 1  # exactly one write
        assert stub.revealed[-1] == "ScoutParts::F450Kit::Battery"

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
        ex.select("DeepScout::FlightStates")
        assert ex.tree.selected == ["DeepScout::FlightStates"]
        assert tuple(ex.diagram.view.selection.ids) == ("DeepScout::FlightStates",)

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
# pane layout: the diagram area fills the pane; inline stays bounded
# ---------------------------------------------------------------------------


class TestPaneFill:
    def test_diagram_box_grows_and_header_stays_fixed(self, ex):
        # the vertical chain: header flex-none, diagram box flex-grow-1
        # with a zero min-height (min-height:auto would turn the diagram
        # widget's floor into the rendered height -- the '400px strip')
        box = ex._diagram_box
        assert box.layout.flex == "1 1 0%"
        assert box.layout.min_height == "0"
        assert box.layout.overflow == "hidden"
        assert box.layout.width == "100%"
        header = ex._pane.children[0]
        assert header.layout.flex == "0 0 auto"

    def test_diagram_widgets_defer_to_the_pane(self, ex):
        # built widgets fill the box exactly; the stock 400px min-height
        # floor (diagrams shown OUTSIDE the explorer keep it) is lifted
        ex.select("Rotorcraft::QuadCopter")
        assert ex.diagram.layout.height == "100%"
        assert ex.diagram.layout.width == "100%"
        assert ex.diagram.layout.min_height == "0"

    def test_inline_pane_honors_the_height_parameter(self, drone_model):
        ex = explore(drone_model, layout="inline", height="420px")
        assert ex._pane.layout.height == "420px"
        assert ex.tree.layout.height == "420px"

    def test_headless_inline_pane_is_bounded_too(self, drone_model):
        ex = Explorer(drone_model, tree=StubTree(), layout="inline", height="500px")
        assert ex._pane.layout.height == "500px"

    def test_docked_pane_fills_the_panel(self, drone_model, monkeypatch):
        _install_stub_ipylab(monkeypatch)
        ex = explore(drone_model, layout="lab", height="420px")
        # the dock, not the height parameter, owns the panel's size
        assert ex._pane.layout.height == "100%"
        assert ex._pane.layout.width == "100%"
        assert ex.tree.layout.height == "100%"
        assert ex._diagram_box.layout.flex == "1 1 0%"


# ---------------------------------------------------------------------------
# fit plumbing: the widgets' own sentinels do the work; the explorer only
# adds the kind-switch re-show refit (and the docked panel's first reveal)
# ---------------------------------------------------------------------------


class TestFitSentinel:
    def test_explorer_attaches_no_pane_sentinel(self, ex):
        # the fit machinery moved to the SOURCE (diagrams._finish mounts
        # a sentinel inside every built widget): the explorer must not
        # double-attach its own pane-level reporter
        assert not hasattr(ex, "_fit_sentinel")
        kinds = {type(child).__name__ for child in ex._pane.children}
        assert "_FitSentinel" not in kinds

    def test_shown_widget_carries_its_own_sentinel(self, ex):
        from longeron.toolbar import AutoFitTool

        ex.select("Rotorcraft::QuadCopter")
        tool = ex.diagram.get_tool(AutoFitTool)
        assert tool.sentinel is not None
        assert tool.sentinel in ex.diagram.children  # INSIDE the widget's DOM

    def test_fresh_view_report_refits_the_widget(self, ex):
        from longeron.toolbar import AutoFitTool

        ex.select("Rotorcraft::QuadCopter")
        tool = ex.diagram.get_tool(AutoFitTool)
        before = tool.fit_count
        stamp = tool.sentinel.fit_stamp
        tool.sentinel.fresh += 1  # what the browser reports on a view swap
        assert tool.fit_count == before + 1
        # every auto-fit clears the browser's user-interaction latch
        assert tool.sentinel.fit_stamp == stamp + 1

    def test_resize_report_refits_the_widget(self, ex):
        from longeron.toolbar import AutoFitTool

        ex.select("Rotorcraft::QuadCopter")
        tool = ex.diagram.get_tool(AutoFitTool)
        before = tool.fit_count
        tool.sentinel.resized += 1  # a debounced, latch-guarded resize
        assert tool.fit_count == before + 1

    def test_reshow_refit_targets_the_reshown_widget(self, ex, monkeypatch):
        # the AutoFitTool seam, spied: switching kinds away and back
        # re-shows the CACHED widget, and the kernel must fit exactly the
        # re-shown widget (its live view hears the fit -- see _show)
        from longeron import toolbar

        fitted: list = []
        monkeypatch.setattr(
            toolbar.AutoFitTool, "refit_now", lambda tool: fitted.append(tool._diagram)
        )
        ex.select("DeepScout::FlightStates")
        structure = ex.diagram
        ex.kind = "state"
        state = ex.diagram
        assert state is not structure
        ex.kind = "structure"
        assert ex.diagram is structure  # cached: the SAME widget re-enters
        assert fitted and fitted[-1] is structure  # ... freshly fitted
        ex.kind = "state"
        assert fitted[-1] is state  # and the same on the way back

    def test_built_widgets_persist_as_display_toggled_children(self, ex):
        # swapping children would DESTROY the outgoing browser view (whose
        # model listeners the vendored frontend never unbinds): built
        # widgets must STAY in the box, exactly one displayed
        ex.select("DeepScout::FlightStates")
        structure = ex.diagram
        ex.kind = "state"
        state = ex.diagram
        assert {structure, state} <= set(ex._diagram_box.children)
        assert structure.layout.display == "none"
        assert state.layout.display is None  # displayed
        ex.kind = "structure"
        assert {structure, state} <= set(ex._diagram_box.children)  # both kept
        assert state.layout.display == "none"
        assert structure.layout.display is None

    def test_first_build_is_not_kernel_refitted(self, ex, monkeypatch):
        # a brand-new widget has no browser view yet -- a kernel fit
        # would be dropped; its fit is the sentinel's ``fresh`` report
        # (plus the AutoFitTool's own first-layout fit)
        from longeron import toolbar

        fitted: list = []
        monkeypatch.setattr(
            toolbar.AutoFitTool, "refit_now", lambda tool: fitted.append(tool._diagram)
        )
        ex.select("DeepScout::FlightStates")
        ex.kind = "state"  # builds the state widget
        assert ex.diagram not in fitted

    def test_refits_are_safe_without_a_diagram(self, drone_model):
        ex = Explorer(drone_model, tree=StubTree(), layout="inline")
        ex._diagram_box.children = ()  # no visible diagram
        ex._refit_current()  # must not raise


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
