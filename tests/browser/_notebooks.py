"""Generated scenario notebooks for the browser tier.

Each builder returns a plain nbformat-4.5 dict (stdlib only, no nbformat
dependency) that the session fixture writes into the JupyterLab root
directory.  The notebooks are deliberately tiny: one cell that builds and
displays the widget under test, plus one *checker* cell that prints a JSON
line of kernel-side state.  Tests re-run the checker cell after driving
the browser and parse its output (`LabPage.run_cell_json`), closing the
browser -> kernel round trip.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SCENARIO_NOTEBOOKS"]


def _notebook(*sources: str) -> dict[str, Any]:
    """A minimal runnable notebook: one code cell per source string."""

    return {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "id": f"cell-{index}",
                "metadata": {},
                "outputs": [],
                "source": source.strip() + "\n",
            }
            for index, source in enumerate(sources)
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (ipykernel)",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def replay_notebook() -> dict[str, Any]:
    """Scenario: a state-machine replay widget over a baked SVG."""

    return _notebook(
        '''
import longeron
from longeron import replay

model = longeron.loads("""
package Machines {
    state def TrafficLight {
        entry; then red;

        state red;
        transition first red accept go then green;

        state green;
        transition first green accept caution then yellow;

        state yellow;
        transition first yellow accept stop then red;
    }
}
""")
interp = longeron.Interpreter(model)
widget = replay.replay_widget(
    interp, "Machines::TrafficLight", ["go", "caution", "stop"], width_px=720
)
widget
''',
        """
print(widget.timeline_json)
""",
    )


def toolbar_notebook() -> dict[str, Any]:
    """Scenario: search / routing / direction on the longeron toolbar."""

    return _notebook(
        '''
import json

import longeron
from longeron import diagrams
from longeron.toolbar import DiagramSearch, DirectionTool, EdgeRoutingTool

model = longeron.loads("""
package Garage {
    part def Wheel;
    part def Engine;
    part car {
        part wheel : Wheel;
        part engine : Engine;
    }
    part spareWheel : Wheel;
}
""")
selections = []
widget = diagrams.structure_diagram(model)
diagrams.on_select(widget, model, selections.append)
widget
''',
        """
