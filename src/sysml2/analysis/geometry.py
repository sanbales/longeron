"""Parametric 3D geometry for architecture mixes (spike).

Builds to-scale UAVs from a mix's catalog attribute values with plain
triangle meshes (stdlib ``math`` only).  Three airframe families are
supported: the plain quad-copter (:func:`drone_geometry` -- frame sized
from prop diameter + tip clearance), the winged VTOL
(:func:`winged_vtol_geometry` -- wing from span/chord/taper, wingtip
nacelles carrying the two large forward props, twin booms to vertical
stabilizers topped by the two smaller lift props), and the streamlined
interceptor (:func:`interceptor_geometry` -- slender lathed fuselage,
small cruciform tail, pusher prop).  Motor cylinders come from motor mass
(solid-cylinder density heuristic), prop disks from diameter, and the
battery box from battery mass (LiPo density + brick proportions).  One
call turns a configuration into the mesh dict
:mod:`sysml2.analysis.viewer3d` paints:

    {"unit": "m",
     "parts": [{"name", "color", "opacity",
                "vertices": [x, y, z, ...], "faces": [i, j, k, ...]}, ...],
     "bounds": [[xmin, ymin, zmin], [xmax, ymax, zmax]]}

House pattern: geometry is baked in Python once per configuration (about
a millisecond at most -- no CAD kernel in the loop); the front-end never
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

from math import atan2, ceil, cos, floor, pi, sin
from typing import Any

from ._expr import AnalysisError
from .trades import Architecture, TradeStudy

__all__ = ["architecture_geometry", "architecture_params", "drone_geometry",
           "interceptor_geometry", "lineup", "mission_geometry",
           "mission_params", "to_cadquery", "winged_vtol_geometry"]

Mesh = tuple[list[float], list[int]]  # flat vertices, flat triangle indices

IN = 0.0254  # metres per inch

# --- documented sizing heuristics (SI) -------------------------------------
_MOTOR_DENSITY = 2800.0    # kg/m^3: solid-cylinder equivalent of a BLDC
_MOTOR_ASPECT = 0.7        # motor height / diameter (2306 -> 28 x 19 mm)
_BATTERY_DENSITY = 2400.0  # kg/m^3: LiPo brick incl. wrap and leads
_BATTERY_PROPORTIONS = (2.5, 1.2, 1.0)  # length : width : height
_BOARD_SIDE = 0.0305       # m: the standard 30.5 mm FC/ESC mount pattern
_BOARD_DENSITY = 1900.0    # kg/m^3: populated PCB stack
_PROP_CLEARANCE = 0.02     # m: prop-tip to prop-tip clearance
_PLATE_THICKNESS = 0.003
_ARM_WIDTH = 0.013
_ARM_THICKNESS = 0.005

#: per-part colors: muted categorical set at roughly constant lightness
COLORS = {
    "frame": "#4a4e54",     # neutral dark (fuselage, booms, plates)
    "motors": "#b4674e",    # terracotta (motor cans + nacelles)
    "props": "#58939b",     # teal (drawn translucent: a spinning disk)
    "battery": "#7181b8",   # indigo
    "esc": "#a58a4d",       # ochre
    "wing": "#6f8f6a",      # sage
    "tail": "#8a8f98",      # light gray (stabilizers)
}


# ---------------------------------------------------------------------------
# primitive meshes (closed, CCW-outward winding -- three.js front faces)
# ---------------------------------------------------------------------------

# (u, v) picked so that u x v == the face normal for each box face.
_BOX_FACES = (((1, 0, 0), (0, 1, 0), (0, 0, 1)),
              ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
              ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
              ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
              ((0, 0, 1), (1, 0, 0), (0, 1, 0)),
              ((0, 0, -1), (0, 1, 0), (1, 0, 0)))


def _box(sx: float, sy: float, sz: float,
         cx: float = 0.0, cy: float = 0.0, cz: float = 0.0) -> Mesh:
    """An axis-aligned box; vertices duplicated per face (flat shading)."""

    half = (sx / 2, sy / 2, sz / 2)
    vertices: list[float] = []
    faces: list[int] = []
    for normal, u, v in _BOX_FACES:
        base = len(vertices) // 3
        for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            vertices += [
                cx + (normal[0] * half[0] + su * u[0] * half[0]
                      + sv * v[0] * half[0]),
                cy + (normal[1] * half[1] + su * u[1] * half[1]
                      + sv * v[1] * half[1]),
                cz + (normal[2] * half[2] + su * u[2] * half[2]
                      + sv * v[2] * half[2]),
            ]
        faces += [base, base + 1, base + 2, base, base + 2, base + 3]
    return vertices, faces


def _cylinder(radius: float, height: float, cx: float = 0.0, cy: float = 0.0,
              cz: float = 0.0, segments: int = 24) -> Mesh:
    """A Y-axis cylinder: smooth side ring, flat cap fans."""

    vertices: list[float] = []
    faces: list[int] = []
    ring = [(radius * cos(2 * pi * i / segments),
             radius * sin(2 * pi * i / segments)) for i in range(segments)]
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
            faces += ([center, rim + i, rim + j] if flip
                      else [center, rim + j, rim + i])
    return vertices, faces


def _rotate_y(vertices: list[float], angle: float) -> list[float]:
    """Rotate flat XYZ vertices about the +Y axis through the origin."""

    c, s = cos(angle), sin(angle)
    out = list(vertices)
    for i in range(0, len(out), 3):
        x, z = out[i], out[i + 2]
        out[i], out[i + 2] = c * x + s * z, -s * x + c * z
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
        return (c[0] + su * u[0] + sv * v[0],
                c[1] + su * u[1] + sv * v[1],
                c[2] + su * u[2] + sv * v[2])

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

    quad(b[0], b[1], b[2], b[3])              # end cap (+w)
    quad(a[3], a[2], a[1], a[0])              # start cap (-w)
    for j in range(4):
        k = (j + 1) % 4
        quad(a[j], a[k], b[k], b[j])          # side
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
    unit = [(cos(2 * pi * i / segments), sin(2 * pi * i / segments))
            for i in range(segments)]
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
            faces += ([center, rim + k, rim + j] if flip
                      else [center, rim + j, rim + k])
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


def _pack(named: list[tuple[str, Mesh, float]]) -> dict[str, Any]:
    """Round, color, and bound a list of (name, mesh, opacity) parts."""

    parts: list[dict[str, Any]] = []
    rounded_parts: list[list[float]] = []
    for name, (vertices, faces), opacity in named:
        rounded = [round(c, 5) for c in vertices]
        rounded_parts.append(rounded)
        parts.append({"name": name, "color": COLORS[name],
                      "opacity": opacity,
                      "vertices": rounded, "faces": faces})
    lo = [min(min(v[i::3]) for v in rounded_parts) for i in range(3)]
    hi = [max(max(v[i::3]) for v in rounded_parts) for i in range(3)]
    return {"unit": "m", "parts": parts,
            "bounds": [[floor(v * 1e5) / 1e5 for v in lo],
                       [ceil(v * 1e5) / 1e5 for v in hi]]}


def drone_geometry(*, prop_diameter_in: float, motor_mass: float,
                   battery_mass: float, esc_mass: float,
                   segments: int = 24) -> dict[str, Any]:
    """A to-scale quad-copter mesh dict from catalog attribute values.

    The frame is *derived*: adjacent motors sit one prop diameter plus
    ``_PROP_CLEARANCE`` apart, so a 10-inch cruiser genuinely dwarfs a
    5-inch racer.  Parts of one kind merge into a single mesh (one draw
    call each in the viewer).
    """

    prop_d = prop_diameter_in * IN
    spacing = prop_d + _PROP_CLEARANCE      # adjacent motor-to-motor
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, bat_h = battery_size(battery_mass)
    esc_t = board_thickness(esc_mass)

    plate_side = max(0.075, bat_w + 0.014, _BOARD_SIDE + 0.024)
    arm_reach = (spacing / 2) * 2**0.5      # centre -> motor axis, in XZ
    motor_y = _ARM_THICKNESS / 2 + motor_h / 2
    prop_y = _ARM_THICKNESS / 2 + motor_h + 0.002 + 0.00125

    arms, motors, props = [], [], []
    arm_length = arm_reach + motor_d / 2
    for mx, mz in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        angle = atan2(mz, mx)
        arm = _box(arm_length, _ARM_THICKNESS, _ARM_WIDTH,
                   cx=arm_length / 2)
        arms.append((_rotate_y(arm[0], -angle), arm[1]))
        x, z = mx * spacing / 2, mz * spacing / 2
        motors.append(_cylinder(motor_d / 2, motor_h, x, motor_y, z,
                                segments))
        props.append(_cylinder(prop_d / 2, 0.0025, x, prop_y, z,
                               max(segments, 32)))

    frame = _merge(_box(plate_side, _PLATE_THICKNESS, plate_side), *arms)
    battery = _box(bat_l, bat_w, bat_h,
                   cy=-(_PLATE_THICKNESS / 2 + 0.004 + bat_h / 2))
    esc = _box(_BOARD_SIDE, esc_t, _BOARD_SIDE,
               cy=_PLATE_THICKNESS / 2 + esc_t / 2)

    parts: list[tuple[str, Mesh, float]] = [
        ("frame", frame, 1.0), ("motors", _merge(*motors), 1.0),
        ("props", _merge(*props), 0.55), ("battery", battery, 1.0),
        ("esc", esc, 1.0)]
    return _pack(parts)


#: tail lift props of the winged VTOL relative to the main (catalog) props
#: -- also baked into the catalog's diskAreaFactor (2 + 2 * 0.8^2 ~ 3.3)
_TAIL_PROP_RATIO = 0.8
_WING_THICKNESS = 0.12       # thickness / chord
_FIN_HEIGHT_RATIO = 0.24     # vertical stabilizer height / boom length


def winged_vtol_geometry(*, wing_span: float, wing_chord: float,
                         taper: float, fuselage_length: float,
                         prop_diameter: float, motor_mass: float,
                         battery_mass: float,
                         segments: int = 24) -> dict[str, Any]:
    """A to-scale winged VTOL: wingtip cruise props + tail lift props.

    The wing is lofted from span/chord/taper; the two large catalog props
    ride forward-facing nacelles on the wingtips (where they turn against
    the tip vortices -- the modeled induced-drag bonus), and two smaller
    lift props (``_TAIL_PROP_RATIO`` of the catalog diameter) sit atop the
    twin vertical stabilizers.  Fuselage width follows the battery brick;
    everything else is proportioned from the wing.
    """

    if min(wing_span, wing_chord, fuselage_length, prop_diameter) <= 0:
        raise AnalysisError("winged VTOL dimensions must be positive")
    root = 2.0 * wing_chord / (1.0 + taper)
    tip = root * taper
    thick = _WING_THICKNESS * root
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, bat_h = battery_size(battery_mass)

    body_w = max(0.10, bat_w + 0.03)
    body_h = max(0.11, bat_h + 0.06)
    nose, cabin, boat = (0.22 * fuselage_length, 0.38 * fuselage_length,
                         0.40 * fuselage_length)
    x_nose = 0.30 * fuselage_length + nose  # wing sits above the CG
    fuselage = _merge(
        _loft((x_nose - nose, 0.0, 0.0), (0.0, body_h / 2, 0.0),
              (0.0, 0.0, body_w / 2),
              (x_nose, -0.1 * body_h, 0.0), (0.0, 0.3 * body_h, 0.0),
              (0.0, 0.0, 0.3 * body_w)),
        _box(cabin, body_h, body_w, cx=x_nose - nose - cabin / 2),
        _loft((x_nose - nose - cabin, 0.0, 0.0), (0.0, 0.0, body_w / 2),
              (0.0, body_h / 2, 0.0),
              (x_nose - nose - cabin - boat, 0.05 * body_h, 0.0),
              (0.0, 0.0, 0.18 * body_w), (0.0, 0.18 * body_h, 0.0)))

    wing_y = body_h / 2 + thick / 2  # shoulder wing
    half = wing_span / 2
    wing = _merge(*(
        _loft((0.0, wing_y, 0.0), (root / 2, 0.0, 0.0),
              (0.0, side * thick / 2, 0.0),
              (0.0, wing_y, side * half), (tip / 2, 0.0, 0.0),
              (0.0, side * thick / 2, 0.0))
        for side in (1.0, -1.0)))

    # twin booms from the wing back to the vertical stabilizers
    boom_len = 0.55 * fuselage_length + 0.25 * wing_chord
    boom_z = 0.30 * half
    fin_h = _FIN_HEIGHT_RATIO * boom_len
    fin_root = 0.45 * wing_chord + 0.05
    x_fin = -boom_len  # fin quarter-chord
    booms = [_box(boom_len + root / 2, 0.024, 0.024,
                  cx=-(boom_len - root / 2) / 2, cy=wing_y, cz=side * boom_z)
             for side in (1.0, -1.0)]
    fins = [_loft((x_fin, wing_y, side * boom_z),
                  (fin_root / 2, 0.0, 0.0), (0.0, 0.0, -0.010),
                  (x_fin - 0.15 * fin_root, wing_y + fin_h, side * boom_z),
                  (0.55 * fin_root / 2, 0.0, 0.0), (0.0, 0.0, -0.007))
            for side in (1.0, -1.0)]
    hstab = _box(0.55 * fin_root, 0.012, 2 * boom_z,
                 cx=x_fin - 0.15 * fin_root, cy=wing_y + fin_h)
    tail = _merge(*fins, hstab)

    # wingtip nacelles: forward-facing cruise props (the tip-vortex bonus)
    nac_r = 0.75 * motor_d
    nac_len = 3.0 * motor_h
    nacelles, props, motors = [], [], []
    for side in (1.0, -1.0):
        z = side * half
        body = _tube([(0.45 * nac_len, 0.35 * nac_r),
                      (0.15 * nac_len, nac_r),
                      (-0.55 * nac_len, nac_r),
                      (-0.65 * nac_len, 0.5 * nac_r)], segments)
        nacelles.append((_translate(body[0], 0.0, wing_y, z), body[1]))
        disk = _tube([(0.45 * nac_len + 0.006, prop_diameter / 2),
                      (0.45 * nac_len + 0.0085, prop_diameter / 2)],
                     max(segments, 32))
        props.append((_translate(disk[0], 0.0, wing_y, z), disk[1]))
    # tail lift props atop the vertical stabilizers
    tail_prop_r = _TAIL_PROP_RATIO * prop_diameter / 2
    for side in (1.0, -1.0):
        z = side * boom_z
        y = wing_y + fin_h + 0.012
        motors.append(_cylinder(motor_d / 2, motor_h,
                                x_fin - 0.15 * fin_root, y + motor_h / 2, z,
                                segments))
        props.append(_cylinder(tail_prop_r, 0.0025, x_fin - 0.15 * fin_root,
                               y + motor_h + 0.004, z, max(segments, 32)))

    battery = _box(bat_l, bat_h, bat_w,
                   cx=x_nose - nose - cabin / 2,
                   cy=-(body_h / 2 + bat_h / 2 - 0.01))

    return _pack([
        ("frame", _merge(fuselage, *booms), 1.0),
        ("wing", wing, 1.0),
        ("tail", tail, 1.0),
        ("motors", _merge(*nacelles, *motors), 1.0),
        ("props", _merge(*props), 0.55),
        ("battery", battery, 1.0),
    ])


def interceptor_geometry(*, body_length: float, wing_span: float,
                         wing_chord: float, taper: float,
                         prop_diameter: float, motor_mass: float,
                         battery_mass: float,
                         segments: int = 24) -> dict[str, Any]:
    """A to-scale streamlined interceptor: slender body, pusher prop.

    The fuselage is a lathed low-drag body just wide enough for the
    battery brick, with small swept mid-body wings, a cruciform tail,
    and the single catalog prop pushing at the stern.  The battery bay is
    drawn as an indigo sleeve around the fuselage at its true length and
    position (the brick rides inside the body).
    """

    if min(body_length, wing_span, wing_chord, prop_diameter) <= 0:
        raise AnalysisError("interceptor dimensions must be positive")
    motor_d, motor_h = motor_size(motor_mass)
    bat_l, bat_w, _bat_h = battery_size(battery_mass)
    body_r = max(0.040, bat_w / 2 + 0.012, motor_d / 2 + 0.004)
    half = body_length / 2

    fuselage = _tube([(half, 0.12 * body_r),                # nose tip
                      (half - 0.28 * body_length, body_r),  # max section
                      (-half + 0.22 * body_length, body_r),
                      (-half, 0.55 * body_r)],              # boat tail
                     segments)

    root = 2.0 * wing_chord / (1.0 + taper)
    tip = root * taper
    thick = max(0.008, _WING_THICKNESS * root * 0.7)  # thin, fast section
    wing = _merge(*(
        _loft((0.0, 0.0, 0.0), (root / 2, 0.0, 0.0),
              (0.0, side * thick / 2, 0.0),
              (-0.12 * root, 0.0, side * wing_span / 2),  # swept tips
              (tip / 2, 0.0, 0.0), (0.0, side * thick / 2, 0.0))
        for side in (1.0, -1.0)))

    fin_span = 0.34 * wing_span
    fin_root = 0.62 * wing_chord
    x_tail = -half + 0.30 * fin_root + 0.02
    fins = []
    for uy, uz in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
        fins.append(_loft(
            (x_tail, 0.0, 0.0), (fin_root / 2, 0.0, 0.0),
            (0.0, uz * 0.005, -uy * 0.005),
            (x_tail - 0.18 * fin_root, uy * fin_span / 2, uz * fin_span / 2),
            (0.55 * fin_root / 2, 0.0, 0.0),
            (0.0, uz * 0.0035, -uy * 0.0035)))
    tail = _merge(*fins)

    motor = _tube([(-half - 0.002, 0.5 * body_r),
                   (-half - 0.002 - motor_h, 0.45 * body_r)], segments)
    prop = _tube([(-half - motor_h - 0.006, prop_diameter / 2),
                  (-half - motor_h - 0.0085, prop_diameter / 2)],
                 max(segments, 32))

    x_bay = half - 0.30 * body_length - bat_l / 2
    battery = _tube([(x_bay + bat_l / 2, body_r + 0.002),
                     (x_bay - bat_l / 2, body_r + 0.002)], segments)

    return _pack([
        ("frame", fuselage, 1.0),
        ("wing", wing, 1.0),
        ("tail", tail, 1.0),
        ("motors", motor, 1.0),
        ("props", prop, 0.55),
        ("battery", battery, 1.0),
    ])


def _translate(vertices: list[float], dx: float, dy: float,
               dz: float) -> list[float]:
    out = list(vertices)
    for i in range(0, len(out), 3):
        out[i] += dx
        out[i + 1] += dy
        out[i + 2] += dz
    return out


def lineup(meshes: list[dict[str, Any]], *, gap: float = 0.25,
           labels: list[str] | None = None) -> dict[str, Any]:
    """Merge mesh dicts into one to-scale scene, side by side along X.

    Each mesh keeps its parts (names prefixed by its label so a scene can
    carry several configurations); everything sits on a shared ground
    plane (ymin aligned).  ``gap`` metres separate neighbouring bounds.
    """

    if not meshes:
        raise AnalysisError("lineup needs at least one mesh")
    if labels is not None and len(labels) != len(meshes):
        raise AnalysisError("lineup needs one label per mesh")
    widths = [m["bounds"][1][0] - m["bounds"][0][0] for m in meshes]
    total = sum(widths) + gap * (len(meshes) - 1)
    y_floor = min(m["bounds"][0][1] for m in meshes)

    parts: list[dict[str, Any]] = []
    cursor = -total / 2
    for index, mesh in enumerate(meshes):
        (x0, y0, _z0), _ = mesh["bounds"]
        dx = cursor - x0
        dy = y_floor - y0
        prefix = (labels[index] if labels is not None else str(index + 1))
        for part in mesh["parts"]:
            parts.append({
                "name": f"{prefix}:{part['name']}",
                "color": part["color"],
                "opacity": part.get("opacity", 1.0),
                "vertices": [round(c, 5) for c in _translate(
                    part["vertices"], dx, dy, 0.0)],
                "faces": list(part["faces"]),
            })
        cursor += widths[index] + gap

    lo = [min(min(p["vertices"][i::3]) for p in parts) for i in range(3)]
    hi = [max(max(p["vertices"][i::3]) for p in parts) for i in range(3)]
    return {"unit": "m", "parts": parts,
            "bounds": [[floor(v * 1e5) / 1e5 for v in lo],
                       [ceil(v * 1e5) / 1e5 for v in hi]]}


def mission_params(study: TradeStudy,
                   architecture: Architecture) -> dict[str, float]:
    """Geometry inputs from a ``UavMissions``-style mix.

    Expects variation points ``airframe`` (attributes ``wingSpan``,
    ``wingChord``, ``taper``, ``fuselageLength``, ``motorCount``),
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
                f"variation point, variant, or attribute: {err})") from err

    return {"wing_span": attr("airframe", "wingSpan"),
            "wing_chord": attr("airframe", "wingChord"),
            "taper": attr("airframe", "taper"),
            "fuselage_length": attr("airframe", "fuselageLength"),
            "motor_count": attr("airframe", "motorCount"),
            "motor_mass": attr("motors", "mass"),
            "prop_diameter": attr("props", "diameter"),
            "battery_mass": attr("battery", "mass")}


