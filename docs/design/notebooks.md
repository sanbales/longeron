# Design: the tutorial notebooks, rebuilt as one curriculum

> Status: RATIFIED (2026-08-27) -- the maintainer approved the
> proposal and all five recommendations ("i like your suggestions"):
> two models with the program framing, scoreboard rebased onto the
> fleet model, notation gallery to Reference, two foundations
> notebooks, authoring starts immediately in parallel worktrees.
> LANDING of the renumbered set waits for the v0.11.0 tag (0.11 docs
> keep the old numbering); the rebuild is the 0.12 headline arc.
> Authoring order: T1+T2 and T4+T5 first (no dependency on in-flight
> work); T3 after the inspector/relationships landing; T6 after the
> board clears (it owns the uav_missions scoring edit).

The maintainer's charge, verbatim: *"the tutorial notebooks have grown
organically as we added features. Some things are repetitive, others
are disjointed. Other are not very interesting, some things are too
basic, others are doing a lot of complex things. ... I want examples
that are non-trivial, are interesting, the results are insightful, and
they explain how you can use SysMLv2 as the underlying source of truth
for doing valuable analyses and tying different perspectives to the
data contained in SysMLv2 models."*

## What exists, measured

Fifteen notebooks, 370 cells. Each landed with a feature, so the
sequence narrates the changelog, not a curriculum.

| # | Title | Cells | Model | Diagnosis |
|---|---|---|---|---|
| 01 | Define and explore | 9 | toy inline | Too basic. No payoff visual. |
| 02 | Export and interchange | 10 | toy inline | Plumbing without a motivating question. |
| 03 | Calculations and constraints | 14 | toy `plant` | Sound content, toy subject. |
| 04 | Actions and states | 10 | toy inline | Sound content, toy subject. |
| 05 | Stdlib and validation | 8 | toy inline | Thin. Overlaps `longeron lint` docs. |
| 06 | Interactive diagrams | 25 | drone | Feature tour. Overlaps 11 and 12. |
| 07 | Analysis and trades | 74 | drone + uav_missions | The flagship, and the dumping ground. Five arcs in one file. |
| 08 | Semantic web and RAG | 19 | uav_missions | Good hook, weak tie to the rest. |
| 09 | M0 interpretations | 26 | drone + uav_missions | The deepest concept, buried at #9. |
| 10 | Diagrams meet CAD | 23 | drone | Coherent. Re-explains the selection seam. |
| 11 | Notation gallery | 99 | inline snippets | Reference material, not a tutorial. |
| 12 | Model explorer | 13 | drone + uav_missions | Feature demo. Overlaps 06 and 14. |
| 13 | Requirements scoreboard | 25 | inline `isr_scoring` | Third model family for no reason. Overlaps 07's scoreboard section. |
| 14 | Model app | 15 | drone | Feature demo. Overlaps 12. |
| 15 | Grand tour | 10 | drone + uav_missions | The right capstone. Keep. |

The repetition, named:

- The **selection seam** (tree ↔ diagram ↔ plot ↔ 3D) is explained
  five times: 07, 10, 12, 13, 14.
