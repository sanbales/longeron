# Model-defined analysis surfaces (design)

> **Status: adopted 2026-08-30; phase 1 shipped 2026-08-30**
> (`longeron.analysis.surfaces.surface` -- the engine, the rendering
> vocabulary, and the two-subject proof; phase 2, the grand tour as a
> declaration, rides 0.13). Nothing below is implemented; this
> is the contract for the arc. Decisions: a dashboard is a standard
> VIEW USAGE -- exposes select, renderings present, subviews compose
> (Q1); renderings bind to the widgets catalog through a Python
> registry keyed by rendering qualified name (Q2); slider ranges are
> MINED from the model's own constraints, with assume constraints in
> the case objective as the authoring idiom and flagged fallbacks for
> unmined sides (Q3); subject typing is the applicability test --
> the specialization walk decides which cases fit a craft, and
> non-fitting panels render as honest absence (Q4); panel-to-engine
> bindings ride the standard's @ToolExecution at the case level,
> while the house @ExternalAnalysis stays at the calc level for
> component fidelity (Q5); panel coupling is EXPLICIT ONLY -- the
> corpus's ':>> attr = case.result' binding is the one spelling, the
> name convention is REMOVED entirely, and the derived wiring map
> lists unbound case results as a visible diagnostic so a forgotten
> binding is loud (Q6, adopted stricter than the recommendation);
> phase 1 (the engine + the two-subject proof) lands late in 0.12
> behind provenance and the time seam's phase 1, and phase 2 (the
> grand tour as a DeepScout declaration) rides 0.13 beside geometry
> phase 1 (Q7); declarations are hand-authored first -- the DeepScout
> dashboard declaration is the deliverable and the documentation --
> and a save_surface builder waits for phase 3 (Q8; the current
> save_view's thin configurability is noted, and the surfaces engine
> is what will make saved views worth configuring).

Goal: declare dashboards as SysML v2 data and derive the UI from the
model. The grand-tour dashboard today works only for the QuadCopter:
its sliders, its requirement wiring, its sizing and consistency
panels are Python choreography around one subject. This design gives
the surface a model-side declaration -- which subject, which what-if
parameters and their ranges, which requirements, which analyses --
so any architecture (the hexa, the teardrop, a future tilt-rotor)
gets its dashboard by declaration, not by code.

The thesis follows longeron's spine. A dashboard is a view: it
selects content and says how to render it, and the standard already
owns that vocabulary (`view`, `expose`, `render`). What a dashboard
shows is cases: analysis cases carry the what-ifs (a subject, in
parameters, measured returns), and verification cases carry the
requirement panels (a subject, verified requirements, verdicts). The
standing posture applies throughout: model-derived, never invented.
Every panel below is grounded in standard vocabulary, and the one
extension is a clearly labeled longeron library of renderings.

All empirical claims were verified against longeron 0.11.0 at commit
`f1d9d29` (the DeepScout program, the vendored stdlib, the analysis
modules). Library claims cite the pinned OMG corpus at commit
`de1070ae`. Spec citations use the printed page numbers of the SysML
v2 Part 1 PDF.

## The standards boundary: what the language states about surfaces

The inventory below is the raw material. Each subsection names the
vocabulary, cites it, and states what the dashboard needs from it.

### Cases: subject, parameters, objective, result

`Cases.sysml` (vendored, 70 lines) is the base: `Case` (line 15)
carries a `subject subj : Anything[1]` (line 24), an
`objective obj : RequirementCheck[1]` (line 40), and a
`return ref result` (line 49). Everything a panel needs to know --
what is under study, what question is asked, what came out -- is
already a slot on `Case`.

`AnalysisCases.sysml` (vendored, 37 lines) specializes it:
`AnalysisCase` (line 14) with `subject subj` (line 22) and the base
feature `analysisCases` (line 32). The spec's worked definition
(training example `33. Analysis/Analysis Case Definition Example
.sysml`) shows the full shape: a subject, `in attribute` parameters,
an objective holding `assume`/`require` constraints, analysis
actions, and a named return. The usage example binds results back
into the part tree:

```sysml
analysis cityAnalysis : FuelEconomyAnalysis {
    subject vehicle = vehicle_c1;
    in scenario = cityScenario;
}
part vehicle_c1 : Vehicle {
    attribute :>> fuelEconomy_city = cityAnalysis.fuelEconomyResult;
}
```

