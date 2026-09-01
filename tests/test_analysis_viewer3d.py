"""Spike tests: the three.js mesh-viewer widget (payload wiring only --
the front-end needs a browser; geometry sanity lives in
test_analysis_geometry)."""

import json

import pytest

from longeron.analysis import geometry
from longeron.widgets import viewer3d

MESH = geometry.drone_geometry(
    prop_diameter_in=5.0, motor_mass=0.033, battery_mass=0.19, esc_mass=0.012, fc_mass=0.039
)


class TestMeshViewer:
    def test_single_mesh(self):
        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH, label="racer", width_px=500)
        parsed = json.loads(widget.mesh_json)
        assert [p["name"] for p in parsed["parts"]] == [
            "frame",
            "motors",
            "props",
            "battery",
            "esc",
            "fc",
        ]
        assert widget.mesh_b_json == ""  # single mode
        assert widget.label == "racer" and widget.width_px == 500

    def test_compare_mode(self):
        pytest.importorskip("anywidget")
        other = geometry.drone_geometry(
            prop_diameter_in=10.0, motor_mass=0.056, battery_mass=0.18, esc_mass=0.009
        )
        widget = viewer3d.mesh_viewer(MESH, other, label="a", label_b="b")
        assert json.loads(widget.mesh_b_json)["bounds"] != json.loads(widget.mesh_json)["bounds"]

    def test_esm_contracts(self):
        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH)
        # the front-end contract: CDN import (documented offline tradeoff),
        # graceful fallback, re-fit gesture, in-place mesh swaps, and
        # billboard sprite labels for grid lineups
        assert viewer3d.THREE_URL in widget._esm
        assert "offline" in widget._esm
        assert "dblclick" in widget._esm
        assert "change:mesh_json" in widget._esm
        for token in ("mesh.labels", "Sprite", "CanvasTexture", "label.anchor"):
            assert token in widget._esm, token

    def test_esm_linked_selection_contracts(self):
        """The linked-selection front-end, encoded: every part mesh
        carries its model identity key; highlight changes pop matches
        with the JupyterLab selection accent and dim the rest (a mesh
        swap re-applies the active highlight); a still click raycasts
        and reports the hit key on picked_json."""

        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH)
        for token in (
            "userData.key",
            "part.key || part.name",
            "change:highlight_json",
            "--jp-brand-color2",
            "emissive",
            "applyHighlight",
            "Raycaster",
            "picked_json",
            "save_changes",
            "moved",
        ):
            assert token in widget._esm, token

    def test_highlight_round_trip(self):
        """widget.highlight(keys) bakes a sorted, deduplicated JSON set
        into the synced traitlet; highlight() clears it instantly."""

        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH)
        assert widget.highlight_json == "[]"  # nothing popped by default
        assert widget.picked_json == "[]"  # nothing picked either
        widget.highlight(["Rotorcraft::QuadCopter::rotors", "frame", "frame"])
        assert json.loads(widget.highlight_json) == ["Rotorcraft::QuadCopter::rotors", "frame"]
        widget.highlight()
        assert widget.highlight_json == "[]"

    def test_esm_ux_contracts(self):
        """The UX rework, encoded: the canvas fills the host width and
        re-fits on resize; right-drag pan works under JupyterLab (the
        canvas swallows contextmenu) with shift-drag as the fallback;
        a subtle overlay hint names every binding."""

        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH)
        for token in (
            "ResizeObserver",
            "contextmenu",
            "preventDefault",
            "stopPropagation",
            "shiftKey",
            "button === 2",
            "setPointerCapture",
            "longeron-viewer3d-hint",
        ):
            assert token in widget._esm, token
        for word in ("orbit", "pan", "zoom", "fit"):
            assert word in widget._esm, word
        assert "width: 100%" in widget._css

    def test_swap_in_place(self):
        pytest.importorskip("anywidget")
        widget = viewer3d.mesh_viewer(MESH)
        widget.mesh_json = json.dumps(
            geometry.drone_geometry(
                prop_diameter_in=10.0, motor_mass=0.056, battery_mass=0.18, esc_mass=0.009
            )
        )
        assert json.loads(widget.mesh_json)["bounds"][1][0] > 0.2
