# The lofting framework and the multisection wing (design)

> **Status: DRAFT.** Nothing below is implemented. Four commitments
> arrive settled, and the body states them as commitments, not
> questions: the generalization itself (a domain-neutral loft
> framework, with domain content as model libraries); the tier-3
> posture (a real seam for cited artifacts, with runnable stand-ins:
> AeroSandbox as the different-physics stand-in, OpenAeroStruct as
> the binding demo on the existing mdao bridge, and the
> real-CFD-via-cited-`FileArtifact` rung retained above both); the
> editor's landing (0.13, beside geometry phases 1-2, with the loft
> compiler as its rendering engine); and the editor's day-one
> round-trip through workspace save. The open questions at the end
> each carry one recommendation.

Goal: lofted bodies as model content. A multisection wing -- real
airfoils, taper, twist, dihedral -- is an ordered stack of sections
in SysML v2 text, and the model itself derives the planform numbers
and the tier-1 aerodynamics. The same vocabulary lofts a rocket body
with zero framework changes. That symmetry is the design's point:
the framework is domain-agnostic, and domain content is model
libraries.

The thesis follows longeron's spine. The adopted geometry design
inverted geometry ownership: parts carry their shapes as model
content, and the kernel compiles that content. This design applies
the same inversion to lofted surfaces and then generalizes it. A
profile is a model calc. A section is a placed, scaled instance of a
profile. A body is an ordered stack of sections. Everything
downstream -- the planform numbers, the lift polar, the editor's
live 3D view -- derives from that stack. The standing posture
applies throughout: model-derived, never invented.

All measured claims below come from the executed wing spike,
recorded in `WING_SPIKE_FINDINGS.md` (the notebook
`wing_spike.ipynb` and the candidate scripts sit beside it). The
spike ran against longeron 0.11.0. This document cites the spike's
numbers and re-derives none of them. The spike's vendored prior-art
reference is the MIT-licensed ipyvsp airfoil implementation
(fetched 2026-08-30).

## The revision: one library becomes a framework

This design revises one adopted decision: geometry decision 2's
`LongeronAero` library is dissolved, and its place is taken by
`LongeronLoft`, a domain-neutral loft framework, plus domain model
libraries in SysML text.

The geometry design named three extension packages:
`LongeronGeometry`, `LongeronAero`, and `LongeronKinematics`. Its
`LongeronAero` sketch carried the domain inside the vocabulary: an
`AirfoilSection` with `family : String = "NACA4"` and
`code : String` ("2412"), and a `WingPanel` that knows span,
dihedral, and sweep. The spike showed that shape is both too
specific and too weak. Too specific, because nothing in a section
stack is aeronautical: station, scale, rotation, and in-plane
offsets loft a rocket as readily as a wing. Too weak, because a
string code hides the parameters an editor wants to slide: `"2412"`
buries camber and thickness inside digits, where
`camberMax = 0.02` is an ordinary attribute the interpreter
evaluates and `longeron.edit` validates.

The rocket smoke test justifies the split empirically. The spike's
framework code lofted a tangent-ogive rocket body with zero
framework deltas -- the new content was model text only: a
`CirclePoint` profile calc, a `TangentOgiveRadius` calc, and
sections whose `scale` the model computes from that calc. The model
evaluates the ogive radii itself and satisfies
`r(noseLength) == bodyRadius` to 1e-12. What differs between the
wing and the rocket is only the derived quantities: the wing
derives S, AR, taper, and MAC, and the rocket derives length and
fineness ratio. Both are calcs over the same stack spelling. The
domain lives in the calcs, so the calcs are the libraries.

The revised split:

- **`LongeronLoft`** (domain-neutral): `Section` (station, scale,
  rotation, offsetU, offsetV), `LoftedBody` (the ordered stack, the
  profile binding, the ruled loft rule), and the profile-calc
  contract. Its Python surface has four responsibilities, measured
  at ~150 lines in the spike: calc resolution by name, parameter
  binding by attribute name, cached interpreter sampling, and the
  placement rule.
- **Domain model libraries** (SysML text, not Python): `Profiles`
  (NACA 4-digit, PARSEC, circle, ogive), `AeroTier1` (planform and
  lifting-line calcs), and future `Hull` or `Rocket` equivalents.
  The rocket proved these are pure-model additions.

Everything else in the geometry design stands: `LongeronGeometry`
and `LongeronKinematics` are untouched, the fidelity ceiling holds
(analysis-grade lofts, not manufacturing surfaces), and geometry
phase 2's wing deliverable now rides `LongeronLoft` plus the two
aero libraries instead of `LongeronAero`.

