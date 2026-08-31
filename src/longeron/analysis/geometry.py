"""Parametric 3D geometry for architecture mixes (spike).

Builds to-scale UAVs from a mix's catalog attribute values with plain
triangle meshes (stdlib ``math`` only).  Four airframe families are
supported: the N-arm multirotor (:func:`drone_geometry` -- arms every
``360 / N`` degrees, sized from prop diameter + tip clearance; a 3-arm
frame grows a tail boom, ``coaxial=True`` stacks counter-rotating motor
pairs on every arm, and the default is the classic quad), the
streamlined teardrop-body quad
(:func:`teardrop_quad_geometry` -- a lathed low-drag bullet stood on end,
its long axis normal to the planar rotor quad around it), the cruciform
tail-sitter VTOL (:func:`winged_vtol_geometry` -- a minimal lathed
fuselage, two unswept airfoil wing pairs in a ``+`` cruciform, and one
tractor rotor on each of the four wingtips with every thrust axis
parallel to the chords/body axis; baked nose-up in its hover attitude),
and the streamlined interceptor
(:func:`interceptor_geometry` -- slender lathed fuselage, thin unswept
NACA-0009 wing, cruciform tail, pusher prop).  The tailless flying wing
(:func:`flying_wing_geometry`) is the one family drawn with real
stability-and-control geometry: quarter-chord sweep, tip washout, and a
parametric reflexed section, straight from its model attributes.  Every
lifting surface is
lofted from a real NACA 4-digit section (:func:`naca4_profile`), not a
rectangular slab.  Motor cylinders come from motor mass
(solid-cylinder density heuristic), prop disks from diameter, and the
battery box from battery mass (LiPo density + brick proportions).  One
call turns a configuration into the mesh dict
:mod:`longeron.widgets.viewer3d` paints:

    {"unit": "m",
     "parts": [{"name", "color", "opacity",
                "vertices": [x, y, z, ...], "faces": [i, j, k, ...]}, ...],
     "bounds": [[xmin, ymin, zmin], [xmax, ymax, zmax]]}

A part may additionally carry a ``key`` -- a stable model identity (by
convention the SysML part usage's qualified name) stamped by
:func:`tag_parts` -- which the viewer uses for linked selection
(:mod:`longeron.analysis.link`); untagged parts fall back to their
``name``.

The same geometry feeds the GEOMETRIC REQUIREMENT CHECKS, which are
CAD-NATIVE: :func:`camera_occlusion` builds a VIEW CONE solid at a
mounted camera (apex at the lens, axis along the boresight, half-angle
``fieldOfView / 2``) and boolean-INTERSECTS it with every other
component's parametric solid -- the same solids :func:`to_cadquery`
builds -- reporting intersected volume over cone volume (0.0 is a
perfectly clear view), and :func:`disc_overlap` boolean-intersects each
propeller disc (a thin cylinder solid, stamped analytically by
:func:`drone_geometry` in ``split_instances`` mode) with every other
component, reporting the overlap volume (0.0 is no overlap).  cadquery
(the ``cad`` extra) powers the exact booleans; without it both checks
fall back to a deterministic stdlib volume quadrature over the mesh
triangles that integrates the SAME measures (see
:func:`occlusion_report` / :func:`overlap_report` for the accuracy
contract).  Both are deterministic and keyed by :func:`geometry_checks`
to feed the DeepScout program's ``installation`` requirements
(``examples/deepscout/aircraft.sysml``) through the scoreboard's
``values=`` seam in either posture.

House pattern: MESH geometry is baked in Python once per configuration
(a millisecond or so -- no CAD kernel in the render loop); the front-end
never recomputes it.  Y is up, +X is forward, one unit is one metre, and every
dimension is a real measurement or a documented heuristic, so two mixes
render truly to scale side by side (:func:`lineup` merges several
configurations into one to-scale scene).  :func:`mission_geometry`
dispatches a ``UavMissions``-style mix onto its family builder from the
selected airframe's attributes.

:func:`to_cadquery` rebuilds the quad-copter assembly as CAD solids
(STEP export, and the solid source of the CAD-native checks above)
behind the ``cad`` extra -- the mesh pipeline here deliberately does not
need the ~1 GB OCC kernel.
"""

from __future__ import annotations

from collections.abc import Mapping
from importlib.util import find_spec
from math import atan, atan2, ceil, cos, floor, pi, radians, sin, sqrt, tan
from typing import Any, Literal

from ..errors import MissingExtraError
from ._expr import AnalysisError
from .trades import Architecture, TradeStudy

__all__ = [
    "GeometryEngine",
    "airframe_geometry",
    "architecture_geometry",
    "architecture_params",
    "camera_occlusion",
    "disc_overlap",
    "drone_geometry",
    "flying_wing_geometry",
    "geometry_checks",
    "interceptor_geometry",
    "lineup",
    "mission_geometry",
    "mission_params",
    "naca4_profile",
    "occlusion_report",
    "overlap_report",
    "tag_parts",
    "teardrop_quad_geometry",
    "to_cadquery",
    "view_cone",
    "winged_vtol_geometry",
]

Mesh = tuple[list[float], list[int]]  # flat vertices, flat triangle indices

#: which implementation the interference/occlusion checks run on:
#: ``"cad"`` (exact booleans on the OCC kernel, behind the ``cad`` extra),
#: ``"mesh"`` (the dependency-free sampled fallback), or ``"auto"``
#: (cad when importable, mesh otherwise -- the honest default)
GeometryEngine = Literal["auto", "cad", "mesh"]

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
#: rear-boom reach over the regular arm reach on a 3-arm frame: the
#: RCExplorer-style tail boom carries the tilt mount and visibly reads
#: as a boom, not a fourth arm
_TRI_BOOM_RATIO = 1.3
#: m: standoff drop of a coax pair's lower motor below its arm (20 mm
#: standoff posts -- clears the battery brick under the centre plate)
_COAX_DROP = 0.02

