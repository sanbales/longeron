# Release notes

## 0.11.0 (unreleased)

### The DeepScout program

- **One program replaces the three example models**
  (`examples/deepscout/`): six files, one workspace, open-closed -- a
  new configuration lands in its family file without touching the
  shared physics. `parts.sysml` is the component catalog,
  `aircraft.sysml` the abstract `Aircraft` root with the discipline
  packages, requirement definitions, behaviors, and units,
  `multirotor.sysml` the rotorcraft family plus the fleet airframes,
  `vtolwing.sysml` the `VtolWing` and `DartInterceptor` branch,
  `missions.sysml` the three missions plus the MAUT scoring hierarchy
  (`ScoutMissions::scoring` -- the scoreboard scores the same truth
  the trades trade), and `sizing.sysml` the CP-SAT structural catalog.
  `longeron.load("examples/deepscout")` loads the whole program; the
  old `drone.sysml`, `uav_missions.sysml`, and `drone_catalog.sysml`
  are gone (see the upgrade notes below)

- **Real parts on nominal manufacturer figures**: the catalog carries
  two component classes -- the F450-class bench kit (DJI Flame Wheel
  F450, EMAX MT2213-935KV with its bench thrust table, APC 10x4.5MR
  props, Tattu 5200mAh 3S pack, Hobbywing XRotor 40A ESC, Pixhawk 6C
  Mini, GPS/RC/telemetry, tall-skid gear) and a heavy 6S lineup
  (T-Motor/SunnySky motors with power ceilings, APC/T-Motor props
  behind a genuine `propFit` bind, three Tattu LiPos against a 6S6P
  NCR18650GA li-ion pack at the honest 1.3-1.6x pack-level advantage,
  payload optics priced like life). Every figure is declared nominal
  at the package level. The chemistry axis resolves per mission: ISR
  goes li-ion (+47 min on station), logistics takes the 16Ah LiPo and
  the winch, intercept stays all-LiPo

- **The multirotor family -- tri, quad, hexa, coax-X8, flat-eight
  octo -- and no configuration wins everything**: an abstract
  `MultiRotor` owns everything the configurations share (equipment
  bay, wiring, the attitude physics chain, hover and takeoff
  constraints), and the REDEFINED MULTIPLICITIES ARE THE ARCHITECTURE
  DIFFERENCE -- `motors[4]` vs `frontMotors[2] + tailMotor` vs six on
  60-degree arms vs `upperMotors[4] + lowerMotors[4]` with the coax
  wake penalty visible in the hover amps. `FailSafeHover` -- hover
  with any single motor out -- is satisfied by the hexa, the X8, and
  the octo only; the quad's and tri's missing edges are the point. The
  family matrix holds no all-rounder: the quad takes endurance with
  zero redundancy, the tri takes price but busts the mission budget,
  the hexa takes redundancy and the biggest payload envelope but is
  heaviest and thirstiest, the X8 takes redundancy and the fastest
  cruise in the quad's own footprint at the highest price. Geometry
  goes N-arm parametric -- arms at odd multiples of pi/N, stations
  spaced so adjacent discs just clear for any N, coax discs stacked on
  drawn standoffs -- so every architecture renders to scale, and the
  disc-overlap and occlusion checks run per configuration (they find
  the X8's lower forward discs grazing the belly camera's view cone)

- **Payload and payload-range**: ten derived `MultiRotor` attributes
  -- `emptyMass`, `mtowPayload`, `thrustLimitPayload` (exact algebraic
  inversion of the hover margin), `maxPayload` with its BINDING limit
  named, `failsafePayload` (redundancy priced in kilograms),
  `reserveFraction`, `cruiseRange`, `payloadRangeKgKm`. The table
  teaches: only the tri is thrust-bound (every other configuration
  runs out of book MTOW first); the X8's and octo's failsafePayload
  EXCEED their maxPayload, so the whole envelope survives a motor
  failure; the quad fails motor-out even empty. Three independent
  roads agree, all asserted: the model's closed-form hexa
  failsafePayload (0.44451 kg) matches `verify.hunt`'s independently
  bisected edge (0.4445), and the X8's mtowPayload (0.498 kg) is
  exactly the 249/500 envelope bound Z3 attributes to
  `takeoffMassLimit`. Tutorial 4 gains the payload-range diagram, one
  curve per configuration, each ending at its ceiling

