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

**Loss tolerance (the sync discipline every widget follows).**  Comm
messages are fire-and-forget: under load the channel drops them
(jupyter-server's iopub rate limiter, websocket reconnects mid-burst),
and trait sync only sends CHANGES, so a dropped update stays wrong
forever unless the widget's protocol heals it.  The kernel is the
source of truth; front-ends reconcile.  Three tiers, matched to the
state a widget mirrors:

* **Baked idempotent payloads** (every widget): kernel -> front-end
  state rides absolute JSON traitlets (``spec_json``, ``czml_json``,
  ``timeline_json``...), never deltas, so any later push heals any
  earlier drop.  This is the house convention already -- keep it.
* **Single-shot interaction traits** (picks, selections, splitter
  ratios, tool toggles): a drop loses one gesture and the user's retry
  is the retransmit; the kernel-side handler must therefore be
  idempotent and order-independent.  No extra machinery.
* **Live bidirectional seams** (the time seam's ``time`` / ``playing``
  / ``rate``: high-rate reports racing kernel seeks): generation
  stamps + acknowledged reports + full-state re-pushes + a
  trailing-edge verify, via :mod:`longeron.widgets._seam` (kernel
  mixin :class:`~longeron.widgets._seam.SeamHost`, front-end
  ``lgnSeam``).  A new widget with kernel-mirrored state that either
  side can write while the other is also writing MUST ride this seam
  client; see the module's docstring for the protocol and the CI
  anatomy that mandated it.

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
* ``Clock`` -- the shared playhead for one linked group of time-aware
  views (the :doc:`time-seam reference </reference/widgets/time>`).
* ``Timebase`` -- one recording, many views: a trace plus its optional
  mission binding, aligned on one axis (the time-seam reference).
* ``link_time`` -- wire time-aware views to one clock, the temporal
  ``link_selection`` (the time-seam reference).
* ``time_scrubber`` -- the standalone transport bar: play/pause, rate,
  the shared time axis (the time-seam reference).

Current resident modules:

* :mod:`longeron.widgets.app` -- the review workbench (``ModelApp``,
  ``open``) and its Lab docking (``replay`` extra).
* :mod:`longeron.widgets.explorer` -- the model explorer: tree engine,
  diagram pane, Lab docking (``replay`` extra).
* :mod:`longeron.widgets.graph3d` -- the 3D graph widget's home
  (``rdf`` + ``viz`` extras).
* :mod:`longeron.widgets.inspector` -- the item property sheet
  (``replay`` extra).
* :mod:`longeron.widgets.mission3d` -- the Cesium mission viewer
  (``viz`` extra); its track/CZML synthesis stays in
  :mod:`longeron.analysis.mission3d`.
* :mod:`longeron.widgets.replay` -- the diagram replay widget
  (``replay`` extra); the timeline recorders stay in
  :mod:`longeron.replay`.
* :mod:`longeron.widgets.time` -- the time seam's home: ``Clock``,
  ``Timebase``, ``link_time``, and the scrubber (``replay`` extra for
  the scrubber only).
* :mod:`longeron.widgets.viewer3d` -- the three.js mesh viewer
  (``viz`` extra).

The pre-0.12 homes (``longeron.explorer``, ``longeron.inspector``,
``longeron.app``, ``longeron.analysis.viewer3d``, plus
``replay_widget`` on ``longeron.replay`` and ``mission_viewer`` on
``longeron.analysis.mission3d``) remain importable as deprecated
aliases that warn once and will be removed in a future release.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - static re-exports for type checkers
    from ..analysis.dashboard import mission_dashboard as mission_dashboard
    from ..analysis.grand import grand_dashboard as grand_dashboard
    from ..analysis.scoreboard import scoreboard as scoreboard
    from ..diagrams import action_diagram as action_diagram
    from ..diagrams import diagram as diagram
    from ..diagrams import state_diagram as state_diagram
    from ..diagrams import structure_diagram as structure_diagram
    from . import app as app
    from . import explorer as explorer
    from . import graph3d as graph3d
    from . import inspector as inspector
    from . import mission3d as mission3d
    from . import replay as replay
    from . import time as time
    from . import viewer3d as viewer3d
    from .app import ModelApp as ModelApp
    from .app import open as open
    from .explorer import Explorer as Explorer
    from .explorer import ModelTree as ModelTree
    from .explorer import explore as explore
    from .graph3d import graph_viewer as graph_viewer
    from .inspector import Inspector as Inspector
    from .mission3d import mission_viewer as mission_viewer
    from .replay import replay_widget as replay_widget
    from .time import Clock as Clock
    from .time import Timebase as Timebase
    from .time import link_time as link_time
    from .time import time_scrubber as time_scrubber
    from .viewer3d import mesh_viewer as mesh_viewer

#: catalog entry -> (home module, attribute); the re-export is the home
#: object itself (identity, not a copy), imported on first access
_CATALOG: dict[str, tuple[str, str]] = {
    "explore": ("longeron.widgets.explorer", "explore"),
    "Explorer": ("longeron.widgets.explorer", "Explorer"),
    "ModelTree": ("longeron.widgets.explorer", "ModelTree"),
    "ModelApp": ("longeron.widgets.app", "ModelApp"),
    "open": ("longeron.widgets.app", "open"),
    "Inspector": ("longeron.widgets.inspector", "Inspector"),
    "diagram": ("longeron.diagrams", "diagram"),
    "structure_diagram": ("longeron.diagrams", "structure_diagram"),
    "state_diagram": ("longeron.diagrams", "state_diagram"),
    "action_diagram": ("longeron.diagrams", "action_diagram"),
    "replay_widget": ("longeron.widgets.replay", "replay_widget"),
    "scoreboard": ("longeron.analysis.scoreboard", "scoreboard"),
    "mission_dashboard": ("longeron.analysis.dashboard", "mission_dashboard"),
    "grand_dashboard": ("longeron.analysis.grand", "grand_dashboard"),
    "mesh_viewer": ("longeron.widgets.viewer3d", "mesh_viewer"),
    "mission_viewer": ("longeron.widgets.mission3d", "mission_viewer"),
    "graph_viewer": ("longeron.widgets.graph3d", "graph_viewer"),
    "Clock": ("longeron.widgets.time", "Clock"),
    "Timebase": ("longeron.widgets.time", "Timebase"),
    "link_time": ("longeron.widgets.time", "link_time"),
    "time_scrubber": ("longeron.widgets.time", "time_scrubber"),
}

#: resident submodules (widget homes living inside this package)
_RESIDENTS = ("app", "explorer", "graph3d", "inspector", "mission3d", "replay", "time", "viewer3d")

__all__ = sorted([*_CATALOG, *_RESIDENTS])


def __getattr__(name: str) -> Any:
    if name in _RESIDENTS:
        return importlib.import_module(f"{__name__}.{name}")
    try:
        home, attribute = _CATALOG[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(importlib.import_module(home), attribute)
    globals()[name] = value  # cache: later accesses bypass __getattr__
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
