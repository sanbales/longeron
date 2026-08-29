# Release notes

## 0.11.0 (unreleased)

- **`longeron.analysis.verify`: model-driven requirement-violation
  hunting** ([design doc](design/verify.md); supersedes and
  retires the `_verify_spike` prototype): the model fights back, from
  nothing but the `.sysml` text. Four tiers over one oracle -- every
  verdict is the interpreter's, solvers only propose:
  - **`hunt`** (Hypothesis, `pip install "longeron[verify]"`): sampling +
    shrinking over strategies *derived from the model* -- attribute
    types, mined `assert` bodies, and exact Z3 bounds pushed through
    `smt.py`'s reachability fixed point under the assumption set (bounds
    living only on derived attributes are found, honestly flagged
    fallbacks otherwise). The shrunk catch is paired with
    interpreter-bisected edges per violated check (`report.boundaries`)
  - **`sequences`**: one generic rule + one invariant over the *real*
    `StateMachine`; shrinking strips every irrelevant event. The drone
    example gains a genuinely sequence-sensitive trap (`SortieStates`'
    go-around path re-enters `airborne` past the launch guard's battery
    floor; `SafeSortie`), and verify finds the minimal 4-event sortie
    `launch, goAround, goAround, goAround` on shipped examples only
  - **`cover`**: in-house IPOG-F t-way covering arrays (t = 2..6, pure
    stdlib, no new dependency; documented ceilings refuse loudly), Z3 as
    the constraint engine for `assume=`d build rules through the model's
    own constraint bodies, every row settled interpreter-exact, and
    violated-check recall *measured* against exhaustive ground truth
    while that stays feasible (100% on both shipped catalogs). Validated
    by an independent coverage checker + generator property tests +
    published-benchmark size comparisons (TCAS t=2..6 within ~3% of
    Lei et al.'s IPOG sizes, recorded in `_ipog.py`)
  - **`prove`**: absence proofs by negating one check at a time under
    the assumption set (UNSAT = no configuration can violate -- sampling
    can never say that), SAT witnesses believed only after interpreter
    re-check, and exact rational bounds attributed to their binding
    constraint (max drone payload = `23/50` kg, bound by
    `takeoffMassLimit`)
  - `verify.verify` dispatches by scope kind; every catch
    `materialize()`s to identified M0 individuals; vacuous passes
    (violated assumptions) are recorded, never coerced into failures;
    every Hypothesis run is derandomized with seeds echoed on the report
  - the SMT encoder now walks *anonymous* requirement constraints too
    (an unnamed `assume` was silently dropped -- a latent false-`proven`
    bug, fixed for `prove` to land)
  - notebook 07 gains the "find my violations" beat: hunt, the minimal
    sortie, the covering array with its measured-recall line, and the
    hoverMargin absence proof, executing with or without the extra
  - extras restructured: `verify = ["hypothesis>=6.100",
    "longeron[smt]"]`, plus composites `analysis`, `ui`, and `all`
    (`cad` deliberately excluded from `all`)
- **Object-valued analysis I/O in the OpenMDAO bridge**
  ([design doc](design/mdao-objects.md), all seven decisions
  adopted): objects -- not just scalars -- cross `build_problem`, on
  OpenMDAO's stock discrete-variable machinery (no fork)
  - **Entity binding**: variation-typed part/item members become
    discrete inputs carrying the configured **M0 individual** instead
    of a scalar shred. The case being evaluated is an
    `m0.interpret(...)` interpretation (`build_problem(...,
    interpretation=...)`; models with variation points materialize the
    implicit anonymous point lazily -- scalar-only models pay nothing
    and behave exactly as before). `bind_entity()` swaps cases
    (qname-resolved, conformance- and pickle-checked); `entity_cases()`
    turns a trade study's catalog into `DOEDriver`-ready cases of
    individuals (variant body redefinitions honored, riding the 0.11
    variant-bundle fix)
  - **Result recording**: `record_case()` freezes each evaluated case
    as a NEW immutable interpretation snapshot -- outputs land as
    attribute values on the case's individuals (stable
    `qname#index` ids, JSON-clean `to_dict()`, `rollup()` over the
    recorded population); the input interpretation stays pristine.
    `case_values()` feeds a snapshot straight into the scoreboard's
    `values=` seam. `Individual` gained the `to_json` recorder hook, so
    a recorded entity case reads back as its full bundle, never as the
    class-name string `'Individual'`
  - **The file boundary**: `FileArtifact` (path + sha256 + media type)
    flows as ~200 bytes of discrete value while the bytes stay on disk
    -- `ExternalCodeComp`-compatible, hash as caching identity,
    `to_json` as the lossless recorder seam. `write_artifact()` /
    `file_artifact()` build one; `artifact_component()` wraps a writer
    callable as a boundary component. The matching SysML convention
    ships as `examples/analysis_conventions.sysml`
    (`item def FileArtifact`), so flows can be typed by it
  - **Item-flow wiring derivation**: `derive_flows()` resolves a
    part's `flow of Payload from a.out to b.in` usages into proposed
    OpenMDAO connections -- the same resolution semantics as the new
    `dangling-flow`/`flow-payload-mismatch` validation (plus
    direction checking, which a `connect()` needs) -- and
    `apply_flows()` wires them. Propose + apply, never silent magic
  - Picklability is asserted at bind time with an error naming the
    offender (the recipes-not-solids rule enforced); serial discrete
    transfers alias by reference, so payloads stay frozen by
    convention. Tutorial 07 closes with a discrete motor-entity case
    swap and a `FileArtifact` roundtrip

