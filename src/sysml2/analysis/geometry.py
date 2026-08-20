"""Parametric 3D geometry for architecture mixes (spike).

Builds a to-scale quad-copter from a mix's catalog attribute values with
plain triangle meshes (stdlib ``math`` only): the frame is sized from prop
diameter + tip clearance, motor cylinders from motor mass (solid-cylinder
density heuristic), prop disks from diameter, the battery box from battery
mass (LiPo density + brick proportions), and the controller board from the
standard 30.5 mm mount.  One call turns a configuration into the mesh dict
:mod:`sysml2.analysis.viewer3d` paints:

    {"unit": "m",
     "parts": [{"name", "color", "opacity",
                "vertices": [x, y, z, ...], "faces": [i, j, k, ...]}, ...],
     "bounds": [[xmin, ymin, zmin], [xmax, ymax, zmax]]}

House pattern: geometry is baked in Python once per configuration (well
under a millisecond -- no CAD kernel in the loop); the front-end never
recomputes it.  Y is up, one unit is one metre, and every dimension is a
real measurement or a documented heuristic, so two mixes render truly to
scale side by side.

:func:`to_cadquery` rebuilds the same parametric assembly as CAD solids
(STEP export, fillets) behind the ``cad`` extra -- the mesh pipeline here
deliberately does not need the ~1 GB OCC kernel.
"""

from __future__ import annotations

from math import atan2, ceil, cos, floor, pi, sin
from typing import Any

from ._expr import AnalysisError
from .trades import Architecture, TradeStudy

__all__ = ["architecture_geometry", "architecture_params", "drone_geometry",
           "to_cadquery"]

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
    "frame": "#4a4e54",     # neutral dark
    "motors": "#b4674e",    # terracotta
    "props": "#58939b",     # teal (drawn translucent: a spinning disk)
    "battery": "#7181b8",   # indigo
    "esc": "#a58a4d",       # ochre
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

    parts: list[dict[str, Any]] = []
    rounded_parts: list[list[float]] = []
    for name, (vertices, faces), opacity in (
            ("frame", frame, 1.0), ("motors", _merge(*motors), 1.0),
            ("props", _merge(*props), 0.55), ("battery", battery, 1.0),
            ("esc", esc, 1.0)):
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
