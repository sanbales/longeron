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
        """SysML v2 notation: subclassification and feature typing point at
        the general/type with a hollow triangle -- the closed symbol plus a
        white fill in the stylesheet; everything else keeps the open V."""

        widget = diagrams.structure_diagram(drone_model)
        typed = [
            e for e in widget.source.value.edges if "sysml-edge-typed" in e.properties.cssClasses
        ]
        assert typed
        assert all(e.properties.shape.end == "generalization" for e in typed)
        assert diagrams.SYSML_STYLE[" .sysml-edge-typed > .elkarrow"]["fill"] == "#ffffff"
        assert diagrams.SYSML_STYLE[" .sysml-edge-specializes > .elkarrow"]["fill"] == "#ffffff"

    def test_redefinition_and_subsetting_edges(self):
        """KerML notation for the other Specialization kinds: an open arrow
        to the general feature, labeled with the relationship keyword."""

        model = longeron.loads("""
            package Q {
                part def V { part engine; }
                part car : V { part engine :>> engine; }
                part vehicle;
                part truck :> vehicle;
            }
        """)
        widget = diagrams.structure_diagram(model)
        found = {}
        for e in widget.source.value.edges:
            css = e.properties.cssClasses
            if "sysml-edge-redefines" in css or "sysml-edge-subsets" in css:
                assert e.properties.shape.end == "arrow"  # open V, not a triangle
                found[css.split()[-1]] = (e.source.id, e.target.id, e.labels[0].text)
        assert found["sysml-edge-redefines"] == (
            "Q::car::engine",
            "Q::V::engine",  # the shadowed inherited feature, not a self-loop
            "\u00abredefines\u00bb",
        )
        assert found["sysml-edge-subsets"] == (
            "Q::truck",
            "Q::vehicle",
            "\u00absubsets\u00bb",
        )

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
        assert len(markers) == 2  # start + done
        guarded = [e for e in root.edges if "sysml-edge-guarded" in e.properties.cssClasses]
        assert len(guarded) == 1
        assert guarded[0].labels[0].text == "[x > 0]"

    def test_declaration_order_chain(self, drone_model):
        widget = diagrams.action_diagram(drone_model.find("Drone::PlanBattery"))
        root = widget.source.value
        steps = [n for n in _walk(root) if "sysml-step" in n.properties.cssClasses]
        assert len(steps) == 2  # assign + if
        assert len(root.edges) == len(steps) + 1  # chain through start/done


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
