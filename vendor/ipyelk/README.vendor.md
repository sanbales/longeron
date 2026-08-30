# Vendored ipyelk

Source: https://github.com/jupyrdf/ipyelk
Tag: v2.1.1 (65c08ad lineage)
License: BSD-3-Clause (see LICENSE.txt)

Vendored for local TLC: install with `pip install -e vendor/ipyelk` (the
pixi environments do this automatically). The prebuilt JupyterLab extension
(`src/_d/share/...`) was originally grafted from the ipyelk 2.1.1 PyPI wheel;
since patch 7 it is **built from the vendored TypeScript sources** (`js/`),
so every JS fix below is active in the shipped bundles. To rebuild:

    cd vendor/ipyelk
    jlpm install          # uses the vendored yarn.lock / .yarnrc.yml
    jlpm build            # tsc -> lib/, then `jupyter labextension build .`
                          # (needs node >=20 + jupyterlab>=4.1 with builder)

The build writes directly into
`src/_d/share/jupyter/labextensions/@jupyrdf/jupyter-elk/`.

Local patches are tracked in this repo: `git log -- vendor/ipyelk`.

## Local patches (chronological)

1. **Headless-safe scheduling** -- `Pipe.schedule_run` no longer raises
   `RuntimeError: no running event loop` outside Jupyter; it skips
   scheduling (layout is a browser round-trip) without orphaning coroutines.
2. **Prebuilt labextension grafted** from the 2.1.1 wheel into `src/_d/`
   (the git tree only carries TypeScript sources); their `.gitignore`
   overridden so the graft is tracked.
3. **Resend-with-backoff browser round-trips** (`util.browser_roundtrip`) --
   `Widget.send` only reaches existing views, so pipes that ran before the
   diagram was displayed hung forever ("diagram never loads" until a kernel
   interrupt). Retry semantics refined by patch 9: a browser-reported error
   stops the resends and the default deadline is finite.
4. **F1-F6 ported from the patch author's ipyelk fork, branch
   `critical-fixes-batch-1`** (targeting upstream master):
   - F1: `IDReport.message` printed literal `{eid}`/`{el}` instead of ids
   - F2: empty `Pipeline` crashed `check()` (UnboundLocalError) and
     `get_progress_value()` (ZeroDivisionError)
   - F3: `Tool._on_run_handlers` was a shared class attribute -- callbacks
     leaked across tool instances
   - F4: exceptions raised inside asyncio done-callbacks were silently
     dropped; they now land on `pipe.status` and an `on_error(pipe, exc)`
     callback, and errored runs no longer push stale layouts to the view
   - F6 (python): `wait_for_change(timeout=...)`, an ElkJS browser error
     channel (`action: error` rejects the pending future), and a `timeout`
     trait on ElkJS/BrowserTextSizer -- **merged with patch 3**: default
     `timeout=0` kept resending forever (correct for not-yet-displayed
     widgets); a positive timeout is a hard deadline (the default became a
     finite 30 s deadline in patch 9)
   - F5/F6 (JS): exporter enabled-flag fix and browser-side layout error
     reporting, applied to the TypeScript sources (active in the shipped
     bundles since the source rebuild, patch 7)
   - the ported upstream tests live in `tests/` and run via
     `make test-vendor` / `pixi run test-vendor`
   - 07_Simulation example notebook fixes
