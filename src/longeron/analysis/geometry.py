"""Parametric 3D geometry for architecture mixes (spike).

Builds to-scale UAVs from a mix's catalog attribute values with plain
triangle meshes (stdlib ``math`` only).  Four airframe families are
supported: the plain quad-copter (:func:`drone_geometry` -- frame sized
from prop diameter + tip clearance), the streamlined teardrop-body quad
(:func:`teardrop_quad_geometry` -- a lathed low-drag bullet stood on end,
its long axis normal to the planar rotor quad around it), the cruciform
tail-sitter VTOL (:func:`winged_vtol_geometry` -- a minimal lathed
fuselage, two unswept airfoil wing pairs in a ``+`` cruciform, and one
tractor rotor on each of the four wingtips with every thrust axis
parallel to the chords/body axis; baked nose-up in its hover attitude),
and the streamlined interceptor
(:func:`interceptor_geometry` -- slender lathed fuselage, thin unswept
NACA-0009 wing, cruciform tail, pusher prop).  Every lifting surface is
lofted from a real NACA 4-digit section (:func:`naca4_profile`), not a
rectangular slab.  Motor cylinders come from motor mass
(solid-cylinder density heuristic), prop disks from diameter, and the
battery box from battery mass (LiPo density + brick proportions).  One
call turns a configuration into the mesh dict
:mod:`longeron.analysis.viewer3d` paints:

    {"unit": "m",
     "parts": [{"name", "color", "opacity",
                "vertices": [x, y, z, ...], "faces": [i, j, k, ...]}, ...],
     "bounds": [[xmin, ymin, zmin], [xmax, ymax, zmax]]}

A part may additionally carry a ``key`` -- a stable model identity (by
convention the SysML part usage's qualified name) stamped by
:func:`tag_parts` -- which the viewer uses for linked selection
(:mod:`longeron.analysis.link`); untagged parts fall back to their
``name``.

House pattern: geometry is baked in Python once per configuration (a
millisecond or so -- no CAD kernel in the loop); the front-end never
recomputes it.  Y is up, +X is forward, one unit is one metre, and every
dimension is a real measurement or a documented heuristic, so two mixes
render truly to scale side by side (:func:`lineup` merges several
configurations into one to-scale scene).  :func:`mission_geometry`
dispatches a ``UavMissions``-style mix onto its family builder from the
selected airframe's attributes.

:func:`to_cadquery` rebuilds the quad-copter assembly as CAD solids
(STEP export, fillets) behind the ``cad`` extra -- the mesh pipeline here
deliberately does not need the ~1 GB OCC kernel.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import atan, atan2, ceil, cos, floor, pi, sin, sqrt
from typing import Any

from ..errors import MissingExtraError
from ._expr import AnalysisError
from .trades import Architecture, TradeStudy

__all__ = [
    "architecture_geometry",
    "architecture_params",
    "drone_geometry",
    "interceptor_geometry",
    "lineup",
    "mission_geometry",
    "mission_params",
    "naca4_profile",
    "tag_parts",
    "teardrop_quad_geometry",
    "to_cadquery",
    "winged_vtol_geometry",
]

Mesh = tuple[list[float], list[int]]  # flat vertices, flat triangle indices

IN = 0.0254  # metres per inch

# --- documented sizing heuristics (SI) -------------------------------------
_MOTOR_DENSITY = 2800.0  # kg/m^3: solid-cylinder equivalent of a BLDC
_MOTOR_ASPECT = 0.7  # motor height / diameter (2306 -> 28 x 19 mm)
_BATTERY_DENSITY = 2400.0  # kg/m^3: LiPo brick incl. wrap and leads
_BATTERY_PROPORTIONS = (2.5, 1.2, 1.0)  # length : width : height
_BOARD_SIDE = 0.0305  # m: the standard 30.5 mm FC/ESC mount pattern
_BOARD_DENSITY = 1900.0  # kg/m^3: populated PCB stack
_PROP_CLEARANCE = 0.02  # m: prop-tip to prop-tip clearance
_PLATE_THICKNESS = 0.003
_ARM_WIDTH = 0.013
_ARM_THICKNESS = 0.005

#: per-part colors: muted categorical set at roughly constant lightness
COLORS = {
    "frame": "#4a4e54",  # neutral dark (fuselage, booms, plates)
    "motors": "#b4674e",  # terracotta (motor cans + nacelles)
    "props": "#58939b",  # teal (drawn translucent: a spinning disk)
    "battery": "#7181b8",  # indigo
    "esc": "#a58a4d",  # ochre
    "wing": "#6f8f6a",  # sage
    "tail": "#8a8f98",  # light gray (stabilizers)
}


# ---------------------------------------------------------------------------
# primitive meshes (closed, CCW-outward winding -- three.js front faces)
# ---------------------------------------------------------------------------

# (u, v) picked so that u x v == the face normal for each box face.
_BOX_FACES = (
    ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
    ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
    ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
    ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
    ((0, 0, -1), (0, 1, 0), (1, 0, 0)),
)


def _box(
    sx: float, sy: float, sz: float, cx: float = 0.0, cy: float = 0.0, cz: float = 0.0
) -> Mesh:
    """An axis-aligned box; vertices duplicated per face (flat shading)."""

    half = (sx / 2, sy / 2, sz / 2)
    vertices: list[float] = []
    faces: list[int] = []
    for normal, u, v in _BOX_FACES:
        base = len(vertices) // 3
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            vertices += [
                cx + (normal[0] * half[0] + su * u[0] * half[0] + sv * v[0] * half[0]),
                cy + (normal[1] * half[1] + su * u[1] * half[1] + sv * v[1] * half[1]),
                cz + (normal[2] * half[2] + su * u[2] * half[2] + sv * v[2] * half[2]),
            ]
        faces += [base, base + 1, base + 2, base, base + 2, base + 3]
    return vertices, faces


def _cylinder(
    radius: float,
    height: float,
    cx: float = 0.0,
    cy: float = 0.0,
    cz: float = 0.0,
    segments: int = 24,
) -> Mesh:
    """A Y-axis cylinder: smooth side ring, flat cap fans."""

    vertices: list[float] = []
    faces: list[int] = []
    ring = [
        (radius * cos(2 * pi * i / segments), radius * sin(2 * pi * i / segments))
        for i in range(segments)
    ]
    top, bottom = cy + height / 2, cy - height / 2

    for x, z in ring:  # side: shared vertices -> smooth normals
        vertices += [cx + x, bottom, cz + z, cx + x, top, cz + z]
    for i in range(segments):
        b0, t0 = 2 * i, 2 * i + 1
        b1, t1 = 2 * ((i + 1) % segments), 2 * ((i + 1) % segments) + 1
        faces += [b0, t0, t1, b0, t1, b1]

    for y, flip in ((top, False), (bottom, True)):  # caps: duplicated rims
        center = len(vertices) // 3
        vertices += [cx, y, cz]
        rim = len(vertices) // 3
        for x, z in ring:
            vertices += [cx + x, y, cz + z]
        for i in range(segments):
            j = (i + 1) % segments
            faces += [center, rim + i, rim + j] if flip else [center, rim + j, rim + i]
    return vertices, faces


def _rotate_y(vertices: list[float], angle: float) -> list[float]:
    """Rotate flat XYZ vertices about the +Y axis through the origin."""

    c, s = cos(angle), sin(angle)
    out = list(vertices)
    for i in range(0, len(out), 3):
        x, z = out[i], out[i + 2]
        out[i], out[i + 2] = c * x + s * z, -s * x + c * z
    return out


def _rotate_z(vertices: list[float], angle: float) -> list[float]:
    """Rotate flat XYZ vertices about the +Z axis through the origin
    (angle ``pi / 2`` stands a nose-along-+X craft on its tail: +X -> +Y)."""

    c, s = cos(angle), sin(angle)
    out = list(vertices)
    for i in range(0, len(out), 3):
        x, y = out[i], out[i + 1]
        out[i], out[i + 1] = c * x - s * y, s * x + c * y
    return out


def _merge(*meshes: Mesh) -> Mesh:
    vertices: list[float] = []
    faces: list[int] = []
    for v, f in meshes:
        base = len(vertices) // 3
        vertices += v
        faces += [base + index for index in f]
    return vertices, faces


Vec = tuple[float, float, float]


def _loft(c0: Vec, u0: Vec, v0: Vec, c1: Vec, u1: Vec, v1: Vec) -> Mesh:
    """A closed frustum between two rectangles (centre + half-extent axes).

    Each rectangle is ``c +/- u +/- v``; (u, v, c1 - c0) should form a
    right-handed triple so the winding faces outward.  Vertices are
    duplicated per face for flat shading.
    """

    def corner(c: Vec, u: Vec, v: Vec, su: int, sv: int) -> Vec:
        return (
            c[0] + su * u[0] + sv * v[0],
            c[1] + su * u[1] + sv * v[1],
            c[2] + su * u[2] + sv * v[2],
        )

    signs = ((-1, -1), (1, -1), (1, 1), (-1, 1))  # CCW seen from +w
    a = [corner(c0, u0, v0, su, sv) for su, sv in signs]
    b = [corner(c1, u1, v1, su, sv) for su, sv in signs]

    vertices: list[float] = []
    faces: list[int] = []

    def quad(p0: Vec, p1: Vec, p2: Vec, p3: Vec) -> None:
        base = len(vertices) // 3
        for p in (p0, p1, p2, p3):
            vertices.extend(p)
        faces.extend((base, base + 1, base + 2, base, base + 2, base + 3))

    quad(b[0], b[1], b[2], b[3])  # end cap (+w)
    quad(a[3], a[2], a[1], a[0])  # start cap (-w)
    for j in range(4):
        k = (j + 1) % 4
        quad(a[j], a[k], b[k], b[j])  # side
    return vertices, faces


def _tube(rings: list[tuple[float, float]], segments: int = 24) -> Mesh:
    """A closed surface of revolution about the +X axis.

    ``rings`` is ``[(x, radius), ...]`` ordered nose-to-tail (descending or
    ascending x -- both cap correctly); radii must be positive.  Shared
    side vertices give smooth normals, caps get duplicated rims.
    """

    if len(rings) < 2:
        raise AnalysisError("a tube needs at least two rings")
    if any(r <= 0 for _, r in rings):
        raise AnalysisError("tube radii must be positive")
    unit = [(cos(2 * pi * i / segments), sin(2 * pi * i / segments)) for i in range(segments)]
    ascending = rings[-1][0] >= rings[0][0]

    vertices: list[float] = []
    faces: list[int] = []
    for x, radius in rings:
        for cy, cz in unit:
            vertices += [x, radius * cy, radius * cz]
    for i in range(len(rings) - 1):
        r0, r1 = i * segments, (i + 1) * segments
        for j in range(segments):
            k = (j + 1) % segments
            if ascending:
                faces += [r0 + j, r0 + k, r1 + k, r0 + j, r1 + k, r1 + j]
            else:
                faces += [r0 + j, r1 + j, r1 + k, r0 + j, r1 + k, r0 + k]

    lo_i, hi_i = (0, len(rings) - 1) if ascending else (len(rings) - 1, 0)
    for index, flip in ((hi_i, False), (lo_i, True)):  # +X cap, -X cap
        x, radius = rings[index]
        center = len(vertices) // 3
        vertices += [x, 0.0, 0.0]
        rim = len(vertices) // 3
        for cy, cz in unit:
            vertices += [x, radius * cy, radius * cz]
        for j in range(segments):
            k = (j + 1) % segments
            faces += [center, rim + k, rim + j] if flip else [center, rim + j, rim + k]
    return vertices, faces


# ---------------------------------------------------------------------------
# component sizing from catalog attributes
# ---------------------------------------------------------------------------


def motor_size(mass: float) -> tuple[float, float]:
    """(diameter, height) of a solid-cylinder-equivalent BLDC motor."""

    if mass <= 0:
        raise AnalysisError(f"motor mass must be positive (got {mass!r})")
    diameter = (4.0 * mass / (_MOTOR_ASPECT * pi * _MOTOR_DENSITY)) ** (1 / 3)
    return diameter, _MOTOR_ASPECT * diameter


def battery_size(mass: float) -> tuple[float, float, float]:
    """(length, width, height) of a LiPo brick of the given mass."""

    if mass <= 0:
        raise AnalysisError(f"battery mass must be positive (got {mass!r})")
    pl, pw, ph = _BATTERY_PROPORTIONS
    height = (mass / _BATTERY_DENSITY / (pl * pw * ph)) ** (1 / 3) * ph
    return pl / ph * height, pw / ph * height, height


def board_thickness(mass: float) -> float:
    """Stack thickness of a 30.5 mm-mount controller board."""

    thickness = mass / (_BOARD_DENSITY * _BOARD_SIDE**2)
    return min(max(thickness, 0.004), 0.014)


# ---------------------------------------------------------------------------
# the drone assembly
# ---------------------------------------------------------------------------


def _pack(
    named: list[tuple[str, Mesh, float]], colors: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """Round, color, and bound a list of (name, mesh, opacity) parts.

    ``colors`` adds per-part color entries on top of the module
    :data:`COLORS` (for generated names like ``motor1`` that are not in
    the fixed palette).
    """

    palette = {**COLORS, **(colors or {})}
    parts: list[dict[str, Any]] = []
    rounded_parts: list[list[float]] = []
    for name, (vertices, faces), opacity in named:
        rounded = [round(c, 5) for c in vertices]
        rounded_parts.append(rounded)
        parts.append(
            {
                "name": name,
                "color": palette[name],
                "opacity": opacity,
                "vertices": rounded,
                "faces": faces,
            }
        )
    lo = [min(min(v[i::3]) for v in rounded_parts) for i in range(3)]
    hi = [max(max(v[i::3]) for v in rounded_parts) for i in range(3)]
    return {
        "unit": "m",
        "parts": parts,
        "bounds": [[floor(v * 1e5) / 1e5 for v in lo], [ceil(v * 1e5) / 1e5 for v in hi]],
    }


def drone_geometry(
    *,
    prop_diameter_in: float,
    motor_mass: float,
    battery_mass: float,
    esc_mass: float,
    arm_thickness: float = _ARM_THICKNESS,
    arm_width: float = _ARM_WIDTH,
    segments: int = 24,
    split_instances: bool = False,
) -> dict[str, Any]:
    """A to-scale quad-copter mesh dict from catalog attribute values.

    The frame is *derived*: adjacent motors sit one prop diameter plus
    ``_PROP_CLEARANCE`` apart, so a 10-inch cruiser genuinely dwarfs a
    5-inch racer.  ``arm_thickness``/``arm_width`` default to the demo
    heuristics; callers with load-sized arm tubes (see
    :func:`mission_geometry`) pass the sized outer diameter so heavier-
    loaded designs genuinely look beefier.  Parts of one kind merge into
    a single mesh (one draw call each in the viewer).

    ``split_instances`` keeps the motor and prop instances as separate
    parts -- ``motor1`` .. ``motor4`` and ``prop1`` .. ``prop4``, the
    same names and order as the :func:`to_cadquery` assembly children --
    so each can carry its own identity key (e.g. an M0 individual id,
    see :func:`tag_parts`) for per-instance linked selection.  The
    geometry is a pure re-partition: concatenating the instance parts
    reproduces the merged part exactly, and the default (``False``)
    output is unchanged.
    """

    prop_d = prop_diameter_in * IN
    spacing = prop_d + _PROP_CLEARANCE  # adjacent motor-to-motor
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, bat_h = battery_size(battery_mass)
    esc_t = board_thickness(esc_mass)

    plate_side = max(0.075, bat_w + 0.014, _BOARD_SIDE + 0.024)
    arm_reach = (spacing / 2) * 2**0.5  # centre -> motor axis, in XZ
    motor_y = arm_thickness / 2 + motor_h / 2
    prop_y = arm_thickness / 2 + motor_h + 0.002 + 0.00125

    arms, motors, props = [], [], []
    arm_length = arm_reach + motor_d / 2
    for mx, mz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        angle = atan2(mz, mx)
        arm = _box(arm_length, arm_thickness, arm_width, cx=arm_length / 2)
        arms.append((_rotate_y(arm[0], -angle), arm[1]))
        x, z = mx * spacing / 2, mz * spacing / 2
        motors.append(_cylinder(motor_d / 2, motor_h, x, motor_y, z, segments))
        props.append(_cylinder(prop_d / 2, 0.0025, x, prop_y, z, max(segments, 32)))

    frame = _merge(_box(plate_side, _PLATE_THICKNESS, plate_side), *arms)
    battery = _box(bat_l, bat_w, bat_h, cy=-(_PLATE_THICKNESS / 2 + 0.004 + bat_h / 2))
    esc = _box(_BOARD_SIDE, esc_t, _BOARD_SIDE, cy=_PLATE_THICKNESS / 2 + esc_t / 2)

    if split_instances:
        parts: list[tuple[str, Mesh, float]] = [
            ("frame", frame, 1.0),
            *((f"motor{i + 1}", motor, 1.0) for i, motor in enumerate(motors)),
            *((f"prop{i + 1}", prop, 0.55) for i, prop in enumerate(props)),
            ("battery", battery, 1.0),
            ("esc", esc, 1.0),
        ]
        instance_colors = {
            f"{kind}{i + 1}": COLORS[f"{kind}s"] for kind in ("motor", "prop") for i in range(4)
        }
        return _pack(parts, colors=instance_colors)
    parts = [
        ("frame", frame, 1.0),
        ("motors", _merge(*motors), 1.0),
        ("props", _merge(*props), 0.55),
        ("battery", battery, 1.0),
        ("esc", esc, 1.0),
    ]
    return _pack(parts)


#: cruciform tail-sitter proportions (documented heuristics): the
#: secondary (short) wing pair's span relative to the main pair, and the
#: props on its tips relative to the main-tip (catalog) props -- the prop
#: ratio is baked into the catalog's diskAreaFactor (2 + 2 * 0.8^2 ~ 3.3)
_SECONDARY_SPAN_RATIO = 0.62
_SECONDARY_PROP_RATIO = 0.8

#: NACA 4-digit sections per surface role (max thickness fraction = the
#: last two digits / 100; validated by the geometry tests)
WING_SECTION = "2412"  # cambered, 12% thick: the VTOL cruise wing
TAIL_SECTION = "0009"  # symmetric, 9%: stabilizers + fast surfaces


def naca4_profile(code: str = WING_SECTION, points: int = 24) -> list[tuple[float, float]]:
    """A closed NACA 4-digit section as chord-normalized ``(x, y)`` pairs.

    Cosine-spaced stations, closed trailing edge (the -0.1036 thickness
    coefficient), ordered TE -> upper surface -> LE -> lower surface ->
    TE, i.e. counter-clockwise in the chord plane.  ``points`` is the
    total vertex count of the closed polygon (~24 is plenty for a mesh
    loft).
    """

    if len(code) != 4 or not code.isdigit():
        raise AnalysisError(f"not a NACA 4-digit code: {code!r}")
    if points < 8:
        raise AnalysisError("a NACA section needs at least 8 points")
    m, p, t = int(code[0]) / 100, int(code[1]) / 10, int(code[2:]) / 100
    half = points // 2

    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    for k in range(half + 1):
        x = 0.5 * (1.0 - cos(pi * k / half))  # cosine spacing, 0 = LE
        yt = (
            5.0
            * t
            * (0.2969 * sqrt(x) - 0.1260 * x - 0.3516 * x * x + 0.2843 * x**3 - 0.1036 * x**4)
        )
        if m == 0.0 or p == 0.0:
            yc, theta = 0.0, 0.0
        elif x < p:
            yc = m / p**2 * (2 * p * x - x * x)
            theta = atan(2 * m / p**2 * (p - x))
        else:
            yc = m / (1 - p) ** 2 * ((1 - 2 * p) + 2 * p * x - x * x)
            theta = atan(2 * m / (1 - p) ** 2 * (p - x))
        upper.append((x - yt * sin(theta), yc + yt * cos(theta)))
        lower.append((x + yt * sin(theta), yc - yt * cos(theta)))
    return list(reversed(upper)) + lower[1:-1]


def _skin(rings: list[list[Vec]]) -> Mesh:
    """A closed skin over ordered cross-section rings (equal counts).

    Quad strips join neighbouring rings; triangle fans (about the ring
    centroid, rim vertices duplicated) cap the ends.  Ring vertices must
    run counter-clockwise as seen from the *next* ring so the winding
    faces outward.
    """

    if len(rings) < 2 or len({len(r) for r in rings}) != 1:
        raise AnalysisError("a skin needs >= 2 rings of equal vertex count")
    n = len(rings[0])
    vertices: list[float] = []
    faces: list[int] = []
    for ring in rings:
        for x, y, z in ring:
            vertices += [x, y, z]
    for i in range(len(rings) - 1):
        r0, r1 = i * n, (i + 1) * n
        for j in range(n):
            k = (j + 1) % n
            faces += [r0 + j, r0 + k, r1 + k, r0 + j, r1 + k, r1 + j]
    for ring, flip in ((rings[-1], False), (rings[0], True)):
        cx = sum(p[0] for p in ring) / n
        cy = sum(p[1] for p in ring) / n
        cz = sum(p[2] for p in ring) / n
        center = len(vertices) // 3
        vertices += [cx, cy, cz]
        rim = len(vertices) // 3
        for x, y, z in ring:
            vertices += [x, y, z]
        for j in range(n):
            k = (j + 1) % n
            faces += [center, rim + k, rim + j] if flip else [center, rim + j, rim + k]
    return vertices, faces


def _mirror_z(mesh: Mesh) -> Mesh:
    """The mesh reflected through the XY plane, winding kept outward."""

    vertices, faces = mesh
    out = list(vertices)
    for i in range(2, len(out), 3):
        out[i] = -out[i]
    flipped: list[int] = []
    for i in range(0, len(faces), 3):
        flipped += [faces[i], faces[i + 2], faces[i + 1]]
    return out, flipped


def _lift_surface(
    *,
    origin: Vec,
    direction: Vec,
    length: float,
    root_chord: float,
    tip_chord: float,
    section: str = WING_SECTION,
    points: int = 24,
) -> Mesh:
    """One lofted lifting-surface panel with a real airfoil section.

    The NACA ``section`` is swept from ``origin`` (the *root
    quarter-chord point*) along the unit ``direction`` for ``length``,
    the chord tapering ``root_chord`` -> ``tip_chord`` about a constant
    quarter-chord -- i.e. the quarter-chord line is exactly parallel to
    ``direction``: zero sweep by construction.  Chords run along -X
    (leading edge forward); the section's thickness/camber axis is
    ``direction x X-hat``, so a horizontal panel swept toward +Z lifts
    upward.
    """

    dx, dy, dz = direction
    norm = sqrt(dx * dx + dy * dy + dz * dz)
    if norm <= 0 or min(length, root_chord, tip_chord) <= 0:
        raise AnalysisError("lift surface needs positive dimensions")
    dx, dy, dz = dx / norm, dy / norm, dz / norm
    # thickness axis n = direction x X-hat (unit, perpendicular to both)
    nx, ny, nz = (dy * 0.0 - dz * 0.0, dz * 1.0 - dx * 0.0, dx * 0.0 - dy * 1.0)
    profile = list(reversed(naca4_profile(section, points)))

    def ring(s: float) -> list[Vec]:
        chord = root_chord + (tip_chord - root_chord) * s
        ox = origin[0] + dx * length * s
        oy = origin[1] + dy * length * s
        oz = origin[2] + dz * length * s
        out: list[Vec] = []
        for xa, ya in profile:
            along = (0.25 - xa) * chord  # x = quarter-chord + offset
            out.append((ox + along + nx * ya * chord, oy + ny * ya * chord, oz + nz * ya * chord))
        return out

    return _skin([ring(0.0), ring(1.0)])


def _lift_rotor(
    x: float, y: float, z: float, *, prop_radius: float, motor_mass: float, segments: int
) -> tuple[Mesh, Mesh]:
    """(motor, prop) for one HORIZONTAL lift rotor whose mount top is at
    ``y``: the motor can sits on the mount, the prop disk spins above it
    with its surface normal straight up (+Y) -- the VTOL requirement."""

    motor_d, motor_h = motor_size(motor_mass)
    motor = _cylinder(motor_d / 2, motor_h, x, y + motor_h / 2, z, segments)
    prop = _cylinder(prop_radius, 0.0025, x, y + motor_h + 0.004, z, max(segments, 32))
    return motor, prop


def winged_vtol_geometry(
    *,
    wing_span: float,
    wing_area: float,
    taper: float,
    fuselage_length: float,
    prop_diameter: float,
    motor_mass: float,
    battery_mass: float,
    segments: int = 24,
) -> dict[str, Any]:
    """A to-scale cruciform tail-sitter VTOL, baked in its hover attitude.

    The craft is assembled nose-along-+X (the cruise frame) and then
    stood on its tail (+X -> +Y), so the scene reads as hover: a minimal
    slender lathed fuselage; two unswept airfoil-lofted wing pairs in a
    ``+`` cruciform -- the main NACA-2412 pair spans ``wing_span`` with
    chord = ``wing_area / wing_span`` tapering about a straight
    quarter-chord, the secondary NACA-0009 pair is
    ``_SECONDARY_SPAN_RATIO`` of that span at the same chords -- and one
    tractor rotor on each of the four wingtips, every thrust axis
    PARALLEL to the wing chords and the body axis.  In hover the vehicle
    hangs nose-up on its four (now horizontal) disks; for cruise the
    whole craft pitches over and flies wing-borne.  No booms and no
    separate tail: the cruciform panels are the tail.  The main-pair
    tips carry the catalog props, the secondary tips
    ``_SECONDARY_PROP_RATIO``-scaled ones (that ratio is baked into the
    catalog's diskAreaFactor).  Fuselage radius follows the battery
    brick, drawn as an indigo sleeve at its true station.
    """

    if min(wing_span, wing_area, fuselage_length, prop_diameter, taper) <= 0:
        raise AnalysisError("winged VTOL dimensions must be positive")
    mean_chord = wing_area / wing_span
    root = 2.0 * mean_chord / (1.0 + taper)
    tip = root * taper
    long_half = wing_span / 2
    short_half = _SECONDARY_SPAN_RATIO * long_half
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, _bat_h = battery_size(battery_mass)

    # not much of a body: just wide enough for the battery brick
    body_r = max(0.040, bat_w / 2 + 0.010)
    half = fuselage_length / 2
    fuselage = _tube(
        [
            (half, 0.15 * body_r),
            (half - 0.30 * fuselage_length, body_r),
            (-half + 0.30 * fuselage_length, body_r),
            (-half, 0.40 * body_r),
        ],
        segments,
    )

    x_qc = -0.05 * fuselage_length  # shared quarter-chord, near mid-body
    main = _lift_surface(
        origin=(x_qc, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
        length=long_half,
        root_chord=root,
        tip_chord=tip,
        section=WING_SECTION,
    )
    wing = _merge(main, _mirror_z(main))
    tail = _merge(
        *(
            _lift_surface(
                origin=(x_qc, 0.0, 0.0),
                direction=(0.0, side, 0.0),
                length=short_half,
                root_chord=root,
                tip_chord=tip,
                section=TAIL_SECTION,
            )
            for side in (1.0, -1.0)
        )
    )

    # one tractor rotor per wingtip: pod + motor can + disk, all four
    # thrust axes along +X (the body axis) -- horizontal disks in hover
    nac_r = 0.72 * motor_d
    pod_len = max(4.0 * motor_h, 0.9 * tip)
    x_pod_nose = x_qc + 0.25 * tip + 0.35 * pod_len
    x_disk = x_pod_nose + motor_h + 0.004
    tips = [
        (0.0, long_half, prop_diameter / 2),
        (0.0, -long_half, prop_diameter / 2),
        (short_half, 0.0, _SECONDARY_PROP_RATIO * prop_diameter / 2),
        (-short_half, 0.0, _SECONDARY_PROP_RATIO * prop_diameter / 2),
    ]
    pods, motors, props = [], [], []
    for ty, tz, prop_r in tips:
        pod = _tube(
            [
                (x_pod_nose, 0.35 * nac_r),
                (x_pod_nose - 0.30 * pod_len, nac_r),
                (x_pod_nose - 0.85 * pod_len, nac_r),
                (x_pod_nose - pod_len, 0.40 * nac_r),
            ],
            segments,
        )
        pods.append((_translate(pod[0], 0.0, ty, tz), pod[1]))
        motor = _tube(
            [(x_pod_nose + motor_h, 0.42 * motor_d), (x_pod_nose, 0.50 * motor_d)], segments
        )
        motors.append((_translate(motor[0], 0.0, ty, tz), motor[1]))
        prop = _tube([(x_disk, prop_r), (x_disk + 0.0025, prop_r)], max(segments, 32))
        props.append((_translate(prop[0], 0.0, ty, tz), prop[1]))

    x_bay = 0.10 * fuselage_length  # battery just ahead of the wing
    battery = _tube(
        [(x_bay + bat_l / 2, body_r + 0.002), (x_bay - bat_l / 2, body_r + 0.002)], segments
    )

    def stand(mesh: Mesh) -> Mesh:  # hover attitude: nose up
        return _rotate_z(mesh[0], pi / 2), mesh[1]

    return _pack(
        [
            ("frame", stand(fuselage), 1.0),
            ("wing", stand(wing), 1.0),
            ("tail", stand(tail), 1.0),
            ("motors", stand(_merge(*pods, *motors)), 1.0),
            ("props", stand(_merge(*props)), 0.55),
            ("battery", stand(battery), 1.0),
        ]
    )


def interceptor_geometry(
    *,
    body_length: float,
    wing_span: float,
    wing_area: float,
    taper: float,
    prop_diameter: float,
    motor_mass: float,
    battery_mass: float,
    segments: int = 24,
) -> dict[str, Any]:
    """A to-scale streamlined interceptor: slender body, pusher prop.

    The fuselage is a lathed low-drag body just wide enough for the
    battery brick; the wing is a thin unswept NACA-0009 loft (chord =
    ``wing_area / wing_span``, straight quarter-chord) at mid-body, the
    cruciform tail fins carry the same section, and the single catalog
    prop pushes at the stern.  The battery bay is drawn as an indigo
    sleeve around the fuselage at its true length and position (the
    brick rides inside the body).
    """

    if min(body_length, wing_span, wing_area, prop_diameter, taper) <= 0:
        raise AnalysisError("interceptor dimensions must be positive")
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, _bat_h = battery_size(battery_mass)
    body_r = max(0.040, bat_w / 2 + 0.012, motor_d / 2 + 0.004)
    half = body_length / 2

    fuselage = _tube(
        [
            (half, 0.12 * body_r),  # nose tip
            (half - 0.28 * body_length, body_r),  # max section
            (-half + 0.22 * body_length, body_r),
            (-half, 0.55 * body_r),
        ],  # boat tail
        segments,
    )

    mean_chord = wing_area / wing_span
    root = 2.0 * mean_chord / (1.0 + taper)
    tip = root * taper
    right = _lift_surface(
        origin=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
        length=wing_span / 2,
        root_chord=root,
        tip_chord=tip,
        section=TAIL_SECTION,
    )
    wing = _merge(right, _mirror_z(right))

    fin_span = 0.34 * wing_span
    fin_root = 0.62 * mean_chord
    x_tail = -half + 0.30 * fin_root + 0.02
    fins = [
        _lift_surface(
            origin=(x_tail, 0.0, 0.0),
            direction=(0.0, uy, uz),
            length=fin_span / 2,
            root_chord=fin_root,
            tip_chord=0.55 * fin_root,
            section=TAIL_SECTION,
        )
        for uy, uz in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0))
    ]
    tail = _merge(*fins)

    motor = _tube(
        [(-half - 0.002, 0.5 * body_r), (-half - 0.002 - motor_h, 0.45 * body_r)], segments
    )
    prop = _tube(
        [
            (-half - motor_h - 0.006, prop_diameter / 2),
            (-half - motor_h - 0.0085, prop_diameter / 2),
        ],
        max(segments, 32),
    )

    x_bay = half - 0.30 * body_length - bat_l / 2
    battery = _tube(
        [(x_bay + bat_l / 2, body_r + 0.002), (x_bay - bat_l / 2, body_r + 0.002)], segments
    )

    return _pack(
        [
            ("frame", fuselage, 1.0),
            ("wing", wing, 1.0),
            ("tail", tail, 1.0),
            ("motors", motor, 1.0),
            ("props", prop, 0.55),
            ("battery", battery, 1.0),
        ]
    )


def teardrop_quad_geometry(
    *,
    fuselage_length: float,
    prop_diameter: float,
    motor_mass: float,
    battery_mass: float,
    arm_thickness: float = _ARM_THICKNESS,
    arm_width: float = _ARM_WIDTH,
    segments: int = 24,
) -> dict[str, Any]:
    """A to-scale streamlined teardrop-body quad (wingless dash bird).

    The shell is a body of revolution lathed from the NACA-0025
    half-thickness curve and stood on end: its long axis is NORMAL to
    the rotor plane -- the bullet pierces the disk plane blunt-nose-up,
    fine tail down -- so in a dash (the whole quad pitched over) the
    body flies point-first with minimal frontal area.  Four arms radiate
    horizontally from the widest station to the lift motors, keeping the
    four prop disks a planar quad around the body (surface normals +Y,
    parallel to the body axis) with genuine radial clearance to the
    hull.  The battery is drawn as an indigo sleeve at its true position
    inside the shell.
    """

    if min(fuselage_length, prop_diameter) <= 0:
        raise AnalysisError("teardrop quad dimensions must be positive")
    prop_d = prop_diameter
    spacing = prop_d + _PROP_CLEARANCE
    motor_d, _motor_h = motor_size(motor_mass)
    bat_l, bat_w, _bat_h = battery_size(battery_mass)
    body_r = max(0.045, bat_w / 2 + 0.014)
    half = fuselage_length / 2

    # teardrop of revolution: the NACA-0025 upper surface as the radius
    # profile (tiny positive end radii keep the lathe well-formed);
    # lathed about +X, then stood on end (+X -> +Y: blunt nose up)
    curve = [(x, y) for x, y in naca4_profile("0025", 28) if y > -1e-9]
    peak = max(y for _, y in curve)
    rings = sorted(
        ((half - x * fuselage_length, body_r * max(y, 0.02 * peak) / peak) for x, y in curve),
        key=lambda r: r[0],
    )
    shell = _tube(rings, segments)
    shell = (_rotate_z(shell[0], pi / 2), shell[1])
    y_widest = half - 0.30 * fuselage_length  # NACA max thickness station

    arms, motors, props = [], [], []
    arm_reach = (spacing / 2) * 2**0.5
    arm_length = arm_reach + motor_d / 2
    for mx, mz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        angle = atan2(mz, mx)
        arm = _box(arm_length, arm_thickness, arm_width, cx=arm_length / 2)
        arms.append((_translate(_rotate_y(arm[0], -angle), 0.0, y_widest, 0.0), arm[1]))
        motor, prop = _lift_rotor(
            mx * spacing / 2,
            y_widest + arm_thickness / 2,
            mz * spacing / 2,
            prop_radius=prop_d / 2,
            motor_mass=motor_mass,
            segments=segments,
        )
        motors.append(motor)
        props.append(prop)

    y_bay = half - 0.32 * fuselage_length
    bay_r = body_r * 0.96 + 0.003
    bay = _tube([(y_bay + bat_l / 2, bay_r), (y_bay - bat_l / 2, bay_r)], segments)
    battery = (_rotate_z(bay[0], pi / 2), bay[1])

    return _pack(
        [
            ("frame", _merge(shell, *arms), 1.0),
            ("motors", _merge(*motors), 1.0),
            ("props", _merge(*props), 0.55),
            ("battery", battery, 1.0),
        ]
    )


def _translate(vertices: list[float], dx: float, dy: float, dz: float) -> list[float]:
    out = list(vertices)
    for i in range(0, len(out), 3):
        out[i] += dx
        out[i + 1] += dy
        out[i + 2] += dz
    return out


def _grid_shape(count: int) -> tuple[int, int]:
    """The (rows, cols) of a visually balanced, wider-than-tall lineup.

    ``rows = floor(sqrt(n))``, ``cols = ceil(n / rows)``: 1 -> 1x1,
    2 -> 1x2, 3 -> 1x3, 4 -> 2x2, 6 -> 2x3, 8 -> 2x4, 9 -> 3x3.
    """

    rows = max(1, floor(sqrt(count)))
    return rows, ceil(count / rows)


def lineup(
    meshes: list[dict[str, Any]], *, gap: float = 0.25, labels: list[str] | None = None
) -> dict[str, Any]:
    """Merge mesh dicts into one to-scale scene on a shared ground plane.

    Each mesh keeps its parts (names prefixed by its label so a scene can
    carry several configurations); everything sits on a shared ground
    plane (ymin aligned) with ``gap`` metres between neighbouring cells.
    Up to three meshes pack side by side along X at their true widths;
    larger lineups fold into the adaptive grid of :func:`_grid_shape`
    (rows along Z, row-major from the front, uniform cells sized by the
    largest footprint) so four configurations read as 2x2, six as 2x3,
    eight as 2x4.  With ``labels`` the scene carries a ``labels`` list
    (``{text, anchor}``) that :func:`longeron.analysis.viewer3d.mesh_viewer`
    renders as a billboard caption above each cell.
    """

    if not meshes:
        raise AnalysisError("lineup needs at least one mesh")
    if labels is not None and len(labels) != len(meshes):
        raise AnalysisError("lineup needs one label per mesh")
    rows, cols = _grid_shape(len(meshes))
    y_floor = min(m["bounds"][0][1] for m in meshes)

    # per-mesh cell origin (x, z), packed for a single row, uniform grid
    # cells otherwise (columns line up between rows)
    origins: list[tuple[float, float]] = []
    if rows == 1:
        widths = [m["bounds"][1][0] - m["bounds"][0][0] for m in meshes]
        total = sum(widths) + gap * (len(meshes) - 1)
        cursor = -total / 2
        for width in widths:
            origins.append((cursor + width / 2, 0.0))
            cursor += width + gap
    else:
        cell_w = max(m["bounds"][1][0] - m["bounds"][0][0] for m in meshes) + gap
        cell_d = max(m["bounds"][1][2] - m["bounds"][0][2] for m in meshes) + gap
        for index in range(len(meshes)):
            row, col = divmod(index, cols)
            origins.append(
                (
                    (col - (cols - 1) / 2) * cell_w,
                    ((rows - 1) / 2 - row) * cell_d,  # row 0 at the front
                )
            )

    parts: list[dict[str, Any]] = []
    captions: list[dict[str, Any]] = []
    for index, mesh in enumerate(meshes):
        (x0, y0, z0), (x1, y1, z1) = mesh["bounds"]
        cx, cz = origins[index]
        dx = cx - (x0 + x1) / 2
        dy = y_floor - y0
        dz = cz - (z0 + z1) / 2
        prefix = labels[index] if labels is not None else str(index + 1)
        for part in mesh["parts"]:
            entry = {
                "name": f"{prefix}:{part['name']}",
                "color": part["color"],
                "opacity": part.get("opacity", 1.0),
                "vertices": [round(c, 5) for c in _translate(part["vertices"], dx, dy, dz)],
                "faces": list(part["faces"]),
            }
            if "key" in part:  # model identity survives the label prefix
                entry["key"] = part["key"]
            parts.append(entry)
        if labels is not None:
            captions.append(
                {
                    "text": labels[index],
                    "anchor": [
                        round(cx, 5),
                        round(y1 + dy + 0.06 * max(x1 - x0, y1 - y0, 0.2), 5),
                        round(cz, 5),
                    ],
                }
            )

    lo = [min(min(p["vertices"][i::3]) for p in parts) for i in range(3)]
    hi = [max(max(p["vertices"][i::3]) for p in parts) for i in range(3)]
    scene = {
        "unit": "m",
        "parts": parts,
        "bounds": [[floor(v * 1e5) / 1e5 for v in lo], [ceil(v * 1e5) / 1e5 for v in hi]],
    }
    if captions:
        scene["labels"] = captions
    return scene


def tag_parts(
    mesh: dict[str, Any], mapping: Mapping[str, str], *, strict: bool = True
) -> dict[str, Any]:
    """Stamp model identities onto mesh parts (linked-selection plumbing).

    Returns a copy of ``mesh`` whose parts named in ``mapping`` carry a
    ``key`` -- by convention the *qualified name* of the model part the
    component renders, or, for per-instance parts (see
    :func:`drone_geometry`'s ``split_instances``), the **M0 individual
    id** from :func:`longeron.m0.interpret` (``Drone::QuadCopter#0.
    rotors#2``), whose dotted path derives the owning usage for linked
    selection (:func:`longeron.analysis.link.individual_qname`).
    Several mesh parts may share one key (a quad's ``motors`` and
    ``props`` both render the ``rotors`` usage; a ``motor``/``prop``
    pair renders one rotor individual); parts not named keep no key and
    fall back to their ``name`` as their identity in
    :mod:`longeron.analysis.viewer3d`.  Vertex and face arrays are
    shared with the input, not copied.

    With ``strict`` (the default) every mapping entry must name a part,
    so typos fail loudly; pass ``strict=False`` to reuse one mapping
    across airframe families with different part sets.  :func:`lineup`
    carries keys through unchanged (its label prefixes only rename), so
    tag each configuration *before* merging and a selection lights up
    in every cell.
    """

    names = {part["name"] for part in mesh["parts"]}
    missing = sorted(set(mapping) - names)
    if strict and missing:
        raise AnalysisError(
            f"tag_parts: no mesh part named {missing} (parts: {sorted(names)}; "
            "pass strict=False to ignore)"
        )
    out = dict(mesh)
    out["parts"] = [
        {**part, "key": mapping[part["name"]]} if part["name"] in mapping else dict(part)
        for part in mesh["parts"]
    ]
    return out


def mission_params(study: TradeStudy, architecture: Architecture) -> dict[str, float]:
    """Geometry inputs from a ``UavMissions``-style mix.

    Expects variation points ``airframe`` (attributes ``wingSpan``,
    ``wingArea``, ``taper``, ``fuselageLength``, ``motorCount``),
    ``motors`` (``mass``), ``props`` (``diameter``), and ``battery``
    (``mass``) -- the convention of ``examples/uav_missions.sysml``.
    """

    def attr(point: str, name: str) -> float:
        try:
            variant = architecture.selection[point]
            return float(study.points[point].variants[variant][name])
        except KeyError as err:
            raise AnalysisError(
                f"cannot read '{point}.{name}' for this mix (missing "
                f"variation point, variant, or attribute: {err})"
            ) from err

    return {
        "wing_span": attr("airframe", "wingSpan"),
        "wing_area": attr("airframe", "wingArea"),
        "taper": attr("airframe", "taper"),
        "fuselage_length": attr("airframe", "fuselageLength"),
        "motor_count": attr("airframe", "motorCount"),
        "motor_mass": attr("motors", "mass"),
        "prop_diameter": attr("props", "diameter"),
        "battery_mass": attr("battery", "mass"),
    }


def mission_geometry(
    study: TradeStudy, architecture: Architecture, **overrides: Any
) -> dict[str, Any]:
    """Family-dispatched geometry for a ``UavMissions`` mix.

    The selected airframe's attributes pick the builder: no wing and no
    fuselage -> :func:`drone_geometry` (the plain quad); no wing but a
    real fuselage -> :func:`teardrop_quad_geometry` (the upended
    bullet); a single motor station -> :func:`interceptor_geometry`;
    otherwise :func:`winged_vtol_geometry` (the cruciform tail-sitter,
    rendered in hover attitude).  When the mix's metrics carry the
    load-sized ``armOuterDiameter`` (the assembly's structural sizing),
    the quad families draw their arms at that diameter -- a sprint-motor
    aluminum build genuinely looks beefier than a carbon eco build.
    """

    p = {**mission_params(study, architecture), **overrides}
    motor_count = p.pop("motor_count")
    sized_arm = float(architecture.metrics.get("armOuterDiameter", 0.0) or 0.0)
    arm_kw: dict[str, Any] = (
        {"arm_thickness": sized_arm, "arm_width": sized_arm} if sized_arm > 0 else {}
    )
    if p["wing_span"] <= 0:  # rotor-borne only
        if p["fuselage_length"] > 0:  # the streamlined teardrop shell
            return teardrop_quad_geometry(
                fuselage_length=p["fuselage_length"],
                prop_diameter=p["prop_diameter"],
                motor_mass=p["motor_mass"],
                battery_mass=p["battery_mass"],
                **arm_kw,
            )
        return drone_geometry(
            prop_diameter_in=p["prop_diameter"] / IN,
            motor_mass=p["motor_mass"],
            battery_mass=p["battery_mass"],
            esc_mass=0.014,
            **arm_kw,
        )  # 30.5 mm stack heuristic
    if motor_count <= 1:
        return interceptor_geometry(body_length=p.pop("fuselage_length"), **p)
    return winged_vtol_geometry(**p)


def architecture_params(study: TradeStudy, architecture: Architecture) -> dict[str, float]:
    """Geometry inputs from a drone-catalog mix.

    Expects the ``TradeQuad``-style variation points ``motors`` (attribute
    ``mass``), ``props`` (``diameterIn``), ``battery`` (``mass``), and
    ``esc`` (``mass``) -- this is demo-grade wiring for the drone catalog,
    not a generic geometry mapping.
    """

    def attr(point: str, name: str) -> float:
        try:
            variant = architecture.selection[point]
            return float(study.points[point].variants[variant][name])
        except KeyError as err:
            raise AnalysisError(
                f"cannot read '{point}.{name}' for this mix (missing "
                f"variation point, variant, or attribute: {err})"
            ) from err

    return {
        "motor_mass": attr("motors", "mass"),
        "prop_diameter_in": attr("props", "diameterIn"),
        "battery_mass": attr("battery", "mass"),
        "esc_mass": attr("esc", "mass"),
    }


def architecture_geometry(
    study: TradeStudy, architecture: Architecture, **overrides: Any
) -> dict[str, Any]:
    """:func:`drone_geometry` for a mix (see :func:`architecture_params`)."""

    return drone_geometry(**{**architecture_params(study, architecture), **overrides})


# ---------------------------------------------------------------------------
# optional CAD bridge
# ---------------------------------------------------------------------------


def to_cadquery(
    *, prop_diameter_in: float, motor_mass: float, battery_mass: float, esc_mass: float
) -> Any:
    """The same parametric assembly as cadquery solids (``cad`` extra).

    Returns a ``cadquery.Assembly`` with one named, colored child per
    part -- ready for ``assembly.export("drone.step")`` or downstream CAD.
    Kept separate from the mesh pipeline so the viewer never depends on
    the OCC kernel.
    """

    try:
        import cadquery as cq
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise MissingExtraError(
            "longeron.analysis.geometry.to_cadquery", "cadquery", "cad"
        ) from err

    def color(name: str) -> Any:
        r, g, b = (int(COLORS[name][i : i + 2], 16) / 255 for i in (1, 3, 5))
        return cq.Color(r, g, b)

    prop_d = prop_diameter_in * IN
    spacing = prop_d + _PROP_CLEARANCE
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, bat_h = battery_size(battery_mass)
    esc_t = board_thickness(esc_mass)
    plate_side = max(0.075, bat_w + 0.014, _BOARD_SIDE + 0.024)
    arm_reach = (spacing / 2) * 2**0.5

    frame = cq.Workplane("XZ").box(plate_side, plate_side, _PLATE_THICKNESS)
    length = arm_reach + motor_d / 2
    for mx, mz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        angle = atan2(mz, mx)
        arm = (
            cq.Workplane("XZ")
            .box(length, _ARM_WIDTH, _ARM_THICKNESS)
            .translate((length / 2, 0, 0))
            .rotate((0, 0, 0), (0, 1, 0), -angle * 180.0 / pi)
        )
        frame = frame.union(arm)

    assembly = cq.Assembly(name="drone")
    assembly.add(frame, name="frame", color=color("frame"))
    for i, (mx, mz) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        x, z = mx * spacing / 2, mz * spacing / 2
        motor = cq.Workplane("XZ", origin=(x, motor_h / 2 + _ARM_THICKNESS / 2, z)).cylinder(
            motor_h, motor_d / 2, direct=(0, 1, 0)
        )
        prop = cq.Workplane(
            "XZ", origin=(x, _ARM_THICKNESS / 2 + motor_h + 0.002 + 0.00125, z)
        ).cylinder(0.0025, prop_d / 2, direct=(0, 1, 0))
        assembly.add(motor, name=f"motor{i + 1}", color=color("motors"))
        assembly.add(prop, name=f"prop{i + 1}", color=color("props"))
    battery = cq.Workplane("XZ", origin=(0, -(_PLATE_THICKNESS / 2 + 0.004 + bat_h / 2), 0)).box(
        bat_l, bat_w, bat_h
    )
    esc = cq.Workplane("XZ", origin=(0, _PLATE_THICKNESS / 2 + esc_t / 2, 0)).box(
        _BOARD_SIDE, _BOARD_SIDE, esc_t
    )
    assembly.add(battery, name="battery", color=color("battery"))
    assembly.add(esc, name="esc", color=color("esc"))
    return assembly
