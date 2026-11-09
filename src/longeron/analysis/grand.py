"""The grand-tour dashboard: every analysis seam on one linked surface.

One :func:`grand_dashboard` call composes the house widgets over a drone
model (plus the multi-mission sizing model) into a single reactive
dashboard -- the capability finale of the tutorial series (tutorial 9).

Every pane follows one **subject**
(:class:`longeron.analysis.subject.Subject`): one mission architecture.
A subject is a mission (a key of
:data:`longeron.analysis.dashboard.DEFAULT_MISSIONS`), one variant of the
mission's ``airframe`` variation point, one variant for each other
variation point, and transient overrides.  A transient override replaces
a model value for the analysis only and never writes the model.  A
**visiting craft** is a craft that the 3D pane shows but that is not the
subject.  The panes:

* a **header** that names the subject's mission, airframe and selection,
  and says when the 3D pane shows a visiting craft;
* a **subject card** -- a mission selector, the subject's mission metric
  and verdict, and the **knobs** (:func:`longeron.analysis.knobs.
  derive_knobs`): a dropdown per variation point other than the
  airframe, and a slider per input attribute that the model bounds on
  both sides;
* a **structure diagram** pane (:func:`longeron.diagrams.structure_diagram`,
  compact toolbar on) -- the linked-selection hub;
* a **containment tree** pane (:class:`longeron.widgets.explorer.ModelTree`,
  the model explorer's tree) beside the diagram.  The containment tree
  lists every package, definition, usage and relationship by ownership;
* a **3D CAD** pane (:func:`longeron.widgets.viewer3d.mesh_viewer`),
  config-keyed through :func:`longeron.analysis.link.bind_config_view`
  (tutorial 7's seam, promoted).  It shows the subject craft, baked from
  the subject's mix (:func:`longeron.analysis.geometry.mission_geometry`)
  with the craft's declared camera.  Clicking ANY other craft in the
  diagram -- a build configuration, a fleet airframe shell, or the
  mission catalog's variant usages -- renders THAT craft, while
  selections inside the shown craft highlight per M0 individual; a
  translucent **view cone** follows the camera what-if sliders over
  the subject craft;
* a **requirements scoreboard** pane
  (:func:`longeron.analysis.scoreboard.scoreboard`, Voronoi tessellation)
  scoring the model's own requirement hierarchy, repainted live as the
  measured geometry changes;
* a **camera what-if** card -- elevation/azimuth sliders that re-run the
  CAD-native occlusion measure (:func:`longeron.analysis.geometry.
  occlusion_report`, deterministic mesh engine) on the subject craft's
  declared camera on every move;
* an **OpenMDAO sizing** strip -- the sizing part's generated ``Problem``
  (:func:`longeron.analysis.mdao.build_problem`), re-run live from a
  loiter-speed slider, with a one-click driver run that snaps the slider
  to the optimum;
* a **Z3 verdict** strip -- requirement-consistency cards
  (:func:`longeron.analysis.smt.to_smt`): the design point's SAT witness
  beside an impossible what-if's UNSAT conflict core;
* a **Cesium mission** pane (:mod:`longeron.widgets.mission3d`) flying
  the subject's geometry through the recorded execution of the shared
  ``FlightStates`` machine over the shared route, at satellite imagery
  (offline front-ends degrade to a printed note; the dashboard composes
  regardless).

WIRING MAP -- everything reacts to everything, kernel-side, through
traitlets observers (so the whole surface works headless):

* mission selector -> the subject keeps its airframe, and the airframe's
  preset for the new mission (:func:`longeron.analysis.subject.preset`)
  fills the other variation points;
* diagram or tree click on a catalog craft (a variant of the
  ``airframe`` variation point, or the definition that types one) -> the
  craft becomes the subject's airframe and its preset fills the other
  variation points, and the mission-level overrides stay;
* dropdown knob -> that variation point changes, and the others stay;
* slider knob -> a transient override that reaches
  :meth:`longeron.analysis.trades.TradeStudy.evaluate`;
* any subject change -> the subject scene re-bakes (the stale entry of
  :attr:`longeron.analysis.link.ConfigViewBinding.scenes` is replaced),
  the 3D pane shows the subject, the camera card measures the subject's
  declared camera, the Cesium pane flies the subject's mesh, and the
  header names the new subject;
* diagram click -> 3D highlight (and mesh pick -> diagram selection);
* containment tree selection -> diagram selection of the element, or of
  its nearest drawn ancestor when the diagram does not draw the element
  (the diagram selection then drives the 3D pane and the scoreboard);
  diagram selection -> containment tree selection, with the row
  revealed;
* diagram click on a build configuration (``Rotorcraft::QuadCopter`` and
  its siblings, which are not catalog airframes) -> the 3D pane shows it
  as a visiting craft, the subject does not change, and the camera
  what-if keeps measuring the subject craft;
* diagram click on a requirement -> scoreboard selection (and a
  scoreboard cell click -> diagram selection);
* camera sliders -> occlusion re-measure -> the view cone repaints, the
  obstructing parts highlight in 3D, the occlusion readout lists them,
  the scoreboard recolors, and the header score updates;
* loiter slider -> ``run_model`` -> the sizing cards repaint; the
  *maximize* button runs the optimization driver and snaps the slider.

Requires the ``viz`` extra for the widgets and the ``mdao``/``smt``
extras for the sizing and verdict strips:
``pip install "longeron[viz,mdao,smt]"``.
"""

from __future__ import annotations

import io
import json
from collections.abc import Mapping, Sequence
from contextlib import redirect_stdout
from dataclasses import replace
from math import cos, floor, log10, pi, radians, sin, tan
from typing import Any, cast

from .. import model as M
from ..interpreter import Interpreter
from ..widgets.mission3d import Imagery
from . import geometry
from ._expr import AnalysisError
from .dashboard import DEFAULT_MISSIONS, _ipywidgets
from .knobs import derive_knobs
from .subject import MissionName, Preset, Subject, craft_variant, preset
from .trades import Architecture, TradeStudy

__all__ = [
    "ATLANTA_LOOP",
    "FLIGHT_EVENTS",
    "drone_scene",
    "grand_dashboard",
    "scene_for",
    "tilt_viewer",
    "view_cone_part",
]

#: default mission route: a small loop over Piedmont Park, midtown
#: Atlanta -- ``(lat, lon, alt m MSL)``; the ground there sits ~300 m MSL
ATLANTA_LOOP: tuple[tuple[float, float, float], ...] = (
    (33.7813, -84.3833, 350.0),
    (33.7885, -84.3785, 390.0),
    (33.7900, -84.3695, 380.0),
    (33.7838, -84.3690, 360.0),
    (33.7770, -84.3825, 350.0),
)

#: default event feed for the flight state machine replay
#: (the ``Interpreter.simulate`` protocol: numbers advance the clock)
FLIGHT_EVENTS: tuple[Any, ...] = (2.0, "launch", 6.0, "airborne", 150.0, "low_battery", 10.0)

