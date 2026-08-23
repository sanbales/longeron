"""Diagram construction tests (headless -- rendering happens in the browser)."""

import pytest

pytest.importorskip("ipyelk")

import longeron
from longeron import diagrams
from longeron import model as M

_TYPED_SUBMACHINE = """
package P {
    state def Inner {
        entry; then a;
        state a;
        transition first a accept go then b;
        state b;
    }
    state def Outer {
        entry; then x;
        state x : Inner;
        transition first x accept quit then off;
        state off;
    }
}
"""


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load("examples/drone.sysml")


class TestStructure:
    def test_builds(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        assert type(widget).__name__ == "Diagram"

    def test_node_ids_are_qualified_names(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        ids = {n.id for n in _walk(widget.source.value) if n.id}
        assert {"Drone", "Drone::QuadCopter", "Drone::Battery"} <= ids

    def test_attribute_compartments(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        battery = next(n for n in _walk(widget.source.value) if n.id == "Drone::Battery")
        texts = [label.text for label in battery.labels]
        assert any("capacity : Real = 5200.0" in t for t in texts)

    def test_attribute_rows_pre_sized_to_shared_width(self, drone_model):
        """Regression (V2): attribute rows are pre-sized to the node's widest
        label so ELK's centered boxes share one left edge (left-aligned
        compartments); title/stereotype labels stay snug and centered."""

        from longeron.render import _measure

        widget = diagrams.structure_diagram(drone_model)
        battery = next(n for n in _walk(widget.source.value) if n.id == "Drone::Battery")
        rows = [
            label
            for label in battery.labels
            if "sysml-attribute" in (label.properties.cssClasses or "")
        ]
        assert len(rows) >= 2
        expected = max(
            _measure(label.text or "", label.properties.cssClasses or "")[0]
            for label in battery.labels
        )
        for label in rows:
            shape = label.properties.get_shape()
            assert shape.width == expected
            assert shape.height is not None
        title = next(label for label in battery.labels if label.text == "Battery")
        assert title.properties.get_shape().width is None  # browser measures it

    def test_multiplicity_shown(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        rotors = next(n for n in _walk(widget.source.value) if n.id == "Drone::QuadCopter::rotors")
        assert any("rotors : Rotor [4]" in label.text for label in rotors.labels)

    def test_parameter_rows(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        hover = next(n for n in _walk(widget.source.value) if n.id == "Drone::HoverTime")
        texts = [label.text for label in hover.labels]
        assert "in capacity : Real" in texts
        assert "return : Real" in texts

    def test_requirement_and_constraint_rows(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        envelope = next(n for n in _walk(widget.source.value) if n.id == "Drone::FlightEnvelope")
        texts = " | ".join(label.text for label in envelope.labels)
        assert "subject drone : QuadCopter" in texts
        assert "require hoverMargin" in texts
        quad = next(n for n in _walk(widget.source.value) if n.id == "Drone::QuadCopter")
        quad_texts = " | ".join(label.text for label in quad.labels)
        assert "assert takeoffMassLimit" in quad_texts

    def test_typing_edges(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        edges = widget.source.value.edges
        assert len(edges) >= 3  # chassis/battery/rotors -> their defs
        classes = {e.properties.cssClasses for e in edges}
        assert any("sysml-edge-typed" in c for c in classes)

    def test_specialization_edges(self):
        model = longeron.loads("""
            package P {
                part def Base;
                part def Derived :> Base;
            }
        """)
        widget = diagrams.structure_diagram(model)
        edges = widget.source.value.edges
        assert len(edges) == 1
        assert "sysml-edge-specializes" in edges[0].properties.cssClasses
        # spec notation: a (hollow) triangle pointing at the general
        assert edges[0].properties.shape.end == "generalization"

    def test_specialization_family_heads_are_hollow_triangles(self, drone_model):
        """SysML v2 notation: the whole specialization family points at the
        general/type with a closed hollow triangle -- white-filled in the
        stylesheet; feature typing carries the colon-dot shaft adornment
        (symbol id ``generalization-colon``, errata E2)."""

        widget = diagrams.structure_diagram(drone_model)
        typed = [
            e for e in widget.source.value.edges if "sysml-edge-typed" in e.properties.cssClasses
        ]
        assert typed
        assert all(e.properties.shape.end == "generalization-colon" for e in typed)
        assert diagrams.SYSML_STYLE[" .sysml-edge-typed > .elkarrow"]["fill"] == "#ffffff"
        assert diagrams.SYSML_STYLE[" .sysml-edge-specializes > .elkarrow"]["fill"] == "#ffffff"
        # the filled colon dots draw with currentColor, bound to the stroke
        assert diagrams.SYSML_STYLE[" .sysml-edge-typed > .elkarrow"]["color"] == "#6a9a48"

    def test_redefinition_and_subsetting_edges(self):
        """Spec notation for the rest of the Specialization family (errata
        E3-E5): the SAME solid line and hollow triangle as subclassification,
        distinguished ONLY by the shaft adornment -- a perpendicular bar
        tick for redefinition, nothing for subsetting, double colon dots
        for reference subsetting; no keyword labels."""

        model = longeron.loads("""
            package Q {
                part def V { part engine; }
                part car : V { part engine :>> engine; }
                part vehicle;
                part truck :> vehicle;
                part pool;
                part spare ::> pool;
            }
        """)
        widget = diagrams.structure_diagram(model)
        found = {}
        for e in widget.source.value.edges:
            css = e.properties.cssClasses
            for kind in ("redefines", "subsets", "references"):
                if f"sysml-edge-{kind}" in css:
                    assert not e.labels  # NO «keyword» labels (spec p.200)
                    found[kind] = (e.source.id, e.target.id, e.properties.shape.end)
        assert found["redefines"] == (
            "Q::car::engine",
            "Q::V::engine",  # the shadowed inherited feature, not a self-loop
            "generalization-tick",
        )
        assert found["subsets"] == (
            "Q::truck",
            "Q::vehicle",
            "generalization",  # identical head to subclassification
        )
        assert found["references"] == (
            "Q::spare",
            "Q::pool",
            "generalization-dcolon",
        )

    def test_membership_edges_carry_diamonds_and_multiplicities(self):
        """Definition-level membership edges (errata E6/E7): filled diamond
        at the whole end for composite members, hollow for referential
        (``ref``) members; role name on the line, multiplicity at the part
        end.  Members whose type is drawn INSIDE the whole stay nesting-only."""

        model = longeron.loads("""
            package P {
                part def Wheel;
                part def Driver;
                part def Car {
                    part wheels : Wheel [4];
                    ref part driver : Driver;
                    part def Trunk;
                    part trunk : Trunk;
                }
            }
        """)
        widget = diagrams.structure_diagram(model)
        members = {}
        for e in widget.source.value.edges:
            css = e.properties.cssClasses
            if "sysml-edge-member" in css or "sysml-edge-refmember" in css:
                members[(e.source.id, e.target.id)] = e
        composite = members[("P::Car", "P::Wheel")]
        assert composite.properties.shape.start == "composition"
        assert composite.properties.shape.end is None
        texts = [label.text for label in composite.labels]
        assert "wheels" in texts  # role name rides the line
        mult = next(label for label in composite.labels if label.text == "[4]")
        assert mult.layoutOptions["elk.edgeLabels.placement"] == "HEAD"
        assert "sysml-attribute" in mult.properties.cssClasses
        referential = members[("P::Car", "P::Driver")]
        assert referential.properties.shape.start == "aggregation"
        # trunk : Trunk is drawn nested inside Car -- nesting already shows
        # the membership, so no diamond edge duplicates it
        assert ("P::Car", "P::Car::Trunk") not in members
        # the browser stylesheet binds the filled diamond to the stroke and
        # flips both on selection; the hollow diamond stays white
        assert diagrams.SYSML_STYLE[" .sysml-edge-member > .elkarrow"]["fill"] == "#555555"
        assert (
            diagrams.SYSML_STYLE[" .elkedge.sysml-edge-member.selected > .elkarrow"]["fill"]
            == "var(--jp-elk-color-selected)"
        )
        assert diagrams.SYSML_STYLE[" .sysml-edge-refmember > .elkarrow"]["fill"] == "#ffffff"
        assert " .elkedge.sysml-edge-refmember.selected > .elkarrow" not in diagrams.SYSML_STYLE

    def test_membership_edges_can_be_disabled(self):
        model = longeron.loads("""
            package P {
                part def Wheel;
                part def Car { part wheels : Wheel [4]; }
            }
        """)
        widget = diagrams.structure_diagram(model, composition="none")
        assert not any(
            "sysml-edge-member" in e.properties.cssClasses for e in widget.source.value.edges
        )

    def test_connector_end_multiplicities_label_the_ends(self):
        model = longeron.loads("""
            package P {
                part def S {
                    part a;
                    part b;
                    connect [1] a to [0..2] b;
                }
            }
        """)
        widget = diagrams.structure_diagram(model)
        connect = next(
            e for e in widget.source.value.edges if "sysml-edge-connect" in e.properties.cssClasses
        )
        placements = {
            label.text: label.layoutOptions["elk.edgeLabels.placement"] for label in connect.labels
        }
        assert placements == {"[1]": "TAIL", "[0..2]": "HEAD"}

    def test_connection_edges(self):
        model = longeron.loads("""
            package P {
                part sys {
                    part a;
                    part b;
                    connect a to b;
                }
            }
        """)
        widget = diagrams.structure_diagram(model)
        assert any(
            "sysml-edge-connect" in e.properties.cssClasses for e in widget.source.value.edges
        )

    def test_flow_edges_carry_pin_symbols(self):
        """Flow connections (errata E16): border pin at BOTH ends -- the
        square source-output pin and the square-plus-filled-arrowhead
        target-input pin -- with payload item labels near each end."""

        model = longeron.loads("""
            package P {
                item def Item1;
                action def A { in x : Item1; out y : Item1; }
                action a1 : A;
                action a2 : A;
                flow of Item1 from a1.y to a2.x;
            }
        """)
        widget = diagrams.structure_diagram(model)
        flow = next(
            e for e in widget.source.value.edges if "sysml-edge-flow" in e.properties.cssClasses
        )
        assert flow.properties.shape.start == "flow-source-pin"
        assert flow.properties.shape.end == "flow-target-pin"
        assert (flow.source.id, flow.target.id) == ("P::a1", "P::a2")
        placements = {
            label.layoutOptions["elk.edgeLabels.placement"]
            for label in flow.labels
            if label.text == "Item1"
        }
        assert placements == {"TAIL", "HEAD"}  # payload labels at both ends
        # both pin symbols are registered, self-painted (white body +
        # currentColor), and the stylesheet binds currentColor to the stroke
        library = widget.symbols.library
        for identifier in ("flow-source-pin", "flow-target-pin"):
            assert 'fill="#ffffff"' in library[identifier].element.properties.shape.use
        assert "currentColor" in library["flow-target-pin"].element.properties.shape.use
        assert diagrams.SYSML_STYLE[" .sysml-edge-flow > .elkarrow"]["color"] == "#555555"

    def test_binding_edge_rides_the_equals_glyph(self):
        model = longeron.loads("package P { part a; part b; binding bind a = b; }")
        widget = diagrams.structure_diagram(model)
        binding = next(
            e for e in widget.source.value.edges if "sysml-edge-binding" in e.properties.cssClasses
        )
        assert [label.text for label in binding.labels] == ["="]
        assert binding.properties.shape is None  # no endpoint glyphs

    def test_named_satisfy_draws_reference_subsetting_to_the_requirement(self):
        model = longeron.loads("""
            package Reqs { requirement requirement1; }
            package Sys {
                part part1 {
                    satisfy requirement requirement2 references Reqs::requirement1;
                }
            }
        """)
        widget = diagrams.structure_diagram(model)
        node = next(n for n in _walk(widget.source.value) if n.id == "Sys::part1::requirement2")
        assert node.labels[0].text == "\u00absatisfy requirement\u00bb"
        edge = next(
            e
            for e in widget.source.value.edges
            if "sysml-edge-references" in e.properties.cssClasses
        )
        assert (edge.source.id, edge.target.id) == (
            "Sys::part1::requirement2",
            "Reqs::requirement1",
        )
        assert edge.properties.shape.end == "generalization-dcolon"

    def test_anonymous_satisfy_draws_keyword_edge(self):
        model = longeron.loads("""
            package P {
                requirement requirement1;
                part sys;
                satisfy requirement1 by sys;
            }
        """)
        widget = diagrams.structure_diagram(model)
        edge = next(
            e
            for e in widget.source.value.edges
            if "sysml-edge-satisfies" in e.properties.cssClasses
        )
        assert (edge.source.id, edge.target.id) == ("P::sys", "P::requirement1")
        label = edge.labels[0]
        assert label.text == "\u00absatisfy\u00bb"
        assert "sysml-stereotype" in label.properties.cssClasses  # keyword typography

    def test_nary_dependency_junction(self):
        model = longeron.loads("""
            package P {
                part a;
                part b;
                part s;
                dependency Multi from a, b to s;
            }
        """)
        widget = diagrams.structure_diagram(model)
        root = widget.source.value
        junction = next(
            n for n in _walk(root) if "sysml-junction" in (n.properties.cssClasses or "")
        )
        assert junction.labels[0].text == "(Multi)"
        kinds = [
            (e.source.id, e.target.id, e.properties.cssClasses)
            for e in root.edges
            if "sysml-edge-dep" in e.properties.cssClasses
        ]
        client_edges = [k for k in kinds if "depclient" in k[2]]
        supplier_edges = [k for k in kinds if "sysml-edge-dependency" in k[2]]
        assert len(client_edges) == 2 and len(supplier_edges) == 1
        # selection contract: the junction is a FILLED glyph (fill follows
        # the stroke on selection) with a pinned stroke width
        selected = diagrams.SYSML_STYLE[" .sysml-junction > .elknode.selected"]
        assert selected == {
            "fill": "var(--jp-elk-color-selected)",
            "stroke": "var(--jp-elk-color-selected)",
        }
        assert diagrams.SYSML_STYLE[" .sysml-junction > .elknode"] == {"stroke-width": "1.2"}

    def test_alias_edge_carries_the_hollow_circle(self):
        model = longeron.loads("""
            package Lib { part def Target; }
            package App { alias T for Lib::Target; }
        """)
        widget = diagrams.structure_diagram(model)
        alias = next(
            e for e in widget.source.value.edges if "sysml-edge-alias" in e.properties.cssClasses
        )
        assert (alias.source.id, alias.target.id) == ("App", "Lib::Target")
        assert alias.properties.shape.start == "alias-circle"
        assert alias.labels[0].text == "T"
        # hollow forever: the alias circle stays white even selected
        assert diagrams.SYSML_STYLE[" .sysml-edge-alias > .elkarrow"]["fill"] == "#ffffff"

    def test_portion_membership_edge(self):
        model = longeron.loads("""
            package P {
                individual part def Rover;
                timeslice t1 : Rover;
            }
        """)
        widget = diagrams.structure_diagram(model)
        edges = [
            e for e in widget.source.value.edges if "sysml-edge-portion" in e.properties.cssClasses
        ]
        assert [(e.source.id, e.target.id) for e in edges] == [("P::t1", "P::Rover")]
        assert edges[0].properties.shape.end == "portion-ball"
        # the portion edge REPLACES the plain typing edge
        assert not any(
            "sysml-edge-typed" in e.properties.cssClasses for e in widget.source.value.edges
        )
        # keywords ride the boxes (errata N15)
        t1 = next(n for n in _walk(widget.source.value) if n.id == "P::t1")
        assert t1.labels[0].text == "\u00abtimeslice\u00bb"
        rover = next(n for n in _walk(widget.source.value) if n.id == "P::Rover")
        assert rover.labels[0].text == "\u00abindividual part def\u00bb"

    def test_actor_and_stakeholder_boxes(self):
        model = longeron.loads("""
            package P {
                part def Person;
                use case def Deliver {
                    actor driver : Person;
                }
            }
        """)
        widget = diagrams.structure_diagram(model)
        driver = next(n for n in _walk(widget.source.value) if n.id == "P::Deliver::driver")
        assert driver.labels[0].text == "\u00abactor\u00bb"
        assert "sysml-usage" in driver.properties.cssClasses

    def test_relationships_can_be_disabled(self, drone_model):
        widget = diagrams.structure_diagram(drone_model, show_relationships=False)
        edges = widget.source.value.edges
        # only layout-only packing edges remain -- no relationship edges
        assert all("sysml-packing" in e.properties.cssClasses for e in edges)
        assert not any("sysml-edge" in e.properties.cssClasses for e in edges)

    def test_disconnected_members_get_packing_edges(self, drone_model):
        # V1: members that touch no edge are chained into rows; the chains
        # are layout-only (unlabeled, css 'sysml-packing', hidden by style)
        # and attached to the container whose sub-layout packs them
        widget = diagrams.structure_diagram(drone_model)

        def all_edges(node):
            yield from node.edges
            for child in node.children:
                yield from all_edges(child)

        packing = [
            e for e in all_edges(widget.source.value) if "sysml-packing" in e.properties.cssClasses
        ]
        assert packing
        assert all(not e.labels for e in packing)
        assert " .sysml-packing > path" in diagrams.SYSML_STYLE

    def test_connected_members_are_never_chained(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        root = widget.source.value
        connected = set()
        for e in root.edges:
            if "sysml-packing" not in e.properties.cssClasses:
                connected.add(id(e.source))
                connected.add(id(e.target))
        for e in root.edges:
            if "sysml-packing" in e.properties.cssClasses:
                assert id(e.source) not in connected
                assert id(e.target) not in connected


class TestStates:
    def test_builds_with_marker_and_transitions(self, drone_model):
        machine = drone_model.find("Drone::FlightStates")
        widget = diagrams.state_diagram(machine)
        root = widget.source.value
        state_ids = {n.id for n in _walk(root) if n.id}
        assert "Drone::FlightStates::idle" in state_ids
        markers = [n for n in _walk(root) if "sysml-marker" in n.properties.cssClasses]
        assert len(markers) == 1  # the entry marker
        assert len(root.edges) == 6  # entry + 5 transitions

    def test_transition_labels(self, drone_model):
        machine = drone_model.find("Drone::FlightStates")
        widget = diagrams.state_diagram(machine)
        texts = [label.text for e in widget.source.value.edges for label in e.labels]
        assert "launch" in texts
        assert 'low_battery / send "RTL"' in texts  # real effect, not '\u2026'

    def test_nested_states(self):
        model = longeron.loads("""
            package P {
                state def M {
                    entry; then outer;
                    state outer {
                        entry; then inner;
                        state inner;
                    }
                }
            }
        """)
        widget = diagrams.state_diagram(model.find("P::M"))
        outer = next(n for n in _walk(widget.source.value) if n.id == "P::M::outer")
        assert any(n.id == "P::M::outer::inner" for n in _walk(outer))

    def test_typed_submachine_expands(self):
        model = longeron.loads(_TYPED_SUBMACHINE)
        widget = diagrams.state_diagram(model.find("P::Outer"))
        root = widget.source.value
        x = next(n for n in _walk(root) if n.id == "P::Outer::x")
        ids = {n.id for n in _walk(x) if n.id}
        # instance-qualified ids: unique per expansion site, and exactly the
        # keys longeron.replay records (never the shared definition's)
        assert {"P::Outer::x::a", "P::Outer::x::b"} <= ids
        # the definition's entry marker and transitions are drawn too
        assert any("sysml-marker" in (n.properties.cssClasses or "") for n in _walk(x))
        pairs = {(e.source.id, e.target.id) for e in root.edges}
        assert ("P::Outer::x::a", "P::Outer::x::b") in pairs
        # the typed state names its definition, SysML usage style
        assert any(label.text == "x : Inner" for label in x.labels)

    def test_typed_submachine_depth_zero_is_collapsed(self):
        model = longeron.loads(_TYPED_SUBMACHINE)
        widget = diagrams.state_diagram(model.find("P::Outer"), submachine_depth=0)
        x = next(n for n in _walk(widget.source.value) if n.id == "P::Outer::x")
        assert not x.children  # the pre-expansion behavior

    def test_sibling_typed_usages_expand_independently(self):
        model = longeron.loads("""
            package P {
                state def Inner { entry; then a; state a; }
                state def Outer {
                    entry; then left;
                    state left { entry; then x; state x : Inner; }
                    state right { entry; then x; state x : Inner; }
                    transition first left accept go then right;
                }
            }
        """)
        widget = diagrams.state_diagram(model.find("P::Outer"))
        ids = [n.id for n in _walk(widget.source.value) if n.id]
        assert "P::Outer::left::x::a" in ids
        assert "P::Outer::right::x::a" in ids
        assert len(ids) == len(set(ids))  # instance ids stay unique

    def test_typed_submachine_cycles_collapse(self):
        """A definition reached again through its own submachine must not
        recurse forever: the repeated level draws as a collapsed leaf."""

        model = longeron.loads("""
            package P {
                state def A { entry; then s; state s : B; }
                state def B { entry; then t; state t : A; }
            }
        """)
        widget = diagrams.state_diagram(model.find("P::A"))  # must terminate
        t = next(n for n in _walk(widget.source.value) if n.id == "P::A::s::t")
        assert not t.children

    def test_dispatcher_forwards_submachine_depth(self):
        model = longeron.loads(_TYPED_SUBMACHINE)
        widget = diagrams.diagram(model.find("P::Outer::x"), submachine_depth=0)
        assert type(widget).__name__ == "Diagram"


class TestActions:
    def test_succession_graph(self):
        model = longeron.loads("""
            package P {
                action def Pipeline {
                    action a { assign x := 1; }
                    action b { assign x := 2; }
                    first start then a;
                    first a if x > 0 then b;
                    first b then done;
                }
            }
        """)
        widget = diagrams.action_diagram(model.find("P::Pipeline"))
        root = widget.source.value
        markers = [n for n in _walk(root) if "sysml-marker" in n.properties.cssClasses]
        assert len(markers) == 1  # start (done is a bullseye glyph now)
        finals = [n for n in _walk(root) if "sysml-final" in n.properties.cssClasses]
        assert len(finals) == 1  # done = bullseye (spec errata N6)
        guarded = [e for e in root.edges if "sysml-edge-guarded" in e.properties.cssClasses]
        assert len(guarded) == 1
        assert guarded[0].labels[0].text == "[x > 0]"

    def test_declaration_order_chain(self, drone_model):
        widget = diagrams.action_diagram(drone_model.find("Drone::PlanBattery"))
        root = widget.source.value
        steps = [n for n in _walk(root) if "sysml-step" in n.properties.cssClasses]
        assert len(steps) == 2  # assign + if
        assert len(root.edges) == len(steps) + 1  # chain through start/done

    def test_control_nodes_use_spec_glyphs(self):
        """Spec errata N7/N8: fork/join draw as thick filled bars, decision/
        merge as empty rhombi -- identical within each pair, role by
        topology -- not as «keyword» step boxes."""

        model = longeron.loads("""
            package P {
                action def Flow {
                    action a;
                    action b;
                    fork f;
                    join j;
                    decide d;
                    merge g;
                    first start then f;
                    first f then a;
                    first f then b;
                    first a then j;
                    first b then j;
                    first j then d;
                    first d if x > 0 then g;
                    first d then g;
                    first g then done;
                }
            }
        """)
        widget = diagrams.action_diagram(model.find("P::Flow"))
        root = widget.source.value
        by_id = {n.id: n for n in _walk(root) if n.id}
        for name in ("P::Flow::f", "P::Flow::j"):
            node = by_id[name]
            assert "sysml-ctrl-bar" in node.properties.cssClasses
            assert (node.width, node.height) == (6, 40)  # bar, not a box
            assert "sysml-step" not in node.properties.cssClasses
        for name in ("P::Flow::d", "P::Flow::g"):
            node = by_id[name]
            assert "sysml-ctrl-diamond" in node.properties.cssClasses
            assert type(node.properties.shape).__name__ == "Diamond"
        # glyph labels hang OUTSIDE, below the glyph
        f_label = by_id["P::Flow::f"].labels[0]
        assert f_label.text == "f"
        assert "OUTSIDE" in f_label.layoutOptions["nodeLabels.placement"]

    def test_accept_and_send_actions_get_badged_boxes(self):
        """Spec errata N9/N10: accept/send are STANDARD rounded action boxes
        with a small filled top-left badge (notched banner for accept,
        pointed tag for send) -- not whole-node pentagons."""

        model = longeron.loads("""
            package P {
                item def Go;
                action def Chat {
                    action rx accept go : Go;
                    action tx send new Go() via ch;
                    first start then rx;
                    first rx then tx;
                    first tx then done;
                }
            }
        """)
        widget = diagrams.action_diagram(model.find("P::Chat"))
        by_id = {n.id: n for n in _walk(widget.source.value) if n.id}
        for name, form in (("P::Chat::rx", "accept"), ("P::Chat::tx", "send")):
            node = by_id[name]
            assert f"sysml-step-{form}" in node.properties.cssClasses
            assert "sysml-step" in node.properties.cssClasses  # standard box
            badge = node.labels[0]
            assert f"sysml-badge-{form}" in badge.properties.cssClasses
            shape = badge.properties.shape
            assert type(shape).__name__ == "Icon" and shape.use == f"{form}-badge"
            assert badge.layoutOptions["nodeLabels.placement"] == "H_LEFT V_TOP INSIDE"
            stereotype = node.labels[1]
            assert stereotype.text == f"\u00ab{form}\u00bb"
        # both badge symbols are registered and filled via the stylesheet
        assert "accept-badge" in widget.symbols.library
        assert "send-badge" in widget.symbols.library
        assert diagrams.SYSML_STYLE[" .accept-badge"]["fill"] == "#333333"

    def test_terminate_renders_as_circle_x(self):
        model = longeron.loads("""
            package P {
                action def Abort {
                    action warn { assign x := 1; }
                    terminate;
                }
            }
        """)
        widget = diagrams.action_diagram(model.find("P::Abort"))
        terminates = [
            n
            for n in _walk(widget.source.value)
            if "sysml-terminate" in (n.properties.cssClasses or "")
        ]
        assert len(terminates) == 1
        assert terminates[0].labels[0].text == "terminate"
        shape = terminates[0].properties.shape
        assert type(shape).__name__ == "SVG"
        assert "glyph-x" in shape.use  # the inscribed X

    def test_successions_render_dashed(self):
        """Spec errata E12: action-flow successions are DASHED with open-V
        arrows; state-view transitions stay solid."""

        from longeron import render

        assert render._EDGE_STYLES["sysml-edge-succession"]["stroke-dasharray"] == "4 2"
        assert "stroke-dasharray" not in render._EDGE_STYLES["sysml-edge-transition"]
        assert render._EDGE_ENDS["sysml-edge-succession"] == "open"

    def test_control_glyphs_get_convergence_anchor_ports(self):
        """Item 10: decision/merge/terminate/start/done glyphs carry two
        invisible fixed-side ports (west in, east out) so ELK joins every
        fan at a single point; fork/join bars stay port-free (edges
        distribute along the bar, their semantic)."""

        model = longeron.loads("""
            package P {
                action def Flow {
                    action a;
                    fork f;
                    decide d;
                    first start then f;
                    first f then d;
                    first d then a;
                    first a then done;
                }
            }
        """)
        widget = diagrams.action_diagram(model.find("P::Flow"))
        root = widget.source.value
        by_css = {}
        for node in _walk(root):
            for fragment in (node.properties.cssClasses or "").split():
                by_css.setdefault(fragment, node)
        for css in ("sysml-ctrl-diamond", "sysml-marker", "sysml-final"):
            node = by_css[css]
            sides = [port.layoutOptions["elk.port.side"] for port in node.ports]
            assert sides == ["WEST", "EAST"], css
            assert all((port.width, port.height) == (0, 0) for port in node.ports)
            assert node.layoutOptions["elk.portConstraints"] == "FIXED_SIDE"
            assert node.layoutOptions["elk.portAlignment.default"] == "CENTER"
        assert by_css["sysml-ctrl-bar"].ports == []  # bars distribute
        # edges into/out of anchored glyphs reference the PORTS
        diamond = by_css["sysml-ctrl-diamond"]
        into = [e for e in root.edges if getattr(e.target, "get_parent", None) is not None]
        assert any(e.target in diamond.ports for e in root.edges)
        assert any(e.source in diamond.ports for e in root.edges)
        assert into  # port-anchored edges exist

    def test_swimlanes_default_off_and_explicit_mapping(self):
        """lanes= partitions steps into dashed «performer» containers; an
        explicit mapping wins over derivation; default draws no lanes."""

        model = longeron.loads("""
            package P {
                action def Pipeline {
                    action a { assign x := 1; }
                    action b { assign x := 2; }
                    first start then a;
                    first a then b;
                    first b then done;
                }
            }
        """)
        pipeline = model.find("P::Pipeline")
        plain = diagrams.action_diagram(pipeline)
        assert not any(
            "sysml-lane" in (n.properties.cssClasses or "") for n in _walk(plain.source.value)
        )
        widget = diagrams.action_diagram(pipeline, lanes={"robot": ["a", "b"]})
        root = widget.source.value
        lanes = [n for n in _walk(root) if "sysml-lane" in (n.properties.cssClasses or "")]
        assert len(lanes) == 1
        lane = lanes[0]
        assert [label.text for label in lane.labels] == ["\u00abperformer\u00bb", "robot"]
        assert {child.id for child in lane.children} == {"P::Pipeline::a", "P::Pipeline::b"}
        # lanes order left-to-right by ELK layer partitioning
        assert root.layoutOptions["elk.partitioning.activate"] == "true"
        assert lane.layoutOptions["elk.partitioning.partition"] == "1"
        start = next(n for n in _walk(root) if "sysml-marker" in (n.properties.cssClasses or ""))
        done = next(n for n in _walk(root) if "sysml-final" in (n.properties.cssClasses or ""))
        assert start.layoutOptions["elk.partitioning.partition"] == "0"
        assert done.layoutOptions["elk.partitioning.partition"] == "2"
        # the lane boundary is dashed and its stroke width pinned
        assert diagrams.SYSML_STYLE[" .sysml-lane > rect"]["stroke-dasharray"] == "4 3"
        assert diagrams.SYSML_STYLE[" .sysml-lane > .elknode"] == {"stroke-width": "1.2"}


class TestDispatcherAndSelection:
    def test_dispatch(self, drone_model):
        state = diagrams.diagram(drone_model.find("Drone::FlightStates"))
        action = diagrams.diagram(drone_model.find("Drone::PlanBattery"))
        structure = diagrams.diagram(drone_model)
        assert all(type(w).__name__ == "Diagram" for w in (state, action, structure))

    def test_on_select_resolves_elements(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        received: list = []
        diagrams.on_select(widget, drone_model, received.extend)
        widget.view.selection.ids = ["Drone::QuadCopter"]
        assert [e.qualified_name for e in received] == ["Drone::QuadCopter"]
        assert isinstance(received[0], M.Definition)


def test_headless_schedule_run_is_safe():
    """The vendored ipyelk patch: no 'no running event loop' crashes."""

    from ipyelk.elements import Label, Node

    root = Node(children=[Node(labels=[Label(text="x")])])
    import ipyelk

    widget = ipyelk.from_element(root)  # would raise RuntimeError unpatched
    assert widget.source.value is not None
