"""Spike tests: parametric mix geometry -- mesh sanity and scaling."""

from math import acos, pi, radians, sqrt, tan
from pathlib import Path
from typing import ClassVar

import pytest

import longeron
from longeron.analysis import AnalysisError, geometry

EXAMPLES = Path(__file__).parent.parent / "examples"

RACER = {"prop_diameter_in": 5.0, "motor_mass": 0.033, "battery_mass": 0.19, "esc_mass": 0.012}
CRUISER = {"prop_diameter_in": 10.0, "motor_mass": 0.056, "battery_mass": 0.18, "esc_mass": 0.009}

QUAD_MAP = {
    "frame": "Drone::QuadCopter::chassis",
    "motors": "Drone::QuadCopter::motors",
    "props": "Drone::QuadCopter::propellers",
    "battery": "Drone::QuadCopter::battery",
}


@pytest.fixture(scope="module")
def study():
    from longeron.analysis import trades

    catalog = longeron.load(EXAMPLES / "drone_catalog.sysml", cache=False)
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


class TestSplitInstances:
    """``split_instances=True`` re-partitions the motor/prop meshes
    per instance; ``False`` (the default) is byte-identical to the
    pre-flag behavior."""

    SPLIT_NAMES: ClassVar[list[str]] = [
        "frame",
        *[f"motor{i}" for i in (1, 2, 3, 4)],
        *[f"prop{i}" for i in (1, 2, 3, 4)],
        "battery",
        "esc",
    ]

    def test_default_is_byte_identical(self):
        import json

        merged = json.dumps(geometry.drone_geometry(**RACER), sort_keys=True)
        explicit = json.dumps(
            geometry.drone_geometry(**RACER, split_instances=False), sort_keys=True
        )
        assert merged == explicit

    def test_split_part_names_match_the_cadquery_children(self):
        mesh = geometry.drone_geometry(**RACER, split_instances=True)
        assert [p["name"] for p in mesh["parts"]] == self.SPLIT_NAMES

    def test_instances_inherit_the_kind_color_and_opacity(self):
        mesh = geometry.drone_geometry(**RACER, split_instances=True)
        by_name = {p["name"]: p for p in mesh["parts"]}
        for i in (1, 2, 3, 4):
            assert by_name[f"motor{i}"]["color"] == geometry.COLORS["motors"]
            assert by_name[f"motor{i}"]["opacity"] == 1.0
            assert by_name[f"prop{i}"]["color"] == geometry.COLORS["props"]
            assert by_name[f"prop{i}"]["opacity"] == 0.55

    def test_split_is_a_pure_repartition_of_the_merged_mesh(self):
        # concatenating the instance parts (with face-index offsets)
        # reproduces the merged part exactly -- same bytes, same order
        merged = geometry.drone_geometry(**CRUISER)
        split = geometry.drone_geometry(**CRUISER, split_instances=True)
        merged_by_name = {p["name"]: p for p in merged["parts"]}
        split_by_name = {p["name"]: p for p in split["parts"]}
        for kind in ("motor", "prop"):
            vertices: list[float] = []
            faces: list[int] = []
            for i in (1, 2, 3, 4):
                part = split_by_name[f"{kind}{i}"]
                offset = len(vertices) // 3
                vertices += part["vertices"]
                faces += [f + offset for f in part["faces"]]
            assert vertices == merged_by_name[f"{kind}s"]["vertices"]
            assert faces == merged_by_name[f"{kind}s"]["faces"]
        for name in ("frame", "battery", "esc"):
            assert split_by_name[name] == merged_by_name[name]
        assert split["bounds"] == merged["bounds"] and split["unit"] == merged["unit"]

    def test_each_instance_is_a_watertight_solid(self):
        mesh = geometry.drone_geometry(**RACER, split_instances=True)
        instances = [p for p in mesh["parts"] if p["name"][-1].isdigit()]
        assert len(instances) == 8
        for part in instances:
            assert _watertight(part["vertices"], part["faces"]), part["name"]
            assert _volume(part["vertices"], part["faces"]) > 0

    def test_split_mode_stamps_the_cad_recipe(self):
        # the parametric recipe the CAD-native checks rebuild solids from
        mesh = geometry.drone_geometry(**RACER, split_instances=True)
        assert mesh["cad"] == {
            **RACER,
            "arm_thickness": geometry._ARM_THICKNESS,
            "arm_width": geometry._ARM_WIDTH,
            "motor_spacing": None,
        }
        assert all(disc["thickness"] == 0.0025 for disc in mesh["discs"])
        assert "cad" not in geometry.drone_geometry(**RACER)  # merged mode: no recipe

    def test_instances_tag_to_m0_individual_ids(self):
        mesh = geometry.drone_geometry(**RACER, split_instances=True)
        mapping = {
            **{f"motor{i + 1}": f"Drone::QuadCopter#0.motors#{i}" for i in range(4)},
            **{f"prop{i + 1}": f"Drone::QuadCopter#0.propellers#{i}" for i in range(4)},
        }
        tagged = geometry.tag_parts(mesh, mapping)
        keys = {p["name"]: p.get("key") for p in tagged["parts"]}
        assert keys["motor3"] == "Drone::QuadCopter#0.motors#2"
        assert keys["prop3"] == "Drone::QuadCopter#0.propellers#2"
        assert keys["frame"] is None  # unmapped parts stay untagged