#: the 30.5 mm stack heuristic -- the demo model carries no ESC part
_ESC_MASS = 0.012

# -- layout constants (explicit heights: the composed surface must fit a
# ~1600x900 recording viewport together with the notebook chrome) --------
_ROW1_PX = 430  # tree / diagram / 3D / scoreboard
_TREE_PX = 240  # fixed containment tree pane width
_VIEWER_PX = 400  # fixed 3D pane width (canvas height = width / aspect)
_BOARD_PX = 400  # fixed scoreboard pane width
_STRIP_PX = 200  # what-if / sizing / verdict cards
_MISSION_PX = 330  # the Cesium finale

_FONT = "font-family:var(--jp-ui-font-family,Helvetica,Arial,sans-serif)"
_CARD_STYLE = (
    "border:1px solid var(--jp-border-color2,#e0e0e0); border-radius:8px; "
    "padding:8px 12px; box-sizing:border-box; height:100%; overflow:hidden; "
    f"background:var(--jp-layout-color1,#ffffff); {_FONT}; "
    "color:var(--jp-ui-font-color1,#2b2d31); font-size:12px"
)
_TITLE_STYLE = (
    "font-size:11px; font-weight:600; letter-spacing:0.06em; text-transform:uppercase; "
    "color:var(--jp-ui-font-color2,#6b7078); margin-bottom:4px"
)
_OK = "var(--jp-success-color0,#1b7d2c)"
_BAD = "var(--jp-error-color0,#b0413e)"
_DIM = "var(--jp-ui-font-color2,#6b7078)"
_NUM = "font-variant-numeric:tabular-nums"

#: chrome for the widget-backed strip cards (ipywidgets ``Layout`` has no
#: border-radius trait) -- injected once per dashboard as a zero-size
#: ``<style>`` child
_GRAND_CSS = (
    "<style>"
    ".lgn-grand-card { border: 1px solid var(--jp-border-color2,#e0e0e0); "
    "border-radius: 8px; padding: 8px 12px; box-sizing: border-box; "
    "background: var(--jp-layout-color1,#ffffff); }"
    "</style>"
)


# ---------------------------------------------------------------------------
# scene baking (interpreter-exact, widget-free)
# ---------------------------------------------------------------------------


def drone_scene(
    model: M.Model, assembly: str = "Rotorcraft::QuadCopter"
) -> tuple[dict[str, Any], dict[str, str]]:
    """Bake the tagged per-instance mesh for a drone-family assembly.

    Interprets ``assembly`` at M0 (:func:`longeron.m0.interpret`), sizes
    the parametric mesh from the population's own attribute values
    (:func:`longeron.analysis.geometry.drone_geometry`,
    ``split_instances=True``), and stamps every rendered part with its
    **M0 individual id** (tutorial 7's identity keys).  The rotor
    population picks the frame family -- the CONFIG-KEYED rendering
    seam: a ``motors`` population fans out one arm per member (the quad
    and the hexa), ``frontMotors`` + ``tailMotor`` build the three-arm
    tricopter with its tail boom, and ``upperMotors`` + ``lowerMotors``
    stack the coaxial pairs (uppers take ``motor1..4`` / the first
    propeller individuals, lowers follow).  The assembly must have the
    MultiRotor build-family shape of the DeepScout program
    (``examples/deepscout``): ``chassis``, ``battery``, and
    ``propellers`` slots, one of the rotor-population shapes above,
    plus an optional ``camera`` whose placement/boresight attributes
    drive the occlusion checks.  Pair with
    :func:`longeron.analysis.link.owning_config` to resolve a diagram
    selection anywhere inside a configuration to the configuration
    this function renders.  Returns ``(mesh, part_map)``.
    """

    from .. import m0  # heavier import; keep the module import light

    population = m0.interpret(model, assembly)
    slots = population.root.slots
    missing = [n for n in ("chassis", "battery", "propellers") if n not in slots]
    if missing:
        raise AnalysisError(
            f"{assembly} is missing the drone-assembly slot(s) {missing} "
            "(drone_scene expects the DeepScout MultiRotor build-family shape)"
        )
    coaxial = False
    if "motors" in slots:
        motors = list(slots["motors"])
        arm_count = len(motors)
    elif "frontMotors" in slots and "tailMotor" in slots:
        motors = [*slots["frontMotors"], slots["tailMotor"]]
        arm_count = len(motors)
    elif "upperMotors" in slots and "lowerMotors" in slots:
        uppers, lowers = list(slots["upperMotors"]), list(slots["lowerMotors"])
        motors = uppers + lowers
        arm_count, coaxial = len(uppers), True
    else:
        raise AnalysisError(
            f"{assembly} declares no rotor population drone_scene knows "
            "(motors, frontMotors + tailMotor, or upperMotors + lowerMotors)"
        )
    props = list(slots["propellers"])
    camera = dict(slots["camera"].slots) if "camera" in slots else None
    # the flight controller rides the model: MultiRotor declares the part
    # (the F450 kit's board), so its declared mass sizes the drawn stack --
    # absent from the model means absent from the scene (honest absence)
    fc_mass = (
        float(slots["flightController"].slots["mass"]) if "flightController" in slots else None
    )
    mesh = geometry.drone_geometry(
        prop_diameter_in=float(props[0].slots["diameter"]) / geometry.IN,
        motor_mass=float(motors[0].slots["mass"]),
        battery_mass=float(slots["battery"].slots["mass"]),
        esc_mass=_ESC_MASS,
        fc_mass=fc_mass,
        arm_count=arm_count,
        coaxial=coaxial,
        split_instances=True,
        camera=camera,
    )
    part_map = {
        "frame": slots["chassis"].id,
        "battery": slots["battery"].id,
        **({"fc": slots["flightController"].id} if fc_mass is not None else {}),
        **({"camera": slots["camera"].id} if camera is not None else {}),
        **{f"motor{i + 1}": motor.id for i, motor in enumerate(motors)},
        **{f"prop{i + 1}": prop.id for i, prop in enumerate(props)},
    }
    return geometry.tag_parts(mesh, part_map), part_map


#: nominal display propulsion for :func:`scene_for`'s fleet branch: an
#: airframe definition carries the shell's geometry knobs but selects no
#: motors, props, or pack (those are a MIX's choice -- see
#: :func:`longeron.analysis.geometry.mission_geometry`), so a def-keyed
#: render sizes its rotors and battery sleeve at the catalog's 10-inch
#: small-class figures.
_FLEET_DISPLAY: dict[str, Any] = {
    "prop_diameter": 10.0 * geometry.IN,
    "motor_mass": 0.06,
    "battery_mass": 0.45,
}

#: the DeepScout ``Airframe`` def's geometry knobs -- the attribute set
#: whose presence marks a fleet airframe shell
_AIRFRAME_KNOBS = ("wingSpan", "wingArea", "taper", "fuselageLength", "motorCount", "armCount")


