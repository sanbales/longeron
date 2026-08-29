# Copyright (c) 2024 ipyelk contributors.
# Distributed under the terms of the Modified BSD License.
import asyncio

import ipywidgets as W
import traitlets as T

from ..pipes import Pipe
from .tool import Tool


class PipelineProgressBar(Tool):
    bar = T.Instance(W.FloatProgress, kw={})
    pipe = T.Instance(Pipe)
    priority = T.Int(default_value=100)

    @T.default("ui")
    def _default_ui(self):
        return self.bar

    def update(self, pipe: Pipe):
        self.pipe = pipe
        bar = self.bar

        bar.value = pipe.get_progress_value()
        bar.max = 1

        if pipe.status.exception:
            # the run is over: fill the bar and leave it visible as a
            # warning instead of an eternally "in progress" sliver
            bar.value = bar.max
            bar.bar_style = "warning"
            bar.layout.visibility = "visible"
        elif bar.value == bar.max:
            bar.bar_style = ""
            bar.layout.visibility = "hidden"
        else:
            bar.bar_style = ""
            bar.layout.visibility = "visible"

        if bar.value >= bar.max:
            # LOCAL PATCH (sysml2-experiments): the terminal transition
            # (hide, or fill-as-warning) is a fire-and-forget state update
            # with no retransmit; a lossy iopub channel (e.g. a run-all
            # burst on a slow CI runner) that drops it leaves a zombie
            # bar on screen forever.  Re-emit the terminal state twice
            # with delay so a dropped hide heals itself.
            self._schedule_terminal_echo()

    def _schedule_terminal_echo(self):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # headless (scripts, pytest): nothing to re-sync
        for delay in (2.0, 10.0):
            loop.call_later(delay, self._echo_terminal_state)

    def _echo_terminal_state(self):
        bar = self.bar
        if bar.value >= bar.max:  # still terminal; a new run resets value
            bar.send_state()
            bar.layout.send_state()
