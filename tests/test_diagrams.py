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


def _assert_adornment_contract(widget):
    """Walk EVERYTHING a built widget emits and assert the node-adornment
    contract (see TestAdornmentContract): every node-attached ICON label
    and every drawn port carries the ``sysml-adornment`` marker, icon
    kinds are registered in diagrams._ADORNMENTS, and hollow-family
    symbols bind the shared stroke-width bridge.  Returns the set of
    ``(kind, flavor)`` pairs discovered, so callers can assert coverage."""

    found = set()
    for node in _walk(widget.source.value):
        for label in node.labels or []:
            shape = label.properties.shape
            if type(shape).__name__ != "Icon":
                continue  # text labels are not adornments
            css = label.properties.cssClasses or ""
            assert "sysml-adornment" in css, (
                f"icon label {shape.use!r} on {node.id!r} skipped _adornment_label"
            )
            assert shape.use in diagrams._ADORNMENTS, (
                f"icon adornment {shape.use!r} is not registered in diagrams._ADORNMENTS"
            )
            found.add((shape.use, "label"))
        for port in getattr(node, "ports", None) or []:
            css = port.properties.cssClasses or ""
            if not css:
                continue  # invisible convergence anchors never draw
            assert "sysml-adornment" in css, (
                f"drawn port {port.id!r} on {node.id!r} skipped _adornment_port"
            )
            kind = "sysml-port-proxy" if "sysml-port-proxy" in css else "sysml-port"
            found.add((kind, "port"))
    return found


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load("examples/deepscout")


