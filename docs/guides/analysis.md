# Choosing an analysis

{mod}`longeron.analysis` projects executable models onto external
solvers. Each bridge answers a different question, and each imports its
solver lazily behind its own extra, so the core package stays
dependency-light. This guide tells you which bridge to reach for, and
how the pieces compose. Tutorial
{doc}`7 <../tutorials/07_analysis_and_trades>` drives all of them end to
end on one model, and tutorial
{doc}`8 <../tutorials/08_semantic_web_and_rag>` covers the query
surfaces.

## Match the question to the tool

| Your question | Tool | Extra |
|---|---|---|
| Which discrete component mixes are feasible or optimal, and why do the others fail? | {mod}`~longeron.analysis.trades` (OR-Tools CP-SAT) | `trades` |
| What continuous sizing is best, and what happens if I change an input? | {mod}`~longeron.analysis.mdao` (OpenMDAO) | `mdao` |
| Is the requirement set consistent at all, and which requirements conflict? | {mod}`~longeron.analysis.smt` (Z3) | `smt` |
| Which elements relate how, across the whole model? | {mod}`longeron.rdf` (SPARQL) | `rdf` |
| What context should an LLM agent retrieve about this model? | {mod}`longeron.rag` | none |

One principle holds across all five: the interpreter stays the single
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

## SMT: guard the requirement set

Use {mod}`~longeron.analysis.smt` before spending solver time on an
impossible ask. It encodes requirement sets as Z3 assertions over
unbounded reals and answers three questions: is the set satisfiable,
which minimal subset conflicts (the unsat core), and what exact bounds
does the set impose on a freed attribute. Because Z3 works over the
reals, a "consistent" verdict is exact, not sampled.

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
{mod}`~longeron.analysis.viewer3d`) render the results: Pareto fronts,
parallel coordinates, N2 matrices, constraint networks, to-scale 3D
meshes, and the linked mission-compromise dashboard.