#: per-part colors: muted categorical set at roughly constant lightness
COLORS = {
    "frame": "#4a4e54",  # neutral dark (fuselage, booms, plates)
    "motors": "#b4674e",  # terracotta (motor cans + nacelles)
    "props": "#58939b",  # teal (drawn translucent: a spinning disk)
    "battery": "#7181b8",  # indigo
    "esc": "#a58a4d",  # ochre
    "wing": "#6f8f6a",  # sage
    "tail": "#8a8f98",  # light gray (stabilizers)
    "camera": "#7a5d8c",  # violet (the mission camera body)
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


def _arm_angles(arm_count: int) -> list[float]:
    """Arm azimuths (radians about +Y, matching ``atan2(z, x)`` of the
    arm's tip direction, applied via ``_rotate_y(arm, -angle)``) for an
    N-arm frame.

    Arms sit every ``360 / N`` degrees at the odd multiples of
    ``pi / N`` -- the flight-controller \"X\" convention: no arm points
    straight forward, so the nose (and the mission camera) stays clear.
    Ordering pairs mirror arms front to back (``+pi/N, -pi/N, +3pi/N,
    ...``); an odd N ends with the single rear arm at ``pi`` -- on a
    tricopter, the tail boom.  The quad's four angles reproduce the
    legacy ``atan2(+-1, +-1)`` layout exactly.
    """

    if arm_count < 3:
        raise AnalysisError(f"a multirotor frame needs at least 3 arms (got {arm_count!r})")
    angles: list[float] = []
    k = 1
    while len(angles) < arm_count:
        angles.append(k * pi / arm_count)
        if len(angles) < arm_count:
            angles.append(-k * pi / arm_count)
        k += 2
    return angles


def _rotor_stations(arm_count: int, spacing: float) -> list[tuple[float, float, float, float]]:
    """Per-arm ``(angle, x, z, reach)`` motor stations for an N-arm frame.

    Adjacent rotor axes sit ``spacing`` apart on a circle of radius
    ``spacing / (2 sin(pi / N))``, so the derived prop discs just clear
    each other for every N.  On a 3-arm frame the rear station rides
    ``_TRI_BOOM_RATIO`` further out: the tail boom.  The 4-arm case is
    computed the exact legacy way (``+-spacing/2`` on each axis) so the
    stock quad stays byte-stable.
    """

    angles = _arm_angles(arm_count)
    if arm_count == 4:
        reach = (spacing / 2) * 2**0.5
        signs = ((1, 1), (1, -1), (-1, 1), (-1, -1))
        return [
            (angle, mx * spacing / 2, mz * spacing / 2, reach)
            for angle, (mx, mz) in zip(angles, signs, strict=True)
        ]
    radius = spacing / (2.0 * sin(pi / arm_count))
    stations = []
    for angle in angles:
        reach = radius * (_TRI_BOOM_RATIO if arm_count == 3 and angle == pi else 1.0)
        stations.append((angle, reach * cos(angle), reach * sin(angle), reach))
    return stations


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
    arm_count: int = 4,
    coaxial: bool = False,
    arm_thickness: float = _ARM_THICKNESS,
    arm_width: float = _ARM_WIDTH,
    segments: int = 24,
    split_instances: bool = False,
    motor_spacing: float | None = None,
    camera: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """A to-scale multirotor mesh dict from catalog attribute values.

    ``arm_count`` sets the frame family: arms radiate every ``360 / N``
    degrees (:func:`_arm_angles` -- the \"X\" convention, nose clear),
    a 3-arm frame stretches its single rear arm into the tail boom
    (``_TRI_BOOM_RATIO``), and the default 4 reproduces the classic
    quad byte-for-byte.  ``coaxial`` stacks a counter-rotating pair on
    every arm: the upper motor rides the arm top exactly like the flat
    build, the lower hangs ``_COAX_DROP`` beneath it on a drawn
    standoff post, and its prop disc spins below -- two discs per arm,
    both stamped in ``split_instances`` mode.

    The frame is *derived*: adjacent motors sit one prop diameter plus
    ``_PROP_CLEARANCE`` apart (for any N, on the circle that spacing
    implies), so a 10-inch cruiser genuinely dwarfs a 5-inch racer and
    a hexa is honestly wider than a quad.  ``motor_spacing`` overrides
    that derivation with a FIXED adjacent motor-to-motor distance -- a
    real frame does not grow when a bigger prop is bolted onto it, so a
    prop-swap what-if passes the stock spacing and lets
    :func:`disc_overlap` judge the result.
    ``arm_thickness``/``arm_width`` default to the demo
    heuristics; callers with load-sized arm tubes (see
    :func:`mission_geometry`) pass the sized outer diameter so heavier-
    loaded designs genuinely look beefier.  Parts of one kind merge into
    a single mesh (one draw call each in the viewer).

    ``split_instances`` keeps the motor and prop instances as separate
    parts -- ``motor1`` .. ``motorR`` and ``prop1`` .. ``propR`` for
    ``R`` rotors, the same names and order as the :func:`to_cadquery`
    assembly children (coaxial builds count the uppers first, arm by
    arm, then the lowers in the same arm order) -- so each can carry
    its own identity key (e.g. an M0 individual id, see
    :func:`tag_parts`) for per-instance linked selection.  The
    geometry is a pure re-partition: concatenating the instance parts
    reproduces the merged part exactly, and the default (``False``)
    output is unchanged.  Split mode additionally stamps the analytic
    propeller discs onto the mesh (``mesh["discs"]``: centre, normal,
    radius, thickness, owning part, and the same-station parts an
    overlap check must ignore) -- the input :func:`overlap_report`
    consumes -- and the parametric recipe (``mesh["cad"]``: this
    function's own sizing inputs) from which the CAD-native checks
    rebuild the exact solids via :func:`to_cadquery`.

    ``camera`` mounts the mission camera: a mapping with the placement
    and boresight attribute names of the DeepScout program's
    ``ScoutParts::F450Kit::Camera`` part (``x``/``y``/``z`` metres from the top-plate centre,
    ``azimuth``/``elevation``/``fieldOfView`` degrees), typically the
    slot dict of an instantiated/interpreted camera individual.  It adds
    a violet ``camera`` body part (a small box, yawed to the azimuth)
    and stamps the parameters on ``mesh["camera"]`` for
    :func:`camera_occlusion`'s view cone.
    """

    prop_d = prop_diameter_in * IN
    spacing = prop_d + _PROP_CLEARANCE if motor_spacing is None else motor_spacing
    if spacing <= 0:
        raise AnalysisError(f"motor spacing must be positive (got {spacing!r})")
    arm_stations = _rotor_stations(arm_count, spacing)
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, bat_h = battery_size(battery_mass)
    esc_t = board_thickness(esc_mass)

    plate_side = max(0.075, bat_w + 0.014, _BOARD_SIDE + 0.024)
    motor_y = arm_thickness / 2 + motor_h / 2
    prop_y = arm_thickness / 2 + motor_h + 0.002 + 0.00125
    # the coax pair's lower station mirrors the upper below the arm,
    # dropped on a standoff post so the disc clears the battery brick
    low_motor_y = -(arm_thickness / 2 + _COAX_DROP + motor_h / 2)
    low_prop_y = -(arm_thickness / 2 + _COAX_DROP + motor_h + 0.002 + 0.00125)

    arms, posts, motors, props = [], [], [], []
    for angle, x, z, reach in arm_stations:
        arm_length = reach + motor_d / 2
        arm = _box(arm_length, arm_thickness, arm_width, cx=arm_length / 2)
        arms.append((_rotate_y(arm[0], -angle), arm[1]))
        motors.append(_cylinder(motor_d / 2, motor_h, x, motor_y, z, segments))
        props.append(_cylinder(prop_d / 2, 0.0025, x, prop_y, z, max(segments, 32)))
    if coaxial:
        for _angle, x, z, _reach in arm_stations:
            posts.append(
                _cylinder(0.004, _COAX_DROP, x, -(arm_thickness / 2 + _COAX_DROP / 2), z, segments)
            )
            motors.append(_cylinder(motor_d / 2, motor_h, x, low_motor_y, z, segments))
            props.append(_cylinder(prop_d / 2, 0.0025, x, low_prop_y, z, max(segments, 32)))

    frame = _merge(_box(plate_side, _PLATE_THICKNESS, plate_side), *arms, *posts)
    battery = _box(bat_l, bat_w, bat_h, cy=-(_PLATE_THICKNESS / 2 + 0.004 + bat_h / 2))
    esc = _box(_BOARD_SIDE, esc_t, _BOARD_SIDE, cy=_PLATE_THICKNESS / 2 + esc_t / 2)

    camera_part: list[tuple[str, Mesh, float]] = []
    if camera is not None:
        params = _camera_params(camera)
        body = _box(0.020, 0.016, 0.016)  # a 20 x 16 x 16 mm camera pod
        body = (_rotate_y(body[0], radians(params["azimuth"])), body[1])
        body = (_translate(body[0], params["x"], params["y"], params["z"]), body[1])
        camera_part.append(("camera", body, 1.0))

    # rotor stations in instance order: the uppers arm by arm, then (for
    # a coax build) the lowers in the same arm order, one disc each
    discs = [(x, prop_y, z) for _angle, x, z, _reach in arm_stations]
    if coaxial:
        discs += [(x, low_prop_y, z) for _angle, x, z, _reach in arm_stations]
    if split_instances:
        parts: list[tuple[str, Mesh, float]] = [
            ("frame", frame, 1.0),
            *((f"motor{i + 1}", motor, 1.0) for i, motor in enumerate(motors)),
            *((f"prop{i + 1}", prop, 0.55) for i, prop in enumerate(props)),
            ("battery", battery, 1.0),
            ("esc", esc, 1.0),
            *camera_part,
        ]
        instance_colors = {
            f"{kind}{i + 1}": COLORS[f"{kind}s"]
            for kind in ("motor", "prop")
            for i in range(len(discs))
        }
        mesh = _pack(parts, colors=instance_colors)
        mesh["discs"] = [
            {
                "part": f"prop{i + 1}",
                "center": [round(x, 5), round(y, 5), round(z, 5)],
                "normal": [0.0, 1.0, 0.0],
                "radius": round(prop_d / 2, 5),
                "thickness": 0.0025,
                "exclude": [f"motor{i + 1}", f"prop{i + 1}"],
            }
            for i, (x, y, z) in enumerate(discs)
        ]
        mesh["cad"] = {
            "prop_diameter_in": prop_diameter_in,
            "motor_mass": motor_mass,
            "battery_mass": battery_mass,
            "esc_mass": esc_mass,
            "arm_count": arm_count,
            "coaxial": coaxial,
            "arm_thickness": arm_thickness,
            "arm_width": arm_width,
            "motor_spacing": motor_spacing,
        }
        if camera is not None:
            mesh["camera"] = _camera_params(camera)
        return mesh
    parts = [
        ("frame", frame, 1.0),
        ("motors", _merge(*motors), 1.0),
        ("props", _merge(*props), 0.55),
        ("battery", battery, 1.0),
        ("esc", esc, 1.0),
        *camera_part,
    ]
    mesh = _pack(parts)
    if camera is not None:
        mesh["camera"] = _camera_params(camera)
    return mesh


# ---------------------------------------------------------------------------
# geometric requirement checks (camera view cone, prop-disc overlap)
# ---------------------------------------------------------------------------

#: the camera parameter names -- exactly the attribute names of
#: the DeepScout program's ``ScoutParts::F450Kit::Camera`` part, so an
#: instantiated / M0-interpreted camera's slot dict wires straight through
_CAMERA_KEYS = ("x", "y", "z", "azimuth", "elevation", "fieldOfView")

#: boolean-intersection volumes below this (m^3) count as zero: OCC
#: booleans on flush faces (the ESC sitting directly on the top plate)
#: can return slivers of numerical dust instead of an empty shape
_VOLUME_EPS = 1e-12

#: propeller-disc solid thickness (m) assumed when a stamped disc does
#: not carry its own ``thickness`` -- the prop-cylinder thickness of
#: :func:`drone_geometry` and :func:`to_cadquery`
_DISC_THICKNESS = 0.0025

#: fixed parity-ray direction for point-in-solid tests: (1, 2, 3)
#: normalized -- oblique to every axis-aligned face and lathe/fan edge of
#: the primitive meshes, so no quadrature sample's ray grazes an edge
_PARITY_DIR: Vec = (0.2672612419124244, 0.5345224838248488, 0.8017837257372732)


def _camera_params(camera: Mapping[str, Any]) -> dict[str, float]:
    """Validate/normalize a camera mapping (see :data:`_CAMERA_KEYS`)."""

    missing = [k for k in _CAMERA_KEYS if k not in camera]
    if missing:
        raise AnalysisError(
            f"camera mapping is missing {missing} (needs the Camera part's "
            f"attributes: {list(_CAMERA_KEYS)})"
        )
    params = {k: float(camera[k]) for k in _CAMERA_KEYS}
    if not 0.0 < params["fieldOfView"] < 180.0:
        raise AnalysisError(
            f"fieldOfView must be in (0, 180) degrees (got {params['fieldOfView']!r})"
        )
    return params


def _boresight(azimuth_deg: float, elevation_deg: float) -> Vec:
    """The unit view direction: +x forward, +y up; azimuth is a right-hand
    rotation about +y (positive yaws +x toward -z), elevation pitches
    above the horizon."""

    az, el = radians(azimuth_deg), radians(elevation_deg)
    return (cos(el) * cos(az), sin(el), -cos(el) * sin(az))


def _perpendicular(normal: Vec) -> tuple[Vec, Vec]:
    """Two unit vectors completing a right-handed frame with ``normal``."""

    nx, ny, nz = normal
    ux, uy, uz = (1.0, 0.0, 0.0) if abs(nx) < 0.9 else (0.0, 1.0, 0.0)
    vx, vy, vz = ny * uz - nz * uy, nz * ux - nx * uz, nx * uy - ny * ux
    norm = sqrt(vx * vx + vy * vy + vz * vz)
    vx, vy, vz = vx / norm, vy / norm, vz / norm
    return (vx, vy, vz), (ny * vz - nz * vy, nz * vx - nx * vz, nx * vy - ny * vx)


def _part_triangles(part: Mapping[str, Any]) -> list[tuple[Vec, Vec, Vec]]:
    v, f = part["vertices"], part["faces"]
    tris = []
    for i in range(0, len(f), 3):
        a, b, c = f[i] * 3, f[i + 1] * 3, f[i + 2] * 3
        tris.append(
            (
                (v[a], v[a + 1], v[a + 2]),
                (v[b], v[b + 1], v[b + 2]),
                (v[c], v[c + 1], v[c + 2]),
            )
        )
    return tris


def _part_aabb(part: Mapping[str, Any]) -> tuple[Vec, Vec]:
    v = part["vertices"]
    return (
        (min(v[0::3]), min(v[1::3]), min(v[2::3])),
        (max(v[0::3]), max(v[1::3]), max(v[2::3])),
    )


def _ray_hits_triangle(origin: Vec, direction: Vec, tri: tuple[Vec, Vec, Vec]) -> bool:
    """Moller-Trumbore, no backface culling, hits strictly ahead only."""

    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
    e1 = (bx - ax, by - ay, bz - az)
    e2 = (cx - ax, cy - ay, cz - az)
    px = direction[1] * e2[2] - direction[2] * e2[1]
    py = direction[2] * e2[0] - direction[0] * e2[2]
    pz = direction[0] * e2[1] - direction[1] * e2[0]
    det = e1[0] * px + e1[1] * py + e1[2] * pz
    if abs(det) < 1e-14:
        return False
    inv = 1.0 / det
    tx, ty, tz = origin[0] - ax, origin[1] - ay, origin[2] - az
    u = (tx * px + ty * py + tz * pz) * inv
    if u < 0.0 or u > 1.0:
        return False
    qx = ty * e1[2] - tz * e1[1]
    qy = tz * e1[0] - tx * e1[2]
    qz = tx * e1[1] - ty * e1[0]
    v = (direction[0] * qx + direction[1] * qy + direction[2] * qz) * inv
    if v < 0.0 or u + v > 1.0:
        return False
    t = (e2[0] * qx + e2[1] * qy + e2[2] * qz) * inv
    return t > 1e-9


#: one closed connected sub-solid of a mesh part: its triangles + AABB
_Component = tuple[list[tuple[Vec, Vec, Vec]], Vec, Vec]


def _solid_components(part: Mapping[str, Any]) -> list[_Component]:
    """The closed connected sub-solids of a (possibly merged) mesh part.

    A merged part (the frame: centre plate + four arm boxes) is a
    concatenation of closed sub-meshes that INTERPENETRATE, so ray
    parity over the whole triangle soup misclassifies points inside two
    sub-solids at once (two exits -> even -> "outside").  Vertices are
    merged positionally and faces grouped by connectivity; membership is
    then decided per component (:func:`_point_in_part`), each with its
    own AABB prune.
    """

    vertices, faces = part["vertices"], part["faces"]
    canonical: dict[tuple[float, float, float], int] = {}
    index_of = []
    for i in range(0, len(vertices), 3):
        key = (round(vertices[i], 7), round(vertices[i + 1], 7), round(vertices[i + 2], 7))
        index_of.append(canonical.setdefault(key, len(canonical)))
    parent = list(range(len(canonical)))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for i in range(0, len(faces), 3):
        a = find(index_of[faces[i]])
        for k in (1, 2):
            parent[find(index_of[faces[i + k]])] = a

    grouped: dict[int, list[tuple[Vec, Vec, Vec]]] = {}
    for i in range(0, len(faces), 3):
        a, b, c = faces[i] * 3, faces[i + 1] * 3, faces[i + 2] * 3
        grouped.setdefault(find(index_of[faces[i]]), []).append(
            (
                (vertices[a], vertices[a + 1], vertices[a + 2]),
                (vertices[b], vertices[b + 1], vertices[b + 2]),
                (vertices[c], vertices[c + 1], vertices[c + 2]),
            )
        )

    components: list[_Component] = []
    for tris in grouped.values():
        xs = [p[0] for tri in tris for p in tri]
        ys = [p[1] for tri in tris for p in tri]
        zs = [p[2] for tri in tris for p in tri]
        components.append((tris, (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))))
    return components


