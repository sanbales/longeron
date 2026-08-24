# tests/browser -- the browser-truth tier

Real JupyterLab + headless Chromium (Playwright) driving the actual
rendered widgets: elkjs layout, sprotty rendering, trait sync, and the
labextension bundle all run for real.  This tier exists because an
entire class of regressions (stale served bundles, marker-end paint
bugs, layout-error starvation, auto-fit) is **invisible to kernel-side
tests** -- it only reproduces in a browser.

## Running

```bash
pixi run test-browser          # syncs the labextension, then runs this dir
```

The task lives in the pixi `browser` environment (the default toolchain
plus the `browser-test` extra: playwright + pytest-rerunfailures).  First
run on a machine needs the browser binary once:

```bash
pixi run -e browser playwright install chromium
```

Plain `pytest -q` never runs these tests: everything here carries
`@pytest.mark.browser` (enforced by a conftest hook) and the default
`addopts` deselects that marker.  Keep it that way -- default envs must
not grow a browser.

Outside pixi, any interpreter works if it has jupyterlab, the dev
extras, the `browser-test` extra, the vendored ipyelk installed, and
`node` on `PATH` (the replay scenario bakes SVG through elkjs-on-node).
The conftest boots the lab server from `sys.executable` and syncs the
served jupyter-elk labextension from `vendor/ipyelk/src/_d` first --
never skip that sync; a stale served bundle "passes" with yesterday's
frontend code.

## Flake discipline

**What a test here MAY assert (semantics):**

- settle states: no busy prompts, no visible progress bars, N widgets
  rendered -- with slack (`>= 20` of 23, never `== 23`);
- error counts: page errors, console errors (allowlist in `conftest.py`,
  empty today; additions need a written reason);
- element/class presence: `.elknode`, `.sysml-search-hit`,
  `.longeron-fired`, `.lgx-selected`, a resolving `marker-end`
  reference;
- viewport transforms *moved off the identity* (the auto-fit signal) --
  the direction of change, never coordinates;
- kernel round trips: re-run a checker cell, parse its JSON, compare
  traits (selection counts, tool state, `pipe.status.exception`).

**What a test here MUST NOT assert:**

- pixels: no screenshot comparisons, no colors, no geometry beyond
  "the transform is not the identity";
- exact coordinates, sizes, or node positions (layout output may change
  with any elk/sprotty/font update);
- timing margins: never "settled within N seconds" as a *quality* claim.
  Timeouts exist only as failure deadlines and are deliberately generous;
- exact counts where the model could legitimately grow (use `>=` with
  slack, and record today's true value in a comment).

**Determinism over waiting:** prefer driving state directly (scrub the
replay slider to a recorded transition time) over playing animations and
polling. Every wait goes through `wait_until`/`wait_settled`, which
require the condition to hold for consecutive polls -- never `sleep(n)`
followed by a bare assert.

**Retry policy:** the pixi task runs with `--reruns 1`
(pytest-rerunfailures). One rerun absorbs infrastructure hiccups (slow
CI kernel start); it must never be the fix for a test that flakes on its
own logic.

**Quarantine convention:** a test that flakes twice in a week despite
the rerun gets `@pytest.mark.skip(reason="QUARANTINED: <issue link>")` on
the spot, an issue with the failure artifacts attached, and an owner.
Quarantined tests are un-skipped only with evidence (10 consecutive
local green runs of that test alone). Never delete a quarantined test to
make CI green.

**Failure artifacts:** every failed test writes a full-page screenshot
and the console/page-error log to `build/test-artifacts/` (plus
`lab-server.log`); CI uploads that directory on failure. Look there
first -- most "mysterious" failures are one console line away from
obvious.