## The vocabulary

### Section, LoftedBody, and the stack

The load-bearing spellings, verbatim from the spike's parsed and
validated model:

```sysml
part def Section {
    attribute station : Real;          // position along the stack axis
    attribute scale : Real;            // profile is unit-sized
    attribute rotation : Real = 0.0;   // in-plane, deg
    attribute offsetU : Real = 0.0;    // in-plane offsets
    attribute offsetV : Real = 0.0;
}

part def SpikeWing :> LoftedBody {
    part root : Section { :>> station = 0.0;  :>> scale = 0.30; :>> rotation = 2.0; }
    part mid  : Section { :>> station = 0.55; :>> scale = 0.24; :>> rotation = 0.5;
                          :>> offsetU = 0.030; :>> offsetV = 0.0288; }
    part tip  : Section { :>> station = 1.10; :>> scale = 0.12; :>> rotation = -1.0;
                          :>> offsetU = 0.090; :>> offsetV = 0.0577; }
    attribute stack = (root, mid, tip);        // THE ordering spelling
    :>> profileCalc = "Profiles::Naca4Point";
    attribute camberMax : Real = 0.02;         // NACA 2412
    attribute camberPos : Real = 0.4;
    attribute thickness : Real = 0.12;

    attribute stations : Real = stack->collect { in s; s.station };
    attribute scales   : Real = stack->collect { in s; s.scale };
    attribute area : Real = 2.0 * panelAreas->sum();
    attribute aspectRatio : Real = span * span / area;
    // ... taper, MAC, meanTwist: same pattern
}
```

The interpreter evaluates this wing with zero Python aero code:
S = 0.495 m^2, b = 2.2 m, AR = 9.778, taper = 0.4, MAC = 0.2373 m,
mean twist = 0.65 deg. `validate()` returns 0 diagnostics, strict
mode included, and the model round-trips through
`to_sysml` -> `loads` cleanly.

The spike's spelling verdicts, all measured:

- **The ordered stack is an explicit instance tuple.**
  `attribute stack = (root, mid, tip);` plus
  `stack->collect { in s; s.attr }` works today and is the 0.13
  spelling.
- **Multiplicity collections are NOT stacks.**
  `part sections : Section[3]` gives no way to bind per-instance
  values, and broadcast access returns `[None, None, None]`.
- **Indexing is `xs#(i)`** (1-based). `->at(i)` does not parse
  inside model text because `at` is a keyword.
- Sequence attributes, ranges `(1..n)`, `->collect` with bodies,
  chained conditionals, calc-local intermediates, and nested calc
  calls all parse and evaluate. The whole spike model uses only
  these. Grammar work for a first-class ordered collection is
  deferred (open question 2).

### The profile-calc contract

A profile is a calc from a curve parameter to a closed curve:
`in t : Real` in [0, 1) maps to a point `(u, v)` on the unit-sized
profile. The NACA 4-digit closed curve is a pure model calc
(`Profiles::Naca4Point`, ported from ipyvsp), and the
interpreter-sampled curve matches a direct numpy port to 4.2e-17 --
machine epsilon. The contract's cost envelope, measured by the
spike:

| operation | measured |
|---|---|
| raw profile eval, uncached, params varying | 23,348 evals/s (43 us/point) |
| trivial profile (circle) | 170,050 evals/s (6 us/point) |
| cold loft, 3 sections x 100 points, shared airfoil | 5.4 ms (~184 fps-equivalent) |
| cached loft (param-hash hit) | 1.30 ms |
| `instantiate` of the wing | 1.4 ms |
| cold `loads` of the spike model (new process) | ~12 s |

Parameter binding is by attribute name: the sampler reads the
calc's parameters off the body's same-named attributes. The
parameter-hash cache -- key = (calc qualified name, sorted
parameters, sample count) -- made repeat lofts 4x faster in the
spike and makes shared-profile sections nearly free. The ~12 s cold
`loads` is a per-process cost (vendored stdlib attach), not a
per-edit cost. An editor session amortizes it; per-invocation CLI
and CI workflows will feel it, and the phasing notes say so.

### Beyond model algebra: the edit-time solve

PARSEC marks the precise point where the profile-calc contract
breaks. The surface `z(x) = sum a_k x^(k-1/2)` IS model algebra
(`Profiles::ParsecHalf`). The 12 coefficients are not: they come
from two 6x6 linear solves, and the expression language has no
linalg primitive, no recursion, and no mutable state. Gaussian
elimination is not expressible, and Cramer's rule on a 6x6 is not a
serious spelling.

