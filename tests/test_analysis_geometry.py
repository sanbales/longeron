"""Spike tests: parametric mix geometry -- mesh sanity and scaling."""

from math import pi
from pathlib import Path

import pytest

import sysml2
from sysml2.analysis import AnalysisError, geometry

EXAMPLES = Path(__file__).parent.parent / "examples"

RACER = {"prop_diameter_in": 5.0, "motor_mass": 0.033, "battery_mass": 0.19, "esc_mass": 0.012}
CRUISER = {"prop_diameter_in": 10.0, "motor_mass": 0.056, "battery_mass": 0.18, "esc_mass": 0.009}


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
        ax, ay, az = vertices[a : a + 3]
        bx, by, bz = vertices[b : b + 3]
        cx, cy, cz = vertices[c : c + 3]
        total += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    return total / 6.0


def _watertight(vertices, faces):
    """Every directed edge is matched by its reverse exactly once
    (after merging positionally-duplicated vertices)."""

    canonical: dict[tuple[float, float, float], int] = {}
    index_of = []
    for i in range(0, len(vertices), 3):
        key = (round(vertices[i], 7), round(vertices[i + 1], 7), round(vertices[i + 2], 7))
        index_of.append(canonical.setdefault(key, len(canonical)))
    edges: dict[tuple[int, int], int] = {}
    for i in range(0, len(faces), 3):
        tri = [index_of[faces[i + k]] for k in range(3)]
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            edges[(a, b)] = edges.get((a, b), 0) + 1
    return all(count == 1 and edges.get((b, a)) == 1 for (a, b), count in edges.items())


