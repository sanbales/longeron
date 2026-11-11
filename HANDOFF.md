# Handoff — wave 5 (DecisionAnalysis) after the 0.12.0 release

Written 2026-11-10 on the 0.12.0 release commit (parent `209ba2d`,
main). This document stands alone; the local-only session ledger
(`.handoff/CURRENT-2026-08-30.md`, gitignored) has the full campaign
narrative if this machine is available.

## Where things stand

**0.12.0 is released** from the commit that carries this file: tag
`v0.12.0`, wheel + sdist on PyPI (`release.yml`), and the GitHub
Release with the re-recorded demo (`demo.gif`, `demo.mp4`; the README
links `releases/latest/download/demo.gif`). `docs/release-notes.md`
`## 0.12.0 (2026-11-10)` records what 0.12 shipped.

Next: **wave 5** (below), the last arc before 0.13, then the 0.13
slate (Open threads).

Baselines to trust (and assert against), measured on the release
commit:

| thing | value |
|---|---|
| non-browser suite, pixi lane (has cadquery; CI-equivalent) | **3394 passed** / 5 skipped / 2 xfailed (37 browser deselected) |
| non-browser suite, .venv lane | **3377 passed** / 22 skipped / 2 xfailed (37 browser deselected) |
| notebook harness (`tests/test_notebooks.py`) | 21/21 |
| browser tier | 5 CI shards (`ci.yml` matrix; the grand tour has its own); not re-run locally on the release commit |
| crossing | **1920** platform mixes (12 airframes × 4 motors × 4 props × 5 batteries × 2 materials); ISR and logistics cross 3 payloads each, 5760 |
| declared references (`ScoutMissions`) | 274.6 min / 187.0 kg·km / 66.9 m/s / $9706.5 / 6.89 kg |
| mission winners | ISR: flyingWingSingle · logistics: flyingWingTwinTip · intercept: dartInterceptor |

The declared references reproduce from the live winners: 274.567 min,
186.986 kg·km, 66.927 m/s; fleet cost = the three winners'
`missionCost` (5965.93 + 1910.47 + 1830.07 = 9706.47); heaviest bird =
the logistics winner's `outboundMass` 6.885 kg.

The fleet is **twelve airframes**: six rotorcraft (`boxQuad`,
`teardropQuad`, `openTri`, `hexLifter`, `coaxOcto`, `ringOcto`),
`vtolWing`, `dartInterceptor`, three flying wings (`flyingWingSingle`,
`flyingWingTwin`, `flyingWingTwinTip`) and `tiltTriWing`
(`TiltRotors::TiltTriWing`, `examples/deepscout/tilttri.sysml`).

## Wave 5 — the enlarged DecisionAnalysis arc (ratified, unbuilt)

All decisions below are maintainer-ratified; do not relitigate. Build
once, against the final 12-airframe fleet.

**1. The `DecisionAnalysis` library** (SysML, stdlib shelf beside the
vendored TradeStudies — NOT `Longeron*`-prefixed):

- Naming convention (ratified): `Longeron*` prefix = TOOL CONTRACT only.
  DecisionAnalysis is portable domain content and must carry a
  **mechanically-enforced portability test**: it references nothing
  tool-specific; the test doubles as a rename tripwire if OMG ships a
  standard equivalent. (`LongeronSurfaces` keeps its prefix — the
  rendering-registry seam is a genuine tool contract.)
- An MCDA **taxonomy, not one pipeline** — three families, common
  signatures, strategy chosen by typed reference (the loft
  profile-binding idiom), TWO members per family minimum (the surfaces
  two-subject proof pattern):
  - **Utilities** (raw → 0..1): the scoreboard's existing shapes
    (larger/smaller-is-better, ramp, target-is-best, step) + an
    exponential risk-averse/prone member.
  - **Weights**: direct + Rank Order Centroid (w_i = (1/k)·Σ_{j≥i} 1/j)
    + swing weights.
  - **Aggregations**: SAW (additive) + worst-n shortfall + Hurwicz blend.