The adopted pattern is the edit-time solve, prototyped as the
spike's candidate A. Python solves the system when a design
parameter changes and writes the 12 coefficients back with
`edit.set_attribute_value`, each flagged as derived with the solver
name and a hash of the design parameters. Measured: the solve plus
write-back of 12 attributes takes 394 ms, dominated by longeron's
per-edit validation, not the 30-us numpy solve. The edited model
exports, re-parses, and validates clean, and the sampled curve
matches the original ipyvsp implementation to 5.3e-6 (interpolation
noise on 201 points).

Candidate B -- a framework `solve(A, b)` interpreter builtin -- is
declined. It would drag linear algebra into the interpreter's
contract and hide an iterative numeric process inside "model
algebra". The edit-time solve keeps the interpreter closed-form,
matches the editor reality (a PARSEC slider drag owns a solver
anyway), and turns the staleness hazard it introduces -- design
parameters edited, coefficients not re-solved -- into exactly the
kind of flag longeron's provenance lint machinery can check. The
flag's upgrade from doc comments to provenance metadata is a
cross-design seam below (and open question 4). The pattern is
general: any parameterization that exceeds model algebra (PARSEC
now, structures later) gets the same treatment.

## The domain libraries

`Profiles` ships the four spike-proven profile calcs: NACA 4-digit,
the PARSEC half-surface, the circle, and the ogive-supporting
circle-plus-radius pair. `AeroTier1` ships the planform calcs
(S, AR, taper, MAC, mean twist over the stack) and the closed-form
lifting-line polar the money table's tier 1 evaluates. Future
`Hull` and `Rocket` libraries follow the rocket smoke test's shape:
new calcs, zero framework lines.

Two library obligations carry over from the spike's risk list.
First, the tier-1 formulas carry citation debt: the spike
transcribed the Nita-Scholz quartic from memory and cross-checked
it against tier 2, and the shipped library version must verify the
citation against the paper through the evidence machinery. Second,
the spike mixes degrees (rotation, alphas) and radians (teBeta);
the shipped vocabulary should pin angle units before the editor
exposes sliders (open question 7).

## The editor

The editor is settled: an OpenVSP-class section-stack editor lands
in 0.13 with geometry phases 1-2, as a `longeron.widgets` citizen,
and it round-trips through workspace save from day one. OpenVSP's
wing and fuselage editors are the reference UX. The loft compiler
is the editor's rendering engine, which is why the two land
together.

Three surfaces compose it: a section table (the stack, ordered), a
property sheet (the selected section's attributes plus the body's
profile parameters), and a live 3D loft. The spike's numbers say
live means live: a cold loft is 5.4 ms and a cached loft is
1.30 ms, so slider drags re-render at frame rate. Section
placement edits (station, scale, rotation, offsets) hit the
parameter-hash cache -- the curves are unchanged and only placement
moves -- and tier-1 readouts update at interpreter speed.

Every edit goes through `longeron.edit`. That sentence is the
design: value edits ride `set_attribute_value` with its unit gate
(dimension conflicts and fake units are refused, stating both
dimensions), every change lands on the `Tracker`, and the app
chrome's dirty dot and Save/Push affordances follow. Add, remove,
and reorder of sections are structural edits; growing the `edit`
surface to cover them -- tracked, unit-validated, refusal-honest,
like `rename` and `set_attribute_value` today -- is this arc's
edit-surface work. Save is `export.save_workspace`: only files with
tracked changes re-render, and the saved text re-parses and
validates. The editor never holds a private document format; the
model is the document.

PARSEC sliders follow the drag/commit pattern the spike's numbers
force. During a drag the editor solves in memory (the numpy solve
is 30 us) and re-samples the curve directly; on release it commits
the flagged write-back through `edit` (394 ms, dominated by edit
validation). The user sees a live curve and the model receives one
validated, tracked, provenance-flagged change per gesture.

One honest cost from the spike's risk list: the tuple-stack
spelling puts ordering in an attribute, not in the part structure,
so the editor (and any diagram tooling) must read `stack` to order
the table. The editor writes the tuple too, which is why authors
rarely type it.

## Multi-fidelity: analysis cases over the lofted subject

