# Model-driven requirement-violation hunting (design)

> **Status: adopted 2026-08-27, targeted for 0.11.** This document
> consolidates the adopted decisions and the results of an exploration
> spike into one architecture for
> `longeron.analysis.verify`. The
> experimental helper `src/longeron/analysis/_verify_spike.py` is
> superseded by this design and retires with the implementation
> (retirement plan below). Spike measurements predate the
> drone-example overhaul (`Rotor` → `Motor` + `Propeller`): the
> canHover edge moved from 2.6297 kg to ~2.6865 kg and the exact Z3
> rationals differ, but every qualitative result stands; numbers below
> are quoted from the spike as run.

Goal: find the configurations, event sequences, and architecture mixes
that *break* a model's requirements — automatically, from nothing but
the `.sysml` text — and hand each catch back as a concrete, re-checkable
M0 individual. Longeron's existing analyses show the model answering
questions; `verify` makes the model fight back. Everything a
property-based tester needs is already declared: attribute types give
value domains, `assert constraint` bodies give minable ranges,
`assume`/`require` constraints give the universal property, state
machines give the event alphabet, and variation catalogs give the
discrete factors. The module derives all of it, hunts, shrinks, proves,
and materializes.

## What the spike established

Five experiments, all successful, all against `check_requirement`'s
existing semantics, in about seven seconds of total compute:

| experiment | result |
| --- | --- |
| auto-derived Hypothesis strategies from model asserts | `IsrPrime.loiterSpeed → [11, 24]` mined with zero hand-mapping; shrinking reduced the drone catch to `payloadMass = 1.0` |
| boundary refinement | bisection against the same oracle pinned the canHover edge to 2.629724771 kg, matching the closed form to 1e-9 |
| stateful hunting (`hypothesis.stateful`) | one generic rule (`send(ev)` over the alphabet read from the transitions) + one invariant found — and shrank to — the 4-event minimal sortie `launch, goAround, goAround, goAround` |
| pairwise covering arrays | 100% violation recall on both catalogs vs interpreter-exact exhaustive ground truth: 9/54 rows (TradeQuad, 5/5 constraints), 16/648 (IsrUav, 6/6) |
| Z3 proof tier + M0 materialization | negated requirements gave SAT witnesses and UNSAT absence proofs; `maximize` attributed exact rational bounds (`23/50`, `7166/2725 − ε`) to their binding constraints; every catch materialized as identified individuals (`Drone::QuadCopter#0`) |

Two spike findings shape the architecture more than any success. First,
Z3 immediately found a genuine model gap — `payloadMass = −1.04 kg`,
because no assumption says payload mass is non-negative — a region
sampling over `[0, 5]` would never visit. Sampling and proof are
complements, not competitors. Second, range mining does not reach
through derived attributes (`payloadMass` is only bounded via
`totalMass`), and the fix is not research: `smt.py`'s symbolic-marking
fixed point already computes exactly that reachability, and Z3
`maximize`/`minimize` over the reachable encoding yields provably tight
strategy bounds. That composition — Z3 bounds feeding Hypothesis
strategies — is the single most valuable item in this design.

## Architecture

`verify` is four tiers over one oracle. The oracle is the interpreter:
every verdict, in every tier, comes from `instantiate` + `check` +
`check_requirement` (or `simulate` for sequences), never from a solver's
arithmetic. Solvers *propose*; the interpreter *decides*. This is the
same honesty contract `analysis.trades` already keeps (CP-SAT
enumerates, the interpreter re-verifies exactly), extended to the whole
module.

| tier | engine | question answered |
| --- | --- | --- |
| `hunt` | Hypothesis (sampling + shrinking) | is there a *simple* violating configuration? |
| `sequences` | Hypothesis stateful | is there a *minimal* violating event sequence? |
| `cover` | in-house IPOG-F + Z3 constraints | which discrete mixes violate, at t-way coverage? |
| `prove` | Z3 (via {mod}`longeron.analysis.smt`) | is violation *impossible* — and if not, exactly where? |