def scene_for(
    model: M.Model,
    config: M.Definition | str,
    *,
    interpreter: Interpreter | None = None,
    tilt_deg: float | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Bake the tagged scene for ANY renderable craft definition.

    One dispatcher over both DeepScout craft families.  A **fleet
    airframe shell** -- a definition whose own attributes evaluate to
    the ``Airframe`` geometry knobs (``wingSpan``, ``wingArea``,
    ``taper``, ``fuselageLength``, ``motorCount``, ``armCount``) --
    renders through :func:`longeron.analysis.geometry.airframe_geometry`
    at nominal display propulsion.  Every part carries the definition's
    qualified name as its identity key (selecting the def lights the
    whole craft), EXCEPT the clickable internals: a rendered
    ``battery``, ``fc``, or ``camera`` part whose shell declares the
    matching part usage (``battery`` / ``flightController`` /
    ``camera`` -- every DeepScout fleet shell does) carries THAT
    usage's qualified name, so picking the battery in the scene
    selects the battery element, not just the craft.  A shell that
    declares a ``camera`` part also carries that camera's parameters on
    ``mesh["camera"]``, so :func:`longeron.analysis.geometry.
    occlusion_report` measures every craft family.  Anything else
    goes to :func:`drone_scene`: the MultiRotor build family bakes
    from its own M0 population with per-individual identity keys, and
    non-assembly shapes fail loudly with :class:`AnalysisError`.

    This is the config-keyed rendering seam behind
    :func:`longeron.analysis.link.bind_config_view`: resolve a
    selection to its owning configuration, hand the configuration
    here, swap the viewer to the result.  ``tilt_deg`` is the tilt-rotor
    family's conversion state (hover 90 .. cruise 0, the scene-level
    knob behind :func:`tilt_viewer`); shells that declare no pivot
    chain ignore it.  Returns ``(mesh, part_map)``.
    """

    interp = interpreter if interpreter is not None else Interpreter(model)
    definition = model.find(config) if isinstance(config, str) else config
    if not isinstance(definition, M.Definition) or not definition.qualified_name:
        raise AnalysisError(f"scene_for needs a named definition (got {config!r})")
    qname = definition.qualified_name
    knobs: dict[str, float] = {}
    for name in _AIRFRAME_KNOBS:
        try:
            knobs[name] = float(interp.evaluate(f"{qname}::{name}"))
        except Exception:
            knobs = {}  # unvalued or absent knob: not a fleet shell
            break
    if knobs:
        # the tailless S&C and pusher-installation knobs are optional:
        # only the flying wings declare them, and the zero-sweep,
        # no-crank defaults keep every other family's loft exactly as
        # it was
        extras: dict[str, Any] = {}
        for attr_name, kw in (
            ("sweepDeg", "sweep_deg"),
            ("washoutDeg", "washout_deg"),
            ("centerSectionSpan", "center_section_span"),
            ("podLength", "pod_length"),
            ("podDiameter", "pod_diameter"),
            ("podStation", "pod_station"),
            ("bayLength", "bay_length"),
            ("bayWidth", "bay_width"),
            ("bayHeight", "bay_height"),
            # the tilt-rotor family's declared pivot chain (tilt-tri only)
            ("fuselageDiameter", "fuselage_diameter"),
            ("tailArea", "tail_area"),
            ("tiltPivotSetback", "tilt_pivot_setback"),
            ("tiltArm", "tilt_arm"),
            ("noseArm", "nose_arm"),
        ):
            try:
                extras[kw] = float(interp.evaluate(f"{qname}::{attr_name}"))
            except Exception:
                pass
        for attr_name, kw in (("wingSection", "wing_section"), ("bayShape", "bay_shape")):
            try:
                extras[kw] = str(interp.evaluate(f"{qname}::{attr_name}"))
            except Exception:
                pass
        camera = _declared_camera(interp, qname)
        if camera is not None:  # drawn (and occlusion-ready, see _with_camera)
            extras["camera"] = camera
        try:  # the declared flight controller sizes the drawn board
            fc_usage = interp.resolve(f"{qname}::flightController")
            if isinstance(fc_usage, (M.Definition, M.Usage)):
                extras["fc_mass"] = float(interp.instantiate(fc_usage).slots["mass"])
        except Exception:
            pass
        if tilt_deg is not None:
            extras["tilt_deg"] = float(tilt_deg)
        shell = geometry.airframe_geometry(
            wing_span=knobs["wingSpan"],
            wing_area=knobs["wingArea"],
            taper=knobs["taper"],
            fuselage_length=knobs["fuselageLength"],
            motor_count=knobs["motorCount"],
            arm_count=int(knobs["armCount"]),
            **extras,
            **_FLEET_DISPLAY,
        )
        part_map = _shell_part_map(interp, qname, shell)
        return _with_camera(geometry.tag_parts(shell, part_map), camera), part_map
    return drone_scene(model, qname)


def _declared_camera(interp: Interpreter, qname: str) -> dict[str, float] | None:
    """The numeric slots of the ``camera`` part that ``qname`` declares, or ``None``."""

    try:
        camera_usage = interp.resolve(f"{qname}::camera")
        if isinstance(camera_usage, (M.Definition, M.Usage)):
            slots = interp.instantiate(camera_usage).slots
            return {k: float(v) for k, v in slots.items() if isinstance(v, (int, float))}
    except Exception:
        pass
    return None


def _with_camera(mesh: dict[str, Any], camera: Mapping[str, float] | None) -> dict[str, Any]:
    """``mesh`` with the declared camera's parameters on ``mesh["camera"]``.

    Only the multirotor builder stamps the parameters itself. The other
    families draw the camera body at a fixed station, so this stamp is what
    lets :func:`longeron.analysis.geometry.occlusion_report` measure every
    craft from its declared camera.
    """

    if camera is None or mesh.get("camera") is not None:
        return mesh
    return {**mesh, "camera": geometry._camera_params(camera)}


def _shell_part_map(interp: Interpreter, qname: str, shell: Mapping[str, Any]) -> dict[str, str]:
    """Identity keys for a fleet shell's parts: the craft, or a declared internal part.

    A rendered battery, FC, or camera keys to the shell's own part usage
    when the shell declares one (every DeepScout fleet shell does).
    """

    internals = {"battery": "battery", "fc": "flightController", "camera": "camera"}
    part_map = {}
    for part in shell["parts"]:
        key = qname
        usage = internals.get(part["name"])
        if usage is not None:
            try:
                interp.resolve(f"{qname}::{usage}")
                key = f"{qname}::{usage}"
            except Exception:
                pass
        part_map[part["name"]] = key
    return part_map


def view_cone_part(
    camera: Mapping[str, Any],
    *,
    length: float,
    name: str = "viewCone",
    segments: int = 48,
    color: str = "#7a5d8c",
    opacity: float = 0.25,
) -> dict[str, Any]:
    """A translucent view-cone mesh part for the 3D scene.

    Apex at the camera position, axis along the azimuth/elevation
    boresight, half-angle ``fieldOfView / 2``, reaching ``length``
    metres -- the same construction :func:`longeron.analysis.geometry.
    occlusion_report` measures, here as a *display* part (append it to a
    scene's ``parts``; never to the analysis mesh, where it would count
    as an obstruction).  ``camera`` uses the attribute names of the
    DeepScout program's ``ScoutParts::F450Kit::Camera``
    part.  Untagged, so linked selection ignores it.
    """

    if length <= 0:
        raise AnalysisError(f"view cone length must be positive (got {length!r})")
    params = geometry._camera_params(camera)
    apex = (params["x"], params["y"], params["z"])
    axis = geometry._boresight(params["azimuth"], params["elevation"])
    u, w = geometry._perpendicular(axis)
    radius = length * tan(radians(params["fieldOfView"]) / 2.0)
    centre = tuple(apex[i] + axis[i] * length for i in range(3))
    vertices: list[float] = [round(c, 5) for c in apex]
    for k in range(segments):
        t = 2.0 * pi * k / segments
        for i in range(3):
            vertices.append(round(centre[i] + radius * (cos(t) * u[i] + sin(t) * w[i]), 5))
    vertices += [round(c, 5) for c in centre]
    faces: list[int] = []
    base = 1 + segments  # the cap centre vertex
    for k in range(segments):
        j = (k + 1) % segments
        faces += [0, 1 + j, 1 + k]  # lateral surface (outward winding)
        faces += [base, 1 + k, 1 + j]  # base cap
    return {"name": name, "color": color, "opacity": opacity, "vertices": vertices, "faces": faces}


def tilt_viewer(
    model: M.Model,
    config: str = "TiltRotors::TiltTriWing",
    *,
    tilt_deg: float = 90.0,
    width_px: int = 640,
    height_px: int = 420,
) -> Any:
    """A mesh viewer with the tilt-rotor conversion affordance.

    One :func:`longeron.widgets.viewer3d.mesh_viewer` over one
    ``ipywidgets`` slider: the slider commands the conversion state,
    sweeping hover (90 deg) to cruise (0), and every move re-bakes the
    scene through :func:`scene_for` at that tilt -- the tip pods and
    the nose unit rotate about the pivots the MODEL declares, so the
    slider drives the same geometry the interference gate samples.
    The returned ``VBox`` exposes the pieces for scripting and tests:
    ``.viewer`` (the mesh viewer), ``.tilt`` (the slider), and
    ``.part_map``.  Requires the ``viz`` extra.
    """

    from ..widgets import viewer3d

    widgets = _ipywidgets()
    interp = Interpreter(model)
    mesh, part_map = scene_for(model, config, interpreter=interp, tilt_deg=tilt_deg)
    viewer = viewer3d.mesh_viewer(
        mesh,
        label=f"{config} -- tilt {tilt_deg:.0f} deg",
        width_px=width_px,
        height_px=height_px,
    )
    tilt = widgets.FloatSlider(
        value=float(tilt_deg),
        min=0.0,
        max=90.0,
        step=5.0,
        description="tilt deg",
        readout_format=".0f",
        continuous_update=True,
        style={"description_width": "62px"},
        layout=widgets.Layout(width="98%"),
    )

    def _on_tilt(_change: Any = None) -> None:
        angle = float(tilt.value)
        scene, _ = scene_for(model, config, interpreter=interp, tilt_deg=angle)
        viewer.mesh_json = json.dumps(scene)
        viewer.label = f"{config} -- tilt {angle:.0f} deg"

    tilt.observe(_on_tilt, "value")
    box = widgets.VBox([viewer, tilt])
    box.viewer = viewer
    box.tilt = tilt
    box.part_map = part_map
    return box


# ---------------------------------------------------------------------------
# card rendering (plain HTML over Lab CSS variables)
# ---------------------------------------------------------------------------


def _card(title: str, body: str) -> str:
    return f'<div style="{_CARD_STYLE}"><div style="{_TITLE_STYLE}">{title}</div>{body}</div>'


def _stat(label: str, value: str, *, color: str = "inherit") -> str:
    return (
        '<div style="display:flex; justify-content:space-between; gap:8px; margin:1px 0">'
        f'<span style="color:{_DIM}">{label}</span>'
        f'<span style="{_NUM}; color:{color}"><b>{value}</b></span></div>'
    )


def _header_html(
    subject: Subject, score: float, occluded: float | None, *, visiting: str | None
) -> str:
    """The header: the subject's mission, airframe and selection, then the scores."""

    tone = _DIM if occluded is None else (_OK if occluded <= 0.0 else _BAD)
    occluded_text = "no camera" if occluded is None else f"{occluded:.4f}"
    picks = [f"{point} {variant}" for point, variant in subject.selection.items()]
    picks += [f"{name} = {value:g}" for name, value in subject.overrides.items()]
    visit = (
        f'<span style="color:{_BAD}; font-size:11px">visiting <b>{visiting}</b>. '
        "The subject did not change.</span>"
        if visiting is not None
        else ""
    )
    return (
        f'<div style="{_CARD_STYLE.replace("height:100%", "height:auto")} ; '
        'display:flex; align-items:baseline; gap:14px; padding:9px 14px">'
        f'<span style="font-size:14px"><b>{subject.mission}</b> &middot; '
        f"<b>{subject.airframe}</b> &mdash; the grand tour</span>"
        f'<span style="color:{_DIM}; font-size:11px">{" &middot; ".join(picks)}</span>'
        f"{visit}"
        '<span style="flex:1 1 0"></span>'
        f'<span style="{_NUM}; font-size:12px">requirements score '
        f"<b>{score * 100:.1f}%</b></span>"
        f'<span style="{_NUM}; font-size:12px; color:{tone}">occludedFraction '
        f"<b>{occluded_text}</b></span></div>"
    )