#: the stock examples/drone.sysml design point (see the model's defaults)
STOCK = {"prop_diameter_in": 10.0, "motor_mass": 0.055, "battery_mass": 0.39, "esc_mass": 0.012}
STOCK_CAMERA = {
    "x": 0.06,
    "y": 0.0,
    "z": 0.0,
    "azimuth": 0.0,
    "elevation": -15.0,
    "fieldOfView": 50.0,
}


def _plate_mesh(*, sx=0.1, sy=20.0, sz=20.0, cx=1.0, cy=0.0, cz=0.0, name="plate"):
    """A single-box mesh dict for closed-form check cases."""

    vertices, faces = geometry._box(sx, sy, sz, cx=cx, cy=cy, cz=cz)
    return {
        "unit": "m",
        "parts": [
            {"name": name, "color": "#000000", "opacity": 1.0, "vertices": vertices, "faces": faces}
        ],
    }


class TestCameraOcclusion:
    """Closed-form view-cone quadrature cases + the stock design point.

    All the cases here run the ``mesh`` engine (the stdlib fallback);
    the exact-CAD engine is validated against the same closed forms in
    :class:`TestCadEngine`.  The slab cases align their faces with the
    quadrature's axial cell edges (multiples of ``length / resolution``)
    and span the full cone cross-section, so the deterministic grid
    integrates them EXACTLY, not just approximately.
    """

    CAM: ClassVar[dict[str, float]] = {
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "azimuth": 0.0,
        "elevation": 0.0,
        "fieldOfView": 60.0,
    }

    def test_unobstructed_cone_is_exactly_zero(self):
        # the only geometry sits BEHIND the camera: nothing in the cone
        mesh = _plate_mesh(cx=-1.0)
        assert geometry.camera_occlusion(mesh, self.CAM, sensing_range=1.0) == 0.0

    def test_slab_through_the_cone_is_the_analytic_volume(self):
        # a wall from x = 0.25 to 0.75 covering the whole cross-section:
        # the cone volume between depths d0..d1 is proportional to
        # d1^3 - d0^3, so the occluded fraction is exactly that
        mesh = _plate_mesh(sx=0.5, cx=0.5)
        fraction = geometry.camera_occlusion(mesh, self.CAM, sensing_range=1.0)
        assert fraction == pytest.approx(0.75**3 - 0.25**3, rel=1e-9)

    def test_half_plane_slab_is_half_the_slab(self):
        # the same slab cut at the boresight plane (y > 0 only): the
        # azimuthal cells split evenly, so exactly half the slab counts
        mesh = _plate_mesh(sx=0.5, cx=0.5, cy=10.0)
        fraction = geometry.camera_occlusion(mesh, self.CAM, sensing_range=1.0)
        assert fraction == pytest.approx((0.75**3 - 0.25**3) / 2.0, rel=1e-9)

    def test_interpenetrating_sub_solids_count_once(self):
        # a merged part (two boxes sharing x in [0.45, 0.55], like the
        # frame's plate + arms) occludes its UNION, not its XOR -- the
        # per-component parity split is what makes this hold
        blob = geometry._merge(
            geometry._box(0.3, 20.0, 20.0, cx=0.4), geometry._box(0.3, 20.0, 20.0, cx=0.6)
        )
        mesh = {
            "unit": "m",
            "parts": [
                {
                    "name": "blob",
                    "color": "#000000",
                    "opacity": 1.0,
                    "vertices": blob[0],
                    "faces": blob[1],
                }
            ],
        }
        fraction = geometry.camera_occlusion(mesh, self.CAM, sensing_range=1.0)
        assert fraction == pytest.approx(0.75**3 - 0.25**3, rel=1e-9)

    def test_report_carries_the_full_story(self):
        mesh = _plate_mesh(sx=0.5, cx=0.5)
        report = geometry.occlusion_report(mesh, self.CAM, sensing_range=1.0)
        assert report["engine"] == "mesh"
        assert report["sensingRange"] == 1.0
        cone_volume = pi / 3.0 * tan(radians(30.0)) ** 2
        assert report["coneVolume"] == pytest.approx(cone_volume, rel=1e-12)
        assert set(report["obstructions"]) == {"plate"}
        assert report["obstructions"]["plate"] == pytest.approx(report["occludedVolume"])
        assert report["occludedVolume"] == pytest.approx(
            report["occludedFraction"] * cone_volume, rel=1e-9
        )

    def test_stock_drone_cone_is_clear(self):
        # the stock camera placement genuinely sees past the airframe:
        # nothing intersects the view cone, so the measure is exactly 0.0
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        report = geometry.occlusion_report(mesh, engine="mesh")
        assert report["occludedFraction"] == 0.0
        assert report["obstructions"] == {}

    def test_backward_camera_is_blocked_by_the_airframe(self):
        # the same camera yawed 180 degrees looks straight back through
        # the stack: the battery is the biggest thing in the cone
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        report = geometry.occlusion_report(
            mesh, camera={**STOCK_CAMERA, "azimuth": 180.0}, engine="mesh"
        )
        assert report["occludedFraction"] > 0.0
        assert next(iter(report["obstructions"])) == "battery"
        assert "camera" not in report["obstructions"]  # its own body is excluded

    def test_deterministic(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        camera = {**STOCK_CAMERA, "azimuth": 180.0}
        first = geometry.occlusion_report(mesh, camera=camera, engine="mesh")
        assert first == geometry.occlusion_report(mesh, camera=camera, engine="mesh")

    def test_missing_camera_fails_loudly(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True)
        with pytest.raises(AnalysisError, match="camera"):
            geometry.camera_occlusion(mesh)
        with pytest.raises(AnalysisError, match="missing"):
            geometry.camera_occlusion(mesh, {"x": 0.0})

    def test_validates_range_and_resolution(self):
        mesh = _plate_mesh(cx=-1.0)
        with pytest.raises(AnalysisError, match="range"):
            geometry.camera_occlusion(mesh, self.CAM, sensing_range=0.0)
        with pytest.raises(AnalysisError, match="resolution"):
            geometry.camera_occlusion(mesh, self.CAM, resolution=0)


#: the analytic lens: intersection volume of two coplanar discs of
#: radius r whose centres sit d apart (times the disc thickness)
def _lens_volume(r, d, thickness):
    return (2.0 * r * r * acos(d / (2.0 * r)) - (d / 2.0) * sqrt(4.0 * r * r - d * d)) * thickness


class TestDiscOverlap:
    """Closed-form disc-overlap cases + the stock and prop-swap points."""

    @staticmethod
    def _disc_mesh(part_mesh, *, center=(0.0, 0.0, 0.0), radius=0.1, thickness=0.0025):
        mesh = dict(part_mesh)
        mesh["discs"] = [
            {
                "part": "disc",
                "center": list(center),
                "normal": [0.0, 1.0, 0.0],
                "radius": radius,
                "thickness": thickness,
                "exclude": [],
            }
        ]
        return mesh

    def test_clear_disc_is_exactly_zero(self):
        mesh = self._disc_mesh(_plate_mesh(sx=0.2, sy=0.2, sz=0.2, cx=0.0, cy=-0.5))
        assert geometry.disc_overlap(mesh) == 0.0

    def test_half_disc_through_a_box_is_exact(self):
        # a box occupying the half-space x > 0 across the disc's whole
        # thickness: the overlap is exactly half the disc volume, and the
        # equal-area mid-plane quadrature integrates it exactly
        mesh = self._disc_mesh(_plate_mesh(sx=10.0, sy=10.0, sz=20.0, cx=5.0))
        assert geometry.disc_overlap(mesh) == pytest.approx(pi * 0.1**2 * 0.0025 / 2.0, rel=1e-12)

    def test_thickness_scales_the_overlap(self):
        thin = self._disc_mesh(_plate_mesh(sx=10.0, sy=10.0, sz=20.0, cx=5.0))
        thick = self._disc_mesh(_plate_mesh(sx=10.0, sy=10.0, sz=20.0, cx=5.0), thickness=0.005)
        assert geometry.disc_overlap(thick) == pytest.approx(
            2.0 * geometry.disc_overlap(thin), rel=1e-12
        )

    def test_stock_drone_discs_are_clear(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True)
        rows = geometry.overlap_report(mesh, engine="mesh")
        assert [row["disc"] for row in rows] == ["prop1", "prop2", "prop3", "prop4"]
        assert all(row["overlap"] == 0.0 and row["parts"] == {} for row in rows)
        assert geometry.disc_overlap(mesh, engine="mesh") == 0.0

    def test_oversized_prop_on_the_stock_frame_overlaps(self):
        # 12" props bolted onto the frame sized for 10" props: each disc
        # cuts a lens into each of its two neighbours -- the quadrature
        # estimate lands within 2% of the analytic lens volume
        stock_spacing = 10.0 * geometry.IN + 0.02
        mesh = geometry.drone_geometry(
            **{**STOCK, "prop_diameter_in": 12.0},
            split_instances=True,
            motor_spacing=stock_spacing,
        )
        rows = geometry.overlap_report(mesh, engine="mesh")
        lens = _lens_volume(6.0 * geometry.IN, stock_spacing, 0.0025)
        for row in rows:
            assert row["overlap"] == pytest.approx(2.0 * lens, rel=0.02)
            assert all(name.startswith("prop") for name in row["parts"])
            assert len(row["parts"]) == 2  # the two adjacent stations
        assert geometry.disc_overlap(mesh, engine="mesh") == pytest.approx(8.0 * lens, rel=0.02)
        assert geometry.disc_overlap(mesh, engine="mesh") > 0.0  # propClearance violated

    def test_symmetric_stations_report_symmetric_overlaps(self):
        stock_spacing = 10.0 * geometry.IN + 0.02
        mesh = geometry.drone_geometry(
            **{**STOCK, "prop_diameter_in": 12.0},
            split_instances=True,
            motor_spacing=stock_spacing,
        )
        rows = geometry.overlap_report(mesh, engine="mesh")
        assert len({round(row["overlap"], 12) for row in rows}) == 1

    def test_merged_mesh_fails_loudly(self):
        mesh = geometry.drone_geometry(**STOCK)  # no split: no per-station discs
        with pytest.raises(AnalysisError, match="split_instances"):
            geometry.disc_overlap(mesh)

    def test_validates_resolution(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True)
        with pytest.raises(AnalysisError, match="resolution"):
            geometry.overlap_report(mesh, resolution=0)


class TestEngineDispatch:
    """``auto`` prefers CAD, falls back to the mesh quadrature, and the
    explicit engines fail loudly when their prerequisites are missing."""

    def test_auto_uses_mesh_without_cadquery(self, monkeypatch):
        monkeypatch.setattr(geometry, "_cad_available", lambda: False)
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        assert geometry.occlusion_report(mesh)["engine"] == "mesh"
        assert geometry.overlap_report(mesh)[0]["engine"] == "mesh"

    def test_auto_needs_the_stamped_recipe(self, monkeypatch):
        # a synthetic mesh carries no parametric recipe: auto stays on
        # the mesh engine even when cadquery is importable
        monkeypatch.setattr(geometry, "_cad_available", lambda: True)
        report = geometry.occlusion_report(
            _plate_mesh(cx=-1.0), TestCameraOcclusion.CAM, sensing_range=1.0
        )
        assert report["engine"] == "mesh"

    def test_explicit_cad_without_the_extra_is_loud(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def no_cadquery(name, *args, **kwargs):
            if name == "cadquery":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_cadquery)
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        with pytest.raises(ImportError, match="longeron\\[cad\\]"):
            geometry.camera_occlusion(mesh, engine="cad")
        with pytest.raises(ImportError, match="longeron\\[cad\\]"):
            geometry.disc_overlap(mesh, engine="cad")

    def test_unknown_engine_is_loud(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        with pytest.raises(AnalysisError, match="engine"):
            geometry.occlusion_report(mesh, engine="frustum")


class TestCadEngine:
    """Exact CAD booleans (skipped without the ~1 GB ``cad`` extra).

    Mirrors :class:`TestCameraOcclusion` / :class:`TestDiscOverlap`'s
    closed forms against the OCC kernel: the view cone's volume and
    slab intersections are analytic, the prop-swap overlap is the
    analytic two-disc lens, and the stock drone reads exactly clear.
    """

    @pytest.fixture(autouse=True)
    def _needs_cadquery(self):
        pytest.importorskip("cadquery")

    def test_view_cone_volume_is_analytic(self):
        cone = geometry.view_cone(TestCameraOcclusion.CAM, length=1.0)
        assert cone.Volume() == pytest.approx(pi / 3.0 * tan(radians(30.0)) ** 2, rel=1e-12)

    def test_view_cone_apex_axis_and_reach(self):
        camera = {**STOCK_CAMERA, "elevation": 0.0, "azimuth": 180.0}
        cone = geometry.view_cone(camera, length=1.0)
        box = cone.BoundingBox()
        assert box.xmax == pytest.approx(0.06, abs=1e-9)  # apex at the camera
        assert box.xmin == pytest.approx(0.06 - 1.0, abs=1e-9)  # reaches backward
        half = tan(radians(camera["fieldOfView"]) / 2.0)
        assert box.ymax == pytest.approx(half, abs=1e-6)  # base radius at length

    def test_slab_through_the_cone_is_analytic(self):
        import cadquery as cq

        cone = geometry.view_cone(TestCameraOcclusion.CAM, length=1.0)
        plate = cq.Solid.makeBox(0.5, 20.0, 20.0, pnt=cq.Vector(0.25, -10.0, -10.0))
        fraction = cone.intersect(plate).Volume() / cone.Volume()
        assert fraction == pytest.approx(0.75**3 - 0.25**3, rel=1e-9)

    def test_view_cone_validates(self):
        with pytest.raises(AnalysisError, match="length"):
            geometry.view_cone(TestCameraOcclusion.CAM, length=0.0)

    def test_stock_drone_is_exactly_clear(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        report = geometry.occlusion_report(mesh)  # auto picks CAD here
        assert report["engine"] == "cad"
        assert report["occludedFraction"] == 0.0 and report["obstructions"] == {}
        rows = geometry.overlap_report(mesh)
        assert all(row["engine"] == "cad" and row["overlap"] == 0.0 for row in rows)
        assert geometry.geometry_checks(mesh) == {
            "occludedFraction": 0.0,
            "discOverlapVolume": 0.0,
        }

    def test_backward_camera_matches_the_mesh_estimate(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        camera = {**STOCK_CAMERA, "azimuth": 180.0}
        cad = geometry.occlusion_report(mesh, camera=camera, engine="cad")
        estimate = geometry.occlusion_report(mesh, camera=camera, engine="mesh")
        assert cad["occludedFraction"] > 0.0
        assert next(iter(cad["obstructions"])) == "battery"
        # the quadrature integrates the same measure, to grid accuracy
        assert estimate["occludedFraction"] == pytest.approx(cad["occludedFraction"], rel=0.5)

    def test_oversized_prop_overlap_is_the_analytic_lens(self):
        stock_spacing = 10.0 * geometry.IN + 0.02
        mesh = geometry.drone_geometry(
            **{**STOCK, "prop_diameter_in": 12.0},
            split_instances=True,
            motor_spacing=stock_spacing,
        )
        lens = _lens_volume(6.0 * geometry.IN, stock_spacing, 0.0025)
        rows = geometry.overlap_report(mesh, engine="cad")
        for row in rows:
            assert row["overlap"] == pytest.approx(2.0 * lens, rel=1e-6)
            assert len(row["parts"]) == 2
        assert geometry.disc_overlap(mesh, engine="cad") == pytest.approx(8.0 * lens, rel=1e-6)

    def test_recipe_less_mesh_is_loud(self):
        with pytest.raises(AnalysisError, match="recipe"):
            geometry.occlusion_report(
                _plate_mesh(cx=1.0), TestCameraOcclusion.CAM, sensing_range=1.0, engine="cad"
            )


class TestGeometryChecks:
    def test_both_measures_keyed_for_the_scoreboard(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        checks = geometry.geometry_checks(mesh, engine="mesh")
        assert set(checks) == {"occludedFraction", "discOverlapVolume"}
        assert checks["occludedFraction"] == geometry.camera_occlusion(mesh, engine="mesh")
        assert checks["discOverlapVolume"] == geometry.disc_overlap(mesh, engine="mesh")

    def test_deterministic(self):
        mesh = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        assert geometry.geometry_checks(mesh) == geometry.geometry_checks(mesh)

    def test_stock_drone_satisfies_both_requirements(self):
        # the requirement bodies of examples/drone.sysml at the stock point
        checks = geometry.geometry_checks(
            geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        )
        assert checks["occludedFraction"] <= 0.0  # clearView
        assert checks["discOverlapVolume"] <= 0.0  # propClearance


class TestMotorSpacingOverride:
    def test_default_spacing_is_derived_from_the_prop(self):
        derived = geometry.drone_geometry(**STOCK, split_instances=True)
        fixed = geometry.drone_geometry(
            **STOCK, split_instances=True, motor_spacing=10.0 * geometry.IN + 0.02
        )
        assert derived["discs"] == fixed["discs"]

    def test_spacing_moves_the_stations(self):
        wide = geometry.drone_geometry(**STOCK, split_instances=True, motor_spacing=0.5)
        assert wide["discs"][0]["center"][0] == pytest.approx(0.25)
        with pytest.raises(AnalysisError):
            geometry.drone_geometry(**STOCK, motor_spacing=0.0)


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
    "prop_diameter": 0.2794,
    "motor_mass": 0.183,
    "battery_mass": 1.92,
}
DART = {
    "body_length": 1.25,
    "wing_span": 1.05,
    "wing_area": 0.179,
    "taper": 0.5,
    "prop_diameter": 0.2794,
    "motor_mass": 0.32,
    "battery_mass": 0.78,
}
TEARDROP = {
    "fuselage_length": 0.62,
    "prop_diameter": 0.2794,
    "motor_mass": 0.183,
    "battery_mass": 1.32,
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
        # z extent: wing tips plus the wingtip lift disks (prop radius)
        assert hi[2] == pytest.approx(2.6 / 2 + 0.2794 / 2, abs=1e-3)
        assert lo[2] == pytest.approx(-(2.6 / 2 + 0.2794 / 2), abs=1e-3)
        # the 2.6 m wing dwarfs the quad frame
        quad = geometry.drone_geometry(
            prop_diameter_in=0.3302 / geometry.IN,
            motor_mass=0.183,
            battery_mass=1.32,
            esc_mass=0.014,
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

    @pytest.mark.parametrize("prop_diameter", [0.2794, 0.3302, 0.381, 0.51])
    def test_no_two_props_intersect(self, prop_diameter):
        """The reported overlap bug, encoded: every pair of prop disks is
        strictly AABB-separated, even for props past the catalog's 15 in."""

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
            assert hi[0] - lo[0] == pytest.approx(0.2794, abs=1e-3)
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
    from longeron.analysis import trades

    catalog = longeron.load(EXAMPLES / "uav_missions.sysml", cache=False)
    return trades.TradeStudy(catalog, "UavMissions::InterceptUav")


class TestMissionBridge:
    def test_family_dispatch(self, mission_study):
        def mix(airframe):
            return mission_study.evaluate(
                {
                    "airframe": airframe,
                    "motors": "x4112s",
                    "props": "apc11x55",
                    "battery": "tattu10000",
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
                    "motors": "at4120",
                    "props": "tm15x5",  # long arms: stiffness governs
                    "battery": "tattu10000",
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
                "motors": "mn4006",
                "props": "tm15x5",
                "battery": "tattu5200",
                "material": "carbonFiber",
            }
        )
        params = geometry.mission_params(mission_study, arch)
        assert params["wing_span"] == 2.6
        assert params["wing_area"] == 0.624
        assert params["prop_diameter"] == 0.381
        assert params["motor_mass"] == 0.068
        assert params["battery_mass"] == 0.78

    def test_missing_point_is_loud(self, mission_study):
        arch = mission_study.evaluate(
            {
                "airframe": "boxQuad",
                "motors": "x4112s",
                "props": "apc11x55",
                "battery": "tattu10000",
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

    def test_grid_shape_mapping(self):
        """The user-visible contract: wider-than-tall, visually balanced
        grids -- 4 is 2x2 (not a wonky 4x1), 6 is 2x3, 8 is 2x4."""

        assert {n: geometry._grid_shape(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9)} == {
            1: (1, 1),
            2: (1, 2),
            3: (1, 3),
            4: (2, 2),
            5: (2, 3),
            6: (2, 3),
            7: (2, 4),
            8: (2, 4),
            9: (3, 3),
        }

    @staticmethod
    def _cell_centers(scene, labels):
        centers = {}
        for label in labels:
            xs = [
                v
                for p in scene["parts"]
                if p["name"].startswith(label + ":")
                for v in p["vertices"][0::3]
            ]
            zs = [
                v
                for p in scene["parts"]
                if p["name"].startswith(label + ":")
                for v in p["vertices"][2::3]
            ]
            centers[label] = (
                round((min(xs) + max(xs)) / 2, 3),
                round((min(zs) + max(zs)) / 2, 3),
            )
        return centers

    def test_four_fold_into_two_by_two(self):
        dart = geometry.interceptor_geometry(**DART)
        labels = ["a", "b", "c", "d"]
        scene = geometry.lineup([dart] * 4, labels=labels)
        centers = self._cell_centers(scene, labels)
        assert len({x for x, _ in centers.values()}) == 2  # two columns
        assert len({z for _, z in centers.values()}) == 2  # two rows
        # row-major: a and b share the front row, a and c share a column
        assert centers["a"][1] == centers["b"][1]
        assert centers["a"][0] == centers["c"][0]
        assert centers["a"][1] > centers["c"][1]  # row 0 in front

    def test_six_fold_into_two_by_three(self):
        dart = geometry.interceptor_geometry(**DART)
        labels = list("abcdef")
        scene = geometry.lineup([dart] * 6, labels=labels)
        centers = self._cell_centers(scene, labels)
        assert len({x for x, _ in centers.values()}) == 3
        assert len({z for _, z in centers.values()}) == 2

    def test_labels_ride_above_their_cells(self):
        winged = geometry.winged_vtol_geometry(**WINGED)
        dart = geometry.interceptor_geometry(**DART)
        scene = geometry.lineup([winged, dart, winged, dart], labels=["1", "2", "3", "4"])
        assert [entry["text"] for entry in scene["labels"]] == ["1", "2", "3", "4"]
        centers = self._cell_centers(scene, ["1", "2", "3", "4"])
        for entry, label in zip(scene["labels"], ["1", "2", "3", "4"], strict=True):
            x, y, z = entry["anchor"]
            assert x == pytest.approx(centers[label][0], abs=0.02)
            assert z == pytest.approx(centers[label][1], abs=0.02)
            top = max(
                v
                for p in scene["parts"]
                if p["name"].startswith(label + ":")
                for v in p["vertices"][1::3]
            )
            assert y > top  # the caption floats above its own cell
        # unlabeled lineups carry no labels key
        assert "labels" not in geometry.lineup([dart, dart])

    def test_validates(self):
        with pytest.raises(AnalysisError):
            geometry.lineup([])
        with pytest.raises(AnalysisError):
            geometry.lineup([geometry.interceptor_geometry(**DART)], labels=["a", "b"])


class TestTagParts:
    def test_stamps_keys_without_copying_geometry(self):
        mesh = geometry.drone_geometry(**RACER)
        tagged = geometry.tag_parts(mesh, QUAD_MAP)
        assert [p.get("key") for p in tagged["parts"]] == [
            "Drone::QuadCopter::chassis",
            "Drone::QuadCopter::motors",
            "Drone::QuadCopter::propellers",
            "Drone::QuadCopter::battery",
            None,  # esc has no model part: identity stays its name
        ]
        # the input mesh is untouched; vertex arrays are shared, not copied
        assert all("key" not in p for p in mesh["parts"])
        assert all(
            t["vertices"] is m["vertices"] and t["faces"] is m["faces"]
            for t, m in zip(tagged["parts"], mesh["parts"], strict=True)
        )
        assert tagged["bounds"] == mesh["bounds"] and tagged["unit"] == "m"

    def test_typos_fail_loudly_unless_relaxed(self):
        mesh = geometry.drone_geometry(**RACER)
        with pytest.raises(AnalysisError, match="rotor"):
            geometry.tag_parts(mesh, {"rotor": "Drone::QuadCopter::motors"})
        # one shared map across families: unknown names are ignored
        relaxed = geometry.tag_parts(mesh, {"wing": "X::wing"}, strict=False)
        assert all("key" not in p for p in relaxed["parts"])

    def test_lineup_carries_keys_through_the_label_prefix(self):
        tagged = geometry.tag_parts(geometry.drone_geometry(**RACER), QUAD_MAP)
        scene = geometry.lineup([tagged, geometry.drone_geometry(**CRUISER)], labels=["a", "b"])
        by_name = {p["name"]: p.get("key") for p in scene["parts"]}
        assert by_name["a:motors"] == "Drone::QuadCopter::motors"
        assert by_name["a:esc"] is None  # untagged part stays untagged
        assert by_name["b:motors"] is None  # the untagged mesh is inert


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

    def test_camera_mounts_as_a_child(self):
        pytest.importorskip("cadquery")
        assembly = geometry.to_cadquery(**RACER, camera=STOCK_CAMERA)
        camera = next(child for child in assembly.children if child.name == "camera")
        box = geometry._shape(camera.obj).BoundingBox()
        assert (box.xmin + box.xmax) / 2 == pytest.approx(STOCK_CAMERA["x"], abs=1e-9)
        assert box.xmax - box.xmin == pytest.approx(0.020, abs=1e-9)  # azimuth 0: length in x

    def test_cylinders_stand_upright(self):
        # the motors and prop discs spin about +y, exactly like the mesh
        # (a regression: local-frame cylinder axes laid them on their sides)
        pytest.importorskip("cadquery")
        solids = {
            child.name: geometry._shape(child.obj)
            for child in geometry.to_cadquery(**RACER).children
        }
        _, motor_h = geometry.motor_size(RACER["motor_mass"])
        motor_box = solids["motor1"].BoundingBox()
        assert motor_box.ymax - motor_box.ymin == pytest.approx(motor_h, rel=1e-9)
        prop_box = solids["prop1"].BoundingBox()
        assert prop_box.ymax - prop_box.ymin == pytest.approx(0.0025, abs=1e-9)
        assert prop_box.xmax - prop_box.xmin == pytest.approx(
            RACER["prop_diameter_in"] * geometry.IN, rel=1e-9
        )

    def test_solids_match_the_mesh_footprint(self):
        # the CAD twin and the mesh describe the same craft: identical
        # bounding boxes (the mesh's 32-gon prop rims touch the true
        # cylinder radius at angle 0, so even x/z extents agree)
        pytest.importorskip("cadquery")
        mesh = geometry.drone_geometry(**RACER, split_instances=True)
        by_name = {part["name"]: part for part in mesh["parts"]}
        solids = {
            child.name: geometry._shape(child.obj)
            for child in geometry.to_cadquery(**RACER).children
        }
        for name in ("motor1", "prop1", "esc"):
            (lo, hi) = geometry._part_aabb(by_name[name])
            box = solids[name].BoundingBox()
            for axis, (a, b) in enumerate(
                ((box.xmin, box.xmax), (box.ymin, box.ymax), (box.zmin, box.zmax))
            ):
                assert a == pytest.approx(lo[axis], abs=1e-4), (name, axis)
                assert b == pytest.approx(hi[axis], abs=1e-4), (name, axis)

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