That is the what-if card's data, in the standard's own spelling: the
in parameters are the sliders, the subject is the craft, and the
return is the readout.

### Trade studies: the objective vocabulary

`TradeStudies.sysml` (corpus, 170 lines) ships `EvaluationFunction`
(line 12), `TradeStudyObjective` (line 35) with its
`require constraint { eval(selectedAlternative) == best }`,
`MinimizeObjective` / `MaximizeObjective` (lines 80, 98), and the
abstract `TradeStudy` analysis (line 116) whose subject is the
alternative set and whose return is `selectedAlternative` (line 162).
The corpus uses it exactly this way (validation model
`10b-Trade-off Among Alternative Configurations.sysml`): a
`TradeStudy` usage over a variation's variants, a `MaximizeObjective`,
and a selection constraint on the chosen part. The library's own doc
scopes it to a *given set of alternatives* -- a discrete choice. The
grand tour's optimize button is the continuous cousin: maximize
`stationMinutes` over a freed `loiterSpeed`. The vocabulary grounds
the intent (`MaximizeObjective` names the direction and the measure),
and the freed in parameter's mined range is the design-variable box.

### Verification cases: the requirements panel, standardized

`VerificationCases.sysml` (vendored, 102 lines) is the standard's own
requirements-panel data. `VerificationCase` (line 13) returns
`verdict : VerdictKind` (line 22), and its objective owns
`requirementVerifications : RequirementCheck[0..*]` (line 27) -- "a
record of the evaluations of the RequirementChecks of requirements
being verified." `VerdictKind` (line 58) enumerates `pass`, `fail`,
`inconclusive`, `error`. `PassIf` (line 70) turns a boolean into a
verdict. `VerificationMethod` metadata (line 81) names the method,
and its kind enumeration (line 90) includes `analyze` -- the Z3 and
scoreboard panels' method, named by the standard.

The corpus spells usages tersely (training example
`34. Verification/Verification Case Definition Example.sysml`):

```sysml
verification def VehicleMassTest {
    subject testVehicle : Vehicle;
    objective vehicleMassVerificationObjective {
        verify vehicleMassRequirement;
    }
}
```

The Annex A vehicle model adds the method annotation
(`@VerificationMethod { kind = (VerificationMethodKind::test, ...); }`)
and binds the subject with `subject vehicle_uut :> vehicle_b`. A
requirement panel is therefore one verification case: the subject
names the craft, the `verify` members name the rows, and the verdict
vocabulary names the colors.

### Views: select content, say how to render it

`Views.sysml` (vendored, 163 lines) is the container. `View` (line
13) owns `subviews : View[0..*]` (line 16) -- "other Views that are
used in the rendering of this View" -- and one
`viewRendering : Rendering[0..1]` (line 23). `Rendering` (line 64)
composes through `subrenderings`, with `TextualRendering` /
`GraphicalRendering` / `TabularRendering` (lines 80-94) and four
standard rendering usages: `asTextualNotation` (line 122),
`asTreeDiagram` (line 130), `asInterconnectionDiagram` (line 138),
and `asElementTable` (line 146), whose ordered `columnView` pattern
shows how a rendering parameterizes itself with nested views.
`StandardViewDefinitions.sysml` (vendored, 123 lines) names eight
view definitions, including `GeometryView` (line 81) -- already
claimed by the geometry design as the 3D pane's grounding -- and
`GridView` (line 103), whose doc names the tabular and matrix
presentations.

The corpus composes views out of views (training example
`42. Views/Views Example.sysml`): `view 'vehicle tabular views'`
contains two nested view usages, each with its own `expose` and
`render`. A dashboard -- one view whose panels are subviews, each
exposing its content and naming its rendering -- is that example's
shape, not a new invention.

### Tool bindings: the standard names the seam

`AnalysisTooling.sysml` (corpus, 33 lines, spec §9.4.2 printed
p. 562) ships `ToolExecution` (line 10: `toolName`, `uri` --
"identifies an external analysis tool to be used to implement the
annotated action") and `ToolVariable` (line 21). This is the
standard's own version of the house `@ExternalAnalysis` convention
(DeepScout `aircraft.sysml` line 37), which
`longeron.analysis.mdao` already reads to bind calc defs to OpenMDAO
components. The dashboard's panel-to-engine bindings (this case runs
the occlusion measure, that one the Z3 bridge) have a standard home.