- **The crossed catalog: 288 -> 1280 platform mixes** (mission spaces
  864 -> 3840): motors, props, and packs cross both airframe branches,
  with honest infeasibility -- `propFit`, `packPower`, and `cellMatch`
  refuse the mixes that cannot fly instead of pricing them. The
  S1000-class `HexLifter` loiters 26.5 min on li-ion; the big-motor
  dart keeps the dash crown; restricted to the legacy variants, the
  old counts reproduce exactly. Full interpreter enumeration of all
  three mission spaces runs in 1.9 s, CP-SAT agrees mix-for-mix in
  1.03 s, and the dashboard bakes all 1280 candidates in 2.65 s

- **Current budgets and attitude, derived not asserted**:
  `continuousThrustFraction` stops being a magic constant and derives
  as the min of the throttle-cap, ESC, and pack-C ceilings; a
  `MotorCurrent` calc reproduces the bench table's current column;
  `PropThrust` recalibrates against the bench table (Ct 0.11 -> 0.097,
  the calibration shown in the model); and the hover (13.35 A) and
  cruise (15.40 A) current budgets roll up as asserts that Z3 proves
  safe inside the takeoff envelope. Attitude comes from the model too:
  `MaxTilt = arccos(mg/T)` at the usable continuous thrust,
  `CruiseTilt` capped by the operational limit, `TiltForSpeed` from
  the parasite-drag balance, and a `MissionTime` calc over the
  waypoint legs whose budget lands on the scoreboard as a requirement
  -- the Cesium quad flies its route at the model-derived tilt instead
  of pitching vertical

### The curriculum

- **The tutorial curriculum, rebuilt**: fifteen feature-tour notebooks
  become nine tutorials with one arc -- *data -> execution -> reading ->
  trading -> individuals -> judging -> geometry -> knowledge ->
  everything at once* -- over one subject, the DeepScout UAV program
  (`examples/deepscout`). Each tutorial opens with an engineering
  question and closes with the model answering it; concepts are taught
  once and cross-referenced everywhere else (tutorial 3 owns the
  selection seam, tutorial 5 owns M0). The notation gallery leaves the
  tutorial track for the docs reference section
  (`notebooks/notation_gallery.ipynb`, still executable and still the
  notation regression harness). Old numbering, for readers with
  bookmarks: 01+02+05 -> 1; 03+04 -> 2; 06+12+14 -> 3; 07 split into
  4 (trades), 5 (with 09, individuals), and 6 (with 13, requirements);
  10 -> 7; 08 -> 8; 15 -> 9; 11 -> the notation gallery; the
  `isr_scoring` inline model retired into the fleet model

### Verification and conformance

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
    constraint (the X8's max payload = `249/500` kg, bound by
    `takeoffMassLimit`)
  - `verify.verify` dispatches by scope kind; every catch
    `materialize()`s to identified M0 individuals; vacuous passes
    (violated assumptions) are recorded, never coerced into failures;
    every Hypothesis run is derandomized with seeds echoed on the report
  - the SMT encoder now walks *anonymous* requirement constraints too
    (an unnamed `assume` was silently dropped -- a latent false-`proven`
    bug, fixed for `prove` to land)
  - tutorial 6 ("Requirements: score, hunt, prove") carries the "find
    my violations" beat: hunt, the minimal
    sortie, the covering array with its measured-recall line, and the
    hoverMargin absence proof, executing with or without the extra
  - extras restructured: `verify = ["hypothesis>=6.100",
    "longeron[smt]"]`, plus composites `analysis`, `ui`, and `all`
    (`cad` deliberately excluded from `all`)

