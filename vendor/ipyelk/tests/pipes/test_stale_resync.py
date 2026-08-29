# Copyright (c) 2024 ipyelk contributors.
# Distributed under the terms of the Modified BSD License.
"""LOCAL PATCH 12: a browser-reported ``stale`` re-syncs pipe state.

jupyter-server's iopub rate limiter silently drops comm messages under
bursty load; a dropped state update leaves the frontend pipe model unable
to serve ``run`` requests forever (it has no inlet value to measure or
lay out).  The frontend now answers such a request with ``action: stale``
and the kernel re-emits the full state of the pipe and its endpoints, so
the ongoing resend-with-backoff loop converges instead of hanging.
"""

import asyncio

import pytest

from ipyelk.elements import Node
from ipyelk.pipes import MarkElementWidget
from ipyelk.pipes.elkjs import ElkJS
from ipyelk.pipes.text_sizer import BrowserTextSizer


def _synced(cls):
    pipe = cls(timeout=5.0)
    pipe.inlet = MarkElementWidget()
    pipe.outlet = MarkElementWidget()
    return pipe


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [ElkJS, BrowserTextSizer])
async def test_stale_report_resyncs_state_and_keeps_the_roundtrip_alive(cls):
    """``action: stale`` re-sends state; the roundtrip still completes."""
    pipe = _synced(cls)

    synced = []
    for name in ("pipe", "inlet", "outlet"):
        widget = pipe if name == "pipe" else getattr(pipe, name)
        widget.send_state = lambda key=None, _name=name: synced.append(_name)

    sends = []

    def fake_send(content, *_args, **_kwargs):
        sends.append(content)
        if len(sends) == 1:
            # the frontend got the run request but its state never arrived
            pipe._stale_resync_at = 0.0  # step past the resync throttle
            pipe._handle_browser_msg(
                pipe, {"action": "stale", "missing": {"value": True}}, None
            )
        else:
            # the re-synced frontend serves the re-sent request
            pipe.outlet.value = Node()

    pipe.send = fake_send

    await asyncio.wait_for(pipe.run(), timeout=3.0)

    # the stale report re-emitted the pipe's and both endpoints' state
    # (a trailing 'outlet' may follow: run() persists the outlet on finish)
    assert synced[:3] == ["pipe", "inlet", "outlet"]
    # ... without rejecting the pending roundtrip (two run requests total)
    assert sends == [{"action": "run"}, {"action": "run"}]
    assert pipe._roundtrip_future is None


@pytest.mark.asyncio
async def test_stale_report_is_not_an_error(event_loop=None):
    """A stale report must not reject the roundtrip future."""
    pipe = _synced(ElkJS)
    pipe.send_state = lambda key=None: None
    pipe.inlet.send_state = lambda key=None: None
    pipe.outlet.send_state = lambda key=None: None

    future = asyncio.get_event_loop().create_future()
    pipe._roundtrip_future = future
    pipe._handle_browser_msg(pipe, {"action": "stale"}, None)
    assert not future.done()
    future.cancel()


def test_viewer_stale_report_resyncs_view_wiring():
    """A viewer-reported stale re-emits the viewer's and source's state."""
    from ipyelk.diagram.viewer import Viewer

    viewer = Viewer()
    synced = []
    viewer.send_state = lambda key=None: synced.append("viewer")

    # no source wired yet: only the viewer's own state is re-emitted
    viewer._handle_browser_msg(viewer, {"action": "stale", "missing": {"source": True}}, None)
    assert synced == ["viewer"]

    # an immediate repeat is throttled: the first re-sync is in flight
    viewer._handle_browser_msg(viewer, {"action": "stale", "missing": {"source": True}}, None)
    assert synced == ["viewer"]

    viewer.source = MarkElementWidget()
    viewer.source.send_state = lambda key=None: synced.append("source")
    synced.clear()  # the assignment itself syncs the changed trait
    viewer._stale_resync_at = 0.0  # step past the throttle window
    viewer._handle_browser_msg(viewer, {"action": "stale", "missing": {"value": True}}, None)
    assert synced == ["viewer", "source"]

    # non-stale messages are ignored
    viewer._handle_browser_msg(viewer, {"action": "center"}, None)
    viewer._handle_browser_msg(viewer, "not-a-dict", None)
    assert synced == ["viewer", "source"]
