# Object-valued analysis I/O in the OpenMDAO bridge (design)

> **Status: proposed.** The direction is ratified -- OpenMDAO's
> discrete-variable machinery is the native object pipe, no fork -- and
> this document elaborates it. All empirical claims were verified
> against the worktree at `e64f9f9` (longeron 0.10.0) and the installed
> OpenMDAO 3.45.0; each claim says which. Two open questions
> (optionality, result lifecycle) are the load-bearing decisions and
> carry recommendations below.

Goal: let objects -- not just scalars -- cross the OpenMDAO bridge. The
maintainer's two motivating cases:

1. **Discrete entities.** "It is easy to define cases by parameter
   combinations, but if we have discrete combinations of things, it
   would be nice to pass an entity (e.g., a motor that has specific
   weight, Kt, Kv...) and have the OpenMDAO module take that."
2. **Object handoff.** "A component that makes a 3D geometry and
   another that takes it (RCS analysis, or CFD/FEA) -- write to file
   and pass the path? serialize?"

And the integration question behind both: how does this compose with
longeron's SysML v2 constructs, so the wiring is *derivable from the
model* rather than hand-assembled in Python?

## The central identity: a case is an interpretation

The design's organizing idea comes from longeron's own M0 layer
([M0 interpretations](m0-interpretations.md)): the M1 model is the
*space of possibilities*; an OpenMDAO evaluation is always a *point* in
that space; and a point in that space already has a name in longeron --
an **M0 interpretation** ({func}`longeron.m0.interpret`, `m0.py`
l. 227). A DOE or covering-array run is then a *population* of
interpretations. Everything below is that identity, applied:

- A **discrete case** (motor A × prop B) *is* an interpretation with
  its variation points pinned -- `m0.interpret(model, part,
  selection={"motor": "at2814"})`. A trades
  {class}`~longeron.analysis.trades.Architecture` is already a
  proto-interpretation ({func}`~longeron.m0.from_architecture`, `m0.py`
  l. 453), and the verify spike's counterexample configurations are the
  same currency, one `interpret(bindings=...)` away. One currency
  across trades, verify, and mdao.
- **Entity binding** (tier 1) passes the *individual* -- the
  `m0.Individual` with its resolved attribute values -- not the raw M1
  usage. The M1 usage is the whole space; the individual is the point.
- **Geometry flowing between components** (tier 2) is *M0-keyed*:
  {func}`~longeron.analysis.grand.drone_scene` (`grand.py` l. 131)
  already stamps every rendered part with its individual id
  (`Drone::QuadCopter#0.motors#2`), and that id is the join key that
  says which sub-mesh belongs to which configured individual in a
  downstream RCS/CFD component.
- **Results land on the interpretation** (below): OM outputs become
  attribute values on the case's individuals -- stable ids for
  recording, traceability from an output back to the exact configured
  individual that produced it, roll-ups over populations, and a direct
  `values=` feed into the scoreboard.

The tension this creates -- continuous-sweep users must not pay M0
ceremony -- is the design's first open question; the short answer is
that the light path materializes one implicit anonymous interpretation
and never mentions it.

## The native boundary: what OpenMDAO provides (verified)

OpenMDAO has carried object-valued variables since 2.5:
`add_discrete_input` / `add_discrete_output` declare them, `connect()`
and promotion wire them, and `compute()` receives them in separate
`discrete_inputs` / `discrete_outputs` dicts. Every behavior below was
verified against the installed 3.45.0 with throwaway single-process
Problems (dict-valued `motor` and `mesh` payloads); line numbers are
from the installed package.