The tier ladder is not new machinery. Each tier is an analysis case
over the lofted subject, per the adopted surfaces contract: the
subject is the `LoftedBody`, the in parameters are the flight
conditions, the returns are the polar numbers, and `@ToolExecution`
at the case level names the engine. Subject typing decides
applicability, and a case whose tool is not installed renders as
honest absence -- the panel states the extra it needs, and no
number is fabricated.

The ladder, with every runtime measured by the spike:

| rung | what runs | binding | runtime (3 alphas) |
|---|---|---|---|
| tier 1 | `AeroTier1` model calcs (closed-form lifting line) | the interpreter; no tool | 0.1 ms |
| tier 2 | the in-house 190-line numpy VLM (384 panels) | `@ToolExecution` naming the house module | 130 ms |
| tier 3 stand-in | AeroSandbox AeroBuildup + NeuralFoil (MIT) | `@ToolExecution`; in-process import today, `FileArtifact` when runs move out-of-process | 86 ms |
| tier 3 binding demo | OpenAeroStruct (Apache-2.0), OpenMDAO-native | the existing `@ExternalAnalysis` bridge in `longeron.analysis.mdao`, zero new seam | 106 ms |
| the CFD rung | a real CFD or wind-tunnel result | a cited `FileArtifact`: path + sha256 + media type | no runtime; it is a citation |

Tier 2 earns its keep as the house referee. Its validation record,
from the spike: the 2D limit gives CLa = 6.264/rad against
2 pi = 6.283, a near-elliptic planform gives e = 0.993 against the
ideal 1.0, a rectangular AR=6 wing converges across three mesh
densities to CLa = 4.25/rad and e = 1.00, and AeroSandbox's
independent VLM agrees within 1-4% on CL for the spike wing. No
literature numbers were quoted from memory; the
independent-implementation cross-check replaced them, per the
provenance rule.

### The evidence exhibit

The money table, reproduced from the spike. The subject is the
3-section NACA 2412 wing above (S = 0.495 m^2, AR = 9.78, taper
0.4, twist +2/-1 deg, 3 deg dihedral) at V = 20 m/s,
Re_MAC = 3.2e5. All runtimes are for 3 alphas. "--" means the
method cannot produce that number.

| method | physics content | runtime | a=0: CL / CDi / CD_tot | a=4: CL / CDi / CD_tot | a=8: CL / CDi / CD_tot |
|---|---|---|---|---|---|
| tier 1: model calcs (LLT closed form) | inviscid, closed-form | 0.1 ms | 0.2475 / 0.0020 / -- | 0.6105 / 0.0124 / -- | 0.9735 / 0.0314 / -- |
| tier 2: in-house numpy VLM (384 panels) | inviscid, lifting-surface | 130 ms | 0.2265 / 0.0019 / -- | 0.5774 / 0.0109 / -- | 0.9237 / 0.0277 / -- |
| MachUpX 2.7.2 NLL (MIT) | inviscid, nonlinear lifting-line | 81 ms | 0.2542 / 0.0023 / -- | 0.6173 / 0.0123 / -- | 0.9807 / 0.0307 / -- |
| AeroSandbox 4.2.10 VLM (MIT) | inviscid, lifting-surface | 82 ms | 0.2350 / 0.0020 / -- | 0.5868 / 0.0111 / -- | 0.9340 / 0.0278 / -- |
| OpenAeroStruct 2.12 (Apache-2.0) | VLM + flat-plate viscous | 106 ms | 0.2040 / 0.0016 / 0.0130 | 0.5585 / 0.0101 / 0.0215 | 0.9119 / 0.0264 / 0.0378 |
| ASB AeroBuildup + NeuralFoil (MIT) | viscous, CFD/XFoil-trained surrogate | 86 ms | 0.3092 / -- / 0.0123 | 0.6916 / -- / 0.0290 | 0.9747 / -- / 0.0528 |

The spread is the story the ladder exists to tell. At alpha = 4 deg
the five inviscid CL values sit within +-5% of each other, with
tier 1 reading high (the classic lifting-line bias). The drag
column carries the fidelity: CDi-only methods say 0.010-0.012, the
flat-plate buildup says 0.0215, and the NeuralFoil buildup says
0.0290. The drag the low tiers cannot see is 2-3x the drag they
can. NeuralFoil also adds physics no tier-1/2 method has: at
Re = 3.2e5 it reports Cd 0.0077 -> 0.0710 and Cl flattening from
1.26 to 1.30 between alpha 12 and 16 deg (stall onset), with a
published analysis-confidence signal (0.97-0.99 on this wing).

### The tier-3 posture, settled

