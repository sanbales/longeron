# Copyright (c) 2024 ipyelk contributors.
# Distributed under the terms of the Modified BSD License.

from typing import Tuple

import ipywidgets as W
import traitlets as T
from ipywidgets.widgets.trait_types import TypedTuple

from time import monotonic

from ..pipes import MarkElementWidget
from ..tools import CenterTool, ControlOverlay, FitTool, Hover, Pan, Selection, Zoom


class Viewer(W.Widget):
    """Generic Viewer of ELK Json diagrams. Currently only mainly used by :py:class:`~ipyelk.diagram.SprottyViewer`

    Attributes
    ----------
    :parameter source: :py:class:`~ipyelk.pipes.MarkElementWidget`
        input source for rendering.
    :parameter selection: :py:class:`~ipyelk.tools.Selection`
        maintains selected ids and methods to resolve the python elements.
    :parameter hover: :py:class:`~ipyelk.tools.Hover`
        maintains hovered ids.
    :parameter zoom: :py:class:`~ipyelk.tools.Zoom`
    :parameter pan: :py:class:`~ipyelk.tools.Pan`
    :parameter control_overlay: :py:class:`~ipyelk.tools.ControlOverlay`
        additional jupyterlab widgets that can be rendered on top of the diagram
        based on the current selected states.

    """

    source: MarkElementWidget = T.Instance(MarkElementWidget, allow_none=True).tag(
        sync=True, **W.widget_serialization
    )

    selection: Selection = T.Instance(Selection, kw={}).tag(
        sync=True, **W.widget_serialization
    )
    hover: Hover = T.Instance(Hover, kw={}).tag(sync=True, **W.widget_serialization)
    zoom = T.Instance(Zoom, kw={}).tag(sync=True, **W.widget_serialization)
    pan = T.Instance(Pan, kw={}).tag(sync=True, **W.widget_serialization)
    control_overlay: ControlOverlay = T.Instance(ControlOverlay, kw={}).tag(
        sync=True, **W.widget_serialization
    )

    viewed: Tuple[str] = TypedTuple(trait=T.Unicode()).tag(
        sync=True
    )  # list element ids in the current view bounding box
    fit_tool: FitTool = T.Instance(FitTool)
    center_tool: CenterTool = T.Instance(CenterTool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_msg(self._handle_browser_msg)

    #: throttle for stale-state re-syncs, mirroring SyncedPipe: the gap
    #: doubles 2s..30s so re-syncs (the source value can be large) cannot
    #: flood a congested iopub relay whose queued backlog is the very
    #: reason the browser still looks stale
    _stale_resync_at: float = 0.0
    _stale_resync_interval: float = 0.0

    def _handle_browser_msg(self, widget, content, buffers):
        """Re-sync a frontend view that reports unrenderable state.

        LOCAL PATCH (sysml2-experiments): the viewer's ``source`` starts
        ``None`` at comm-open and is rewired to the pipe outlet by a later
        state update -- one message jupyter-server's iopub rate limiter
        may silently DROP under bursty load (a run-all creating two dozen
        diagrams on a slow CI runner).  The frontend then watches an
        empty/stale source forever: a blank diagram with no error.  The
        frontend now reports ``action: stale`` while it has nothing to
        render (see ``ELKViewerView.scheduleStaleCheck``); re-emitting
        the viewer's state (and the source's, which also carries the
        laid-out value when the kernel has one) heals the divergence.
        """
        if isinstance(content, dict) and content.get("action") == "stale":
            now = monotonic()
            if now - self._stale_resync_at < self._stale_resync_interval:
                return  # a re-sync is already in flight; let it land
            self._stale_resync_at = now
            self._stale_resync_interval = min(
                max(2.0, self._stale_resync_interval * 2), 30.0
            )
            self.log.warning(
                "Browser reports stale state for %s (missing: %s); re-syncing",
                type(self).__name__,
                content.get("missing"),
            )
            self.send_state()
            if self.source is not None:
                self.source.send_state()

    @T.default("fit_tool")
    def _default_fit_tool(self) -> FitTool:
        return FitTool(handler=lambda _: self.fit())

    @T.default("center_tool")
    def _default_center_tool(self) -> CenterTool:
        return CenterTool(handler=lambda _: self.center())

    def fit(self):
        pass

    def center(self):
        pass