- **Conformance, measured and enforced**
  ([design](design/conformance.md)): the 309/309 corpus badge is a
  positive-only claim (every file of the pinned OMG corpus parses and
  builds), so the negative direction is now its own suite: 75
  spec-cited rejection cases -- 28 parse rejections, 37 semantic
  errors, 10 reference problems pinned as diagnosed -- with 2 known
  permissiveness gaps tracked as strict xfails, visible and
  un-regressable. The permissiveness burn-down flips 34 of 36 known
  gaps into enforced diagnostics (usage-vs-type metatype conformance,
  interface ends must be ports, exhibit-of-non-state,
  perform-of-non-action, duplicate sibling names, multiplicity bounds,
  unresolved qualified references and enum literals, the redefinition
  featuring-type family) with the corpus as the make-or-break gate:
  309/309 still parse and build with zero new corpus errors. A
  generative tier (Hypothesis) hunts the toolchain itself: composite
  strategies generate valid SysML text by construction, adversarial
  mutations must produce clean diagnostics and never a traceback,
  round-trip invariants run over generated models, and a spec-cited
  catalog of invalidating mutations counts every silently accepted
  mutant as a finding -- 12 new gaps found this way, each verified
  against the pilot implementation's own validator sources

- **Strict mode** (`validate(strict=True)` / `longeron lint
  --strict`): the resolution-failure family (`unresolved-reference`,
  `unresolved-name`, `unresolved-unit`, `dangling-expose`,
  `dangling-flow`, `dangling-succession`) promotes from warning to
  error, and a bare `import` (no visibility prefix) warns as
  `bare-import` -- never an error; the notation appears in
  OMG-authored text. Deliberately not promoted: `stdlib-implicit-name`
  (a successful resolution), the dimensional-lint codes, and the style
  codes. **Behavior change**: the CLI exit code is error-count-only in
  both modes -- the old `--strict` failed on any warning. What
  `--strict` means against OMG's own files is measured and published:
  142 of 309 corpus files carry at least one strict-mode diagnostic,
  dominated by cross-file references. And one new DEFAULT-mode error:
  a literal multiplicity range whose lower bound exceeds its upper
  (`part p : D[3..1];`) rejects as `multiplicity-bound-order` --
  deliberately stricter than the pilot implementation, the divergence
  recorded in [the validation guide](guides/validation.md)

### Analysis objects and units

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
    convention. Tutorial 5 closes with a discrete motor-entity case
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

### The widgets layer

- **`longeron.widgets`, the catalog**: one import for every house
  widget -- 17 canonical entries re-exported under `longeron.widgets`
  (the explorer and its tree engine, the review workbench and the
  inspector, the four diagram entries, the replay player, the
  scoreboard, both dashboards, the mesh and mission viewers, and the
  RDF graph), each entry the one the tutorials teach. Lazy by
  construction (PEP 562): the import pulls no widget toolkit until an
  entry is touched, and extras-gated entries raise `MissingExtraError`
  with the exact install command on access. The
  [catalog page](reference/widgets/index.md) and `__all__` cannot
  drift: a test parses the table and compares the sets. Composables
  (parallel coordinates, N2, toolbar tools) stay excluded --
  destinations only

- **`longeron.widgets.graph3d`: the knowledge graph in 3D**: the RDF
  projection becomes a force-directed explorer on the house three.js
  platform, no new dependencies. The default view is designed, not
  dumped: on DeepScout, 8,606 triples become 1,134 element nodes and
  1,355 relationship edges -- literals fold into hover payloads
  (`literals=True` opts back in) -- as instanced spheres sized by
  degree and colored with the explorer chip palette, edges styled by
  predicate family, namespace and edge-family filters in-scene, and a
  node cap with an honest notice. The top-center slider morphs the
  whole graph between the seeded force layout and a layered hierarchy
  (one ring per layer, package roots at the apex) at animation rate
  with zero kernel round trips. Focus mode extracts the selection's
  k-hop neighborhood with a breadcrumb back out; type-ahead search
  flies the camera to its match; billboard labels density-cap and
  fade with camera distance; the control panel -- toggle pills, slim
  sliders, hairline borders -- follows JupyterLab's theme into dark
  mode; `export_html(path)` writes a standalone page. Graph clicks
  speak the house selection contract, so the graph joins the
  linked-view family