- The **scoreboard** is taught twice (07 § "From feasible to
  preferred", all of 13) on two different models.
- **Diagrams** are toured three times: 06 (features), 11 (glyphs),
  12 (explorer context).
- **M0** is introduced three times: 09 (concept), 10 (geometry),
  07 (entities across the bridge).
- Notebooks 01–05 spend 51 cells on toy models before the reader sees
  anything a real program would do.

## Principles for the rebuild

0. **Prose follows the writing-documentation skill** (maintainer
   directive). Every markdown cell obeys the skill's contract:
   one claim per sentence, descriptive sentences of at most 25 words,
   active voice with a named actor, one term per concept, no
   intensifiers, topic-sentence-first paragraphs. Authoring agents
   read the skill file in full before writing and run its self-check
   before delivering.

1. **One question per notebook.** Each notebook opens with an
   engineering question and closes with the model answering it. A
   reader who wants feature reference goes to `docs/reference`, not
   to a tutorial.
2. **One source of truth, many perspectives.** The curriculum's spine
   is the maintainer's thesis: the SysML v2 model is the single
   source, and every perspective (diagram, trade study, scoreboard,
   proof, CAD, globe, knowledge graph) is a *view* of that same data.
   Every notebook shows at least one element the reader already met
   in an earlier notebook, rendered in the new perspective.
3. **The payoff is visual and early.** Each notebook shows its hero
   visual within the first ~5 cells (the finished dashboard, the
   painted violation, the globe), then rebuilds it step by step.
   Snapshot capture feeds the docs from the hero cells.
4. **Concepts are taught once, at the moment of need, and
   cross-referenced everywhere else.** The selection seam gets one
   canonical exposition. M0 gets one. Later notebooks link, never
   re-teach.
5. **No toy models after the foundations.** The drone program is the
   subject everywhere: `uav_missions.sysml` (the fleet you trade) and
   `drone.sysml` (the bird you build). Foundations may use small
   excerpts *of the drone*, never a disconnected toy.

## The unified program (ratified 2026-08-28, supersedes Q1's answer)

The maintainer overrode the earlier two-models-with-framing answer:
ONE example replaces the bunch. Four decisions, ratified:

1. **One program, few files** -- a single top-level program split
   across domain files loaded as one workspace, refined by the
   maintainer to the open-closed layout: a file for the GENERIC
   concept and one file per specialization branch, so a future
   concept (tilt-rotor) adds a file without touching the others.
   Layout: parts catalog / abstract aircraft concepts / multirotor
   branch / vtol-wing branch / missions+requirements(+scoring) /
   structural sizing. `analysis_conventions.sysml` stays a library.
2. **One family, both branches** -- the winged VTOL airframes join
   as sibling configurations of the same program (the wing-buys-the-
   loiter lesson survives); the multirotor configurations join the
   dashboard tradespace beside them.
3. **The octocopter is a flat-8 on the same catalog** (8x MT2213 on
   a larger ring, disclaimed as a custom-build convention) -- AND
   the catalog expands to the heavy part class so architecture and
   part-class CROSS: an S1000-class hexa or quad, a big-motor dart,
   coax pairs at either scale. Architecture alone stays one lesson;
   the crossing is the scalability demonstration.
4. **Finish, then tag** -- v0.11.0 waits for the unification, the
   completed T-series, the old-notebook deletion, and the renumber;
   one release whose docs, examples, and demo tell one story.

## The proposed curriculum: 9 tutorials + 1 reference

15 notebooks → 9. Working titles; final names at authoring time.

### Track A — Foundations (2 notebooks, ~25 cells total)

**T1. The model is data** *(merges 01 + 02 + 05)*
The question: what IS a SysML v2 model once longeron parses it?
Parse the drone package; walk the dataclass tree; build a fragment
programmatically; prove JSON round-trips losslessly (parse it back and
keep executing); save/load dispatch; the KerML projection in one cell;
`validate()` and `longeron lint` as the first quality gate. Cut: the
multi-file workspace ceremony (one cell), the ecore aside (docs).

**T2. The model executes** *(merges 03 + 04)*
The question: the drone's datasheet claims a max speed — can the model
compute it? Evaluate expressions with bindings; call the drone's own
calcs (`PropThrust`, `MaxTilt`, `MaxCruiseSpeed`); instantiate;
check constraints with what-if overrides; requirement verdicts with
assumptions gating; then behavior: the mission action graph
(succession-driven, not source-order), the flight state machine,
time triggers. The `plant` toy retires.

### Track B — One truth, many perspectives (6 notebooks)

**T3. Views for review** *(merges 06 + 12 + 14)*
The question: a design review is tomorrow — how do reviewers read
this model without reading text? Structure/state/action/requirement
views from one dispatcher; the toolbar; the explorer (tree ↔ diagram,
relationships as first-class rows); the app sidebar as the no-code
entry (launcher tile, load, tabs, inspect, edit, save/push); saved
views as review artifacts. This notebook owns the **canonical
selection-seam exposition**. The 25+13+15 = 53 source cells compress
to ~30: the three feature tours become one workflow.

**T4. Trades: sizing the fleet** *(07's first arc, trimmed)*
The question: three missions, one airframe family — which bird, and
does any bird do everything? The catalog; requirements as the model
states them; the honest solver choice; the three mission studies with
their distinct physics lessons (the wing buys the loiter; out heavy
back empty; low drag wins the dash); brushing the mission space;
shapes to scale in 3D; the compromise dashboard; continuous sizing
with the N2 map and margins; swapping aerodynamics fidelity via
declared external analyses. Ends by SAVING results into the model —
the source of truth absorbs what analysis learned (the seam T6/T9
reuse).

**T5. Individuals: populations, not possibilities** *(09 + 07's
objects arc)*
The question: the M1 model says `rotor[4]` — but which four, and what
do they weigh TOGETHER? M0 interpretations as the answer: features
read as sequences; roll-ups weigh the individuals that exist (and the
two hand-encodings that disagree prove why M1 build-ups cannot);
nominal vs random; Monte-Carlo over the catalog; traces are
interpretations; a trades architecture is a partial interpretation;
entities and file artifacts across the OpenMDAO bridge. This is the
curriculum's conceptual summit and it now sits where the reader is
ready for it.

**T6. Requirements: score, hunt, prove** *(13 + 07's verify + Z3 arcs)*
The question: the fleet passes its requirements — how good is it
really, and where does it break? MAUT scoreboard (weights, utility
shapes, units — in the model), what-if injection, the trade-study
bridge, linked selection back to T4's studies; then the adversarial
turn: `verify` hunts violations (hunt/sequences/cover/prove — the
shrunk catch, the minimal violating sortie, measured recall, the
proved ceiling), and Z3 answers requirement *consistency*. The inline
`isr_scoring` model retires: the scoreboard scores the fleet model
(scoring attributes fold into `uav_missions.sysml`), so the score and
the violations describe the SAME truth the reader has traded since T4.

**T7. Geometry and the mission** *(10, trimmed)*
*(Maintainer requirement, added 2026-08-28: selecting a
configuration -- or any of its parts -- in the linked views renders
THAT configuration's geometry in the 3D scene. The family arc's
config-keyed geometry API is the enabler; T7 owns the UX.)*
The question: the model claims the camera sees the ground and the
props clear the hull — who measured? M1 vs M0 side by side; the CAD
scene as a rendering of the M0 population; geometric requirements
(view-cone occlusion, disc clearance) with `engine='cad'` exactness;
the violating variant painted where it hurts; the mission on the
globe with model-derived attitude. Trim: the seam re-explanation
(link to T3), the M0 re-introduction (link to T5).

**T8. The knowledge graph** *(08, reframed)*
The question: three questions grep cannot answer about the fleet —
answered in SPARQL over the model's RDF projection; the retrieval
substrate; how an agent consumes the model. Reframed as a
perspective on the same fleet, with at least one query whose answer
the reader can verify against T4's dashboard.

### Capstone

**T9. Grand tour** *(15, unchanged in role)*
One dashboard, every seam: graft a performance branch, measure it,
watch every perspective update. The demo video records this notebook.

### Reference (leaves the tutorial track)

**R1. Notation gallery** *(11, relocated unchanged)*
99 cells of spec-cited glyph coverage is reference material. It moves
to a `Reference` section in the docs toctree (the notebook remains the
snapshot source and stays under test). Tutorial numbering no longer
counts it.

## What this buys

- 15 numbered stops become 9 with a visible arc: *data → execution →
  reading → trading → individuals → judging → geometry → knowledge →
  everything at once*.
- Every overlap named above gets exactly one home.
- Three model families become one program: the fleet and the bird.
  The third (isr_scoring) retires.
- The maintainer's thesis is the spine, stated in T1 and proved by
  T9: the model is the source of truth; perspectives attach to it,
  not to each other.

## Migration mechanics and costs

- `tests/test_notebooks.py` discovers by glob — renumbering is free
  there. Snapshot directories under `docs/_static/widget-snapshots/`
  are keyed by notebook name: rename + one full re-capture per
  affected notebook (browser tier, serialized).
- `docs/tutorials/index.md` toctree, README links, and
  `scripts/record_demo.py` (pins `15_grand_tour.ipynb`) update
  mechanically.
- Old numbering disappears from the repo. Published-docs URLs change;
  0.12 release notes carry the mapping table.
- Authoring is the real cost: T3/T4/T6 are rewrites-with-reuse, not
  moves. Estimate: one focused agent-arc per track (A, B, capstone
  +reference), each landing with tests + captures + docs green.
- Model authoring: scoring attributes fold into `uav_missions.sysml`
  (T6); drone calc names surface in T2. Both are additive edits to
  shipping example models — the rejection/corpus gates do not apply,
  but `examples/` must stay lint-clean.

## Open questions for the maintainer

1. **One program or two models?** T4–T9 stand on `uav_missions` (the
   fleet) + `drone` (the bird), framed as one program: "the fleet you
   trade, the bird you build." The alternative is authoring a single
   unified program model, which is cleaner narrative but a large
   model-authoring project and a rebase of 07's physics.
   *Recommendation:* keep the two models with the explicit program
   framing now; revisit unification only if the seams chafe during
   authoring.
2. **Does the scoreboard rebase onto the fleet model?** T6 assumes
   yes (retire `isr_scoring`, fold scoring into `uav_missions`).
   *Recommendation:* yes — it is the single highest-leverage edit for
   the source-of-truth story.
3. **Where does the notation gallery live?** *Recommendation:* docs
   `Reference` section, notebook retained as snapshot source (R1
   above).
4. **Foundations: one notebook or two?** T1+T2 could compress to one
   ~35-cell notebook. *Recommendation:* two — "the model is data" and
   "the model executes" are different mental models and each deserves
   a clean landing.
5. **Timing.** *Recommendation:* the 0.12 headline arc, immediately
   after v0.11.0 ships; nothing in 0.11 blocks on it.