| behavior | verdict | evidence |
| --- | --- | --- |
| declare + promote + explicit `connect()` of dict-valued discretes | works | probes A1/A3 |
| `get_val`/`set_val` with raw dicts (rebinding between runs) | works | probes A2/A4 |
| `compute_totals` over continuous vars with discretes present | works -- FD partials simply skip discretes | probe B1 |
| `compute_totals` wrt a discrete | fails with an opaque `KeyError: '_auto_ivc.v0'` | probe B2 |
| discrete design var under `ScipyOptimizeDriver` | rejected cleanly at `final_setup`: "Discrete design variables are not supported by this driver" (`driver.py` l. 530, gated on `supports['integer_design_vars']`) | probe B3 |
| SLSQP over continuous desvars *with* discretes in the model | converges normally -- the two-loop pattern (discrete case outside, gradient opt inside) works today | probe J1 |
| `DOEDriver` with a discrete desvar + `ListGenerator` of dicts | works; each case records and reads back the full dict (`doe_driver.py` l. 63 sets `supports['integer_design_vars'] = True`) | probe D1 |
| discrete↔continuous connection | rejected with a clear `TypeError` | probe E1 |
| discrete↔discrete value compatibility | checked at setup by `isinstance` in either direction on the *declared defaults* (`conn_graph.py` l. 85); a `val=None` default is incompatible with everything | probes E2/I1 |
| `IndepVarComp.add_discrete_output` | works -- the bridge's existing `consts` IVC pattern extends to entities | probe K2 |
| `list_inputs`/`list_outputs` include discretes | works -- the external-binding contract validation (`_component_io`) extends for free | probe K1 |
| serial discrete transfer | **by reference, not copy** -- the source comment is explicit that a downstream mutation is visible upstream (`group.py` l. 2066) | source |
| MPI discrete transfer | values move through `comm.gather`/broadcast -- i.e. mpi4py *pickles* them (`group.py`, MPI branch of `_discrete_transfer`) | source; MPI run not exercised |
| recorder + discretes | recorded, but see the recorder section: JSON-text storage, silent lossy degradation for non-JSON objects | probes C/F/G/K3 |

The OM documentation's own claims (discrete variables page) match what
we verified; the reference-aliasing and class-name-degradation
behaviors below are *not* documented and were established from source
and probes. `ExternalCodeComp` (`external_code_comp.py` l. 234) is
file-based by contract: `command`, `external_input_files`,
`external_output_files` options (l. 41-56) -- the file boundary in
tier 3 is what it already expects.

## What longeron supports today (gap analysis)

Every row was established empirically: spec-shaped samples parsed with
`longeron.loads()`, instantiated, pushed through
{func}`~longeron.analysis.mdao.build_problem`, and validated.