- **The worst-n aggregation** (the maintainer's design): standardize
  every requirement to a utility; shortfall = 1 − score; importance
  weights the shortfall (an unimportant miss stops hurting);
  pessimistic aggregate = mean of the **n worst** weighted shortfalls
  (CVaR over shortfalls — Rockafellar & Uryasev is the citation).
  Default n(k) is the maintainer's table, which is EXACTLY triangular
  thresholds: n increments at k = n(n+1)/2 + 2 (i.e. 5, 8, 12, 17);
  closed form `n = max(1, floor((sqrt(8k−15) − 1)/2))`, verified against
  all 20 table rows. The arc must COMPARE this √-law against linear
  tail-fraction forms (p=0.4 rounded; floor(k/2.5)) on the real
  requirement sets and show the maintainer the lineup differences
  before the default is final.
- **The published MOE** = Hurwicz blend of pessimistic and additive
  (one blend parameter, mined-anchor idiom so the dashboard slider is
  model-derived). n=1 ≡ the scoreboard's existing `min`; n=k ≡ weighted
  mean — the law interpolates the existing Aggregation vocabulary.
- **TOPSIS is named-and-reserved**: population-level calcs
  (ideal/anti-ideal over the candidate SET) — document the seam, do not
  build.
- DeepScout::scoring rebuilds atop the library as the proof.

**2. Interpreter sequence ops** (the strict choice, ratified): the
expression language gains sort / nth-worst / take so the ENTIRE score is
a calc the interpreter evaluates — no engine asterisk. Extend the
existing sequence-builtin seam (`size` at `src/longeron/interpreter.py`
~line 236). Semantics must be standard-KerML-flavored (the portability
gate depends on it). This feature pays beyond scoring: order-statistics
calcs for any model.

**3. Requirement-driven MOE** (dashboard rework):

- Priorities/weights live IN the model as requirement attributes (the
  slider-anchor idiom); the dashboard MINES them — no more hardcoded
  three mission rows.
- **Boolean requirements become toggle FILTERS** (feasibility screens,
  not graded scores): crew-portable, launch-equipment, and
  **EngineOutYaw** — flipping "require engine-out" should move the
  logistics crown between flyingWingTwinTip (187.0) and the root twin
  (184.7) live; that toggle is the ratified answer to "should a courier
  that cannot survive a tip-engine failure win?" (maintainer chose:
  accept the crown, the toggle makes the gate interactive).
- Continuous requirements enter the weighted MOE.
- **COST STAYS OUT of the MOE** — it is the other scatter axis; the
  frontier judges.

**4. The attrition + operational cost chain** (maintainer reframe:
engine-out is a COST, not a safety constraint — nobody is aboard):

- Catalog parts (motors, ESCs) gain cited NOMINAL failure rates per
  flight hour.
- Each shell derives **P(craft loss | engine failure) FROM its own
  engine-out story**: the tip twin's busted EngineOutYaw ⇒ ~certain
  loss in cruise; multirotor mirror-shutdown (hexa/X8) ⇒ low;
  TiltTriWing's centerline CruiseEngineOut PASS ⇒ low in cruise, fatal
  in hover (tri); single-engine craft ⇒ loss on failure.
- expectedAttritionCost = mission hours × rate × P(loss) × unit cost.
- **Operational cost** (maintainer amendment): energy per sortie from
  the pack the mission actually drains, battery-cycle depreciation at a
  cited cycle life, a nominal maintenance rate per flight hour.
- The dashboards' **cost axis becomes acquisition + attrition reserve +
  operating** — every constant cited, every input model-derived.

## The next release train (0.13.0)

The 0.12.0 train ran in this order; repeat it.

1. Release notes: the lanes add bullets under `## <next> (unreleased)`
   as they land; at the train, date the header and read the section
   once as a newcomer (duplicated lane bullets, internal notes, terms
   undefined at first use). Check the section against
   `git log v<previous>..HEAD`: every user-visible commit since the last
   tag needs a bullet (the 0.12 section had missed the 31 commits that
   landed before the grand tour v2 lanes).
2. Version bump: `pyproject.toml`, `src/longeron/__init__.py`,
   `npm/package.json`, then the jlpm labextension rebuild
   (`pixi run -- bash -c 'cd npm && jlpm install && jlpm build'`).
   The rebuild renames `remoteEntry.<hash>.js` (the old file is
   deleted, the new one added: stage both) and rewrites the manifest's
   `version` and `load` path; the JS changes only by the version string
   and a webpack module id. `test_extension_version_matches_the_wheel`
   catches a missed step.
3. `pixi lock`: the lock pins the local manifest hash, so only the
   `longeron` entry moves (version + sha256). Any other package moving
   is a red flag.
4. Dist check BEFORE the tag, as `release.yml` does: `python -m build`,
   `twine check dist/*`, and the fresh-venv wheel smoke, plus both
   suite lanes (the .venv lane caught the OpenMDAO 3.45.2 break in the
   0.12 train). setuptools
   warns that the `project.license` TOML table and the license
   classifier are deprecated (unsupported after 2027-02-18): move to an
   SPDX `license = "Apache-2.0"` string (it needs `setuptools>=77` in
   `[build-system]`; today `>=68`) before then.
5. CI green on the EXACT commit, then tag, then PyPI, then the GitHub
   Release with the demo media. `scripts/record_demo.py` records the
   demo; media stages in `~/workplace/longeron-demo-media/<version>/`
   and never enters the repo.

