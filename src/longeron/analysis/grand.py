"""The grand-tour dashboard: every analysis seam on one linked surface.

One :func:`grand_dashboard` call composes the house widgets over a drone
model (plus the multi-mission sizing model) into a single reactive
dashboard -- the capability finale of the tutorial series (notebook 15):

* a **structure diagram** pane (:func:`longeron.diagrams.structure_diagram`,
  compact toolbar on) -- the linked-selection hub;
* a **3D CAD** pane (:func:`longeron.analysis.viewer3d.mesh_viewer`) over
  the per-instance drone mesh, cross-linked with the diagram through
  :func:`longeron.analysis.link.link_selection` (tutorial 10's M1 <-> M0
  wiring), plus a translucent **view cone** that follows the camera
  what-if sliders;
* a **requirements scoreboard** pane
  (:func:`longeron.analysis.scoreboard.scoreboard`, Voronoi tessellation)
  scoring the model's own requirement hierarchy, repainted live as the
  measured geometry changes;
* a **camera what-if** card -- elevation/azimuth sliders that re-run the
  CAD-native occlusion measure (:func:`longeron.analysis.geometry.
  occlusion_report`, deterministic mesh engine) on every move;
* an **OpenMDAO sizing** strip -- the sizing part's generated ``Problem``
  (:func:`longeron.analysis.mdao.build_problem`), re-run live from a
  loiter-speed slider, with a one-click driver run that snaps the slider
  to the optimum;
* a **Z3 verdict** strip -- requirement-consistency cards
  (:func:`longeron.analysis.smt.to_smt`): the design point's SAT witness
  beside an impossible what-if's UNSAT conflict core;
* a **Cesium mission** pane (:func:`longeron.analysis.mission3d`) flying
  the drone's own geometry through its recorded state-machine execution
  over satellite imagery (offline front-ends degrade to a printed note;
  the dashboard composes regardless).

WIRING MAP -- everything reacts to everything, kernel-side, through
traitlets observers (so the whole surface works headless):

* diagram click -> 3D highlight (and mesh pick -> diagram selection);
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
from math import cos, pi, radians, sin, tan
from typing import Any

from .. import model as M
from ..interpreter import Interpreter
from . import geometry
from ._expr import AnalysisError
from .dashboard import _ipywidgets

__all__ = [
    "ATLANTA_LOOP",
    "FLIGHT_EVENTS",
    "drone_scene",
    "grand_dashboard",
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
_ROW1_PX = 430  # diagram / 3D / scoreboard
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
    model: M.Model, assembly: str = "Drone::QuadCopter"
) -> tuple[dict[str, Any], dict[str, str]]:
    """Bake the tagged per-instance mesh for a drone assembly.

    Interprets ``assembly`` at M0 (:func:`longeron.m0.interpret`), sizes
    the parametric mesh from the population's own attribute values
    (:func:`longeron.analysis.geometry.drone_geometry`,
    ``split_instances=True``), and stamps every rendered part with its
    **M0 individual id** (tutorial 10's identity keys).  The assembly
    must have the ``examples/drone.sysml`` shape: ``chassis``,
    ``battery``, ``motors``, ``propellers`` slots, plus an optional
    ``camera`` whose placement/boresight attributes drive the occlusion
    checks.  Returns ``(mesh, part_map)``.
    """

    from .. import m0  # heavier import; keep the module import light

    population = m0.interpret(model, assembly)
    slots = population.root.slots
    missing = [n for n in ("chassis", "battery", "motors", "propellers") if n not in slots]
    if missing:
        raise AnalysisError(
            f"{assembly} is missing the drone-assembly slot(s) {missing} "
            "(drone_scene expects the examples/drone.sysml shape)"
        )
    motors = list(slots["motors"])
    props = list(slots["propellers"])
    camera = dict(slots["camera"].slots) if "camera" in slots else None
    mesh = geometry.drone_geometry(
        prop_diameter_in=float(props[0].slots["diameter"]) / geometry.IN,
        motor_mass=float(motors[0].slots["mass"]),
        battery_mass=float(slots["battery"].slots["mass"]),
        esc_mass=_ESC_MASS,
        split_instances=True,
        camera=camera,
    )
    part_map = {
        "frame": slots["chassis"].id,
        "battery": slots["battery"].id,
        **({"camera": slots["camera"].id} if camera is not None else {}),
        **{f"motor{i + 1}": motor.id for i, motor in enumerate(motors)},
        **{f"prop{i + 1}": prop.id for i, prop in enumerate(props)},
    }
    return geometry.tag_parts(mesh, part_map), part_map


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
    as an obstruction).  ``camera`` uses the ``examples/drone.sysml``
    camera attribute names.  Untagged, so linked selection ignores it.
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


def _header_html(assembly: str, score: float, occluded: float) -> str:
    tone = _OK if occluded <= 0.0 else _BAD
    return (
        f'<div style="{_CARD_STYLE.replace("height:100%", "height:auto")} ; '
        'display:flex; align-items:baseline; gap:14px; padding:9px 14px">'
        f'<span style="font-size:14px"><b>{assembly}</b> &mdash; the grand tour</span>'
        f'<span style="color:{_DIM}; font-size:11px">diagram &middot; CAD &middot; occlusion '
        "&middot; scoreboard &middot; OpenMDAO &middot; Z3 &middot; Cesium</span>"
        '<span style="flex:1 1 0"></span>'
        f'<span style="{_NUM}; font-size:12px">requirements score '
        f"<b>{score * 100:.1f}%</b></span>"
        f'<span style="{_NUM}; font-size:12px; color:{tone}">occludedFraction '
        f"<b>{occluded:.4f}</b></span></div>"
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
    assembly: str = "Drone::QuadCopter",
    states: str = "Drone::FlightStates",
    sizer: str = "UavMissions::IsrPrime",
    station_requirement: str = "UavMissions::IsrStation",
    station_var: str = "stationMinutes",
    loiter_var: str = "loiterSpeed",
    what_if_station: float = 420.0,
    values: Mapping[str, Any] | None = None,
    waypoints: Sequence[Sequence[float]] = ATLANTA_LOOP,
    events: Sequence[Any] = FLIGHT_EVENTS,
    ground_alt: float = 300.0,
    imagery: str = "satellite",
) -> Any:
    """The grand-tour dashboard (an ipywidgets ``VBox``) -- one call.

    ``model`` carries the drone: its structure feeds the diagram, its
    interpreted M0 population sizes the 3D mesh, its requirement
    hierarchy is the scoreboard, and its ``states`` machine flies the
    Cesium mission over ``waypoints``.  ``sizing`` (default: ``model``
    itself) carries the continuous side: ``sizer`` becomes the OpenMDAO
    problem behind the loiter slider, and ``station_requirement`` the
    Z3 consistency cards -- the what-if card demands ``station_var >=
    what_if_station`` with ``loiter_var`` freed, an impossible floor
    whose UNSAT core names the binding constraints.  ``values`` injects
    extra measured scoreboard bindings (e.g. performance measures
    computed through the interpreter); the live occlusion and
    disc-overlap measures are merged on top.

    See the module docstring for the pane list and the wiring map.  The
    returned layout exposes every piece for scripting and tests:
    ``.diagram``, ``.viewer``, ``.board`` (+ ``.scoreboard``, the
    current :class:`~longeron.analysis.scoreboard.Scoreboard`),
    ``.elevation`` / ``.azimuth`` / ``.readout`` / ``.report``,
    ``.loiter`` / ``.optimize`` / ``.problem`` / ``.optimum``,
    ``.smt_sat`` / ``.smt_what_if``, ``.mission`` / ``.track``,
    ``.mesh`` / ``.part_map`` / ``.camera``, ``.header``, and
    ``.unlink`` (drops the diagram <-> 3D link).
    """

    from ..diagrams import structure_diagram  # pulls the vendored ipyelk
    from . import link, mdao, mission3d, smt, viewer3d
    from .scoreboard import scoreboard

    widgets = _ipywidgets()
    sizing_model = sizing if sizing is not None else model
    base_values = dict(values or {})

    # -- the scene: mesh, identity keys, camera defaults ---------------------
    mesh, part_map = drone_scene(model, assembly)
    if mesh.get("camera") is None:
        raise AnalysisError(f"{assembly} mounts no camera part; the occlusion what-if needs one")
    camera0 = geometry._camera_params(mesh["camera"])
    cone_length = 0.45 * geometry._bounds_diagonal(mesh)
    disc_overlap = geometry.disc_overlap(mesh, engine="mesh")

    # -- panes ---------------------------------------------------------------
    diagram = structure_diagram(model, height=f"{_ROW1_PX}px")
    viewer = viewer3d.mesh_viewer(
        mesh,
        label=f"{assembly} -- one M0 interpretation",
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
    # the cruise attitude comes FROM THE MODEL where it carries one (the
    # drone example's cruiseTilt calc); a model without the physics still
    # flies, props level
    interp = Interpreter(model)
    try:
        tilt_deg = mission3d.model_tilt(interp, assembly)
    except AnalysisError:
        tilt_deg = 0.0
    track = mission3d.from_replay(
        interp,
        states,
        list(events),
        waypoints=waypoints,
        ground_alt=ground_alt,
        tilt_deg=tilt_deg,
    )
    mission = mission3d.mission_viewer(
        track,
        mesh=mesh,
        label=f"{states} replay -- the drone's own geometry over {imagery} imagery",
        height_px=_MISSION_PX,
        imagery=imagery,
    )

    # -- controls -------------------------------------------------------------
    slider_kw = {
        "continuous_update": True,
        "style": {"description_width": "62px"},
        "layout": widgets.Layout(width="98%"),
    }
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
    readout = widgets.HTML()
    sizing_card = widgets.HTML()
    header = widgets.HTML()

    box = widgets.VBox()
    box.report = {}
    box.scoreboard = board_score

    # -- wiring ---------------------------------------------------------------
    def _repaint_board(occluded: float) -> None:
        merged = {
            **base_values,
            "occludedFraction": occluded,
            "discOverlapVolume": disc_overlap,
        }
        score = scoreboard(model, values=merged)
        box.scoreboard = score
        payload = json.dumps(score.payload())
        if board.nodes_json != payload:
            board.nodes_json = payload
        header.value = _header_html(assembly, score.score, occluded)

    def _on_camera(_change: Any = None) -> None:
        camera = {
            **camera0,
            "elevation": float(elevation.value),
            "azimuth": float(azimuth.value),
        }
        report = geometry.occlusion_report(mesh, camera=camera, engine="mesh")
        box.report = report
        readout.value = _occlusion_html(report)
        scene = {**mesh, "parts": [*mesh["parts"], view_cone_part(camera, length=cone_length)]}
        viewer.mesh_json = json.dumps(scene)
        offenders = sorted(part_map.get(name, name) for name in report["obstructions"])
        viewer.highlight_json = json.dumps(offenders)
        _repaint_board(float(report["occludedFraction"]))

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

    unlink = link.link_selection(diagram, viewer, model)  # mesh already tagged
    from ..diagrams import on_select

    on_select(diagram, model, _on_diagram)
    board.on_select(_on_board)
    elevation.observe(_on_camera, names="value")
    azimuth.observe(_on_camera, names="value")
    loiter.observe(_on_loiter, names="value")
    optimize.on_click(_on_optimize)

    # -- layout ---------------------------------------------------------------
    # Sizing discipline (the NB10 lesson, re-learned in evidence capture):
    # anywidget roots are flex items with min-width:auto, so a wrapper Box
    # does NOT constrain them -- the canvas grows toward the notebook width
    # and the visible pane clips its empty corner.  Pin width/flex on each
    # widget's OWN layout instead.
    viewer.layout = widgets.Layout(width=f"{_VIEWER_PX}px", flex="0 0 auto")
    board.layout = widgets.Layout(width=f"{_BOARD_PX}px", flex="0 0 auto")
    diagram.layout.width = "auto"
    diagram.layout.flex = "1 1 auto"
    diagram.layout.min_width = "0"
    diagram.layout.overflow = "hidden"
    mission.layout = widgets.Layout(width="100%")
    row1 = widgets.HBox(
        [diagram, viewer, board],
        layout=widgets.Layout(
            width="100%", height=f"{_ROW1_PX + 8}px", align_items="stretch", overflow="hidden"
        ),
    )

    def _strip_card(title: str, children: list[Any]) -> Any:
        titled = widgets.HTML(f'<div style="{_TITLE_STYLE}">{title}</div>')
        card = widgets.VBox(
            [titled, *children],
            layout=widgets.Layout(
                flex="1 1 0",
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
        mission,
    ]
    box.layout = widgets.Layout(width="100%")

    # -- the automation/testing surface ---------------------------------------
    box.diagram = diagram
    box.viewer = viewer
    box.board = board
    box.mission = mission
    box.track = track
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
    box.mesh = mesh
    box.part_map = dict(part_map)
    box.camera = dict(camera0)
    box.values = base_values
    box.unlink = unlink

    _on_camera()
    _on_loiter()
    return box
