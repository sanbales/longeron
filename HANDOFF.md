# Handoff — wave 5 (DecisionAnalysis) and the 0.12.0 release train

Written 2026-09-01 at `a448c13` (main, pushed, both suite lanes green).
This document stands alone; the local-only session ledger
(`.handoff/CURRENT-2026-08-30.md`, gitignored) has the full campaign
narrative if this machine is available.

## Where things stand

Main is at `a448c13`. Everything ratified for 0.12.0 is BUILT and LANDED
except **wave 5** (below), which is fully specified and is the last arc
before the release train. CI was fully green at `715c653` (first green
board since `d47a27a`); every push since has passed the local pre-push
battery, and the shard/seam/gate fixes have held.

Baselines to trust (and assert against):

| thing | value |
|---|---|
| non-browser suite, pixi lane (has cadquery; CI-equivalent) | **3228 passed** / 5 skipped / 2 xfailed |
| non-browser suite, .venv lane | **3205 passed** / 28 skipped / 2 xfailed |
| notebook harness | 21/21 |
| browser tier | 23 tests, 4 CI shards (`ci.yml` matrix), single-run green locally |
| crossing | **1920** candidates (12 airframes × 4 × 4 × 5 × 2) |
| declared references (`ScoutMissions`) | 274.6 min / 187.0 kg·km / 66.8 m/s / $9706.5 / 6.89 kg |
| mission winners | ISR: flyingWingSingle · logistics: flyingWingTwinTip · intercept: dartInterceptor |

The fleet is now **twelve airframes**: five multirotors, teardrop dart,
vtolWing, flyingWingSingle, flyingWingTwin, flyingWingTwinTip,
dartInterceptor's bench kin, and the new `TiltRotors::TiltTriWing`
(`examples/deepscout/tilttri.sysml`).

## What landed this session (for release-notes mining)

Commit messages are the source material; each carries its full story.

- `d47a27a`..`6a322d8` — the 0.12 punch list (flying wings, widget moves,
  typing/Literal pass, rdf self-loop fix, browser-harness watchdog).
- `981f648` — flying-wing stability & control (StabilityControl calcs,
  static margin, plank-busts proof, swept/washed/reflexed mesh).
- `88d67fd` — cranked planform + clearance-derived pods + the fleet
  prop-disc interference gate (Möller–Trumbore, oracle-teeth proof).
- `1231e7e` — the loss-tolerant widget seam (`widgets/_seam.py`):
  generation stamps, stale-report rejection, user-intent override,
  loss-injection browser test. The state split needed NO drops.
- `67fbe22` — CI browser tier sharded 4 ways; `test-browser-shard` task.
- `205a30f` — volumetric bays fleet-wide, FIT requirements, clickable
  battery/fc/camera, multirotor gussets. References followed live
  winners (283.3→274.6, →184.7 then →187.0 at the tip-crown landing).
- `715c653` — the geometry API stops inventing flight controllers
  (fc_mass None-default; model-driven callers; the cadquery-lane gate
  gap closed).
- `920657a` — the pre-push hook (see Protocols).
- `b14ae41` — wave 3: gust placard (dart wins riding it, 72.9→66.8),
  fleet tilt cap, tip-prop axis (11th airframe, derived recovery,
  engine-out busted 14.9× in the open, maintainer-ratified crown),
  vtolwing retrofit (IsrPrime thawed 208.7→200.4 + 6 downstream pins).
- `a448c13` — wave 4: TiltTriWing (wing-shadow download from the
  planform, tilt mechanism mass, centerline cruise engine-out PASS,
  rotatable rotors + tilt slider, tilt-swept interference gate).

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

## Then: the 0.12.0 release train

1. Release-notes agent (commit messages `d47a27a..HEAD` are the source;
   `docs/release-notes.md` follows the 0.11 entry's shape).
2. Version bump — **REMEMBER npm/package.json + the jlpm labextension
   rebuild** (the 0.11 lesson; a parity test catches it on every lane,
   but do it right the first time).
3. `pixi lock` if pyproject changed (the lock pins the local manifest
   hash — twice bitten).
4. CI green on the EXACT commit, then tag, then PyPI (wheel + sdist),
   then the GitHub Release. Demo media decision with the maintainer
   (the grand tour now has the config click, the time seam, the tilt
   slider, and the tip-crown toggle to show off; media stages in
   `~/workplace/longeron-demo-media/`, never enters the repo).

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
  cadquery-gated tests; the pixi default env is the CI-equivalent.
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
- Vendored ipyelk: LOCAL PATCH protocol (currently at patch 14);
  upstream PR #139 is the off-ramp.

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
