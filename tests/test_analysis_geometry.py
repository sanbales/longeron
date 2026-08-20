"""Spike tests: parametric mix geometry -- mesh sanity and scaling."""

from math import pi
from pathlib import Path

import pytest

import sysml2
from sysml2.analysis import AnalysisError, geometry

EXAMPLES = Path(__file__).parent.parent / "examples"

RACER = {"prop_diameter_in": 5.0, "motor_mass": 0.033,
         "battery_mass": 0.19, "esc_mass": 0.012}
CRUISER = {"prop_diameter_in": 10.0, "motor_mass": 0.056,
           "battery_mass": 0.18, "esc_mass": 0.009}


@pytest.fixture(scope="module")
def study():
    from sysml2.analysis import trades

    catalog = sysml2.load(EXAMPLES / "drone_catalog.sysml", cache=False)
    return trades.TradeStudy(catalog, "DroneCatalog::TradeQuad")


def _volume(vertices, faces):
    """Signed volume via the divergence theorem: positive iff the mesh is
    closed with CCW-outward winding (three.js front faces)."""

    total = 0.0
    for i in range(0, len(faces), 3):
        a, b, c = (faces[i] * 3, faces[i + 1] * 3, faces[i + 2] * 3)
        ax, ay, az = vertices[a:a + 3]
        bx, by, bz = vertices[b:b + 3]
        cx, cy, cz = vertices[c:c + 3]
        total += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx)
                  + az * (bx * cy - by * cx))
    return total / 6.0


def _watertight(vertices, faces):
    """Every directed edge is matched by its reverse exactly once
    (after merging positionally-duplicated vertices)."""

    canonical: dict[tuple[float, float, float], int] = {}
    index_of = []
    for i in range(0, len(vertices), 3):
        key = (round(vertices[i], 7), round(vertices[i + 1], 7),
               round(vertices[i + 2], 7))
        index_of.append(canonical.setdefault(key, len(canonical)))
    edges: dict[tuple[int, int], int] = {}
    for i in range(0, len(faces), 3):
        tri = [index_of[faces[i + k]] for k in range(3)]
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges[(a, b)] = edges.get((a, b), 0) + 1
    return all(count == 1 and edges.get((b, a)) == 1
               for (a, b), count in edges.items())


class TestPrimitives:
    def test_box_volume_and_bounds(self):
        vertices, faces = geometry._box(2.0, 3.0, 4.0, cx=1.0, cy=1.0, cz=1.0)
        assert len(vertices) == 24 * 3 and len(faces) == 12 * 3
        assert _volume(vertices, faces) == pytest.approx(24.0)
        assert min(vertices[0::3]) == 0.0 and max(vertices[0::3]) == 2.0
        assert min(vertices[1::3]) == -0.5 and max(vertices[2::3]) == 3.0
        assert _watertight(vertices, faces)

    def test_cylinder_volume(self):
        vertices, faces = geometry._cylinder(0.5, 2.0, segments=24)
        exact = pi * 0.25 * 2.0
        assert 0.95 * exact < _volume(vertices, faces) < exact
        assert _watertight(vertices, faces)

    def test_rotate_y(self):
        rotated = geometry._rotate_y([1.0, 0.0, 0.0], -pi / 2)
        assert rotated[0] == pytest.approx(0.0, abs=1e-12)
        assert rotated[2] == pytest.approx(1.0)  # +X toward +Z for -angle


class TestDroneGeometry:
    def test_parts_and_schema(self):
        mesh = geometry.drone_geometry(**RACER)
        assert [p["name"] for p in mesh["parts"]] == [
            "frame", "motors", "props", "battery", "esc"]
        assert mesh["unit"] == "m"
        colors = {p["color"] for p in mesh["parts"]}
        assert len(colors) == 5  # per-part colors are distinct
        for part in mesh["parts"]:
            assert len(part["vertices"]) % 3 == 0
            assert len(part["faces"]) % 3 == 0
            assert max(part["faces"]) < len(part["vertices"]) // 3
            assert _volume(part["vertices"], part["faces"]) > 0

    def test_bounds_enclose_all_vertices(self):
        mesh = geometry.drone_geometry(**CRUISER)
        (lo, hi) = mesh["bounds"]
        for part in mesh["parts"]:
            for axis in range(3):
                coords = part["vertices"][axis::3]
                assert min(coords) >= lo[axis] - 1e-9
                assert max(coords) <= hi[axis] + 1e-9

    def test_to_scale(self):
        mesh = geometry.drone_geometry(**CRUISER)
        (_lo, hi) = mesh["bounds"]
        # prop tips: half wheelbase + prop radius, both from the 10" prop
        spacing = 10.0 * geometry.IN + 0.02
        assert hi[0] == pytest.approx(spacing / 2 + 5.0 * geometry.IN,
                                      abs=1e-3)
        racer = geometry.drone_geometry(**RACER)
        assert racer["bounds"][1][0] < hi[0] / 1.8  # 10" dwarfs 5"

    def test_motor_sizing_heuristic(self):
        diameter, height = geometry.motor_size(0.033)  # a 2306-class motor
        assert 0.024 < diameter < 0.032
        assert height == pytest.approx(0.7 * diameter)
        with pytest.raises(AnalysisError):
            geometry.motor_size(0.0)

    def test_battery_sizing_heuristic(self):
        length, width, height = geometry.battery_size(0.190)
        assert 0.06 < length < 0.09 and length > width > height


class TestArchitectureBridge:
    def test_params_from_mix(self, study):
        arch = study.evaluate({"motors": "sunnySky2212", "props": "apc1045",
                               "battery": "lipo3s2200", "esc": "esc20"})
        params = geometry.architecture_params(study, arch)
        assert params == {"motor_mass": 0.056, "prop_diameter_in": 10.0,
                          "battery_mass": 0.18, "esc_mass": 0.009}
        mesh = geometry.architecture_geometry(study, arch)
        assert len(mesh["parts"]) == 5

    def test_missing_point_is_loud(self, study):
        arch = study.evaluate({"motors": "emax2306", "props": "hq5x43",
                               "battery": "lipo4s1500", "esc": "esc45"})
        arch.selection.pop("esc")
        with pytest.raises(AnalysisError):
            geometry.architecture_params(study, arch)


class TestCadqueryBridge:
    def test_assembly(self):
        pytest.importorskip("cadquery")
        assembly = geometry.to_cadquery(**RACER)
        names = {child.name for child in assembly.children}
        assert names == {"frame", "motor1", "motor2", "motor3", "motor4",
                         "prop1", "prop2", "prop3", "prop4", "battery",
                         "esc"}

    def test_missing_extra_is_loud(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def no_cadquery(name, *args, **kwargs):
            if name == "cadquery":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_cadquery)
        with pytest.raises(ImportError, match="longeron\\[cad\\]"):
            geometry.to_cadquery(**RACER)