`ParametersOfInterestMetadata.sysml` (corpus, 38 lines, spec §9.3.4
printed p. 558) ships `MeasureOfEffectiveness` and
`MeasureOfPerformance` semantic metadata -- the standard's way to
flag headline measures. The header score and the readout rows can
take their designation from it later; nothing below depends on it.

### Parameter ranges: the model already states them

A slider needs bounds, and the model already carries them as
constraints. `ScoutSizing::IsrPrime` asserts
`aboveStall { loiterSpeed >= 11.0 }` and
`belowCruise { loiterSpeed <= 24.0 }` -- the exact 11.0 and 24.0 the
dashboard hardcodes twice. The mining seam exists:
`verify.attribute_domains` walks its documented ladder (types, direct
constraint mining, Z3 bounds under the assumption set, flagged
fallback) and returns a `Domain` with `lo`, `hi`, and per-rung
provenance. Verified: `attribute_domains(interp, IsrPrime,
("loiterSpeed",))` yields `lo=11.0, hi=24.0, mined_from=['type:
Real', 'mined: aboveStall', 'mined: belowCruise']`.

Two miner gaps surfaced during verification, both small. First,
constraints nested inside a case's `objective` are not mined
(`named_members` walks direct members only), and the objective is
the spec's own home for a case's `assume` constraints. Second, a
negative literal bound (`elevation >= -90.0`) is not folded --
`_mine_comparison` matches plain literals, and unary minus wraps
one. Both are engine work in phase 1, not new vocabulary.

### Parse status: the vocabulary is already real in longeron