class TestStructure:
    def test_builds(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        assert type(widget).__name__ == "Diagram"

    def test_node_ids_are_qualified_names(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        ids = {n.id for n in _walk(widget.source.value) if n.id}
        assert {"Rotorcraft", "Rotorcraft::QuadCopter", "ScoutParts::F450Kit::Battery"} <= ids

    def test_attribute_compartments(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        battery = next(
            n for n in _walk(widget.source.value) if n.id == "ScoutParts::F450Kit::Battery"
        )
        texts = [label.text for label in battery.labels]
        assert any("capacity : Real = 5200.0" in t for t in texts)

    def test_attribute_rows_pre_sized_to_shared_width(self, drone_model):
        """Regression (V2): attribute rows are pre-sized to the node's widest
        label so ELK's centered boxes share one left edge (left-aligned
        compartments); title/stereotype labels stay snug and centered."""

        from longeron.render import _measure

        widget = diagrams.structure_diagram(drone_model)
        battery = next(
            n for n in _walk(widget.source.value) if n.id == "ScoutParts::F450Kit::Battery"
        )
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
        motors = next(
            n for n in _walk(widget.source.value) if n.id == "Rotorcraft::QuadCopter::motors"
        )
        assert any("motors : Motor [4]" in label.text for label in motors.labels)

    def test_parameter_rows(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        hover = next(n for n in _walk(widget.source.value) if n.id == "DeepScout::HoverTime")
        texts = [label.text for label in hover.labels]
        assert "in capacity : Real" in texts
        assert "return : Real" in texts

    def test_requirement_and_constraint_rows(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        envelope = next(
            n for n in _walk(widget.source.value) if n.id == "DeepScout::FlightEnvelope"
        )
        texts = " | ".join(label.text for label in envelope.labels)
        assert "subject drone : MultiRotor" in texts
        assert "require hoverMargin" in texts
        # the installation requirement's subject is the abstract base:
        # any configuration can be measured (the quad is the satisfy
        # anchor, over in the Rotorcraft branch)
        install = next(n for n in _walk(widget.source.value) if n.id == "DeepScout::installation")
        install_texts = " | ".join(label.text for label in install.labels)
        assert "subject drone : MultiRotor" in install_texts
        # the shared constraints render on the abstract base
        base = next(n for n in _walk(widget.source.value) if n.id == "DeepScout::MultiRotor")
        base_texts = " | ".join(label.text for label in base.labels)
        assert "assert takeoffMassLimit" in base_texts

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

    def test_junction_spokes_anchor_at_the_dot_center(self):
        """Junction dots get the control-node convergence treatment (t2
        item 10), pulled to the CENTER: two invisible fixed-side ports
        whose elk.port.anchor offsets move both attachment points to the
        glyph's midpoint, so every spoke -- client or supplier -- visually
        radiates from the dot (spec printed pp.19, 66).  Border attachment
        scattered the lines across the dot's boundary."""

        from longeron.render import _JUNCTION_SIZE

        model = longeron.loads("""
            package P {
                part a;
                part b;
                part s;
                dependency Multi from a, b to s;
            }
        """)
        root = diagrams.structure_diagram(model).source.value
        junction = next(
            n for n in _walk(root) if "sysml-junction" in (n.properties.cssClasses or "")
        )
        assert junction.layoutOptions["elk.portConstraints"] == "FIXED_SIDE"
        half = _JUNCTION_SIZE / 2
        anchors = {p.properties.key: p for p in junction.ports}
        assert anchors["in"].layoutOptions == {
            "elk.port.side": "WEST",
            "elk.port.anchor": f"({half:g},0)",
        }
        assert anchors["out"].layoutOptions == {
            "elk.port.side": "EAST",
            "elk.port.anchor": f"({-half:g},0)",
        }
        # clients converge on the in anchor, suppliers fan out of the out
        for edge in root.edges:
            if "sysml-edge-depclient" in edge.properties.cssClasses:
                assert edge.target is anchors["in"]
            elif "sysml-edge-dependency" in edge.properties.cssClasses:
                assert edge.source is anchors["out"]

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

    def test_membership_edges_unnest_package_members(self):
        """membership="edges" (errata E18, spec printed p.26): packages do
        not swallow their drawn members -- members become SIBLING nodes at
        the diagram root (never ELK ancestor<->descendant edges) joined by
        a solid unlabeled edge with the circle-plus at the OWNING end."""

        model = longeron.loads("""
            package Package0 { package Package1 { part def X; } }
        """)
        widget = diagrams.structure_diagram(model, membership="edges")
        root = widget.source.value
        # recursively flattened: every package and member is a root sibling
        assert {n.id for n in root.children} == {
            "Package0",
            "Package0::Package1",
            "Package0::Package1::X",
        }
        assert all(not n.children for n in root.children)
        owned = [e for e in root.edges if "sysml-edge-owned" in e.properties.cssClasses]
        assert {(e.source.id, e.target.id) for e in owned} == {
            ("Package0", "Package0::Package1"),
            ("Package0::Package1", "Package0::Package1::X"),
        }
        for edge in owned:
            assert edge.properties.shape.start == "owned-circle-plus"
            assert edge.properties.shape.end is None  # no head at the member
            assert not edge.labels  # the spec draws the edge unlabeled

    def test_membership_edges_draw_without_relationships(self):
        """Membership edges are containment presentation (they replace
        nesting), not relationship edges: show_relationships=False keeps
        them; membership defaults to "nested" (no owned edges) and other
        values are rejected."""

        model = longeron.loads("package Package0 { package Package1; }")
        widget = diagrams.structure_diagram(model, membership="edges", show_relationships=False)
        kinds = [e.properties.cssClasses for e in widget.source.value.edges]
        assert any("sysml-edge-owned" in k for k in kinds)
        nested = diagrams.structure_diagram(model)
        assert not any(
            "sysml-edge-owned" in e.properties.cssClasses for e in nested.source.value.edges
        )
        with pytest.raises(ValueError, match="membership"):
            diagrams.structure_diagram(model, membership="flat")

    def test_owned_membership_circle_plus_is_a_true_circled_plus(self):
        """The owning-end glyph is a TRUE circled plus (spec p.26 crop):
        both cross strokes span the FULL diameter, so every stroke endpoint
        sits exactly ON the circle -- never a floating '+' inside it.
        Selection contract: hollow family -- explicit white body, circle
        outline and cross strokes in currentColor (bound to the edge
        stroke, so selection recolors both, never the fill)."""

        import math

        from longeron.render import _CIRCLE_RADIUS as r

        use = diagrams._symbols().library["owned-circle-plus"].element.properties.shape.use
        assert f'<circle cx="{r:g}" cy="0" r="{r:g}" fill="#ffffff"' in use
        assert f'd="M 0,0 L {2 * r:g},0 M {r:g},{-r:g} L {r:g},{r:g}"' in use
        # prove it: each cross-stroke endpoint is exactly r from the center
        center = (r, 0.0)
        for x, y in ((0, 0), (2 * r, 0), (r, -r), (r, r)):
            assert math.hypot(x - center[0], y - center[1]) == pytest.approx(r)
        assert use.count('stroke="currentColor"') == 2  # circle + cross
        style = diagrams.SYSML_STYLE[" .sysml-edge-owned > .elkarrow"]
        assert style["fill"] == "#ffffff"  # hollow forever, even selected
        assert style["stroke"] == "#555555" and style["color"] == "#555555"

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

    def test_actor_default_is_the_stick_figure(self):
        """Actor usages draw the spec's stick figure by DEFAULT (BNF
        printed p.244; crop gt-actor.png): a fixed-size SVG-shape node in
        the usage palette, name below the figure, «actor» stereotype
        omitted -- the figure IS the stereotype.  Geometry single-sourced
        with the headless renderer via render._actor_geometry."""

        from longeron import render

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
        assert driver.properties.cssClasses == "sysml-actor"
        assert (driver.width, driver.height) == (render._ACTOR_WIDTH, render._ACTOR_HEIGHT)
        use = driver.properties.shape.use
        cx, cy, _r, limbs = render._actor_geometry()
        assert f'<circle class="glyph-actor glyph-actor-head" cx="{cx:g}" cy="{cy:g}"' in use
        assert f'd="{limbs}"' in use
        # ONE label: the name below the figure (no «actor» row)
        assert [label.text for label in driver.labels] == ["driver : Person"]
        label = driver.labels[0]
        assert not label.properties.cssClasses  # title typography, not stereotype
        assert label.layoutOptions["nodeLabels.placement"] == "OUTSIDE H_CENTER V_BOTTOM"
        # the figure joins the box selection/hover contract: state rules
        # bind the SAME theme variables as the rects
        assert diagrams.SYSML_STYLE[" .sysml-actor .glyph-actor"]["stroke-width"] == (
            "var(--jp-elk-stroke-width)"
        )
        for state, width in (
            ("selected", "var(--jp-elk-stroke-width-selected)"),
            ("mouseover", "var(--jp-elk-stroke-width-hover)"),
            ("selected.mouseover", "var(--jp-elk-stroke-width-hover)"),
        ):
            rule = diagrams.SYSML_STYLE[f" .sysml-actor > .elknode.{state} .glyph-actor"]
            assert rule["stroke-width"] == width

    def test_actor_box_form_and_stakeholder_boxes(self):
        """actor_style="box" keeps the «actor» keyword box (errata N17);
        stakeholders ALWAYS draw the «stakeholder» box -- the spec
        reserves the figure for actors."""

        model = longeron.loads("""
            package P {
                part def Person;
                use case def Deliver {
                    actor driver : Person;
                }
                requirement def Comfort {
                    stakeholder owner : Person;
                }
            }
        """)
        widget = diagrams.structure_diagram(model, actor_style="box")
        driver = next(n for n in _walk(widget.source.value) if n.id == "P::Deliver::driver")
        assert driver.labels[0].text == "\u00abactor\u00bb"
        assert "sysml-usage" in driver.properties.cssClasses
        widget = diagrams.structure_diagram(model)  # figure default
        owner = next(n for n in _walk(widget.source.value) if n.id == "P::Comfort::owner")
        assert owner.labels[0].text == "\u00abstakeholder\u00bb"
        assert "sysml-usage" in owner.properties.cssClasses
        with pytest.raises(ValueError, match="actor_style"):
            diagrams.structure_diagram(model, actor_style="stick")

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

    def test_endpoint_clearance_restated_per_hierarchy_level(self, drone_model):
        """ELK does not inherit layered spacing through INCLUDE_CHILDREN
        levels: inside a compound node the edge channels fall back to the
        elkjs 10px default -- within every arrowhead's footprint, so the
        last bend sat under the head (maintainer repro: the shaft entered
        the triangle's side, colon dots floated off the turned line).
        _finish restates render._EDGE_END_CLEARANCE on every container in
        every view; pack grids keep their deliberately tighter value."""

        from longeron.render import _EDGE_END_CLEARANCE

        clearance = f"{_EDGE_END_CLEARANCE:g}"
        key = "elk.layered.spacing.edgeNodeBetweenLayers"
        for build in (
            lambda: diagrams.structure_diagram(drone_model),
            lambda: diagrams.state_diagram(drone_model.find("DeepScout::FlightStates")),
            lambda: diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery")),
        ):
            root = build().source.value
            assert root.layoutOptions[key] == clearance
            for node in _walk(root):
                if node is root or not node.children:
                    continue
                expected = "4" if "elk.hierarchyHandling" in node.layoutOptions else clearance
                assert node.layoutOptions[key] == expected  # grids stay tight


class TestEdgeRoutingKwarg:
    """``routing=`` on every view constructor: the ELK edge routing style
    for headless renders (the toolbar button cycles the same option
    live).  Restated per hierarchy level -- ELK does not inherit it
    through INCLUDE_CHILDREN, exactly like the layer clearance."""

    def test_default_is_orthogonal_on_every_level(self, drone_model):
        for build in (
            lambda: diagrams.structure_diagram(drone_model),
            lambda: diagrams.state_diagram(drone_model.find("DeepScout::FlightStates")),
            lambda: diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery")),
        ):
            root = build().source.value
            assert root.layoutOptions["elk.edgeRouting"] == "ORTHOGONAL"
            for node in _walk(root):
                if node.children:
                    assert node.layoutOptions["elk.edgeRouting"] == "ORTHOGONAL"

    def test_routing_kwarg_lands_on_every_level(self, drone_model):
        for build in (
            lambda: diagrams.structure_diagram(drone_model, routing="polyline"),
            lambda: diagrams.state_diagram(
                drone_model.find("DeepScout::FlightStates"), routing="POLYLINE"
            ),
            lambda: diagrams.action_diagram(
                drone_model.find("DeepScout::PlanBattery"), routing="Polyline"
            ),
        ):
            root = build().source.value
            assert root.layoutOptions["elk.edgeRouting"] == "POLYLINE"
            for node in _walk(root):
                if node.children:
                    assert node.layoutOptions["elk.edgeRouting"] == "POLYLINE"

    def test_unknown_routing_rejected(self, drone_model):
        with pytest.raises(ValueError, match="routing must be one of"):
            diagrams.structure_diagram(drone_model, routing="bezier")


class TestDirectionKwarg:
    """``direction=`` on every view constructor: the layout flow for
    headless renders (the toolbar button toggles the same option live).
    ROOT-ONLY, unlike ``routing=``: elkjs carries ``elk.direction`` into
    nested compounds under INCLUDE_CHILDREN (pinned against real elkjs in
    test_render), and the SEPARATE_CHILDREN packing grids deliberately
    keep their own wide flow."""

    def _builds(self, drone_model, **kwargs):
        return (
            diagrams.structure_diagram(drone_model, **kwargs),
            diagrams.state_diagram(drone_model.find("DeepScout::FlightStates"), **kwargs),
            diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery"), **kwargs),
        )

    def test_default_is_right_on_the_root_only(self, drone_model):
        for built in self._builds(drone_model):
            root = built.source.value
            assert root.layoutOptions["elk.direction"] == "RIGHT"
            for node in _walk(root):
                if node is not root:
                    assert "elk.direction" not in node.layoutOptions

    def test_direction_kwarg_lands_on_the_root_only(self, drone_model):
        for built in self._builds(drone_model, direction="down"):
            root = built.source.value
            assert root.layoutOptions["elk.direction"] == "DOWN"
            for node in _walk(root):
                if node is not root:
                    assert "elk.direction" not in node.layoutOptions

    def test_dispatcher_forwards_direction(self, drone_model):
        built = diagrams.diagram(drone_model, direction="Down")
        assert built.source.value.layoutOptions["elk.direction"] == "DOWN"

    def test_unknown_direction_rejected(self, drone_model):
        with pytest.raises(ValueError, match="direction must be right or down"):
            diagrams.structure_diagram(drone_model, direction="diagonal")


_PORTED = """
package P {
    item def Item1;
    part def Part1;
    part def Part2;
    port def Pin { in item x : Item1; }
    port def Pout { out item y : Item1; }
    port def Pio { in item a : Item1; out item b : Item1; }
    port def Plain;
    connection def ConnectionDef2 {
        end [1..1] part sourceEnd : Part1;
        end [1..*] part targetEnd : Part2;
    }
    part part0 {
        part part1 : Part1 { port po : Pout; port p4 : Plain; }
        part part2 : Part2 { port pc : ~Pin; port pio : Pio; port pd : ~Pout; }
        interface if1 connect part1.po to part2.pc;
        connection connection2 : ConnectionDef2 connect part1 to part2;
        flow of Item1 from part1.po to part2.pc;
    }
}
"""


class TestPortNotation:
    """Phase 2: port usages render as boundary squares (spec Ports,
    printed p.59), direction arrows inside, conjugation textual, and the
    connector family attaches square-to-square."""

    @pytest.fixture(scope="class")
    def root(self):
        return diagrams.structure_diagram(longeron.loads(_PORTED)).source.value

    def test_port_usages_become_boundary_squares(self, root):
        part1 = next(n for n in _walk(root) if n.id == "P::part0::part1")
        # never nested child boxes
        assert not any((child.id or "").endswith("::po") for child in part1.children)
        ports = {port.id: port for port in part1.ports}
        po = ports["P::part0::part1::po"]
        assert (po.width, po.height) == (10, 10)
        # the square straddles the border
        assert po.layoutOptions["elk.port.borderOffset"] == "-5"
        assert "sysml-port" in po.properties.cssClasses
        # name : Type label, pre-sized, placed INSIDE the box by ELK
        # (the spec's part figures write port labels within the body)
        assert po.labels[0].text == "po : Pout"
        assert po.labels[0].properties.get_shape().width > 0
        assert part1.layoutOptions["elk.portLabels.placement"] == "INSIDE"
        # the box grows around its inside port labels
        assert "PORT_LABELS" in part1.layoutOptions["nodeSize.constraints"]

    def test_direction_arrows_derive_from_the_port_definition(self, root):
        """The spec's arrows (printed p.59): the port DEF's directed
        features agree on in/out; mixed draws the double arrow; sides pin
        (in = WEST, out = EAST) and the SYMBOL is the one oriented for
        that side, so the drawn arrow reads relative to the node interior
        (an in-arrow points INTO the node from whatever border)."""

        part1 = next(n for n in _walk(root) if n.id == "P::part0::part1")
        ports = {port.id: port for port in part1.ports}
        po = ports["P::part0::part1::po"]
        assert po.properties.shape.use == "port-out-east"
        assert po.layoutOptions["elk.port.side"] == "EAST"
        assert part1.layoutOptions["elk.portConstraints"] == "FIXED_SIDE"
        part2 = next(n for n in _walk(root) if n.id == "P::part0::part2")
        pio = {port.id: port for port in part2.ports}["P::part0::part2::pio"]
        assert pio.properties.shape.use == "port-inout-east"

    def test_conjugated_ports_stay_textual_and_flip_direction(self, root):
        """Verified against the spec figures (printed pp.75-77): conjugated
        squares draw UNSHADED -- the ~ lives in the type text only -- and
        the direction flips BOTH ways (7.12.3: conjugation reverses
        in/out; the spec's own p.77 example receives a flow on a ``~Pa``
        port whose original feature is ``out``)."""

        part2 = next(n for n in _walk(root) if n.id == "P::part0::part2")
        pc = {port.id: port for port in part2.ports}["P::part0::part2::pc"]
        assert pc.labels[0].text == "pc : ~Pin"
        # in, flipped (+ the adornment contract marker, like every drawn port)
        assert pc.properties.cssClasses == "sysml-adornment sysml-port sysml-port-out"
        assert pc.properties.shape.use == "port-out-east"  # arrow leaves the node
        pd = {port.id: port for port in part2.ports}["P::part0::part2::pd"]
        assert pd.labels[0].text == "pd : ~Pout"
        # out, flipped
        assert pd.properties.cssClasses == "sysml-adornment sysml-port sysml-port-in"
        assert pd.properties.shape.use == "port-in-west"  # arrow enters the node
        assert pd.layoutOptions["elk.port.side"] == "WEST"

    def test_plain_squares_draw_no_arrow(self, root):
        part1 = next(n for n in _walk(root) if n.id == "P::part0::part1")
        p4 = {port.id: port for port in part1.ports}["P::part0::part1::p4"]
        assert p4.properties.cssClasses == "sysml-adornment sysml-port"
        assert p4.properties.shape is None

    def test_undirected_ports_keep_free_constraints(self):
        model = longeron.loads(
            "package P { port def Q; part a { port p : Q; } part b { port q : Q; } }"
        )
        root = diagrams.structure_diagram(model).source.value
        for name in ("P::a", "P::b"):
            node = next(n for n in _walk(root) if n.id == name)
            assert "elk.portConstraints" not in node.layoutOptions
            assert all("elk.port.side" not in p.layoutOptions for p in node.ports)

    def test_interface_and_flow_edges_attach_port_to_port(self, root):
        connect = [
            e
            for e in root.edges
            if "sysml-edge-connect" in e.properties.cssClasses
            and getattr(e.source, "id", None) == "P::part0::part1::po"
        ]
        assert connect and connect[0].target.id == "P::part0::part2::pc"
        assert connect[0].labels[0].text == "if1"
        flows = [e for e in root.edges if "sysml-edge-portflow" in e.properties.cssClasses]
        assert [(e.source.id, e.target.id) for e in flows] == [
            ("P::part0::part1::po", "P::part0::part2::pc")
        ]
        # port-attached flows keep only the FILLED arrowhead (the drawn
        # square already is the pin, spec printed p.77)
        assert flows[0].properties.shape.end == "flow-arrow"
        assert flows[0].properties.shape.start is None

    def test_boundary_ports_draw_no_typing_edges(self, root):
        port_ids = {
            "P::part0::part1::po",
            "P::part0::part1::p4",
            "P::part0::part2::pc",
            "P::part0::part2::pio",
        }
        for edge in root.edges:
            if "sysml-edge-typed" in edge.properties.cssClasses:
                assert getattr(edge.source, "id", None) not in port_ids

    def test_port_symbols_are_registered(self):
        library = diagrams._symbols().library
        # one directed square per (direction, border side): the arrow is
        # drawn relative to the node interior, never absolutely
        for direction in ("in", "out", "inout"):
            for side in ("west", "east", "north", "south"):
                assert f"port-{direction}-{side}" in library
        for identifier in ("port-proxy", "package-tab"):
            assert identifier in library
        # square + currentColor arrow, so the stylesheet drives selection
        use = library["port-in-west"].element.properties.shape.use
        assert "<rect" in use and 'stroke="currentColor"' in use
        # in-arrows point INTO the node: +x from the west border, -x from
        # the east one (the two symbols differ exactly there)
        from longeron.render import _port_arrow_d

        assert (
            _port_arrow_d("in", side="WEST") in library["port-in-west"].element.properties.shape.use
        )
        assert (
            _port_arrow_d("in", side="EAST") in library["port-in-east"].element.properties.shape.use
        )
        assert _port_arrow_d("in", side="WEST") != _port_arrow_d("in", side="EAST")

    def test_portless_nodes_stay_on_the_pre_port_path(self, drone_model):
        """Layout-stability guard: only nodes that actually own drawn
        ports opt into ELK port handling; everything else keeps the exact
        pre-port layout inputs (no ports array, no port options)."""

        root = diagrams.structure_diagram(drone_model).source.value
        for node in _walk(root):
            assert node.ports == []
            assert "elk.portConstraints" not in node.layoutOptions
            assert "elk.portLabels.placement" not in node.layoutOptions


class TestConnectorNotation:
    """Tranche-3 connector family: direction indication, n-ary junctions,
    proxy dots, allocations (spec printed pp.66-67, 79)."""

    def test_directed_connection_draws_open_head_and_typed_label(self):
        root = diagrams.structure_diagram(longeron.loads(_PORTED)).source.value
        directed = [e for e in root.edges if "sysml-edge-directed" in e.properties.cssClasses]
        assert [(e.source.id, e.target.id) for e in directed] == [
            ("P::part0::part1", "P::part0::part2")
        ]
        assert directed[0].properties.shape.end == "arrow"
        assert directed[0].labels[0].text == "connection2 : ConnectionDef2"

    def test_plain_connections_stay_headless(self):
        model = longeron.loads("package P { part a; part b; connect a to b; }")
        root = diagrams.structure_diagram(model).source.value
        connect = [e for e in root.edges if "sysml-edge-connect" in e.properties.cssClasses]
        assert len(connect) == 1
        assert connect[0].properties.shape is None  # no endpoint glyphs

    def test_direction_needs_source_target_end_names(self):
        """The spec's only direction signal is the definition's end names
        (printed pp.65-66) -- ordinary end names draw the undirected form."""

        model = longeron.loads("""
            package P {
                part def A; part def B;
                connection def C1 { end a1 : A; end b1 : B; }
                part a : A; part b : B;
                connection c : C1 connect a to b;
            }
        """)
        root = diagrams.structure_diagram(model).source.value
        assert not any("sysml-edge-directed" in e.properties.cssClasses for e in root.edges)

    def test_nary_connection_draws_the_junction_dot(self):
        model = longeron.loads("""
            package P {
                part def ConnectionDef1;
                part part1; part part2; part part3;
                connection connection1 : ConnectionDef1
                    connect (part1, part2, part3);
            }
        """)
        root = diagrams.structure_diagram(model).source.value
        junction = next(n for n in _walk(root) if "sysml-connjunction" in n.properties.cssClasses)
        # label beside the dot, name : Type (spec printed p.66)
        assert junction.labels[0].text == "connection1 : ConnectionDef1"
        assert junction.id == "P::connection1"
        # spokes anchor on the dot's invisible center ports, so all three
        # lines radiate from the junction itself (t2 item 10 treatment,
        # pulled to the CENTER: the spec draws the lines meeting AT the dot)
        anchors = list(junction.ports)
        assert [p.properties.key for p in anchors] == ["in", "out"]
        spokes = [
            e
            for e in root.edges
            if "sysml-edge-connect" in e.properties.cssClasses
            and any(e.source is p or e.target is p for p in anchors)
        ]
        others = {
            (e.source if any(e.target is p for p in anchors) else e.target).id for e in spokes
        }
        assert len(spokes) == 3
        assert others == {"P::part1", "P::part2", "P::part3"}

    def test_proxy_connection_dots_on_the_drawn_ancestor(self):
        """spec printed p.67: connector ends naming UNDRAWN nested parts
        draw a filled ball on the shallowest drawn ancestor's border,
        labeled with the residual path -- never an edge into the
        definition's member box."""

        model = longeron.loads("""
            package P {
                part def Part2 { part part4; }
                part def Part3 { part part5; }
                part part1 {
                    part part2 : Part2;
                    part part3 : Part3;
                    connect part2.part4 to part3.part5;
                }
            }
        """)
        root = diagrams.structure_diagram(model).source.value
        part2 = next(n for n in _walk(root) if n.id == "P::part1::part2")
        proxies = [p for p in part2.ports if "sysml-port-proxy" in p.properties.cssClasses]
        assert len(proxies) == 1
        assert proxies[0].labels[0].text == ".part4"
        assert proxies[0].properties.shape.use == "port-proxy"
        # the residual-path label reads INSIDE the part box, adjacent to
        # the dot (spec p.67 figure), and the box grows around it
        assert part2.layoutOptions["elk.portLabels.placement"] == "INSIDE"
        assert "PORT_LABELS" in part2.layoutOptions["nodeSize.constraints"]
        connect = [e for e in root.edges if "sysml-edge-connect" in e.properties.cssClasses]
        assert len(connect) == 1
        assert connect[0].source is proxies[0]
        part3 = next(n for n in _walk(root) if n.id == "P::part1::part3")
        assert connect[0].target in part3.ports

    def test_anonymous_allocate_draws_the_keyword_edge(self):
        model = longeron.loads("""
            package P {
                part part1; part part2;
                allocate part1 to part2;
            }
        """)
        root = diagrams.structure_diagram(model).source.value
        allocate = [e for e in root.edges if "sysml-edge-allocate" in e.properties.cssClasses]
        assert [(e.source.id, e.target.id) for e in allocate] == [("P::part1", "P::part2")]
        assert allocate[0].properties.shape.end == "arrow"
        assert allocate[0].labels[0].text == "\u00aballocate\u00bb"

    def test_named_allocations_draw_the_box_form(self):
        model = longeron.loads("""
            package P {
                allocation def AllocationDef1;
                part part1; part part2;
                allocation allocation1 : AllocationDef1
                    allocate part1 to part2;
            }
        """)
        root = diagrams.structure_diagram(model).source.value
        box = next(n for n in _walk(root) if n.id == "P::allocation1")
        assert box.labels[0].text == "\u00aballocation\u00bb"
        assert box.labels[1].text == "allocation1 : AllocationDef1"
        defbox = next(n for n in _walk(root) if n.id == "P::AllocationDef1")
        assert defbox.labels[0].text == "\u00aballocation def\u00bb"
        # the box form replaces the keyword edge (like named satisfies)
        assert not any("sysml-edge-allocate" in e.properties.cssClasses for e in root.edges)


class TestAdornmentContract:
    """Round 4, the UNIVERSAL node-adornment mechanism: every glyph that
    rides a node -- the package folder tab, accept/send badges, boundary
    port squares, proxy dots, and any future adornment -- is built through
    ONE construction site (diagrams._adornment_label /
    diagrams._adornment_port), which stamps the ``sysml-adornment``
    contract class, and is styled by ONE derived rule family keyed on that
    class, so hover AND selection treat the node + its adornments as a
    single shape BY CONSTRUCTION (maintainer: 'I don't want this to be an
    issue every time we have a new type of node')."""

    @pytest.fixture(scope="class")
    def contract_widgets(self):
        """Widgets exercising every adornment construction site the
        builders have: package tabs, boundary squares (directed, plain,
        conjugated, nested), proxy dots, accept/send badges -- across the
        structure view (both membership modes, annotations, both actor
        styles), the action view, and the state view."""

        structure = longeron.loads("""
            package Contract {
                part def Person;
                port def Pin { in item x : Person; }
                port def Pout { out item y : Person; }
                part def Part2 { part part4; }
                part def Part3 { part part5; }
                part def Box {
                    port a : Pin;
                    port b : Pout;
                    port c : ~Pin;
                    port plain;
                }
                part box1 : Box;
                part part1 {
                    part part2 : Part2;
                    part part3 : Part3;
                    connect part2.part4 to part3.part5;
                }
                use case def Deliver { actor driver : Person; }
                requirement def Comfort { stakeholder owner : Person; }
                comment about Person /* annotated */
            }
        """)
        behavior = longeron.loads("""
            package B {
                item def Go;
                action def Chat {
                    action rx accept go : Go;
                    action tx send new Go() via ch;
                    first start then rx;
                    first rx then tx;
                    first tx then done;
                }
                state def Machine {
                    entry; then on;
                    state on;
                    transition first on accept quit then off;
                    state off;
                }
            }
        """)
        return [
            diagrams.structure_diagram(structure, annotations=True),
            diagrams.structure_diagram(structure, membership="edges"),
            diagrams.structure_diagram(structure, actor_style="box"),
            diagrams.action_diagram(behavior.find("B::Chat")),
            diagrams.state_diagram(behavior.find("B::Machine")),
        ]

    def test_every_built_adornment_carries_the_contract(self, contract_widgets):
        """DISCOVERY tripwire: walk everything the builders actually emit
        and fail any node-attached glyph that skipped the construction
        helpers -- a future adornment added without them breaks here
        immediately.  Applied to the full notation gallery too
        (test_every_gallery_model_ships_with_ids)."""

        found = set()
        for widget in contract_widgets:
            found |= _assert_adornment_contract(widget)
        # the fixture exercises every REGISTERED icon adornment kind
        icon_kinds = {kind for kind, flavor in found if flavor == "label"}
        assert icon_kinds == set(diagrams._ADORNMENTS)
        assert ("sysml-port", "port") in found  # squares walked too
        assert ("sysml-port-proxy", "port") in found

    def test_icon_adornment_kinds_are_registered_and_styled(self):
        """The _ADORNMENTS table is the single per-kind parameter source:
        each kind gets exactly one derived resting-ink rule, and the
        hollow family's symbol geometry binds the shared width bridge."""

        library = diagrams._symbols().library
        for use, (family, rest_color) in diagrams._ADORNMENTS.items():
            assert family in ("hollow", "filled")
            assert diagrams.SYSML_STYLE[f" .{use}"] == {"color": rest_color}
            svg = library[use].element.properties.shape.use
            binds_bridge = "var(--lgn-adorn-stroke-width" in svg
            assert binds_bridge == (family == "hollow")

    def test_node_hover_reaches_every_adornment(self):
        """Maintainer repro (a): hovering a package highlighted the rect
        but the tab kept its resting weight.  Hover feedback lands ONLY on
        the node's own <rect> (.elknode.mouseover -- sprotty's hover
        pipeline never decorates labels), but the rect is the PRECEDING
        SIBLING of the <g class="elkchildren"> that holds the adornments
        as DIRECT children (DOM verified live), so the ~ combinator
        retargets the contract bridge -- no decoration needed at all.  The
        rules bind the SAME theme hover variables the rect uses, so the
        weights and colors always match; hover overrides selection (higher
        specificity), and hovered+selected takes the hover-selected color
        at hover width, exactly like the rect."""

        hover = diagrams.SYSML_STYLE[" .elknode.mouseover ~ .elkchildren > .sysml-adornment"]
        assert hover == {
            "color": "var(--jp-elk-stroke-hover)",
            "--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width-hover)",
        }
        both = diagrams.SYSML_STYLE[
            " .elknode.selected.mouseover ~ .elkchildren > .sysml-adornment"
        ]
        assert both == {
            "color": "var(--jp-elk-stroke-hover-selected)",
            "--lgn-adorn-stroke-width": "var(--jp-elk-stroke-width-hover)",
        }

    def test_node_states_recolor_port_squares(self):
        """Ports are the contract's third flavor: the square straddles the
        border, so node selection AND hover recolor its outline and its
        currentColor geometry (direction arrows, proxy dots) with the box;
        the width stays PINNED (the port contract -- hover never fattens a
        10px square) and a port selected in its OWN right keeps the
        fill-flip with a white arrow."""

        for state, color in (
            ("selected", "var(--jp-elk-color-selected)"),
            ("mouseover", "var(--jp-elk-stroke-hover)"),
            ("selected.mouseover", "var(--jp-elk-stroke-hover-selected)"),
        ):
            rule = diagrams.SYSML_STYLE[
                f" .elknode.{state} ~ .elkchildren > .sysml-adornment .elkport"
            ]
            assert rule == {"stroke": color, "color": color}
            own = diagrams.SYSML_STYLE[
                f" .elknode.{state} ~ .elkchildren > .sysml-adornment .elkport.selected"
            ]
            assert own == {"color": "#ffffff"}


class TestPackageTabAndAnnotations:
    """Phase 5: the package folder tab (spec printed p.24) and the opt-in
    annotation layer (notes + metadata adornments, printed pp.20-21, 157)."""

    def test_packages_carry_the_tab_icon_label(self, drone_model):
        root = diagrams.structure_diagram(drone_model).source.value
        package = next(n for n in _walk(root) if "sysml-package" in n.properties.cssClasses)
        tab = package.labels[0]
        assert "sysml-tab" in tab.properties.cssClasses
        assert tab.properties.shape.use == "package-tab"
        # placed OUTSIDE at the top-left, flush (label-node spacing 0)
        assert tab.layoutOptions["nodeLabels.placement"] == "H_LEFT V_TOP OUTSIDE"
        assert package.layoutOptions["elk.spacing.labelNode"] == "0"

    def test_tab_symbol_carries_the_package_palette(self):
        """Maintainer browser repro: the tab rendered as a borderless gray
        block.  The tab is <use> shadow content, where the theme's
        .elklabel rule (label-color fill, stroke-width 0) wins over any
        class-based fill/stroke -- so the symbol geometry itself carries
        the package fill and a currentColor outline as EXPLICIT attributes
        (one continuous folder silhouette, tab styled like the box), and
        .package-tab binds currentColor to the package stroke; selection
        recolors the tab WITH the box."""

        from longeron import render

        style = render._NODE_STYLES["sysml-package"]
        symbol = diagrams._symbols().library["package-tab"]
        use = symbol.element.properties.shape.use
        assert f'fill="{style["fill"]}"' in use  # the package body fill
        assert 'stroke="currentColor"' in use  # outline follows .package-tab
        assert 'stroke-width="1"' in use  # never the .elklabel 0-width
        assert diagrams.SYSML_STYLE[" .package-tab"]["color"] == style["stroke"]
        assert (
            diagrams.SYSML_STYLE[" .elklabel.sysml-adornment.selected"]["color"]
            == "var(--jp-elk-color-selected)"
        )

    def test_tab_outline_thickens_with_selection_like_the_rect(self):
        """Round-3 maintainer nit: selecting a package bolded the box
        outline but not the tab -- the folder must thicken as ONE
        silhouette.  stroke-width cannot reach the <use> shadow geometry
        from CSS (the tab's own attribute wins over anything inherited
        from the <use>), so the geometry binds it through a CSS CUSTOM
        PROPERTY -- which DOES inherit into use-shadow content -- via an
        inline var() style, and the derived stylesheet retargets it: the
        theme's base width normally, the theme's SELECTED width when the
        node is selected (sprotty's select tool decorates every child
        vnode, the tab's <use> included, with the node's .selected).
        Round 4 universalized the bridge: the property is the adornment
        contract's --lgn-adorn-stroke-width, retargeted by the ONE rule
        family keyed on .sysml-adornment (hover variants included -- see
        test_node_hover_reaches_every_adornment)."""

        symbol = diagrams._symbols().library["package-tab"]
        use = symbol.element.properties.shape.use
        # the inline style consumes the inherited custom property, with
        # the base weight as fallback (renderers without the scoped rules)
        assert 'style="stroke-width: var(--lgn-adorn-stroke-width, 1)"' in use
        base = diagrams.SYSML_STYLE[" .sysml-adornment"]
        selected = diagrams.SYSML_STYLE[" .elklabel.sysml-adornment.selected"]
        # bound to the SAME theme variables the .elknode rect uses, so
        # box and tab can never thicken apart
        assert base["--lgn-adorn-stroke-width"] == "var(--jp-elk-stroke-width)"
        assert selected["--lgn-adorn-stroke-width"] == "var(--jp-elk-stroke-width-selected)"

    def test_annotations_default_off(self, drone_model):
        root = diagrams.structure_diagram(drone_model).source.value
        assert not any("sysml-note" in n.properties.cssClasses for n in _walk(root))

    def test_notes_and_anchors(self):
        model = longeron.loads("""
            package P {
                part def Part1 {
                    attribute attribute1 : Real;
                }
                comment about Part1 /* The annotated element is Part1. */
            }
        """)
        root = diagrams.structure_diagram(model, annotations=True).source.value
        note = next(n for n in _walk(root) if "sysml-note" in n.properties.cssClasses)
        assert note.labels[0].text == "\u00abcomment\u00bb"
        assert note.labels[1].text == "The annotated element is Part1."
        anchors = [e for e in root.edges if "sysml-edge-anchor" in e.properties.cssClasses]
        assert [(e.source is note, e.target.id) for e in anchors] == [(True, "P::Part1")]
        assert anchors[0].properties.shape is None  # NO endpoint glyph

    def test_note_carries_the_folded_corner_crease(self):
        """The UML/SysML note silhouette (spec printed pp.20-21): the
        cut-off corner PLUS the two short crease lines outlining the fold
        triangle.  The vendored ipyelk Comment view draws only the plain
        5-sided polygon, so the note pins its geometry and ships the
        outline + crease as one explicit path -- the SAME path family the
        headless renderer draws (render._note_path_d)."""

        from longeron.render import _note_path_d

        model = longeron.loads("""
            package P {
                part def Part1;
                comment about Part1 /* The annotated element is Part1. */
            }
        """)
        root = diagrams.structure_diagram(model, annotations=True).source.value
        note = next(n for n in _walk(root) if "sysml-note" in n.properties.cssClasses)
        assert note.properties.shape.type == "node:path"
        assert note.width and note.height
        d = note.properties.shape.use
        assert d == _note_path_d(note.width, note.height)
        # the crease 'L': down the fold line, then out to the right edge,
        # stroked with the note outline (one path, one stroke)
        fold = min(10.0, note.width / 3, note.height / 3)
        crease = (
            f"M {note.width - fold:g},0 L {note.width - fold:g},{fold:g} L {note.width:g},{fold:g}"
        )
        assert d.endswith(crease)
        assert d.count("Z") == 1  # outline closed; crease lines open
        # labels pinned + pre-sized so both pipelines share the geometry
        assert all(label.x is not None and label.y is not None for label in note.labels)
        # the derived stylesheet strokes the path like the old polygon
        note_style = diagrams.SYSML_STYLE[" .sysml-note > path"]
        assert note_style["stroke"] == "#888888" and note_style["fill"] == "#ffffff"

    def test_notes_are_siblings_of_their_target(self):
        """A doc note annotates its owner but must never nest INSIDE it
        (an anchor into one's own ancestor is the layout hazard)."""

        model = longeron.loads("""
            package P {
                part part0 {
                    doc /* The assembly under test. */
                }
            }
        """)
        root = diagrams.structure_diagram(model, annotations=True).source.value
        package = next(n for n in _walk(root) if n.id == "P")
        note = next(n for n in _walk(root) if "sysml-note" in n.properties.cssClasses)
        assert note in package.children  # sibling of part0, not inside it
        anchors = [e for e in root.edges if "sysml-edge-anchor" in e.properties.cssClasses]
        assert anchors[0].target.id == "P::part0"

    def test_metadata_adornments(self):
        model = longeron.loads("""
            package P {
                metadata def Safety;
                part def Pump;
                @Safety about Pump;
            }
        """)
        root = diagrams.structure_diagram(model, annotations=True).source.value
        pump = next(n for n in _walk(root) if n.id == "P::Pump")
        assert pump.labels[0].text == "\u00ab@Safety\u00bb"
        # ... and stays off by default
        root = diagrams.structure_diagram(model).source.value
        pump = next(n for n in _walk(root) if n.id == "P::Pump")
        assert pump.labels[0].text == "\u00abpart def\u00bb"


class TestViewUsageBoxes:
    """View usages draw in structure diagrams (view-persistence design,
    gap-analysis finding 3): saved diagram recipes are model elements
    too, presented as \u00abview\u00bb keyword boxes."""

    MODEL = """
    package Rig {
        part def Axle { part hub : Hub [2]; }
        part def Hub;
        part axle : Axle;
        view 'axle structure' : StandardViewDefinitions::InterconnectionView {
            expose Rig::**;
            render Views::asInterconnectionDiagram;
        }
    }
    """

    def test_view_usage_draws_as_a_keyword_box(self):
        model = longeron.loads(self.MODEL)
        widget = diagrams.structure_diagram(model)
        node = next((n for n in _walk(widget.source.value) if n.id == "Rig::axle structure"), None)
        assert node is not None, "the view usage is not drawn"
        assert "sysml-usage" in node.properties.cssClasses
        stereotypes = [
            label.text
            for label in node.labels
            if "sysml-stereotype" in (label.properties.cssClasses or "")
        ]
        assert stereotypes == ["\u00abview\u00bb"]

    def test_view_recipe_members_draw_no_stray_boxes(self):
        # the expose and the render reference configure the view; they are
        # not themselves boxes
        model = longeron.loads(self.MODEL)
        widget = diagrams.structure_diagram(model)
        view_node = next(n for n in _walk(widget.source.value) if n.id == "Rig::axle structure")
        assert view_node.children == []

    def test_headless_svg_contains_the_view_box(self):
        from longeron import render

        model = longeron.loads(self.MODEL)
        svg = render.to_svg(diagrams.structure_diagram(model))
        assert "\u00abview\u00bb" in svg
        assert "axle structure" in svg

    def test_adornment_contract_holds_with_view_boxes(self):
        model = longeron.loads(self.MODEL)
        _assert_adornment_contract(diagrams.structure_diagram(model))


class TestStates:
    def test_builds_with_marker_and_transitions(self, drone_model):
        machine = drone_model.find("DeepScout::FlightStates")
        widget = diagrams.state_diagram(machine)
        root = widget.source.value
        state_ids = {n.id for n in _walk(root) if n.id}
        assert "DeepScout::FlightStates::idle" in state_ids
        markers = [n for n in _walk(root) if "sysml-marker" in n.properties.cssClasses]
        assert len(markers) == 1  # the entry marker
        assert len(root.edges) == 6  # entry + 5 transitions

    def test_transition_labels(self, drone_model):
        machine = drone_model.find("DeepScout::FlightStates")
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
        widget = diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery"))
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

        from longeron import render

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
            # the badge is PINNED (empty placement = ELK leaves it): inset
            # clear of the box's rounded corner (rx=6), never at the raw
            # corner where ELK's inside placer put it (maintainer repro:
            # the badge protruded past the corner arc)
            assert badge.layoutOptions["nodeLabels.placement"] == ""
            assert (badge.x, badge.y) == (render._BADGE_INSET_X, render._BADGE_INSET_Y)
            assert badge.x >= 6  # the sysml-step corner radius
            stereotype = node.labels[1]
            assert stereotype.text == f"\u00ab{form}\u00bb"
            # the keyword row starts BELOW the badge strip -- it may never
            # cover the badge (both pipelines share this pinned geometry)
            assert stereotype.layoutOptions["nodeLabels.placement"] == ""
            assert stereotype.y == render._BADGE_STRIP
            assert stereotype.y >= badge.y + render._BADGE_HEIGHT
            # text rows are pre-sized and the box size is fixed, so the
            # browser cannot re-center anything over the badge
            assert stereotype.properties.shape.width
            assert node.width >= 60 and node.height >= 44
            assert node.layoutOptions["elk.nodeSize.constraints"] == "MINIMUM_SIZE"
        # both badge symbols are registered; the badge body paints in
        # currentColor (CSS cannot select INTO the <use> shadow, and an
        # explicit fill attribute there would beat any rule on the <use>),
        # so the stylesheet's `color` binding -- which DOES inherit into
        # the shadow -- drives dark ink normally and the selection color
        # when the owning box is selected (filled family, rule 3; the
        # state rules ride the sysml-adornment contract class)
        assert "accept-badge" in widget.symbols.library
        assert "send-badge" in widget.symbols.library
        for form in ("accept", "send"):
            assert diagrams.SYSML_STYLE[f" .{form}-badge"] == {"color": "#333333"}
            assert (
                diagrams.SYSML_STYLE[" .elklabel.sysml-adornment.selected"]["color"]
                == "var(--jp-elk-color-selected)"
            )
            use = widget.symbols.library[f"{form}-badge"].element.properties.shape.use
            assert 'fill="currentColor"' in use and 'stroke="none"' in use

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

    def test_done_core_is_pure_fill(self):
        """Maintainer browser repro: the done bullseye's filled center dot
        drew a gray outline -- the circle carried no stroke of its own, so
        it inherited the theme's .elknode stroke.  The core is pure fill
        in BOTH pipelines (explicit stroke=none on the geometry AND in the
        derived stylesheet); the terminate X and the start dot already
        paint their strokes explicitly."""

        from longeron import render

        core = diagrams._bullseye_svg().split('class="glyph-core"')[1].split("/>")[0]
        assert 'stroke="none"' in core
        final = render._NODE_STYLES["sysml-final"]
        assert diagrams.SYSML_STYLE[" .sysml-final .glyph-core"] == {
            "fill": final["fill"],
            "stroke": "none",
        }
        # selection still flips the core fill with the ring stroke (rule 3)
        selected = diagrams.SYSML_STYLE[" .sysml-final > .elknode.selected .glyph-core"]
        assert selected == {"fill": "var(--jp-elk-color-selected)"}
        # terminate: ring and X strokes are explicit (never inherited)
        term = diagrams._terminate_svg()
        ring = term.split('class="glyph-ring"')[1].split("/>")[0]
        x_glyph = term.split('class="glyph-x"')[1].split("/>")[0]
        assert 'stroke="#333333"' in ring and 'stroke="#333333"' in x_glyph
        # the start dot is a plain rect: fill and stroke share one color
        marker = render._NODE_STYLES["sysml-marker"]
        assert marker["fill"] == marker["stroke"]

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
        state = diagrams.diagram(drone_model.find("DeepScout::FlightStates"))
        action = diagrams.diagram(drone_model.find("DeepScout::PlanBattery"))
        structure = diagrams.diagram(drone_model)
        assert all(type(w).__name__ == "Diagram" for w in (state, action, structure))

    def test_on_select_resolves_elements(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        received: list = []
        diagrams.on_select(widget, drone_model, received.extend)
        widget.view.selection.ids = ["Rotorcraft::QuadCopter"]
        assert [e.qualified_name for e in received] == ["Rotorcraft::QuadCopter"]
        assert isinstance(received[0], M.Definition)


def test_headless_schedule_run_is_safe():
    """The vendored ipyelk patch: no 'no running event loop' crashes."""

    from ipyelk.elements import Label, Node

    root = Node(children=[Node(labels=[Label(text="x")])])
    import ipyelk

    widget = ipyelk.from_element(root)  # would raise RuntimeError unpatched
    assert widget.source.value is not None


# ---------------------------------------------------------------------------
# browser-transport ids: NOTHING longeron builds may serialize with id null
# ---------------------------------------------------------------------------
#
# The ipyelk browser transport ships ``element.id`` verbatim; ``"id": null``
# kills the elkjs worker (JsonImportException: Id must be a string or an
# integer: 'null') and -- because a failed layout never clears the dirty
# flow -- the pipeline retries forever, starving the notebook.  ipyelk only
# repairs null ids on pipeline flows that wake ValidationPipe ("new") or
# VisibilityPipe (hidden/"layout"); the routing tool's layout-options flow
# wakes neither, so every tree must be transport-ready from birth
# (diagrams._assign_ids).


def _null_transport_ids(data, path="root"):
    """Every element in serialized transport JSON whose id is null, plus
    edge endpoints that failed to resolve to an id."""

    hits = []
    if isinstance(data, dict):
        if "id" in data and data["id"] is None:
            hits.append(path)
        for key in ("sources", "targets"):
            if None in (data.get(key) or []):
                hits.append(f"{path}.{key}")
        for key in ("children", "ports", "edges", "labels", "sections"):
            for index, sub in enumerate(data.get(key) or []):
                hits += _null_transport_ids(sub, f"{path}.{key}[{index}]")
    return hits


def _transport_json(widget):
    from ipyelk.elements.serialization import to_json

    return to_json(widget.source.value, widget.source)


_PROXY_AND_JUNCTION = """
package Proxies {
    part def P;
    part part1 {
        part part2 { part part4 : P; }
    }
    part part3 : P;
    connect part1.part2.part4 to part3;
    dependency part1 to part3;
}
"""

_FLOW_PIN_FORM = """
package Flows {
    item def Item1;
    action def A { in x : Item1; out y : Item1; }
    action action1 : A;
    action action2 : A;
    flow of Item1 from action1.y to action2.x;
}
"""

_DRAWN_PORTS = """
package Ports {
    item def Item1;
    port def Pin { in item x : Item1; }
    port def Pout { out item y : Item1; }
    part part0 {
        part part1 { port po : Pout; }
        part part2 { port pi : Pin; port pc : ~Pout; }
        interface if1 connect part1.po to part2.pc;
    }
}
"""

_ANNOTATED = """
package Notes {
    part def Widget;
    comment about Widget /* a note with a dog-ear */
}
"""


class TestBrowserTransportIds:
    """Regression tripwire for the notation-gallery layout loop."""

    @pytest.mark.parametrize(
        ("source", "build"),
        [
            (_FLOW_PIN_FORM, lambda m: diagrams.structure_diagram(m)),
            (_DRAWN_PORTS, lambda m: diagrams.structure_diagram(m)),
            (_PROXY_AND_JUNCTION, lambda m: diagrams.structure_diagram(m)),
            (_ANNOTATED, lambda m: diagrams.structure_diagram(m, annotations=True)),
            (
                _TYPED_SUBMACHINE,
                lambda m: diagrams.state_diagram(m.find("P::Outer")),
            ),
        ],
        ids=["flow-pins", "drawn-ports", "proxy-junction", "notes", "states"],
    )
    def test_construction_sites_ship_with_ids(self, source, build):
        widget = build(longeron.loads(source))
        assert _null_transport_ids(_transport_json(widget)) == []

    def test_action_lanes_ship_with_ids(self, drone_model):
        widget = diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery"))
        assert _null_transport_ids(_transport_json(widget)) == []

    def test_assign_ids_is_idempotent_and_stable(self):
        first = diagrams.structure_diagram(longeron.loads(_FLOW_PIN_FORM))
        again = diagrams.structure_diagram(longeron.loads(_FLOW_PIN_FORM))
        snapshot = _transport_json(first)
        diagrams._assign_ids(first.source.value)  # re-stamping: a no-op
        assert _transport_json(first) == snapshot
        assert _transport_json(again) == snapshot  # deterministic per build

    def test_synthetic_ids_stay_out_of_qualified_name_consumers(self, drone_model):
        from longeron.render import _SYNTH_ID_PREFIX, _svg_title, _to_elk_json
        from longeron.toolbar import DiagramSearch

        widget = diagrams.structure_diagram(drone_model)
        root = widget.source.value
        assert str(root.id).startswith(_SYNTH_ID_PREFIX)  # the root IS stamped
        # exported titles are recovered from model qnames, never synthetics
        assert _SYNTH_ID_PREFIX not in (_svg_title(widget, root) or "")
        # the headless ELK JSON keeps its compact generated ids
        assert _SYNTH_ID_PREFIX not in str(_to_elk_json(root))
        # the search index carries model-backed nodes only
        search = widget.get_tool(DiagramSearch)
        assert all(not entry.node_id.startswith(_SYNTH_ID_PREFIX) for entry in search._entries)
        assert search.total_count > 0

    def test_every_gallery_model_ships_with_ids(self):
        """Execute EVERY code cell of the notation gallery in-process and
        assert no constructed widget serializes a null id anywhere -- the
        tripwire covers every construction site the gallery exercises
        (drawn ports, proxy dots, junctions, notes, lanes, states, the
        routing tool's clicks in section 9, ...)."""

        import json
        from pathlib import Path

        from ipyelk import Diagram

        path = Path(__file__).resolve().parent.parent / "notebooks" / "11_notation_gallery.ipynb"
        cells = json.loads(path.read_text("utf-8"))["cells"]
        namespace: dict = {}
        for index, cell in enumerate(cells):
            if cell["cell_type"] != "code":
                continue
            code = "".join(cell["source"])
            try:
                exec(compile(code, f"gallery-cell-{index}", "exec"), namespace)
            except Exception as err:  # pragma: no cover - debugging aid
                pytest.fail(f"gallery cell {index} failed: {err}")
        widgets = {name: value for name, value in namespace.items() if isinstance(value, Diagram)}
        assert len(widgets) >= 20  # the gallery builds one widget per section
        for name, widget in sorted(widgets.items()):
            nulls = _null_transport_ids(_transport_json(widget))
            assert nulls == [], f"gallery widget {name!r} ships null ids: {nulls[:5]}"
            # the adornment contract holds across the WHOLE gallery too:
            # any node-attached glyph a gallery section emits without the
            # construction helpers fails the suite here
            _assert_adornment_contract(widget)


class TestRoundtripTimeouts:
    """Pipe timeouts are longeron's knob, not ipyelk's 30s default (CI)."""

    def _pipe_timeouts(self, widget) -> list[float]:
        return [pipe.timeout for pipe in widget.pipe.pipes if hasattr(pipe, "timeout")]

    def test_default_is_generous(self):
        model = longeron.loads("package P { part def A; part a : A; }")
        widget = diagrams.structure_diagram(model)
        timeouts = self._pipe_timeouts(widget)
        assert timeouts, "expected at least one browser-roundtrip pipe"
        assert all(t == 120.0 for t in timeouts), timeouts

    def test_env_var_overrides(self, monkeypatch):
        monkeypatch.setenv("LONGERON_BROWSER_TIMEOUT", "600")
        model = longeron.loads("package P { part def A; part a : A; }")
        widget = diagrams.structure_diagram(model)
        timeouts = self._pipe_timeouts(widget)
        assert timeouts and all(t == 600.0 for t in timeouts), timeouts


_ABSURD_ROW = """
package Fleet {
    part def Mission {
        attribute absurd : Real = base.mass + cargo.bayMass + cargo.payloadKg
            + airframe.wingSpan * airframe.wingArea / (props.cruiseEff * motors.efficiency)
            + battery.energyWh * battery.usableFraction - avionics.mass * 9.81;
        attribute short : Real = 1.0;
        part cargo;
        part battery;
    }
}
"""


class TestMaxLabelWidth:
    """``max_label_width`` caps compartment-row DISPLAY width (default 480):
    calculation/expression rows are unbounded in the model, and one absurd
    expression made its whole node (and every fit computed from it) absurd.
    Overlong rows are END-ellipsized kernel-side at construction, BEFORE any
    measurement -- so the browser text sizer, ``_size_compartment_rows`` and
    the compound-width fits all see only the display string -- and the full
    text rides ``properties.tooltip`` (the label's svg ``<title>`` in both
    pipelines).  Labels stay labels: css classes and selection behavior are
    untouched."""

    def _node(self, widget, ident):
        return next(n for n in _walk(widget.source.value) if n.id == ident)

    def test_overlong_rows_are_ellipsized_with_the_full_text_on_the_tooltip(self):
        from longeron.render import _measure

        model = longeron.loads(_ABSURD_ROW)
        widget = diagrams.structure_diagram(model)
        node = self._node(widget, "Fleet::Mission")
        row = next(label for label in node.labels if (label.text or "").startswith("absurd"))
        assert row.text.endswith("\u2026")
        assert _measure(row.text, row.properties.cssClasses or "")[0] <= 480.0
        full = row.properties.tooltip
        assert full is not None and full.startswith("absurd : Real = ") and "9.81" in full
        assert "sysml-attribute" in (row.properties.cssClasses or "")  # still a row

    def test_short_rows_are_untouched(self):
        model = longeron.loads(_ABSURD_ROW)
        widget = diagrams.structure_diagram(model)
        node = self._node(widget, "Fleet::Mission")
        row = next(label for label in node.labels if (label.text or "").startswith("short"))
        assert row.text == "short : Real = 1.0"
        assert row.properties.tooltip is None

    def test_the_pinned_row_shapes_see_the_display_width(self):
        """_size_compartment_rows runs AFTER truncation, so the shared
        row-box width (and through it every compound fit) keys off the
        truncated string automatically."""

        model = longeron.loads(_ABSURD_ROW)
        widget = diagrams.structure_diagram(model)
        node = self._node(widget, "Fleet::Mission")
        for label in node.labels:
            shape = label.properties.shape
            if shape is not None and shape.width:
                assert shape.width <= 480.0 + 0.01

    def test_none_lifts_the_cap(self):
        model = longeron.loads(_ABSURD_ROW)
        widget = diagrams.structure_diagram(model, max_label_width=None)
        node = self._node(widget, "Fleet::Mission")
        row = next(label for label in node.labels if (label.text or "").startswith("absurd"))
        assert not row.text.endswith("\u2026")
        assert row.properties.tooltip is None

    def test_a_tighter_cap_and_option_persistence(self):
        model = longeron.loads(_ABSURD_ROW)
        widget = diagrams.structure_diagram(model, max_label_width=200)
        node = self._node(widget, "Fleet::Mission")
        from longeron.render import _measure

        for label in node.labels:
            if "sysml-attribute" in (label.properties.cssClasses or ""):
                assert _measure(label.text or "", label.properties.cssClasses or "")[0] <= 200.0
        # deviations persist through the view sidecar; the default does not
        assert widget._lgn_view_state["options"]["max_label_width"] == 200
        default = diagrams.structure_diagram(model)
        assert "max_label_width" not in default._lgn_view_state["options"]
        lifted = diagrams.structure_diagram(model, max_label_width=None)
        assert lifted._lgn_view_state["options"]["max_label_width"] is None

    def test_invalid_cap_is_rejected(self):
        model = longeron.loads(_ABSURD_ROW)
        with pytest.raises(ValueError, match="max_label_width"):
            diagrams.structure_diagram(model, max_label_width=0)
        with pytest.raises(ValueError, match="max_label_width"):
            diagrams.structure_diagram(model, max_label_width=-10)

    def test_state_and_action_builders_accept_the_cap(self, drone_model):
        diagrams.state_diagram(drone_model.find("DeepScout::FlightStates"), max_label_width=200)
        widget = diagrams.action_diagram(
            drone_model.find("DeepScout::PlanBattery"), max_label_width=200
        )
        assert widget._lgn_view_state["options"]["max_label_width"] == 200


class TestUniversalFitMachinery:
    """EVERY built diagram is self-fitting: the builder funnel (_finish)
    registers the AutoFitTool and mounts its fit sentinel INSIDE the
    widget's own DOM, so plain display(widget) gets fit-on-first-reveal
    and fit-on-resize with zero consumer wiring -- the explorer's pane,
    an HBox beside a 3D viewer, a bare notebook cell: same machinery."""

    def _builders(self, drone_model):
        from longeron.explorer import requirements_view

        yield diagrams.structure_diagram(drone_model)
        yield diagrams.state_diagram(drone_model.find("DeepScout::FlightStates"))
        yield diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery"))
        yield requirements_view(drone_model)

    def test_every_builder_mounts_the_sentinel(self, drone_model):
        from longeron.toolbar import AutoFitTool

        for widget in self._builders(drone_model):
            tool = widget.get_tool(AutoFitTool)
            assert tool.sentinel is not None, widget
            assert tool.sentinel in widget.children, widget
            assert tool.sentinel.layout.display == "none", widget
            assert "lgx-diagram" in widget._dom_classes, widget

    def test_one_sentinel_per_widget(self, drone_model):
        # the notation gallery renders ~24 diagrams in one notebook: one
        # (hidden, observer-based) sentinel per widget is the whole cost
        from longeron.toolbar import AutoFitTool

        for widget in self._builders(drone_model):
            sentinel = widget.get_tool(AutoFitTool).sentinel
            mounted = [child for child in widget.children if child is sentinel]
            assert len(mounted) == 1
            kind = type(sentinel).__name__
            same_kind = [c for c in widget.children if type(c).__name__ == kind]
            assert len(same_kind) == 1


class TestBuilderHeight:
    """The builders' height story: bare cells keep the 400px minimum
    floor; an explicit ``height=`` is honored exactly (plumbed to
    ``result.layout`` in ``_finish``), even below the floor -- so inline
    compositions can match a neighbor (NB10's 480px 3D viewer)."""

    def test_default_keeps_the_bare_cell_floor(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        assert widget.layout.min_height == "400px"
        assert widget.layout.height == "100%"  # ipyelk default: fill what the cell gives

    def test_explicit_height_is_exact_for_every_builder(self, drone_model):
        for widget in (
            diagrams.structure_diagram(drone_model, height="480px"),
            diagrams.state_diagram(drone_model.find("DeepScout::FlightStates"), height="480px"),
            diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery"), height="480px"),
        ):
            assert widget.layout.height == "480px"
            # the floor must NOT fight the request (CSS min-height wins
            # over height, so an explicit height drops it)
            assert widget.layout.min_height == "0"

    def test_explicit_height_wins_below_the_floor(self, drone_model):
        widget = diagrams.structure_diagram(drone_model, height="300px")
        assert widget.layout.height == "300px"
        assert widget.layout.min_height == "0"

    def test_requirements_view_passes_height_through(self, drone_model):
        from longeron.explorer import requirements_view

        widget = requirements_view(drone_model, height="480px")
        assert widget.layout.height == "480px"

    def test_height_is_presentation_not_a_stamped_option(self, drone_model):
        # view persistence stores builder OPTIONS; height is live layout
        widget = diagrams.structure_diagram(drone_model, height="480px")
        assert "height" not in widget._lgn_view_state["options"]

    def test_non_string_height_is_rejected(self, drone_model):
        with pytest.raises(ValueError, match="CSS length"):
            diagrams.structure_diagram(drone_model, height=480)