def _component_boxes(part):
    """Axis-aligned bounds of each connected component of a merged mesh
    (vertices merged positionally, components joined by shared faces)."""

    vertices, faces = part["vertices"], part["faces"]
    canonical: dict[tuple[float, float, float], int] = {}
    index_of = []
    for i in range(0, len(vertices), 3):
        key = (round(vertices[i], 7), round(vertices[i + 1], 7), round(vertices[i + 2], 7))
        index_of.append(canonical.setdefault(key, len(canonical)))
    parent = list(range(len(canonical)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(0, len(faces), 3):
        a = find(index_of[faces[i]])
        for k in (1, 2):
            b = find(index_of[faces[i + k]])
            parent[b] = a
    boxes: dict[int, list[list[float]]] = {}
    for v in range(len(index_of)):
        root = find(index_of[v])
        x, y, z = vertices[3 * v : 3 * v + 3]
        lo, hi = boxes.setdefault(root, [[x, y, z], [x, y, z]])
        for axis, c in enumerate((x, y, z)):
            lo[axis] = min(lo[axis], c)
            hi[axis] = max(hi[axis], c)
    return list(boxes.values())


def _disjoint(box_a, box_b):
    """True iff the two AABBs are strictly separated on some axis."""

    (alo, ahi), (blo, bhi) = box_a, box_b
    return any(ahi[axis] < blo[axis] or bhi[axis] < alo[axis] for axis in range(3))


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
        assert [p["name"] for p in mesh["parts"]] == ["frame", "motors", "props", "battery", "esc"]
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
        assert hi[0] == pytest.approx(spacing / 2 + 5.0 * geometry.IN, abs=1e-3)
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
            (0, 0, 0), (0.5, 0, 0), (0, 0.5, 0), (0, 0, 2), (0.25, 0, 0), (0, 0.25, 0)
        )
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


WINGED = {
    "wing_span": 2.6,
    "wing_area": 0.624,
    "taper": 0.6,
    "fuselage_length": 0.95,
    "prop_diameter": 0.24,
    "motor_mass": 0.092,
    "battery_mass": 1.95,
}
DART = {
    "body_length": 1.25,
    "wing_span": 1.05,
    "wing_area": 0.179,
    "taper": 0.5,
    "prop_diameter": 0.24,
    "motor_mass": 0.15,
    "battery_mass": 0.5,
}
TEARDROP = {
    "fuselage_length": 0.62,
    "prop_diameter": 0.24,
    "motor_mass": 0.092,
    "battery_mass": 0.98,
}


def _thickest(profile):
    """Max thickness fraction of a chord-normalized closed section."""

    return max(y for _, y in profile) - min(y for _, y in profile)


class TestNacaProfile:
    def test_thickness_matches_the_code(self):
        # last two digits / 100 = max thickness fraction of chord
        for code, spec in (("2412", 0.12), ("0009", 0.09), ("0025", 0.25)):
            profile = geometry.naca4_profile(code, 24)
            assert len(profile) == 24
            assert _thickest(profile) == pytest.approx(spec, rel=0.03)

    def test_cambered_versus_symmetric(self):
        cambered = geometry.naca4_profile("2412", 24)
        assert sum(y for _, y in cambered) > 0.05  # mean camber is up
        symmetric = geometry.naca4_profile("0009", 24)
        points = {(round(x, 9), round(y, 9)) for x, y in symmetric}
        assert all((x, -y) in points for x, y in points)  # mirror-true

    def test_closed_and_chord_normalized(self):
        profile = geometry.naca4_profile("2412", 24)
        xs = [x for x, _ in profile]
        assert max(xs) == pytest.approx(1.0, abs=1e-9)  # trailing edge
        assert min(xs) == pytest.approx(0.0, abs=0.02)  # leading edge

    def test_validates(self):
        with pytest.raises(AnalysisError):
            geometry.naca4_profile("24123")
        with pytest.raises(AnalysisError):
            geometry.naca4_profile("24x2")
        with pytest.raises(AnalysisError):
            geometry.naca4_profile("2412", points=4)


def _chord_at(part, coord, station, tol=0.02, axis=0):
    """(le, te) chordwise extent of a lifting surface at one span station.

    ``coord`` picks the span axis to filter on, ``axis`` the chord axis to
    measure (0 = x for cruise-frame builders, 1 = y for the tail-sitter
    baked in hover attitude)."""

    vertices = part["vertices"]
    xs = [
        vertices[i + axis]
        for i in range(0, len(vertices), 3)
        if abs(vertices[i + coord] - station) < tol
    ]
    assert xs, f"no section vertices near station {station}"
    return max(xs), min(xs)


class TestWingedVtolGeometry:
    def test_parts_and_solidity(self):
        mesh = geometry.winged_vtol_geometry(**WINGED)
        assert [p["name"] for p in mesh["parts"]] == [
            "frame",
            "wing",
            "tail",
            "motors",
            "props",
            "battery",
        ]
        assert len({p["color"] for p in mesh["parts"]}) == 6
        for part in mesh["parts"]:
            assert _volume(part["vertices"], part["faces"]) > 0

    def test_to_scale_span(self):
        mesh = geometry.winged_vtol_geometry(**WINGED)
        lo, hi = mesh["bounds"]
        # z extent: wing tips plus the wingtip lift disks (radius 0.12)
        assert hi[2] == pytest.approx(2.6 / 2 + 0.12, abs=1e-3)
        assert lo[2] == pytest.approx(-(2.6 / 2 + 0.12), abs=1e-3)
        # the 2.6 m wing dwarfs the quad frame
        quad = geometry.drone_geometry(
            prop_diameter_in=0.33 / geometry.IN, motor_mass=0.092, battery_mass=0.98, esc_mass=0.014
        )
        assert (hi[2] - lo[2]) > 2.5 * (quad["bounds"][1][2] - quad["bounds"][0][2])

    def test_exactly_four_horizontal_lift_props(self):
        """The hover story: four wingtip rotors, every disk's surface
        normal straight up (+Y) in the baked hover attitude."""

        mesh = geometry.winged_vtol_geometry(**WINGED)
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        assert props["opacity"] < 1.0  # spinning disks stay translucent
        disks = _component_boxes(props)
        assert len(disks) == 4
        for lo, hi in disks:
            assert hi[1] - lo[1] < 0.004  # wafer-thin in Y ...
            assert hi[0] - lo[0] > 10 * (hi[1] - lo[1])  # ... wide in X
            assert hi[2] - lo[2] > 10 * (hi[1] - lo[1])  # ... and in Z
        # catalog props on the main-pair tips, smaller ones on the
        # secondary pair (the ratio baked into diskAreaFactor)
        spans = sorted(box[1][2] - box[0][2] for box in disks)
        assert spans[0] == pytest.approx(spans[1], abs=1e-3)
        assert spans[2] == pytest.approx(spans[3], abs=1e-3)
        assert spans[0] == pytest.approx(geometry._SECONDARY_PROP_RATIO * spans[2], rel=0.02)

    def test_thrust_axes_parallel_to_the_body_axis(self):
        """The tail-sitter requirement, encoded: the fuselage's long axis
        points up (hover attitude) and every prop disk's surface normal
        is the SAME axis -- thrust parallel to the chords/body axis, not
        perpendicular to the wing surface."""

        mesh = geometry.winged_vtol_geometry(**WINGED)
        frame = next(p for p in mesh["parts"] if p["name"] == "frame")
        boxes = _component_boxes(frame)
        assert len(boxes) == 1  # one slender fuselage: no booms
        lo, hi = boxes[0]
        extents = [hi[i] - lo[i] for i in range(3)]
        body_axis = extents.index(max(extents))
        assert body_axis == 1  # nose up
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        for dlo, dhi in _component_boxes(props):
            d = [dhi[i] - dlo[i] for i in range(3)]
            assert d.index(min(d)) == body_axis  # normal == body axis

    def test_minimal_slender_fuselage_no_boom_tail(self):
        mesh = geometry.winged_vtol_geometry(**WINGED)
        frame = next(p for p in mesh["parts"] if p["name"] == "frame")
        boxes = _component_boxes(frame)
        assert len(boxes) == 1  # the double-boom tail is gone
        lo, hi = boxes[0]
        length = hi[1] - lo[1]  # body axis is vertical in hover
        assert length == pytest.approx(0.95, abs=1e-3)
        assert max(hi[0] - lo[0], hi[2] - lo[2]) < length / 6  # slender

    def test_cruciform_span_ratio(self):
        """A '+' cruciform: the main pair (z) is strictly longer than the
        secondary pair (x), at the documented ratio, and each pair is a
        thin airfoil in the other pair's span direction."""

        mesh = geometry.winged_vtol_geometry(**WINGED)
        wing = next(p for p in mesh["parts"] if p["name"] == "wing")
        tail = next(p for p in mesh["parts"] if p["name"] == "tail")
        wing_span = max(wing["vertices"][2::3]) - min(wing["vertices"][2::3])
        tail_span = max(tail["vertices"][0::3]) - min(tail["vertices"][0::3])
        assert wing_span == pytest.approx(2.6, abs=1e-3)
        assert tail_span == pytest.approx(geometry._SECONDARY_SPAN_RATIO * 2.6, rel=0.01)
        assert wing_span > tail_span
        # thin across their thickness axes: airfoils, not slabs
        wing_thick = max(wing["vertices"][0::3]) - min(wing["vertices"][0::3])
        tail_thick = max(tail["vertices"][2::3]) - min(tail["vertices"][2::3])
        assert wing_thick < 0.1 * wing_span
        assert tail_thick < 0.1 * tail_span

    @pytest.mark.parametrize("prop_diameter", [0.24, 0.33, 0.51])
    def test_no_two_props_intersect(self, prop_diameter):
        """The reported overlap bug, encoded: every pair of prop disks is
        strictly AABB-separated, even for the largest catalog prop."""

        mesh = geometry.winged_vtol_geometry(**{**WINGED, "prop_diameter": prop_diameter})
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        disks = _component_boxes(props)
        assert len(disks) == 4
        for i in range(len(disks)):
            for j in range(i + 1, len(disks)):
                assert _disjoint(disks[i], disks[j]), (i, j)

    def test_wing_is_an_unswept_airfoil_loft(self):
        """Zero sweep (straight quarter-chord), chord = area/span, and a
        real NACA-2412 section instead of a rectangular slab.  In the
        hover attitude the chords run along +Y (the body axis)."""

        mesh = geometry.winged_vtol_geometry(**WINGED)
        wing = next(p for p in mesh["parts"] if p["name"] == "wing")
        mean = 0.624 / 2.6
        root = 2.0 * mean / 1.6
        root_le, root_te = _chord_at(wing, 2, 0.0, axis=1)
        tip_le, tip_te = _chord_at(wing, 2, 1.29, tol=0.02, axis=1)
        assert root_le - root_te == pytest.approx(root, rel=0.02)
        assert tip_le - tip_te == pytest.approx(0.6 * root, rel=0.03)
        # straight quarter-chord: identical at root and tip
        root_qc = root_le - 0.25 * (root_le - root_te)
        tip_qc = tip_le - 0.25 * (tip_le - tip_te)
        assert root_qc == pytest.approx(tip_qc, abs=0.003)
        # section thickness ~ NACA 2412 (12% of chord), not a slab
        vertices = wing["vertices"]
        xs = [vertices[i] for i in range(0, len(vertices), 3) if abs(vertices[i + 2]) < 0.02]
        assert max(xs) - min(xs) == pytest.approx(0.12 * root, rel=0.06)
        assert len({round(x, 4) for x in xs}) > 6  # curved, not boxy

    def test_wing_aspect_ratio_from_the_model(self):
        mesh = geometry.winged_vtol_geometry(**WINGED)
        wing = next(p for p in mesh["parts"] if p["name"] == "wing")
        span = max(wing["vertices"][2::3]) - min(wing["vertices"][2::3])
        chord = max(wing["vertices"][1::3]) - min(wing["vertices"][1::3])
        assert span == pytest.approx(2.6, abs=1e-3)
        # chordwise (y) extent = root chord; AR = span / mean chord
        assert chord == pytest.approx(2.0 * 0.624 / 2.6 / 1.6, rel=0.02)
        assert 6.0 < span / (0.624 / 2.6) < 14.0

    def test_validates_dimensions(self):
        with pytest.raises(AnalysisError):
            geometry.winged_vtol_geometry(**{**WINGED, "wing_span": 0.0})
        with pytest.raises(AnalysisError):
            geometry.winged_vtol_geometry(**{**WINGED, "wing_area": 0.0})


class TestInterceptorGeometry:
    def test_parts_and_solidity(self):
        mesh = geometry.interceptor_geometry(**DART)
        assert [p["name"] for p in mesh["parts"]] == [
            "frame",
            "wing",
            "tail",
            "motors",
            "props",
            "battery",
        ]
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

    def test_wing_is_an_unswept_thin_airfoil(self):
        """The interceptor wing gets the same treatment: straight
        quarter-chord, NACA-0009 section, chord from area/span."""

        mesh = geometry.interceptor_geometry(**DART)
        wing = next(p for p in mesh["parts"] if p["name"] == "wing")
        mean = 0.179 / 1.05
        root = 2.0 * mean / 1.5
        root_le, root_te = _chord_at(wing, 2, 0.0)
        tip_le, tip_te = _chord_at(wing, 2, 0.515, tol=0.011)
        assert root_le - root_te == pytest.approx(root, rel=0.02)
        root_qc = root_le - 0.25 * (root_le - root_te)
        tip_qc = tip_le - 0.25 * (tip_le - tip_te)
        assert root_qc == pytest.approx(tip_qc, abs=0.003)
        vertices = wing["vertices"]
        ys = [vertices[i + 1] for i in range(0, len(vertices), 3) if abs(vertices[i + 2]) < 0.02]
        assert max(ys) - min(ys) == pytest.approx(0.09 * root, rel=0.06)

    def test_pusher_prop_at_the_stern(self):
        mesh = geometry.interceptor_geometry(**DART)
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        assert max(props["vertices"][0::3]) < 0  # aft of the midpoint

    def test_validates_dimensions(self):
        with pytest.raises(AnalysisError):
            geometry.interceptor_geometry(**{**DART, "body_length": 0.0})


class TestTeardropQuadGeometry:
    def test_parts_and_solidity(self):
        mesh = geometry.teardrop_quad_geometry(**TEARDROP)
        assert [p["name"] for p in mesh["parts"]] == ["frame", "motors", "props", "battery"]
        for part in mesh["parts"]:
            assert _volume(part["vertices"], part["faces"]) > 0

    def test_teardrop_shell_stands_on_end(self):
        """A lathed body of revolution stood on end: vertical long axis,
        blunt maximum section in the upper half (nose up), and slender
        against its length."""

        mesh = geometry.teardrop_quad_geometry(**TEARDROP)
        frame = next(p for p in mesh["parts"] if p["name"] == "frame")
        shell_box = max(_component_boxes(frame), key=lambda box: box[1][1] - box[0][1])
        y_lo, y_hi = shell_box[0][1], shell_box[1][1]
        assert y_hi - y_lo == pytest.approx(0.62, abs=1e-3)
        vertices = frame["vertices"]
        widest = max(
            (vertices[i : i + 3] for i in range(0, len(vertices), 3)),
            key=lambda v: v[0] ** 2 + v[2] ** 2,
        )
        assert widest[1] > (y_lo + y_hi) / 2  # blunt nose is UP
        radius = max(
            (vertices[i] ** 2 + vertices[i + 2] ** 2) ** 0.5
            for i in range(0, len(vertices), 3)
            if abs(vertices[i]) < 0.06 and abs(vertices[i + 2]) < 0.06
        )
        assert radius < 0.15 * 0.62  # genuinely streamlined

    def test_body_long_axis_normal_to_the_rotor_discs(self):
        """The reported orientation bug, encoded: the bullet's long axis
        is PERPENDICULAR to the rotor discs (dot(body axis, disc normal)
        ~ 1) and the shell pierces the rotor plane."""

        mesh = geometry.teardrop_quad_geometry(**TEARDROP)
        frame = next(p for p in mesh["parts"] if p["name"] == "frame")
        shell_box = max(_component_boxes(frame), key=lambda box: box[1][1] - box[0][1])
        extents = [shell_box[1][i] - shell_box[0][i] for i in range(3)]
        body_axis = extents.index(max(extents))
        assert body_axis == 1  # the bullet stands on end
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        disks = _component_boxes(props)
        for dlo, dhi in disks:
            d = [dhi[i] - dlo[i] for i in range(3)]
            assert d.index(min(d)) == body_axis  # normal || body axis
        # the body pierces the rotor plane: disks sit strictly between
        # the shell's nose and tail
        rotor_plane = min(lo[1] for lo, _ in disks)
        assert shell_box[0][1] < rotor_plane < shell_box[1][1]

    def test_four_horizontal_props_no_overlap(self):
        mesh = geometry.teardrop_quad_geometry(**TEARDROP)
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        disks = _component_boxes(props)
        assert len(disks) == 4
        for lo, hi in disks:
            assert hi[1] - lo[1] < 0.004  # horizontal: wafer-thin in Y
            assert hi[0] - lo[0] == pytest.approx(0.24, abs=1e-3)
        for i in range(4):
            for j in range(i + 1, 4):
                assert _disjoint(disks[i], disks[j]), (i, j)

    def test_props_clear_the_hull_radially(self):
        """The discs surround the vertical hull as a planar quad: each
        disc's inner edge keeps clear of the hull's maximum radius."""

        mesh = geometry.teardrop_quad_geometry(**TEARDROP)
        frame = next(p for p in mesh["parts"] if p["name"] == "frame")
        shell_box = max(_component_boxes(frame), key=lambda box: box[1][1] - box[0][1])
        hull_r = max(shell_box[1][0], -shell_box[0][0], shell_box[1][2], -shell_box[0][2])
        props = next(p for p in mesh["parts"] if p["name"] == "props")
        for lo, hi in _component_boxes(props):
            cx = (lo[0] + hi[0]) / 2
            cz = (lo[2] + hi[2]) / 2
            disc_r = (hi[0] - lo[0]) / 2
            assert (cx**2 + cz**2) ** 0.5 - disc_r > hull_r

    def test_bounds_enclose_all_vertices(self):
        mesh = geometry.teardrop_quad_geometry(**TEARDROP)
        (lo, hi) = mesh["bounds"]
        for part in mesh["parts"]:
            for axis in range(3):
                coords = part["vertices"][axis::3]
                assert min(coords) >= lo[axis] - 1e-9
                assert max(coords) <= hi[axis] + 1e-9

    def test_validates_dimensions(self):
        with pytest.raises(AnalysisError):
            geometry.teardrop_quad_geometry(**{**TEARDROP, "fuselage_length": 0.0})


@pytest.fixture(scope="module")
def mission_study():
    from sysml2.analysis import trades

    catalog = sysml2.load(EXAMPLES / "uav_missions.sysml", cache=False)
    return trades.TradeStudy(catalog, "UavMissions::InterceptUav")


class TestMissionBridge:
    def test_family_dispatch(self, mission_study):
        def mix(airframe):
            return mission_study.evaluate(
                {
                    "airframe": airframe,
                    "motors": "stdMotor",
                    "props": "slimProp",
                    "battery": "packMid",
                    "material": "aluminum",
                }
            )

        quad = geometry.mission_geometry(mission_study, mix("boxQuad"))
        assert [p["name"] for p in quad["parts"]] == ["frame", "motors", "props", "battery", "esc"]
        teardrop = geometry.mission_geometry(mission_study, mix("teardropQuad"))
        assert [p["name"] for p in teardrop["parts"]] == ["frame", "motors", "props", "battery"]
        winged = geometry.mission_geometry(mission_study, mix("vtolWing"))
        assert any(p["name"] == "wing" for p in winged["parts"])
        dart = geometry.mission_geometry(mission_study, mix("dartInterceptor"))
        span_z = dart["bounds"][1][2] - dart["bounds"][0][2]
        assert span_z == pytest.approx(1.05, abs=1e-3)

    def test_sized_arms_show_in_the_mesh(self, mission_study):
        """The structural sizing reaches the geometry: a mix whose
        metrics carry armOuterDiameter draws its arms at that diameter,
        so the harder-loaded aluminum build is visibly thicker in Y than
        the same mix in carbon (stiffness sizes the aluminum wall)."""

        def arm_thickness(material):
            arch = mission_study.evaluate(
                {
                    "airframe": "boxQuad",
                    "motors": "sprintMotor",
                    "props": "lifterProp",  # long arms: stiffness governs
                    "battery": "packMid",
                    "material": material,
                }
            )
            assert arch.metrics["armOuterDiameter"] > 0
            mesh = geometry.mission_geometry(mission_study, arch)
            frame = next(p for p in mesh["parts"] if p["name"] == "frame")
            ys = frame["vertices"][1::3]
            return max(ys), arch.metrics["armOuterDiameter"]

        (top_al, d_al), (top_cf, d_cf) = arm_thickness("aluminum"), arm_thickness("carbonFiber")
        assert d_al > d_cf  # aluminum needs more wall for the same load
        assert top_al > top_cf  # ... and the mesh genuinely shows it
        assert top_al == pytest.approx(d_al / 2, abs=1e-4)

    def test_params_read_the_selected_variants(self, mission_study):
        arch = mission_study.evaluate(
            {
                "airframe": "vtolWing",
                "motors": "ecoMotor",
                "props": "lifterProp",
                "battery": "packLite",
                "material": "carbonFiber",
            }
        )
        params = geometry.mission_params(mission_study, arch)
        assert params["wing_span"] == 2.6
        assert params["wing_area"] == 0.624
        assert params["prop_diameter"] == 0.51
        assert params["motor_mass"] == 0.058
        assert params["battery_mass"] == 0.5

    def test_missing_point_is_loud(self, mission_study):
        arch = mission_study.evaluate(
            {
                "airframe": "boxQuad",
                "motors": "stdMotor",
                "props": "slimProp",
                "battery": "packMid",
                "material": "aluminum",
            }
        )
        arch.selection.pop("battery")
        with pytest.raises(AnalysisError):
            geometry.mission_params(mission_study, arch)


class TestLineup:
    def test_side_by_side_at_true_scale(self):
        winged = geometry.winged_vtol_geometry(**WINGED)
        dart = geometry.interceptor_geometry(**DART)
        scene = geometry.lineup([winged, dart], labels=["isr", "dash"])
        assert len(scene["parts"]) == 12
        assert {p["name"].split(":")[0] for p in scene["parts"]} == {"isr", "dash"}
        # widths are preserved, meshes do not overlap, ground is shared
        width = sum(m["bounds"][1][0] - m["bounds"][0][0] for m in (winged, dart)) + 0.25
        assert scene["bounds"][1][0] - scene["bounds"][0][0] == pytest.approx(width, abs=1e-3)
        assert scene["bounds"][0][1] == pytest.approx(
            min(m["bounds"][0][1] for m in (winged, dart)), abs=1e-3
        )

    def test_validates(self):
        with pytest.raises(AnalysisError):
            geometry.lineup([])
        with pytest.raises(AnalysisError):
            geometry.lineup([geometry.interceptor_geometry(**DART)], labels=["a", "b"])


class TestArchitectureBridge:
    def test_params_from_mix(self, study):
        arch = study.evaluate(
            {"motors": "sunnySky2212", "props": "apc1045", "battery": "lipo3s2200", "esc": "esc20"}
        )
        params = geometry.architecture_params(study, arch)
        assert params == {
            "motor_mass": 0.056,
            "prop_diameter_in": 10.0,
            "battery_mass": 0.18,
            "esc_mass": 0.009,
        }
        mesh = geometry.architecture_geometry(study, arch)
        assert len(mesh["parts"]) == 5

    def test_missing_point_is_loud(self, study):
        arch = study.evaluate(
            {"motors": "emax2306", "props": "hq5x43", "battery": "lipo4s1500", "esc": "esc45"}
        )
        arch.selection.pop("esc")
        with pytest.raises(AnalysisError):
            geometry.architecture_params(study, arch)


class TestCadqueryBridge:
    def test_assembly(self):
        pytest.importorskip("cadquery")
        assembly = geometry.to_cadquery(**RACER)
        names = {child.name for child in assembly.children}
        assert names == {
            "frame",
            "motor1",
            "motor2",
            "motor3",
            "motor4",
            "prop1",
            "prop2",
            "prop3",
            "prop4",
            "battery",
            "esc",
        }

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