def mission_geometry(study: TradeStudy, architecture: Architecture,
                     **overrides: Any) -> dict[str, Any]:
    """Family-dispatched geometry for a ``UavMissions`` mix.

    The selected airframe's attributes pick the builder: no wing ->
    :func:`drone_geometry` (the plain quad), a single motor station ->
    :func:`interceptor_geometry`, otherwise
    :func:`winged_vtol_geometry`.
    """

    p = {**mission_params(study, architecture), **overrides}
    motor_count = p.pop("motor_count")
    if p["wing_span"] <= 0:  # rotor-borne only: the quad frame
        return drone_geometry(prop_diameter_in=p["prop_diameter"] / IN,
                              motor_mass=p["motor_mass"],
                              battery_mass=p["battery_mass"],
                              esc_mass=0.014)  # 30.5 mm stack heuristic
    if motor_count <= 1:
        return interceptor_geometry(body_length=p.pop("fuselage_length"),
                                    **p)
    return winged_vtol_geometry(**p)


def architecture_params(study: TradeStudy,
                        architecture: Architecture) -> dict[str, float]:
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
                f"variation point, variant, or attribute: {err})") from err

    return {"motor_mass": attr("motors", "mass"),
            "prop_diameter_in": attr("props", "diameterIn"),
            "battery_mass": attr("battery", "mass"),
            "esc_mass": attr("esc", "mass")}