5. **Re-entrant `ELKLayoutModel.layout()`** (`js/layout_widget.ts`;
   originally also hand-patched into the then-prebuilt bundle, now built
   from source -- see patch 7):
   `collectProperties` stripped `properties` (incl. `cssClasses`) from the
   shared inlet value IN PLACE, restoring them only onto the layout result.
   Duplicate `run` messages -- the resend-with-backoff of patch 3, or
   overlapping `refresh()` calls -- therefore re-laid-out an already
   stripped graph and pushed a style-less layout: diagrams rendered styled,
   then flipped to black-and-white boxes ~2 s later. The graph is now
   deep-copied before stripping, making `layout()` idempotent. Headless
   repro + fix proof: two consecutive `layout()` runs keep 14/14 styled
   elements (previously run#2 kept 0).
6. **Edge labels honor ELK positions** (`js/sprotty/sprotty-model.ts`;
   originally also hand-patched into the then-prebuilt bundle, now built
   from source -- see patch 7): `ElkLabel.DEFAULT_FEATURES` included sprotty's
   `edgeLayoutFeature`, so the EdgeLayoutPostprocessor re-anchored edge
   labels along the route and treated ELK's ABSOLUTE label coordinates as
   a relative offset -- every edge label rendered shifted by roughly its
   edge's origin (+144 px measured live). ELK already places labels;
   dropping the feature makes the browser render them exactly where
   elkjs put them, matching the headless SVG.
7. **Labextension rebuilt from the vendored sources** (2026-08-19): the
   `src/_d/` graft is no longer the hand-patched wheel payload -- it is the
   output of `jlpm install && jlpm build` against the vendored `js/`
   sources, `package.json`, `yarn.lock` and `webpack.config.js` (all
   matching upstream 65c08ad), so F5/F6/F7/F8 are compiled in rather than
   minified-bundle-patched. Build-only source tweaks: the now-unused
   `edgeLayoutFeature` import was dropped from `js/sprotty/sprotty-model.ts`
   (TS6133 under `noUnusedLocals`) and `js/tsconfig.json` excludes
   `**/*.test.ts` (the ported F5/F7 unit tests import `vitest`, which is
   not in the vendored 2.1.1 lockfile). The rebuild is reproducible: 13 of
   the 18 static chunks (incl. the elkjs workers) came out byte-identical
   to the 2.1.1 wheel; only `elklayout`, `elkdisplay`, `elkexporter`,
   chunk `160` and `remoteEntry` changed.
8. **Endpoint symbols follow the route under non-orthogonal edge routing**
   (`js/sprotty/views/edge_views.tsx`; bundles rebuilt as in patch 7 --
   same toolchain lineage, node 26.6.0 + jlpm from the longeron pixi env,
   only the `elkdisplay` chunk, `remoteEntry` and the labextension
   `package.json` `_build` pointer changed). Two maintainer-visible bugs,
   one root cause -- the view derived every symbol angle from the single
   adjacent route segment:
   - elkjs SPLINES sections duplicate control points at the section
     knots, so the terminal chord was zero-length and `atan2(0, 0) == 0`
     rotated end heads 0deg instead of pi on right-to-left ends: satisfy
     reference-subsetting heads rendered 180deg-flipped INSIDE the
     requirement box. The path-offset line trim rotated the same way, so
     the shaft overshot INTO the node beneath the flipped head.
   - elk POLYLINE exits nodes with a short stub (measured 5px) before
     the first real bend; a 12px membership diamond straddled the bend
     and stayed axis-aligned while the visible shaft left diagonally
     (the edge appeared to exit the diamond's SIDE).
   New `routeEndAngle(route, end, reach)`: the tangent is the chord from
   the route end to the point `reach` px along the route (`reach` = the
   connector's `path_offset` length = the symbol's footprint), skipping
   sub-`1e-3` chords; `coveredRoutePoints` additionally drops interior
   bends that fall under a symbol's footprint so the trimmed shaft cannot
   double back beneath it. Orthogonal routes are pixel-identical (their
   terminal runs exceed every symbol's reach by construction -- longeron
   keeps 24px of edge-node clearance). The math is pinned by a Python
   reference implementation (`longeron.render._route_end_angle` /
   `_covered_route_points`) tested against real elkjs section data.
9. **F10 backported from the patch author's ipyelk fork, branch
   `critical-fixes-batch-2` (849769f, targeting upstream
   master): errored layouts surface instead of loading forever.** Python
   only -- `js/` and the shipped bundles are untouched. Replaces the retry
   semantics of patches 3 and 4/F6 with the upstream final form (which was
   itself derived from the vendored `browser_roundtrip`):
   - `PipeStatus.STEPS` gains a terminal `error: 1` entry -- the missing
     entry made `get_progress_value()` raise `TypeError` inside the
     pipeline's own error path, so `on_error` saw the wrong exception and
     the progress bar sat mid-flight forever
   - `PipelineProgressBar` fills the bar and leaves it visible as a
     warning on an errored run (previously an eternally "in progress"
     sliver); a faulty `on_progress` callback logs instead of clobbering
     the pipe's surfaced error
   - the browser error channel (`action: error`, patch 4/F6) is hoisted
     `ElkJS` -> `SyncedPipe`, so `BrowserTextSizer` is covered too; a
     browser-reported layout error rejects the pending future and stops
     the patch-3 resend loop immediately -- "no frontend yet" and "layout
     errored" are distinct outcomes
   - **semantics change**: the `timeout` default on `ElkJS` and
     `BrowserTextSizer` is now a finite 30 s deadline (was 0 = forever), so
     a permanently silent browser cannot hang the kernel; `timeout=0` opts
     back into wait-forever. The build-in-one-cell/display-later pattern
     patch 3 existed for still works: requests are re-sent with backoff
     until a frontend answers (within the deadline)
   - vendored-only adaptations kept: headless-safe `schedule_run` and
     `_CompletedTask` (patch 1)
   - the upstream tests are ported:
     `tests/pipes/test_layout_error_semantics.py`,
     `tests/tools/test_progress.py`
10. **Label hover tooltips** (2026-08-25): `LabelProperties` (python) and
   `ElkProperties` (TS) gain an optional `tooltip` string; `ElkLabelView`
   renders it as the label's svg `<title>` -- the native browser hover
   tooltip. Longeron uses it for truncated compartment rows (the
   `max_label_width` cap ellipsizes overlong calculation rows and parks
   the full text on the tooltip; `render._svg_from_layout` emits the same
   `<title>` headlessly). Bundles rebuilt as in patch 7 (same toolchain,
   node 22.9.0): only the `elkdisplay` chunk, `remoteEntry` and the
   labextension `package.json` `_build` pointer changed.
11. **Early kernel selections queue instead of crashing the view**
   (`js/display_widget.ts`; bundles rebuilt as in patch 7, node 26.6.0 +
   jlpm from the longeron pixi env -- only the `elkdisplay` chunk,
   `remoteEntry` and the labextension `package.json` `_build` pointer
   changed). `JLModelSource.index` is only assigned by the first
   `doSubmitModel`, but the kernel can set the selection tool's `ids`
   BEFORE the first layout round-trip completes (a comm `set_state`
   racing `initSprotty`/`diagramLayout` -- longeron's explorer does
   exactly this when it builds a diagram with an initial highlight).
   `updateSelected` then reached `setSelectedNodes`, whose
   `this.source.index.getById(...)` threw
   `Uncaught (in promise) TypeError: Cannot read properties of undefined
   (reading 'getById')` (maintainer trace, live NB14 session; the same
   zombie-listener family as the `on_source_changed` "TODO disconnect
   old ones"). Now: `updateSelected` QUEUES the ids on
   `pendingSelected` when no index exists yet (`ELK_DEBUG` log) and
   `diagramLayout` replays them (one `SelectAction` + node mapping)
   right after the first model submit, so the early selection still
   lands visibly; `setSelectedNodes` itself null-guards the index (a
   disposed view's zombie listener has nothing to map against). A live
   selection change supersedes any queued one. Surfaced squarely by the
   fix: with early selections now LANDING, the renderer's
   `control_overlay` (a widget-subtype node every viewer renders beside
   the selection) started attaching during selection-render bursts, and
   its async snabbdom insert hook (`js/sprotty/renderer.tsx`
   `renderContent`) could `Widget.attach` onto a container the NEXT
   render pass had already replaced -- lumino throws `Host is not
   attached.` on the disconnected host (previously masked because the
   `getById` crash kept `selectedNodes` empty, so the overlay never
   rendered for kernel selections). `renderContent` now re-checks
   `vnode.elm.isConnected` after its awaits and drops the orphan view
   (`ELK_DEBUG` log) -- the newer insert hook owns the attach. The
   longeron browser tier drops its `getById` page-error allowance with
   this patch.
12. **Silently dropped widget state self-heals: the `stale` re-sync
   protocol** (2026-08-29; `js/measure_text.ts`, `js/layout_widget.ts`,
   `js/display_widget.ts`, `src/ipyelk/pipes/base.py`,
   `src/ipyelk/pipes/util.py`, `src/ipyelk/diagram/viewer.py`,
   `src/ipyelk/tools/progress.py`; bundles rebuilt as in patch 7, node
   26.6.0 + jlpm from the longeron pixi env -- the `elklayout` and
   `elkdisplay` chunks, `remoteEntry` and the labextension
   `package.json` `_build` pointer changed). Root cause of the longeron
   gallery CI wedge (test frozen 480s: 20 bars stuck at exactly 37.5%,
   one at 87.5%, kernel idle, zero errors): jupyter-server's iopub
   **rate limiter silently drops `comm_msg`** (widget state updates AND
   custom messages; `status`/`comm_open`/`execute_input` are exempt)
   whenever a burst outruns `iopub_msg_rate_limit`/`rate_limit_window`
   -- and the widget protocol has no retransmit, so one dropped update
   leaves the frontend model permanently diverged. A run-all creating
   two dozen diagrams is exactly such a burst on a loaded 2-core runner
   (the limiter is rate-based; a starved server drains its zmq backlog
   in bursts). Downstream anatomy, proven by dropping 60% of
   kernel->browser comm_msg for 25s locally (which reproduced the CI
   signature verbatim: 20 pipelines frozen at `BrowserTextSizer`, 6 at
   `ElkJS`, zero rendered, zero errors):
   - a pipe model whose **inlet value never arrived** answered re-sent
     `run` requests by silently returning `null` forever (the 37.5%
     bars: 3/8 progress = validation done, text sizer running);
   - a viewer model whose **`source` rewire never arrived** stayed a
     blank diagram forever;
   - a progress bar whose **terminal hide update was dropped** stayed a
     zombie bar forever.
   The patch closes the class, not the instances:
   - **browser -> kernel `action: stale`**: `measure()`/`layout()`
     answer an unservable `run` (missing inlet/outlet/value) with a
     stale report instead of returning silently; `ELKViewerView` runs a
     backoff stale pump (2s..10s) while it has no renderable source;
   - **kernel re-sync**: `SyncedPipe`/`Viewer._handle_browser_msg`
     answer a stale report with `send_state()` of the pipe and its
     endpoints (or the viewer and its source), throttled with a
     doubling 2s..30s gap (reset per roundtrip) so the re-syncs --
     three full states, the inlet value can be large -- cannot flood
     the congested relay that caused the loss in the first place
     (observed: unthrottled re-syncs collapsed the channel under the
     60% injector); the patch-3 resend loop then re-fires `run` against
     a healed frontend;
   - **`ELKViewerView` listens on the MODEL**: upstream subscribed
     `change:source` on the VIEW (`this.on`), a channel nobody
     triggers, so a source wired after view-init never attached its
     `change:value` listener (blank forever even once state healed);
     now `this.model.on(...)`, with the previous source's listener
     disconnected (the upstream `TODO disconnect old ones`);
   - **terminal progress-bar echoes**: `PipelineProgressBar` re-emits
     the bar's terminal state (hide / fill-as-warning) at +2s and +10s,
     so a dropped hide heals instead of leaving a zombie bar;
   - a throwing `measure()` now reports over the patch-9 error channel
     (it used to reject silently inside the kernel connection's serial
     message chain, whose catch swallows everything).
   Longeron pairs this with conftest-level
   `--ZMQChannelsWebsocketConnection.limit_rate=False` (the tier wants
   correctness, not client-protection dropping). Constrained-repro
   before/after on the notation gallery: pre-patch, a limiter tripping
   at 5 msg/s and the 60%-drop injector both wedge it frozen for the
   full 480s budget; post-patch the same gallery settles green in 27s
   (limiter config neutralized), 33s (20% drops) and 57s (60% drops,
   2426 messages dropped and self-healed). Tests:
   `tests/pipes/test_stale_resync.py`.
13. **Compartment separator rules** (2026-08-31;
   `js/sprotty/views/node_views.tsx`; bundles rebuilt as in patch 7, node
   26.6.0 + jlpm from the longeron pixi env -- only the `elkdisplay`
   chunk, `remoteEntry` and the labextension `package.json` `_build`
   pointer changed). SysML v2 labeled compartments (spec 8.2.3.6) open
   with a full-width horizontal rule above the compartment's header; the
   kernel cannot draw it because node widths are browser-measured, so
   only the view knows the final edge-to-edge span. `ElkNodeView.render`
   now emits one `<path class="sysml-comp-rule">` per child label
   carrying the `sysml-comp-label` class, at the label's laid-out y
   minus a 1px gap -- the exact geometry longeron's headless SVG writer
   draws (`render._COMP_RULE_GAP` mirrors the constant). The paths are
   siblings of the node's rect, so longeron's derived stylesheet binds
   their stroke to the node kind's palette and recolors them with the
   `.elknode` selection/hover state classes via the `~` combinator;
   `pointer-events: none` keeps them out of the way of row hit targets
   (rows themselves need NO patch: the upstream `properties.selectable`
   label flag already makes them selectable/hoverable first-class
   sprotty elements). Nodes without header labels render byte-identically
   to before.
14. **Relayout robustness for wholesale tree swaps** (2026-09-01;
   `js/display_widget.ts` + `src/ipyelk/pipes/marks.py`; bundles rebuilt
   as in patch 7, node 26.6.0 + jlpm from the longeron pixi env -- only
   the `elkdisplay` chunk, `remoteEntry` and the labextension
   `package.json` `_build` pointer changed). Longeron's per-node
   collapse (`longeron.diagrams.CollapseTool`) REBUILDS the diagram's
   source tree and re-runs the pipeline with the birth flow; two stock
   assumptions broke:
   - **`MarkElementWidget.persist()` self-heals a stale index** (python).
     The whole pipeline shares ONE `MarkIndex` (every endpoint aliases
     the source's); `persist()` assumed endpoint values only ever mutate
     in place and `ElementIndex.update` raised `NotFoundError` on the
     first id the rebuilt tree introduced (also reachable without
     longeron: a cancelled run's late browser reply landing a different
     tree generation than the index was built from). It now rebuilds the
     index from the current value -- exactly what first use does --
     instead of erroring the pipeline forever. Test:
     `tests/pipes/test_persist_selfheal.py`.
   - **`diagramLayout` re-applies the kernel's live selection** (TS).
     Every relayout (routing/direction toggles, collapse rebuilds)
     submits a NEW sprotty model, and stock sprotty transfers no
     selection state across `UpdateModelAction`s -- the kernel-side
     selection tool still held its ids while the canvas showed nothing
     selected. After each `updateLayout`, the view now re-dispatches a
     `SelectAction` for the selection tool's current ids, filtered to
     elements that exist in the new model -- which is also what lets a
     collapsed child's selection survive as its compartment ROW (same
     qualified-name id, different element kind). The patch-11
     `pendingSelected` replay (selection BEFORE the first layout) keeps
     precedence.
   - **`handle(SelectAction)`'s write-back is generation-guarded** (TS).
     The write-back of sprotty's selection into the selection tool's
     `ids` is ASYNC (`getSelection()` resolves one action-queue slot
     later), so two `SelectAction`s dispatched close together -- the
     post-relayout re-apply above racing a kernel-driven
     `updateSelected` -- each read the OTHER action's resulting state
     and wrote it back, flipping `ids` between the two values forever: a
     self-sustaining microtask oscillation that pegged the renderer main
     thread and hung the whole page (observed: the app explorer's
     relationship-row click landing while the diagram's initial layout
     settled). A generation stamp now drops every superseded gather;
     only the LATEST `SelectAction`'s write-back lands, which matches
     the final sprotty state, so the feedback loop cannot ignite. (The
     race is latent in stock ipyelk -- two fast clicks could start the
     same oscillation -- but the relayout re-apply made it reliably
     reachable.)