### The universal property (normative)

The property every tier tests is *assumptions-hold implies
requirements-satisfied*, and it is already the exact semantics of
{meth}`~longeron.interpreter.Interpreter.check_requirement`: a violated
`assume` constraint makes the requirement inapplicable and
`RequirementResult.satisfied` is `None` — a **vacuous pass, never a
failure**. This is load-bearing and `verify` preserves it normatively:
a configuration is a violation only when every assumption holds and a
`require` constraint (or an `assert constraint` on the subject) is
actually false. Vacuous outcomes are recorded on every report
(`report.vacuous`), because a hunt that found *only* vacuous ground is
telling the user their assumptions fence off the whole search space —
a finding, not a pass.

### Strategy derivation: the domain ladder

Value domains for free attributes are derived from the model, most
specific source wins, every rung recorded on the report so the user
sees what was derived and what fell back:

1. **Attribute types.** `Real`/`Integer`/`Natural`/`Boolean` map to the
   corresponding Hypothesis strategies; `Natural` adds a `≥ 0` floor;
   enum-typed attributes become `sampled_from` over the enumeration's
   literals (spike-verified code path; still needs a shipped model
   where a discrete attribute participates in a constraint).
2. **Direct constraint mining.** `assert constraint` bodies comparing
   the attribute against a literal (either orientation,
   `and`-conjunctions folded) tighten the interval — the spike's
   `_mine_comparison`, carried over as-is.
3. **Z3-derived bounds through the reachability fixed point.** The new
   rung, closing the spike's known gap: where bounds live only on
   *derived* attributes, `smt.py`'s encoding (constant-pinning
   included) is built with the target attribute free, and Z3
   `maximize`/`minimize` under the assumption set yields exact,
   provably tight sampling windows. Where the encoding refuses
   (a free path reaches nonlinear algebra), the refusal is honest and
   recorded, and the ladder falls through.
4. **Declared fallback.** A caller-supplied or documented default range
   (`±1e6` today), flagged as unbounded on the report — never silent.

A fifth rung is *reserved*: the [units design](units.md)'s core tier
derives dimension vectors and scale tags from the vendored SI model;
once that lands, dimensional knowledge can seed scale-aware ranges and
non-negativity for physical quantities (a mass strategy has no business
sampling negative kilograms *unless* the user is hunting for exactly
the missing-assumption gap Z3 found). Unit-aware derivation is out of
scope until the units core tier exists; the ladder is designed so it
slots in as rung 3½ without API change.

### Stateful hunting: machines as they are

`hypothesis.stateful` maps 1:1 onto the interpreter's
{class}`~longeron.interpreter.StateMachine`: the event alphabet is read
from the model's transitions (`accept` triggers, nested states
included), one generic rule sends an arbitrary alphabet event, and one
invariant checks the requirements against the live simulation
environment. Because `StateMachine.send` treats non-matching events as
*ignored* (recorded, not raised), the rule needs no preconditions —
the whole harness is one rule and one invariant, and shrinking strips
every irrelevant event from the reported sequence. Guards, time
triggers (`after`/`at`, driven by clock-advance entries in the event
stream), and parallel regions come for free because the machine under
test is the real one.

### Covering arrays: in-house IPOG-F, Z3 as the constraint engine

Discrete variation spaces too big to enumerate get t-way covering
arrays. The adopted rules:

