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
4. **F1-F6 ported from `~/workplace/ipyelk` branch `critical-fixes-batch-1`**
   (same author, targeting upstream master):
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
9. **F10 backported from `~/workplace/ipyelk` branch
   `critical-fixes-batch-2` (849769f, same author, targeting upstream
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
