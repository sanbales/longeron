# Copyright (c) 2024 ipyelk contributors.
# Distributed under the terms of the Modified BSD License.
import asyncio


def wait_for_change(widget, value):
    """Initial pattern from
    https://ipywidgets.readthedocs.io/en/stable/examples/Widget%20Asynchronous.html?highlight=async#Waiting-for-user-interaction
    """
    future = asyncio.Future()

    def getvalue(change):
        """Make the new value available"""
        future.set_result(change.new)

    def unobserve(f):
        """Unobserves the `getvalue` callback"""
        widget.unobserve(getvalue, value)

    future.add_done_callback(unobserve)

    widget.observe(getvalue, value)
    return future


async def browser_roundtrip(pipe, trait: str = "value",
                            initial_delay: float = 0.5,
                            max_delay: float = 10.0):
    """Send ``{"action": "run"}`` to a synced pipe's frontend and wait for
    its outlet to change, resending with backoff until an answer arrives.

    LOCAL PATCH (sysml2-experiments): ``Widget.send`` only reaches *views
    that already exist*.  When a pipe ran before its diagram was displayed
    (the common notebook flow: build in one cell, render later), the request
    was lost and ``await`` hung forever -- diagrams appeared to "never
    load" until an interrupt re-triggered the pipeline.  Resending is
    idempotent, so retrying converges as soon as a view attaches.
    """
    future_value = wait_for_change(pipe.outlet, trait)
    delay = initial_delay
    while True:
        pipe.send({"action": "run"})
        try:
            await asyncio.wait_for(asyncio.shield(future_value), delay)
            return
        except asyncio.TimeoutError:
            delay = min(delay * 2, max_delay)
        except asyncio.CancelledError:
            future_value.cancel()
            raise
