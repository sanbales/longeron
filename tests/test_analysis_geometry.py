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


class TestNewPrimitives:
    def test_loft_frustum_volume(self):
        # 1x1 square to 0.5x0.5 square over length 2: V = h/3 (A0+A1+sqrt)
        vertices, faces = geometry._loft(
            (0, 0, 0), (0.5, 0, 0), (0, 0.5, 0),
            (0, 0, 2), (0.25, 0, 0), (0, 0.25, 0))
        assert _volume(vertices, faces) == pytest.approx(2 / 3 * 1.75)
        assert _watertight(vertices, faces)

    def test_tube_volume_and_orientation(self):
        for rings in ([(0.0, 0.5), (2.0, 0.5)], [(2.0, 0.5), (0.0, 0.5)]):
            vertices, faces = geometry._tube(rings, segments=24)
            exact = pi * 0.25 * 2.0
            assert 0.95 * exact < _volume(vertices, faces) < exact
            assert _watertight(vertices, faces)

    def test_tube_validates(self):
        with pytest.raises(AnalysisError):
            geometry._tube([(0.0, 0.5)])
        with pytest.raises(AnalysisError):
            geometry._tube([(0.0, 0.5), (1.0, 0.0)])


WINGED = {"wing_span": 2.6, "wing_chord": 0.24, "taper": 0.6,
          "fuselage_length": 0.95, "prop_diameter": 0.24,
          "motor_mass": 0.092, "battery_mass": 1.95}
DART = {"body_length": 1.25, "wing_span": 1.05, "wing_chord": 0.17,
        "taper": 0.5, "prop_diameter": 0.24, "motor_mass": 0.15,
        "battery_mass": 0.5}


class TestWingedVtolGeometry:
    def test_parts_and_solidity(self):
        mesh = geometry.winged_vtol_geometry(**WINGED)
        assert [p["name"] for p in mesh["parts"]] == [
            "frame", "wing", "tail", "motors", "props", "battery"]
        assert len({p["color"] for p in mesh["parts"]}) == 6
        for part in mesh["parts"]:
            assert _volume(part["vertices"], part["faces"]) > 0

    def test_to_scale_span(self):
        mesh = geometry.winged_vtol_geometry(**WINGED)
        lo, hi = mesh["bounds"]
        # z extent: wing tips plus the wingtip-prop disks (radius 0.12)
        assert hi[2] == pytest.approx(2.6 / 2 + 0.12, abs=1e-3)
        assert lo[2] == pytest.approx(-(2.6 / 2 + 0.12), abs=1e-3)
        # the 2.6 m wing dwarfs the quad frame
        quad = geometry.drone_geometry(prop_diameter_in=0.33 / geometry.IN,
                                       motor_mass=0.092, battery_mass=0.98,
                                       esc_mass=0.014)
        assert (hi[2] - lo[2]) > 2.5 * (quad["bounds"][1][2]
                                        - quad["bounds"][0][2])

    def test_four_props_two_sizes(self):
        mesh = geometry.winged_vtol_geometry(**WINGED)
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        assert props["opacity"] < 1.0  # spinning disks stay translucent
        # wingtip disks face forward (span the YZ plane at |z| = half span)
        zs = props["vertices"][2::3]
        assert max(zs) == pytest.approx(1.3 + 0.12, abs=1e-3)

    def test_validates_dimensions(self):
        with pytest.raises(AnalysisError):
            geometry.winged_vtol_geometry(**{**WINGED, "wing_span": 0.0})


class TestInterceptorGeometry:
    def test_parts_and_solidity(self):
        mesh = geometry.interceptor_geometry(**DART)
        assert [p["name"] for p in mesh["parts"]] == [
            "frame", "wing", "tail", "motors", "props", "battery"]
        for part in mesh["parts"]:
            assert _volume(part["vertices"], part["faces"]) > 0

    def test_slender_to_scale(self):
        mesh = geometry.interceptor_geometry(**DART)
        lo, hi = mesh["bounds"]
        length = hi[0] - lo[0]
        assert length > 1.25  # body plus pusher prop
        assert hi[2] - lo[2] == pytest.approx(1.05, abs=1e-3)  # wing span
        frame = next(p for p in mesh["parts"] if p["name"] == "frame")
        ys = frame["vertices"][1::3]
        assert max(ys) - min(ys) < 0.2 * length  # genuinely slender

    def test_pusher_prop_at_the_stern(self):
        mesh = geometry.interceptor_geometry(**DART)
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        assert max(props["vertices"][0::3]) < 0  # aft of the midpoint

    def test_validates_dimensions(self):
        with pytest.raises(AnalysisError):
            geometry.interceptor_geometry(**{**DART, "body_length": 0.0})


@pytest.fixture(scope="module")
def mission_study():
    from sysml2.analysis import trades

    catalog = sysml2.load(EXAMPLES / "uav_missions.sysml", cache=False)
    return trades.TradeStudy(catalog, "UavMissions::InterceptUav")


class TestMissionBridge:
    def test_family_dispatch(self, mission_study):
        def mix(airframe):
            return mission_study.evaluate({
                "airframe": airframe, "motors": "stdMotor",
                "props": "slimProp", "battery": "packMid"})

        quad = geometry.mission_geometry(mission_study, mix("boxQuad"))
        assert [p["name"] for p in quad["parts"]] == [
            "frame", "motors", "props", "battery", "esc"]
        winged = geometry.mission_geometry(mission_study, mix("vtolWing"))
        assert any(p["name"] == "wing" for p in winged["parts"])
        dart = geometry.mission_geometry(mission_study,
                                         mix("dartInterceptor"))
        span_z = dart["bounds"][1][2] - dart["bounds"][0][2]
        assert span_z == pytest.approx(1.05, abs=1e-3)

    def test_params_read_the_selected_variants(self, mission_study):
        arch = mission_study.evaluate({
            "airframe": "vtolWing", "motors": "ecoMotor",
            "props": "lifterProp", "battery": "packLite"})
        params = geometry.mission_params(mission_study, arch)
        assert params["wing_span"] == 2.6
        assert params["prop_diameter"] == 0.51
        assert params["motor_mass"] == 0.058
        assert params["battery_mass"] == 0.5

    def test_missing_point_is_loud(self, mission_study):
        arch = mission_study.evaluate({
            "airframe": "boxQuad", "motors": "stdMotor",
            "props": "slimProp", "battery": "packMid"})
        arch.selection.pop("battery")
        with pytest.raises(AnalysisError):
            geometry.mission_params(mission_study, arch)


class TestLineup:
    def test_side_by_side_at_true_scale(self):
        winged = geometry.winged_vtol_geometry(**WINGED)
        dart = geometry.interceptor_geometry(**DART)
        scene = geometry.lineup([winged, dart], labels=["isr", "dash"])
        assert len(scene["parts"]) == 12
        assert {p["name"].split(":")[0] for p in scene["parts"]} == \
            {"isr", "dash"}
        # widths are preserved, meshes do not overlap, ground is shared
        width = sum(m["bounds"][1][0] - m["bounds"][0][0]
                    for m in (winged, dart)) + 0.25
        assert scene["bounds"][1][0] - scene["bounds"][0][0] == \
            pytest.approx(width, abs=1e-3)
        assert scene["bounds"][0][1] == pytest.approx(
            min(m["bounds"][0][1] for m in (winged, dart)), abs=1e-3)

    def test_validates(self):
        with pytest.raises(AnalysisError):
            geometry.lineup([])
        with pytest.raises(AnalysisError):
            geometry.lineup([geometry.interceptor_geometry(**DART)],
                            labels=["a", "b"])


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