| construct | grammar / model layer | `to_sysml` | interpreter | mdao bridge | `validate` |
| --- | --- | --- | --- | --- | --- |
| `item def` + attributes | full (`ItemDefinition` per the vendored ecore) | fixpoint | nested `Instance` with value slots | **scalar-shredded**: `motor.mass`, `motor.kv`, `motor.kt` become separate independents; entity identity lost | clean |
| `variation` def + `variant` members (part *or* item) | full | fixpoint | first variant only; unpinned slots `None` | **fails opaquely**: `EvaluationError: cannot apply '*' to 4.0 and None` -- no seam to select a variant | no diagnostic |
| variant with inline redefinitions (`variant item x : Motor { :>> mass = ... }`) | full | fixpoint | -- | trades `VariationPoint` bundle comes back **empty** (`trades.py` l. 397 instantiates the variant's *type*, dropping body redefinitions) | no diagnostic |
| `action def` with typed `in`/`out` parameters | full (direction + types survive) | fixpoint | ignored | **silently ignored** -- not even a `gaps` entry | clean |
| `flow of Mesh from build.mesh to rcs.mesh` | full: `FlowUsage(payload, source, target_end)` (`model.py` l. 606) | fixpoint | ignored | **silently ignored** | **zero diagnostics even when both endpoints and the payload type dangle** |
| `m0.interpret(..., selection=)` over a variation point | -- | -- | works: pins variants, resolves values, `gaps == []` | not consumed | -- |
| `Interpreter.instantiate(defn, motor=individual)` | -- | -- | works: entity override evaluates derived attributes correctly | no `bindings` seam in `build_problem` (l. 555) | -- |

Flow endpoints deserve emphasis because tier 4 stands on them: the
model layer stores `source='build.mesh'`, `target_end='rcs.mesh'`,
`payload='MeshModel'` as **verbatim strings** -- parsed, exported at a
fixpoint, never resolved by the `Resolver`, never validated. This
sample produces zero diagnostics today:

```sysml
part def Sys {
    action a { out mesh : Mesh; }
    action b { in mesh : Mesh; }
    flow of Mesh from a.mesh to nonexistent.pin;   // dangles silently
}
```

The five most consequential findings:

1. **The pipe already exists and is sufficient.** Discrete
   declaration, connection, promotion, setup-time type checking, DOE
   enumeration over dict-valued design variables, clean rejection by
   gradient drivers, and case recording all work in stock OpenMDAO.
   No fork, no subclassing of OM internals -- tiers 1-3 are
   conventions over an existing mechanism.
2. **The recorder is the trap, not the pipe.** `SqliteRecorder` stores
   iteration data as *JSON text* (`sqlite_recorder.py` l. 476): a
   2.4 MB mesh became ~6 MB of JSON *per iteration* (30 MB for five
   `run_model` calls), and any non-JSON-native object silently
   degrades through `make_serializable` (`general_utils.py` l. 772) to
   `o.to_json()` if it exists, else **its class name as a string** --
   a recorded `Recipe()` reads back as `'Recipe'`, no warning. The
   `to_json` hook is the lossless seam tiers 1 and 3 exploit.
3. **Aliasing and pickling are the two transfer regimes.** In serial,
   OM passes discrete values *by reference* (`group.py` l. 2066 --
   deliberate, per the source comment), so a downstream component
   mutating a received mesh corrupts its upstream producer. Under MPI,
   values cross ranks through `comm.gather` -- pickled. The
   recipes-not-solids rule and the frozen-payload convention below are
   load-bearing, not stylistic.
4. **Longeron already parses everything tier 4 needs, and all of it
   evaporates before analysis.** Item defs, typed action parameters,
   and flows survive to the model layer at a `to_sysml` fixpoint --
   then the bridge scalar-shreds item members, silently drops actions
   and flows, fails opaquely on variation points, and validation says
   nothing about dangling flow endpoints.
5. **M0 is the missing currency, and it already works.**
   `m0.interpret(selection=...)` materializes exactly the case
   `build_problem` chokes on (verified: `gaps == []`, correct derived
   values). `Individual`s pickle (3-22 KB -- they drag a copy of the
   reachable M1 graph; acceptable per-case, wasteful per-mesh),
   `rollup()` aggregates over populations, `Instance.set()` writes
   results back, `to_dict()` is JSON-clean, and `drone_scene` already
   keys meshes by individual id.

## Tier 1: entity binding

A variation-typed (or designated item-typed) member becomes **one
discrete input** carrying the whole entity, instead of today's scalar
shred. The bound value is the **M0 individual** -- resolved attribute
values, stable id, definition backlink -- not the M1 usage:

```python
# mdao.py additions (sketch; signatures illustrative)
def build_problem(
    model: M.Model,
    part: str | M.Definition | M.Usage,
    requirements: tuple[str, ...] = (),
    setup: bool = True,
    fidelity: Mapping[str, str] | None = None,
    interpretation: Interpretation | None = None,  # the case being evaluated
) -> ProblemBuild: ...


def bind_entity(build: ProblemBuild, feature: str, entity: str | Instance) -> None:
    """Rebind a variation point to an individual (qname resolved via the interpreter)."""


def entity_cases(study: TradeStudy, *points: str) -> list[list[tuple[str, Any]]]:
    """DOE cases over the catalog: one case per mix, values are individuals."""
```

Mechanics, reusing the bridge's existing patterns:

- `build_problem(..., interpretation=itp)` builds the Problem *around
  a point*: free scalars seed from the interpretation's slots exactly
  as they seed from `instantiate()` today (`mdao.py` l. 589), and each
  entity member becomes an `add_discrete_output` on the group's
  existing `consts` `IndepVarComp` (probe K2) with the individual as
  its value. `ProblemBuild` gains `entities: dict[str, str]` (promoted
  name -> item/part def qname) and `interpretation`.
- An expression component whose value references `motor.mass` declares
  `add_discrete_input("motor")` and reads `.get("mass")` in
  `compute()` -- the floats-only invariant of the
  [units design](units.md) holds, because slot *leaves* stay floats.
- Rebinding between cases is `problem.set_val("motor", individual)`
  (probe A4); `bind_entity` adds qname resolution and a conformance
  check of the individual's definition against the variation point's
  base type.
- The **trades machinery is the discrete-case source**:
  `entity_cases(study)` walks `TradeStudy.points` (`trades.py` l. 376
  already collects both `part`- and `item`-typed variation points) and
  yields `om.ListGenerator`-shaped cases whose values are
  `from_architecture`-style individuals. `DOEDriver` accepts them as
  discrete design variables and records each mix (probe D1). The
  verify design's covering arrays slot in later as another generator
  of the same currency: a population of interpretations.
- Gradient safety needs no work: discrete desvars are rejected by
  gradient drivers with a clear error (probe B3), and the supported
  pattern -- discrete case outside, SLSQP over continuous variables
  inside -- runs today (probe J1).

## Tier 2: object flow

Geometry (and any other structured payload) moves between components
as discrete values. Two conventions, both forced by finding 3:

- **Pass recipes, not kernel objects.** A cadquery/OCC solid is a
  live CFFI handle -- unpicklable, unrecordable, meaningless on
  another rank. The payload is the *recipe* (the parameter dict
  {func}`~longeron.analysis.geometry.to_cadquery` already rebuilds
  from) or the baked *mesh dict* (`{"unit", "parts", "bounds"}`,
  plain lists -- `geometry.py`'s existing currency). Workers rebuild
  solids locally from recipes.
- **Payloads are frozen by convention.** Serial OM aliases discrete
  values across components; a consumer must never mutate a received
  payload. The bridge documents this and the mesh convention keeps
  producer output and consumer input distinguishable by construction
  (producers always emit a fresh dict).

Payload parts carry their **M0 individual id** in the existing `key`
slot ({func}`~longeron.analysis.geometry.tag_parts`), so a downstream
RCS/CFD component can attribute per-part results -- and the results
tier can land them -- on the exact individuals that produced the
geometry. Analysis components consuming entity + emitting payload
compose with tier 1:

```python
class BuildGeometry(om.ExplicitComponent):
    def setup(self) -> None:
        self.add_discrete_input("airframe", val=None)  # an m0 Individual
        self.add_discrete_output("mesh", val={})

    def compute(self, inputs, outputs, discrete_inputs, discrete_outputs) -> None:
        airframe = discrete_inputs["airframe"]
        mesh = drone_geometry(motor_mass=airframe.get("motor.mass"), split_instances=True)
        discrete_outputs["mesh"] = tag_parts(mesh, {"frame": airframe.id})
```

(One OM sharp edge, verified: declare typed defaults on both ends of a
discrete connection -- `val={}`, not `val=None` -- because setup-time
compatibility is `isinstance` on the declared defaults and `None`
matches nothing; probe I1.)

## Tier 3: the file boundary

External tools (RCS codes, CFD, FEA) want files, and
`ExternalCodeComp` already expects them. The convention is a tiny
frozen dataclass that flows as a discrete value while the bytes stay
on disk:

```python
@dataclass(frozen=True)
class FileArtifact:
    """A file crossing the analysis boundary: a path plus content identity."""

    path: str
    sha256: str
    media_type: str = "application/octet-stream"

    def to_json(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256, "media_type": self.media_type}
```

- A boundary component (e.g. a STEP/STL writer over a tier-2 recipe)
  writes the file and emits `FileArtifact(path, sha256(content))`.
  Consumers hand `artifact.path` to `ExternalCodeComp`'s
  `external_input_files` or their own subprocess.
- The **hash is the point**: it is the caching identity (same recipe,
  same hash -- skip the external run) and the recorder-bloat fix. The
  recorder sees ~200 bytes of JSON instead of megabytes of mesh:
  `to_json` is exactly the hook `make_serializable` tries first, so a
  recorded case reads back the full artifact record losslessly
  (verified, probe K3 -- against finding 2's silent `'Recipe'`
  degradation).
- Paths are per-case working directories keyed by interpretation id
  (`Uav::Drone#0` + case counter), so concurrent DOE cases never
  collide and a recorded case can locate its files afterwards.

## Tier 4: SysML integration

The handoff is modeled as **flows between analysis actions** -- the
constructs longeron already parses (`ItemDefinition`, `FlowUsage`,
typed action parameters; vendored ecore nsURI 20250201) -- so OM
wiring becomes *derivable from the model*:

```sysml
item def MeshModel;
action def BuildGeometry { in span : Real; out mesh : MeshModel; }
action def RcsAnalysis { in mesh : MeshModel; out rcs : Real; }
part def Uav {
    attribute span = 2.5;
    action build : BuildGeometry { in span = span; }
    action rcs : RcsAnalysis;
    flow of MeshModel from build.mesh to rcs.mesh;
}
```

```python
def derive_flows(
    model: M.Model, part: str | M.Definition | M.Usage
) -> list[tuple[str, str, str | None]]:
    """Resolved (source, target, payload qname) triples from the part's flow usages."""
```

- `derive_flows` resolves each `FlowUsage`'s endpoint strings against
  the part's action members and returns the connection list
  `build_problem` turns into `connect()` calls -- discrete for
  item-typed parameters, continuous for `Real`-typed ones. The
  declared payload type is validated against both ends' parameter
  types, the same declared-contract stance the `@ExternalAnalysis`
  binding already takes for calc defs.
- Analysis actions bind to components the same way calcs do: an
  `@ExternalAnalysis { component = "module:attr"; }` annotation on an
  `action def` names the ExplicitComponent; the existing contract
  validation extends because `list_inputs`/`list_outputs` already
  report discrete variables (probe K1).
- Two validation diagnostics come first, independent of everything
  else: `dangling-flow` (an endpoint that does not resolve;
  warning severity, mirroring `dangling-expose` from the
  [view-persistence design](view-persistence.md)) and
  `flow-payload-mismatch` (payload type vs endpoint parameter types).
  Today both dangle silently.

## Results land on the interpretation

Closing the loop is what makes cases *auditable*: after a run, OM
outputs become attribute values on the case's individuals.

```python
def record_case(build: ProblemBuild, outputs: Mapping[str, Any] | None = None) -> Interpretation:
    """A new interpretation: the case's individuals with the problem's outputs as slots."""
```

- `record_case` deep-copies the build's interpretation and writes each
  promoted output onto the matching individual's slot
  (`Instance.set()` -- verified write-back mechanics). The result is
  an immutable **interpretation snapshot**: input point + output
  values, one object.
- Individual ids give case recording stable, position-independent keys
  (`Uav::Drone#0.motor` stays `Uav::Drone#0.motor` across mixes);
  traceability runs from any output back to the configured individuals
  that produced it; population roll-ups
  (`Interpretation.rollup`, `m0.py` l. 155) and the scoreboard's
  `values=` seam consume the snapshot directly.
- The snapshot's `to_dict()` is JSON-clean (verified: 274 chars for
  the probe model) -- the natural recorder payload and the future
  `application/vnd.longeron.m0+json` sidecar shape, per the M0
  design's API stance.

## Picklability and MPI

- **Serial:** discretes pass by reference (finding 3); the frozen-
  payload convention is the only defense. No copies means no cost.
- **MPI:** every discrete crossing a rank boundary is pickled by
  mpi4py. `Individual`s pickle (verified: 3-22 KB, because the
  `definition` backlink drags a *copy* of the reachable M1 graph --
  fine per-case, unacceptable inside a large mesh). Rule: entities
  cross ranks as individuals; bulk payloads cross as plain
  dicts/recipes keyed by individual *id* strings, never embedding
  `Individual` objects.
- cadquery/OCC solids never enter a discrete slot (tier 2); rebuild
  from recipes on the consuming rank.
- Gradient machinery is unaffected: discretes are invisible to the
  derivative system except through the documented driver gate
  (probes B1/B3).

## Case recording

The recorder findings (2, and probes C/F/G/K3) fix the conventions:

- Dict/list/scalar payloads record losslessly as JSON -- at full size,
  per iteration. Anything above ~100 KB flows as a `FileArtifact`
  (tier 3), never as an inline discrete, or is excluded via
  `recording_options['excludes']`.
- Custom classes crossing the recorder **must implement `to_json`**
  (the `make_serializable` hook); otherwise they silently record as a
  class-name string. `FileArtifact.to_json` exists for exactly this,
  and `Individual` gains a `to_json` alias for `to_dict` so a recorded
  entity case reads back as its full bundle rather than
  `'Individual'`.
- The interpretation snapshot (previous section) is the durable
  record; the OM sqlite file is a per-run artifact. Snapshot ids link
  the two.

## What we deliberately do not build

- **No OpenMDAO fork, no patched internals.** Everything rides
  `add_discrete_input`/`add_discrete_output`, stock drivers, stock
  recorders.
- **No auto-CFD/RCS/FEA adapters.** The design ships the pipe and the
  conventions (entity bundles, mesh dicts, recipes, `FileArtifact`);
  physics components remain user code behind the existing
  `@ExternalAnalysis` contract.
- **No custom serialization format.** Pickle in memory and across MPI,
  `to_json` at rest, real files behind `FileArtifact`. Nothing new to
  version.
- **No object units.** Payloads are structures; their scalar leaves
  keep the [units design](units.md)'s story unchanged.
- **No M1 mutation.** Interpretation snapshots never write back into
  the model; `Interpreter.snapshot` remains a separate, explicit tool
  (M0 design, non-goals).
- **No dataflow engine.** `derive_flows` produces OM connections; OM
  owns execution order, convergence, and parallelism.

## Open questions for the maintainer

All seven were ratified as recommended by the maintainer on
2026-08-27. The implementation treats them as settled; the two
sequencing rulings (Q5: the trades variant-bundle fix lands FIRST;
Q6: the flow diagnostics ship independently, first) define the
implementation order.


1. **Optionality: what does the continuous-sweep user pay?** (central)
   Demanding an `Interpretation` on every `build_problem` call would
   tax the users the bridge serves best today. *Recommendation:* the
   light path materializes **one implicit anonymous interpretation**
   lazily -- without `interpretation=`, `build_problem` behaves exactly
   as today (verified unchanged for scalar-only models), and the
   implicit point is created only when something asks for it
   (`record_case`, entity binding, M0-keyed payloads). Zero ceremony,
   zero cost until used; the identity stays true because the implicit
   point *is* an interpretation.
2. **Result lifecycle: snapshot per case, or annotate in place?**
   (central) `Instance.set()` makes in-place annotation trivially
   available, but a mutable case history is un-auditable: re-running a
   case overwrites the evidence. *Recommendation:* **a new immutable
   interpretation snapshot per case** (`record_case` returns a fresh
   object; the input interpretation stays pristine) -- matching the
   trades machinery's interpreter-exact re-evaluation honesty and the
   maintainer's stated instinct. In-place `set()` remains for
   interactive notebook use, documented as outside the recorded
   lifecycle.
3. **What object is the discrete value -- `Individual` or its
   `to_dict()` bundle?** *Recommendation:* the `Individual`
   in-process (identity, `get()`, definition backlink for conformance
   checks); the dict at process/file/recorder boundaries, converted
   automatically by the `to_json` hook and the MPI bulk-payload rule.
4. **Where does `FileArtifact` live in the model?** A Python-only
   convention, or also a vendored `item def FileArtifact` so flows can
   be *typed* by it in SysML? *Recommendation:* both -- the dataclass
   in `longeron.analysis`, plus an examples-shipped item def
   convention matching the `@ExternalAnalysis` precedent (convention
   packages over stdlib additions until the shape settles).
5. **Fix the empty variant bundles now?** Variants declaring inline
   redefinitions (`variant item x : Motor { :>> mass = ... }`) yield
   empty `VariationPoint` bundles (`trades.py` l. 397 instantiates the
   variant's type, dropping body redefinitions). *Recommendation:*
   yes, in trades, ahead of this design -- entity binding inherits the
   fix for free, and the bug silently zeroes catalogs today.
6. **Ship the flow diagnostics independently?** `dangling-flow` and
   `flow-payload-mismatch` need no OM work at all.
   *Recommendation:* yes, first -- they close finding 4's silent
   half at validation time and make tier 4's inputs trustworthy.
7. **Heterogeneous per-index selection** (`motors : MotorChoice[4]`
   with mixed variants) -- entity binding naturally extends (one
   discrete input per index, ids `motors#0..3`), but trades enumerates
   homogeneously today. *Recommendation:* defer to the existing
   trades phase-2 item; nothing in this design blocks it.

## References

- OpenMDAO 3.45.0 (installed): `core/driver.py` l. 530,
  `drivers/doe_driver.py` l. 63, `core/conn_graph.py` l. 85
  (`are_compatible_values`), `core/group.py` l. 2066
  (`_discrete_transfer`), `utils/general_utils.py` l. 772
  (`make_serializable`), `recorders/sqlite_recorder.py` l. 476,
  `components/external_code_comp.py` l. 41-56, 234; the discrete
  variables feature docs (openmdao.org, "Discrete Variables").
- Longeron surfaces: {mod}`longeron.analysis.mdao` (l. 555, 589, 655),
  {mod}`longeron.analysis.trades` (l. 376, 397), {mod}`longeron.m0`
  (l. 60, 155, 227, 453), {mod}`longeron.analysis.geometry`,
  {mod}`longeron.analysis.grand` (l. 131), `model.py` l. 606
  (`FlowUsage`), `interpreter.py` l. 770 (`instantiate`).
- SysML v2 constructs: `ItemDefinition`/`ItemUsage`,
  `Flow`/`FlowUsage`/`FlowEnd`/`PayloadFeature` (vendored
  `SysML.ecore`, nsURI 20250201); grammar rules `itemDefinition`
  (`SysML.g4` l. 1171) and `flowUsage`/`flowDeclaration` (l. 1553,
  1573).
- Sibling designs: [M0 interpretations](m0-interpretations.md) (the
  identity this design stands on), [units](units.md) (floats-only
  invariant, OM `units=` boundary), [view
  persistence](view-persistence.md) (the dangling-reference
  diagnostic precedent).
