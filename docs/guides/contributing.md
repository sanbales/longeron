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
| `lint` | `ruff format --check` and `ruff check` over `src tests examples scripts notebooks docs`. |
| `format` | `ruff format` plus `ruff check --fix` over the same paths. |
| `typecheck` | `mypy` over `src/longeron` and `src/sysml2` (generated code excluded). |
| `coverage` | pytest with `--cov=longeron`. |
| `parsers` | regenerate the ANTLR parsers from `grammars/*.g4` (needs Java; pixi provides it). |
| `stdlib` | rebuild the prebuilt standard-library JSON (`scripts/vendor_stdlib.py --prebuilt-only`). |
| `demo` | run `examples/demo.py`. |
| `docs` | `sphinx-build -W -b html docs build/docs` (needs the `docs` extra; execution needs the `dev` extras plus node). |
| `hooks` | point `core.hooksPath` at `scripts/git-hooks`. |
| `notebooks` (pixi) / `scripts/run_notebooks.py` | execute every tutorial notebook, then strip outputs. |
| `lab` (pixi) | JupyterLab in `notebooks/`, with the vendored ipyelk extension pre-registered. |

Ruff formats and lints the notebooks too (`extend-include = ["*.ipynb"]`
in `pyproject.toml`), so `lint` gates notebook code cells exactly like
`.py` files.

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

CI runs a grammar-regen job that fails when the committed parsers drift
from the `.g4` sources, so never hand-edit `_gen/`.

## CI

Three workflows run on pixi (`prefix-dev/setup-pixi`, cached by
`pixi.lock`):

| Workflow | Runs |
|---|---|
| `ci.yml` | the `check` job (lint, mypy, coverage), a test matrix across the four Python environments (`py310`–`py313`), and the grammar-regen drift check |
| `docs.yml` | the documentation build, published to GitHub Pages |
| `release.yml` | on tag push: build, wheel smoke test, and PyPI trusted publishing |

## Documentation

The site builds with `make docs` or `pixi run docs`, which run
`sphinx-build -W`, so every warning fails the build. Tutorial pages are
the committed notebooks, symlinked into `docs/tutorials/` and executed
by myst-nb at build time. If you change a notebook, the next docs build
re-executes it.
