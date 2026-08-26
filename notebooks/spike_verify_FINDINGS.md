# Findings: model-driven requirement-violation hunting (spike)

> **Status: exploration spike, 2026-08-26.** Companion to
> `notebooks/spike_verify.ipynb` (executed outputs committed
> deliberately) and the experimental helper
> `src/longeron/analysis/_verify_spike.py`. Nothing here is wired into
> docs, tutorials, or tests. Seed:
> `.handoff/merge-queue-2026-08-25.md`, "FUTURE DESIGN SEED ...
> violation hunting".
>
> **Staleness note (drone-example overhaul, 2026-08-26):** the drone
> model has since split its lumped `Rotor` into `Motor` + `Propeller`
> with a real thrust parametric (`PropThrust`). The committed spike
> outputs and the numbers below reflect the OLD model: the canHover
> edge moved from 2.6297 kg to ~2.6865 kg (thrust 36.0 -> 36.56 N),
> `rotors` is now `motors`/`propellers`, and the exact Z3 rationals
> differ. The all-constraints payload bound (0.46 kg, takeoffMassLimit)
> is unchanged. Re-run the spike notebook to regenerate.

## Reproduction

The spike needs `hypothesis` and `allpairspy`, which are not project
dependencies. The scratch venv lives under the worktree and is
gitignored:

```bash
uv venv build/spikeenv --python 3.13
uv pip install --python build/spikeenv/bin/python \
    hypothesis allpairspy z3-solver antlr4-python3-runtime==4.13.2 \
    nbformat nbclient ipykernel
PYTHONPATH=$PWD/src build/spikeenv/bin/python -m nbclient  # or re-run cells
```

The notebook executes in about 7 seconds end to end. Every Hypothesis
run uses `derandomize=True`, `database=None`, and `max_examples<=200`.

## What worked

1. **The universal property costs nothing to state.** The property
   "assumptions hold implies requirements satisfied" is already the
   exact semantics of `check_requirement`. `RequirementResult.satisfied
   is None` (a violated assumption) is a vacuous pass, never a failure.
   The helper's `verdict()` preserves that distinction and records
   vacuous requirements separately.
2. **Hunting is fast.** One `instantiate` + `check` + `check_requirement`
   cycle on the drone runs in well under a millisecond. A 200-example
   hunt with shrinking finishes in ~0.1 s, including on the UAV model
   whose attribute chain runs real `pow`/`sqrt` physics.
3. **Shrinking produces the pitchable artifact.** Hypothesis shrinks the
   drone catch to `payloadMass = 1.0` and the sortie catch to the
   4-event sequence `launch, goAround, goAround, goAround`. The shrunk
   example is the *simplest* violator, not the tightest. Where the edge
   matters, `bisect_boundary` refines it against the same oracle
   (canHover edge: 2.629724771 kg, matching the closed form to 1e-9).