- **Units, tiers 2 and 3 of the units design**
  ([design doc](design/units.md)): models with `[SI::kg]`-style
  measurement annotations now get a real dimensional lint, and an
  optional typed conversion facade
  - **The dimensional lint** (`longeron lint` / `validate()`, zero new
    dependencies): five diagnostics over exponent vectors WITH scale
    tags, derived from the vendored quantities library's own
    definitional algebra (`newton = kg*m/s^2` survives in the model and
    seeds the table; all 257 vendored units derive, none hand-coded).
    `unresolved-unit` closes the deliberate unit-reference skip;
    `dimension-mismatch` catches the motivating bug (`mass [kg] +
    flightTime [min]` -- previously a silent `35.0`); `scale-mismatch`
    is an ERROR for cross-scale `+`/`-` (`dBW + W`, `°C + K` -- the
    interval scale marks °C offset so it can never pose as a linear
    kelvin); `mixed-units` warns on same-dimension-different-unit
    arithmetic without the `[units]` extra; `anchor-dimension-mismatch`
    checks scoreboard ramp/target anchors against their `measure`.
    Unknown dimensions are bottom and propagate silently -- unitless
    models validate exactly as before. Guide:
    [The dimensional lint](guides/validation.md#the-dimensional-lint)
  - **`longeron.units`**: the derived unit table is public --
    `unit_table()` / `derive_units()` (user unit packages shaped like
    the stdlib derive with NO mapping table, per the foreign-packages
    decision), `register_unit()` for overrides, and a pint-backed typed
    facade behind `pip install "longeron[units]"`: `convert()` (linear,
    offset °C, logarithmic dBm/dBW), `si_value()`, `si_unit()`,
    `format_quantity()` and `om_unit()` (both pint-free), `with_units()`
    (pint-pandas dtypes for M0/trade tables), `define()` pint
    pass-through. pint never leaks: floats and unit strings in, floats
    out; the registry is a lazy singleton, and `import longeron` stays
    pint-free
  - Interpreter, instance slots, M0, and `compute()` bodies still see
    only floats -- declaration-boundary SI normalization and the
    OpenMDAO/scoreboard conversion hooks are documented seams
    ([reference](reference/units.md#conversion-seams-reserved-for-011))
    wired next release

## 0.10.0

- **The JupyterLab app** (`longeron.app` + `longeron.inspector`):
  `app.open()` docks a left-sidebar panel behind a theme-aware
  model-diagram icon -- load models (path field, multi-select Browse
  over the kernel's filesystem, a collapsible Systems-Modeling-API
  connect), then launch per-model tabs: [Explore] (the explorer),
  [Score] (the scoreboard), [Save]/[Push] with a dirty indicator fed
  by `edit.track`. The ITEM INSPECTOR docks in the right sidebar: a
  selection-driven property sheet (kind, typings, multiplicity,
  relationship endpoints as clickable navigation) where name,
  documentation, and attribute values EDIT through `longeron.edit` --
  refusals render as inline error strips, units show in value
  expressions, and the sidebar reveals itself once on the first
  selection. The app adopts explorers created directly in the kernel,
  so `explore()` users get the inspector too. `longeron:open-app`
  rides the command palette. Tutorial 14
- **Relationships in the explorer tree**: satisfies, connections,
  bindings, interfaces, allocations, flows -- plus newly admitted
  imports, exposes, dependencies, filters, and aliases -- appear under
  the element that OWNS them, dim-italic with relation chips and
  derived labels ('connect axle to hub'), full declaration on hover.
  A tree-toolbar toggle shows/hides them (synced trait); where the
  relationship draws as a diagram edge, selection round-trips both
  ways
- **Diagrams size and fit themselves, everywhere**: the fit-on-reveal/
  resize machinery moved into the builders -- bare `display(widget)`,
  HBox panes, explorer tabs, and restored views all self-fit on first
  reveal and container resize (user pan/zoom is never fought); the
  explorer's docked pane fills its tab; builders take `height=`.
  Compound nodes under top-down flow no longer overflow their labels
  (an elkjs transposed-sizing bug, fixed at the layout-options source),
  and `max_label_width` (default 480px) ellipsizes absurd
  calculation rows kernel-side -- measurement, sizing, and the fits
  all see the display string -- with the full text on hover
- **Geometry as requirements, CAD-native**: the drone example splits
  its rotors into motors x propellers (separable variation points,
  thrust as a calc over the pair) and gains a camera whose view is a
  requirement: `camera_occlusion` builds a VIEW CONE solid and
  boolean-intersects it against every other component
  (`occludedFraction`, per-part obstruction volumes), and prop discs
  prove non-overlap the same way (`discOverlapVolume`). Exact OCC
  booleans with the `[cad]` extra; without it, a deterministic
  quadrature integrates the same integral. Both land on the
  scoreboard like any other requirement
- **The grand tour** (`longeron.analysis.grand`): `grand_dashboard(
  model)` composes the whole toolchain into one reactive surface --
  structure diagram, 3D airframe with the translucent view cone,
  scoreboard voronoi, camera what-if sliders that re-run the occlusion
  check and repaint the board live, OpenMDAO sizing cards, Z3 verdict
  cards (a design-point SAT witness beside an impossible what-if's
  UNSAT core), and the Cesium mission finale. Tutorial 15 builds it in
  five code cells; `scripts/record_demo.py` films it deterministically
  for the README
- **Units groundwork**: the adopted [units design](design/units.md)
  (model-tier stdlib units, an in-house dimensional lint with scale
  tags, pint behind a typed facade at the boundaries only); bracket
  units (`1.5 [SI::kg]`) now appear across the examples, render in
  expression text everywhere (inspector value rows included), and the
  scoreboard displays a reserved `unit` attribute in tooltips and
  tables -- scores themselves default to percent with one decimal
  (`value_format=`)
- - **Model editing** (`longeron.edit`): a small, verified mutation API
  -- the seam UI inspectors change element properties through.
  `rename` validates the new name, rewrites *every* textual reference
  that reaches the renamed element or its descendants (typings,
  subsets, redefines -- including same-named `:>> x` self-shadowing
  redefinitions -- connector ends, satisfy targets, exposes, imports,
  aliases, dependency ends, state-machine transitions, and the names
  inside owned expressions), and then re-resolves the whole model to
  prove nothing changed meaning; whatever cannot be proven safe
  (member access on computed values, name capture through shadowing)
  is refused with an `EditError` listing the sites -- honest refusal
  over corruption. `set_attribute_value` parses expression text and
  preserves `default =`/`:=` flags; `set_doc` creates (append-only),
  updates in place, or removes documentation, with multi-line bodies
  now exporting in a canonical comment form that round-trips at a
  fixpoint. No operation reorders siblings, so index-path element ids
  stay stable. `edit.track(model)` returns a lightweight `Tracker`
  (`dirty`, `changes`, `on_change`, `mark_saved`) that every edit
  records into -- the app layer's save-prompt seam
- **View persistence** (`longeron.views`): diagrams save as SysML v2
  views and restore from them, per the
  [design](design/view-persistence.md). `save_view` appends a
  `ViewUsage` -- typed by the matching `StandardViewDefinitions` view
  definition, exposing the shown scope (`expose Pkg::**`), with a
  `render Views::asInterconnectionDiagram` reference -- to the scope's
  owning package; the standard tier round-trips through `.sysml` text
  and the Systems Modeling API and is legible to any conformant tool.
  Presentation (direction, routing, collapse state, builder options)
  lives in a small versioned sidecar (`.longeron/views.json`, keyed by
  view qualified name); `restore_view` picks the builder from the
  typing, resolves the expose closure through the resolver (metaclass
  filters evaluate), and re-applies the sidecar -- dangling exposes
  warn and skip, never raise. The API projection now emits
  `MembershipExpose`/`NamespaceExpose`/`ElementFilterMembership`
  records (it used to silently drop every expose and filter), view
  usages draw as `«view»` boxes in structure diagrams, `validate`
  gained the `dangling-expose` diagnostic, and the explorer's header
  grew a save button (`Explorer.save_view`)
- **The requirements scoreboard** (`longeron.analysis.scoreboard`): a
  MAUT (multi-attribute utility) layer over the requirements
  hierarchy. Importance weights and utility shapes are declared IN THE
  MODEL as plain attributes on requirement usages (`weight`,
  `utility`, `measure`, plus shape anchors; typed usages inherit from
  their requirement definition), raw measures evaluate through the
  interpreter, and aggregation up the hierarchy is pluggable (SAW by
  default; weakest-link and geometric built in). `values=` injection
  scores any design point without touching the model --
  `architecture_values` bridges trade-study `Architecture` results
  directly. One anywidget renders it as a squarified treemap or a
  Voronoi tessellation (the vendored BSD-licensed d3-voronoi-treemap)
  where area is importance and color is utility on a perceptual
  OKLab red->yellow->green ramp; hover for details, click to select
  (linked-selection-ready `selected` trait), double-click to zoom
  into a subtree (breadcrumb bar + Esc to zoom back out), a twist on
  every group to collapse it in place into one aggregated cell, and a
  `max_depth` render window for deep hierarchies (all of it --
  `selected`, `collapsed`, `zoom_root`, `max_depth` -- scriptable as
  two-way traits; zoom and depth are view state, never scoring
  state); unmeasured
  requirements render hatched grey. Tutorial 13 walks it end to end
- **Mission flight replay on a globe**
  (`longeron.analysis.mission3d`): the model's mission flies on a real
  CesiumJS globe. `mission_track` turns explicit `(lat, lon, alt[, t])`
  waypoints (or `model_waypoints`, read off a mission part's children
  through the interpreter) into a timestamped geodetic track;
  `from_replay` drives the same synthesis from the state machine's
  ACTUAL execution -- the replay recorder's timeline maps each leaf
  state onto a motion segment (takingOff = vertical climb, flying and
  loiter share the waypoint route proportionally to their time,
  landing = descent, everything else holds position), so durations,
  interleavings, and reentries paint straight onto the flight path.
  `mission_viewer` plays the track's CZML document on a Cesium
  `Viewer`: planned-route polyline, waypoint pins, a drone entity with
  a trail whose label follows the active state name, camera tracking
  with a route-sized offset, and Cesium's native timeline + animation
  dial as the playback UI (plus a bidirectional `time` trait and a
  `picked_json` click seam, viewer3d idiom). Pass `mesh=` (the
  geometry module's mesh dict) and the drone's own to-scale airframe
  flies the route nose-first: an in-house, stdlib-only binary glTF
  exporter (`mesh_to_glb`) embeds the parts -- per-part colors,
  translucent prop disks, flat shading -- as a `data:` URI whose
  orientation follows the velocity vector. No Cesium ion token is
  required -- `imagery=` picks the tokenless base: Esri World Imagery
  satellite tiles (the default), a plain dark-slate globe, or
  OpenStreetMap streets, all on the plain ellipsoid; `ion_token=`
  unlocks Cesium World Terrain/imagery.
  CesiumJS (~6 MB) loads from a pinned jsDelivr CDN URL at view time
  (the viewer3d tradeoff, a fortiori) and degrades to an honest
  offline notice without it

## 0.9.1

- **The `sysml2` alias is removed** — the `sysml2` PyPI name and
  namespace were ceded to the [OpenMBEE](https://www.openmbee.org/)
  organization. Gone completely, with no deprecation period: the
  bundled `import sysml2` compatibility shim (which shipped inside the
  longeron wheel and would file-collide with a future OpenMBEE `sysml2`
  package), the `sysml2` console command, the `sysml2` metadata-only
  alias distribution, and the `$SYSML2_CACHE_DIR` cache-directory
  fallback. Replace `import sysml2` with `import longeron`, the
  `sysml2` command with `longeron`, and `$SYSML2_CACHE_DIR` with
  `$LONGERON_CACHE_DIR`
- Note: 0.9.0 shipped wheel-only on PyPI (since yanked)

## 0.9.0

- **The notation program completes** (tranche 3 + polish): ports render
  ON node borders with direction arrows derived from the port
  definition (conjugates flip, stay textual per the spec); directed,
  n-ary, and proxy connections; allocations draw at all (the old
  dispatch branch was dead code); package folder tabs; def/usage
  corner distinction; comment/doc notes with dashed anchors and
  metadata adornments (`annotations=True`); actors draw the spec's
  stick figure by default (`actor_style="box"` keeps the keyword box)
- **A universal adornment contract**: tabs, badges, and ports are
  built through one path and styled by one rule family, so selection
  AND hover treat a node and its adornments as one shape -- and a
  discovery test fails the suite if a future adornment skips the
  contract; hovering a tab/label now highlights its owning node
  (vendored patch 10)
- **Tutorial 11, the notation gallery**: every implemented glyph
  beside its spec figure with self-verifying asserts, plus the new
  [notation coverage guide](guides/notation-coverage.md) stating
  honestly what is drawn, approximated, and deferred
- **Tutorial 12, the model explorer** (`longeron.explorer`): a
  searchable, keyboard-navigable tree over the owning structure beside
  a diagram pane with per-selection kinds (structure/state/action/
  requirements), echo-free two-way selection, and JupyterLab shell
  docking via the `[explorer]` extra (ipylab)
- **Toolbar**: edge-routing toggle (orthogonal/polyline/splines),
  layout-direction toggle (L-to-R / T-to-B), and diagrams now open
  fitted and centered; endpoint symbols orient correctly along
  polyline and spline routes (vendored patch 8, arc-length tangents)
- **Browser-truth test tier**: playwright scenarios in CI (gallery
  sweep, replay arrowheads, selection-safe search, explorer round
  trip, and a layout-failure canary) with a labextension sync task
  that ends the stale-served-bundle class of bug
- **Failure semantics**: a failing browser layout now surfaces a
  visible warning instead of retrying forever (vendored patch 9,
  backported from the upstream ipyelk PR this work also feeds);
  element ids are transport-ready from birth (the infinite-load
  incident class is closed end to end)
- Replay renders arrowheads in Chromium (vector-effect removed from
  edge paths -- a bug as old as the widget); connector-end cross
  multiplicities and end-prefix multiplicities now survive the builder
- Design doc: [longeron and OpenMBEE integration paths](design/openmbee-integration.md)

## 0.8.0

- **Spec-exact SysML v2 graphical notation**, grounded in the OMG 2.0
  spec's figures and clause 8.2.3 BNF (a rendered notation atlas of all
  205 element rows drove the work; every glyph family ships with an
  implementation-vs-spec evidence sheet):
  - specialization family: solid lines, closed hollow triangle heads,
    shaft adornments mirroring the textual characters -- typing `:`
    colon dots, redefinition `:>>` bar tick, reference subsetting `::>`
    2x2 dots; keyword edge labels dropped
  - membership: filled (composite) / hollow (`ref`) diamonds with role
    + end multiplicities via `structure_diagram(composition=)`; owned
    membership as the spec's p.26 edge presentation via
    `membership="edges"` (true circled-plus); alias members draw a
    hollow circle + name
  - connector-end multiplicities render at both ends (the builder now
    captures what the grammar always parsed)
  - flow connections: border pins, filled head at the target pin,
    payload labels; satisfy draws the p.133 form exactly; dependency
    (incl. n-ary junction) and binding `=` edges; portion membership's
    notched ball; `individual`/`timeslice`/`snapshot` keywords
  - behavior views: done bullseye, terminate circle-X, fork/join bars,
    decision/merge rhombi with single in/out convergence anchors,
    accept/send as boxes with spec-form top-left badges, dashed action
    successions, `action_diagram(lanes=)` performer swim lanes,
    actor/stakeholder keyword boxes
  - all arrowheads re-derived from single-source ~27-degree slender
    geometry in both pipelines
- **State diagrams expand typed submachines** (`submachine_depth`),
  cycle-protected; replay keys became instance-qualified -- two
  expansions of one submachine no longer cross-highlight
- **Compact diagram toolbar**: icon buttons with tooltips plus a
  search box that highlights every matching element (never touches the
  selection -- `on_select` provably cannot fire); collapse-stub ports
  take their node kind's palette color
- **Diagrams meet CAD** (`longeron.analysis.link`): bidirectional
  linked selection between structure diagrams and the three.js viewer
  -- M1 selections fan out to M0 individual meshes, 3D picks project
  back (with the picked individual surfaced); tutorial 10 teaches the
  M1/M0 distinction through it; `drone_geometry(split_instances=True)`
- Diagnostic-location test made Windows-safe (the only red CI leg)
- Design docs: the OCL stance recorded
  ([the OCL stance](design/ocl-stance.md))

## 0.7.1

- The five 0.7.0 known issues are fixed: bare `individual`/`snapshot`/
  `timeslice` usages reprint without doubling the keyword, variant
  references keep their specializations, state entry/do/exit inline
  action bodies survive reprint, KerML case result expressions emit as
  valid owned expression features, and `satisfy <Def> by x` projects
  to ecore/API records without crashing (FeatureTyping, not a
  Subsetting to a Classifier)

## 0.7.0

- **Lossless JSON omission**: `to_dict` dropped every falsy field
  unconditionally while import hid omissions behind dataclass defaults
  -- a True-valued flag could vanish silently, including through the
  model cache. Omission is now default-aware; all 36 boolean fields on
  all element types round-trip exactly (old JSON still imports; output
  is byte-identical for well-formed models)
- **Coverage 87% -> 93%** with meaningful tests: the audit's surviving
  mutation probes killed, 20 new round-trip sources over the previously
  untested builder surface (case bodies, exhibit states, inline
  performs, event occurrences, individual/portion usages, variant
  references, metaclassification, ...), CLI/server/analysis suites
  deepened
- Diagrams: compartment rows left-align (UML convention) in both the
  browser and headless pipelines; the palette is single-sourced;
  exported SVGs carry a `<title>`
- Parse errors humanized: ANTLR `expecting {...}` soups become compact
  messages with the offending line and a caret (verbatim text kept on
  `SyntaxIssue.raw_message`)
- Every optional-extra guard raises `MissingExtraError` with a uniform
  `pip install longeron[extra]` message
- `Client.validate` forwards `strict_imports`; the README pip-route
  first run works in a fresh clone (vendored ipyelk install step)
- Perf: succession edges indexed once per plan; the cache fingerprint
  includes the serialization layer (one-time cache invalidation);
  `scripts/bench_cache.py` regenerates the warm-load numbers
- `merge_models` no longer mutates its inputs;
  `spec_from_api_json`/`spec_from_api_records` are the canonical names
  for the spec-metamodel importers (aliases kept)
- Breaking (0.x): `save(format=)` -> `save(fmt=)`; `to_dict`/`to_json`
  first parameter is `element`; `bindings` is reserved on
  `evaluate`/`instantiate`/`check_requirement` (a feature named
  `bindings` must use the mapping form); `Instance.set` raises
  `EvaluationError` (was `KeyError`/`AttributeError`)
- Known issues (found by the new tests, documented as skips; **fixed
  in 0.7.1**): four
  exporter reprint defects (doubled `individual` keyword on bare
  usages, variant-reference types dropped, inline state-action bodies
  dropped, bare case result expressions in KerML behavior bodies) and
  an ecore projection crash on `satisfy <Def> by ...`

## 0.6.0

- Validation diagnostics carry `file:line:column` (positions stamped by
  the builder; models rebuilt from JSON -- including warm cache hits --
  omit the prefix; `--no-cache` restores it)
- CLI failures print one-line actionable errors (`--traceback` opts
  back in); `longeron parse <dir>` reports every file instead of
  aborting at the first failure
- Structure diagrams pack disconnected members toward a ~1.6 aspect
  ratio instead of one tall column; packing grids escape the global
  layer spacing entirely (drone structure: 2.2:1 tall -> 1.14:1,
  -22% canvas area)
- `attribute x : Real :>> x` no longer reports a false
  `specialization-cycle` error (redefinition edges left the cycle walk)
- API server: working-tree model + record projection memoized behind a
  stat-only fingerprint -- paginated listings parse once; per-ref memos
  bounded
- `Env.assign` validates dotted paths before mutating the frame
- `longeron.*` no longer leaks `typing.Literal`, `dataclasses.field`
  et al.: `model.__all__` is explicit, guarded by `tests/test_public_api.py`
- One instantiation engine: `m0._Populator` shares the interpreter's
  `_PopulationEngine` core (identity, variant filtering, gap recording,
  and random defaults stay M0-specific)
- `scripts/check_corpus.py` reproduces the 309/309 corpus sweep from a
  pinned upstream commit; grammar-guide wording aligned with what the
  test suite actually re-checks

## 0.5.1

- Single-file loads use the content-addressed model cache by default
  (`cache=False` opts out) -- repeat CLI invocations on one file drop
  from ~9 s to ~0.1 s
- Interpreter: package-level attribute values that depend on the
  instance in scope are no longer memoized across instances, which could
  silently flip a constraint verdict (a failing check reported
  `passed=True`)
- `validate()` / `longeron lint` treat `library` packages as resolution
  context only, so `lint --stdlib` no longer floods diagnostics about
  library internals on a clean model
- Docs honesty: `builder`/`model` docstrings now describe the
  no-lossy-fallback coverage; stale test/coverage counts dropped from
  the README

## 0.5.0

- Tutorial 09: M0 interpretations (populations, gaps, sequences, the
  trades bridge) + `longeron.m0` reference page
- `POST /x/interpret/{qname}` extension endpoint wraps `longeron.m0.
  interpret()` (strategy/seed/bindings/selection in the body, the
  `Interpretation.to_dict()` JSON out), mirrored by `Client.interpret()`
  -- seeded random populations reproduce exactly over HTTP.

## 0.4.0

- **Systems Modeling API layer**: `longeron serve` exposes any workspace as an
  OMG Systems Modeling API server (FastAPI/uvicorn, `[server]` extra) with
  git-backed commits -- an API commit *is* a git commit -- plus `/x/`
  extension endpoints (`validate`, `instantiate`, `simulate`, `render.svg`);
  `longeron.client` (`[client]` extra) fetches any project/commit into a
  `Model` and pushes changes back. Verified end-to-end by a pilot-ecosystem
  client (pymbe).
- **API JSON navigability**: relationship records emit derived
  `source`/`target` endpoints by default (pilot-API schema; `--no-derived`
  restores the previous format).
- **M0 interpretations** (`longeron.m0`, stdlib-only): populations of
  individuals with stable identities from multiplicities (nominal/seeded-
  random), per-individual attribute evaluation, Annex-A sequences, roll-ups
  over the actual population, `from_architecture` and `from_timeline` --
  execution traces and static populations share one representation. Design
  doc with adopted decisions under *Architecture > Design documents*.
- **CI platform triangle**: Windows and macOS legs join the ubuntu matrix;
  `win-64` added to the pixi lock; git is a pinned conda dependency of every
  environment; workflows on Node24-native action majors.
- Badges (self-hosted coverage endpoint, corpus 309/309), trove classifiers,
  stale "pickle" wording purged (the prebuilt stdlib is JSON).

## 0.3.0

Highlights on `main` since the 0.2.0 release:

### Project rename

- **The import package is now `longeron`** (matching the distribution
  name); the CLI gains a `longeron` command. The historical `sysml2` names
  keep working unchanged: longeron ships a built-in `sysml2` compatibility
  shim (same module objects, no deprecation warnings), the `sysml2` console
  command remains, and `$SYSML2_CACHE_DIR` is still honored behind the new
  `$LONGERON_CACHE_DIR`.

### The analysis stack

- **`longeron.analysis`** — analytical bridges from executable models onto
  external solvers, each behind its own extra:
  - {mod}`longeron.analysis.mdao`: part trees and calcs project onto OpenMDAO
    `Problem`s (derived attributes → components, free attributes → design
    variables, constraints → margin outputs), with `@ExternalAnalysis`
    annotations binding higher-fidelity components in place of calc bodies.
  - {mod}`longeron.analysis.trades`: discrete architecture trade studies over
    variation/variant catalogs on OR-Tools CP-SAT, scored interpreter-exact.
  - {mod}`longeron.analysis.smt`: requirement consistency, conflict cores, and
    design-space bounds on Z3.
- **Views over the analyses**: honest Pareto fronts with explicit senses,
  publication-quality figures, an interactive parallel-coordinates widget
  with editable brushes ({mod}`longeron.analysis.viz`), an N2 matrix in the
  NASA/OpenMDAO convention plus connection-network views
  ({mod}`longeron.analysis.structure`), and the linked mission-compromise
  dashboard ({mod}`longeron.analysis.dashboard`).
- **To-scale 3D**: parametric meshes for architecture mixes (box quad,
  teardrop quad, cruciform tail-sitter VTOL, interceptor) with a three.js
  viewer ({mod}`longeron.analysis.geometry`, {mod}`longeron.analysis.viewer3d`);
  cadquery solid/STEP export behind the `cad` extra.
- **Physics fidelity**: drag buildup, load-sized structure, and a
  multi-mission UAV catalog example (`examples/uav_missions.sysml`) driving
  tutorial 7.

### Language and validation

- **100% OMG-corpus conformance** — grammar patches 6–10 (transition clause
  order, optional `standard`, named send nodes, one-line multiline notes,
  metadata prefixes on enumerated values) plus matching builder fixes.
- **Strict-imports validation** and `isImplied` on the API export.

### Everything else

- Replay v2: action executions replay over the action diagram, step-mode
  scrubbing, scalar-env readouts.
- `sysml2` kept as a PyPI alias distribution of `longeron`.
- ruff format adopted for code *and* notebooks.
- The vendored ipyelk labextension is now built from the patched
  TypeScript sources, so every JS fix ships in the bundles.
- This documentation site (Sphinx + MyST + executed tutorial notebooks).

## 0.2.0 (2025)

The first tagged release. Cumulative capabilities:

- **Full-grammar SysML v2 front-end**: ANTLR-generated parsers (grammar
  patches 1–5), a builder with no lossy fallback, and a typed dataclass
  object model with compact expression ASTs.
- **Round-trip interchange**: JSON export/import (lossless), regenerated
  SysML text, KerML projection, OMG spec-metamodel projection (pyecore)
  and Systems Modeling API JSON records.
- **Execution**: expression evaluation, calcs, instantiation, constraint
  and requirement checking, succession-driven action control flow, and
  hierarchical/parallel state-machine simulation with a clock.
- **Validation** (`sysml2 lint` / {func}`sysml2.validate`) with
  stdlib-aware name resolution and implied specializations; the vendored
  standard library ships as inspectable JSON (no pickles anywhere).
- **Multi-file workspaces** with a content-addressed model cache
  (~1000x faster warm loads).
- **Interactive ELK diagrams** in JupyterLab (structure, states, actions;
  click-selection back to model elements) on a vendored, patched ipyelk;
  headless SVG/PNG rendering via elkjs in node; simulation replay over the
  state diagram.
- **Tooling**: Apache-2.0 license, pixi-locked CI (lint + mypy + coverage,
  a py310–py313 test matrix, grammar-regen drift check), PyPI trusted
  publishing on tag push, output-free committed notebooks enforced by
  git hooks.