- **Config-keyed 3D rendering, as a seam**
  (`longeron.analysis.link.bind_config_view` +
  `longeron.analysis.grand.scene_for`): tutorial 7's inline pattern --
  click anything, render the craft that owns it -- becomes one reusable
  call over any house selection surface (a diagram, an
  explorer-protocol tree). `scene_for` dispatches BOTH DeepScout
  families through one entry point: a MultiRotor build configuration
  bakes from its own M0 population (per-individual identity keys), a
  fleet airframe shell (`TeardropQuad`, `HexLifter`, `VtolWing`, ...)
  bakes from its own attributes via the extracted
  `geometry.airframe_geometry` ladder, and the mission catalog's
  variant usages resolve to the definitions that type them. Swaps
  happen only when the resolved configuration changes (no flicker),
  unrenderable selections keep the scene, rebinding is idempotent, and
  mesh picks still select the source node. `grand_dashboard` wires the
  binding into its 3D pane by default (`dash.config_view`); the camera
  what-if keeps measuring the home assembly while another craft is
  showing

- **The Longeron launcher tile**: the JupyterLab launcher gains a
  Longeron tile (and the `longeron:launch` palette command) that opens
  the review workbench with zero notebooks -- one click creates a
  named console session, imports `longeron.app`, and docks the
  sidebar; a second click reconnects instead of duplicating; a missing
  extra surfaces as a toast with the pip hint. The built extension
  ships in the wheel

- **Workspace save: edits write back to their source files**: models
  loaded from a directory now save. Directory loading records each
  top-level member's source file at the merge; every `longeron.edit`
  operation records the members it touched -- a rename records every
  member its reference cascade rewrote, across files;
  `export.workspace_plan` groups changes by source file, re-renders
  each mapped file whole (per-member emission proven byte-identical
  to whole-model emission), and drops files whose regenerated text
  already matches disk. `save_workspace` writes exactly the plan;
  refusals write NOTHING and name their reason, with the save-as
  escape hatch spelled out. The app's Save button enables for dirty
  workspace entries, and its tooltip names the files it will write

- **Inspector: units first-class, relationships get real sheets**:
  the value field shows `1.5 kg` -- magnitude plus resolved symbol --
  instead of raw bracket-expression text, and commits round-trip
  through the current unit reference; a read-only Unit row renders
  `kg -- mass` (quantity-typed unvalued attributes included); the
  typed-by row renders `Real [kg]` when a unit annotation exists --
  type and unit are different facts, both visible, neither posing as
  the other. Selecting a relationship yields a real sheet: dashed
  kind chip, derived label, clickable endpoint rows generalized to
  every kind (satisfies, verifies, imports, exposes, aliases, and
  dependencies join connects, binds, and flows), and the full
  declaration in a read-only block