def _point_in_part(point: Vec, components: list[_Component]) -> bool:
    """Ray-parity membership: inside ANY closed component of the part."""

    for tris, lo, hi in components:
        if not all(lo[i] - 1e-9 <= point[i] <= hi[i] + 1e-9 for i in range(3)):
            continue
        crossings = sum(1 for tri in tris if _ray_hits_triangle(point, _PARITY_DIR, tri))
        if crossings % 2 == 1:
            return True
    return False


def _cone_cells(
    params: Mapping[str, float], length: float, resolution: int
) -> list[tuple[Vec, float]]:
    """Deterministic quadrature cells filling the view cone.

    The cone is cut into ``resolution`` axial slabs (exact slab
    volumes), each slab into ``max(resolution // 4, 4)`` equal-area
    radial rings times ``resolution`` azimuthal sectors.  Every cell
    yields its centre point and its EXACT volume, so the weights sum to
    the cone volume and a cone that intersects nothing integrates to
    exactly 0.0 occluded volume.
    """

    axial, radial, azimuthal = resolution, max(resolution // 4, 4), resolution
    apex = (params["x"], params["y"], params["z"])
    axis = _boresight(params["azimuth"], params["elevation"])
    u, w = _perpendicular(axis)
    tan_half = tan(radians(params["fieldOfView"]) / 2.0)
    cells: list[tuple[Vec, float]] = []
    for k in range(axial):
        t0, t1 = length * k / axial, length * (k + 1) / axial
        tc = (t0 + t1) / 2.0
        slab = pi * tan_half * tan_half * (t1**3 - t0**3) / 3.0
        for j in range(radial):
            weight = slab * (2 * j + 1) / (radial * radial * azimuthal)
            r = tc * tan_half * (j + 0.5) / radial
            for m in range(azimuthal):
                angle = 2.0 * pi * (m + 0.5) / azimuthal
                c, s = r * cos(angle), r * sin(angle)
                cells.append(
                    (
                        (
                            apex[0] + axis[0] * tc + u[0] * c + w[0] * s,
                            apex[1] + axis[1] * tc + u[1] * c + w[1] * s,
                            apex[2] + axis[2] * tc + u[2] * c + w[2] * s,
                        ),
                        weight,
                    )
                )
    return cells


def _disc_cells(disc: Mapping[str, Any], resolution: int) -> list[tuple[Vec, float]]:
    """Deterministic quadrature cells filling a propeller-disc solid.

    ``resolution`` equal-area radial rings times ``4 * resolution``
    azimuthal sectors on the disc mid-plane, each cell weighted by its
    exact area times the disc thickness (the disc is wafer-thin against
    every neighbouring feature, so mid-plane membership stands in for
    the through-thickness integral).  Weights sum to the disc volume.
    """

    cx, cy, cz = (float(c) for c in disc["center"])
    nx, ny, nz = (float(c) for c in disc["normal"])
    norm = sqrt(nx * nx + ny * ny + nz * nz)
    if norm <= 0:
        raise AnalysisError("disc normal must be non-zero")
    radius = float(disc["radius"])
    if radius <= 0:
        raise AnalysisError(f"disc radius must be positive (got {radius!r})")
    u, w = _perpendicular((nx / norm, ny / norm, nz / norm))
    thickness = float(disc.get("thickness", _DISC_THICKNESS))
    radial, azimuthal = resolution, 4 * resolution
    volume = pi * radius * radius * thickness
    cells: list[tuple[Vec, float]] = []
    for j in range(radial):
        weight = volume * (2 * j + 1) / (radial * radial * azimuthal)
        r = radius * (j + 0.5) / radial
        for m in range(azimuthal):
            angle = 2.0 * pi * (m + 0.5) / azimuthal
            c, s = r * cos(angle), r * sin(angle)
            cells.append(
                (
                    (cx + u[0] * c + w[0] * s, cy + u[1] * c + w[1] * s, cz + u[2] * c + w[2] * s),
                    weight,
                )
            )
    return cells


def _bounds_diagonal(mesh: Mapping[str, Any]) -> float:
    """The mesh bounding-box diagonal: the default view-cone reach."""

    bounds = mesh.get("bounds")
    if bounds is None:
        boxes = [_part_aabb(p) for p in mesh["parts"]]
        bounds = (
            [min(lo[i] for lo, _ in boxes) for i in range(3)],
            [max(hi[i] for _, hi in boxes) for i in range(3)],
        )
    (x0, y0, z0), (x1, y1, z1) = bounds
    return sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2 + (z1 - z0) ** 2)


