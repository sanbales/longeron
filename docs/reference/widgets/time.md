# The time seam

`longeron.widgets.time` makes time a shared, linkable state across
every time-aware view. One `Clock` holds the playhead. `link_time`
subscribes the replay player, the mission globe, and the scrubber to
it. A scrub in one view then scrubs them all, with no echo. The
[time-seam design](../../design/time.md) states the full contract.

`Clock`, `Timebase`, and `link_time` need no extras. The scrubber
widget needs the `replay` extra (`pip install "longeron[replay]"`).

## The pieces

- `Clock` holds the shared state: `t`, `playing`, `rate`, and `span`.
  It owns no timer. Views animate; the clock fans state out.
- `Timebase` aligns one recording with its optional mission track, so
  every view plays the same execution.
- `link_time` wires views to the clock and returns an `unlink()`
  disposer, exactly like `link_selection`.
- `time_scrubber` builds the transport bar: play/pause, rate, the time
  axis with event ticks and phase bands, and a telemetry readout.

## Step-only traces

A pure event cascade records in step mode, and steps are not seconds.
The seam refuses the globe binding for such a trace by default.
`seconds_per_step` opts in: a scalar, or a per-step sequence/mapping
when steps take unequal durations. Durations the caller states count
as first-class. The scrubber labels only the synthesized gaps, with a
striped band and an explicit `(x10 s)` readout tag.

```{eval-rst}
.. automodule:: longeron.widgets.time
```
