"""The widget layer: longeron's interactive front-ends, in one place.

This package has three jobs.  It is the shared toolkit for widget
authors (the anywidget conventions the house front-ends follow: baked
JSON traitlets, kernel-side computation, on-demand rendering).  It is
the mandatory home for every new widget.  And it is the catalog of the
house widgets: every canonical entry point, re-exported under one roof,
so ``longeron.widgets`` is the one import to learn.

The catalog is lazy (PEP 562).  ``import longeron.widgets`` loads no
widget toolkit; each entry imports its home module on first attribute
access.  If an entry's extra is missing, the access (or the call, for
homes that guard at call time) raises
:class:`~longeron.errors.MissingExtraError` with the exact install
command.

The entries (tutorial numbers refer to :doc:`/tutorials/index`):

* ``explore`` -- the model explorer: a tree navigator beside a diagram
  pane (tutorial 3).
* ``Explorer`` -- the explorer widget class that ``explore`` builds
  (tutorial 3).
* ``ModelTree`` -- the explorer's tree engine: disclosure rows, kind
  badges, live filter (tutorial 3).
* ``ModelApp`` -- the review workbench class that ``open`` builds
  (tutorial 3).
* ``open`` -- the review workbench: model list, explorer tabs, item
  inspector (tutorial 3).
* ``Inspector`` -- the property sheet; ``open`` builds one as
  ``app.inspector`` (tutorial 3).
* ``diagram`` -- the diagram dispatcher: picks the view from the
  element's kind (tutorial 3).
* ``structure_diagram`` -- parts, ports, and connections as an
  interactive ELK diagram (tutorial 4).
* ``state_diagram`` -- a state machine as an interactive ELK diagram
  (tutorial 2).
* ``action_diagram`` -- an action's control flow as an interactive ELK
  diagram (tutorial 3 reaches it through ``diagram``).
* ``replay_widget`` -- simulate an element and replay the run over its
  diagram (the :doc:`replay reference </reference/replay>`).
* ``scoreboard`` -- the MAUT requirements scoreboard: area is
  importance, color is utility (tutorial 6).
* ``mission_dashboard`` -- the linked mission-compromise dashboard
  (tutorial 4).
* ``grand_dashboard`` -- the grand tour: diagram, CAD, scoreboard,
  sizing, consistency, and the mission globe on one surface
  (tutorial 9).
* ``mesh_viewer`` -- baked geometry meshes in a three.js canvas, at
  true scale (tutorial 4).
* ``mission_viewer`` -- fly a mission track on a Cesium globe
  (tutorial 7).
* ``graph_viewer`` -- the RDF projection as an interactive 3D force
  graph (tutorial 8).

Current resident module:

* :mod:`longeron.widgets.graph3d` -- the 3D graph widget's home
  (``rdf`` + ``viz`` extras).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - static re-exports for type checkers
    from ..analysis.dashboard import mission_dashboard as mission_dashboard
    from ..analysis.grand import grand_dashboard as grand_dashboard
    from ..analysis.mission3d import mission_viewer as mission_viewer
    from ..analysis.scoreboard import scoreboard as scoreboard
    from ..analysis.viewer3d import mesh_viewer as mesh_viewer
    from ..app import ModelApp as ModelApp
    from ..app import open as open
    from ..diagrams import action_diagram as action_diagram
    from ..diagrams import diagram as diagram
    from ..diagrams import state_diagram as state_diagram
    from ..diagrams import structure_diagram as structure_diagram
    from ..explorer import Explorer as Explorer
    from ..explorer import ModelTree as ModelTree
    from ..explorer import explore as explore
    from ..inspector import Inspector as Inspector
    from ..replay import replay_widget as replay_widget
    from . import graph3d as graph3d
    from .graph3d import graph_viewer as graph_viewer

#: catalog entry -> (home module, attribute); the re-export is the home
#: object itself (identity, not a copy), imported on first access
_CATALOG: dict[str, tuple[str, str]] = {
    "explore": ("longeron.explorer", "explore"),
    "Explorer": ("longeron.explorer", "Explorer"),
    "ModelTree": ("longeron.explorer", "ModelTree"),
    "ModelApp": ("longeron.app", "ModelApp"),
    "open": ("longeron.app", "open"),
    "Inspector": ("longeron.inspector", "Inspector"),
    "diagram": ("longeron.diagrams", "diagram"),
    "structure_diagram": ("longeron.diagrams", "structure_diagram"),
    "state_diagram": ("longeron.diagrams", "state_diagram"),
    "action_diagram": ("longeron.diagrams", "action_diagram"),
    "replay_widget": ("longeron.replay", "replay_widget"),
    "scoreboard": ("longeron.analysis.scoreboard", "scoreboard"),
    "mission_dashboard": ("longeron.analysis.dashboard", "mission_dashboard"),
    "grand_dashboard": ("longeron.analysis.grand", "grand_dashboard"),
    "mesh_viewer": ("longeron.analysis.viewer3d", "mesh_viewer"),
    "mission_viewer": ("longeron.analysis.mission3d", "mission_viewer"),
    "graph_viewer": ("longeron.widgets.graph3d", "graph_viewer"),
}

__all__ = sorted([*_CATALOG, "graph3d"])


def __getattr__(name: str) -> Any:
    if name == "graph3d":
        return importlib.import_module(f"{__name__}.graph3d")
    try:
        home, attribute = _CATALOG[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(home), attribute)
    globals()[name] = value  # cache: later accesses bypass __getattr__
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
