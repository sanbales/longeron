"""Headless SVG/PNG rendering tests (node + vendored elkjs)."""

import shutil

import pytest

pytest.importorskip("ipyelk")
if shutil.which("node") is None:
    pytest.skip("node executable not available", allow_module_level=True)

import sysml2
from sysml2 import diagrams, render


@pytest.fixture(scope="module")
def drone_model():
    return sysml2.load("examples/drone.sysml")


class TestSvg:
    def test_structure_svg(self, drone_model, tmp_path):
        path = tmp_path / "structure.svg"
        svg = render.to_svg(diagrams.structure_diagram(drone_model), path)
        assert path.exists()
        assert svg.startswith("<svg")
        assert "QuadCopter" in svg
        assert "capacity : Real = 5200.0" in svg

    def test_state_svg_has_transitions(self, drone_model):
        svg = render.to_svg(
            diagrams.state_diagram(drone_model.find("Drone::FlightStates")))
        assert "launch" in svg and "touchdown" in svg
        assert 'marker-end="url(#arrow)"' in svg
        assert "#b58900" in svg  # state/transition styling applied

    def test_action_svg(self, drone_model):
        svg = render.to_svg(
            diagrams.action_diagram(drone_model.find("Drone::PlanBattery")))
        assert "start" in svg and "done" in svg

    def test_accepts_model_elements_directly(self, drone_model):
        svg = render.to_svg(drone_model.find("Drone::FlightStates"))
        assert "flying" in svg

    def test_layout_produces_coordinates(self, drone_model):
        widget = diagrams.state_diagram(drone_model.find("Drone::FlightStates"))
        graph = render.layout(render._to_elk_json(widget.source.value))
        assert graph["width"] > 0 and graph["height"] > 0
        assert all("x" in child for child in graph["children"])

    def test_escaping(self):
        model = sysml2.loads(
            'package P { part def A { attribute note : String = "<b>&"; } }')
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