print(json.dumps({
    "selections": len(selections),
    "nonempty_selections": sum(1 for chosen in selections if chosen),
    "matches": widget.get_tool(DiagramSearch).match_count,
    "query": widget.get_tool(DiagramSearch).query,
    "routing": widget.get_tool(EdgeRoutingTool).routing,
    "direction": widget.get_tool(DirectionTool).direction,
}))
""",
    )


def label_fit_notebook() -> dict[str, Any]:
    """Scenario: compartment rows must fit their node in EVERY direction.

    The model is the maintainer repro (examples/drone.sysml, structure
    section): ``QuadCopter`` is an EXPANDED compound node -- children AND
    wide attribute-compartment rows (the ``totalMass`` expression) -- the
    exact shape that tripped elkjs's transposed compound-node sizing
    under a top-down flow (see test_browser_label_fit).  ``Hauler`` adds
    the second maintainer repro (UavMissions' ``LogisticsUav``): an
    expanded compound whose calculation row is ABSURDLY wide -- under the
    un-fixed top-down flow its H_CENTERed rows poked far left of the
    collapsed box, a glob of text over the package's top-left corner --
    and, with the default ``max_label_width`` cap, the row must draw
    END-ellipsized with the full text on its hover ``<title>``.
    """

    return _notebook(
        '''
import json

import longeron
from longeron import diagrams
from longeron.toolbar import DirectionTool

model = longeron.loads("""
package Drone {
    part def Battery {
        attribute capacity : Real = 5200.0;
        attribute mass : Real = 0.38;
    }
    part def Rotor {
        attribute maxThrust : Real = 9.0;
        attribute mass : Real = 0.06;
    }
    part def Frame {
        attribute mass : Real = 0.42;
    }
    part def QuadCopter {
        attribute payloadMass : Real = 0.2;
        attribute totalMass : Real =
            chassis.mass + battery.mass + 4.0 * 0.06 + payloadMass;
        attribute maxTakeoffMass : Real = 1.5;

        part chassis : Frame;
        part battery : Battery;
        part rotors : Rotor[4];

        assert constraint takeoffMassLimit { totalMass <= maxTakeoffMass }
        assert constraint canHover {
            4.0 * 9.0 > totalMass * 9.81
        }
    }
    part def Hauler {
        attribute outboundPowerW : Real = basePowerW
            + cargo.bayMass * dragArea * cruiseSpeed * cruiseSpeed
            / (cruiseEff * motorEff * propEff * transmissionEff)
            + battery.capacity * usableFraction - avionicsPowerW
            + hoverPowerW * hoverOpsSec / missionSec;

        part cargo : Frame;
        part battery : Battery;
    }
}
""")
widget = diagrams.structure_diagram(model)
widget
''',
        """
print(json.dumps({
    "direction": widget.get_tool(DirectionTool).direction,
}))
""",
    )


def explorer_notebook() -> dict[str, Any]:
    """Scenario: the tree <-> diagram selection round trip, inline layout.

    ``layout="inline"`` keeps the panes in the cell output (no ipylab
    docking), so the test works against a single notebook document.  The
    part names share no substrings ("axle", "hub") because Playwright's
    ``has_text`` matching is case-insensitive substring matching.  (The
    relationship rows -- ``satisfy massBudget``, ``connect axle to hub``
    -- do repeat those names, but they are declared AFTER the parts, so
    ``.first`` in document order still lands on the part rows.)  The
    ``Spin`` state def gives the kind switcher a second applicable kind
    (``state``) and is deliberately WIDE (a chain of states with verbose
    transition labels lays out well past the pane's width), so the test
    can prove a kind switch lands FITTED to the container -- the
    maintainer-reported bug rendered the state kind wider than the pane
    with a horizontal scrollbar -- and that the re-shown cached diagram
    is re-fitted on the way back.  The satisfy and the anonymous connect
    exercise the relationship tier: tree rows under their owner, the
    tree-toolbar toggle, and tree -> edge selection through the widget's
    ``_lgn_rel_edges`` seam.
    """

    return _notebook(
        '''
import json

import longeron
from longeron.explorer import explore

model = longeron.loads("""
package Rig {
    part def Chassis;
    part axle : Chassis;
    part hub {
        part bearing;
    }
    requirement massBudget;
    satisfy massBudget by axle;
    connect axle to hub;
    state def Spin {
        entry; then idle;

        state idle;
        transition first idle accept spin_up_commanded then accelerating;

        state accelerating;
        transition first accelerating accept nominal_rotation_speed_reached then turning;

        state turning;
        transition first turning accept controlled_slow_down_commanded then braking;

        state braking;
        transition first braking accept rotor_stopped then idle;
    }
}
""")
ex = explore(model, layout="inline", height="420px")
ex
''',
        """
print(json.dumps({
    "selected": list(ex.tree.selected),
    "element": ex.element.qualified_name if ex.element is not None else None,
    "element_type": type(ex.element).__name__ if ex.element is not None else None,
    "kind": ex.kind,
    "diagram_selection": list(ex.diagram.view.selection.ids),
    "rel_edges": len(getattr(ex.diagram, "_lgn_rel_edges", {})),
    "show_relationships": bool(ex.tree.show_relationships),
    "total_count": ex.tree.total_count,
    "match_count": ex.tree.match_count,
}))
""",
    )


def hbox_fit_notebook() -> dict[str, Any]:
    """Scenario: a plain inline diagram inside a narrow HBox self-fits.

    The NB10 shape (diagram beside a 3D viewer, squeezed to a fraction
    of the cell): NO explorer, NO consumer wiring -- just
    ``display(HBox([widget, filler]))``.  The widget's own fit sentinel
    (mounted by the builder, ``diagrams._finish``) must report the fresh
    view and answer container resizes, so the diagram lands FITTED to
    its box instead of cropped at sprotty's identity transform (the
    maintainer-reported bug).  The state machine is the explorer
    scenario's deliberately WIDE one: it only fits its 55% column with
    ``scale < 1``, so a fitted transform is unambiguous proof.  The
    checker prints the kernel-side sentinel counters, closing the
    browser -> kernel loop (``fresh``/``resized`` reports really
    arrived).
    """

    return _notebook(
        '''
import json

import ipywidgets as W

import longeron
from longeron import diagrams
from longeron.toolbar import AutoFitTool

model = longeron.loads("""
package Rig {
    state def Spin {
        entry; then idle;

        state idle;
        transition first idle accept spin_up_commanded then accelerating;

        state accelerating;
        transition first accelerating accept nominal_rotation_speed_reached then turning;

        state turning;
        transition first turning accept controlled_slow_down_commanded then braking;

        state braking;
        transition first braking accept rotor_stopped then idle;
    }
}
""")
widget = diagrams.state_diagram(model.find("Rig::Spin"))
widget.layout.width = "55%"
widget.layout.height = "420px"
filler = W.Box(layout=W.Layout(width="45%", height="420px"))
W.HBox([widget, filler], layout=W.Layout(align_items="stretch"))
''',
        """
tool = widget.get_tool(AutoFitTool)
print(json.dumps({
    "fresh": tool.sentinel.fresh,
    "resized": tool.sentinel.resized,
    "fit_count": tool.fit_count,
    "fit_stamp": tool.sentinel.fit_stamp,
}))
""",
    )


def layout_failure_notebook() -> dict[str, Any]:
    """Scenario: a deliberately-broken graph must fail loudly (F10).

    The poisoned ``elk.algorithm`` makes the browser-side elkjs layout
    throw.  Under the F10 semantics (vendored ipyelk patch 9) the error
    surfaces on ``pipe.status.exception`` and the progress bar fills as a
    visible warning instead of retrying forever.
    """

    return _notebook(
        """
import json

import longeron
from ipyelk.tools import PipelineProgressBar
from longeron import diagrams

model = longeron.loads("package Broken { part a; part b; }")
widget = diagrams.structure_diagram(model)
# poison the layout: elkjs has no such algorithm, so the browser-side
# layout throws; the diagram wires pipe.inlet = source, so mutating the
# source tree is enough for the poisoned option to reach the browser
widget.source.value.layoutOptions["elk.algorithm"] = "org.example.no.such.algorithm"
widget
""",
        """
bar = widget.get_tool(PipelineProgressBar).bar
print(json.dumps({
    "bar_style": bar.bar_style,
    "bar_full": bar.value == bar.max,
    "exception": str(widget.pipe.status.exception or ""),
}))
""",
    )


def explorer_dock_notebook() -> dict[str, Any]:
    """Scenario: docked-explorer lab citizenship (replace, never accumulate).

    ``layout="lab"`` docks the explorer through ipylab deterministically
    (no frontend auto-detection), under the default ``mode="tab-after"``:
    a background main-area tab that must not reshape the notebook.  The
    ``source_name`` pins the dock key (``dock-demo``), which the test
    uses to find the panel's tab and prove restart+run-all REPLACES the
    panel instead of stacking a second one.

    The second cell manufactures a genuine ORPHAN: it wipes the kernel-
    side registry (as a kernel restart would) before re-exploring, so
    the kernel cannot close the first panel -- only the browser-side
    sweeper can.  Every run-all therefore exercises the sweep, and the
    checker's ``swept >= 1`` is the proof it fired.
    """

    return _notebook(
        '''
import json

import longeron
from longeron.explorer import explore

model = longeron.loads("""
package Dock {
    part def Frame;
    part chassis : Frame;
    part motor;
}
""", source_name="dock demo")
ex = explore(model, layout="lab")
ex
''',
        """
# manufacture an orphan: forget the kernel-side handle (exactly what a
# kernel restart does), then re-explore -- the browser-side sweeper is
# the ONLY thing that can close the first panel now
from longeron import explorer as _explorer_module

_explorer_module._DOCKED_PANELS.clear()
ex = explore(model, layout="lab")
ex
""",
        """
print(json.dumps({
    "strategy": ex.layout_strategy,
    "mode": ex.dock_mode,
    "key": ex._dock_sweeper.key,
    "swept": int(ex._dock_sweeper.swept),
}))
""",
    )


def app_notebook() -> dict[str, Any]:
    """Scenario: the sidebar model app (longeron.app) + its item inspector.

    Cell 1 opens the app; cell 2 RE-opens it, so every run-all exercises
    the same-kernel replace path for BOTH panels (the tests assert
    exactly ONE left tab carries the ``longeron-app`` dock key and ONE
    right tab carries ``longeron-inspector``).  Cell 3 adds a SCOREABLE
    in-memory model (ScoutMini: requirement usages, all unmeasured) and
    a DEFS-ONLY one (a requirement def, no usages) so the tests can
    prove the Score button splits honestly -- live for ScoutMini and
    for drone.sysml (whose geometric installation requirements are
    usages), disabled with a tooltip for the defs-only model -- and
    that a launched scoreboard tab actually RENDERS its
    hatched cells (the maintainer's empty-tab finding).  The tests then
    drive the LIVE panels -- load a model, launch tabs, click a tree
    row, edit through the inspector's sheet -- and the checker cell
    reports the kernel-side truth: the entries list, the current model,
    the inspector-seam element, the inspector's own element, and the
    current model's tracker dirtiness.  Cell 3 also adds a small
    RELATIONSHIPS model (a satisfy + an anonymous connect) so the
    browser can prove the relationship rows show in an app-launched
    tree and that clicking one renders the inspector's relationship
    sheet (endpoints + declaration -- the maintainer's 'I can't inspect
    relationships' finding).
    """

    return _notebook(
        """
import json
from pathlib import Path

import longeron
from longeron import app as app_module

application = app_module.open(layout="lab")
print(type(application).__name__)
""",
        """
# re-open: the same-kernel registry must REPLACE the sidebar panel
# (the browser test counts exactly one longeron-app tab)
application = app_module.open(layout="lab")
print("reopened")
""",
        '''
# a SCOREABLE model beside the file-loaded one: ScoutMini carries real
# requirement usages (all unmeasured -- the scoreboard must still render
# hatched cells, maintainer QA), so its row's Score button is live;
# the defs-only model (a requirement DEF, no usages) keeps the honestly
# disabled Score button + tooltip under test
scored = longeron.loads(
    """
package ScoutMini {
    part sys;
    requirement mission {
        attribute weight : Real = 2.0;
        requirement coverage { attribute weight : Real = 3.0; }
        requirement endurance;
    }
}
""",
    source_name="scout mini",
)
application.add_model(scored, source="inline demo text")
defs_only = longeron.loads(
    """
package BareDefs {
    part sys;
    requirement def Envelope { require constraint { true } }
}
""",
    source_name="bare defs",
)
application.add_model(defs_only, source="defs only text")
# a RELATIONSHIPS model: satisfy + anonymous connect, for the inspector's
# relationship sheet (endpoints, declaration) and the tree's rel rows
rels = longeron.loads(
    """
package RigDemo {
    part def Chassis;
    part axle : Chassis;
    part hub;
    requirement massBudget;
    satisfy massBudget by axle;
    connect axle to hub;
}
""",
    source_name="rels demo",
)
application.add_model(rels, source="rels demo text")
print("scored + defs-only + rels models added")
''',
        """
element = application.current_element
current = next(
    (
        Path(entry.source).name
        for entry in application.entries
        if entry.model is application.current_model
    ),
    None,
)
from longeron import edit

dirty = (
    edit.track(application.current_model).dirty
    if application.current_model is not None
    else False
)
inspector_element = (
    application.inspector.element.qualified_name
    if application.inspector is not None and application.inspector.element is not None
    else None
)
print(json.dumps({
    "models": [Path(entry.source).name for entry in application.entries],
    "origins": [entry.origin for entry in application.entries],
    "current": current,
    "explorers": len(application.explorers),
    "element": element.qualified_name if element is not None else None,
    "inspector_element": inspector_element,
    "dirty": dirty,
}))
""",
    )


#: filename -> builder; the session fixture writes these into the lab root
def dashboard_notebook() -> dict[str, Any]:
    """Scenario: the mission-compromise dashboard on one 1080p screen.

    Cell 0 bakes and displays the dashboard over the real multi-mission
    catalog (copied into the lab root by the session fixture).  Cell 1 is
    the checker: one JSON line of kernel-side dashboard state (candidate
    count, pool/front sizes, toggle state, tab titles, the top pick's
    airframe, and the linked-selection state -- selected candidate,
    traced parcoords line, live brush intervals, 3D highlight keys) that
    tests re-read after driving the browser.
    """

    return _notebook(
        """
import longeron
from longeron.analysis import dashboard

model = longeron.load("examples/uav_missions.sysml")
dash = dashboard.mission_dashboard(model)
dash
""",
        """
import json

print(
    json.dumps(
        {
            "candidates": len(dash.data["candidates"]),
            "pool": len(dash.pool),
            "front": sum(dash.front),
            "toggle": dash.pareto_toggle.value,
            "tabs": [dash.tabs.get_title(i) for i in range(len(dash.tabs.children))],
            "picks": len(dash.picks),
            "top": (
                dash.data["candidates"][dash.picks[0]]["selection"]["airframe"]
                if dash.picks
                else None
            ),
            "selected": dash.selected,
            "selected_label": (
                dash.data["candidates"][dash.selected]["label"]
                if dash.selected is not None
                else None
            ),
            "traced": dash.parcoords.traced,
            "brushes": json.loads(dash.parcoords.brushes or "{}"),
            "highlight": json.loads(dash.viewer.highlight_json or "[]"),
        }
    )
)
""",
    )


SCENARIO_NOTEBOOKS = {
    "replay_scenario.ipynb": replay_notebook,
    "toolbar_scenario.ipynb": toolbar_notebook,
    "label_fit_scenario.ipynb": label_fit_notebook,
    "explorer_scenario.ipynb": explorer_notebook,
    "explorer_dock_scenario.ipynb": explorer_dock_notebook,
    "hbox_fit_scenario.ipynb": hbox_fit_notebook,
    "layout_failure_scenario.ipynb": layout_failure_notebook,
    "app_scenario.ipynb": app_notebook,
    "dashboard_scenario.ipynb": dashboard_notebook,
}
