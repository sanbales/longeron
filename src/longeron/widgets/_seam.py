"""Loss-tolerant state sync for kernel-mirrored widget traits.

The Jupyter widget protocol is fire-and-forget: a comm message that a
congested channel drops (jupyter-server's iopub rate limiter, a
websocket reconnect mid-burst) is gone, and because trait sync only
sends CHANGES, neither side ever re-states the lost value -- one drop
leaves the kernel and the front-end permanently split.  Worse, no drop
is even required: a stale in-flight report can do it alone.  The
observed anatomy (the time seam's browser CI, twice)::

    player front-end playing, reporting time at ~4 Hz
    user scrubs another view to 20
      kernel: clock.seek(20) -> player.time = 20 -> push {time: 20}
      the player's LAST in-flight report (74.7) lands after the seek:
        kernel: player.time = 74.7 -> clock.seek(74.7)
        the reversal never reaches the front-end -- the report itself
        already set the kernel-side trait, so the fan-out write
        coalesces to a no-op (no message)
      front-end: receives {time: 20}, adopts it, stops playback, and
        its force-sync coalesces at the backbone (its model already
        says 20) -- nothing is ever sent back
    fixpoint: front-end stopped at 20, kernel stuck at 74.7, forever

The cure is a small reconciliation protocol on top of plain trait
sync; the kernel is the source of truth and the front-end reconciles:

* **generation stamps** (``_seam_gen``): the kernel bumps the stamp on
  every authoritative push, so every push is a real message even when
  the mirrored values coalesce, and the front-end can SEE a missed
  push (a gap in the stamps) and ask for full state.
* **acknowledged reports** (``_seam_ack``): the front-end echoes the
  last stamp it applied alongside every report.  A report carrying an
  old stamp was sent before the front-end saw the kernel's latest
  push -- the kernel REJECTS it (the stale 74.7 above cannot re-seek
  the clock) and answers with an unconditional full-state re-push,
  which simultaneously heals a dropped push: the rejected reports keep
  arriving until one re-push lands.  Only MACHINE reports (the ~4 Hz
  playback integration -- the poison above) are guarded: a report
  marked as USER INTENT (``_seam_intent`` bumped in the same message:
  a scrub, a transport click) outranks any push it may have raced,
  because intent is new truth, not an echo of old state.
* **idempotent full-state pushes**: kernel pushes carry absolute
  values, never deltas, so any push that arrives heals every drop
  before it.
* **trailing-edge verify**: ~1.5 s after seam traffic quiesces (one
  shot, re-armed by traffic, never a hot timer) the front-end asks the
  kernel to re-state full truth (`lgn_seam: resync`), catching a drop
  of the LAST message of a burst in either direction.  A dropped
  front-end report heals to KERNEL truth -- the user sees the control
  revert and retries, instead of a silent permanent split.

Kernel side, a widget opts in by mixing :class:`SeamHost` into its
class and declaring the two stamp traits; the wiring layer (for the
time seam, :class:`longeron.widgets.time._TimeLink`) does the stamping,
rejection, and re-pushing.  Front-end side, the ESM prepends
:data:`SEAM_ESM` and routes every report through ``lgnSeam(model)``'s
``report()``.  Widgets that hold only single-shot, low-rate mirrored
state (a click's selection ids, a splitter ratio) do not need this
machinery -- see the pattern notes in :mod:`longeron.widgets`.
"""

from __future__ import annotations

from typing import Any

__all__ = ["SEAM_ESM", "SeamHost"]


class SeamHost:
    """Mixin marking which trait changes came from the front-end.

    ipywidgets applies a front-end update through ``set_state`` and
    fires the trait notifications after every key is in place.  During
    those notifications :attr:`_lgn_from_frontend` names the keys the
    front-end sent, so an observer can tell a REPORT (front-end wrote,
    staleness guard applies) from a kernel-side assignment (kernel is
    the truth; no guard).  Empty at every other moment.
    """

    _lgn_from_frontend: frozenset[str] = frozenset()

    def set_state(self, sync_data: dict[str, Any]) -> None:
        self._lgn_from_frontend = frozenset(sync_data)
        try:
            super().set_state(sync_data)  # type: ignore[misc]
        finally:
            self._lgn_from_frontend = frozenset()


#: the front-end half: gen tracking, gap detection, acknowledged
#: reports, and the trailing-edge verify.  Prepend to a widget's ESM
#: and call ``const seam = lgnSeam(model)`` inside ``render``; route
#: every machine report (playback integration) through
#: ``seam.report({...})`` and every user action through
#: ``seam.intent({...})``.  Inert (plain trait sync, no timers) until
#: the kernel stamps a push, so unlinked widgets keep today's behavior
#: byte for byte.
SEAM_ESM = r"""
function lgnSeam(model) {
  let gen = model.get("_seam_gen") || 0;
  let timer = 0;
  function resync() {
    try { model.send({ lgn_seam: "resync", gen }); } catch (err) { /* comm gone */ }
  }
  function verifySoon() {
    if (!(model.get("_seam_gen") > 0)) return;  // unlinked: stay inert
    clearTimeout(timer);
    timer = setTimeout(resync, 1500);  // one shot, trailing edge only
  }
  model.on("change:_seam_gen", () => {
    const g = model.get("_seam_gen") || 0;
    if (gen > 0 && g > gen + 1) resync();  // a push was lost: ask for truth
    gen = g;
    verifySoon();
  });
  function report(fields) {
    for (const key of Object.keys(fields)) model.set(key, fields[key]);
    if (model.get("_seam_ack") !== gen) model.set("_seam_ack", gen);
    model.save_changes();
    verifySoon();
  }
  return {
    report,
    intent(fields) {
      // a USER action outranks the in-flight push it may have raced:
      // the bumped counter rides the same message and lifts the
      // staleness guard for exactly this report
      model.set("_seam_intent", (model.get("_seam_intent") || 0) + 1);
      report(fields);
    },
    dispose() { clearTimeout(timer); },
  };
}
"""