## Protocols (all mechanically or maintainer-enforced — restate in briefs)

- **Agents work in git worktrees** (`../longeron-wt-<task>`), make NO
  git writes, stage nothing; the main session reviews, applies
  (`git -C <wt> diff --binary | git apply`, untracked files copied
  explicitly), gates, and lands. Notebook user-churn: stash before
  applying, pop after (drop if metadata-only).
- **git-guard**: explicit-path staging only; fresh standalone
  `git status --porcelain` immediately before EVERY commit; staging and
  committing in one command is BLOCKED (three steps).
- **Pre-push hook** (`scripts/git-hooks/pre-push`): lint + typecheck +
  the full pixi-lane suite run before ANY push leaves the machine.
  `LONGERON_PUSH_UNGATED=1` is the documented emergency escape.
  Change-scoped gates (notebook harness, docs −W, impacted browser
  files, captures) remain procedural — the hook is the floor.
- **Both suite lanes at every landing** — the .venv lane silently skips
  cadquery-gated tests; the pixi default env is the CI-equivalent. The
  .venv lane resolves the LATEST PyPI releases, so it is the only lane
  that sees upstream drift that `pixi.lock` pins away (the 0.12.0 train:
  OpenMDAO 3.45.2 broke `run_optimization` while the lock held 3.45.0).
- **Browser tier**: ONE customer at a time
  (`pgrep -f 'envs/browser.*pytest|capture_widget'` must be empty);
  explicit `--timeout` always; process kills PID-SCOPED only (verify
  the command line contains your worktree path; NEVER pattern-kill
  jupyter/ipykernel/chromium — a pattern-kill once destroyed the
  maintainer's live lab sessions).
- **Reference-number protocol**: agents REPORT declared-reference
  deltas with reproducible snippets; the main session applies only
  after independent reproduction. Winner-family changes = STOP and ask.
- **Captures**: `pixi run capture-widgets <nb>` when a manifest
  notebook's renders change; keep only genuinely-changed PNGs, revert
  framing jitter. A skipped recapture once broke docs CI.
- **Prose**: `/Users/sanbales/.claude/skills/writing-documentation/SKILL.md`
  in full for any docs/notebook prose; docs voice is as-is, no
  attribution, no process narrative, no out-of-repo references. NOTE:
  the `artifactory-design` skill symlink is BROKEN (points at a removed
  toolbox path) — follow the in-repo `_chrome.py` conventions for
  widget UI until the maintainer repairs it.
- **with-cores** for every suite (`-n 4` light, `-n 8 --min 4` heavy).
- **ipyelk is a plain dependency**: `ipyelk>=3.0,<4` from PyPI, through
  the `diagrams` extra (mirrored in `dev` and in every pixi env).
  Longeron carries no ipyelk patches. Report an ipyelk defect upstream
  (jupyrdf/ipyelk) and work around it in longeron until a release fixes
  it. The ipyelk wheel installs the jupyter-elk labextension.
  `sync-labextension` syncs only the longeron launcher tile.

## Open threads (carried, not blocking)

- 0.13 slate (all adopted): geometry phase 1 (vendored OMG Geometry
  lib, LongeronGeometry CSG, model→mesh/OCC compiler, .jcad export),
  LongeronLoft + wing editor (high-dihedral blended tips are a NAMED
  requirement — the winglets-as-curved-tips question), grand tour as a
  DeepScout declaration (surfaces phase 2), time-seam phase 3,
  transition kinematics for the tilt-tri.
- Deferred nits: compartment header questions (partially unanswered),
  graph3d round 2 (desktop findings, namespace hulls, Barnes-Hut),
  Cesium landing-descent nit, launcher console polish,
  `pilot_referee.py`, ipyarborist decision, 2 permissiveness gaps,
  KerML build path, `save_surface`, playhead-joins-selection.
- The intercept audit's do-not-add list is recorded IN the model: no
  turn-rate/corner-speed floors, no acceleration-time score (they
  promote the wings). The advance-ratio fidelity ceiling is declared on
  the mission doc.
- Dashboard mixed-run lost-click flake: seen once more at the wave-4
  landing (toggle click lost in a 3-file run; isolated-clean). If it
  recurs on CI shards despite the rerun budget, the seam's intent
  machinery is the likely fix point.

## Cost/cadence notes

~130 background agents this campaign. The j141 lesson is worth keeping:
when an agent wedges on a mechanical loop (capture retries), kill it,
diagnose in the main session, and relaunch a FINISHER with the diagnosis
in the brief — j141 burned $144 rediscovering; j142 finished for $26.