The posture is a real seam with a cited artifact, and runnable
stand-ins below it, all proven by the spike (total setup for the
three candidates: under 9 minutes, 557 MB in a scratch venv).

- **AeroSandbox + NeuralFoil is the physics stand-in.** It is the
  only candidate whose physics content genuinely differs from tiers
  1-2: a CFD/XFoil-trained viscous surrogate, not another vortex
  method. MIT-licensed, one pip install (21 MB + 7 MB, dragging
  casadi at 157 MB), 30 ms per polar point. Its VLM doubles as the
  tier-2 referee. Any binding must surface NeuralFoil's confidence
  output: the surrogate's training envelope ends where the
  interesting failures begin, and its own signal says so. If
  install weight ever matters for the demo story, NeuralFoil alone
  (7 MB plus numpy) carries the viscous-polar seam.
- **OpenAeroStruct is the binding demo.** Apache-2.0,
  OpenMDAO-native, so fidelity swap through the existing
  `longeron.analysis.mdao` bridge exercises `build_problem` with
  zero new machinery. Its aerostructural coupling stays in reserve.
- **The cited-artifact CFD rung stands above both.** Nothing in the
  table computes transonic, separated, or truly high-Reynolds flow.
  The `FileArtifact` seam (path + sha256 + media type, already in
  `examples/analysis_conventions.sysml`) is how a wind-tunnel CSV
  or an OpenFOAM result enters with provenance. The spike confirms
  the seam is real: the tier-3 candidates already run as
  subprocess-plus-JSON, the same shape.
- **MachUpX is declined.** Credible but redundant -- a third
  lifting-line answer within 1% of tier 1 -- and its GitHub-only
  install makes it a weaker citation.

## Cross-design seams

- **Provenance.** The PARSEC write-back's derived flags upgrade
  from doc comments to provenance metadata in the shipped
  `Evidence` package, so `verify`-style checking and lint can
  detect staleness (a solved coefficient whose design-parameter
  hash no longer matches). The metadata's exact shape is open
  question 4; the upgrade itself is not.
- **Time.** Untouched. The editor introduces no time-aware view,
  and nothing here joins the clock.
- **Surfaces.** Subject swap applies as adopted: a hull subject
  gets ITS analysis cases by subject typing, and the wing's tier
  cases refuse a hull as honest absence. A lofted body is just a
  subject; the tier ladder above is the wing's case list, not the
  framework's.
- **OpenVSP.** A future export target, on the JCAD-exporter
  posture: model-outward, zero dependency, one line here.

## What we deliberately do not build

- **No ordered-collection grammar in 0.13.** The instance tuple
  ships; the grammar candidate is recorded (open question 2).
- **No `solve()` in the interpreter.** Candidate B is declined; the
  interpreter stays closed-form, and edit-time solves own the rest.
- **No hi-fi CAD.** The geometry design's fidelity ceiling stands:
  analysis-grade lofts over named profile families, no NURBS, no
  free-form BREP, not a manufacturing surface.
- **No MachUpX dependency**, per the tier-3 verdict.
- **No OpenVSP dependency.** Export target only, later.
- **No new widget framework.** The editor composes the existing
  chrome, tracker, and catalog machinery.
- **No per-frame model writes.** Sliders solve and sample in
  memory during a drag; the model receives one tracked edit per
  gesture, on release.

## Phasing

All three phases live inside the 0.13 arc, which geometry phase 1
opens. Each phase is independently shippable.

- **Phase A -- the vocabulary and the sampler.** `LongeronLoft`,
  `Profiles`, and `AeroTier1` ship; the spike wing becomes the
  worked example, with the model-derived planform and tier-1 polar
  as the acceptance test (zero Python aero code); the rocket ships
  beside it as the second-domain proof; the parameter-hash cache is
  the sampler's contract; the `profileCalc` spelling is resolved
  (open question 1) before the libraries freeze. The ~12 s
  cold-`loads` cost is documented for CLI/CI consumers.
- **Phase B -- the editor.** Rides geometry phases 1-2, which
  supply its rendering engine. The section table, property sheet,
  and live loft compose; the `edit` surface grows the structural
  operations (add, remove, reorder); workspace save round-trips
  from the first release; the PARSEC drag/commit pattern lands with
  its provenance flags.
- **Phase C -- the analysis cases.** The tier ladder is declared as
  analysis cases over the lofted subject, riding the surfaces
  design's phase-2 engine in the same release; AeroSandbox and
  OpenAeroStruct arrive behind extras with honest absence when
  missing; the CFD rung ships as a documented, worked
  `FileArtifact` citation.

