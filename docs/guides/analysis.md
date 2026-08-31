# Choosing an analysis

{mod}`longeron.analysis` projects executable models onto external
solvers. Each bridge answers a different question, and each imports its
solver lazily behind its own extra, so the core package stays
dependency-light. This guide tells you which bridge to reach for, and
how the pieces compose. Tutorials
{doc}`4 <../tutorials/04_trades_sizing_the_fleet>` and
{doc}`6 <../tutorials/06_requirements_score_hunt_prove>` drive all of
them end to
end on one model, and tutorial
{doc}`8 <../tutorials/08_the_knowledge_graph>` covers the query
surfaces.

## Match the question to the tool

| Your question | Tool | Extra |
|---|---|---|
| Which discrete component mixes are feasible or optimal, and why do the others fail? | {mod}`~longeron.analysis.trades` (OR-Tools CP-SAT) | `trades` |
| What continuous sizing is best, and what happens if I change an input? | {mod}`~longeron.analysis.mdao` (OpenMDAO) | `mdao` |
| Is the requirement set consistent at all, and which requirements conflict? | {mod}`~longeron.analysis.smt` (Z3) | `smt` |
| How well does a design satisfy the weighted requirement hierarchy, and where does the utility come from? | {mod}`~longeron.analysis.scoreboard` (MAUT, interpreter-only) | none (`viz` for the widget) |
| Which elements relate how, across the whole model? | {mod}`longeron.rdf` (SPARQL) | `rdf` |
| What context should an LLM agent retrieve about this model? | {mod}`longeron.rag` | none |

One principle holds across all six: the interpreter stays the single
source of semantics. Solver results are re-evaluated, or cross-checked,
against the model itself, so an encoding bug cannot misreport a design.

## Trade studies: pick the architecture

Use {mod}`~longeron.analysis.trades` when the model declares a component
catalog: part usages typed by `variation` definitions with `variant`
members. {class}`~longeron.analysis.trades.TradeStudy` maps the catalog
onto CP-SAT with exact fixed-point arithmetic, enumerates or optimizes,
and re-checks every reported architecture through the interpreter.

The CP-SAT mapper covers linear-ish arithmetic (`+ - * /`). If the
derived attributes lean on `sqrt`, `pow`, conditionals, or calc
invocations, the mapper raises {class}`~longeron.analysis.AnalysisError`
instead of silently mis-encoding. At catalog scale the honest fallback
is `TradeStudy.all_architectures()`: walk the whole Cartesian candidate
space through the interpreter, exactly, with each infeasible mix naming
the constraints it breaks in `violations`.

## MDAO: size what stays continuous

Use {mod}`~longeron.analysis.mdao` after the architecture is fixed.
{func}`~longeron.analysis.mdao.build_problem` mirrors a part definition
onto an OpenMDAO `Problem`: derived attributes become components that
evaluate through the interpreter, free attributes become design
variables, and constraints and requirements become `*_margin` outputs.
Components are grouped by the calc definitions' owning packages, so the
generated problem inherits the model's discipline structure.

### The `ExternalAnalysis` fidelity pattern

First-order physics belongs in the model as `calc def` bodies.
Higher-fidelity tools live outside SysML. The shipped convention makes
the model declare the binding:

```sysml
metadata def ExternalAnalysis { attribute component : String; }

calc def CruisePower {
    @ExternalAnalysis { component = "uav_aero:CruisePowerPolar"; }
    in massKg : Real;  in speed : Real;
    return : Real = /* first-order drag polar */;
}
```

The calc's `in`/`return` parameters are the I/O contract.
`build_problem` validates the contract against the named OpenMDAO
component's actual inputs and outputs, and a mismatch fails with both
name lists. Passing `fidelity={"CruisePower": "external"}` swaps the
interpreter-backed body for the component. Everything else in the
problem is untouched, so a lo-fi/hi-fi comparison is one keyword
argument.

### Objects across the bridge