def _cad_available() -> bool:
    """Is cadquery installed (probed without importing the OCC kernel)?"""

    return find_spec("cadquery") is not None


def _require_cadquery(feature: str) -> Any:
    try:
        import cadquery
    except ImportError as err:
        raise MissingExtraError(feature, "cadquery", "cad") from err
    return cadquery


def _resolve_engine(engine: GeometryEngine, mesh: Mapping[str, Any]) -> Literal["cad", "mesh"]:
    """``auto`` picks CAD when cadquery AND a stamped recipe are at hand."""

    if engine not in ("auto", "cad", "mesh"):
        raise AnalysisError(f"engine must be 'auto', 'cad', or 'mesh' (got {engine!r})")
    if engine == "auto":
        return "cad" if "cad" in mesh and _cad_available() else "mesh"
    return engine


def _shape(obj: Any) -> Any:
    """A cadquery Workplane or bare Shape as a bare Shape."""

    return obj.val() if hasattr(obj, "val") else obj


def _intersection_volume(a: Any, b: Any) -> float:
    """The volume of the boolean intersection, with the dust clamp."""

    volume = float(a.intersect(b).Volume())
    return volume if volume > _VOLUME_EPS else 0.0


def _fused_intersection_volume(target: Any, offenders: list[Any]) -> float:
    """Volume of ``target & union(offenders)`` (0.0 for no offenders)."""

    if not offenders:
        return 0.0
    union = offenders[0]
    for solid in offenders[1:]:
        union = union.fuse(solid)
    return _intersection_volume(target, union)