## Open questions

1. **The `profileCalc` binding spelling.** Today it is stringly
   typed (`:>> profileCalc = "Profiles::Naca4Point"`), the spike's
   second vocabulary finding. Candidates: a metadata annotation
   naming the calc, or a typed reference (a redefinable calc usage
   on `LoftedBody` that domain bodies redefine).
   *Recommendation: the typed reference, verified in phase A before
   the vocabulary freezes -- validation then catches a dangling
   binding where a string fails silently; the spike-verified string
   stays as the fallback spelling if redefinition does not
   validate.*
2. **The ordered-stack spelling, long term.** The tuple works but
   puts ordering in an attribute, and multiplicity collections
   cannot bind per-instance values. *Recommendation: ship 0.13 on
   the instance tuple and record a grammar candidate (ordered part
   collections with per-instance binding) for a later language arc;
   the editor writes the tuple, so authors rarely type it.*
3. **Where do `Profiles` and `AeroTier1` live, and how do they
   import?** Candidates: `examples/` beside `evidence.sysml` (the
   convention-package precedent), or the first-class importable
   libraries directory geometry decision 2 already names for the
   `Longeron*` packages. *Recommendation: the importable libraries
   directory, with the loft libraries as its first residents;
   `examples/` keeps program-specific content only.*
4. **The PARSEC write-back's provenance flagging.**
   `SourceEvidence`-style reuse, or a dedicated derived-value
   metadata? A solver is not a document, but the verify/lint
   machinery is the same. *Recommendation: a dedicated
   `DerivedValue` metadata in the `Evidence` package (solver name,
   input hash, solve date), sharing the drift-checking machinery;
   `SourceEvidence` keeps meaning "a document says so".*
5. **Per-section profile-parameter overrides.** Attribute-name
   binding gives them in principle; the spike verified body-level
   binding only. *Recommendation: body-level binding in phase A;
   verify section-level overrides behind a test (a root-to-tip
   thickness ramp is the acceptance case) before the editor exposes
   per-section fields, and gray those fields out until then.*
6. **The editor's catalog and rendering names.** Where does it sit
   in `longeron.widgets`, and what does a surfaces declaration call
   it? *Recommendation: `loft_editor` in the catalog (home module
   `longeron.widgets.loft`), and a rendering usage `asLoftEditor`
   joining `LongeronSurfaces`, so a dashboard panel presents the
   editor the way every panel presents its widget.*
7. **Angle units.** The spike mixes degrees (rotation, alphas) and
   radians (teBeta), and nothing pins either. *Recommendation:
   declare the vocabulary's angle attributes with degree unit
   brackets in phase A, so the editor's edits get dimension
   checking through `set_attribute_value`'s unit gate for free,
   within the units design's floats-only invariant.*

## References

- The wing spike: `WING_SPIKE_FINDINGS.md` (repo root), with
  `wing_spike.ipynb` executed beside it, the candidate scripts in
  `candidates/`, and the vendored prior-art reference
  `vendor_ref/parsec_ipyvsp.py` (MIT-licensed ipyvsp, fetched
  2026-08-30). Every measured number above cites it.
- Sibling designs: [geometry](geometry.md) (the revised decision 2,
  the extension-packaging precedent, the fidelity ceiling, the
  phase structure this arc rides), [surfaces](surfaces.md)
  (analysis cases, `@ToolExecution` at the case level, honest
  absence, subject swap), [provenance](provenance.md) (the
  `Evidence` vocabulary and drift checking),
  [time](time.md) (the untouched seam), [units](units.md) (the
  floats-only invariant behind open question 7).
- Longeron surfaces: {mod}`longeron.edit`
  (`set_attribute_value`, the unit gate, `Tracker`, honest
  refusal), {mod}`longeron.export` (`save_workspace`, `to_sysml`),
  {mod}`longeron.widgets` (the catalog and chrome),
  {mod}`longeron.analysis.mdao` (`build_problem`,
  `@ExternalAnalysis`), {mod}`longeron.interpreter` (the calc
  evaluator the sampler drives),
  `examples/analysis_conventions.sysml` (`FileArtifact`),
  `examples/evidence.sysml` (`SourceEvidence`).
- Verified versions: longeron 0.11.0 (the spike's target);
  AeroSandbox 4.2.10 + NeuralFoil 0.3.3 (MIT); OpenAeroStruct 2.12
  (Apache-2.0); MachUpX 2.7.2 (MIT); the three tier-3 stacks
  together, 557 MB in a scratch venv.
