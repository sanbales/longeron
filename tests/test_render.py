"""Headless SVG/PNG rendering tests (node + vendored elkjs)."""

import math
import re
import shutil

import pytest

pytest.importorskip("ipyelk")
if shutil.which("node") is None:
    pytest.skip("node executable not available", allow_module_level=True)

import longeron
from longeron import diagrams, render


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load("examples/deepscout")


def _walk_children(node):
    yield node
    for child in node.children:
        yield from _walk_children(child)


class TestSvg:
    def test_structure_svg(self, drone_model, tmp_path):
        path = tmp_path / "structure.svg"
        svg = render.to_svg(diagrams.structure_diagram(drone_model), path)
        assert path.exists()
        assert svg.startswith("<svg")
        assert "QuadCopter" in svg
        assert "capacity : Real = 5200.0" in svg

    def test_state_svg_has_transitions(self, drone_model):
        svg = render.to_svg(diagrams.state_diagram(drone_model.find("DeepScout::FlightStates")))
        assert "launch" in svg and "touchdown" in svg
        assert 'marker-end="url(#arrow-b58900)"' in svg  # gold arrowheads
        assert 'markerUnits="userSpaceOnUse"' in svg  # constant-size heads
        assert "#b58900" in svg  # state/transition styling applied

    def test_action_svg(self, drone_model):
        svg = render.to_svg(diagrams.action_diagram(drone_model.find("DeepScout::PlanBattery")))
        assert "start" in svg and "done" in svg

    def test_accepts_model_elements_directly(self, drone_model):
        svg = render.to_svg(drone_model.find("DeepScout::FlightStates"))
        assert "flying" in svg

    def test_disconnected_definitions_pack_wide(self):
        """Regression (V1): edge-free definitions pack into rows, not one
        tall column, and the packing edges themselves are not drawn."""

        import re

        model = longeron.loads(
            "package P { part def A; part def B; part def C; part def D; part def E; part def F; }"
        )
        svg = render.to_svg(model)
        match = re.search(r'width="(\d+)" height="(\d+)"', svg)
        assert match is not None
        width, height = int(match.group(1)), int(match.group(2))
        assert width > height
        body = svg.split("</defs>")[1]
        assert "<path" not in body  # no edges drawn for packing chains

    def test_arrowhead_forms_follow_the_spec_notation(self):
        """SysML v2 notation (single-sourced in render._EDGE_ENDS): the
        specialization family draws SOLID lines into a closed hollow
        triangle -- plain for subclassification, colon-dotted on the shaft
        for feature typing -- and connections carry no arrowhead.
        (Updated with the spec errata: typing was wrongly dashed and
        unadorned before; spec 8.2.3 BNF printed p.200.)"""

        model = longeron.loads("""
            package P {
                part def Base;
                part def Derived :> Base;
                part a : Derived;
                part sys { part x; part y; connect x to y; }
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))

        def edge_group(key):
            return svg.split(f'data-edge="{key}"')[1].split("</g>")[0]

        specializes = edge_group("P::Derived-&gt;P::Base")
        assert f'marker-end="url(#{render._hollow_arrow_id("#4878a8")})"' in specializes
        assert "dasharray" not in specializes  # solid line
        typed = edge_group("P::a-&gt;P::Derived")
        assert f'marker-end="url(#{render._marker_id("hollow-colon", "#6a9a48")})"' in typed
        assert "dasharray" not in typed  # typing is SOLID (errata E2)
        connect = edge_group("P::sys::x-&gt;P::sys::y")
        assert "marker-end" not in connect  # connectors are non-directional
        # hollow marker defs: white fill occludes the line, the outline
        # takes the edge color
        assert 'd="M 1 1 L 11 6 L 1 11 z" fill="#ffffff" stroke="#4878a8"' in svg

    def test_specialization_family_shaft_adornments(self):
        """The family rule (spec errata E1-E5): head always a closed hollow
        triangle, line always solid, and the shaft adornment mirrors the
        extra textual characters -- ':' = two filled dots straddling the
        shaft, ':>>' = one perpendicular bar tick, '::>' = 2x2 dots."""

        model = longeron.loads("""
            package Q {
                part def V { part engine; }
                part tuned : V { part engine :>> engine; }
                part vehicle;
                part truck :> vehicle;
                part pool;
                part spare ::> pool;
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))

        def edge_group(key):
            return svg.split(f'data-edge="{key}"')[1].split("</g>")[0]

        redefines = edge_group("Q::tuned::engine-&gt;Q::V::engine")
        assert f'marker-end="url(#{render._marker_id("hollow-tick", "#6a9a48")})"' in redefines
        assert "dasharray" not in redefines
        assert "\u00ab" not in redefines  # NO «redefines» keyword label (errata E3)
        subsets = edge_group("Q::truck-&gt;Q::vehicle")
        # plain subsetting: the SAME head as subclassification, no adornment
        assert f'marker-end="url(#{render._hollow_arrow_id("#6a9a48")})"' in subsets
        assert "\u00ab" not in subsets  # NO «subsets» keyword label (errata E4)
        references = edge_group("Q::spare-&gt;Q::pool")
        assert f'marker-end="url(#{render._marker_id("hollow-dcolon", "#6a9a48")})"' in references
        # marker geometry: the colon dots are FILLED in the edge color and
        # straddle the shaft (one above, one below); the tick is a bar
        # perpendicular across the shaft just behind the head
        defs = svg.split("</defs>")[0]
        colon = defs.split(f'id="{render._marker_id("hollow-colon", "#6a9a48")}"')[1].split(
            "</marker>"
        )[0]
        assert colon.count('fill="#6a9a48"') == 2  # two dots
        assert 'cy="3"' in colon and 'cy="9"' in colon  # straddling the shaft
        tick = defs.split(f'id="{render._marker_id("hollow-tick", "#6a9a48")}"')[1].split(
            "</marker>"
        )[0]
        assert 'stroke-width="1.4"' in tick  # the perpendicular bar
        dcolon = defs.split(f'id="{render._marker_id("hollow-dcolon", "#6a9a48")}"')[1].split(
            "</marker>"
        )[0]
        assert dcolon.count('fill="#6a9a48"') == 4  # 2x2 dots

    def test_membership_diamonds_and_end_multiplicities(self):
        """Composite part membership draws a FILLED diamond at the whole
        end (errata E6), referential membership a HOLLOW one (E7); the
        member's multiplicity labels the part end and connector cross
        multiplicities label their ends (spec pp.37-38)."""

        model = longeron.loads("""
            package P {
                part def Wheel;
                part def Driver;
                part def Car {
                    part wheels : Wheel [4];
                    ref part driver : Driver;
                    part w1 : Wheel;
                    part w2 : Wheel;
                    connect [1] w1 to [0..2] w2;
                }
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))

        def edge_groups(key):
            return svg.split(f'data-edge="{key}"')[1:]

        composite = edge_groups("P::Car-&gt;P::Wheel")
        assert len(composite) == 3  # wheels, w1, w2
        for group in composite:
            body = group.split("</g>")[0]
            assert f'marker-start="url(#{render._diamond_id("#555555", hollow=False)})"' in body
            assert "marker-end" not in body  # no head at the part end
        assert any(">wheels<" in g.split("</g>")[0] for g in composite)  # role name
        assert any(">[4]<" in g.split("</g>")[0] for g in composite)  # end multiplicity
        referential = edge_groups("P::Car-&gt;P::Driver")[0].split("</g>")[0]
        assert f'marker-start="url(#{render._diamond_id("#555555", hollow=True)})"' in referential
        # connector cross multiplicities ride the connect edge's ends
        connect = edge_groups("P::Car::w1-&gt;P::Car::w2")[0].split("</g>")[0]
        assert ">[1]<" in connect and ">[0..2]<" in connect
        # diamond defs: filled binds fill to the stroke, hollow stays white
        defs = svg.split("</defs>")[0]
        filled = defs.split(f'id="{render._diamond_id("#555555", hollow=False)}"')[1].split(
            "</marker>"
        )[0]
        assert 'fill="#555555"' in filled
        hollow = defs.split(f'id="{render._diamond_id("#555555", hollow=True)}"')[1].split(
            "</marker>"
        )[0]
        assert 'fill="#ffffff"' in hollow

    def test_behavior_view_glyphs(self):
        """Action-flow node glyphs per the spec (errata N5-N10 + terminate):
        done = bullseye, terminate = circle-X, fork/join = thick filled
        bar, decision/merge = empty rhombus, accept/send = standard action
        box with a filled top-left badge; successions render DASHED (E12)."""

        model = longeron.loads("""
            package P {
                item def Go;
                action def Flow {
                    action a;
                    action b;
                    fork f;
                    join j;
                    decide d;
                    merge g;
                    action rx accept go : Go;
                    action tx send new Go() via ch;
                    first start then f;
                    first f then a;
                    first f then b;
                    first a then j;
                    first b then j;
                    first j then d;
                    first d if x > 0 then rx;
                    first d then g;
                    first rx then tx;
                    first tx then g;
                    first g then done;
                }
                action def Abort {
                    action warn send new Go() via ch;
                    terminate;
                }
            }
        """)
        svg = render.to_svg(diagrams.action_diagram(model.find("P::Flow")))
        # fork/join: filled bars (rects in the marker family)
        for name in ("P::Flow::f", "P::Flow::j"):
            bar = svg.split(f'data-qname="{name}"')[1].split("/>")[0]
            assert 'fill="#333333"' in bar
        # decision/merge: hollow rhombi
        for name in ("P::Flow::d", "P::Flow::g"):
            prefix = svg.split(f'data-qname="{name}"')[0]
            assert prefix.rstrip().endswith("<polygon")
        diamond = svg.split('data-qname="P::Flow::d"')[1].split("/>")[0]
        assert 'fill="#ffffff"' in diamond
        # done: bullseye (empty ring + filled core)
        glyph_groups = [g.split("</g>")[0] for g in svg.split("<g data-qname=")[1:]]
        assert any(
            group.count("<circle") == 2 and 'fill="#333333"' in group for group in glyph_groups
        )
        # accept/send: badge polygons at the box's top-left (the control
        # rhombi render as data-qname polygons, badges as plain ones)
        assert svg.count("<polygon points=") == 2
        # successions are dashed with open-V heads
        succession = svg.split('data-edge="P::Flow::rx-&gt;P::Flow::tx"')[1].split("</g>")[0]
        assert 'stroke-dasharray="4 2"' in succession
        assert f'marker-end="url(#{render._arrow_id("#6c56a8")})"' in succession
        # terminate: circle with an inscribed X
        abort = render.to_svg(diagrams.action_diagram(model.find("P::Abort")))
        groups = [g.split("</g>")[0] for g in abort.split("<g data-qname=")[1:]]
        assert any("<circle" in g and "<path" in g and " L " in g for g in groups)
        assert "terminate" in abort  # the glyph label

    def test_flow_connections_draw_pins_and_payload_labels(self):
        """Flow connections (errata E16/M1): solid line from a small square
        source-output pin to a small square target-input pin, small FILLED
        arrowhead at the target pin, payload item labels near each end."""

        model = longeron.loads("""
            package P {
                item def Item1;
                action def A { in x : Item1; out y : Item1; }
                action a1 : A;
                action a2 : A;
                flow of Item1 from a1.y to a2.x;
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        flow = svg.split('data-edge="P::a1-&gt;P::a2"')[1].split("</g>")[0]
        assert f'marker-start="url(#{render._start_marker_id("pin", "#555555")})"' in flow
        assert f'marker-end="url(#{render._marker_id("pin-arrow", "#555555")})"' in flow
        assert "dasharray" not in flow  # flows are solid connector lines
        assert flow.count(">Item1</text>") == 4  # 2 ends x (halo + fill)
        # marker geometry: hollow squares straddle the border (white body),
        # the target pin carries a small FILLED arrowhead tight against it
        defs = svg.split("</defs>")[0]
        pin = defs.split(f'id="{render._start_marker_id("pin", "#555555")}"')[1].split("</marker>")[
            0
        ]
        assert 'fill="#ffffff"' in pin and "<rect" in pin
        pin_arrow = defs.split(f'id="{render._marker_id("pin-arrow", "#555555")}"')[1].split(
            "</marker>"
        )[0]
        assert 'fill="#555555"' in pin_arrow  # the filled direction head
        assert 'fill="#ffffff"' in pin_arrow  # the hollow pin square

    def test_binding_connectors_carry_the_equals_glyph(self):
        """Binding connectors (errata E15): '=' rides the solid line
        mid-span; no endpoint glyphs."""

        model = longeron.loads("""
            package P {
                part a;
                part b;
                binding bind a = b;
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        bind = svg.split('data-edge="P::a-&gt;P::b"')[1].split("</g>")[0]
        assert ">=</text>" in bind
        assert "marker-end" not in bind and "marker-start" not in bind
        assert "dasharray" not in bind

    def test_dependency_edges_binary_and_nary(self):
        """Dependencies (errata E8): dashed open-V client->supplier with the
        optional (rel-name) label; n-ary form radiates dashed links from a
        filled junction dot -- client links plain, supplier links arrowed."""

        model = longeron.loads("""
            package P {
                part a;
                part b;
                part c;
                part s;
                dependency Uses from a to s;
                dependency Multi from b, c to s;
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        binary = svg.split('data-edge="P::a-&gt;P::s"')[1].split("</g>")[0]
        assert f'marker-end="url(#{render._arrow_id("#a85c78")})"' in binary
        assert 'stroke-dasharray="4 2"' in binary
        assert ">(Uses)</text>" in binary  # optional (rel-name) label
        # n-ary: a filled junction dot node; client links carry NO head
        junction = svg.split('data-qname="P::Multi"')[1].split("/>")[0]
        assert 'fill="#a85c78"' in junction
        client = svg.split('data-edge="P::b-&gt;P::Multi"')[1].split("</g>")[0]
        assert "marker-end" not in client
        assert 'stroke-dasharray="4 2"' in client
        supplier = svg.split('data-edge="P::Multi-&gt;P::s"')[1].split("</g>")[0]
        assert f'marker-end="url(#{render._arrow_id("#a85c78")})"' in supplier

    def test_satisfy_notation_both_forms(self):
        """Satisfy (spec printed p.133): the anonymous shorthand draws a
        solid «satisfy» keyword edge from the satisfying element to the
        requirement; the named longhand draws a «satisfy requirement» box
        wired to the «requirement» box by REFERENCE subsetting (the
        double-colon dotted hollow triangle)."""

        model = longeron.loads("""
            package Reqs { requirement requirement1; }
            package Sys {
                part part1 {
                    satisfy requirement requirement2 references Reqs::requirement1;
                }
                part sys;
                satisfy Reqs::requirement1 by sys;
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        assert "\u00abrequirement\u00bb" in svg  # requirement usages draw as boxes
        assert "\u00absatisfy requirement\u00bb" in svg
        longhand = svg.split('data-edge="Sys::part1::requirement2-&gt;Reqs::requirement1"')[
            1
        ].split("</g>")[0]
        assert f'marker-end="url(#{render._marker_id("hollow-dcolon", "#6a9a48")})"' in longhand
        shorthand = svg.split('data-edge="Sys::sys-&gt;Reqs::requirement1"')[1].split("</g>")[0]
        assert f'marker-end="url(#{render._arrow_id("#a85c78")})"' in shorthand
        assert "\u00absatisfy\u00bb" in shorthand
        assert "dasharray" not in shorthand  # keyword edges are solid

    def test_alias_membership_circle(self):
        """Membership (unowned/alias, errata E18): solid line, small HOLLOW
        circle at the referencing namespace end, alias name as the label."""

        model = longeron.loads("""
            package Lib { part def Target; }
            package App { alias T for Lib::Target; }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        alias = svg.split('data-edge="App-&gt;Lib::Target"')[1].split("</g>")[0]
        assert f'marker-start="url(#{render._start_marker_id("circle", "#555555")})"' in alias
        assert "marker-end" not in alias
        assert ">T</text>" in alias  # the alias name labels the edge
        defs = svg.split("</defs>")[0]
        circle = defs.split(f'id="{render._start_marker_id("circle", "#555555")}"')[1].split(
            "</marker>"
        )[0]
        assert 'fill="#ffffff"' in circle  # hollow, forever

    def test_owned_membership_edges_draw_the_circle_plus(self):
        """Membership (owned member, errata E18 official v2 ALTERNATIVE
        presentation, spec printed p.26): membership="edges" unnests
        package members into siblings and joins them to the owning package
        with a solid line carrying a TRUE circled-plus at the OWNING end;
        both membership forms coexist in one diagram."""

        import math

        model = longeron.loads("""
            package Package0 { package Package1; }
            package Package2 { alias Package1Alias for Package0::Package1; }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model, membership="edges"))
        owned = svg.split('data-edge="Package0-&gt;Package0::Package1"')[1].split("</g>")[0]
        plus_id = render._start_marker_id("circle-plus", "#555555")
        assert f'marker-start="url(#{plus_id})"' in owned
        assert "marker-end" not in owned  # no head at the member end
        assert "dasharray" not in owned  # solid line
        assert "<text" not in owned  # unlabeled (unlike the alias form)
        # both E18 forms in one diagram: the alias circle still draws
        alias = svg.split('data-edge="Package2-&gt;Package0::Package1"')[1].split("</g>")[0]
        assert f'marker-start="url(#{render._start_marker_id("circle", "#555555")})"' in alias
        assert "Package1Alias" in alias
        # marker geometry: a TRUE circled plus -- hollow white body, both
        # cross strokes spanning the FULL diameter (endpoints ON the
        # circle; the maintainer rejected a floating '+' inside the circle)
        defs = svg.split("</defs>")[0]
        glyph = defs.split(f'id="{plus_id}"')[1].split("</marker>")[0]
        r = render._CIRCLE_RADIUS
        mid, far = r + 1, 2 * r + 1
        assert f'<circle cx="{mid:g}" cy="{mid:g}" r="{r:g}" fill="#ffffff"' in glyph
        assert f'd="M 1 {mid:g} L {far:g} {mid:g} M {mid:g} 1 L {mid:g} {far:g}"' in glyph
        for x, y in ((1, mid), (far, mid), (mid, 1), (mid, far)):
            assert math.hypot(x - mid, y - mid) == pytest.approx(r)  # ON the circle

    def test_membership_nested_default_is_byte_identical(self, drone_model):
        """membership="nested" IS the default (today's behavior): the SVG
        is byte-identical with and without the argument, and no owned-
        membership glyph reaches the drawn body -- packages keep swallowing
        their members."""

        default = render.to_svg(diagrams.structure_diagram(drone_model))
        nested = render.to_svg(diagrams.structure_diagram(drone_model, membership="nested"))
        assert default == nested
        body = default.split("</defs>")[1]
        assert "circle-plus" not in body  # glyph never referenced
        assert "sysml-edge-owned" not in body
        # members still NEST: the QuadCopter usages sit inside their box
        assert 'data-qname="Rotorcraft::QuadCopter::motors"' in body

    def test_portion_membership_ball(self):
        """Portion membership (errata new row): timeslice/snapshot usages
        link to their individual with a FILLED ball, open-V notch on the
        line side, at the WHOLE-occurrence end -- replacing the plain
        typing edge; the «individual»/«timeslice»/«snapshot» keywords
        ride the boxes."""

        model = longeron.loads("""
            package P {
                individual part def Rover;
                timeslice t1 : Rover;
                snapshot s1 : Rover;
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        assert "\u00abindividual part def\u00bb" in svg
        assert "\u00abtimeslice\u00bb" in svg and "\u00absnapshot\u00bb" in svg
        for name in ("t1", "s1"):
            edge = svg.split(f'data-edge="P::{name}-&gt;P::Rover"')[1].split("</g>")[0]
            assert f'marker-end="url(#{render._marker_id("ball-notch", "#555555")})"' in edge
            # the portion edge REPLACES the typing edge (no colon-dot head)
            assert "hollow-colon" not in edge
        assert svg.count('data-edge="P::t1-&gt;P::Rover"') == 1  # no duplicate
        defs = svg.split("</defs>")[0]
        ball = defs.split(f'id="{render._marker_id("ball-notch", "#555555")}"')[1].split(
            "</marker>"
        )[0]
        assert 'fill="#555555"' in ball and " A " in ball  # filled, notched

    def test_actor_figure_default_with_box_fallback(self):
        """Actors draw the spec's stick FIGURE by default (BNF printed
        p.244; crop gt-actor.png): head circle + limbs line art in the
        usage stroke with the name BELOW the figure, no «actor» keyword
        row (the figure IS the stereotype).  ``actor_style="box"`` keeps
        the errata-N17 keyword-box alternative; stakeholders stay
        «stakeholder» boxes in both styles (the spec reserves the figure
        for actors)."""

        model = longeron.loads("""
            package P {
                part def Person;
                use case def Deliver {
                    subject route;
                    actor driver : Person;
                }
                requirement def Comfort {
                    stakeholder owner : Person;
                }
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        assert "\u00abactor\u00bb" not in svg
        assert "\u00abstakeholder\u00bb" in svg
        figure = svg.split('<g data-qname="P::Deliver::driver">')[1].split("</g>")[0]
        # geometry single-sourced with the browser symbol (_actor_geometry)
        _cx, _cy, r, limbs = render._actor_geometry()
        assert f'r="{r:.1f}"' in figure and f'd="{limbs}"' in figure
        assert figure.count('stroke="#6a9a48"') == 2  # head + limbs, usage green
        # the name reads BELOW the figure -- the glyph-node label path
        top = float(re.search(r'transform="translate\([\d.]+,([\d.]+)\)"', figure).group(1))
        name = re.search(r'<text [^>]*y="([\d.]+)"[^>]*>driver : Person</text>', svg)
        assert name is not None
        assert float(name.group(1)) > top + render._ACTOR_HEIGHT
        # the actor's typing edge still draws like any usage->def typing
        typed = svg.split('data-edge="P::Deliver::driver-&gt;P::Person"')[1].split("</g>")[0]
        assert "hollow-colon" in typed
        # the keyword-box alternative (errata N17) stays a kwarg away
        boxed = render.to_svg(diagrams.structure_diagram(model, actor_style="box"))
        assert "\u00abactor\u00bb" in boxed
        assert '<rect data-qname="P::Deliver::driver"' in boxed

    def test_swimlanes_draw_dashed_performer_lanes(self):
        """Perform Actions Swimlanes (spec printed p.90): lanes=... adds
        dashed-boundary «performer» containers ordered left-to-right by
        ELK layer partitioning; steps sit inside their performer's lane,
        start/done stay outside; default stays lane-free."""

        model = longeron.loads("""
            package P {
                part station { action a1; action a4; }
                part rover { action a2; action a3; }
                action def Swim {
                    perform station.a1;
                    perform rover.a2;
                    perform rover.a3;
                    perform station.a4;
                }
            }
        """)
        widget = diagrams.action_diagram(model.find("P::Swim"), lanes=True)
        graph = render.layout(render._to_elk_json(widget.source.value))
        lanes = [c for c in graph["children"] if "sysml-lane" in c["properties"]["cssClasses"]]
        assert [lane["labels"][1]["text"] for lane in lanes] == ["station", "rover"]
        assert all(lane["labels"][0]["text"] == "\u00abperformer\u00bb" for lane in lanes)
        # partitioning orders the lanes left-to-right, start before, done after
        station, rover = lanes
        assert station["x"] + station["width"] <= rover["x"]
        start = next(c for c in graph["children"] if "sysml-marker" in str(c["properties"]))
        done = next(c for c in graph["children"] if "sysml-final" in str(c["properties"]))
        assert start["x"] + start["width"] <= station["x"]
        assert done["x"] >= rover["x"] + rover["width"]
        # both a2 and a3 sit INSIDE the rover lane
        rover_steps = {child["labels"][-1]["text"] for child in rover["children"]}
        assert rover_steps == {"rover.a2", "rover.a3"}
        # the boundary is dashed in the headless SVG
        svg = render._svg_from_layout(graph)
        assert svg.count('stroke-dasharray="4 3"') == 2
        # default: no lanes
        plain = diagrams.action_diagram(model.find("P::Swim"))
        assert not any(
            "sysml-lane" in (n.properties.cssClasses or "")
            for n in _walk_children(plain.source.value)
        )

    def test_control_glyphs_converge_edges_on_single_anchors(self):
        """Item 10: decision/merge/done/start/terminate glyphs anchor ALL
        incoming edges at one point and all outgoing at one point (fixed
        west/east convergence ports); fork/join bars keep distributing
        edges along the bar; replay's data-edge keys stay node-qualified."""

        model = longeron.loads("""
            package P {
                action def Flow {
                    action a;
                    action b;
                    action c;
                    decide d;
                    merge g;
                    first start then d;
                    first d if x > 0 then a;
                    first d if x < 0 then b;
                    first d then c;
                    first a then g;
                    first b then g;
                    first c then g;
                    first g then done;
                }
            }
        """)
        widget = diagrams.action_diagram(model.find("P::Flow"))
        graph = render.layout(render._to_elk_json(widget.source.value))
        starts: dict = {}
        ends: dict = {}
        for edge in graph.get("edges", []):
            section = edge["sections"][0]
            source = edge["properties"]["sourceNode"]
            target = edge["properties"]["targetNode"]
            point = section["startPoint"]
            starts.setdefault(source, set()).add((point["x"], point["y"]))
            point = section["endPoint"]
            ends.setdefault(target, set()).add((point["x"], point["y"]))
        assert len(starts["P::Flow::d"]) == 1  # 3 out-edges, ONE anchor
        assert len(ends["P::Flow::g"]) == 1  # 3 in-edges, ONE anchor
        # data-edge keys keep the replay contract (node ids, never ports)
        svg = render._svg_from_layout(graph)
        assert 'data-edge="P::Flow::d-&gt;P::Flow::a"' in svg
        assert '.in"' not in svg and '.out"' not in svg

    def test_transition_arrowheads_are_open(self, drone_model):
        """Transitions/successions keep open (two-stroke V) heads; the
        replay fired-edge marker id stays defined and open too."""

        defs = render._arrow_defs()
        for stroke in ("#b58900", "#6c56a8", render._FIRED_STROKE):
            marker = defs.split(f'id="{render._arrow_id(stroke)}"')[1].split("</marker>")[0]
            assert f'd="M 0 1 L 9 5 L 0 9" fill="none" stroke="{stroke}"' in marker
        svg = render.to_svg(diagrams.state_diagram(drone_model.find("DeepScout::FlightStates")))
        assert 'marker-end="url(#arrow-b58900)"' in svg

    def test_typed_submachine_replay_keys_are_instance_qualified(self):
        """Two expansions of one state def must not alias in replay: while
        the simulation sits in the SOURCE-side submachine, only the
        source-side copy may match the timeline.  Every recorded track key
        and fired edge must address exactly ONE node/edge in the baked SVG
        (the double-highlight defect: definition-based keys matched every
        expansion site at once)."""

        from longeron import replay

        model = longeron.loads("""
            package P {
                state def Inner {
                    entry; then a;
                    state a;
                    transition first a accept go then b;
                    state b;
                }
                state def Outer {
                    entry; then source;
                    state source { entry; then x; state x : Inner; }
                    state dest { entry; then x; state x : Inner; }
                    transition first source accept swap then dest;
                }
            }
        """)
        svg = render.to_svg(diagrams.state_diagram(model.find("P::Outer")))
        interp = longeron.Interpreter(model)
        timeline = replay.record_timeline(interp, "P::Outer", ["go", "swap"])
        # keys are per expansion site (the simulator's dotted activation
        # paths, qualified), never the shared definition's
        assert "P::Outer::source::x::a" in timeline.tracks
        assert "P::Outer::dest::x::a" in timeline.tracks  # entered after 'swap'
        assert "P::Inner::a" not in timeline.tracks  # no aliased def key
        # every recorded state/transition addresses exactly one SVG element
        for qname in timeline.tracks:
            assert svg.count(f'data-qname="{qname}"') == 1, qname
        for fired in timeline.fired:
            key = f'data-edge="{fired.source}-&gt;{fired.target}"'
            assert svg.count(key) == 1, key
        # the source-side 'go' fired inside the SOURCE copy only
        assert (
            "P::Outer::source::x::a",
            "P::Outer::source::x::b",
        ) in {(f.source, f.target) for f in timeline.fired}

    def test_layout_produces_coordinates(self, drone_model):
        widget = diagrams.state_diagram(drone_model.find("DeepScout::FlightStates"))
        graph = render.layout(render._to_elk_json(widget.source.value))
        assert graph["width"] > 0 and graph["height"] > 0
        assert all("x" in child for child in graph["children"])

    def test_leaf_nodes_are_snug(self, drone_model):
        """Regression: leaf boxes must hug their label stack, not balloon."""

        widget = diagrams.structure_diagram(drone_model)
        graph = render.layout(render._to_elk_json(widget.source.value))

        def find(node, identifier):
            if node.get("id") == identifier:
                return node
            for child in node.get("children", []):
                found = find(child, identifier)
                if found is not None:
                    return found
            return None

        hover = find(graph, "DeepScout::HoverTime")
        assert hover is not None
        assert hover["width"] < 200  # was ~290 with ELK-guessed sizing
        assert hover["height"] < 110
        # labels carry explicit stacked positions
        ys = [label["y"] for label in hover["labels"]]
        assert ys == sorted(ys) and len(set(ys)) == len(ys)

    def test_container_wide_labels_fit(self, drone_model):
        widget = diagrams.structure_diagram(drone_model)
        graph = render.layout(render._to_elk_json(widget.source.value))

        def find(node, identifier):
            if node.get("id") == identifier:
                return node
            for child in node.get("children", []):
                found = find(child, identifier)
                if found is not None:
                    return found
            return None

        quad = find(graph, "Rotorcraft::QuadCopter")
        widest = max(label["width"] for label in quad["labels"])
        assert quad["width"] >= widest  # totalMass expression stays inside

    def test_compartment_rows_left_align(self, drone_model):
        """Regression (V2): attribute compartments left-align per UML/SysML
        convention; titles and stereotypes stay centered."""

        widget = diagrams.structure_diagram(drone_model)
        graph = render.layout(render._to_elk_json(widget.source.value))

        def find(node, identifier):
            if node.get("id") == identifier:
                return node
            for child in node.get("children", []):
                found = find(child, identifier)
                if found is not None:
                    return found
            return None

        def rows(node):
            return [
                label
                for label in node["labels"]
                if "sysml-attribute" in label["properties"]["cssClasses"]
            ]

        # leaves: attribute rows pin to the 8px margin, titles stay centered
        hover = find(graph, "DeepScout::HoverTime")
        assert {label["x"] for label in rows(hover)} == {8.0}
        title = next(lab for lab in hover["labels"] if lab["text"] == "HoverTime")
        assert title["x"] > 8.0

        # containers: attribute rows get full-width boxes, so their
        # (ELK-centered) left edges coincide
        quad = find(graph, "Rotorcraft::QuadCopter")
        quad_rows = rows(quad)
        assert len(quad_rows) >= 3
        assert len({label["x"] for label in quad_rows}) == 1
        assert len({label["width"] for label in quad_rows}) == 1

        # ... and the SVG writer start-anchors exactly those rows
        svg = render._svg_from_layout(graph)
        texts = svg.split("<text ")[1:]
        starts = [t for t in texts if 'text-anchor="start"' in t.split(">")[0]]
        assert starts
        assert any("payloadMass" in t for t in starts)
        assert not any(">QuadCopter<" in t for t in starts)  # titles stay centered

    def test_svg_carries_a_title(self, drone_model):
        """Regression (V4): exported SVGs name their subject."""

        svg = render.to_svg(drone_model.find("DeepScout::FlightStates"))
        assert "<title>DeepScout::FlightStates</title>" in svg
        # pre-built widgets recover the name from the node qualified names
        svg = render.to_svg(diagrams.state_diagram(drone_model.find("DeepScout::FlightStates")))
        assert "<title>DeepScout::FlightStates</title>" in svg
        # whole models are named by their source
        svg = render.to_svg(drone_model)
        assert "<title>" in svg

    def test_edges_attach_to_boxes(self):
        """Regression: elkjs re-containers edges (its `container` field) and
        emits their coordinates relative to that node; honoring it makes
        arrows meet the boxes they connect."""

        model = longeron.loads("""
            package P {
                state def M {
                    entry; then outer;
                    state outer {
                        entry; then a;
                        state a;
                        transition first a accept go then b;
                        state b;
                    }
                }
            }
        """)
        widget = diagrams.state_diagram(model.find("P::M"))
        graph = render.layout(render._to_elk_json(widget.source.value))
        inner = [e for e in graph.get("edges", []) if e.get("container", "").endswith("::outer")]
        assert inner, "expected inner edges re-containered by elkjs"

        # compute absolute geometry and check each inner edge's endpoints
        origins: dict = {}
        boxes: dict = {}

        def index(node, ox, oy):
            x, y = ox + node.get("x", 0), oy + node.get("y", 0)
            origins[node["id"]] = (x, y)
            boxes[node["id"]] = (x, y, node.get("width", 0), node.get("height", 0))
            for child in node.get("children", []):
                index(child, x, y)

        index(graph, 0, 0)
        for edge in inner:
            ox, oy = origins[edge["container"]]
            section = edge["sections"][0]
            for point, endpoint in (
                (section["startPoint"], edge["sources"][0]),
                (section["endPoint"], edge["targets"][0]),
            ):
                px, py = ox + point["x"], oy + point["y"]
                bx, by, bw, bh = boxes[endpoint]
                assert bx - 1 <= px <= bx + bw + 1, f"edge endpoint x={px} misses box {endpoint}"
                assert by - 1 <= py <= by + bh + 1, f"edge endpoint y={py} misses box {endpoint}"

    def test_escaping(self):
        model = longeron.loads('package P { part def A { attribute note : String = "<b>&"; } }')
        svg = render.to_svg(diagrams.structure_diagram(model))
        assert "&lt;b&gt;&amp;" in svg


_PORTED = """
package P {
    item def Item1;
    part def Part1;
    part def Part2;
    port def Pin { in item x : Item1; }
    port def Pout { out item y : Item1; }
    connection def ConnectionDef2 {
        end [1..1] part sourceEnd : Part1;
        end [1..*] part targetEnd : Part2;
    }
    part part0 {
        part part1 : Part1 { port po : Pout; }
        part part2 : Part2 { port pc : ~Pin; }
        interface if1 connect part1.po to part2.pc;
        connection connection2 : ConnectionDef2 connect part1 to part2;
        flow of Item1 from part1.po to part2.pc;
    }
}
"""


def _rect_geometry(svg: str, qname: str) -> tuple[float, float, float, float]:
    import re

    match = re.search(
        rf'<rect data-qname="{re.escape(qname)}" x="([\d.]+)" y="([\d.]+)" '
        rf'width="([\d.]+)" height="([\d.]+)"',
        svg,
    )
    assert match is not None, f"no rect for {qname}"
    return tuple(float(g) for g in match.groups())  # type: ignore[return-value]


class TestTranche3Svg:
    """Boundary ports + the remaining connector/annotation notation
    (spec Ports printed p.59; Connections pp.66-67; Allocations p.79;
    Packages p.24; Comments pp.20-21) -- headless pipeline."""

    @pytest.fixture(scope="class")
    def ported_svg(self):
        return render.to_svg(diagrams.structure_diagram(longeron.loads(_PORTED)))

    def test_port_squares_straddle_the_owner_border(self, ported_svg):
        """Geometry per the spec figures: the square's center sits ON the
        owning node's border (out ports pin EAST here)."""

        px, py, pw, ph = _rect_geometry(ported_svg, "P::part0::part1::po")
        ox, oy, ow, oh = _rect_geometry(ported_svg, "P::part0::part1")
        assert pw == ph == 10.0
        assert px + pw / 2 == pytest.approx(ox + ow, abs=0.5)  # ON the east border
        assert oy <= py + ph / 2 <= oy + oh  # riding the border, not a corner
        # the owner's stroke colors the square; the body stays white
        assert f'fill="#ffffff" stroke="{render._NODE_STYLES["sysml-usage"]["stroke"]}"' in (
            ported_svg.split('data-qname="P::part0::part1::po"')[1].split("/>")[0] + "/>"
        )

    def test_direction_arrows_and_conjugated_labels(self, ported_svg):
        # 'out' arrows inside po's and pc's squares (conjugated 'in' flips
        # to out on pc), drawn for the EAST border they ride: the arrow
        # points OUT of the node from that side
        assert ported_svg.count(f'<path d="{render._port_arrow_d("out", side="EAST")}"') == 2
        # conjugation stays textual: ~ in the label, square unshaded
        assert ">pc : ~Pin</text>" in ported_svg
        assert ">po : Pout</text>" in ported_svg

    def test_interface_edges_run_port_to_port(self, ported_svg):
        graph = render._to_elk_json(
            diagrams.structure_diagram(longeron.loads(_PORTED)).source.value
        )

        def edges(node):
            yield from node.get("edges", [])
            for child in node.get("children", []):
                yield from edges(child)

        interface = [
            e for e in edges(graph) if "sysml-edge-connect" in e["properties"]["cssClasses"]
        ]
        assert [(e["sources"], e["targets"]) for e in interface] == [
            (["P::part0::part1::po"], ["P::part0::part2::pc"])
        ]
        # identity stays with the owning nodes (the replay contract)
        assert interface[0]["properties"]["sourceNode"] == "P::part0::part1"

    def test_port_attached_flows_keep_only_the_filled_head(self, ported_svg):
        flow = ported_svg.split('marker-end="url(#arrow-filled-555555)"')
        assert len(flow) == 2  # exactly one port-attached flow edge
        group = flow[0].rsplit("<g ", 1)[1]
        assert "marker-start" not in group  # the drawn square IS the pin
        defs = ported_svg.split("</defs>")[0]
        filled = defs.split('id="arrow-filled-555555"')[1].split("</marker>")[0]
        assert 'fill="#555555"' in filled and 'stroke="none"' in filled

    def test_directed_connection_draws_open_head_and_label(self, ported_svg):
        # the directed connect, the interface and the flow all share the
        # owning-node data-edge key: find the group carrying the label
        groups = [
            part.split("</g>")[0]
            for part in ported_svg.split("<g data-edge=")[1:]
            if "connection2 : ConnectionDef2" in part.split("</g>")[0]
        ]
        assert len(groups) == 1
        assert 'marker-end="url(#arrow-555555)"' in groups[0]
        assert "dasharray" not in groups[0]  # a solid connector line

    def test_nary_connection_junction_dot(self):
        model = longeron.loads("""
            package P {
                part def ConnectionDef1;
                part part1; part part2; part part3;
                connection connection1 : ConnectionDef1
                    connect (part1, part2, part3);
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        _x, _y, w, h = _rect_geometry(svg, "P::connection1")
        assert (w, h) == (render._JUNCTION_SIZE, render._JUNCTION_SIZE)
        junction = svg.split('data-qname="P::connection1"')[1].split("/>")[0]
        assert 'fill="#555555"' in junction  # the filled connector-gray dot
        assert "connection1 : ConnectionDef1" in svg  # label beside the dot
        spokes = [part for part in svg.split("<g data-edge=") if "P::connection1" in part[:70]]
        assert len(spokes) == 3

    def test_proxy_connection_dots(self):
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
        svg = render.to_svg(diagrams.structure_diagram(model))
        # two filled balls in the owning usage green, residual-path labels
        usage_stroke = render._NODE_STYLES["sysml-usage"]["stroke"]
        assert svg.count(f'fill="{usage_stroke}" stroke="none"/>') == 2
        assert ">.part4</text>" in svg and ">.part5</text>" in svg
        # the connector runs dot-to-dot; identity stays with the nodes
        assert 'data-edge="P::part1::part2-&gt;P::part1::part3"' in svg

    def test_allocate_keyword_edge(self):
        model = longeron.loads("""
            package P {
                part part1; part part2;
                allocate part1 to part2;
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model))
        group = svg.split('data-edge="P::part1-&gt;P::part2"')[1].split("</g>")[0]
        assert 'marker-end="url(#arrow-a85c78)"' in group
        assert "\u00aballocate\u00bb" in group
        assert "dasharray" not in group  # solid keyword-arrow family line

    def test_package_tab(self):
        model = longeron.loads("package Package1 { part def A; }")
        svg = render.to_svg(diagrams.structure_diagram(model))
        px, py, _w, _h = _rect_geometry(svg, "Package1")
        style = render._NODE_STYLES["sysml-package"]
        tab = (
            f'<rect x="{px:.1f}" y="{py - render._TAB_HEIGHT:.1f}" '
            f'width="{render._TAB_WIDTH:.1f}" height="{render._TAB_HEIGHT:.1f}" '
            f'fill="{style["fill"]}" stroke="{style["stroke"]}"/>'
        )
        # flush with the box's top-left corner (tab bottom ON the box top,
        # left edges aligned) AND in the package palette -- one continuous
        # folder silhouette, never a default-gray rectangle
        assert tab in svg
        # a NESTED package restates the label spacing for its level, so
        # its tab stays flush too
        nested = longeron.loads("package Outer { package Inner { part def A; } }")
        svg = render.to_svg(diagrams.structure_diagram(nested))
        for name in ("Outer", "Outer::Inner"):
            px, py, _w, _h = _rect_geometry(svg, name)
            assert f'<rect x="{px:.1f}" y="{py - render._TAB_HEIGHT:.1f}" ' in svg, (
                name
            )  # tab bottom edge exactly on the box top edge

    def test_definitions_draw_square_corners(self):
        model = longeron.loads("package P { part def A; part a : A; }")
        svg = render.to_svg(diagrams.structure_diagram(model))
        definition = svg.split('data-qname="P::A"')[1].split("/>")[0]
        assert 'rx="0"' in definition
        usage = svg.split('data-qname="P::a"')[1].split("/>")[0]
        assert 'rx="4"' in usage

    def test_notes_and_anchors_opt_in(self):
        model = longeron.loads("""
            package P {
                part def Part1;
                comment about Part1 /* The annotated element is Part1. */
            }
        """)
        plain = render.to_svg(diagrams.structure_diagram(model))
        assert "\u00abcomment\u00bb" not in plain  # default OFF
        svg = render.to_svg(diagrams.structure_diagram(model, annotations=True))
        assert "\u00abcomment\u00bb" in svg
        assert "The annotated element is Part1." in svg
        # folded corner: the note polygon + its crease
        note_style = render._NODE_STYLES["sysml-note"]
        assert f'fill="{note_style["fill"]}" stroke="{note_style["stroke"]}"' in svg
        anchors = [
            part.split("</g>")[0]
            for part in svg.split("<g data-edge=")[1:]
            if 'stroke-dasharray="4 2"' in part.split("</g>")[0]
        ]
        assert len(anchors) == 1 and "P::Part1" in anchors[0]
        assert "marker" not in anchors[0]  # anchors carry NO endpoint glyph

    def test_portless_diagrams_take_the_pre_port_path(self, drone_model):
        """Layout-stability proof: a model without ports/annotations feeds
        elkjs an input with zero port artifacts -- nothing about the port
        machinery can perturb it."""

        graph = render._to_elk_json(diagrams.structure_diagram(drone_model).source.value)

        def walk(node):
            yield node
            for child in node.get("children", []):
                yield from walk(child)

        for node in walk(graph):
            assert "ports" not in node
            options = node.get("layoutOptions", {})
            assert "elk.portConstraints" not in options
            assert "elk.portLabels.placement" not in options


def _origins(graph):
    """Absolute origin of every node (elkjs emits child/edge coordinates
    relative to their parent/container)."""

    origins = {}

    def index(node, ox=0.0, oy=0.0):
        x, y = ox + node.get("x", 0), oy + node.get("y", 0)
        origins[str(node.get("id"))] = (x, y)
        for child in node.get("children", []):
            index(child, x, y)

    index(graph)
    return origins


def _walk_json(node):
    yield node
    for child in node.get("children", []):
        yield from _walk_json(child)


class TestGalleryNits:
    """Geometric proofs for the notation-gallery review fixes (nits 1-5):
    junction convergence, badge insets, and arrowhead-reach clearance."""

    def _junction_endpoint_distances(self, widget, junction_id):
        """Distances of every junction-spoke endpoint from the dot center."""

        graph = render.layout(render._to_elk_json(widget.source.value))
        origins = _origins(graph)
        node = next(n for n in _walk_json(graph) if n["id"] == junction_id)
        ox, oy = origins[junction_id]
        cx, cy = ox + node["width"] / 2, oy + node["height"] / 2
        distances = []
        for owner in _walk_json(graph):
            for edge in owner.get("edges", []):
                props = edge.get("properties", {})
                for tag, key in (("startPoint", "sourceNode"), ("endPoint", "targetNode")):
                    if props.get(key) != junction_id:
                        continue
                    eox, eoy = origins.get(str(edge.get("container")), origins[owner["id"]])
                    for section in edge.get("sections", []):
                        point = section[tag]
                        distances.append(math.hypot(eox + point["x"] - cx, eoy + point["y"] - cy))
        return distances

    def test_junction_spokes_converge_at_the_dot_center(self):
        """Nit 2: edges left/entered the junction dot at scattered boundary
        points -- lines visibly not meeting.  Every spoke endpoint now sits
        AT the dot's center (within its radius, in fact exactly on it), so
        the fan radiates from the dot like the spec crops (printed pp.19,
        66); replay identity stays node-qualified."""

        radius = render._JUNCTION_SIZE / 2
        nary = longeron.loads("""
            package P {
                part def ConnectionDef1;
                part part1; part part2; part part3;
                connection connection1 : ConnectionDef1
                    connect (part1, part2, part3);
            }
        """)
        widget = diagrams.structure_diagram(nary)
        distances = self._junction_endpoint_distances(widget, "P::connection1")
        assert len(distances) == 3
        assert all(d <= radius for d in distances)
        assert all(d < 0.01 for d in distances)  # exactly the center
        # the 3-client / 2-supplier n-ary dependency specimen
        deps = longeron.loads("""
            package P {
                part a; part b; part c; part s; part t;
                dependency Multi from a, b, c to s, t;
            }
        """)
        widget = diagrams.structure_diagram(deps)
        distances = self._junction_endpoint_distances(widget, "P::Multi")
        assert len(distances) == 5
        assert all(d < 0.01 for d in distances)
        # data-edge keys keep the replay contract (node ids, never ports)
        svg = render.to_svg(widget)
        assert 'data-edge="P::a-&gt;P::Multi"' in svg
        assert 'data-edge="P::Multi-&gt;P::t"' in svg

    def test_badge_boxes_pin_identical_geometry_in_both_pipelines(self):
        """Nit 3: in the browser, ELK put the badge at the raw corner
        (outside the rounded-corner arc) and centered the keyword row over
        it.  The accept/send box is now fully pinned: the ELK JSON labels
        carry exactly the coordinates diagrams computed (which the browser
        receives verbatim -- pinned labels are left untouched by elkjs),
        the badge clears the corner radius, and the keyword row starts
        below the badge strip."""

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
        elements = {n.id: n for n in _walk_children(widget.source.value) if n.id}
        graph = render.layout(render._to_elk_json(widget.source.value))
        rx_corner_radius = 6.0  # sysml-step rx (render._NODE_STYLES)
        for name in ("P::Chat::rx", "P::Chat::tx"):
            node = next(n for n in _walk_json(graph) if n["id"] == name)
            badge, stereotype, title = node["labels"]
            # badge bbox inside the node bbox minus the corner radius
            assert badge["x"] >= rx_corner_radius
            assert badge["x"] + badge["width"] <= node["width"] - 0  # inside
            assert badge["y"] >= 0 and badge["y"] + badge["height"] <= node["height"]
            # ... and clear of the corner arc: its top-left corner lies
            # inside the arc circle centered (rx, rx)
            dx = badge["x"] - rx_corner_radius
            dy = badge["y"] - rx_corner_radius
            assert badge["x"] >= rx_corner_radius or math.hypot(dx, dy) <= rx_corner_radius
            # no overlap with the keyword/stereotype row
            assert stereotype["y"] >= badge["y"] + badge["height"]
            assert title["y"] >= stereotype["y"] + stereotype["height"]
            # the geometry in the ELK JSON is EXACTLY what the element tree
            # ships to the browser (pinned labels, fixed box)
            element = elements[name]
            assert (node["width"], node["height"]) == (element.width, element.height)
            for entry, label in zip(node["labels"], element.labels, strict=True):
                assert (entry["x"], entry["y"]) == (label.x, label.y)
                assert label.layoutOptions == {"nodeLabels.placement": ""}

    def test_no_bend_falls_within_an_arrowheads_reach(self):
        """Nit 5: inside compound nodes elkjs spaced edge channels 10px
        from the node border (layered spacing does not inherit through
        INCLUDE_CHILDREN), so the last bend sat under the 10px triangle:
        the shaft entered the head's side and the colon dots floated off
        the turned line.  With the clearance restated per level, every
        hollow-family edge keeps a straight final run at least as long as
        its head's reach (the gallery's annotated-Pump model is the
        repro)."""

        model = longeron.loads("""
            package Annotated {
                metadata def Safety;
                part def Pump { attribute pressure : Real; }
                @Safety about Pump;
                comment about Pump /* Centrifugal, oil-free. */
                part pump : Pump { doc /* The unit under review. */ }
            }
        """)
        widget = diagrams.structure_diagram(model, annotations=True)
        graph = render.layout(render._to_elk_json(widget.source.value))
        checked = 0
        for owner in _walk_json(graph):
            for edge in owner.get("edges", []):
                css = edge.get("properties", {}).get("cssClasses", "")
                end = render._edge_end(css)
                if not end.startswith("hollow"):
                    continue
                reach = render._HEAD_LENGTH + render._ADORN_TAIL[end]
                assert render._EDGE_END_CLEARANCE >= reach  # the guarantee
                for section in edge.get("sections", []):
                    points = [
                        section["startPoint"],
                        *section.get("bendPoints", []),
                        section["endPoint"],
                    ]
                    if len(points) < 3:
                        continue  # straight edges cannot bend under the head
                    last = math.hypot(
                        points[-1]["x"] - points[-2]["x"],
                        points[-1]["y"] - points[-2]["y"],
                    )
                    assert last >= reach, (css, last, reach)
                    checked += 1
        assert checked  # the repro really produced a bent hollow-family edge

    def test_done_core_draws_pure_fill_headless(self):
        """Nit 4 (headless side): the bullseye core is explicit
        stroke=none, so no SVG consumer can inherit an outline onto it."""

        model = longeron.loads("""
            package P {
                action def Flow { action a; first start then a; first a then done; }
            }
        """)
        svg = render.to_svg(diagrams.action_diagram(model.find("P::Flow")))
        groups = [g.split("</g>")[0] for g in svg.split("<g data-qname=")[1:]]
        bullseye = next(g for g in groups if g.count("<circle") == 2)
        core = bullseye.split("<circle")[2]
        assert 'stroke="none"' in core


def _edges_json(node):
    for owner in _walk_json(node):
        yield from owner.get("edges", [])


_GALLERY_PROXIES = """
package Proxies {
    part def Part2 { part part4; }
    part def Part3 { part part5; }
    part part1 {
        part part2 : Part2;
        part part3 : Part3;
        connect part2.part4 to part3.part5;
    }
}
"""

_GALLERY_PORTFLOW = """
package PortFlows {
    item def Item1;
    port def Pout { out item y : Item1; }
    part part0 {
        part part1 { port po : Pout; }
        part part2 { port pc : ~Pout; }
        flow of item1 : Item1 from part1.po to part2.pc;
    }
}
"""


class TestGalleryNits2:
    """Geometric proofs for the round-2 notation-gallery review fixes:
    port/proxy labels INSIDE their boxes, side-relative direction arrows,
    the spec-faithful port-attached flow figure, the note crease, and
    marker survival on non-orthogonal edge routing."""

    def _label_boxes_inside(self, source: str, owner_id: str) -> None:
        """Every drawn-port label of ``owner_id`` sits fully INSIDE the
        owner's bbox after a real elkjs layout."""

        graph = render.layout(
            render._to_elk_json(diagrams.structure_diagram(longeron.loads(source)).source.value)
        )
        owner = next(n for n in _walk_json(graph) if n["id"] == owner_id)
        checked = 0
        for port in owner.get("ports", []):
            if not port.get("properties", {}).get("cssClasses"):
                continue
            for label in port.get("labels", []):
                lx = port["x"] + label["x"]
                ly = port["y"] + label["y"]
                assert 0 <= lx and lx + label["width"] <= owner["width"], (owner_id, label)
                assert 0 <= ly and ly + label["height"] <= owner["height"], (owner_id, label)
                checked += 1
        assert checked

    def test_proxy_labels_sit_inside_the_part_boxes(self):
        """Nit 1: the residual-path labels (.part4/.part5) render INSIDE
        the containing part boxes, adjacent to the proxy dot -- exactly
        where spec-p98-proxy-connection.png writes them."""

        self._label_boxes_inside(_GALLERY_PROXIES, "Proxies::part1::part2")
        self._label_boxes_inside(_GALLERY_PROXIES, "Proxies::part1::part3")

    def test_port_labels_sit_inside_the_part_boxes(self):
        """Nit 3 companion: ``name : Type`` port labels live inside the
        part bodies (spec pp.75/77 figures), leaving the flow line's strip
        to the payload labels."""

        self._label_boxes_inside(_GALLERY_PORTFLOW, "PortFlows::part0::part1")
        self._label_boxes_inside(_GALLERY_PORTFLOW, "PortFlows::part0::part2")

    def test_port_flow_matches_the_spec_figure(self):
        """Nit 3 (spec-p108 / Table 14 flow row): the flow line runs port
        square to port square, STRAIGHT between the facing borders, with
        the item label riding the line near each end and the filled head
        AT the target port square (no source pin marker)."""

        widget = diagrams.structure_diagram(longeron.loads(_GALLERY_PORTFLOW))
        graph = render.layout(render._to_elk_json(widget.source.value))
        flow = next(
            e for e in _edges_json(graph) if "sysml-edge-portflow" in e["properties"]["cssClasses"]
        )
        # square-to-square: the endpoints are the port ids
        assert flow["sources"] == ["PortFlows::part0::part1::po"]
        assert flow["targets"] == ["PortFlows::part0::part2::pc"]
        # straight between the facing borders: one section, no bends
        (section,) = flow["sections"]
        assert not section.get("bendPoints")
        assert section["startPoint"]["y"] == pytest.approx(section["endPoint"]["y"], abs=0.5)
        # payload labels near BOTH ends, Table-14 text
        assert [label["text"] for label in flow["labels"]] == [
            "item1 : Item1",
            "item1 : Item1",
        ]
        svg = render.to_svg(widget)
        group = svg.split('data-edge="PortFlows::part0::part1-&gt;PortFlows::part0::part2"')[1]
        group = group.split("</g>")[0]
        assert 'marker-end="url(#arrow-filled-555555)"' in group
        assert "marker-start" not in group  # the drawn square IS the pin

    def test_conjugated_receiving_port_arrow_points_into_the_node(self):
        """Nit 4: ``pc : ~Pout`` receives the flow, so its square draws
        the IN arrow -- pointing INTO part2 from the WEST border it rides
        (spec p.77's own example receives on the conjugated end)."""

        widget = diagrams.structure_diagram(longeron.loads(_GALLERY_PORTFLOW))
        root = widget.source.value

        def find(node_id):
            stack = [root]
            while stack:
                node = stack.pop()
                if node.id == node_id:
                    return node
                stack.extend(node.children)
            raise AssertionError(node_id)

        pc = next(p for p in find("PortFlows::part0::part2").ports if p.id.endswith("::pc"))
        assert "sysml-port-in" in pc.properties.cssClasses
        assert pc.layoutOptions["elk.port.side"] == "WEST"
        assert pc.properties.shape.use == "port-in-west"
        svg = render.to_svg(widget)
        assert f'<path d="{render._port_arrow_d("in", side="WEST")}"' in svg

    def test_in_arrow_points_at_the_interior_from_every_side(self):
        """Nit 4 (side-relative glyphs): the headless renderer derives the
        arrow orientation from the border the port actually LANDED on --
        an in-port square drawn on the east/north/south border still
        points INTO the node, never absolutely +x."""

        size = render._PORT_SIZE
        graph = {
            "id": "root",
            "width": 200.0,
            "height": 200.0,
            "children": [
                {
                    "id": "box",
                    "x": 50.0,
                    "y": 50.0,
                    "width": 100.0,
                    "height": 100.0,
                    "properties": {"cssClasses": "sysml-usage"},
                    "ports": [
                        {
                            "id": f"p-{side}",
                            "x": px,
                            "y": py,
                            "width": size,
                            "height": size,
                            "properties": {"cssClasses": "sysml-port sysml-port-in"},
                        }
                        for side, px, py in (
                            ("west", -size / 2, 45.0),
                            ("east", 100.0 - size / 2, 45.0),
                            ("north", 45.0, -size / 2),
                            ("south", 45.0, 100.0 - size / 2),
                        )
                    ],
                }
            ],
        }
        svg = render._svg_from_layout(graph)
        for side in ("WEST", "EAST", "NORTH", "SOUTH"):
            assert f'<path d="{render._port_arrow_d("in", size, side)}"' in svg
        # and the four orientations really differ pairwise
        arrows = {
            render._port_arrow_d("in", size, side) for side in ("WEST", "EAST", "NORTH", "SOUTH")
        }
        assert len(arrows) == 4

    def test_sided_arrow_geometry(self):
        """The parametric glyph: 'in' tips toward the interior, 'out' away,
        'inout' both ways; W/E draw horizontal shafts, N/S vertical."""

        def head_x(d):  # x of the arrow tip (the middle point of the barbs)
            return float(d.split(" L ")[1].split(",")[0])

        legacy_in = render._port_arrow_d("in")
        assert render._port_arrow_d("in", side="WEST") == legacy_in  # unchanged default
        assert head_x(render._port_arrow_d("in", side="WEST")) > head_x(
            render._port_arrow_d("in", side="EAST")
        )
        assert render._port_arrow_d("out", side="EAST") == render._port_arrow_d(
            "in", side="WEST"
        )  # both point +x: in through a west border, out through an east one
        vertical = render._port_arrow_d("in", side="NORTH")
        assert vertical != legacy_in and "M 5,2.5 L 5,7.5" in vertical  # vertical shaft
        inout = render._port_arrow_d("inout", side="EAST")
        assert inout.count(" M ") == 2  # shaft + two heads

    def test_polyline_routing_keeps_the_markers(self):
        """Nit 2 proof (headless): the gallery's specialization model laid
        out with POLYLINE routing produces genuinely diagonal edges whose
        hollow-triangle markers stay attached -- SVG markers auto-orient
        (orient="auto-start-reverse"), so the head aligns with the
        diagonal shaft instead of a lost orthogonal stub."""

        model = longeron.loads("""
            package Specializations {
                part def Machine;
                part def Vehicle :> Machine;
                part def Car :> Machine;
                part def Truck :> Machine;
                part car1 : Car;
            }
        """)
        widget = diagrams.structure_diagram(model, routing="polyline")
        graph = render.layout(render._to_elk_json(widget.source.value))
        diagonal = 0
        for edge in _edges_json(graph):
            if "sysml-packing" in edge["properties"]["cssClasses"]:
                continue
            for section in edge.get("sections", []):
                points = [
                    section["startPoint"],
                    *section.get("bendPoints", []),
                    section["endPoint"],
                ]
                first, last = points[-2], points[-1]
                if abs(first["x"] - last["x"]) > 1 and abs(first["y"] - last["y"]) > 1:
                    diagonal += 1
        assert diagonal  # polyline really produced non-orthogonal entries
        svg = render._svg_from_layout(graph)
        blue = render._EDGE_STYLES["sysml-edge-specializes"]["stroke"]
        marker_id = render._marker_id("hollow", blue)
        assert f'marker-end="url(#{marker_id})"' in svg
        defs = svg.split("</defs>")[0]
        marker = defs.split(f'id="{marker_id}"')[1].split("</marker>")[0]
        assert 'orient="auto-start-reverse"' in marker  # rotates with the shaft

    def test_note_crease_drawn_headless(self):
        """Nit 5 (headless side): the note draws the folded-corner
        pentagon PLUS the crease 'L' (fold line down, then out to the
        right edge), stroked like the outline."""

        import re

        model = longeron.loads("""
            package P {
                part def Part1;
                comment about Part1 /* The annotated element is Part1. */
            }
        """)
        svg = render.to_svg(diagrams.structure_diagram(model, annotations=True))
        note_style = render._NODE_STYLES["sysml-note"]
        group = next(  # the note's <g>: polygon in the note palette
            part.split("</g>")[0]
            for part in svg.split("<g data-qname=")[1:]
            if f'fill="{note_style["fill"]}" stroke="{note_style["stroke"]}"' in part
        )
        polygon = re.search(r'<polygon points="([^"]+)"', group)
        assert polygon is not None
        corners = [tuple(map(float, pair.split(","))) for pair in polygon.group(1).split()]
        assert len(corners) == 5  # the cut corner
        crease = re.search(
            r'<path d="M ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+)" '
            rf'fill="none" stroke="{note_style["stroke"]}"',
            group,
        )
        assert crease is not None
        x1, y1, x2, y2, x3, y3 = (float(v) for v in crease.groups())
        # the 'L': down the fold from the top edge, then right to the cut
        assert (x1, y1) == corners[1]  # starts at the fold's top corner
        assert x2 == x1 and y2 > y1  # first stroke straight down
        assert (x3, y3) == corners[2] and y3 == y2  # second stroke to the edge


_DIRECTION_CHAIN = """
package Chain {
    part def A;
    part def B :> A;
    part def C :> B;
}
"""

_DIRECTION_NESTED = """
package Outer {
    part def A;
    part def B :> A;
    package Inner {
        part def X;
        part def Y :> X;
        part def Z :> Y;
    }
}
"""

_DIRECTION_LOOSE = """
package Loose {
    part def A; part def B; part def C;
    part def D; part def E; part def F;
}
"""

_WIDE_GRID_COMPOUND = """
package Fit {
    part def Wide {
        attribute totalMass : Real = chassis.mass + battery.mass + 4.0 * 0.06 + payloadMass;
        part a;
        part b;
    }
}
"""


class TestGalleryNits3:
    """Round-3 gallery review: the layout-direction toggle, pinned against
    the REAL vendored elkjs (the browser worker wraps the same engine)."""

    @staticmethod
    def _positions(source: str, **kwargs):
        widget = diagrams.structure_diagram(longeron.loads(source), **kwargs)
        graph = render.layout(render._to_elk_json(widget.source.value))
        return {
            node["id"]: (node.get("x", 0.0), node.get("y", 0.0))
            for node in _walk_json(graph)
            if node.get("id") and not str(node["id"]).startswith("__lgn__")
        }

    def test_direction_flips_the_flow(self):
        """The same chain lays out left-to-right by default and
        top-to-bottom under direction='down' -- the headless evidence for
        the toolbar toggle (nits3-direction-*.png)."""

        chain = ("Chain::C", "Chain::B", "Chain::A")  # specialization order
        right = self._positions(_DIRECTION_CHAIN)
        xs, ys = zip(*(right[name] for name in chain), strict=True)
        assert xs[0] < xs[1] < xs[2]  # layers march right ...
        assert max(ys) - min(ys) < 1.0  # ... on one horizontal rank
        down = self._positions(_DIRECTION_CHAIN, direction="down")
        xs, ys = zip(*(down[name] for name in chain), strict=True)
        assert ys[0] < ys[1] < ys[2]  # layers march down ...
        assert max(xs) - min(xs) < 1.0  # ... in one vertical column

    def test_root_only_direction_reaches_nested_compounds(self):
        """The INCLUDE_CHILDREN empirical pin: elk.direction set on the
        ROOT alone (diagrams never restate it per level -- see
        TestDirectionToggle.test_direction_is_root_only) flows into
        nested compounds, unlike the spacing/edgeRouting options that
        needed per-level restating."""

        down = self._positions(_DIRECTION_NESTED, direction="down")
        inner = [down[f"Outer::Inner::{name}"] for name in ("Z", "Y", "X")]
        xs, ys = zip(*inner, strict=True)
        assert ys[0] < ys[1] < ys[2]  # the NESTED chain stacks vertically
        assert max(xs) - min(xs) < 1.0

    def test_pack_grids_keep_their_wide_flow_under_down(self):
        """The SEPARATE_CHILDREN packing grids run their own sub-layout:
        a package of disconnected members packs into the same wide grid
        whichever way the diagram flows (the pack-aspect chains assume
        rows, and elkjs leaves isolated sub-layouts at their default
        direction)."""

        def grid(kwargs):
            widget = diagrams.structure_diagram(longeron.loads(_DIRECTION_LOOSE), **kwargs)
            graph = render.layout(render._to_elk_json(widget.source.value))
            package = next(n for n in _walk_json(graph) if n.get("id") == "Loose")
            return {
                child["id"]: (child.get("x", 0.0), child.get("y", 0.0))
                for child in package.get("children", [])
            }

        assert grid({}) == grid({"direction": "down"})


class TestCompoundLabelFit:
    """No compartment label may overflow its node -- in EITHER direction,
    pinned against the REAL vendored elkjs (the maintainer repro:
    QuadCopter's ``totalMass`` row past the border after a top-down
    toggle).  elkjs 0.9.3 sizes an EXPANDED compound node under a
    vertical flow in its internal horizontal coordinates: the
    ``NODE_LABELS`` width contribution lands on the HEIGHT while the
    width collapses to children + padding (leaves are sized after the
    transposition -- collapsing the node made the rows fit).  Both
    pipelines counter it the same way: drop the transposed label
    contribution and pin the width through the swapped
    ``elk.nodeSize.minimum`` (``render._to_elk_json`` headless,
    ``toolbar._fit_compound_labels`` for the widget tree)."""

    @staticmethod
    def _compound_label_overflows(graph) -> list[tuple]:
        """INSIDE labels poking past their COMPOUND node's box (leaves are
        snug-sized around their widest row by construction)."""

        overflows = []
        for node in _walk_json(graph):
            if not node.get("children"):
                continue
            for label in node.get("labels", []):
                placement = (label.get("layoutOptions") or {}).get("nodeLabels.placement", "")
                if "OUTSIDE" in placement:
                    continue  # package tabs ride above the box
                if label["x"] < -0.01 or label["x"] + label["width"] > node["width"] + 0.01:
                    overflows.append((node["id"], label["text"], label["x"], node["width"]))
        return overflows

    @pytest.mark.parametrize("direction", ["right", "down"])
    def test_compartment_rows_fit_expanded_compounds(self, drone_model, direction):
        widget = diagrams.structure_diagram(drone_model, direction=direction)
        graph = render.layout(render._to_elk_json(widget.source.value))
        assert self._compound_label_overflows(graph) == []

    @pytest.mark.parametrize("direction", ["right", "down"])
    def test_rows_fit_a_packing_grid_compound(self, direction):
        """A compound whose loose children make IT the packing grid
        (``SEPARATE_CHILDREN`` on the node itself) is sized by its OWN
        horizontal sub-run whatever the root flow -- it must keep the
        horizontal ``NODE_LABELS`` sizing, not the swapped minimum (the
        swap would land on the wrong axis of the wrong run)."""

        model = longeron.loads(_WIDE_GRID_COMPOUND)
        widget = diagrams.structure_diagram(model, direction=direction)
        graph = render.layout(render._to_elk_json(widget.source.value))
        assert self._compound_label_overflows(graph) == []

    def test_down_keeps_the_compound_height_content_driven(self, drone_model):
        """The same transposition also inflated the compound's HEIGHT by
        the widest row's WIDTH (a huge blank band under the children);
        dropping NODE_LABELS under vertical flows keeps the box snug."""

        widget = diagrams.structure_diagram(drone_model, direction="down")
        graph = render.layout(render._to_elk_json(widget.source.value))
        quad = next(n for n in _walk_json(graph) if n["id"] == "Rotorcraft::QuadCopter")
        rows = max(label["width"] for label in quad["labels"])
        assert quad["width"] >= rows  # the fix: rows drive the width ...
        assert quad["height"] < rows  # ... and never the height

    def test_package_nested_compound_rows_stay_inside_under_down(self):
        """The maintainer's second repro (the mission catalog, the retired
        model-explorer notebook): a part def
        with children AND very wide rows nested INSIDE a package.  Under
        the un-fixed top-down transposition its width collapsed to
        children + padding while the H_CENTERed full-width rows poked
        ~900px LEFT of the box -- a glob of text over the package's
        top-left corner.  ``max_label_width=None`` keeps the rows at
        full width, so this pins the fit itself (not the row cap)."""

        model = longeron.loads(_PACKAGE_GLOB)
        widget = diagrams.structure_diagram(model, direction="down", max_label_width=None)
        graph = render.layout(render._to_elk_json(widget.source.value))
        assert self._compound_label_overflows(graph) == []
        mission = next(n for n in _walk_json(graph) if n["id"] == "Missions::Logistics")
        rows = max(label["width"] for label in mission["labels"])
        assert rows > 480  # uncapped: the row really is absurd
        assert mission["width"] >= rows


_PACKAGE_GLOB = """
package Missions {
    part def Logistics {
        attribute outboundPowerW : Real = basePowerW + cargo.bayMass * airframe.dragArea
            * airframe.cruiseSpeed * airframe.cruiseSpeed / (props.cruiseEff * motors.efficiency)
            + battery.energyWh * battery.usableFraction - avionics.powerW;
        part cargo;
    }
}
"""


class TestRowCapTooltips:
    """The ``max_label_width`` cap's render-side half: truncated rows carry
    their full text as ``properties.tooltip``, which the headless SVG
    writer emits as the label's ``<title>`` (the browser view renders the
    same element; tests/browser/test_browser_label_fit.py asserts it
    against the live DOM)."""

    def test_capped_rows_keep_the_node_narrow(self):
        model = longeron.loads(_PACKAGE_GLOB)
        widget = diagrams.structure_diagram(model)  # default cap: 480
        graph = render.layout(render._to_elk_json(widget.source.value))
        mission = next(n for n in _walk_json(graph) if n["id"] == "Missions::Logistics")
        assert mission["width"] <= 480 + 20  # widest row + box side padding

    def test_truncated_rows_title_the_full_text(self):
        model = longeron.loads(_PACKAGE_GLOB)
        widget = diagrams.structure_diagram(model)
        graph = render.layout(render._to_elk_json(widget.source.value))
        svg = render._svg_from_layout(graph)
        assert "<title>outboundPowerW : Real = basePowerW" in svg
        assert "avionics.powerW</title>" in svg

    def test_uncapped_rows_emit_no_label_titles(self):
        model = longeron.loads(_PACKAGE_GLOB)
        widget = diagrams.structure_diagram(model, max_label_width=None)
        graph = render.layout(render._to_elk_json(widget.source.value))
        svg = render._svg_from_layout(graph, title=None)
        assert "<title>" not in svg


class TestPng:
    def test_png(self, drone_model, tmp_path):
        try:
            import cairosvg  # noqa: F401  (native cairo loads at import)
        except Exception as err:
            pytest.skip(f"cairosvg unavailable: {err}")
        target = tmp_path / "states.png"
        render.to_png(drone_model.find("DeepScout::FlightStates"), target)
        data = target.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(data) > 5000


# ---------------------------------------------------------------------------
# browser-pipeline fixpoint: convert + layout must converge in ONE pass
# ---------------------------------------------------------------------------
#
# A faithful headless re-enactment of the ipyelk BROWSER cycle: kernel-side
# pipes (ValidationPipe, VisibilityPipe) run for real; the two browser pipes
# are emulated exactly the way the frontend performs them -- the tree crosses
# the widget transport (to_json/from_elk_json) both ways, label measuring
# mutates the JSON like measure_text.ts, and layout runs the REAL vendored
# elkjs (the same engine the elklayout worker wraps).  The regression this
# guards: the notation gallery's flow-pin diagram looped forever because a
# routing-tool flow reached the layout stage with unstamped (null) ids.


class TestBrowserPipelineFixpoint:
    @staticmethod
    def _measure_labels(data):
        """measure_text.ts: size every label without a pre-sized shape."""

        for label in data.get("labels") or []:
            shape = (label.get("properties") or {}).get("shape") or {}
            if not shape.get("width") or not shape.get("height"):
                css = (label.get("properties") or {}).get("cssClasses", "")
                width, height = render._measure(label.get("text") or " ", css)
                label["width"], label["height"] = width, height
        for key in ("children", "ports", "edges", "labels"):
            for sub in data.get(key) or []:
                TestBrowserPipelineFixpoint._measure_labels(sub)

    @classmethod
    def _run_cycle(cls, widget):
        """One Pipeline.run + Diagram.refresh.update_view; names of pipes run."""

        import asyncio
        import copy
        import json as json_module

        from ipyelk.elements.serialization import from_elk_json, to_json
        from ipyelk.pipes import BrowserTextSizer, ElkJS
        from ipyelk.pipes.base import PipeStatus

        def collect_properties(node, props):
            props[node.get("id")] = node.pop("properties", None)
            for key in ("children", "ports", "labels", "edges"):
                for sub in node.get(key) or []:
                    collect_properties(sub, props)

        def apply_properties(node, props):
            node["properties"] = props.get(node.get("id"))
            for key in ("children", "ports", "labels", "edges"):
                for sub in node.get(key) or []:
                    apply_properties(sub, props)

        async def run():
            pipeline = widget.pipe
            pipeline.check_dirty()
            ran = []
            for pipe in pipeline.pipes:
                if pipe.status.dirty():
                    ran.append(type(pipe).__name__)
                    if isinstance(pipe, BrowserTextSizer):
                        data = to_json(pipe.inlet.value, pipe.inlet)
                        cls._measure_labels(data)
                        pipe.outlet.value = from_elk_json(
                            json_module.loads(json_module.dumps(data)), None
                        )
                        pipe.outlet.persist()
                    elif isinstance(pipe, ElkJS):
                        data = to_json(pipe.inlet.value, pipe.inlet)
                        graph = copy.deepcopy(data)
                        props: dict = {}
                        collect_properties(graph, props)
                        result = render.layout(graph)  # the REAL elkjs
                        apply_properties(result, props)
                        pipe.outlet.value = from_elk_json(
                            json_module.loads(json_module.dumps(result)), None
                        )
                        pipe.outlet.persist()
                    else:
                        await pipe.run()
                else:
                    pipe.outlet.value = pipe.inlet.value
                pipe.status_update(PipeStatus.finished())
            # Diagram.refresh -> update_view (the browser's settle step)
            laid_out = pipeline.outlet.value
            widget.view.source.value = laid_out
            pipeline.inlet.value = laid_out
            pipeline.inlet.flow = ()
            return ran

        return asyncio.run(run())

    @staticmethod
    def _geometry(widget):
        import json as json_module

        from ipyelk.elements.serialization import to_json

        return json_module.dumps(to_json(widget.source.value, None), sort_keys=True)

    def _settled(self, widget):
        """After a settle NOTHING may be dirty: flow is spent, pipes clean."""

        assert widget.source.flow == ()
        assert widget.pipe.check_dirty() is False

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

    @pytest.mark.parametrize(
        "source",
        [_FLOW_PIN_FORM, _DRAWN_PORTS],
        ids=["flow-pins", "drawn-ports"],
    )
    def test_relayout_is_a_fixpoint(self, source):
        """Convert + layout twice: byte-equal geometry, no dirty marks.

        The second pass re-enters the layout stage exactly like a
        routing-tool refresh (the layout-options flow, which skips the
        id-stamping Validation/Visibility pipes) -- the tree must already
        be transport-complete and the geometry must not change.
        """

        widget = diagrams.structure_diagram(longeron.loads(source))
        assert self._run_cycle(widget) == [
            "ValidationPipe",
            "BrowserTextSizer",
            "VisibilityPipe",
            "ElkJS",
        ]
        first = self._geometry(widget)
        widget.source.flow = ("node.layoutOptions",)  # a routing-style refresh
        assert self._run_cycle(widget) == ["ElkJS"]
        assert self._geometry(widget) == first  # byte-equal: a true fixpoint
        self._settled(widget)

    def test_routing_toggle_round_trip_restores_the_layout(self):
        """Cycle the routing tool through all styles and back: the final
        orthogonal geometry is byte-equal to the original one (stale
        polyline bendPoints must not survive -- apply_routing drops
        computed sections), and clicking mid-flight merges with, never
        clobbers, the pending 'new' flow."""

        from longeron.toolbar import EdgeRoutingTool

        widget = diagrams.structure_diagram(longeron.loads(self._FLOW_PIN_FORM))
        tool = widget.get_tool(EdgeRoutingTool)

        # the maintainer's loop: a click while the initial flow is pending
        assert widget.source.flow == ("new",)
        tool.ui.click()  # -> POLYLINE
        assert widget.source.flow == ("new", "node.layoutOptions")
        self._run_cycle(widget)  # validation DID run: ids stamped, layout ok
        polyline = self._geometry(widget)

        tool.routing = "orthogonal"
        assert self._run_cycle(widget) == ["ElkJS"]
        orthogonal = self._geometry(widget)
        assert orthogonal != polyline  # routing really changed the routes

        tool.ui.click()  # -> POLYLINE again
        self._run_cycle(widget)
        assert self._geometry(widget) == polyline
        tool.routing = "orthogonal"
        self._run_cycle(widget)
        assert self._geometry(widget) == orthogonal  # full round trip
        self._settled(widget)

    def test_direction_toggle_round_trip_restores_the_layout(self):
        """Toggle the direction tool DOWN and back: the final left-to-right
        geometry is byte-equal to the original one (stale sections must
        not survive -- apply_direction drops computed routes), the DOWN
        pass really flowed top-to-bottom, and a click while the initial
        'new' flow is pending merges with it like the routing tool."""

        from longeron.toolbar import DirectionTool

        widget = diagrams.structure_diagram(longeron.loads(self._FLOW_PIN_FORM))
        tool = widget.get_tool(DirectionTool)

        assert widget.source.flow == ("new",)
        tool.ui.click()  # -> DOWN, while the initial flow is pending
        assert widget.source.flow == ("new", "node.layoutOptions")
        self._run_cycle(widget)  # validation DID run: ids stamped, layout ok
        down = self._geometry(widget)

        tool.ui.click()  # -> RIGHT
        assert self._run_cycle(widget) == ["ElkJS"]
        right = self._geometry(widget)
        assert right != down  # the flow really flipped

        tool.ui.click()  # -> DOWN again
        self._run_cycle(widget)
        assert self._geometry(widget) == down
        tool.ui.click()  # -> RIGHT again
        self._run_cycle(widget)
        assert self._geometry(widget) == right  # full round trip
        self._settled(widget)

    _W3B_DIRECTED = """
    package Directed {
        part def Part1;
        part def Part2;
        connection def ConnectionDef2 {
            end [1..1] part sourceEnd : Part1;
            end [1..*] part targetEnd : Part2;
        }
        part part1 : Part1;
        part part2 : Part2;
        connection connection2 : ConnectionDef2 connect part1 to part2;
    }
    """

    @pytest.mark.parametrize("routing", ["orthogonal", "polyline", "splines"])
    def test_w3b_directed_connection_routes_are_never_degenerate(self, routing):
        """Gallery section 3b pinned end to end (maintainer stall triage,
        item 6): the EXACT w3b model through the browser-faithful cycle
        (transport + browser-style label sizes + REAL elkjs), then the
        pinned reference math -- the same formulas the served bundle
        compiles -- over every routed edge.  Every angle finite, every
        renderLine trim drawable, the directed edge really carrying the
        end-only open-V (candidate c: symbol on end, none on start).  The
        live stall did NOT reproduce here or in a real Chromium run of
        the full gallery; this test keeps the code side pinned so any
        future degeneracy fails loudly in CI instead of silently in a
        browser tab."""

        import math

        widget = diagrams.structure_diagram(longeron.loads(self._W3B_DIRECTED), routing=routing)
        self._run_cycle(widget)
        reaches = {}
        for name, sym in widget.symbols.library.items():
            offset = getattr(sym, "path_offset", None)
            if offset is not None:
                reaches[name] = math.hypot(offset.x or 0, offset.y or 0)

        def iter_edges(node):
            yield from node.edges
            for child in node.children:
                yield from iter_edges(child)

        directed = None
        for edge in iter_edges(widget.source.value):
            css = edge.properties.cssClasses or ""
            if "sysml-packing" in css:
                continue
            points = []
            for section in edge.sections or []:
                points.append((section.startPoint.x, section.startPoint.y))
                points.extend((b.x, b.y) for b in section.bendPoints or [])
                points.append((section.endPoint.x, section.endPoint.y))
            assert points, f"unrouted edge: {css}"
            shape = edge.properties.shape
            start = getattr(shape, "start", None) if shape else None
            end = getattr(shape, "end", None) if shape else None
            if "sysml-edge-directed" in css:
                directed = (start, end, points)
            start_reach = reaches.get(start, 0.0)
            end_reach = reaches.get(end, 0.0)
            r = render._route_end_angle(points, "source", start_reach)
            r2 = render._route_end_angle(points, "target", end_reach)
            assert math.isfinite(r) and math.isfinite(r2)
            covered_s = render._covered_route_points(points, "source", start_reach)
            covered_t = render._covered_route_points(points, "target", end_reach)
            # the renderLine trim window is a valid (possibly empty) slice
            first, last = 1 + covered_s, len(points) - 2 - covered_t
            assert first >= 1 and last <= len(points) - 2
        assert directed is not None, "the directed connection edge must draw"
        start, end, points = directed
        assert start is None and end == "arrow"  # candidate (c)'s combination
        assert len(points) >= 2
        self._settled(widget)


_TANGENT_MEMBER = """
package Parts {
    part def Vehicle {
        part eng : Engine;
        ref part spare : Wheel;
    }
    part def Engine;
    part def Wheel;
}
"""

_TANGENT_SATISFY = """
package Reqs { requirement requirement1; }
package Sys {
    part part1 {
        satisfy requirement requirement2 references Reqs::requirement1;
    }
}
"""


def _section_points(edge):
    points = []
    for section in edge.get("sections", []):
        for p in (
            section["startPoint"],
            *section.get("bendPoints", []),
            section["endPoint"],
        ):
            points.append((p["x"], p["y"]))
    return points


def _routed(source: str, routing: str, css: str):
    """Lay out a model headless and return the routed points of the first
    edge whose cssClasses contain ``css``."""

    widget = diagrams.structure_diagram(longeron.loads(source), routing=routing)
    graph = render.layout(render._to_elk_json(widget.source.value))
    edge = next(e for e in _edges_json(graph) if css in e["properties"]["cssClasses"])
    return _section_points(edge)


class TestBrowserEndpointTangents:
    """Pinned reference for the vendored browser edge view's symbol
    orientation (vendor/ipyelk js/sprotty/views/edge_views.tsx
    routeEndAngle / coveredRoutePoints -- compiled into the shipped
    labextension).  The headless renderer is immune (its SVG markers carry
    orient="auto-start-reverse"), so these tests pin the TANGENT MATH the
    browser now uses, against both synthetic routes and real elkjs section
    data: maintainer repro A (polyline membership diamonds axis-aligned on
    a stub shorter than the diamond) and repro B (spline end heads flipped
    180 degrees into the target box by duplicated control points)."""

    # --- the math itself, synthetic routes ---------------------------------

    def test_straight_route_matches_the_naive_tangent(self):
        route = [(0.0, 0.0), (50.0, 0.0), (100.0, 0.0)]
        assert render._route_end_angle(route, "source", 12.0) == 0.0
        assert render._route_end_angle(route, "target", 12.0) == pytest.approx(math.pi)

    def test_orthogonal_clearance_keeps_the_old_angles(self):
        # first/last straight run >= _EDGE_END_CLEARANCE > any symbol reach:
        # the chord lies ON the terminal segment, so orthogonal rendering is
        # pixel-identical to the pre-fix view
        route = [(0.0, 0.0), (24.0, 0.0), (24.0, 40.0), (60.0, 40.0)]
        assert render._route_end_angle(route, "source", 21.2) == 0.0
        assert render._route_end_angle(route, "target", 21.2) == pytest.approx(math.pi)

    def test_duplicated_spline_knots_no_longer_flip_the_head(self):
        # repro B in miniature: elkjs SPLINES duplicates the terminal knot;
        # the old view took atan2(0, 0) == 0 and drew the head rotated 0deg
        # -- pointing INTO the target -- instead of pi (back along the edge)
        route = [(0.0, 0.0), (43.0, 0.0), (86.0, 0.0), (86.0, 0.0), (86.0, 0.0)]
        naive = math.atan2(0.0, 0.0)  # what the browser used to compute
        assert naive == 0.0
        assert render._route_end_angle(route, "target", 15.0) == pytest.approx(math.pi)

    def test_polyline_stub_diamond_rides_the_chord(self):
        # repro A in miniature: a 5px horizontal exit stub, then the real
        # diagonal; the 12px diamond straddles the bend.  The old view
        # oriented it along the stub (0deg, axis-aligned); the chord over
        # the diamond's own footprint follows the visible shaft
        route = [(0.0, 0.0), (5.0, 0.0), (26.8, -9.0)]
        angle = render._route_end_angle(route, "source", 12.0)
        assert angle != 0.0
        assert math.degrees(angle) == pytest.approx(-13.2, abs=0.5)

    def test_start_diamond_tangent_is_the_exact_arc_length_chord(self):
        """Round-3 re-verification of the maintainer's polyline START-
        diamond case (with the served-bundle staleness explained, the
        CODE is re-pinned): for a 5px stub followed by a diagonal, the
        START tangent is the chord to the point at arc-length reach --
        analytically ON the diagonal segment -- so the diamond leans with
        the visible shaft, never with the axis-aligned stub (what any
        stale pre-15624b3 bundle would draw)."""

        stub, reach = 5.0, 12.0  # the composition rhomb's path_offset reach
        route = [(0.0, 0.0), (stub, 0.0), (26.8, -9.0)]
        # the reference point sits (reach - stub) along the diagonal
        t = (reach - stub) / math.dist(route[1], route[2])
        ref = (stub + (26.8 - stub) * t, -9.0 * t)
        expected = math.atan2(ref[1], ref[0])
        angle = render._route_end_angle(route, "source", reach)
        assert angle == pytest.approx(expected)
        # strictly BETWEEN the stub's direction and the diagonal's: the
        # diamond rotates toward the shaft, clamped by its own footprint
        diagonal = math.atan2(-9.0, 26.8 - stub)
        assert min(0.0, diagonal) < angle < max(0.0, diagonal)
        assert angle != 0.0  # never the stub
        # and the stub's interior bend is dropped from the trimmed shaft
        assert render._covered_route_points(route, "source", reach) == 1

    def test_short_route_falls_back_to_the_farthest_point(self):
        route = [(0.0, 0.0), (4.0, 3.0)]
        angle = render._route_end_angle(route, "source", 24.0)
        assert angle == pytest.approx(math.atan2(3.0, 4.0))

    def test_two_point_route_with_oversized_reach_stays_finite(self):
        """Maintainer stall triage (item 6, candidate b): a straight
        2-point route shorter than the symbol reach (short edge, big head
        + label) must fall back to the farthest distinct point -- finite
        angles both ends, nothing covered, no NaN anywhere."""

        route = [(0.0, 0.0), (10.0, 0.0)]  # total length 10 < reach 15
        for end, expected in (("source", 0.0), ("target", math.pi)):
            angle = render._route_end_angle(route, end, 15.0)
            assert math.isfinite(angle)
            assert angle == pytest.approx(expected)
            assert render._covered_route_points(route, end, 15.0) == 0

    def test_identical_endpoint_route_yields_zero_not_nan(self):
        """Item 6 candidate (b) continued: a route whose points all
        coincide (elkjs can emit fully-degenerate stubs) must yield the
        0.0 sentinel -- never NaN (atan2 of a zero chord), never an
        unterminated scan (both reference loops are bounded)."""

        route = [(5.0, 5.0), (5.0, 5.0)]
        for end in ("source", "target"):
            assert render._route_end_angle(route, end, 12.0) == 0.0
            assert render._covered_route_points(route, end, 12.0) == 0

    @pytest.mark.parametrize(
        ("route", "start_reach", "end_reach"),
        [
            # w3b's directed connection: straight 2-point route, open-V
            # arrow at the END only (candidate c: symbol on end, none on
            # start)
            ([(92.5, 237.0), (363.1, 237.0)], 0.0, 1.0),
            # 2-point route shorter than both reaches
            ([(0.0, 0.0), (8.0, 0.0)], 12.0, 15.0),
            # every interior point beneath the end symbol (candidate a:
            # covered removes ALL interior points -- the trim must keep a
            # drawable start->end chord, never an empty path)
            ([(0.0, 0.0), (86.0, 0.0), (86.0, 0.0), (86.0, 0.0)], 0.0, 15.0),
            # overlapping footprints on a short 3-point route
            ([(0.0, 0.0), (5.0, 0.0), (9.0, 3.0)], 12.0, 12.0),
            # fully-degenerate route
            ([(7.0, 7.0), (7.0, 7.0), (7.0, 7.0)], 12.0, 12.0),
        ],
    )
    def test_render_line_trim_never_degenerates(self, route, start_reach, end_reach):
        """Python mirror of the browser renderLine trim (vendor/ipyelk
        edge_views.tsx): ``first = 1 + covered(source)``, ``last = n - 2 -
        covered(target)``, path = start' + interior[first..last] + end'.
        For every degenerate-route vector from the item-6 triage the trim
        must keep at least the two endpoint anchors (a drawable chord) and
        every computed angle must be finite -- the sprotty view can then
        never throw or emit NaN coordinates on these inputs."""

        r = render._route_end_angle(route, "source", start_reach)
        r2 = render._route_end_angle(route, "target", end_reach)
        assert math.isfinite(r) and math.isfinite(r2)
        cs = render._covered_route_points(route, "source", start_reach)
        ct = render._covered_route_points(route, "target", end_reach)
        first, last = 1 + cs, len(route) - 2 - ct
        trimmed = [route[0], *route[first : last + 1], route[-1]]
        assert len(trimmed) >= 2  # the M + final L always survive
        # each end counts covered interior points INDEPENDENTLY: on a
        # short route one bend may sit under BOTH footprints and be
        # counted twice -- the trim window then simply collapses
        # (first > last: empty interior slice), degrading to the bare
        # start->end chord instead of anything negative or throwing
        assert first >= 1 and last <= len(route) - 2
        assert all(math.isfinite(c) for point in trimmed for c in point)

    def test_fully_degenerate_route_yields_zero(self):
        route = [(7.0, 7.0), (7.0, 7.0), (7.0, 7.0)]
        assert render._route_end_angle(route, "source", 12.0) == 0.0
        assert render._route_end_angle(route, "target", 12.0) == 0.0

    def test_covered_points_span_the_symbol_footprint(self):
        route = [(0.0, 0.0), (5.0, 0.0), (26.8, -9.0), (60.0, -9.0)]
        # the 5px stub bend sits under a 12px diamond; the far bend does not
        assert render._covered_route_points(route, "source", 12.0) == 1
        assert render._covered_route_points(route, "source", 0.0) == 0
        assert render._covered_route_points(route, "target", 12.0) == 0
        # duplicated spline knots at the end all sit under the head
        route = [(0.0, 0.0), (43.0, 0.0), (86.0, 0.0), (86.0, 0.0), (86.0, 0.0)]
        assert render._covered_route_points(route, "target", 15.0) == 2

    # --- real elkjs section data (the browser's input) ---------------------

    def test_elkjs_spline_sections_carry_duplicated_control_points(self):
        """Repro B pinned on real layout output: elkjs SPLINES emits bend
        (control) points that DUPLICATE the section's terminal points, and
        the reference tangent still points back along the edge while the
        naive adjacent-segment tangent degenerates."""

        points = _routed(_TANGENT_SATISFY, "splines", "sysml-edge-references")
        assert points[-1] == points[-2]  # the degenerate chord really ships
        naive = math.atan2(points[-2][1] - points[-1][1], points[-2][0] - points[-1][0])
        assert naive == 0.0  # what flipped the satisfy head into the box
        angle = render._route_end_angle(points, "target", render._HEAD_LENGTH + 1)
        assert abs(math.degrees(angle)) == pytest.approx(180.0, abs=15.0)

    def test_elkjs_polyline_stub_would_misorient_the_diamond(self):
        """Repro A pinned on real layout output: under POLYLINE the section
        leaves the whole's border with a stub shorter than the membership
        diamond, so the naive start tangent is axis-aligned while the
        reference chord follows the visible diagonal shaft."""

        points = _routed(_TANGENT_MEMBER, "polyline", "sysml-edge-member")
        stub = math.dist(points[0], points[1])
        diamond = 12.0  # the composition rhomb's path_offset reach
        assert stub < diamond  # the bend really falls inside the footprint
        naive = math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])
        chord = render._route_end_angle(points, "source", diamond)
        assert naive == pytest.approx(0.0, abs=math.radians(1.0))
        assert abs(math.degrees(chord)) > 5.0  # rotates with the shaft
        assert render._covered_route_points(points, "source", diamond) == 1


# three package depths; L2a/L2b are loose members beside connected part
# defs, so pack_components wraps them in a synthetic group -- the exact
# configuration that reproduced the detached tab
_NESTED_PACKAGES = """
package L0 {
    package L1 {
        package L2a { part def A2; }
        package L2b { part def B2; }
        part def W;
        part def V { part w : W; }
    }
    package L1b { part def C1; }
    part def X;
    part def Y { part x : X; }
}
"""


@pytest.fixture(scope="module")
def nested_package_layout():
    model = longeron.loads(_NESTED_PACKAGES)
    root = render._root_of(diagrams.structure_diagram(model))
    return render.layout(render._to_elk_json(root))


class TestPackageTabAdjacency:
    """The package folder tab (spec printed p.24) rides FLUSH with the box
    top at every nesting depth.  elk.spacing.labelNode applies per
    hierarchy level; the invisible pack groups ``pack_components`` wraps
    loose members in once fell back to the elkjs default (5px), floating
    nested packages' tabs off their boxes."""

    @staticmethod
    def _package_tabs_at(graph, depth):
        found = []

        def walk(node, package_depth):
            css = node.get("properties", {}).get("cssClasses", "")
            is_package = "sysml-package" in css
            if is_package and package_depth == depth:
                tab = next(
                    label
                    for label in node.get("labels", [])
                    if "sysml-tab" in label.get("properties", {}).get("cssClasses", "")
                )
                found.append((node.get("id"), tab))
            for child in node.get("children", []):
                walk(child, package_depth + (1 if is_package else 0))

        walk(graph, 0)
        return found

    @pytest.mark.parametrize("depth", [0, 1, 2])
    def test_tab_flush_with_body(self, nested_package_layout, depth):
        tabs = self._package_tabs_at(nested_package_layout, depth)
        assert tabs, f"no package nodes found at depth {depth}"
        for node_id, tab in tabs:
            # tab coordinates are node-relative: the body's top-left corner
            # is (0, 0), so adjacency means bottom edge at y=0, left at x=0
            bottom = tab["y"] + tab["height"]
            assert bottom == pytest.approx(0.0, abs=1e-6), (
                f"{node_id}: tab bottom {bottom} != body top 0"
            )
            assert tab["x"] == pytest.approx(0.0, abs=1e-6), (
                f"{node_id}: tab left {tab['x']} != body left 0"
            )
