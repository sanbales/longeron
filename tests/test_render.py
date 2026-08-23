"""Headless SVG/PNG rendering tests (node + vendored elkjs)."""

import shutil

import pytest

pytest.importorskip("ipyelk")
if shutil.which("node") is None:
    pytest.skip("node executable not available", allow_module_level=True)

import longeron
from longeron import diagrams, render


@pytest.fixture(scope="module")
def drone_model():
    return longeron.load("examples/drone.sysml")


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
        svg = render.to_svg(diagrams.state_diagram(drone_model.find("Drone::FlightStates")))
        assert "launch" in svg and "touchdown" in svg
        assert 'marker-end="url(#arrow-b58900)"' in svg  # gold arrowheads
        assert 'markerUnits="userSpaceOnUse"' in svg  # constant-size heads
        assert "#b58900" in svg  # state/transition styling applied

    def test_action_svg(self, drone_model):
        svg = render.to_svg(diagrams.action_diagram(drone_model.find("Drone::PlanBattery")))
        assert "start" in svg and "done" in svg

    def test_accepts_model_elements_directly(self, drone_model):
        svg = render.to_svg(drone_model.find("Drone::FlightStates"))
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

    def test_actor_and_stakeholder_keyword_boxes(self):
        """Actors/stakeholders (errata N17): the keyword-box form -- a
        rounded usage box with «actor»/«stakeholder» -- not invisible."""

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
        assert "\u00abactor\u00bb" in svg
        assert "\u00abstakeholder\u00bb" in svg
        assert 'data-qname="P::Deliver::driver"' in svg
        # the actor's typing edge draws like any usage->def typing
        typed = svg.split('data-edge="P::Deliver::driver-&gt;P::Person"')[1].split("</g>")[0]
        assert "hollow-colon" in typed

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
        svg = render.to_svg(diagrams.state_diagram(drone_model.find("Drone::FlightStates")))
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
        widget = diagrams.state_diagram(drone_model.find("Drone::FlightStates"))
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

        hover = find(graph, "Drone::HoverTime")
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

        quad = find(graph, "Drone::QuadCopter")
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
        hover = find(graph, "Drone::HoverTime")
        assert {label["x"] for label in rows(hover)} == {8.0}
        title = next(lab for lab in hover["labels"] if lab["text"] == "HoverTime")
        assert title["x"] > 8.0

        # containers: attribute rows get full-width boxes, so their
        # (ELK-centered) left edges coincide
        quad = find(graph, "Drone::QuadCopter")
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

        svg = render.to_svg(drone_model.find("Drone::FlightStates"))
        assert "<title>Drone::FlightStates</title>" in svg
        # pre-built widgets recover the name from the node qualified names
        svg = render.to_svg(diagrams.state_diagram(drone_model.find("Drone::FlightStates")))
        assert "<title>Drone::FlightStates</title>" in svg
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


class TestPng:
    def test_png(self, drone_model, tmp_path):
        try:
            import cairosvg  # noqa: F401  (native cairo loads at import)
        except Exception as err:
            pytest.skip(f"cairosvg unavailable: {err}")
        target = tmp_path / "states.png"
        render.to_png(drone_model.find("Drone::FlightStates"), target)
        data = target.read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        assert len(data) > 5000