- **In-house IPOG, F-style greedy** (horizontal growth with the
  near-free don't-care optimization), supporting t = 2..6.
  `allpairspy` was spike-only (t=2, weak constraint handling) and is
  **not** a dependency; NIST ACTS is the reference algorithm family,
  never a dependency; PICT (MIT, single binary, strong constraints)
  is the documented fallback *only if* a subprocess dependency ever
  becomes acceptable.
- **IPOG-D rejected.** Doubling constructions are a generation-time
  tool for hundreds of parameters; longeron's catalogs are dozens of
  factors at most. The implementation documents this ceiling and
  refuses loudly past it rather than degrading quietly.
- **Z3 is the constraint engine.** Candidate rows and tuples are
  checked against the *model's own* constraints through the existing
  `smt.py` encoding — no parallel constraint DSL is invented. Where a
  catalog's constraints do not encode (nonlinear physics), the array
  is generated unconstrained and every row is settled by the
  interpreter anyway, with the unencodable constraints reported as
  gaps.
- **Array-size optimality is explicitly secondary.** One "test
  execution" is one interpreter evaluation at well under a
  millisecond; ACTS's size frugality serves users whose tests cost
  minutes. Correctness of coverage (validated below) matters; a
  half-dozen extra rows do not.

Factors come from {class}`~longeron.analysis.trades.TradeStudy`'s
variation points (homogeneous selection per point, matching trades
today); rows are ordinary selection dicts, evaluated interpreter-exact
via the same path `TradeStudy.evaluate` uses. When the exhaustive space
is small enough to enumerate, the report *measures* recall against
ground truth (the spike's harness); when it is not, the report states
the honest guarantee — every t-tuple covered, violation coverage not
guaranteed — instead of implying more.

### The proof tier

`prove` is a thin orchestration of {mod}`longeron.analysis.smt`: negate
one requirement at a time under the assumption set — SAT yields a
violation witness (re-checked by the interpreter before it is
reported), UNSAT yields a **proof of absence** no amount of sampling
can deliver; `maximize`/`minimize` with selective exclusion attributes
each feasibility bound to the constraint that binds it, as exact
rationals. Encodability is per-query, not per-model — `smt.py`'s
constant pinning means physics upstream of the free variables never
reaches the solver — so `prove` refuses honestly exactly where a free
path reaches nonlinear algebra, and the refusal on the report is the
signal to fall back to `hunt` over the same scope. One prerequisite
lands as its own small fix: the encoder currently drops *anonymous*
`assume` constraints silently (`_Builder.requirement` iterates named
members only, so `FlightEnvelope`'s unnamed assume never reaches the
solver, and no gap is recorded). That is a latent-bug ticket
independent of this design, but `prove` inherits its correctness, so it
lands first.

### Materialization: every catch becomes an individual

Every counterexample closes the loop into M0:
{func}`longeron.m0.interpret` with the violating bindings for
configuration catches, {func}`longeron.m0.from_architecture` for
covering-array rows. The result is an
{class}`~longeron.m0.Interpretation` of identified individuals
(`Drone::QuadCopter#0`, `...motors#2`), re-checkable with the ordinary
`check`/`check_requirement` machinery and ready for the explorer and
the scoreboard. One honest fence carries over from the spike: M0
roll-ups over heterogeneous-capable populations degrade with recorded
gaps where M1 expressions leaned on the homogeneous convention, so
integration surfaces quote trades-exact metrics for headline numbers
and use the interpretation for identity, inspection, and re-checking.

## The public API

House pattern throughout: lazy third-party imports behind
`MissingExtraError`, interpreter-exact re-checks, honest `gaps` and
`vacuous` lists on every result, seeds surfaced everywhere. One shared
report shape keeps the scoreboard/explorer integration to a single
adapter.

```python
from longeron.analysis import verify

# the umbrella: every applicable tier for one scope, one report
report = verify.verify(
    model,
    "Drone::QuadCopter",
    requirements=("Drone::FlightEnvelope",),
    free=("payloadMass",),
    seed=0,
)
report.status  # 'violated' | 'clean' | 'proven'  (proven = UNSAT everywhere encodable)
report.violations  # names of constraints/requirements found false, deduplicated
report.counterexamples  # minimal first; .bindings / .events / .violated / .source
report.proofs  # absence proofs + exact bounds, each attributed to its binding constraint
report.vacuous  # requirements whose assumptions never held during the search
report.domains  # the derivation ladder's outcome per free attribute
report.gaps  # encoder refusals, unbounded domains, degraded roll-ups

# entry points, one per tier
report = verify.hunt(model, part, requirements=reqs, free=("payloadMass",), max_examples=200)
report.boundaries  # bisected edges per free scalar, refined against the oracle

report = verify.sequences(model, "Drone::FlightStates", requirements=reqs, max_steps=20)
report.counterexamples[0].events  # the minimal violating sequence

report = verify.cover(model, "UavMissions::IsrUav", t=2)
report.coverage.rows  # selection dicts, interpreter-evaluated
report.coverage.recall  # measured vs exhaustive when feasible; None otherwise

report = verify.prove(model, part, requirements=reqs, free=("payloadMass",))
report.proofs[0].bound  # exact rational, e.g. '23/50'

# every counterexample materializes
individual = report.counterexamples[0].materialize()  # m0.Interpretation
```

The result types are frozen dataclasses:

```python
@dataclass
class Counterexample:
    bindings: dict[str, Any]  # shrunk scalar bindings (empty for pure sequences)
    events: tuple[str, ...]  # minimal violating sequence (empty for scalar catches)
    violated: tuple[str, ...]  # constraint / requirement names actually false
    source: str  # 'hunt' | 'sequences' | 'cover' | 'prove'
    selection: dict[str, str]  # variant pins (cover catches)

    def materialize(self) -> Interpretation: ...  # m0.interpret / m0.from_architecture


@dataclass
class Proof:
    requirement: str
    status: str  # 'proven-safe' | 'violation' | 'unknown'
    bound: str  # exact rational text when a bound query was asked
    binding_constraint: str  # which assertion the bound is attributed to
```

Semantics worth pinning in the API contract:

- `verify.verify` dispatches by what the scope *is*: a part
  definition/usage runs `hunt` (+ `prove` where encodable); a state
  machine runs `sequences`; an assembly with variation points runs
  `cover`. Tiers that do not apply are skipped silently; tiers that
  apply but cannot run (missing extra, no free attributes) are
  recorded in `gaps`.
- Shrinking's "minimal" is *simplest, not smallest* — the 3.0 kg repro
  vs the 2.6297 kg edge. The API pairs them: `hunt` reports the shrunk
  counterexample and, per free scalar, the bisected boundary
  (`report.boundaries`); `prove` supplies the exact algebraic edge
  where the model encodes. A demo that quotes only the shrunk number
  invites a fair "sloppy" objection; the report carries both so no
  surface has to choose.
- Determinism policy: `derandomize=True`, `database=None`,
  explicit `phases=(generate, shrink)`, seeds accepted and echoed on
  every report. No reliance on the Hypothesis example database, ever —
  reports are reproducible from their own fields.

Dependency posture: `hypothesis` becomes an **optional extra**
`longeron[verify]`, imported lazily (the `MissingExtraError` pattern
{mod}`longeron.analysis.mdao` already uses). Z3 is already available
via the `smt` extra and `cover`/`prove` reach it the same lazy way. The
`verify` extra also lists `z3-solver` (mirroring `smt`) so one extra
lights the full surface; `dev` mirrors it so notebooks execute in CI.
**No `allpairspy`** — the IPOG-F generator is in-house, pure Python,
stdlib-only. No ACTS, no PICT, no Java, no subprocess at runtime.

## Integration

Three surfaces, all adapters over the one report shape:

- **Scoreboard: violations paint red.** A materialized violator is an
  interpretation whose measured values feed
  {func}`~longeron.analysis.scoreboard.scoreboard` as `values=`
  bindings — exactly the existing trade-study bridge
  (`architecture_values`) generalized to counterexamples. A
  requirement driven below its ramp floor renders as the red cell; the
  `step`-shaped default scores 0 the moment `check_requirement` fails.
  No scoreboard change is required beyond a small
  `counterexample_values(ce)` helper in `verify`.
- **Notebook 07 gains a "find my violations" beat** (0.11 scope).
  The beat is one cell: `verify.verify` over the drone
  scope, the shrunk catch, the exact edge from `prove`, and the
  materialized individual repainting the scoreboard red. The whole
  beat runs on the same `.sysml` file, untouched, from
  strategy ranges to a red cell in under ten seconds of compute.
- **Trades: covering arrays as the case source.** `cover` consumes
  `TradeStudy`'s variation points and emits selection dicts — the same
  currency `TradeStudy.evaluate`, `m0.from_architecture`, and the
  scoreboard already speak. The sibling mdao-objects design (0.11
  item 1, `docs/design/mdao-objects.md`, queued) will consume
  exactly this: covering-array rows as the discrete-case source for
  OpenMDAO discrete entities, so the two designs meet at
  `report.coverage.rows` and neither invents a second case format.

## Validation plan

The covering-array generator is validated **without** an ACTS
dependency, by a three-layer scheme:

1. **Self-validating coverage checker, in CI.** For every emitted
   array: (a) every valid t-tuple is covered, where "valid" is
   Z3-decidable — the tuple extends to at least one full
   constraint-satisfying row; (b) every emitted row is itself Z3-valid
   against the model's constraints. The checker is independent code
   from the generator (tuple enumeration + set cover, not IPOG), so a
   generator bug cannot hide behind its own arithmetic.
2. **Hypothesis property-tests the generator** on random catalogs —
   random factor counts, level counts, and constraint densities — the
   verify machinery testing itself: coverage holds, rows validate,
   the documented parameter ceiling refuses as specified.
3. **ACTS jar / PICT as one-time dev size benchmarks only**, against
   published IPOG tables (TCAS and the standard mixed-level
   benchmarks), with the resulting size comparison recorded in this
   document at implementation time — never a runtime or CI dependency.

The hunt/sequences tiers reuse the spike's recall harness where
exhaustive ground truth stays feasible (`all_architectures` for
catalogs, closed-form edges for boundaries), and pin the vacuous-pass
semantics with direct interpreter-level tests.

## Performance budget

Spike-measured, on the drone and ISR sizing models (Apple Silicon dev
box, single process):

- one `instantiate` + `check` + `check_requirement` cycle: **well
  under 1 ms**, including the UAV model's real `pow`/`sqrt` physics;
- a 200-example hunt including shrinking: **~0.1 s**;
- the full five-experiment spike notebook: **~7 s** end to end;
- covering arrays at catalog scale (9 and 16 rows): generation and
  evaluation both trivially fast; the interpreter-exact re-check *is*
  the cost model, which is why array-size frugality was ruled
  secondary.

Defaults are budgeted to those numbers: `max_examples=200` (hunt),
`max_examples=100, max_steps=20` (sequences), derandomized. A default
`verify.verify` call on a flagship-sized model stays interactive
(seconds, not minutes). Nothing in `verify` runs per-evaluation work
beyond the interpreter call itself; strategy derivation, Z3 bound
queries, and array generation are per-report, not per-example.

## What we deliberately do not build

- **No ACTS, no PICT, no Java at runtime or in CI** — dev-time size
  benchmarks only, recorded here once.
- **No test-code generation and no test-runner packaging.** `verify`
  is a library shape, not a process shape: no pytest plugin, no
  generated test files, no CI-gating semantics. That is a later,
  separate concern.
- **No coercion of vacuous passes.** Assumption violations stay
  vacuous, reported as such; `verify` never "helpfully" counts them as
  failures or silently drops them.
- **No unit-aware strategy derivation yet** — reserved rung, blocked
  on the units core tier landing.
- **No per-index heterogeneous covering arrays** — factors follow
  trades' homogeneous-selection convention; heterogeneity is the
  trades phase-2 item and lands there first.
- **No Z3 encoding of state machines.** Bounded model checking is a
  different design; sequences are hunted, not proven.
- **No IPOG-D**, and no silent degradation past the documented
  parameter ceiling — refuse loudly.

## Retiring `_verify_spike.py`

The experimental helper ships in 0.10 with a prototype warning and no
public export; it retires in the same change that lands `verify`:

1. `hunt`, `verdict`, `Domain`/`attribute_domains`/`strategies_for`,
   `bisect_boundary`, and `events_of` migrate into the new module —
   the mining and verdict logic carry over nearly verbatim (they are
   the spike's *validated* core), re-homed behind the public API and
   under tests.
2. `src/longeron/analysis/_verify_spike.py` is deleted. No deprecation
   cycle: it was never exported from `longeron.analysis`, never
   documented, and its docstring promised exactly this fate.
3. After 0.11, `pip install "longeron[verify,smt]"` installs
   everything needed to reproduce the spike measurements.

## Decisions

All six were adopted on 2026-08-27. The implementation treats them as
settled.

1. **Extras layout: `[verify]` is compositional.**
   `verify = ["hypothesis>=6.100", "longeron[smt]"]` reuses smt's z3
   pin, alongside new composite extras `analysis = ["longeron[mdao,
   trades,smt,viz]"]`, `ui = ["longeron[explorer,replay,viz]"]`, and
   `all = ["longeron[analysis,ui,verify,rdf,client,server,ecore]"]`;
   `[cad]` is deliberately excluded from `all` (the ~1 GB OCC kernel
   stays an explicit opt-in). One extra lights the whole surface, and
   a hypothesis-only install still works for the sampling tiers via
   the lazy-import seam.
2. **The "find my violations" beat lands in notebook 07.** It is the
   analysis tutorial and absorbs a new section cheaply; the grand tour
   is a choreographed dashboard whose re-cut is expensive, and it can
   gain a verdict-strip red-cell moment later without re-recording the
   narrative.
3. **The drone example gains a genuinely sequence-sensitive
   requirement** (a go-around path that re-enters `airborne` past the
   launch guard's battery floor), so the flagship demo runs end to end
   on shipped examples only. Without it, the minimal-sortie catch
   needs a planted vulnerable model — the stock machines only count
   launches monotonically.
4. **`cover` defaults to `t=2`**, with the measured-recall report when
   exhaustive enumeration is feasible; users raise `t` explicitly.
   Pairwise found 6/6 at 16/648 on the spike; higher strength is a
   knob, not a default.
5. **The anonymous-`assume` encoder fix blocks `prove` only.** It
   lands as its own small ticket before `prove` merges (record a gap
   at minimum, encode the body ideally), since a silently dropped
   assumption turns an honest UNSAT into a false "proven". The other
   tiers do not wait for it.
6. **Module layout: one module.** `verify.py` starts beside
   `smt.py`/`trades.py` (the house pattern); the IPOG generator splits
   into a private `_ipog.py` sibling if it crosses ~300 lines, keeping
   the public namespace flat.

## References

- Longeron surfaces: {mod}`longeron.interpreter`
  (`check_requirement`, `StateMachine`), {mod}`longeron.m0`,
  {mod}`longeron.analysis.smt`, {mod}`longeron.analysis.trades`,
  {mod}`longeron.analysis.scoreboard`.
- Sibling designs: [units](units.md) (the reserved dimensional-bounds
  rung), [M0 interpretations](m0-interpretations.md) (identity and
  roll-up semantics), and the queued mdao-objects design (0.11 item 1,
  consumer of `cover`'s rows).
- External: Hypothesis (property-based testing, stateful testing,
  shrinking); Z3 (`Optimize`, unsat cores); Lei et al., "IPOG: A
  General Strategy for T-Way Software Testing" (the IPOG/IPOG-F
  family); NIST ACTS and Microsoft PICT as reference implementations,
  not dependencies.