def _occlusion_html(report: Mapping[str, Any]) -> str:
    occluded = float(report["occludedFraction"])
    obstructions: Mapping[str, float] = report["obstructions"]
    rows = [
        _stat(
            "occludedFraction",
            f"{occluded:.4f}",
            color=_OK if occluded <= 0.0 else _BAD,
        )
    ]
    if obstructions:
        shown = list(obstructions.items())[:3]
        rows += [_stat(name, f"{volume * 1e6:.1f} cm&sup3;", color=_BAD) for name, volume in shown]
        if len(obstructions) > len(shown):
            rows.append(f'<div style="color:{_DIM}">+{len(obstructions) - len(shown)} more</div>')
    else:
        rows.append(f'<div style="color:{_OK}">view cone clear of the airframe</div>')
    return "".join(rows)


def _sizing_html(problem: Any, station_var: str, margin_vars: Mapping[str, str]) -> str:
    rows = [
        _stat("loiterSpeed", f"{float(problem.get_val('loiterSpeed')[0]):.1f} m/s"),
        _stat(station_var, f"{float(problem.get_val(station_var)[0]):.1f} min"),
        _stat("loiterPowerW", f"{float(problem.get_val('loiterPowerW')[0]):.1f} W"),
    ]
    for name, margin_var in margin_vars.items():
        if "::" not in name:
            continue  # local asserts (the slider bounds); requirements only
        margin = float(problem.get_val(margin_var)[0])
        rows.append(
            _stat(name.split("::")[-1], f"{margin:+.1f}", color=_OK if margin >= 0.0 else _BAD),
        )
    return "".join(rows)


