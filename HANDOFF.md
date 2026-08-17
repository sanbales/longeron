# HANDOFF — sysml2-experiments session continuation

Read this first. The previous session ended at ~87% context; this document
is the working state. Delete it once its tasks are done.

## Context discipline (why this file exists)

The prior session burned context by reading large files and tool outputs
directly. Work differently:

- **Launch subagents for bulk work** (`~/.pi/agent/agents/`: `scout` for
  repo reconnaissance, `cartographer` for mapping, `worker` for scoped
  implementation, `verifier` for checks). Have them **write findings to a
  file** (e.g. `.handoff/<topic>.md`) and read only that.
- Never read: `src/sysml2/_gen/` (generated parsers), `vendor/ipyelk/`
  wholesale, `pixi.lock`, `_stdlib/prebuilt.json`, notebook JSON. Grep
  targeted; summarize via subagents.
- Long commands: redirect to `/tmp/*.log`, then `tail`/`grep` the log.

## Hard rules (mechanically enforced)

- **git-guard**: NEVER `git add -A`/`-u`/`.`. Stage explicit paths only.
  Run `git status --porcelain` as a standalone command immediately before
  every commit (it re-checks). Investigate any file you didn't expect.
- **Repo git hooks** (`scripts/git-hooks/pre-commit`, enabled via
  `core.hooksPath`): refuse staged notebooks with outputs/execution counts
  and staged blobs > 5 MB. Notebooks are committed output-free; strip with
  `python scripts/run_notebooks.py --strip-only`.
- Quality gate for every change: `make check` (ruff + mypy + 351 tests +
  33 vendored ipyelk tests). Notebooks validate via
  `python scripts/run_notebooks.py` (executes, then strips).
- Commits: `git -c user.email="sanbales@amazon.com" -c user.name="sanbales" commit`.

## Project in one paragraph

Python package `sysml2` (src layout): ANTLR-generated parsers for SysML v2 +
KerML (grammars locally patched, 5 documented bugs), full-coverage model
builder, lossless JSON import/export, KerML + OMG-API-JSON + Ecore
projections, validator (`sysml2 lint`), interpreter (exprs/calcs/instances/
constraints/requirements/action graphs/hierarchical+parallel state machines
with a clock), vendored OMG standard library (prebuilt JSON, ms loads),
multi-file workspaces with content-addressed JSON cache, interactive ipyelk
diagrams (`sysml2.diagrams`) + headless SVG/PNG rendering (`sysml2.render`,
node+elkjs), 6 tutorial notebooks, pixi-based toolchain and CI. `README.md`
is accurate and current. `vendor/ipyelk` is ipyelk 2.1.1 with local patches
(all marked `LOCAL PATCH`, provenance in `vendor/ipyelk/README.vendor.md`),
including F1–F6 ported from `~/workplace/ipyelk` branch
`critical-fixes-batch-1`.

## Pending tasks, in order

### 1. Rewrite history so notebook outputs never existed (user request)

Notebooks are output-free going forward, but old commits still carry
output-laden blobs (and two committed-then-removed
`notebooks/.ipynb_checkpoints/` files, swept in by a past `git add -A`).
The user wants history cleaned. Recipe (local repo, no remote):

1. Backup first: `git clone --mirror . ../sysml2-experiments-backup.git`
2. `pip install git-filter-repo` (into `.venv`)
3. Collect the blob ids of every historical `notebooks/*.ipynb` version:
   `git rev-list --all --objects | awk '$2 ~ /^notebooks\/.*\.ipynb$/ {print $1}' | sort -u`
4. `git filter-repo --force --invert-paths --path notebooks/.ipynb_checkpoints`
   plus a `--blob-callback` that, for blob ids collected in (3), parses the
   JSON and strips outputs/execution_count/metadata.execution/widgets
   (reuse the logic in `scripts/run_notebooks.py::strip`). Two separate
   filter-repo passes are fine and simpler.
5. Verify: commit count unchanged (minus nothing), `make check` green,
   `git log --oneline | wc -l`, spot-check an old commit's notebook has no
   outputs, repo size shrank (`du -sh .git`).
6. Tell the user all SHAs changed; the backup location.

### 2. Review ~/workplace repos for things worth porting (user request)

Already mined: `ipyelk` (F1–F6 ported), `ar-des` git hooks (ported).
Remaining inventory: `analysis`, `ar-des` (rest of it),
`ARManipulationAIContext`, `ARManipulationDESCommon`, `AROrbitalConceptSim`,
`ARRMTestMaps`, `CR-FlexCellDES-Tester`, `FlexCellSimulation`, `ipyinsight`,
`MyCli`, `RST-LHS-Pentacles`, `SMG-ToteCARE`, `starling-des-vibe-coded`,
`TPSInteg`, `upstage`.

Dispatch a `scout` subagent per candidate (or one agent, sequential) with
this brief: "Inventory <repo>: purpose, local branches/commits not on
origin, uncommitted work, and anything plausibly useful to
`sysml2-experiments` (a SysML v2/ANTLR/ipyelk/Jupyter/pixi Python project):
jupyter-widget fixes, notebook tooling, git hooks, pixi patterns, diagram/
ELK utilities, DES/simulation integrations for the interpreter. Write
findings to `~/workplace/sysml2-experiments/.handoff/review-<repo>.md`,
max 40 lines." Most promising first: `ipyinsight` (sibling jupyrdf-style
widget — likely has relevant widget/pipe fixes), `ARManipulationDESCommon`
(more scripts/conventions like the hooks), `upstage` (DES framework — a
possible interpreter integration target). Then summarize to the user and
port only what they confirm.

### 3. Backlog (user-acknowledged, not yet requested)

- Stage C semantics: implied specializations, spec-exact name resolution
  (would replace the validation whitelist in `validation.py`).
- Rebuild the vendored ipyelk labextension (`js/` toolchain) so the ported
  F5/F6 JS fixes reach the browser; then bump README.vendor.md.
- `pre-commit` (the framework tool) is referenced by the hook chain but not
  in dev extras; add it or drop the chain.

## Verification quickstart

```bash
cd ~/workplace/sysml2-experiments
git log --oneline | head -3   # b4f595f hooks, 2d33e23 output-free notebooks
make check                    # ruff + mypy + 351 tests + 33 vendored
pixi run lab                  # JupyterLab, notebooks/ + vendored examples
```