def _cad_parts(mesh: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """The mesh's parametric CAD twin as ordered (name, Shape) pairs.

    Rebuilt by :func:`to_cadquery` from the recipe ``drone_geometry``
    stamps on ``mesh["cad"]`` in ``split_instances`` mode (plus the
    mounted camera, if any), so the booleans run against the exact
    parametric solids, not mesh tessellations.
    """

    recipe = mesh.get("cad")
    if recipe is None:
        raise AnalysisError(
            "this mesh carries no CAD recipe: build it with "
            "drone_geometry(split_instances=True), or pass engine='mesh'"
        )
    assembly = to_cadquery(**recipe, camera=mesh.get("camera"))
    return [(child.name, _shape(child.obj)) for child in assembly.children]


def view_cone(camera: Mapping[str, Any], *, length: float) -> Any:
    """The camera's view cone as a cadquery solid (``cad`` extra).

    Apex at the camera position, axis along the azimuth/elevation
    boresight, half-angle ``fieldOfView / 2``, truncated ``length``
    metres from the apex (the sensing range under test).  This is the
    solid the CAD-native occlusion check boolean-intersects with the
    airframe: any non-empty intersection is an obstruction.  ``camera``
    uses the ``Camera`` part's attribute names (see
    :func:`occlusion_report`).
    """

    cq = _require_cadquery("longeron.analysis.geometry.view_cone")
    params = _camera_params(camera)
    if length <= 0:
        raise AnalysisError(f"view cone length must be positive (got {length!r})")
    return cq.Solid.makeCone(
        0.0,
        length * tan(radians(params["fieldOfView"]) / 2.0),
        length,
        pnt=cq.Vector(params["x"], params["y"], params["z"]),
        dir=cq.Vector(*_boresight(params["azimuth"], params["elevation"])),
    )


def _occlusion_result(
    engine: Literal["cad", "mesh"],
    occluded: float,
    cone_volume: float,
    length: float,
    obstructions: dict[str, float],
) -> dict[str, Any]:
    return {
        "engine": engine,
        "occludedFraction": occluded / cone_volume,
        "occludedVolume": occluded,
        "coneVolume": cone_volume,
        "sensingRange": length,
        "obstructions": dict(sorted(obstructions.items(), key=lambda kv: -kv[1])),
    }


def _occlusion_cad(
    mesh: Mapping[str, Any],
    params: Mapping[str, float],
    length: float,
    exclude: tuple[str, ...],
) -> dict[str, Any]:
    cone = view_cone(params, length=length)
    cone_volume = float(cone.Volume())
    obstructions: dict[str, float] = {}
    offenders: list[Any] = []
    for name, solid in _cad_parts(mesh):
        if name in exclude:
            continue
        volume = _intersection_volume(cone, solid)
        if volume > 0.0:
            obstructions[name] = volume
            offenders.append(solid)
    occluded = _fused_intersection_volume(cone, offenders)
    return _occlusion_result("cad", occluded, cone_volume, length, obstructions)


def _occlusion_mesh(
    mesh: Mapping[str, Any],
    params: Mapping[str, float],
    length: float,
    exclude: tuple[str, ...],
    resolution: int,
) -> dict[str, Any]:
    parts = [p for p in mesh["parts"] if p["name"] not in exclude]
    components = [_solid_components(p) for p in parts]
    tan_half = tan(radians(params["fieldOfView"]) / 2.0)
    cone_volume = pi * tan_half * tan_half * length**3 / 3.0
    occluded = 0.0
    obstructions: dict[str, float] = {}
    for point, weight in _cone_cells(params, length, resolution):
        for part, comps in zip(parts, components, strict=True):
            if _point_in_part(point, comps):
                occluded += weight
                obstructions[part["name"]] = obstructions.get(part["name"], 0.0) + weight
                break
    return _occlusion_result("mesh", occluded, cone_volume, length, obstructions)


def occlusion_report(
    mesh: Mapping[str, Any],
    camera: Mapping[str, Any] | None = None,
    *,
    sensing_range: float | None = None,
    resolution: int = 24,
    exclude: tuple[str, ...] = ("camera",),
    engine: GeometryEngine = "auto",
) -> dict[str, Any]:
    """How much of the camera's view cone the airframe fills, and what.

    The check is CAD-NATIVE: a VIEW CONE solid -- apex at the camera
    position, axis along the azimuth/elevation boresight, half-angle
    ``fieldOfView / 2``, reaching ``sensing_range`` metres (default: the
    airframe bounding-box diagonal, long enough to sweep past the whole
    craft) -- is boolean-intersected with every other component's
    parametric solid, the same solids :func:`to_cadquery` builds.  A
    perfectly clear view intersects nothing.  Returns::

        {"engine": "cad" | "mesh",
         "occludedFraction": intersected volume / cone volume,
         "occludedVolume": ...,             # m^3, union of all offenders
         "coneVolume": ..., "sensingRange": ...,
         "obstructions": {part: m^3, ...}}  # offenders, largest first

    ``engine`` picks the implementation.  ``"cad"`` (exact booleans)
    needs the ``cad`` extra and a mesh built by
    ``drone_geometry(split_instances=True)`` (which stamps the
    parametric recipe the solids are rebuilt from); ``"mesh"`` is a
    stdlib fallback that integrates the SAME measure by deterministic
    volume quadrature -- ray-parity point-in-solid tests over an exact
    cell decomposition of the cone -- against the mesh triangles.  The
    default ``"auto"`` uses CAD when both prerequisites hold.  The
    quadrature is exact for a clear cone (every weight counted is a
    genuine interior point) but can MISS features thinner than a grid
    cell (``resolution`` axial slabs); treat its nonzero readings as
    real and its zeros as "nothing grid-cell-sized".  CAD per-part
    volumes are each exact (parts that interpenetrate each other are
    counted once per part); the mesh engine attributes each cell to the
    first part (mesh order) containing it.

    ``camera`` defaults to the parameters stamped on ``mesh["camera"]``
    by :func:`drone_geometry`; pass an explicit mapping (the ``Camera``
    part's attribute names) for what-ifs -- e.g. the same camera yawed
    ``azimuth=180`` to look back through the airframe.  ``exclude``
    names mesh parts the cone may legitimately contain (the camera's own
    body, whose centre is the cone apex).  Deterministic in both
    engines: equal inputs give equal fractions.
    """

    if resolution < 1:
        raise AnalysisError(f"resolution must be >= 1 (got {resolution!r})")
    source = camera if camera is not None else mesh.get("camera")
    if source is None:
        raise AnalysisError(
            "no camera parameters: pass camera=... or build the mesh with "
            "drone_geometry(camera=...)"
        )
    params = _camera_params(source)
    length = float(sensing_range) if sensing_range is not None else _bounds_diagonal(mesh)
    if length <= 0:
        raise AnalysisError(f"sensing range must be positive (got {length!r})")
    if _resolve_engine(engine, mesh) == "cad":
        return _occlusion_cad(mesh, params, length, exclude)
    return _occlusion_mesh(mesh, params, length, exclude, resolution)


def camera_occlusion(
    mesh: Mapping[str, Any],
    camera: Mapping[str, Any] | None = None,
    *,
    sensing_range: float | None = None,
    resolution: int = 24,
    exclude: tuple[str, ...] = ("camera",),
    engine: GeometryEngine = "auto",
) -> float:
    """The airframe volume inside the view cone over the cone volume.

    The scalar measure behind the ``clearView`` requirement of
    the DeepScout program (\"occludedFraction\"): 0.0 is a perfectly
    clear view cone, anything positive means some component pokes into
    it.  See :func:`occlusion_report` for the cone construction, the
    engines, and the per-part offender breakdown.
    """

    report = occlusion_report(
        mesh,
        camera,
        sensing_range=sensing_range,
        resolution=resolution,
        exclude=exclude,
        engine=engine,
    )
    return float(report["occludedFraction"])


def _overlap_cad(mesh: Mapping[str, Any], discs: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    parts = _cad_parts(mesh)
    by_name = dict(parts)
    rows: list[dict[str, Any]] = []
    for disc in discs:
        name = disc["part"]
        solid = by_name.get(name)
        if solid is None:
            raise AnalysisError(f"no CAD part named {name!r} to check disc overlap against")
        excluded = set(disc.get("exclude", ())) | {name}
        per: dict[str, float] = {}
        offenders: list[Any] = []
        for other, other_solid in parts:
            if other in excluded:
                continue
            volume = _intersection_volume(solid, other_solid)
            if volume > 0.0:
                per[other] = volume
                offenders.append(other_solid)
        rows.append(
            {
                "disc": name,
                "engine": "cad",
                "overlap": _fused_intersection_volume(solid, offenders),
                "parts": dict(sorted(per.items(), key=lambda kv: -kv[1])),
            }
        )
    return rows


def _overlap_mesh(
    mesh: Mapping[str, Any], discs: list[Mapping[str, Any]], resolution: int
) -> list[dict[str, Any]]:
    parts = [(p, _solid_components(p)) for p in mesh["parts"]]
    rows: list[dict[str, Any]] = []
    for disc in discs:
        excluded = set(disc.get("exclude", ())) | {disc["part"]}
        per: dict[str, float] = {}
        overlap = 0.0
        for point, weight in _disc_cells(disc, resolution):
            for part, comps in parts:
                if part["name"] in excluded:
                    continue
                if _point_in_part(point, comps):
                    overlap += weight
                    per[part["name"]] = per.get(part["name"], 0.0) + weight
                    break
        rows.append(
            {
                "disc": disc["part"],
                "engine": "mesh",
                "overlap": overlap,
                "parts": dict(sorted(per.items(), key=lambda kv: -kv[1])),
            }
        )
    return rows


def overlap_report(
    mesh: Mapping[str, Any], *, resolution: int = 24, engine: GeometryEngine = "auto"
) -> list[dict[str, Any]]:
    """Per-disc overlap: how much of each propeller disc is inside what.

    The CAD-native reading of \"propeller discs shall not overlap other
    components\": each disc is a thin cylinder solid (the assembly's own
    prop cylinders), boolean-intersected with every other component's
    solid.  Consumes the analytic discs :func:`drone_geometry` stamps on
    ``mesh["discs"]`` in ``split_instances`` mode (a disc knows which
    same-station parts -- its own prop and motor can -- to ignore).
    Returns one row per disc, ordered as stamped::

        {"disc": "prop1", "engine": "cad", "overlap": 0.0,   # m^3
         "parts": {offender: m^3, ...}}                      # largest first

    ``overlap`` is the volume of the disc's intersection with the UNION
    of the non-excluded components -- exactly 0.0 when the disc is
    clear.  Engines as in :func:`occlusion_report`: ``"cad"`` computes
    exact booleans on the parametric solids (needs the ``cad`` extra +
    the stamped recipe); ``"mesh"`` estimates the same volumes by
    deterministic mid-plane quadrature over the stamped disc (exact-zero
    when clear, may miss sub-cell slivers); ``"auto"`` prefers CAD.
    """

    if resolution < 1:
        raise AnalysisError(f"resolution must be >= 1 (got {resolution!r})")
    discs = mesh.get("discs")
    if not discs:
        raise AnalysisError(
            "no propeller discs on this mesh: build it with drone_geometry(split_instances=True)"
        )
    if _resolve_engine(engine, mesh) == "cad":
        return _overlap_cad(mesh, discs)
    return _overlap_mesh(mesh, discs, resolution)


def disc_overlap(
    mesh: Mapping[str, Any], *, resolution: int = 24, engine: GeometryEngine = "auto"
) -> float:
    """The total propeller-disc overlap volume, in cubic metres.

    The scalar measure behind the ``propClearance`` requirement of
    the DeepScout program (\"discOverlapVolume\"): the sum over every
    disc of :func:`overlap_report`'s per-disc overlap.  0.0 means no
    disc touches anything; a disc-against-disc overlap counts once per
    participating disc.
    """

    rows = overlap_report(mesh, resolution=resolution, engine=engine)
    return sum(float(row["overlap"]) for row in rows)


def geometry_checks(
    mesh: Mapping[str, Any],
    *,
    sensing_range: float | None = None,
    resolution: int = 24,
    engine: GeometryEngine = "auto",
) -> dict[str, float]:
    """Both geometric requirement measures, keyed for the scoreboard.

    Returns ``{"occludedFraction": ..., "discOverlapVolume": ...}`` --
    exactly the free names the ``installation`` requirements of
    the DeepScout program measure, so the result feeds
    ``scoreboard(model, values=geometry_checks(mesh))`` directly (the
    lightest honest wiring: the measures are computed kernel-side from
    the same parametric geometry the 3D viewer paints, then injected as
    evaluation-frame bindings; nothing is baked into the model file).
    Needs a mesh built with ``drone_geometry(split_instances=True,
    camera=...)``.  Both measures read 0.0 for a clean installation in
    BOTH engines (see :func:`occlusion_report` for the engine contract).
    """

    return {
        "occludedFraction": camera_occlusion(
            mesh, sensing_range=sensing_range, resolution=resolution, engine=engine
        ),
        "discOverlapVolume": disc_overlap(mesh, resolution=resolution, engine=engine),
    }


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


#: the parametric reflexed camber line's shape (documented teaching
#: stand-in, see :func:`_reflexed_profile`): maximum positive camber as a
#: chord fraction, and the chordwise station where the camber crosses
#: zero on its way to the negative (reflexed) aft loading
_REFLEX_CAMBER = 0.02
_REFLEX_CROSSOVER = 0.75


def _reflexed_profile(code: str, points: int = 24) -> list[tuple[float, float]]:
    """A closed reflexed section: NACA 4-digit thickness on an S-camber.

    The camber line is the cubic ``y_c(x) = k x (1 - x) (x0 - x)`` --
    positive camber forward, NEGATIVE camber aft of the crossover
    ``x0 = _REFLEX_CROSSOVER`` (the reflex that gives a tailless wing
    its nose-up zero-lift moment), with ``k`` scaled so the maximum
    camber equals ``_REFLEX_CAMBER``.  This is a deliberate parametric
    stand-in, named as such: a real design lofts a catalog reflexed
    family (Eppler 33x / Horten practice), which is loft-framework
    work.  ``code`` contributes its NACA thickness digits only; its
    camber digits are ignored (spell them ``00``).  Same ordering
    contract as :func:`naca4_profile`: TE -> upper -> LE -> lower -> TE.
    """

    if len(code) != 4 or not code.isdigit():
        raise AnalysisError(f"not a 4-digit thickness code: {code!r}")
    if points < 8:
        raise AnalysisError("a reflexed section needs at least 8 points")
    t = int(code[2:]) / 100
    x0 = _REFLEX_CROSSOVER
    x_peak = ((1.0 + x0) - sqrt((1.0 + x0) ** 2 - 3.0 * x0)) / 3.0
    k = _REFLEX_CAMBER / (x_peak * (1.0 - x_peak) * (x0 - x_peak))
    half = points // 2

    upper: list[tuple[float, float]] = []
    lower: list[tuple[float, float]] = []
    for i in range(half + 1):
        x = 0.5 * (1.0 - cos(pi * i / half))  # cosine spacing, 0 = LE
        yt = (
            5.0
            * t
            * (0.2969 * sqrt(x) - 0.1260 * x - 0.3516 * x * x + 0.2843 * x**3 - 0.1036 * x**4)
        )
        yc = k * x * (1.0 - x) * (x0 - x)
        theta = atan(k * (x0 - 2.0 * (1.0 + x0) * x + 3.0 * x * x))
        upper.append((x - yt * sin(theta), yc + yt * cos(theta)))
        lower.append((x + yt * sin(theta), yc - yt * cos(theta)))
    return list(reversed(upper)) + lower[1:-1]


def _section_profile(section: str, points: int) -> list[tuple[float, float]]:
    """Section dispatch: a NACA 4-digit code, or ``"reflexed"`` + code."""

    if section.startswith("reflexed"):
        return _reflexed_profile(section[len("reflexed") :], points)
    return naca4_profile(section, points)


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
    sweep_deg: float = 0.0,
    washout_deg: float = 0.0,
) -> Mesh:
    """One lofted lifting-surface panel with a real airfoil section.

    The ``section`` -- a NACA 4-digit code, or ``"reflexed"`` + a
    4-digit code for the parametric reflexed camber stand-in
    (:func:`_reflexed_profile`) -- is swept from ``origin`` (the *root
    quarter-chord point*) along the unit ``direction`` for ``length``,
    the chord tapering ``root_chord`` -> ``tip_chord`` about the
    quarter-chord line.  ``sweep_deg`` rakes that line aft: each ring's
    origin shifts ``tan(sweep) x span distance`` along -X, so the
    quarter-chord line slopes at exactly the declared sweep; at the
    default 0 it stays exactly parallel to ``direction`` and the loft
    is byte-identical to the legacy unswept panel.  ``washout_deg``
    twists each ring nose-down about its own quarter-chord point,
    linearly with span position (the tip ring carries the full twist;
    any future intermediate ring inherits its interpolated share).
    Chords run along -X (leading edge forward); the section's
    thickness/camber axis is ``direction x X-hat``, so a horizontal
    panel swept toward +Z lifts upward and washout drops its tip
    leading edge.
    """

    dx, dy, dz = direction
    norm = sqrt(dx * dx + dy * dy + dz * dz)
    if norm <= 0 or min(length, root_chord, tip_chord) <= 0:
        raise AnalysisError("lift surface needs positive dimensions")
    dx, dy, dz = dx / norm, dy / norm, dz / norm
    # thickness axis n = direction x X-hat (unit, perpendicular to both)
    nx, ny, nz = (dy * 0.0 - dz * 0.0, dz * 1.0 - dx * 0.0, dx * 0.0 - dy * 1.0)
    profile = list(reversed(_section_profile(section, points)))
    aft_per_span = tan(radians(sweep_deg))  # quarter-chord rake, -X per span

    def ring(s: float) -> list[Vec]:
        chord = root_chord + (tip_chord - root_chord) * s
        ox = origin[0] + dx * length * s - aft_per_span * length * s
        oy = origin[1] + dy * length * s
        oz = origin[2] + dz * length * s
        out: list[Vec] = []
        if washout_deg == 0.0:  # the legacy loft, expression for expression
            for xa, ya in profile:
                along = (0.25 - xa) * chord  # x = quarter-chord + offset
                out.append(
                    (ox + along + nx * ya * chord, oy + ny * ya * chord, oz + nz * ya * chord)
                )
            return out
        twist = -radians(washout_deg) * s  # nose-down about the ring's qc
        c_t, s_t = cos(twist), sin(twist)
        for xa, ya in profile:
            along = (0.25 - xa) * chord
            rise = ya * chord
            u = along * c_t - rise * s_t  # chordwise, toward the LE (+X)
            v = along * s_t + rise * c_t  # thickness axis n
            out.append((ox + u + nx * v, oy + ny * v, oz + nz * v))
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


def flying_wing_geometry(
    *,
    wing_span: float,
    wing_area: float,
    taper: float,
    motor_count: float,
    prop_diameter: float,
    motor_mass: float,
    battery_mass: float,
    sweep_deg: float = 0.0,
    washout_deg: float = 0.0,
    section: str = "0015",
    segments: int = 24,
) -> dict[str, Any]:
    """A to-scale tailless flying wing: swept panels, trailing-edge pushers.

    The wing IS the airframe (the DeepScout ``FlyingWings`` convention:
    ``fuselageLength`` 0 marks the family): one straight-tapered panel
    pair lofted from ``section`` (a NACA 4-digit code or a
    ``"reflexed"``-prefixed one, see :func:`_lift_surface`), its
    quarter-chord line raked aft by ``sweep_deg`` and its tips twisted
    down by ``washout_deg``; a winglet rides each swept tip, raked with
    the wing; one pusher motor can per station hangs on the TRUE
    trailing edge -- carried aft with the local chord -- and the
    battery is an indigo sleeve bulging through the root bay.  The
    three planform knobs are the model's own declared attributes
    (``sweepDeg`` / ``washoutDeg`` / the reflexed 15% bay section of
    ``examples/deepscout/flyingwing.sysml``), so the drawn planform IS
    the declared one: in plan view the tips sit aft of the root
    leading edge by roughly half-span x tan(sweep).  One stand-in
    remains, named so nobody reads more than the mesh knows: the
    reflexed camber line is a simple parametric S-camber, not a
    catalog airfoil, and the panels loft straight -- the blended
    center body this family really flies is a job for the loft
    framework's lofted wing body.
    """

    if min(wing_span, wing_area, taper, prop_diameter) <= 0:
        raise AnalysisError("flying wing dimensions must be positive")
    stations = max(1, round(motor_count))
    mean_chord = wing_area / wing_span
    root = 2.0 * mean_chord / (1.0 + taper)
    tip = root * taper
    half = wing_span / 2
    aft_per_span = tan(radians(sweep_deg))  # quarter-chord rake, -X per span

    right = _lift_surface(
        origin=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0),
        length=half,
        root_chord=root,
        tip_chord=tip,
        section=section,
        sweep_deg=sweep_deg,
        washout_deg=washout_deg,
    )
    wing = _merge(right, _mirror_z(right))

    fin = _lift_surface(
        origin=(-aft_per_span * half, 0.0, half),  # the SWEPT tip quarter-chord
        direction=(0.0, 1.0, 0.0),
        length=0.16 * half,
        root_chord=0.8 * tip,
        tip_chord=0.5 * tip,
        section=TAIL_SECTION,
        sweep_deg=sweep_deg,  # the winglet rakes aft with the wing
    )
    winglets = _merge(fin, _mirror_z(fin))

    motor_d, motor_h = motor_size(motor_mass)
    if stations == 1:
        z_pods = [0.0]
    else:  # a symmetric row across the middle third of the span
        z_pods = [(2.0 * i / (stations - 1) - 1.0) * half / 3.0 for i in range(stations)]
    motor_meshes: list[Mesh] = []
    prop_meshes: list[Mesh] = []
    for z in z_pods:
        chord = root + (tip - root) * abs(z) / half
        # chords run LE +0.25c .. TE -0.75c about the local quarter-chord,
        # which the sweep carries aft: the pods hug the TRUE trailing edge
        x_te = -aft_per_span * abs(z) - 0.75 * chord
        can = _tube(
            [(x_te - 0.002, motor_d / 2), (x_te - 0.002 - motor_h, 0.4 * motor_d)], segments
        )
        disk = _tube(
            [
                (x_te - motor_h - 0.006, prop_diameter / 2),
                (x_te - motor_h - 0.0085, prop_diameter / 2),
            ],
            max(segments, 32),
        )
        motor_meshes.append((_translate(can[0], 0.0, 0.0, z), can[1]))
        prop_meshes.append((_translate(disk[0], 0.0, 0.0, z), disk[1]))

    bat_l, bat_w, _bat_h = battery_size(battery_mass)
    battery = _tube(
        [(min(bat_l / 2, 0.24 * root), bat_w / 2 + 0.002), (-bat_l / 2, bat_w / 2 + 0.002)],
        segments,
    )

    return _pack(
        [
            ("wing", wing, 1.0),
            ("winglets", winglets, 1.0),
            ("motors", _merge(*motor_meshes), 1.0),
            ("props", _merge(*prop_meshes), 0.55),
            ("battery", battery, 1.0),
        ],
        colors={"winglets": COLORS["tail"]},
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
    (``{text, anchor}``) that :func:`longeron.widgets.viewer3d.mesh_viewer`
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
    id** from :func:`longeron.m0.interpret` (``Rotorcraft::QuadCopter#0.
    motors#2``), whose dotted path derives the owning usage for linked
    selection (:func:`longeron.analysis.link.individual_qname`).
    Several mesh parts may share one key, and parts not named keep no
    key and fall back to their ``name`` as their identity in
    :mod:`longeron.widgets.viewer3d`.  Vertex and face arrays are
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


def mission_params(study: TradeStudy, architecture: Architecture) -> dict[str, Any]:
    """Geometry inputs from a mission-catalog mix.

    Expects variation points ``airframe`` (attributes ``wingSpan``,
    ``wingArea``, ``taper``, ``fuselageLength``, ``motorCount``,
    ``armCount``), ``motors`` (``mass``), ``props`` (``diameter``), and
    ``battery`` (``mass``) -- the convention of the DeepScout mission
    catalog (``examples/deepscout/missions.sysml``).  The tailless
    S&C knobs (``sweepDeg``, ``washoutDeg``, ``wingSection``) ride
    along when the selected airframe declares them and default to the
    unswept legacy planform when it does not.
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

    def optional(point: str, name: str, default: Any) -> Any:
        try:
            value = study.points[point].variants[architecture.selection[point]][name]
        except KeyError:
            return default
        return float(value) if isinstance(value, (int, float)) else value

    return {
        "wing_span": attr("airframe", "wingSpan"),
        "wing_area": attr("airframe", "wingArea"),
        "taper": attr("airframe", "taper"),
        "fuselage_length": attr("airframe", "fuselageLength"),
        "motor_count": attr("airframe", "motorCount"),
        "arm_count": attr("airframe", "armCount"),
        "motor_mass": attr("motors", "mass"),
        "prop_diameter": attr("props", "diameter"),
        "battery_mass": attr("battery", "mass"),
        # the tailless family's S&C planform knobs: optional on purpose
        # (only the flying wings declare them; every other airframe
        # keeps the zero-sweep, no-washout, NACA-section defaults)
        "sweep_deg": optional("airframe", "sweepDeg", 0.0),
        "washout_deg": optional("airframe", "washoutDeg", 0.0),
        "wing_section": optional("airframe", "wingSection", None),
    }


def airframe_geometry(
    *,
    wing_span: float,
    wing_area: float,
    taper: float,
    fuselage_length: float,
    motor_count: float,
    arm_count: int,
    prop_diameter: float,
    motor_mass: float,
    battery_mass: float,
    esc_mass: float = 0.014,
    arm_thickness: float | None = None,
    arm_width: float | None = None,
    sweep_deg: float = 0.0,
    washout_deg: float = 0.0,
    wing_section: str | None = None,
) -> dict[str, Any]:
    """Family-dispatched geometry from airframe-shell attribute values.

    The keyword names mirror the geometry knobs of the DeepScout
    ``Airframe`` def (``examples/deepscout/aircraft.sysml``) plus the
    propulsion sizes a mix or a display default supplies.  The
    dispatch ladder picks the builder: no wing and no fuselage ->
    :func:`drone_geometry` (the N-arm multirotor -- ``arm_count`` sets
    the frame family, and a station count of twice the arm count
    stacks the coaxial pairs); no wing but a real fuselage ->
    :func:`teardrop_quad_geometry` (the upended bullet); a wing with no
    fuselage -> :func:`flying_wing_geometry` (the tailless family: the
    wing IS the fuselage); a single motor station ->
    :func:`interceptor_geometry`; otherwise
    :func:`winged_vtol_geometry` (the cruciform tail-sitter, rendered
    in hover attitude).  ``arm_thickness``/``arm_width`` draw the quad
    families' arms at a load-sized tube diameter when given;
    ``esc_mass`` is the drone branch's 30.5 mm stack heuristic.  Two
    callers feed this ladder: :func:`mission_geometry` from a
    mission-catalog mix, and :func:`longeron.analysis.grand.scene_for`
    from a fleet airframe definition's own attributes.  The tailless
    S&C knobs (``sweep_deg``, ``washout_deg``, ``wing_section``) reach
    :func:`flying_wing_geometry` only -- the flying wings are the one
    family whose model declares them; every other loft keeps its
    zero-sweep planform until the loft framework generalizes.
    """

    arm_kw: dict[str, Any] = {}
    if arm_thickness is not None:
        arm_kw["arm_thickness"] = arm_thickness
    if arm_width is not None:
        arm_kw["arm_width"] = arm_width
    if wing_span <= 0:  # rotor-borne only
        if fuselage_length > 0:  # the streamlined teardrop shell
            return teardrop_quad_geometry(
                fuselage_length=fuselage_length,
                prop_diameter=prop_diameter,
                motor_mass=motor_mass,
                battery_mass=battery_mass,
                **arm_kw,
            )
        return drone_geometry(
            prop_diameter_in=prop_diameter / IN,
            motor_mass=motor_mass,
            battery_mass=battery_mass,
            esc_mass=esc_mass,
            arm_count=arm_count if arm_count > 0 else 4,
            coaxial=arm_count > 0 and motor_count == 2 * arm_count,
            **arm_kw,
        )
    if fuselage_length <= 0:  # tailless: the wing IS the fuselage
        return flying_wing_geometry(
            wing_span=wing_span,
            wing_area=wing_area,
            taper=taper,
            motor_count=motor_count,
            prop_diameter=prop_diameter,
            motor_mass=motor_mass,
            battery_mass=battery_mass,
            sweep_deg=sweep_deg,
            washout_deg=washout_deg,
            # None = no declared section: the legacy symmetric bay loft
            section=wing_section if wing_section is not None else "0015",
        )
    if motor_count <= 1:
        return interceptor_geometry(
            body_length=fuselage_length,
            wing_span=wing_span,
            wing_area=wing_area,
            taper=taper,
            prop_diameter=prop_diameter,
            motor_mass=motor_mass,
            battery_mass=battery_mass,
        )
    return winged_vtol_geometry(
        wing_span=wing_span,
        wing_area=wing_area,
        taper=taper,
        fuselage_length=fuselage_length,
        prop_diameter=prop_diameter,
        motor_mass=motor_mass,
        battery_mass=battery_mass,
    )


def mission_geometry(
    study: TradeStudy, architecture: Architecture, **overrides: Any
) -> dict[str, Any]:
    """Family-dispatched geometry for a mission-catalog mix.

    The selected airframe's attributes feed :func:`airframe_geometry`,
    whose dispatch ladder picks the family builder.  When the mix's
    metrics carry the load-sized ``armOuterDiameter`` (the assembly's
    structural sizing), the quad families draw their arms at that
    diameter -- a sprint-motor aluminum build genuinely looks beefier
    than a carbon eco build.
    """

    p = {**mission_params(study, architecture), **overrides}
    sized_arm = float(architecture.metrics.get("armOuterDiameter", 0.0) or 0.0)
    arm_kw: dict[str, Any] = (
        {"arm_thickness": sized_arm, "arm_width": sized_arm} if sized_arm > 0 else {}
    )
    return airframe_geometry(
        wing_span=p["wing_span"],
        wing_area=p["wing_area"],
        taper=p["taper"],
        fuselage_length=p["fuselage_length"],
        motor_count=p["motor_count"],
        arm_count=int(p["arm_count"]),
        prop_diameter=p["prop_diameter"],
        motor_mass=p["motor_mass"],
        battery_mass=p["battery_mass"],
        sweep_deg=p["sweep_deg"],
        washout_deg=p["washout_deg"],
        wing_section=p["wing_section"],
        **arm_kw,
    )


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
    *,
    prop_diameter_in: float,
    motor_mass: float,
    battery_mass: float,
    esc_mass: float,
    arm_count: int = 4,
    coaxial: bool = False,
    arm_thickness: float = _ARM_THICKNESS,
    arm_width: float = _ARM_WIDTH,
    motor_spacing: float | None = None,
    camera: Mapping[str, float] | None = None,
) -> Any:
    """The same parametric assembly as cadquery solids (``cad`` extra).

    Returns a ``cadquery.Assembly`` with one named, colored child per
    part -- ready for ``assembly.export("drone.step")`` or downstream
    CAD -- built from the same sizing inputs as :func:`drone_geometry`
    (``arm_count``/``coaxial`` pick the frame family and the coax
    stacking, ``motor_spacing`` fixes the adjacent motor-to-motor
    distance for prop-swap what-ifs, ``camera`` mounts the mission
    camera body and takes the ``Camera`` part's attribute names).  The
    child names and order match ``drone_geometry``'s
    ``split_instances`` parts (coax lowers follow the uppers).  These
    exact solids are what the CAD-native geometric checks
    (:func:`occlusion_report` / :func:`overlap_report`)
    boolean-intersect.  Kept separate from the mesh pipeline so the
    viewer never depends on the OCC kernel.
    """

    cq = _require_cadquery("longeron.analysis.geometry.to_cadquery")

    def color(name: str) -> Any:
        r, g, b = (int(COLORS[name][i : i + 2], 16) / 255 for i in (1, 3, 5))
        return cq.Color(r, g, b)

    prop_d = prop_diameter_in * IN
    spacing = prop_d + _PROP_CLEARANCE if motor_spacing is None else motor_spacing
    if spacing <= 0:
        raise AnalysisError(f"motor spacing must be positive (got {spacing!r})")
    arm_stations = _rotor_stations(arm_count, spacing)
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, bat_h = battery_size(battery_mass)
    esc_t = board_thickness(esc_mass)
    plate_side = max(0.075, bat_w + 0.014, _BOARD_SIDE + 0.024)

    frame = cq.Workplane("XZ").box(plate_side, plate_side, _PLATE_THICKNESS)
    for angle, x, z, reach in arm_stations:
        length = reach + motor_d / 2
        arm = (
            cq.Workplane("XZ")
            .box(length, arm_width, arm_thickness)
            .translate((length / 2, 0, 0))
            .rotate((0, 0, 0), (0, 1, 0), -angle * 180.0 / pi)
        )
        frame = frame.union(arm)
        if coaxial:  # the lower pair member's standoff post
            post = cq.Solid.makeCylinder(
                0.004,
                _COAX_DROP,
                pnt=cq.Vector(x, -(arm_thickness / 2 + _COAX_DROP), z),
                dir=cq.Vector(0, 1, 0),
            )
            frame = frame.union(post)

    # rotor stations in instance order (uppers, then coax lowers): the
    # base y of each motor can, matching the mesh's cylinder placement
    stations = [(x, z, arm_thickness / 2) for _angle, x, z, _reach in arm_stations]
    if coaxial:
        stations += [
            (x, z, -(arm_thickness / 2 + _COAX_DROP + motor_h))
            for _angle, x, z, _reach in arm_stations
        ]

    assembly = cq.Assembly(name="drone")
    assembly.add(frame, name="frame", color=color("frame"))
    for i, (x, z, base_y) in enumerate(stations):
        # global-frame cylinders: axis straight up (+y), like the mesh --
        # a Workplane("XZ").cylinder(direct=...) reads direct in LOCAL
        # plane coordinates and would lay the cans on their sides
        motor = cq.Solid.makeCylinder(
            motor_d / 2,
            motor_h,
            pnt=cq.Vector(x, base_y, z),
            dir=cq.Vector(0, 1, 0),
        )
        prop_base = base_y + motor_h + 0.002 if base_y >= 0 else base_y - 0.002 - 0.0025
        prop = cq.Solid.makeCylinder(
            prop_d / 2,
            0.0025,
            pnt=cq.Vector(x, prop_base, z),
            dir=cq.Vector(0, 1, 0),
        )
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
    if camera is not None:
        params = _camera_params(camera)
        body = (
            cq.Workplane("XZ")
            .box(0.020, 0.016, 0.016)
            .rotate((0, 0, 0), (0, 1, 0), params["azimuth"])
            .translate((params["x"], params["y"], params["z"]))
        )
        assembly.add(body, name="camera", color=color("camera"))
    return assembly
