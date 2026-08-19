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
   interrupt).
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
     `timeout=0` keeps resending forever (correct for not-yet-displayed
     widgets); a positive timeout is a hard deadline
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