All of it parses today with zero diagnostics (verified against
0.11.0): `analysis def`/usage with subject, in parameters,
objective-nested assumes, and returns; `verification def`/usage with
`objective { verify X; }` (the verified requirement lands on the
`verify` member's `subsets`, readable); `view def`/usage with
nested view usages, `expose` (the `Expose` element with recursion
flags), and `render` references (readable through `subsets`);
`rendering def`/usage; and metadata annotations with attribute
values (`MetadataUsage.typed_by` plus `MetadataValue` members --
the same surface `mdao` reads `@ExternalAnalysis` through).

## What longeron hardcodes today (gap analysis)

`analysis/grand.py` (768 lines) was read end to end. The module
composes seven panes and wires them kernel-side. Everything below
cites its lines.

The gap table -- what each pane needs, where that knowledge lives:

| Pane / behavior | Declared in DeepScout today | Baked in Python (grand.py) |
| --- | --- | --- |
| The subject | `Rotorcraft::QuadCopter` exists as a configuration | the default `assembly` kwarg (lines 138, 408); `drone_scene` demands the MultiRotor slot shape (`chassis`/`battery`/`propellers`, the rotor populations, lines 167-188) |
| Camera what-if pair | `Camera` attributes `elevation`/`azimuth`/`fieldOfView` (parts.sysml line 125); the `installation` requirement measures `occludedFraction` | WHICH two attributes are what-ifs; slider ranges -90..90 / -180..180 and steps (lines 532, 541); the re-measure call (`occlusion_report`); the cone length `0.45 * diagonal` (line 462) |
| Loiter slider + IsrPrime | `IsrPrime` with `loiterSpeed`, the full sizing chain, `aboveStall`/`belowCruise` (11..24), `IsrStation` | the case itself: `sizer`/`station_requirement`/`station_var`/`loiter_var` kwargs (lines 410-413); the range 11..24 hardcoded twice (slider line 550, `design_vars` line 484); the maximize intent |
| Z3 verdict strip | `IsrStation` (`stationMinutes >= 90.0`) | the requirement pick (same kwargs); the impossible floor `what_if_station = 420.0` (line 414); the freed variable |
| Occlusion -> `clearView` wiring | `installation.clearView` declares `measure = occludedFraction` | the `values=` merge keyed by attribute name (lines 572-576); the offender-highlight fan-out |
| Scoreboard | the MAUT hierarchy: weights, utility shapes, ramps, measures (`ScoutMissions::scoring`; moved into the model in 0.11) | the injection seam only (`values=`, line 473) |
| Cesium mission | `FlightStates`; `cruiseTilt` (read via `model_tilt`, in-model since 0.11) | `states` kwarg (line 409); `FLIGHT_EVENTS` (line 91); `ATLANTA_LOOP` (line 81); `ground_alt`, `imagery` |
| 3D pane keying | configurations render per M0 population (0.11's `scene_for` + `bind_config_view`) | `_ESC_MASS` (line 94), `_FLEET_DISPLAY` (line 217), `_AIRFRAME_KNOBS` (line 221) |
| Layout + wiring | -- | row heights, CSS, the reentrancy guard, observer plumbing (stays code; see below) |

The direction of travel is established. 0.11 already moved the
scoring hierarchy (weights, utilities, ramps, measures) into
`missions.sysml`; keyed scenes by configuration (`scene_for`
dispatching both craft families); promoted the config-click seam
(`bind_config_view`: any craft clicked in the diagram renders in the
pane); and read the cruise attitude from the model (`model_tilt`
over the `cruiseTilt` calc). Each was a Python constant that became
model content plus a derivation. This design is the same move,
applied to the surface itself.

## Precedents in the house

- **`views.py` already writes and reads the Views vocabulary.**
  `save_view` writes a `ViewUsage` typed by a
  `StandardViewDefinitions` definition, with recursive exposes and a
  `render` reference; `restore_view` picks the builder from the
  typing through a mapping table (`VIEW_DEFINITIONS`), computes the
  `expose_closure` (membership and namespace exposes, filters,
  dangling-expose warnings), and re-applies presentation from a
  versioned sidecar. The ratified two-tier scheme -- standard content
  in the model, presentation in a sidecar -- transfers to surfaces
  unchanged. Verified: `expose_closure` resolves a panel subview's
  expose of an analysis usage without modification.
- **`@ExternalAnalysis` is a working metadata-to-bridge binding.**
  `mdao.component_spec` reads the annotation off a calc def by
  metadata-definition name and instantiates the named component.
  The panel bindings below reuse the mechanism with the standard's
  own `ToolExecution` vocabulary.
- **`analysis_conventions.sysml` is the convention-package
  precedent**: model-side counterparts of Python analysis machinery,
  shipped as a longeron package, never labeled standard library --
  the geometry design promoted the same pattern to importable
  `Longeron*` libraries.
- **`verify.attribute_domains` is the range miner** (verified above),
  and `smt.to_smt(..., free=...)` already frees named paths for the
  what-if consistency question.
- **The widgets catalog is the rendering vocabulary's target.**
  `longeron.widgets` re-exports the 17 house entry points behind one
  lazy roof, keyed by name (`_CATALOG`). A rendering-name-to-builder
  registry is the same table one level up.

## The design

### The grounded vocabulary: what rides as-is

| Surface concept | Grounding | Status |
| --- | --- | --- |
| The dashboard container | `view def` / `view usage`, panels as nested view usages (`subviews`) | standard; vendored |
| Panel content selection | `expose` (membership / namespace, filters) | standard; `views.py` machinery exists |
| Panel presentation | `render` reference to a rendering usage | standard; vendored |
| What-if card | `analysis def` / usage: subject, `in` parameters, named returns | standard; parses today |
| Slider ranges | `assume` constraints in the case objective, mined by `attribute_domains` | standard; miner needs two small fixes |
| Optimize affordance | `TradeStudies::MaximizeObjective` as the case objective | standard; **vendor `TradeStudies.sysml`** |
| Requirement panel | `verification def` / usage: subject, `verify` members, `VerdictKind` | standard; parses today |
| Panel method | `@VerificationMethod { kind = analyze; }` | standard; vendored |
| Panel-to-engine binding | `@ToolExecution { toolName; uri; }` | standard; **vendor `AnalysisTooling.sysml`** |
| House widget names | rendering usages | **longeron extension** (`LongeronSurfaces`) |

The one extension is deliberately small. The standard ships four
rendering usages (tree, interconnection, table, text); longeron's
panels need names for the house widgets. `LongeronSurfaces` is a
longeron-authored library (the `LongeronGeometry` packaging
precedent: shipped beside the vendored stdlib, never labeled
standard, self-declaring in its doc comment) of rendering usages
subsetting `Views::renderings`:

```sysml
package LongeronSurfaces {
    doc /* Longeron extension: renderings naming the house widgets.
           Each rendering usage is bound to one longeron.widgets
           catalog entry by the surface engine's registry. */
    private import Views::*;

    rendering def PanelRendering :> GraphicalRendering;

    rendering asStructureDiagram : PanelRendering;  // structure_diagram
    rendering asMeshViewer : PanelRendering;        // mesh_viewer + scene_for
    rendering asScoreboard : PanelRendering;        // scoreboard
    rendering asWhatIfCard : PanelRendering;        // sliders + readout
    rendering asSizingCards : PanelRendering;       // mdao strip
    rendering asVerdictCards : PanelRendering;      // smt strip
    rendering asMissionGlobe : PanelRendering;      // mission_viewer
    rendering asReplayPlayer : PanelRendering;      // replay_widget
}
```

The vocabulary starts with the grand tour's eight and grows one
rendering per panel-able catalog entry. Catalog entries that are
applications, not panels (`explore`, `open`, `Inspector`), get no
rendering.

### The worked declaration

The DeepScout program grows a seventh file, `surfaces.sysml`. The
full sketch below parses and validates with zero diagnostics against
the shipped program (verified at `f1d9d29`, with `ToolExecution`
declared locally pending the vendoring):

```sysml
package ScoutSurfaces {
    private import Views::*;
    private import VerificationCases::*;
    private import LongeronSurfaces::*;
    private import AnalysisTooling::*;
    private import DeepScout::*;
    private import ScoutSizing::*;

    analysis def CameraWhatIf {
        doc /* Re-measure camera occlusion as the boresight moves. */
        subject drone : MultiRotor;
        in attribute elevation : Real = drone.camera.elevation;
        in attribute azimuth : Real = drone.camera.azimuth;
        objective {
            assume constraint elevationRange {
                elevation >= -90.0 and elevation <= 90.0 }
            assume constraint azimuthRange {
                azimuth >= -180.0 and azimuth <= 180.0 }
        }
        @ToolExecution { toolName = "longeron.analysis.geometry";
                         uri = "occlusion_report"; }
        return occludedFraction : Real;
    }

    verification def InstallationCheck {
        subject drone : MultiRotor;
        objective { verify installation; }
        @VerificationMethod { kind = VerificationMethodKind::analyze; }
    }

    analysis def LoiterWhatIf {
        subject uav : IsrPrime;
        in attribute loiterSpeed : Real = uav.loiterSpeed;
        // bounds mined from IsrPrime: aboveStall / belowCruise
        @ToolExecution { toolName = "longeron.analysis.mdao";
                         uri = "build_problem"; }
        return stationMinutes : Real = uav.stationMinutes;
    }

    verification def StationConsistency {
        subject uav : IsrPrime;
        objective { verify IsrStation; }
        @VerificationMethod { kind = VerificationMethodKind::analyze; }
        @ToolExecution { toolName = "longeron.analysis.smt";
                         uri = "to_smt"; }
    }

    analysis cameraWhatIf : CameraWhatIf;
    verification installationCheck : InstallationCheck;
    analysis loiterWhatIf : LoiterWhatIf;
    verification stationConsistency : StationConsistency;

    view def GrandTour {
        doc /* The grand-tour surface: any craft, its cases,
               its panels. */
    }

    view grandTour : GrandTour {
        expose Rotorcraft::QuadCopter;    // the home subject

        view structurePane { expose DeepScout::**; render asStructureDiagram; }
        view cadPane { expose Rotorcraft::QuadCopter; render asMeshViewer; }
        view boardPane {
            expose ScoutMissions::scoring;
            expose ScoutSurfaces::installationCheck;
            render asScoreboard;
        }
        view cameraPane { expose ScoutSurfaces::cameraWhatIf; render asWhatIfCard; }
        view sizingPane { expose ScoutSurfaces::loiterWhatIf; render asSizingCards; }
        view verdictPane { expose ScoutSurfaces::stationConsistency; render asVerdictCards; }
        view missionPane { expose DeepScout::FlightStates; render asMissionGlobe; }
    }
}
```

Every Python constant from the gap table now has a model home. The
what-if attributes are the cases' in parameters. The camera ranges
are assume constraints (they were never in the model at all -- an
honest new statement, not a relocation). The loiter range is mined
from `IsrPrime`'s existing constraints, so the model states 11..24
once and the slider and the design-variable box both derive from it.
The requirement picks are `verify` members. The engine choices are
`ToolExecution` annotations. The subject is one expose.

### Subject swap and honest absence

The dashboard's own expose names the home subject. The config-click
seam keeps working: `bind_config_view` resolves a diagram click to a
configuration, and the engine re-binds every case to the new subject
-- when the case admits it. Admissibility is subject typing: a case
applies to a configuration when the configuration's specialization
chain reaches the case's subject type. Verified on the program:
`HexaCopter` reaches `MultiRotor` through its `supers`, so
`CameraWhatIf` and `InstallationCheck` re-derive for the hexa -- its
camera, its geometry, its own occlusion verdict. `LoiterWhatIf`'s
subject is `IsrPrime`, which no rotorcraft configuration reaches, so
the sizing and consistency panels do not apply to the hexa.

A case that does not apply renders as honest absence: the panel
stays in the layout, dimmed, stating the subject type it needs
("LoiterWhatIf applies to IsrPrime"). Silently dropping the panel
would hide the model's shape; pretending it applies would fabricate
a measurement. The absence card is the surface-level analogue of the
scoreboard's unmeasured-leaf NaN semantics.

### The derivation engine

A new module, `analysis/surfaces.py`, turns the declaration into the
composed widget:

```text
surface(model, "ScoutSurfaces::grandTour")
  -> the view usage           (model.find + views.list_views machinery)
  -> panel graph              (per subview: expose_closure -> content,
     |                         render reference -> rendering name)
  -> per analysis case:
     |   in parameters        -> sliders
     |   attribute_domains    -> slider bounds + design-var box (mined)
     |   @ToolExecution       -> the measure runner (registry)
     |   named returns        -> readouts + measured-value keys
     |   MaximizeObjective    -> the optimize affordance
  -> per verification case:
     |   verify members       -> the requirement rows
     |   subject typing       -> applicability (honest absence)
     |   @ToolExecution       -> smt / scoreboard / interpreter check
  -> wiring derivation        (returns meeting same-named requirement
     |                         attributes couple panels: occludedFraction
     |                         flows from cameraWhatIf into every panel
     |                         verifying installation -- the values= seam,
     |                         now derived instead of hand-merged)
  -> widget composition       (rendering name -> builder registry, the
                               views.py VIEW_DEFINITIONS mapping-table
                               precedent; selection seam wired by
                               link_selection / bind_config_view)
```

The registry maps rendering qualified names to builders, exactly as
`views.py` maps view-definition names to diagram builders. A
rendering the registry does not know warns and renders the absence
card (the `_known_options` forward-compatibility posture).

The wiring map that grand.py hand-writes becomes a derivation. Today
the camera observer re-measures, merges
`{"occludedFraction": ..., "discOverlapVolume": ...}` into `values=`,
and repaints the scoreboard -- the coupling exists because the
analysis return and the requirement's measured attribute share a
name. The engine derives the same edges: an analysis return couples
to every exposed verification case whose verified requirements
declare a same-named measured attribute. Where an author wants the
coupling explicit, the corpus binding idiom
(`attribute :>> occludedFraction = cameraWhatIf.occludedFraction`)
is recognized first; the name convention is the fallback, and the
scoreboard's `values=` seam is the unchanged transport.

`grand_dashboard` becomes the wrapper: when the model carries a
surface declaration it calls
`surface(model.find("ScoutSurfaces::grandTour"))`, and its keyword
arguments survive as overrides during the transition. The demo
choreography (the event feed, the route) stays notebook input.

### What stays code, honestly

- **Layout aesthetics.** Row heights, the CSS card chrome, flex
  pinning, slider steps and debounce -- presentation, not content.
  The view-persistence sidecar tier is the designated home if any of
  it ever needs to persist; the model never carries pixel numbers.
- **The wiring mechanics.** Reentrancy guards, first-fixpoint
  writes, observer disposal -- the seam discipline the selection and
  time designs already own.
- **The measure implementations.** `occlusion_report`, the mdao
  bridge, the smt encoder: `ToolExecution` names them; the model
  never contains them.
- **The demo choreography.** `FLIGHT_EVENTS` and `ATLANTA_LOOP` are
  a demo's script, not the craft's data. The time design's phase 3
  migrates waypoints and the epoch onto model seams
  (`model_waypoints`, `Time::Iso8601DateTime`); this design does not
  duplicate that work.

## Migration path

1. **Vendor the two corpus files**: `TradeStudies.sysml` and
   `AnalysisTooling.sysml` into `src/longeron/_stdlib/` (both parse
   against the shipped resolver; `TradeStudies` references
   `ControlFunctions`/`ScalarFunctions`, the `KernelShim` posture
   from the geometry design applies).
2. **Fix the two miner gaps** in `verify`: fold unary-minus literal
   bounds, and mine objective-nested constraints (the spec's own
   home for a case's assumptions).
3. **Ship `LongeronSurfaces`** beside the vendored stdlib, and the
   builder registry in `analysis/surfaces.py`.
4. **DeepScout grows `surfaces.sysml`** (the declaration above). The
   program's open-closed posture holds: a new architecture file adds
   its own cases without touching the shared ones.
5. **`grand.py` becomes the engine's client.** `drone_scene`,
   `scene_for`, and `view_cone_part` stay (they are the mesh bakery,
   not choreography); the composition function shrinks to layout
   plus the `surface()` call. Byte-comparable behavior for the
   QuadCopter is the transition gate, mirroring the geometry
   design's builder-to-compiler rule.
6. **Tutorial 9 teaches the declaration**: the finale becomes "state
   the dashboard, derive it, click the hexa and watch the same
   declaration serve it."

## What we deliberately do not build

- **No layout language in the model.** No grid coordinates, no row
  heights, no colors as model content. Panels are subviews; order is
  declaration order; geometry belongs to the engine and, if
  persisted, to the sidecar tier.
- **No new widget framework.** The rendering vocabulary names the
  existing catalog; panels compose the widgets that exist.
- **No general filter-expression evaluation.** The views scope fence
  stands: metaclass filters evaluate, arbitrary expressions are
  preserved but not applied.
- **No viewpoint evaluation.** `ViewpointCheck` machinery parses and
  is preserved (the view-persistence posture); stakeholder
  conformance checking is not this design's job.
- **No live model editing from the surface.** Sliders write analysis
  inputs and `values=` bindings, never model attributes -- the
  scoreboard's injection semantics, kept.
- **No cross-model dashboards.** One surface, one model. The grand
  tour's `sizing` keyword already defaults to the one DeepScout
  program; the declaration drops the second model entirely.

## Phasing

The finish-then-tag posture holds. The standing queue -- provenance
layers 1-2 and the time seam inside 0.12, geometry phase 1 opening
0.13 -- is not displaced; the slices below are sized to slot behind
it.

- **Phase 1 -- two panels, two subjects (the smallest honest
  slice).** Vendor the two corpus files, fix the two miner gaps,
  ship `LongeronSurfaces` and the engine core (panel graph, domains,
  applicability, registry), and derive exactly two panels from
  declarations: one what-if card (`CameraWhatIf`) and one
  verification panel (`InstallationCheck`) -- for the QuadCopter
  *and* the HexaCopter from the same declaration, with
  `LoiterWhatIf` present and honestly absent on both. Headless
  tests drive the sliders and assert the derived coupling.
  Deliverable: the same declaration serves two architectures, which
  is the design's entire point in miniature.
- **Phase 2 -- the full grand tour.** All seven panels declared in
  `surfaces.sysml`; the engine composes the existing panes; the
  wiring map derives; `grand_dashboard` re-homes as the wrapper;
  subject swap re-derives every panel through `bind_config_view`;
  tutorial 9 rewrites its finale. The time seam's clock row joins
  here if its phase 2 has landed.
- **Phase 3 -- authoring UX.** `save_surface` promotes a composed
  dashboard into a declaration (the `save_view` idiom); the sidecar
  presentation tier extends to surfaces; `mission_dashboard` is
  assessed against the same vocabulary; `MeasureOfEffectiveness`
  metadata designates the header score.

## Open questions

1. **Grounding: view usage, or a dedicated metadata-annotated
   container?** A `@Dashboard`-annotated package would be simpler to
   author but would invent a container the standard already has.
   *Recommendation: the view usage. Exposes select, renderings
   present, subviews compose -- the corpus's own nested-views
   example is the shape, and `views.py` already reads all of it.*
2. **How does the rendering vocabulary bind to the widgets
   catalog?** Candidates: a Python registry keyed by rendering
   qualified name, or `ToolExecution`-style URI metadata on each
   rendering usage. *Recommendation: the registry (the
   `VIEW_DEFINITIONS` mapping-table precedent); metadata binding
   only if third-party widgets ever need to join without touching
   longeron.*
3. **Ranges: mined, or explicitly declared?** A dedicated range
   metadata (`@SliderRange { lo; hi; }`) would be direct but would
   duplicate truth the constraints already state.
   *Recommendation: the mining ladder, with assume constraints in
   the case objective as the authoring idiom for bounds the subject
   does not state; the two miner fixes make it whole; unmined sides
   keep the flagged-fallback honesty.*
4. **Subject polymorphism: where does applicability live?**
   Per-configuration panel lists would be explicit but quadratic.
   *Recommendation: subject typing is the applicability test (the
   specialization walk, verified above), and refusals render as
   honest absence -- the model's own typing already says which cases
   fit which craft.*
5. **Where do the Z3/OpenMDAO panel bindings live?** Candidates:
   grow the house `@ExternalAnalysis`, keep bindings in Python, or
   adopt the standard's `@ToolExecution`.
   *Recommendation: `@ToolExecution` at the case level (vendored,
   standard, made for exactly this); `@ExternalAnalysis` stays at
   the calc level for component fidelity, unchanged.*
6. **Coupling spelling: name convention or explicit binding?** Today
   `occludedFraction` couples panels because two declarations share
   a name. *Recommendation: recognize the corpus's explicit result
   binding (`:>> attr = case.result`) first, keep the name
   convention as the documented fallback, and report which rule
   fired in the derived wiring map.*
7. **Timing against the 0.12 arcs?** The engine touches no widget
   front-ends, but phase 2 rewrites the tutorial finale.
   *Recommendation: phase 1 as a short arc late in 0.12 behind
   provenance and the time seam's phase 1; phase 2 rides 0.13
   beside geometry phase 1, which grounds the same pane
   (`GeometryView`) and wants the same subject-swap story.*
8. **Authoring ergonomics: hand-written declarations, or a builder
   that writes them?** *Recommendation: hand-authoring first -- the
   declaration is the deliverable, and the DeepScout example doubles
   as the documentation; `save_surface` arrives in phase 3 once the
   derived direction is stable, mirroring how `save_view` followed
   the diagram builders.*

## References

- OMG Systems Modeling Language (SysML) v2.0, Part 1: §7.22 Cases
  (printed p. 169), §7.23 Analysis Cases (p. 170, trade-offs
  §7.23.3 p. 172), §7.24 Verification Cases (p. 173), §7.26 Views
  and Viewpoints (p. 181), §9.2.15-9.2.17 (Cases / AnalysisCases /
  VerificationCases libraries, pp. 532-536), §9.2.19 Views (p. 539),
  §9.2.20 Standard View Definitions (p. 545), §9.3.4 Parameters of
  Interest Metadata (p. 558), §9.4.2 Analysis Tooling (p. 562),
  §9.4.5 Trade Studies (p. 568).
- Pinned corpus at `de1070ae`: `Systems Library/{Cases,AnalysisCases,
  VerificationCases,Views,StandardViewDefinitions}.sysml`, `Domain
  Libraries/Analysis/{TradeStudies,AnalysisTooling}.sysml`, `Domain
  Libraries/Metadata/ParametersOfInterestMetadata.sysml`; the usage
  spellings in `sysml/src/training/{33. Analysis, 34. Verification,
  42. Views}`, `sysml/src/validation/{10-Analysis and Trades,
  11-View and Viewpoint}`, and the Annex A vehicle model.
- Longeron surfaces: {mod}`longeron.analysis.grand` (the gap table's
  subject), {mod}`longeron.views` (`save_view`, `expose_closure`,
  the mapping tables), {mod}`longeron.analysis.verify`
  (`attribute_domains`), {mod}`longeron.analysis.smt` (`free=`),
  {mod}`longeron.analysis.mdao` (`build_problem`,
  `component_spec`), {mod}`longeron.analysis.link`
  (`bind_config_view`), {mod}`longeron.widgets` (the catalog),
  `examples/deepscout` (the program), `examples/
  analysis_conventions.sysml` (the convention precedent).
- Sibling designs: [view persistence](view-persistence.md) (the
  two-tier scheme, the scope fences), [geometry](geometry.md)
  (extension packaging, `GeometryView`, the vendoring posture),
  [time](time.md) (the clock row, the seam discipline,
  model-stated bindings), [verify](verify.md) (the domain ladder),
  [mdao-objects](mdao-objects.md) (convention packages, case-is-
  an-interpretation).
- Verified versions: longeron 0.11.0 at `f1d9d29`; corpus pin
  `de1070ae`; the surfaces sketch validated with zero diagnostics
  against the shipped DeepScout program.