- **Writes validate units**: `set_attribute_value` refuses a fake
  unit with nearest-candidate hints ("unit 'SI::kgg' does not resolve
  (did you mean 'SI::kg' or 'SI::g'?)"); quantity typing pins the
  dimension (a mass-typed attribute refuses a duration); when typing
  pins nothing, the CURRENT value's resolved unit is the pin, with
  `validate=False` as the documented override -- refusals mutate
  nothing, and the inspector surfaces them in its error strip. Input
  symmetry: the commit path accepts the compact form the tool itself
  displays -- `17 g` (and `17g`) resolves through the same unit table
  the display reads -- and prefixed units decompose through the
  standard library's own `SIPrefixes` definitions, so `17 mg` stores
  exactly as `0.017 [SI::g]` and nothing unresolvable ever enters the
  export. Ambiguous decompositions refuse with both readings spelled
  out

- **Scoreboard legibility and selection**: group membership reads at
  a glance -- an always-on two-tone boundary tier, perimeter group
  labels that zoom reveals level by level, and a hover extent
  spotlight that washes out everything outside the hovered group
  while member cells keep exact utility colors. The selected cell
  draws a full-perimeter inset stroke (the old centered stroke
  clipped to one visible edge) plus a subtle fill lift, on both
  tessellations and on hatched unmeasured cells. Collapse twists stay
  inside their own group's polygon: placement is
  containment-constrained, with labels chord-capped so they can never
  cross the group boundary

### The mission dashboard

- **The dashboard on one screen**: a header strip carries the new
  Pareto-only toggle and the lineup slider, parallel coordinates sit
  beside the Pareto scatter, the three mission panels become one tab
  set (a summary, then a tab per mission), and the 3D lineup docks
  beside the sliders so nothing scrolls at 1080p. The layout is fluid
  full width by default (`width_px=None`), fills its host's height
  (rows grow proportionally; the parallel coordinates, scatter,
  cards, and 3D canvas all re-render to their new boxes), and the
  section dividers drag -- pointer-capture gutters with min-size
  clamps on both sides, ratios saved to synced traits so re-renders
  and sibling views keep the layout, double-click to reset

- **Pareto honesty**: dominance is a pure, exported `pareto_mask`
  (cost minimized, three mission metrics maximized, weak dominance --
  weights provably never change the front), and the display explains
  itself. Every front member carries a justification:
  `front_justifications` names the metrics where it tops every pick
  that beats it in the DISPLAYED cost-vs-MOE plane (a greedy minimal
  set cover), the lineup cards carry the line, hovering a card traces
  its line in the parallel coordinates where all four axes are
  visible, and the scatter tooltip carries the why. The ink tells the
  4-D truth: front membership chooses the INK, the in-plane staircase
  chooses the MARKER -- filled dot on the staircase, open ring off
  it, gray strictly for dominated points -- and the staircase is
  retitled for what it is, a frontier in this plane only

- **The dashboard's state matrix, leak-free**: a 1,713-transition
  hunt over toggle x brush x thresholds x priorities x lineup size x
  tabs found two real leaks, both fixed at the source. An empty front
  no longer falls back silently to the whole catalog (the empty state
  says 'relax the requirement floors'), and brushes sync as INTERVALS
  BY AXIS NAME with the brushed subset re-derived from the table each
  recompute just baked -- stale row indices are structurally
  impossible. One `dash.selected` state closes the selection seam
  both ways: card click <-> scatter <-> parallel coordinates <-> 3D,
  background clicks clear, selection survives re-bakes while its
  candidate stays in view, and selection takes its own color channel
  (violet) beside the brush (blue) and the pick rings (terracotta)

- **CP-SAT learns calc inlining**: calc invocations inline (named and
  positional arguments, defaults, valued locals, nested,
  cycle-guarded), `max`/`min` map natively, constants fold, and
  magnitude-aware rescaling keeps int64 alive through pi*r^2*yieldPa
  chains -- the structural sizing catalog now encodes fully, and the
  CP-SAT enumeration equals the interpreter's verified set exactly.
  Whatever remains unencodable refuses with a one-line verdict naming
  the innermost operation, never an expression-tree dump. And typed
  variants with body redefinitions no longer produce empty bundles:
  trades instantiates the variant USAGE itself, so body overrides
  merge over inherited defaults into the CP-SAT bundles and into the
  interpreter-exact re-verification

### Diagrams and platform

- **Direction-aware glyphs**: toggling a diagram from left-right to
  top-down now transposes fork/join bars to lie perpendicular to the
  flow, moves the convergence anchors of decision and merge diamonds
  (and start, done, terminate) to north/south, re-derives n-ary
  junction ports on the flow axis, and moves the control glyphs' name
  captions beside the glyph, clear of the fan-out. Geometry
  re-derives from constants on every direction change, so any toggle
  sequence is idempotent and the left-right output stays
  byte-identical

- **Package tabs sit flush at every nesting depth**: nested packages
  drew their folder tab 5 px above the body -- `elk.spacing.labelNode`
  does not inherit under `INCLUDE_CHILDREN`, and the synthetic groups
  that pack loose members fell back to the elkjs default. Every
  container node now sets the option before layout, pinned by an
  adjacency test over nesting depths 0/1/2

- **Diagrams under load self-heal** (vendored ipyelk patch 12):
  jupyter-server's iopub rate limiter silently drops widget comm
  messages under burst, and one dropped update could leave a diagram
  frozen at its progress bar forever -- kernel idle, zero errors. The
  frontend now reports an unservable run as stale and backs off; the
  kernel answers by re-emitting the full pipe state, throttled so the
  re-syncs cannot flood the congested relay; zombie progress bars
  hide on terminal re-sync. Diagrams that wedged under notebook-wide
  run-all load now recover on their own

- **The prebuilt standard library carries no build-machine path**:
  `source_name` on stdlib elements is the symbolic `<stdlib>` (the
  old prebuilt JSON embedded an absolute local path that shipped in
  the wheel), and the prebuilt regenerates current

### Documentation

- **The docs describe the tool as-is**: design-doc citations of
  material outside the repository restate the content inline;
  ratification transcripts collapse to a dated status line plus a
  plain Decisions section; the notation gallery's spec-figure
  directory becomes the `SYSML_SPEC_PAGES` environment variable with
  graceful degradation

- **Design documents for the next arcs**:
  [geometry as model content](design/geometry.md) -- SysML v2-native
  CAD primordials over the OMG Geometry domain library's own 43 shape
  item defs, a zero-dependency `.jcad` exporter for editor interop,
  kinematics as clearly labeled extensions; adopted, implementation
  in a later release. [Data provenance](design/provenance.md) --
  evidence-linked models citing documents by sha256 + page + quote,
  attach/verify/coverage kept honest by construction, git LFS for
  owned documents, third-party datasheets never committed; adopted.
  [The time seam](design/time.md) -- one clock across every
  time-aware view (replay, mission globe, occurrence individuals);
  draft, unratified, targeted at the 0.12 arc.
  [The notebook curriculum](design/notebooks.md) -- the rebuild this
  release ships; adopted

### Upgrade notes

- **The example models merged into one program**:
  `examples/drone.sysml`, `examples/uav_missions.sysml`, and
  `examples/drone_catalog.sysml` are deleted; `examples/deepscout/`
  replaces them. The one-line fix:
  `model = longeron.load("examples/deepscout")` -- directory loading
  merges the workspace. The inline `isr_scoring` model from the old
  scoreboard tutorial is retired into `missions.sysml`'s scoring
  package; `examples/analysis_conventions.sysml` is unchanged
- **The tutorial notebooks renumbered**: the old numbered notebooks
  are gone; nine tutorials and the notation gallery (now a docs
  reference page, still executable) replace them. The old-to-new
  mapping is in the curriculum entry above
- **`longeron lint` exit codes changed**: the exit code counts errors
  only, in both modes. The old `--strict` failed on any warning; the
  new `--strict` promotes the resolution-failure family to errors
  (and only those promotions fail the run). Pipelines that relied on
  any-warning-fails semantics should parse the diagnostic output
- **`[3..1]` multiplicity bounds now reject**: a literal range whose
  lower bound exceeds its upper is an error
  (`multiplicity-bound-order`) in default mode -- deliberately
  stricter than the pilot implementation. Models that carried such
  ranges validated before and error now; swap the bounds

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
