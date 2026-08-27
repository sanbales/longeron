# Development

This guide covers building the package from source, the task runners,
the git hooks, and the conventions that keep the repository clean. The
same checks run locally and in CI, so a green `check` locally means a
green pipeline.

## Set up a working tree

Two routes exist. They run the same commands.

With a plain virtualenv:

```bash
git clone https://github.com/sanbales/longeron
cd longeron
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" -e vendor/ipyelk
make check
```

With [pixi](https://pixi.sh), which adds a locked toolchain (node, the
ANTLR tool, a JDK, JupyterLab) on top of the same `[project]` metadata:

```bash
pixi run check
```

Enable the git hooks once per clone:

```bash
make hooks        # or: pixi run hooks
```

## The tasks

Every task exists in both runners. `make <target>` uses the venv, and
`pixi run <task>` uses the locked pixi environment.

| Task | Does |
|---|---|
| `check` | `lint` + `typecheck` + `test` + `test-vendor`. The full gate. |
| `test` | `pytest -q` over `tests/`. |
| `test-vendor` | the vendored ipyelk test suite (`vendor/ipyelk/tests`). |
| `test-browser` (pixi) | the browser-truth tier (`tests/browser/`): headless JupyterLab driven by Playwright/Chromium. See below. |
| `lint` | `ruff format --check` and `ruff check` over `src tests examples scripts notebooks docs`. |
| `format` | `ruff format` plus `ruff check --fix` over the same paths. |
| `typecheck` | `mypy` over `src/longeron` (generated code excluded). |
| `coverage` | pytest with `--cov=longeron`. |
| `parsers` | regenerate the ANTLR parsers from `grammars/*.g4` (needs Java; pixi provides it). |
| `stdlib` | rebuild the prebuilt standard-library JSON (`scripts/vendor_stdlib.py --prebuilt-only`). |
| `demo` | run `examples/demo.py`. |
| `docs` | `sphinx-build -W -b html docs build/docs` (needs the `docs` extra; execution needs the `dev` extras plus node). |
| `capture-widgets` (pixi) | re-capture the tutorial widget snapshots (`docs/_static/widget-snapshots/`) from a headless JupyterLab; run after changing a widget-bearing cell in tutorials 1–11. See below. |
| `hooks` | point `core.hooksPath` at `scripts/git-hooks`. |
| `notebooks` (pixi) / `scripts/run_notebooks.py` | execute every tutorial notebook, then strip outputs. |
| `sync-labextension` (pixi) | copy the repo's labextension builds -- the vendored jupyter-elk **and** the longeron launcher tile (`npm/_d`, which editable installs never place) -- into every pixi env's `share/jupyter/labextensions` (the copy JupyterLab actually serves); warns when a served copy was stale. |
| `lab` (pixi) | JupyterLab in `notebooks/`, with the vendored ipyelk extension and the longeron launcher tile pre-registered (depends on `sync-labextension`). |

Ruff formats and lints the notebooks too (`extend-include = ["*.ipynb"]`
in `pyproject.toml`), so `lint` gates notebook code cells exactly like
`.py` files.

## Browser-truth tests

`tests/browser/` drives a **real** JupyterLab in headless Chromium:
elkjs layout, sprotty rendering, widget trait sync, and the served
labextension bundle all run for real. Kernel-side tests cannot see that
class of regression (stale served bundles, unpainted arrowheads,
layout-error starvation), so this tier exists as its own opt-in gate:

```bash
pixi run -e browser playwright install chromium   # once per machine
pixi run test-browser
```

The tier is deselected from plain `pytest -q` (everything there carries
`@pytest.mark.browser`, and the default `addopts` excludes that marker),
and its dependencies live in the `browser-test` extra / the pixi
`browser` environment -- **not** in `dev`, so default environments never
grow a browser. This is the one task without a `make` twin: it needs the
pixi-locked JupyterLab plus a Chromium binary. The task syncs the
vendored labextension first (the stale-bundle footgun below applies
doubly to tests). Assertions are semantic only -- settle states, error
counts, DOM presence, kernel round trips; never pixels or timing
margins. The full flake policy, quarantine convention, and
failure-artifact locations are documented in `tests/browser/README.md`.