def architecture_geometry(study: TradeStudy, architecture: Architecture,
                          **overrides: Any) -> dict[str, Any]:
    """:func:`drone_geometry` for a mix (see :func:`architecture_params`)."""

    return drone_geometry(**{**architecture_params(study, architecture),
                             **overrides})


# ---------------------------------------------------------------------------
# optional CAD bridge
# ---------------------------------------------------------------------------


def to_cadquery(*, prop_diameter_in: float, motor_mass: float,
                battery_mass: float, esc_mass: float) -> Any:
    """The same parametric assembly as cadquery solids (``cad`` extra).

    Returns a ``cadquery.Assembly`` with one named, colored child per
    part -- ready for ``assembly.export("drone.step")`` or downstream CAD.
    Kept separate from the mesh pipeline so the viewer never depends on
    the OCC kernel.
    """

    try:
        import cadquery as cq
    except ImportError as err:  # pragma: no cover - exercised without extra
        raise ImportError(
            "sysml2.analysis.geometry.to_cadquery needs cadquery; install "
            "the extra with 'pip install \"longeron[cad]\"'") from err

    def color(name: str) -> Any:
        r, g, b = (int(COLORS[name][i:i + 2], 16) / 255 for i in (1, 3, 5))
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
        arm = (cq.Workplane("XZ")
               .box(length, _ARM_WIDTH, _ARM_THICKNESS)
               .translate((length / 2, 0, 0))
               .rotate((0, 0, 0), (0, 1, 0), -angle * 180.0 / pi))
        frame = frame.union(arm)

    assembly = cq.Assembly(name="drone")
    assembly.add(frame, name="frame", color=color("frame"))
    for i, (mx, mz) in enumerate(((1, 1), (1, -1), (-1, 1), (-1, -1))):
        x, z = mx * spacing / 2, mz * spacing / 2
        motor = (cq.Workplane("XZ", origin=(x, motor_h / 2
                                            + _ARM_THICKNESS / 2, z))
                 .cylinder(motor_h, motor_d / 2, direct=(0, 1, 0)))
        prop = (cq.Workplane("XZ", origin=(x, _ARM_THICKNESS / 2 + motor_h
                                           + 0.002 + 0.00125, z))
                .cylinder(0.0025, prop_d / 2, direct=(0, 1, 0)))
        assembly.add(motor, name=f"motor{i + 1}", color=color("motors"))
        assembly.add(prop, name=f"prop{i + 1}", color=color("props"))
    battery = (cq.Workplane("XZ", origin=(0, -(_PLATE_THICKNESS / 2 + 0.004
                                               + bat_h / 2), 0))
               .box(bat_l, bat_w, bat_h))
    esc = (cq.Workplane("XZ", origin=(0, _PLATE_THICKNESS / 2 + esc_t / 2, 0))
           .box(_BOARD_SIDE, _BOARD_SIDE, esc_t))
    assembly.add(battery, name="battery", color=color("battery"))
    assembly.add(esc, name="esc", color=color("esc"))
    return assembly