4. **Stateful hunting maps 1:1 onto the interpreter.** One generic rule
   (`send(ev)` over the alphabet read from the model's transitions) plus
   one invariant (requirement check against the live simulation
   environment) is the whole harness. `StateMachine.send` treats
   non-matching events as ignored, so the rule needs no preconditions.
   Shrinking strips every irrelevant event from the reported sequence.
5. **Pairwise recall was 100% on both catalogs.** Measured against the
   interpreter-exact exhaustive ground truth (`all_architectures`):
   TradeQuad 9 pairwise rows vs 54 exhaustive found 5/5 violated
   constraints; IsrUav 16 rows vs 648 found 6/6. The caveat stands:
   pairwise guarantees pair coverage, not violation coverage, and the
   recall number is only measurable while exhaustive stays feasible.
6. **Z3 complements rather than competes.** `maximize` with selective
   exclusion attributes each feasibility bound to the constraint that
   binds it, as exact rationals (`23/50`, `24494/24525`,
   `7166/2725 - epsilon` for the strict inequality). Negating one
   requirement gives violation existence (SAT with witness) or a proof
   of absence (UNSAT) that no amount of sampling can deliver.
7. **M0 materialization closes the loop.** `m0.interpret(...,
   bindings=counterexample)` and `m0.from_architecture(study, bad_mix)`
   turn catches into identified individuals (`Drone::QuadCopter#0`,
   `...rotors#2`), re-checkable with the ordinary `check` /
   `check_requirement` machinery and ready for the explorer/scoreboard.

## What surprised

1. **Z3 found a genuine model gap immediately.** The first SAT witness
   on the quad was `payloadMass = -1.04 kg`: the model never assumes
   payload mass is non-negative. Sampling over `[0, 5]` would never
   have looked there. (The companion `totalMass = 0` witness also
   exploits Z3's total real division at zero inside the inlined
   `ThrustToWeight` calc.)
2. **Encodability is per-query, not per-model.** `smt.py`'s
   constant-pinning means the ISR sizing context (`pow`/`sqrt`
   throughout) is *fully encodable* when `loiterSpeed` is free (the
   physics sits upstream and is pinned), yet refuses honestly when
   `emptyMassKg` is free (the hover-power `pow` chain then depends on
   the variable). "Nonlinear model" is the wrong dividing line; "does a
   free path reach nonlinear algebra" is the right one, and the tool
   already computes it.
3. **A latent tool bug: anonymous `assume` constraints are silently
   dropped by the SMT encoder.** `_Builder.requirement` iterates
   `named_members(...)`, which requires a name; `FlightEnvelope`'s
   `assume constraint { drone.totalMass > 0.0 }` therefore never
   reaches the solver, and no gap is recorded. The interpreter checks
   unnamed constraints fine (`check_requirement` walks `members_of`
   directly). Worth a ticket independent of this spike: at minimum the
   encoder should record a gap for unnamed constraint bodies.
4. **Shrinking's "minimal" is simplest, not smallest.** The canHover
   hunt shrinks to 3.0 kg although the true edge is 2.6297 kg.
   This is a feature (3.0 is the debuggable repro) but the demo must
   pair it with bisection or Z3, or a reviewer will call the number
   sloppy. The notebook does exactly that pairing.

## What failed, or degraded honestly

1. **Range mining does not reach through derived attributes.**
   `payloadMass` has no direct comparison against a literal anywhere;
   every bound lives on `totalMass`, which derives from it. The miner
   returns UNBOUNDED and the hunt falls back to a caller-supplied
   range. The fix is known and already prototyped: `smt.py`'s
   symbolic-marking fixed point computes exactly this reachability, and
   Z3 `maximize` over the reachable set can *derive* the tight strategy
   bounds for the sampler. That composition (Z3 bounds feeding
   Hypothesis strategies) is the single most valuable design-doc item.
2. **M0 roll-ups over heterogeneous-capable populations degrade where
   M1 leaned on the homogeneous convention.** `from_architecture` on
   the violating ISR mix records 4 gaps (`missionMass: cannot apply '+'
   to None...`) because M1 expressions read `motors.mass` as a scalar.
   Documented behavior (`m0.py` docstring), and `rollup("sum(motors.
   mass)")` works over the real individuals. The demo uses the
   trades-exact metrics for the red number instead.
3. **The stock models contain no sequence-violable behavior.**
   `FlightStates` only counts launches monotonically. The stateful demo
   therefore plants a spike-local vulnerable model (a go-around path
   that re-enters `airborne` and skips the launch guard's battery
   floor). This is honest about today's examples and also a note for
   the demo roadmap: the drone-example overhaul could add one genuinely
   sequence-sensitive requirement so the flagship demo needs no plant.
4. **Enum-strategy derivation is untested beyond the code path.** The
   drone's `FlightMode` enum never participates in a constraint, so the
   enum branch in `strategies_for` ran but proved nothing. Fine for a
   spike; a real `verify` needs a model where a discrete attribute
   matters.

## Auto-derivation feasibility

How far the spike got, concretely:

| input | derived | status |
| --- | --- | --- |
| attribute types (`Real`/`Integer`/`Natural`/`Boolean`) | value strategies | works (`strategies_for`) |
| enum-typed attributes | `sampled_from` over literals | code path exists, no demo model |
| `assert constraint` bodies comparing the attribute to a literal (both orientations, `and`-conjunctions) | float/int bounds | works; `IsrPrime.loiterSpeed -> [11, 24]` with zero hand-mapping |
| bounds reachable only through derived attributes | -- | missing; the known gap |
| unit dimensions (`docs/design/units.md`) | typed magnitudes / scale-aware ranges | not attempted; units are annotations today |
| state machine transitions | event alphabet for stateful rules | works (`events_of`, nested states included) |
| multiplicity ranges | population-size strategies | not attempted (m0's random strategy already samples these) |

The missing reachability pass is not research; it is the same fixed
point `smt.py` runs today, followed by either (a) interval propagation
over the expression AST, or (b) letting Z3 `maximize`/`minimize` each
free attribute under the assumption set and using the resulting exact
bounds as strategy ranges. Option (b) is ~30 lines on top of what
exists and gives *provably tight* sampling windows wherever the algebra
encodes. Where it refuses, fall back to declared fallback ranges.

## API sketch for `longeron.analysis.verify`

Follows the house pattern: lazy third-party imports behind a
`MissingExtraError` (`verify` extra = `hypothesis`, reusing `allpairspy`
or an in-house IPOG for arrays), interpreter-exact re-checks, honest
`gaps`/`refusals` lists on every result.

```python
from longeron.analysis import verify

# 1. sampling + shrinking (Hypothesis; strategies derived from the model)
report = verify.hunt(
    model,
    "Drone::QuadCopter",
    requirements=("Drone::FlightEnvelope",),
    free=("payloadMass",),  # domains auto-derived; kwargs override
    max_examples=200,
    seed=0,
)
report.counterexamples[0].bindings  # shrunk, minimal
report.counterexamples[0].violated  # constraint / requirement names
report.boundaries  # bisected edges per free scalar
report.domains  # what was derived, what fell back

# 2. adversarial event sequences (hypothesis.stateful)
report = verify.sequences(
    model,
    "Drone::FlightStates",
    requirements=("Drone::SafeOps",),
    max_examples=100,
    max_steps=20,
)
report.counterexamples[0].events  # minimal violating sequence

# 3. covering arrays over variation catalogs (pairwise now, t-way later)
report = verify.pairwise(model, "UavMissions::IsrUav")  # or t=3 ...
report.recall  # vs exhaustive, when feasible; else None

# 4. proof where encodable (wraps analysis.smt; refusals recorded)
report = verify.prove(
    model,
    "Drone::QuadCopter",
    requirements=("Drone::FlightEnvelope",),
    free=("payloadMass",),
)
report.status  # 'violation' | 'proven-safe' | 'unknown'
report.bounds  # exact rationals per binding constraint

# every counterexample materializes
individual = report.counterexamples[0].materialize()  # m0.Interpretation
```

One shared result shape (`VerifyReport` with `counterexamples`,
`vacuous`, `gaps`, `stats`) keeps the scoreboard/explorer integration to
a single adapter.

## Recommended design-doc scope (0.11)

In scope:

1. `verify.hunt` + `verify.sequences` on Hypothesis, with the
   domain-derivation ladder: types -> direct constraint mining ->
   Z3-derived bounds through the reachability fixed point (the smt.py
   composition). Vacuous-pass semantics stated normatively.
2. `verify.pairwise` with measured-recall reporting when exhaustive
   ground truth is feasible, silent-guarantee honesty when not.
   Decision item: `allpairspy` dependency (pairwise only, GPL-clean
   MIT, tiny) vs in-house IPOG (enables t>=3; NIST ACTS is the
   reference, not a dependency).
3. `verify.prove` as a thin orchestration of `analysis.smt` (negated
   requirements, exclusion sets, bounds attribution) -- plus the
   unnamed-constraint encoder fix, which should land as its own small
   bug ticket regardless.
4. Counterexample materialization to M0 and a scoreboard hook (a
   materialized violator shows as a red interpretation).
5. Determinism policy: seeds surfaced in every report, derandomize
   defaults, no reliance on the Hypothesis example database.

Out of scope (deliberately):

- unit-aware strategy derivation (blocks on the units design's core
  tier landing);
- heterogeneous per-index variant selection in covering arrays (matches
  the trades phase-2 item);
- CI integration / test-runner packaging of hunts (a later, separate
  concern -- the spike shows the library shape, not the process shape);
- any attempt to encode state machines for Z3 (bounded model checking
  is a different design).

## Demo-value assessment

Yes -- this is flagship material, with one caveat. The strongest single
demo longeron has today (notebook 07's trade study) shows the model
*answering questions*; this spike shows the model *fighting back*: the
same `.sysml` file, untouched, yields the strategy ranges, the property,
the event alphabet, the discrete test plan, the exact algebraic bounds,
and finally the concrete individual that breaks the requirement. The
arc of the notebook -- sample, shrink, bisect, prove, materialize, all
against `check_requirement`'s existing semantics in under ten seconds
of compute -- is a story no mainstream SysML tool tells, and it
composes five existing longeron subsystems (interpreter, m0, trades,
smt, and now hypothesis) rather than bolting on a verifier.

The caveat: the stock examples are one planted bug short of perfect.
The quad's violations are parameter-sweep findable (a skeptic will say
"I could have plotted that"); the sequence hunt -- the most impressive
catch -- currently needs the spike-local vulnerable model. Landing one
sequence-sensitive requirement in the drone-example overhaul (already
queued) would let the flagship demo run end to end on shipped examples
only. With that, this is the demonstration to lead with.
