"""Spike tests: the three.js mesh-viewer widget (payload wiring only --
the front-end needs a browser; geometry sanity lives in
test_analysis_geometry)."""

import json

import pytest

from sysml2.analysis import geometry, viewer3d

MESH = geometry.drone_geometry(prop_diameter_in=5.0, motor_mass=0.033,
                               battery_mass=0.19, esc_mass=0.012)


class TestMeshViewer:
    def test_single_mesh(self):
        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH, label="racer", width_px=500)
        parsed = json.loads(widget.mesh_json)
        assert [p["name"] for p in parsed["parts"]] == [
            "frame", "motors", "props", "battery", "esc"]
        assert widget.mesh_b_json == ""  # single mode
        assert widget.label == "racer" and widget.width_px == 500

    def test_compare_mode(self):
        pytest.importorskip("anywidget")
        other = geometry.drone_geometry(prop_diameter_in=10.0,
                                        motor_mass=0.056,
                                        battery_mass=0.18, esc_mass=0.009)
        widget = viewer3d.mesh_viewer(MESH, other, label="a", label_b="b")
        assert json.loads(widget.mesh_b_json)["bounds"] != \
            json.loads(widget.mesh_json)["bounds"]

    def test_esm_contracts(self):
        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH)
        # the front-end contract: CDN import (documented offline tradeoff),
        # graceful fallback, re-fit gesture, and in-place mesh swaps
        assert viewer3d.THREE_URL in widget._esm
        assert "offline" in widget._esm
        assert "dblclick" in widget._esm
        assert "change:mesh_json" in widget._esm

    def test_swap_in_place(self):
        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH)
        widget.mesh_json = json.dumps(
            geometry.drone_geometry(prop_diameter_in=10.0, motor_mass=0.056,
                                    battery_mass=0.18, esc_mass=0.009))
        assert json.loads(widget.mesh_json)["bounds"][1][0] > 0.2
