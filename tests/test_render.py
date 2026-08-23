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
        """SysML v2/KerML notation (single-sourced in render._EDGE_ENDS):
        specialization = solid line + hollow triangle, feature typing =
        dashed line + hollow triangle, connections = no arrowhead."""

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
        assert f'marker-end="url(#{render._hollow_arrow_id("#6a9a48")})"' in typed
        assert 'stroke-dasharray="4 2"' in typed  # dashed 'defined by'
        connect = edge_group("P::sys::x-&gt;P::sys::y")
        assert "marker-end" not in connect  # connectors are non-directional
        # hollow marker defs: white fill occludes the line, the outline
        # takes the edge color
        assert 'd="M 1 1 L 11 6 L 1 11 z" fill="#ffffff" stroke="#4878a8"' in svg

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