Scalars are not the only things that cross
([design](../design/mdao-objects.md)). A part/item member typed by a
`variation` definition becomes one **discrete input** carrying the
configured M0 individual -- the case being evaluated is an
{func}`~longeron.m0.interpret` interpretation (passed as
`build_problem(..., interpretation=...)`, or materialized implicitly
when the model has variation points). Swap the case with
{func}`~longeron.analysis.mdao.bind_entity`, enumerate a catalog as DOE
cases with {func}`~longeron.analysis.mdao.entity_cases`, and freeze each
evaluated case as an immutable interpretation snapshot with
{func}`~longeron.analysis.mdao.record_case` (the snapshot feeds the
scoreboard through {func}`~longeron.analysis.mdao.case_values`).
Structured payloads (mesh dicts, cadquery *recipes* -- never live
kernel solids) flow between components as discrete values keyed by M0
individual id; files cross as a
{class}`~longeron.analysis.mdao.FileArtifact` (path + sha256, the
caching identity) while the bytes stay on disk; and
{func}`~longeron.analysis.mdao.derive_flows` /
{func}`~longeron.analysis.mdao.apply_flows` turn the model's
`flow of Payload from a.out to b.in` usages into proposed OpenMDAO
connections -- propose + apply, never silent magic.

## SMT: guard the requirement set

Use {mod}`~longeron.analysis.smt` before spending solver time on an
impossible ask. It encodes requirement sets as Z3 assertions over
unbounded reals and answers three questions: is the set satisfiable,
which minimal subset conflicts (the unsat core), and what exact bounds
does the set impose on a freed attribute. Because Z3 works over the
reals, a "consistent" verdict is exact, not sampled.

## Scoreboard: how good is this design, requirement by requirement

Use {mod}`~longeron.analysis.scoreboard` when the requirement hierarchy
carries importance weights and you want one number -- and its full
decomposition -- for how well a design satisfies it. Weights and
utility shapes are declared as plain attributes on the requirement
usages themselves (`weight`, `utility`, `measure`, and the shape
anchors), so the model stays the source of truth;
{func}`~longeron.analysis.scoreboard.scoreboard` evaluates raw measures
through the interpreter, maps them onto [0, 1] utilities, aggregates up
the hierarchy (simple additive weighting by default, weakest-link and
geometric strategies built in, custom aggregators pluggable), and
renders as an interactive treemap or Voronoi tessellation where area is
importance and color is utility. `values=` injection scores any
trade-study architecture without touching the model (tutorial
{doc}`6 <../tutorials/06_requirements_score_hunt_prove>`).

## RDF and RAG: query and retrieve

Two projections serve machine consumers rather than solvers:

- {mod}`longeron.rdf` projects the model onto an RDF graph and answers
  SPARQL queries over structure, specializations, typed attribute
  values, variation points, and requirement traceability.
- {mod}`longeron.rag` chunks the model into deterministic, re-parseable
  SysML fragments keyed by qualified name, walks semantic
  neighborhoods, and does keyword search, all stdlib-only. It is the
  retrieval layer for LLM agents, which cite qualified names and then
  resolve them through the interpreter for ground truth.

## How the pieces compose

The bridges form a two-level loop, classic mixed-discrete MDO:

1. `smt` confirms the requirement set is satisfiable.
2. `trades` scores every architecture exactly and picks the winner.
3. The winner freezes into a concrete part definition, and `mdao`
   optimizes its continuous attributes, swapping in declared external
   analyses where first-order physics is not enough.

The view modules ({mod}`~longeron.analysis.viz`,
{mod}`~longeron.analysis.structure`,
{mod}`~longeron.analysis.dashboard`,
{mod}`~longeron.analysis.geometry`,
{mod}`~longeron.widgets.viewer3d`) render the results: Pareto fronts,
parallel coordinates, N2 matrices, constraint networks, to-scale 3D
meshes, and the linked mission-compromise dashboard.
