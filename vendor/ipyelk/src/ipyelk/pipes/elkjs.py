# Copyright (c) 2024 ipyelk contributors.
# Distributed under the terms of the Modified BSD License.
import traitlets as T
from ipywidgets.widgets.trait_types import TypedTuple

from ..constants import EXTENSION_NAME, EXTENSION_SPEC_VERSION
from . import flows as F
from .base import SyncedPipe
from .util import browser_roundtrip


class ElkJS(SyncedPipe):
    """Jupyterlab widget for calling `elkjs <https://github.com/kieler/elkjs>`_
    layout given a valid elkjson dictionary
    """

    _model_name = T.Unicode("ELKLayoutModel").tag(sync=True)
    _model_module = T.Unicode(EXTENSION_NAME).tag(sync=True)
    _model_module_version = T.Unicode(EXTENSION_SPEC_VERSION).tag(sync=True)
    _view_module = T.Unicode(EXTENSION_NAME).tag(sync=True)

    #: seconds to wait for the browser before giving up; 0 waits forever
    #: (requests are re-sent with backoff until a view answers)
    timeout = T.Float(default_value=0.0)

    observes = TypedTuple(T.Unicode(), default_value=(F.Anythinglayout,))
    reports = TypedTuple(T.Unicode(), default_value=(F.Layout,))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.on_msg(self._handle_browser_msg)

    def _handle_browser_msg(self, widget, content, buffers):
        """Reject the pending layout future if the browser reports an error."""
        if isinstance(content, dict) and content.get("action") == "error":
            future = getattr(self, "_roundtrip_future", None)
            if future is not None and not future.done():
                future.set_exception(
                    RuntimeError(content.get("error", "browser layout failed"))
                )

    async def run(self):
        # watch once
        if self.outlet is None:
            return

        # signal to browser (resending until a view answers -- LOCAL PATCH,
        # see util.browser_roundtrip) and wait for done / error / deadline
        await browser_roundtrip(self, timeout=self.timeout or None)
        self.outlet.persist()