## Notebook conventions

The eight tutorials in `notebooks/` follow three rules:

1. **Committed notebooks are output-free.** The pre-commit hook strips
   outputs, execution counts, and volatile metadata from every staged
   `.ipynb`, rewriting only the git index, so your working tree keeps
   the outputs you are looking at.
2. **Executability is tested.** `tests/test_notebooks.py` executes every
   notebook, and the documentation build executes them again to render
   the tutorial pages, so a broken notebook fails both gates.
3. **Refresh runs are deterministic.** `python scripts/run_notebooks.py`
   executes and strips every notebook in place. A rerun on an unchanged
   tree produces no diff.

The hook also refuses any staged blob over 5 MB, after stripping. For a
deliberate large asset, commit with `--no-verify` and say why in the
commit message.

## The generated and vendored pieces

Some trees are outputs, not sources. Edit the source and regenerate:

| Tree | Source | Regenerate with |
|---|---|---|
| `src/longeron/_gen/` | `grammars/*.g4` | `pixi run parsers` (or `make parsers`) |
| `src/longeron/_stdlib/prebuilt.json` | `src/longeron/_stdlib/**/*.sysml` | `make stdlib` |
| `vendor/ipyelk/` | upstream ipyelk 2.1.1 + local patches | edit in place; mark changes `LOCAL PATCH` and log them in `vendor/ipyelk/README.vendor.md` |

One labextension footgun to know about: rebuilding the vendored
TypeScript (`vendor/ipyelk/js/`) writes the bundles into
`vendor/ipyelk/src/_d/share/jupyter/labextensions/@jupyrdf/jupyter-elk`
(and rebuilding the launcher tile, `npm/`, writes into
`npm/_d/share/jupyter/labextensions/longeron` -- see `npm/README.md`),
but JupyterLab serves the **copy** that `pixi install` made under
`.pixi/envs/*/share/jupyter/labextensions/` -- so a rebuilt bundle
silently keeps serving the old code ("the fix didn't take").  `pixi run
lab` now runs `sync-labextension` first (it prints a warning whenever a
served copy was stale before syncing); after rebuilding either
extension's TS, restart lab through `pixi run lab` (or run `make
sync-labextension`) and
hard-refresh the browser.

CI runs a grammar-regen job that fails when the committed parsers drift
from the `.g4` sources, so never hand-edit `_gen/`.

## CI

Three workflows run on pixi (`prefix-dev/setup-pixi`, cached by
`pixi.lock`):

| Workflow | Runs |
|---|---|
| `ci.yml` | the `check` job (lint, mypy, coverage), a test matrix across the four Python environments (`py310`–`py313`), the browser-truth job (`tests/browser/` in headless Chromium, failure screenshots uploaded as artifacts), and the grammar-regen drift check |
| `docs.yml` | the documentation build, published to GitHub Pages |
| `release.yml` | on tag push: build, wheel smoke test, and PyPI trusted publishing |

## Documentation

The site builds with `make docs` or `pixi run docs`, which run
`sphinx-build -W`, so every warning fails the build. Tutorial pages are
the committed notebooks, symlinked into `docs/tutorials/` and executed
by myst-nb at build time. If you change a notebook, the next docs build
re-executes it.

Interactive widget outputs (ipyelk diagrams, anywidget viewers) render
on the tutorial pages as committed PNG snapshots from
`docs/_static/widget-snapshots/` (swapped in by the
`docs/_ext/widget_snapshots.py` extension, keyed by its
`manifest.json`). The docs build itself stays deterministic and
Chromium-free; the snapshots are refreshed manually with
`pixi run capture-widgets` (browser environment: needs
`pixi run -e browser playwright install chromium` once per machine,
like `test-browser`). If you change a widget-bearing cell in tutorials
1–11, re-run it and commit the refreshed PNGs + manifest -- a stale
manifest fails the `-W` build with a pointer to that command.
