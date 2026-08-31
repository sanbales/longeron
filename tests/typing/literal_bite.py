"""Typecheck fixtures proving the public Literal vocabularies bite.

This file is CHECKED BY MYPY and never executed or imported (no ``test_``
prefix, so pytest does not collect it; the calls live in function bodies
nothing calls).  It is listed in ``[tool.mypy] files`` alongside
``src/longeron``.

The mechanism: every deliberately-wrong call below carries a
``# type: ignore[arg-type]`` (or ``[dict-item]``).  Because the project
sets ``warn_unused_ignores = true``, each comment is load-bearing in BOTH
directions:

* if the signature really rejects the wrong literal, the ignore is used
  and mypy stays quiet;
* if a signature ever loosens back to ``str``, the wrong literal becomes
  legal, the ignore turns UNUSED, and mypy fails the build.

So this file fails typecheck exactly when a vocabulary constraint stops
biting.  The correct-literal twin calls (no ignore) prove the vocabulary
admits its legal members; ``assert_type`` pins the Literal-typed returns.
"""

from __future__ import annotations

from typing import assert_type

import longeron.model as M
from longeron import diagrams, evidence, export, m0, views
from longeron.analysis import geometry, mdao, scoreboard, smt, surfaces, verify, viz
from longeron.analysis.mission3d import MissionTrack
from longeron.analysis.trades import Architecture
from longeron.client import Client
from longeron.diagrams import NodeLevel
from longeron.interpreter import Interpreter
from longeron.parser import parse_file
from longeron.widgets import app as widgets_app
from longeron.widgets import explorer as widgets_explorer
from longeron.widgets import mission3d as widgets_mission3d
from longeron.widgets import replay as widgets_replay


def structure_diagram_vocabularies(model: M.Model) -> None:
    diagrams.structure_diagram(model, parts="rows")
    diagrams.structure_diagram(model, parts="flat")  # type: ignore[arg-type]
    diagrams.structure_diagram(model, membership="edges")
    diagrams.structure_diagram(model, membership="loose")  # type: ignore[arg-type]
    diagrams.structure_diagram(model, composition="none")
    diagrams.structure_diagram(model, composition="all")  # type: ignore[arg-type]
    diagrams.structure_diagram(model, actor_style="box")
    diagrams.structure_diagram(model, actor_style="stick")  # type: ignore[arg-type]
    diagrams.structure_diagram(model, levels={"Pkg::part": "partial"})
    diagrams.structure_diagram(model, levels={"Pkg::part": "hidden"})  # type: ignore[dict-item]
    diagrams.structure_diagram(model, folded={"Pkg::part": ("attributes", "parts")})
    diagrams.structure_diagram(model, folded={"Pkg::part": ("junk drawer",)})  # type: ignore[dict-item]
    diagrams.structure_diagram(model, routing="splines", direction="down")
    diagrams.structure_diagram(model, routing="bezier")  # type: ignore[arg-type]
    diagrams.structure_diagram(model, direction="up")  # type: ignore[arg-type]


def diagram_view_family(machine: M.Definition) -> None:
    diagrams.state_diagram(machine, routing="polyline", direction="down")
    diagrams.state_diagram(machine, routing="manhattan")  # type: ignore[arg-type]
    diagrams.action_diagram(machine, direction="down")
    diagrams.action_diagram(machine, direction="left")  # type: ignore[arg-type]


def collapse_api(widget: object, element: M.Element) -> None:
    assert_type(diagrams.level(widget, element), NodeLevel)
    diagrams.level(widget, element, to="collapsed")
    diagrams.level(widget, element, to="folded")  # type: ignore[arg-type]
    diagrams.fold(widget, element, "require constraints")
    diagrams.fold(widget, element, "requires")  # type: ignore[arg-type]


def geometry_engines(mesh: dict[str, object]) -> None:
    geometry.occlusion_report(mesh, engine="mesh")
    geometry.occlusion_report(mesh, engine="occt")  # type: ignore[arg-type]
    geometry.camera_occlusion(mesh, engine="cad")
    geometry.camera_occlusion(mesh, engine="exact")  # type: ignore[arg-type]
    geometry.overlap_report(mesh, engine="auto")
    geometry.overlap_report(mesh, engine="fast")  # type: ignore[arg-type]
    geometry.disc_overlap(mesh, engine="sampled")  # type: ignore[arg-type]
    geometry.geometry_checks(mesh, engine="best")  # type: ignore[arg-type]