def _architecture_html(architecture: Architecture, metric: str) -> str:
    """The subject's mission metric and its verdict, one line each."""

    verdict = (
        _stat("verified", "all constraints hold", color=_OK)
        if architecture.verified
        else _stat("violates", ", ".join(architecture.violations), color=_BAD)
    )
    return _stat(metric, f"{architecture.metrics[metric]:.1f}") + verdict


def _verdict_html(title: str, result: Any, detail: str) -> str:
    tone = _OK if result.status == "sat" else _BAD
    badge = f'<span style="color:{tone}; font-weight:600">{result.status.upper()}</span>'
    return (
        f'<div style="margin:2px 0 4px"><span style="color:{_DIM}">{title}</span> {badge}</div>'
        f"{detail}"
    )


# ---------------------------------------------------------------------------
# the dashboard composition
# ---------------------------------------------------------------------------


def grand_dashboard(
    model: M.Model,
    sizing: M.Model | None = None,
    *,
    mission: MissionName = "ISR",
    airframe: str | None = None,
    states: str = "DeepScout::FlightStates",
    sizer: str = "ScoutSizing::IsrPrime",
    station_requirement: str = "ScoutSizing::IsrStation",
    station_var: str = "stationMinutes",
    loiter_var: str = "loiterSpeed",
    what_if_station: float = 420.0,
    values: Mapping[str, Any] | None = None,
    waypoints: Sequence[Sequence[float]] = ATLANTA_LOOP,
    events: Sequence[Any] = FLIGHT_EVENTS,
    ground_alt: float = 300.0,
    imagery: Imagery = "satellite",
) -> Any:
    """The grand-tour dashboard (an ipywidgets ``VBox``) -- one call.

    ``model`` carries the drone program: its structure feeds the diagram
    and the containment tree, its mission definitions
    (:data:`~longeron.analysis.dashboard.DEFAULT_MISSIONS`) and their
    trade studies supply the **subject** (a
    :class:`~longeron.analysis.subject.Subject`: one mission, one airframe
    variant, one variant per other variation point, and transient
    overrides), its requirement hierarchy is the scoreboard, and its
    ``states`` machine flies the Cesium mission over ``waypoints``.
    ``mission`` names the first subject's mission, and ``airframe`` its
    airframe variant.  The default airframe is the mission's winner: the
    airframe whose preset (:func:`~longeron.analysis.subject.preset`) has
    the best mission metric.  ``sizing`` (default: ``model`` itself)
    carries the continuous side: ``sizer`` becomes the OpenMDAO problem
    behind the loiter slider, and ``station_requirement`` the Z3
    consistency cards -- the what-if card demands ``station_var >=
    what_if_station`` with ``loiter_var`` freed, an impossible floor whose
    UNSAT core names the binding constraints.  ``values`` injects extra
    measured scoreboard bindings (e.g. performance measures computed
    through the interpreter); the live occlusion and disc-overlap measures
    of the subject craft are merged on top.

    See the module docstring for the pane list and the wiring map.  The
    returned layout exposes every piece for scripting and tests:
    ``.subject`` (the current :class:`~longeron.analysis.subject.Subject`),
    ``.architecture`` (its :meth:`TradeStudy.evaluate
    <longeron.analysis.trades.TradeStudy.evaluate>` result, overrides
    applied), ``.craft`` (the qualified name of the subject's airframe
    definition), ``.studies`` (mission name -> trade study, built on first
    use), ``.mission_toggle`` (the mission selector), ``.knobs`` (knob name
    -> widget: a variation point name gives its dropdown, a slider name
    such as ``minStationMinutes`` its slider), ``.knob_set`` (the
    :class:`~longeron.analysis.knobs.KnobSet` behind them), ``.diagram``,
    ``.tree`` (the containment tree, a
    :class:`~longeron.widgets.explorer.ModelTree`), ``.viewer``,
    ``.board`` (+ ``.scoreboard``, the current
    :class:`~longeron.analysis.scoreboard.Scoreboard`),
    ``.elevation`` / ``.azimuth`` / ``.readout`` / ``.report``,
    ``.loiter`` / ``.optimize`` / ``.problem`` / ``.optimum``,
    ``.smt_sat`` / ``.smt_what_if``, ``.mission`` (the Cesium viewer) /
    ``.track``, ``.mesh`` / ``.part_map`` / ``.camera`` (the subject
    scene, its identity keys, and its declared camera, ``None`` when the
    craft declares none), ``.header``, ``.config_view`` (the
    :class:`~longeron.analysis.link.ConfigViewBinding` behind the
    config-keyed 3D pane), and ``.unlink`` (drops the diagram <-> 3D
    binding).
    """

    from ..diagrams import structure_diagram  # pulls in ipyelk
    from ..widgets import mission3d as mission3d_widget
    from ..widgets import viewer3d
    from ..widgets.explorer import (
        ModelTree,
        _diagram_node_ids,
        _nearest_drawn,
        _nearest_tree_id,
        _tree_data,
    )
    from . import link, mdao, mission3d, smt
    from .scoreboard import scoreboard

    widgets = _ipywidgets()
    sizing_model = sizing if sizing is not None else model
    base_values = dict(values or {})
    interp = Interpreter(model)

    # -- the subject: trade studies and presets, cached per mission ----------
    studies: dict[str, TradeStudy] = {}
    presets: dict[tuple[str, str], Preset] = {}

    def _study(name: str) -> TradeStudy:
        if name not in studies:
            studies[name] = TradeStudy(model, DEFAULT_MISSIONS[name][0])
        return studies[name]

    def _preset(name: MissionName, variant: str) -> Subject:
        # one preset evaluates every mix of the other points (~0.25 s for
        # ISR), so each (mission, airframe) pair is computed once
        if (name, variant) not in presets:
            presets[name, variant] = preset(_study(name), variant, DEFAULT_MISSIONS[name][1])
        return presets[name, variant].subject(name)

    def _winner(name: MissionName) -> str:
        metric = DEFAULT_MISSIONS[name][1]
        for variant in _study(name).points["airframe"].variants:
            _preset(name, variant)
        found = [p for (m, _), p in presets.items() if m == name]
        verified = [p for p in found if p.basis == "verified"]
        best = (
            max(verified, key=lambda p: p.architecture.metrics[metric])
            if verified
            else min(
                found,
                key=lambda p: (len(p.architecture.violations), -p.architecture.metrics[metric]),
            )
        )
        return best.architecture.selection["airframe"]

    def _craft_qname(study: TradeStudy, variant: str) -> str:
        usage = study._variant_usage("airframe", variant)
        typed = study.interp.resolver.resolve(usage.types[0], usage.owner or study.assembly)
        if not (isinstance(typed, M.Definition) and typed.qualified_name):
            raise AnalysisError(f"airframe variant {variant!r} is not typed by a named definition")
        return typed.qualified_name

    def _bake(subject: Subject) -> dict[str, Any]:
        """Everything the panes need for one subject (no widget writes)."""

        study = _study(subject.mission)
        architecture = study.evaluate(subject.mix(), subject.overrides)
        qname = _craft_qname(study, subject.airframe)
        camera = _declared_camera(study.interp, qname)
        raw = geometry.mission_geometry(study, architecture, camera=camera)
        part_map = _shell_part_map(study.interp, qname, raw)
        mesh = _with_camera(geometry.tag_parts(raw, part_map), camera)
        try:
            disc_overlap: float | None = geometry.disc_overlap(mesh, engine="mesh")
        except AnalysisError:  # a shell mesh carries no rotor discs: unmeasured
            disc_overlap = None
        try:
            tilt = mission3d.model_tilt(interp, qname)
        except AnalysisError:  # no cruiseTilt: the shell flies level
            tilt = 0.0
        return {
            "architecture": architecture,
            "craft": qname,
            "mesh": mesh,
            "part_map": part_map,
            "camera": None if mesh.get("camera") is None else dict(mesh["camera"]),
            "cone_length": 0.45 * geometry._bounds_diagonal(mesh),
            "disc_overlap": disc_overlap,
            "tilt": tilt,
        }

    if mission not in DEFAULT_MISSIONS:
        raise AnalysisError(f"unknown mission {mission!r} (have: {sorted(DEFAULT_MISSIONS)})")
    first = _preset(mission, airframe if airframe is not None else _winner(mission))
    baked = _bake(first)

    # -- panes ---------------------------------------------------------------
    diagram = structure_diagram(model, height=f"{_ROW1_PX}px")
    drawn = _diagram_node_ids(diagram)
    tree_nodes, tree_index = _tree_data(model)
    tree_ids = {id(element): node_id for node_id, element in tree_index.items()}
    tree = ModelTree(tree_nodes)
    viewer = viewer3d.mesh_viewer(
        baked["mesh"],
        label=f"{baked['craft']} -- the {mission} subject",
        width_px=_VIEWER_PX,
        height_px=_ROW1_PX,
    )
    board_score = scoreboard(model, values={**base_values, "occludedFraction": 0.0})
    board = board_score.widget("voronoi", width_px=_BOARD_PX, height_px=_ROW1_PX - 26, seed=42)
    board_qnames = {row.qname for row in board_score.table()}

    # -- OpenMDAO: the generated sizing problem + its optimization twin ------
    build = mdao.build_problem(sizing_model, sizer, requirements=(station_requirement,))
    build.problem.run_model()
    optimum = mdao.build_problem(
        sizing_model, sizer, setup=False, requirements=(station_requirement,)
    )
    mdao.add_optimization(
        optimum, objective=station_var, design_vars={loiter_var: (11.0, 24.0)}, maximize=True
    )
    optimum.problem.setup()

    # -- Z3: the design point's witness beside an impossible what-if ---------
    smt_sat = smt.to_smt(sizing_model, sizer, requirements=(station_requirement,)).check()
    what_if_system = smt.to_smt(
        sizing_model, sizer, requirements=(station_requirement,), free=(loiter_var,)
    )
    what_if_label = f"{station_var} &ge; {what_if_station:g} (what-if)"
    what_if_system.assertions.append(
        (what_if_label, what_if_system.variables[station_var] >= float(what_if_station))
    )
    smt_what_if = what_if_system.check()

    # -- Cesium: the state machine's recorded execution over the route -------
    # FlightStates and the route are shared by every mission (no mission
    # declares its own); the subject supplies the geometry and the tilt
    replay = mission3d.from_replay(
        interp,
        states,
        list(events),
        waypoints=waypoints,
        ground_alt=ground_alt,
        tilt_deg=baked["tilt"],
    )
    flight = mission3d_widget.mission_viewer(
        replay,
        mesh=baked["mesh"],
        label=f"{states} replay -- the subject's own geometry over {imagery} imagery",
        height_px=_MISSION_PX,
        imagery=imagery,
    )

    # -- controls -------------------------------------------------------------
    slider_kw = {
        "continuous_update": True,
        "style": {"description_width": "62px"},
        "layout": widgets.Layout(width="98%"),
    }
    camera0 = baked["camera"] or {"elevation": 0.0, "azimuth": 0.0}
    elevation = widgets.FloatSlider(
        value=camera0["elevation"],
        min=-90.0,
        max=90.0,
        step=5.0,
        description="elevation",
        readout_format=".0f",
        **slider_kw,
    )
    azimuth = widgets.FloatSlider(
        value=camera0["azimuth"],
        min=-180.0,
        max=180.0,
        step=15.0,
        description="azimuth",
        readout_format=".0f",
        **slider_kw,
    )
    loiter = widgets.FloatSlider(
        value=float(build.problem.get_val(loiter_var)[0]),
        min=11.0,
        max=24.0,
        step=0.5,
        description="loiter m/s",
        readout_format=".1f",
        **slider_kw,
    )
    optimize = widgets.Button(
        description="maximize station time",
        tooltip="run the OpenMDAO driver and snap the slider to the optimum",
        layout=widgets.Layout(width="98%"),
    )
    mission_toggle = widgets.ToggleButtons(
        options=list(DEFAULT_MISSIONS),
        value=mission,
        style={"button_width": "74px"},
        layout=widgets.Layout(width="98%"),
    )
    readout = widgets.HTML()
    sizing_card = widgets.HTML()
    subject_card = widgets.HTML()
    knob_grid = widgets.GridBox(
        layout=widgets.Layout(width="98%", grid_template_columns="1fr 1fr", grid_gap="0 6px")
    )
    knob_sliders = widgets.VBox(layout=widgets.Layout(width="100%"))
    header = widgets.HTML()

    box = widgets.VBox()
    box.report = {}
    box.scoreboard = board_score
    box.studies = studies
    box.knobs = {}
    live: dict[str, Any] = {"score": board_score.score, "occluded": None}
    sync = {"knobs": False, "camera": False}  # programmatic writes, not user moves

    def _install(subject: Subject, pieces: dict[str, Any]) -> None:
        box.subject = subject
        box.architecture = pieces["architecture"]
        box.craft = pieces["craft"]
        box.mesh = pieces["mesh"]
        box.part_map = dict(pieces["part_map"])
        box.camera = None if pieces["camera"] is None else dict(pieces["camera"])
        live["cone_length"] = pieces["cone_length"]
        live["disc_overlap"] = pieces["disc_overlap"]
        box.track = replace(replay, tilt_deg=pieces["tilt"])
        subject_card.value = _architecture_html(
            pieces["architecture"], DEFAULT_MISSIONS[subject.mission][1]
        )

    # -- wiring ---------------------------------------------------------------
    def _refresh_header() -> None:
        visiting = binding.current if binding.current != box.craft else None
        header.value = _header_html(box.subject, live["score"], live["occluded"], visiting=visiting)

    def _repaint_board(occluded: float | None) -> None:
        merged = dict(base_values)
        if occluded is not None:
            merged["occludedFraction"] = occluded
        if live["disc_overlap"] is not None:
            merged["discOverlapVolume"] = live["disc_overlap"]
        score = scoreboard(model, values=merged)
        box.scoreboard = score
        payload = json.dumps(score.payload())
        if board.nodes_json != payload:
            board.nodes_json = payload
        live["score"], live["occluded"] = score.score, occluded
        _refresh_header()

    def _camera_now() -> dict[str, float] | None:
        if box.camera is None:
            return None
        return {**box.camera, "elevation": float(elevation.value), "azimuth": float(azimuth.value)}

    def _cone_scene(base: dict[str, Any]) -> dict[str, Any]:
        camera = _camera_now()
        if camera is None:
            return base
        cone = view_cone_part(camera, length=live["cone_length"])
        return {**base, "parts": [*base["parts"], cone]}

    def _on_camera(_change: Any = None) -> None:
        if sync["camera"]:
            return
        camera = _camera_now()
        offenders: list[str] = []
        if camera is None:
            box.report = {}
            readout.value = f'<div style="color:{_DIM}">{box.craft} declares no camera</div>'
            occluded = None
        else:
            report = geometry.occlusion_report(box.mesh, camera=camera, engine="mesh")
            box.report = report
            readout.value = _occlusion_html(report)
            occluded = float(report["occludedFraction"])
            offenders = sorted(box.part_map.get(name, name) for name in report["obstructions"])
        if binding.current == box.craft:  # the pane may be showing a visiting craft
            viewer.mesh_json = json.dumps(_cone_scene(box.mesh))
            viewer.highlight_json = json.dumps(offenders)
        _repaint_board(occluded)

    def _render_knobs() -> None:
        """Rebuild the knob widgets for the subject's mission and airframe."""

        subject = box.subject
        study = _study(subject.mission)
        knob_set = derive_knobs(study.interp, study.assembly, study=study, selection=subject.mix())
        box.knob_set = knob_set
        made: dict[str, Any] = {}
        for dropdown in knob_set.dropdowns:
            widget = widgets.Dropdown(
                options=list(dropdown.variants),
                value=dropdown.selected,
                description=dropdown.point,
                style={"description_width": "56px"},
                layout=widgets.Layout(width="auto"),
            )
            widget.observe(_dropdown_observer(dropdown.point), names="value")
            made[dropdown.point] = widget
        sliders = []
        for knob in knob_set.sliders:
            widget = widgets.FloatSlider(
                value=subject.overrides.get(knob.name, knob.value),
                min=knob.low,
                max=knob.high,
                step=knob.step,
                description=knob.name.split(".")[-1],
                readout_format=f".{max(0, -floor(log10(knob.step)))}f",
                continuous_update=True,
                style={"description_width": "116px"},
                layout=widgets.Layout(width="98%"),
            )
            widget.observe(_slider_observer(knob.name), names="value")
            made[knob.name] = widget
            sliders.append(widget)
        box.knobs = made
        knob_grid.children = [made[d.point] for d in knob_set.dropdowns]
        knob_sliders.children = sliders

    def _dropdown_observer(point: str) -> Any:
        def _observe(change: Any) -> None:
            if sync["knobs"]:
                return
            subject = box.subject
            _set_subject(replace(subject, selection={**subject.selection, point: change["new"]}))

        return _observe

    def _slider_observer(name: str) -> Any:
        def _observe(change: Any) -> None:
            if sync["knobs"]:
                return
            subject = box.subject
            overrides = {**subject.overrides, name: float(change["new"])}
            _set_subject(replace(subject, overrides=overrides))

        return _observe

    def _set_subject(subject: Subject) -> None:
        """Make ``subject`` the tour's subject and repaint every pane that follows it."""

        old_subject, old_craft = box.subject, box.craft
        _install(subject, _bake(subject))
        # the bake cache holds the old subject scene under its craft name
        binding.scenes.pop(old_craft, None)
        binding.scenes[box.craft] = (box.mesh, box.part_map)
        binding.current = box.craft
        viewer.label = f"{box.craft} -- the {subject.mission} subject"
        flight.czml_json = json.dumps(box.track.to_czml(mesh=box.mesh))
        if (subject.mission, subject.airframe) != (old_subject.mission, old_subject.airframe):
            sync["knobs"] = True
            try:
                if mission_toggle.value != subject.mission:
                    mission_toggle.value = subject.mission
                _render_knobs()
            finally:
                sync["knobs"] = False
            if box.camera is not None:  # the new craft's declared camera angles
                sync["camera"] = True
                try:
                    elevation.value = box.camera["elevation"]
                    azimuth.value = box.camera["azimuth"]
                finally:
                    sync["camera"] = False
        _on_camera()

    def _on_mission(change: Any) -> None:
        if sync["knobs"]:
            return
        name = cast(MissionName, change["new"])
        # the airframe stays; its preset for the new mission fills the rest
        _set_subject(_preset(name, box.subject.airframe))

    def _on_craft(elements: list[M.Element]) -> None:
        """A catalog craft click fills the airframe; any other craft only visits."""

        if not elements:
            return
        study = _study(box.subject.mission)
        variant = craft_variant(study, elements[0])
        if variant is None:
            config = link.owning_config(model, elements[0])
            variant = craft_variant(study, config) if config is not None else None
        if variant is not None and variant != box.subject.airframe:
            subject = _preset(box.subject.mission, variant)
            plain = {k: v for k, v in box.subject.overrides.items() if "." not in k}
            _set_subject(replace(subject, overrides=plain))

    def _on_loiter(_change: Any = None) -> None:
        build.problem.set_val(loiter_var, float(loiter.value))
        build.problem.run_model()
        sizing_card.value = _sizing_html(build.problem, station_var, build.constraints)

    def _on_optimize(_button: Any = None) -> None:
        with redirect_stdout(io.StringIO()):  # the scipy driver prints its epilogue
            optimum.problem.set_val(loiter_var, float(loiter.value))
            optimum.problem.run_driver()
        loiter.value = round(float(optimum.problem.get_val(loiter_var)[0]), 2)
        _on_loiter()  # a no-op change (already-optimal slider) still repaints

    syncing = {"active": False}  # reentrancy guard: diagram <-> scoreboard

    def _on_diagram(elements: list[M.Element]) -> None:
        if syncing["active"]:
            return
        hits = [
            qname
            for element in elements
            if (qname := getattr(element, "qualified_name", None)) in board_qnames
        ]
        syncing["active"] = True
        try:
            if list(board.selected) != hits:
                board.selected = hits
        finally:
            syncing["active"] = False

    def _on_board(qnames: list[str]) -> None:
        if syncing["active"]:
            return
        ids = [qname for qname in qnames if not qname.startswith("~")]
        syncing["active"] = True
        try:
            if list(diagram.view.selection.ids) != ids:
                diagram.view.selection.ids = ids
        finally:
            syncing["active"] = False

    # tree <-> diagram has its own guard: a tree-originated diagram write
    # must still reach the scoreboard through _on_diagram
    tree_sync = {"active": False}

    def _on_tree(ids: list[str]) -> None:
        if tree_sync["active"] or not ids:
            return
        element = tree_index.get(ids[0])
        if element is None:
            return
        qname = _nearest_drawn(element, drawn)
        want = [qname] if qname is not None else []
        if list(diagram.view.selection.ids) != want:
            tree_sync["active"] = True
            try:
                diagram.view.selection.ids = want
            finally:
                tree_sync["active"] = False

    def _diagram_to_tree(elements: list[M.Element]) -> None:
        if tree_sync["active"] or not elements:
            return  # the echo of a tree selection stops here
        node_id = _nearest_tree_id(elements[0], tree_ids)
        if node_id is None or list(tree.selected) == [node_id]:
            return
        tree_sync["active"] = True
        try:
            tree.selected = [node_id]
        finally:
            tree_sync["active"] = False
        tree.reveal(node_id)

    def _scene(_model: M.Model, qname: str) -> tuple[dict[str, Any], dict[str, str]]:
        if qname == box.craft:  # the subject craft bakes with its mix
            return box.mesh, box.part_map
        return scene_for(model, qname, interpreter=interp)

    from ..diagrams import on_select

    # a craft click changes the subject BEFORE the binding resolves the
    # click, so the binding finds the new subject scene already showing
    on_select(diagram, model, _on_craft)
    _install(first, baked)
    binding = link.bind_config_view(
        diagram,
        viewer,
        model,
        showing=box.craft,
        scene=_scene,
        decorate=lambda qname, scene: _cone_scene(scene) if qname == box.craft else scene,
    )
    on_select(diagram, model, _on_diagram)
    on_select(diagram, model, _diagram_to_tree)
    on_select(diagram, model, lambda _elements: _refresh_header())  # visiting or not
    tree.on_select(_on_tree)
    board.on_select(_on_board)
    elevation.observe(_on_camera, names="value")
    azimuth.observe(_on_camera, names="value")
    loiter.observe(_on_loiter, names="value")
    optimize.on_click(_on_optimize)
    mission_toggle.observe(_on_mission, names="value")
    _render_knobs()

    # -- layout ---------------------------------------------------------------
    # Sizing discipline (the diagram-beside-3D lesson, re-learned in
    # evidence capture):
    # anywidget roots are flex items with min-width:auto, so a wrapper Box
    # does NOT constrain them -- the canvas grows toward the notebook width
    # and the visible pane clips its empty corner.  Pin width/flex on each
    # widget's OWN layout instead.
    tree.layout = widgets.Layout(width=f"{_TREE_PX}px", height=f"{_ROW1_PX}px", flex="0 0 auto")
    viewer.layout = widgets.Layout(width=f"{_VIEWER_PX}px", flex="0 0 auto")
    board.layout = widgets.Layout(width=f"{_BOARD_PX}px", flex="0 0 auto")
    diagram.layout.width = "auto"
    diagram.layout.flex = "1 1 auto"
    diagram.layout.min_width = "0"
    diagram.layout.overflow = "hidden"
    flight.layout = widgets.Layout(width="100%")
    row1 = widgets.HBox(
        [tree, diagram, viewer, board],
        layout=widgets.Layout(
            width="100%", height=f"{_ROW1_PX + 8}px", align_items="stretch", overflow="hidden"
        ),
    )

    def _strip_card(title: str, children: list[Any], *, flex: str = "1 1 0") -> Any:
        titled = widgets.HTML(f'<div style="{_TITLE_STYLE}">{title}</div>')
        card = widgets.VBox(
            [titled, *children],
            layout=widgets.Layout(
                flex=flex,
                min_width="0",
                height=f"{_STRIP_PX}px",
                overflow="hidden",
            ),
        )
        card.add_class("lgn-grand-card")
        return card

    verdicts = widgets.HTML(
        _verdict_html(
            f"{station_requirement.split('::')[-1]} at the design point",
            smt_sat,
            "".join(
                _stat(path, f"{smt_sat.witness[path]:.1f}")
                for path in (loiter_var, station_var)
                if path in smt_sat.witness
            ),
        )
        + _verdict_html(
            what_if_label,
            smt_what_if,
            "".join(
                f'<div style="color:{_BAD}; {_NUM}">&#10007; {name}</div>'
                for name in smt_what_if.core
                if not name.endswith(".value")
            )
            or f'<div style="color:{_DIM}">no conflict core</div>',
        )
    )
    row2 = widgets.HBox(
        [
            _strip_card(
                "subject (mission, knobs)",
                [mission_toggle, subject_card, knob_grid, knob_sliders],
                flex="1.6 1 0",
            ),
            _strip_card("camera what-if (occlusion, mesh engine)", [elevation, azimuth, readout]),
            _strip_card(
                f"OpenMDAO sizing -- {sizer.split('::')[-1]}", [loiter, sizing_card, optimize]
            ),
            _strip_card("Z3 requirement consistency", [verdicts]),
        ],
        layout=widgets.Layout(width="100%", align_items="stretch", overflow="hidden"),
    )

    box.children = [
        widgets.HTML(_GRAND_CSS, layout=widgets.Layout(display="none")),
        header,
        row1,
        row2,
        flight,
    ]
    box.layout = widgets.Layout(width="100%")

    # -- the automation/testing surface ---------------------------------------
    box.diagram = diagram
    box.tree = tree
    box.viewer = viewer
    box.board = board
    box.mission = flight
    box.mission_toggle = mission_toggle
    box.subject_card = subject_card
    box.header = header
    box.readout = readout
    box.sizing_card = sizing_card
    box.verdicts = verdicts
    box.elevation = elevation
    box.azimuth = azimuth
    box.loiter = loiter
    box.optimize = optimize
    box.problem = build
    box.optimum = optimum
    box.smt_sat = smt_sat
    box.smt_what_if = smt_what_if
    box.values = base_values
    box.config_view = binding
    box.unlink = binding.unbind

    _on_camera()
    _on_loiter()
    return box
