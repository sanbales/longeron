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


def explorer_notebook() -> dict[str, Any]:
    """Scenario: the tree <-> diagram selection round trip, inline layout.

    ``layout="inline"`` keeps the panes in the cell output (no ipylab
    docking), so the test works against a single notebook document.  The
    part names share no substrings ("axle", "hub") because Playwright's
    ``has_text`` matching is case-insensitive substring matching.  The
    ``Spin`` state def gives the kind switcher a second applicable kind
    (``state``) and is deliberately WIDE (a chain of states with verbose
    transition labels lays out well past the pane's width), so the test
    can prove a kind switch lands FITTED to the container -- the
    maintainer-reported bug rendered the state kind wider than the pane
    with a horizontal scrollbar -- and that the re-shown cached diagram
    is re-fitted on the way back.
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
    "kind": ex.kind,
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


#: filename -> builder; the session fixture writes these into the lab root
SCENARIO_NOTEBOOKS = {
    "replay_scenario.ipynb": replay_notebook,
    "toolbar_scenario.ipynb": toolbar_notebook,
    "explorer_scenario.ipynb": explorer_notebook,
    "explorer_dock_scenario.ipynb": explorer_dock_notebook,
    "layout_failure_scenario.ipynb": layout_failure_notebook,
}