def scoreboard_vocabularies(model: M.Model) -> None:
    board = scoreboard.scoreboard(model, aggregation="geometric", value_format="float")
    scoreboard.scoreboard(model, aggregation="mean")  # type: ignore[arg-type]
    scoreboard.scoreboard(model, value_format="ratio")  # type: ignore[arg-type]
    scoreboard.scoreboard(model, utilities={"Range": "larger-is-better"})
    scoreboard.scoreboard(model, utilities={"Range": "bigger-is-better"})  # type: ignore[dict-item]
    board.widget(tessellation="voronoi")
    board.widget(tessellation="hexagons")  # type: ignore[arg-type]
    board.widget(value_format="percent")
    board.widget(value_format="fraction")  # type: ignore[arg-type]


def viewer_vocabularies(track: MissionTrack) -> None:
    widgets_mission3d.mission_viewer(track, imagery="osm")
    widgets_mission3d.mission_viewer(track, imagery="terrain")  # type: ignore[arg-type]


def export_formats(element: M.Element) -> None:
    export.save(element, "model.sysml", fmt="kerml")
    export.save(element, "model.sysml", fmt="xmi")  # type: ignore[arg-type]
    parse_file("model.sysml", language="kerml")
    parse_file("model.sysml", language="xtext")  # type: ignore[arg-type]


def interpretation_strategies(model: M.Model, client: Client) -> None:
    m0.interpret(model, "Pkg::Drone", strategy="random")
    m0.interpret(model, "Pkg::Drone", strategy="exhaustive")  # type: ignore[arg-type]
    client.interpret("Pkg::Drone", strategy="nominal")
    client.interpret("Pkg::Drone", strategy="trace")  # type: ignore[arg-type]


def view_kinds(model: M.Model, widget: object) -> None:
    views.save_view(model, widget, kind="requirements")
    views.save_view(model, widget, kind="sequence")  # type: ignore[arg-type]


def widget_layer(model: M.Model) -> None:
    widgets_app.open(layout="inline")
    widgets_app.open(layout="dock")  # type: ignore[arg-type]
    widgets_app.ModelEntry(model=model, source="<text>", origin="text")
    widgets_app.ModelEntry(model=model, source="<text>", origin="memory")  # type: ignore[arg-type]
    widgets_explorer.explore(model, layout="lab", structure_scope="element")
    widgets_explorer.explore(model, layout="sidebar")  # type: ignore[arg-type]
    widgets_explorer.explore(model, structure_scope="model")  # type: ignore[arg-type]
    widgets_explorer.Explorer(model, structure_scope="element")
    widgets_explorer.Explorer(model, structure_scope="selection")  # type: ignore[arg-type]
    ex = widgets_explorer.Explorer(model)
    ex.kind = "requirements"
    ex.kind = "topology"  # type: ignore[assignment]


def replay_kinds(interp: Interpreter, element: M.Usage) -> None:
    widgets_replay.replay_widget(interp, element, kind="action")
    widgets_replay.replay_widget(interp, element, kind="animation")  # type: ignore[arg-type]


def mdao_fidelity(model: M.Model) -> None:
    mdao.build_problem(model, "Pkg::Sizing", fidelity={"Calc": "external"})
    mdao.build_problem(model, "Pkg::Sizing", fidelity={"Calc": "surrogate"})  # type: ignore[dict-item]


def viz_senses(archs: list[Architecture]) -> None:
    viz.pareto_figure(archs, x="cost", y="endurance", sense=("min", "max"))
    viz.pareto_figure(archs, x="cost", y="endurance", sense=("min", "up"))  # type: ignore[arg-type]


def report_states() -> None:
    verify.Report(scope="Pkg::Drone", status="proven")
    verify.Report(scope="Pkg::Drone", status="failed")  # type: ignore[arg-type]
    verify.Counterexample(source="sequences")
    verify.Counterexample(source="fuzzing")  # type: ignore[arg-type]
    verify.Proof(requirement="r", status="proven-safe")
    verify.Proof(requirement="r", status="disproven")  # type: ignore[arg-type]
    smt.SmtResult(status="unsat")
    smt.SmtResult(status="timeout")  # type: ignore[arg-type]


def panel_verdicts() -> None:
    surfaces.Panel(name="p", rendering="", builder="", verdict="inconclusive")
    surfaces.Panel(name="p", rendering="", builder="", verdict="maybe")  # type: ignore[arg-type]


def evidence_statuses(citation: evidence.Citation) -> None:
    # pre-existing Literal (evidence.Status): bites before and after this pass
    evidence.Verdict(citation, "drifted")
    evidence.Verdict(citation, "stale")  # type: ignore[arg-type]
