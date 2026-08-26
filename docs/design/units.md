# Units and quantities (design)

> **Status: ratified.** The maintainer approved this design on
> 2026-08-25, ruling on three questions raised in review -- dBW + W
> scale mixing, foreign unit packages, and kg + lbm normalization.
> Each ruling is folded into its section below and marked
> **RESOLVED (2026-08-25)**; the open-question recommendations at the
> end stand with the approved document.

Goal: give longeron models real units -- temperature scales, decibels,
the full SI, US customary engineering units -- without slowing the
interpreter, bloating the dependency tree, or spraying `Any` through the
typed public API. This document records the design for longeron 0.10+.
It records design intent; no units code exists yet beyond what the
parser already carries. All empirical claims below were verified against
longeron 0.9.1 at commit `5ca6e73`; library claims were verified in a
scratch venv (`build/units-scratch`) against pint 0.25.3, pint-pandas
0.8.0, unyt 3.1.0, and OpenMDAO 3.45.0.

## The standards boundary

SysML v2 already owns the units problem. The spec's stance (§7.7.1,
printed p. 45): only the *kind* of unit (`MassUnit`, `LengthUnit`) is
associated with an attribute definition, while a *specific* unit (`kg`,
`m`) is given with an actual quantity value -- so an attribute usage is
independent of the units used, "allowing for automatic conversion and
interoperability between different units of the same kind." The
Quantities and Units Domain Library (§9.8, printed p. 576) supplies the
whole vocabulary: quantity values and dimensions (§9.8.2, printed
p. 577), measurement references with `IntervalScale` for offset units
like °C and `LogarithmicScale` for dB/dBm (§9.8.3.2.16-17, printed
p. 592), the ISQ (§9.8.4), SI (§9.8.6, printed p. 616), and US customary
units (§9.8.7, printed p. 616).

The textual notation is the bracket operator. A quantity value is
constructed by `'['`, a calculation whose signature the spec gives
explicitly (§9.8.9, printed pp. 624-625):

```text
calc def '[' specializes BaseFunctions::'[' {
    in num: Number[1];
    in mRef: ScalarMeasurementReference[1];
    return quantity : ScalarQuantityValue[1];
}
```

with the spec's own examples: `attribute mass : MassValue[1] = 24.5 [kg];`,
`attribute speed : SpeedValue[1] := 3*x [m/s];`,
`attribute :>> ISQ::width default 250.0 [mm];`. The same clause defines
quantity-dimension rules for arithmetic -- exponent-vector products of
powers of base quantities -- and is honest that dimension agreement is
"a necessary but not a sufficient condition" (energy and torque share
L²·M·T⁻² but must not be added).

The design therefore has three tiers:

- **Model tier (standard).** Units are declared *in the model*, using
  the spec's own bracket notation and the vendored `Quantities`/`ISQ`/
  `SI` library packages. This tier round-trips through `.sysml` text and
  is legible to every conformant tool. It exists today (verified below).
- **Core tier (zero new dependencies).** The interpreter and M0 keep
  canonical floats; unit references ride as metadata on expressions. A
  dimensional-consistency lint -- plain exponent-vector arithmetic
  with a per-unit scale tag, implemented in-house -- catches
  `mass + flightTime` at validation time, where the interpreter today
  returns `35.0` without comment.
- **Boundary tier (optional extra, `longeron[units]` = pint).**
  Conversion, display, and exchange only: scoreboard tooltips and ramp
  anchors in declared units, OpenMDAO bridge translation, pint-pandas
  for M0/trade-study tables, a user-facing `convert()`. A typed facade
  wraps pint so its loosely-typed `Quantity` never appears in a public
  signature: floats and unit strings in, floats out, `py.typed` clean.

## Why not just adopt a units library

Candidates scored against the maintainer's criteria. "Complete" means
offset units (°C/°F), logarithmic units (dB, dBW, dBm), and full SI plus
common engineering systems.

| criterion | pint 0.25.3 | unyt 3.1.0 | astropy.units | OpenMDAO units | roll-our-own |
| --- | --- | --- | --- | --- | --- |
| complete | **yes** -- verified: 25 °C→298.15 K, 3 dBm→1.995 mW, 20 dBW→100 W | partial -- °C/°F work; `dB` parses with a `(logarithmic)` dimension but converts to *nothing* (verified `UnitConversionError`, even to dimensionless) | yes (function units, equivalencies) | partial -- °C/°F verified; dB/dBm/dBW rejected, `gal` missing (verified 3.45.0) | whatever we write, at our cost |
| cheap in hot paths | no -- scalar `Quantity` add measured ≈430× a float add; import 463 ms + 89 ms registry | arrays are `ndarray` subclasses (cheap in bulk); scalars still boxed | no -- heaviest of all | conversion functions over plain floats: cheap, no quantity objects at all | floats: free |
| numpy | wraps arrays (verified) | native subclass (verified) | native subclass | pass-through | n/a |
| pandas | **pint-pandas 0.8.0** `pint[m]` ExtensionArray, verified against pandas 3.0.5 | broken -- units survive `Series()` construction, verified *lost after the first operation* | no integration | none | n/a |
| modern typing | ships `py.typed` (verified) but `Quantity` is not dimension-generic; registry lookups degrade to `Any` | **no `py.typed` at all** (verified) | untyped | untyped private module | exactly as typed as we make it |
| dependencies | flexcache, flexparser, platformdirs, typing-extensions -- all small, pure Python | numpy + **sympy** (heavy) + packaging | the astropy stack -- ruled out by the maintainer despite quality | zero *extra* -- already inside `[mdao]` | zero |

Verdict: no library is fit to sit in the core, and none needs to. pint
is the only candidate that passes the completeness bar (unyt's dB is
decorative; OpenMDAO's units reject dB outright) with a working pandas
story and a small pure-Python closure -- so pint backs the *boundary*
tier, where its typing weakness is contained by a facade and its 430×
scalar overhead never meets a hot path. OpenMDAO's units library is not
good enough to be *the* solution but is exactly right as the *dialect*
at the OpenMDAO boundary: longeron converts, OM receives its own
spellings. The core tier rolls its own -- but "own" is only exponent
vectors, ~a hundred lines, not a units library.

## What longeron supports today (gap analysis)

Every row below was established empirically against the worktree at
`5ca6e73`, spec-shaped samples parsed with `longeron.loads()`.

**The vendored library is a curated subset.** 11 of the upstream
release's 23 Quantities-and-Units files ship (~96 KB of ~1.0 MB):
`Quantities`, `MeasurementReferences` (+`MeasurementRefCalculations`),
`ISQ`, `ISQBase`, `SI`, `SIPrefixes`, `QuantityCalculations`, `Time`,
`VectorCalculations`, `TensorCalculations`. Omitted: the twelve ISQ
domain extensions (`ISQMechanics` 74 KB, `ISQThermodynamics` 65 KB,
`ISQSpaceTime` 55 KB, ... ~882 KB total) and `USCustomaryUnits`
(30 KB). The vendored `SI.sysml` is complete enough to matter: base
units, ~200 derived units with definitional algebra (`newton = kg*m/s^2`),
prefixed units via `ConversionByPrefix`, the °C *interval scale* with
its 273.15 K shift, and `dB`/`oct`/`dec` declared (as
dimension-one units, not full `LogarithmicScale`s).

**The measurement notation parses and round-trips.** All of the spec's
own example shapes parse, resolve, and hit a `to_sysml` fixpoint:

```sysml
attribute mass :> ISQ::mass = 24.5 [kg];        // bare unit, library visibility
attribute mass2 :> ISQ::mass = 5.0 [SI::kg];    // qualified
attribute speed = 3 * x [m / s];                // derived-unit expression
attribute energy : Real = 42.0 [SI::'W⋅h'];     // quoted unrestricted name
attribute :>> width default = 250.0 [mm];       // default value
```

The grammar folds the bracket into `primaryExpression` (`KerML.g4`
l. 1705); the AST carries it as `QuantityOp(base, unit)` (`ast.py`); the
model layer stores `FeatureValue(expr=QuantityOp(base=Literal(5.0),
unit=FeatureRef(('SI', 'kg'))))`. Longeron's lossless JSON
(`to_json`/`from_json`) preserves it. The API projection does not -- but
that gap is not units-specific: `to_api_records` drops *every* attribute
`FeatureValue` today (verified: a plain `= 5.0` produces no
`LiteralRational` record either), so units ride whichever fix closes the
value-expression projection (a precondition already flagged in the
[view-persistence design](view-persistence.md)).

**Resolution against the vendored stdlib is good where it ships, gone
where it doesn't.** Verified resolutions: `SI::kg`, `SI::K`, `SI::N`,
`SI::dB`, `SI::°C`, `SI::°C_abs`, `SI::W⋅h`, `SI::km/h`, `SIPrefixes::kilo`,
`ISQ::mass`, `ISQ::length`, `ISQ::duration`, `ISQ::electricCurrent`,
`MeasurementReferences::{IntervalScale,LogarithmicScale,ConversionByConvention}`.
Verified dangling: `ISQ::temperature`, `ISQ::force`, `ISQ::speed`,
`ISQ::energy`, `ISQ::power`, `ISQ::frequency`, `ISQ::pressure` (their
homes are the omitted domain files), and all of `USCustomaryUnits`.
The vendored library even dangles *internally*: `SI::newton` is typed
`ForceUnit`, defined in the omitted `ISQMechanics` -- but its
definitional expression `kg * m / s ^ 2` survives in the model layer,
which the core tier exploits below.

**Units are annotations at evaluation.** `interpreter.py` l. 1001:
`QuantityOp` evaluates its base and discards the unit -- one
`isinstance` branch that already exists. Instance slots are pure floats
(verified: `{'mass': 5.0, 'cells': 4.0, 'totalMass': 20.0}`); M0
roll-ups over populations return floats.

**Nothing checks anything.** `validation.py` l. 427 deliberately skips
`QuantityOp.unit`, so `= 5.0 [SI::bogusUnit]` produces *zero*
diagnostics (verified). And the motivating bug class passes silently:

```sysml
attribute mass = 5.0 [SI::kg];
attribute flightTime = 30.0 [SI::min];
attribute nonsense = mass + flightTime;   // evaluates to 35.0, no complaint
```

**The OpenMDAO bridge is unit-blind.** No `add_input`/`add_output` call
in `analysis/mdao.py` passes `units=` (verified); OpenMDAO's own
conversion machinery sits unused one keyword away.

The five most consequential findings:

1. **The model tier already works.** Spec measurement notation parses,
   resolves against the vendored SI/ISQ, and round-trips at a fixpoint.
   Tier 1 needs no parser, exporter, or model-layer work -- only more
   vendored library and diagnostics.
2. **`kg + min = 35.0`, silently.** The interpreter's unit-stripping is
   the right performance call and the wrong safety default; the lint
   tier exists because of this exact observation.
3. **Dangling units are invisible.** Validation skips `QuantityOp.unit`
   by design, so today a typo'd unit is *less* diagnosed than a typo'd
   type. Closing this is cheap and independent of everything else.
4. **The vendored SI carries its own conversion semantics.** Derived
   units keep definitional expressions (`kg*m/s^2`), prefixed units
   keep `ConversionByPrefix`, °C keeps its `IntervalScale` shift --
   enough to *derive* exponent vectors and SI factors from the model
   itself, no third-party unit database required in core.
5. **Engineering vocabulary is missing, cheaply fixable.** `force`,
   `speed`, `power`, `temperature`, and all US customary units dangle
   today; `ISQMechanics` + `ISQSpaceTime` + `ISQThermodynamics` +
   `USCustomaryUnits` are ~224 KB of vendorable text that closes the
   gap for most engineering models.

## The three-tier architecture

### Model tier: the spec's machinery, more of it

Users declare units exactly as the spec shows -- nothing
longeron-specific to learn, nothing that other tools cannot read. Work
in this tier is curation, not code: vendor the three core ISQ domain
files and `USCustomaryUnits` (finding 5), refresh `prebuilt.json`, and
add a `unresolved-unit` diagnostic (below) so the model tier fails
loudly instead of silently.

### Core tier: floats plus an exponent-vector lint

Quantity objects never enter evaluation. The invariant, stated once and
enforced by review: **`Interpreter.eval`, `Instance` slots, M0
`Individual` slots, roll-ups, and `compute()` bodies in the OpenMDAO
bridge see only `float`/`int`/`bool`/`str`** -- exactly as today. Unit
references stay where the parser put them, in `QuantityOp.unit` and in
quantity-typed attribute declarations, as metadata.

The lint is dimensional analysis over exponent vectors -- `(m, kg, s,
A, K, mol, cd)` powers as a tuple of `Fraction`s, closed under multiply/
divide/power -- each tagged with a *scale* (`linear`/`log`/`offset`;
ratified below). The unit table is *derived from the vendored SI model
itself* (finding 4): base units seed the basis, `ConversionByPrefix`/
`ConversionByConvention` members inherit their reference unit's vector,
derived units evaluate their definitional expression (`kg*m/s^2`) in
unit space. Attribute dimensions come from quantity subsetting
(`:> ISQ::mass`) and from `QuantityOp` annotations; unknown dimensions
are bottom and propagate silently -- the lint only speaks when two
*known* vectors conflict. ~150 lines, `Fraction` from the stdlib, no
dependency.

```python
# validation.py (sketch)
@dataclass(frozen=True)
class _Dim:
    exp: tuple[Fraction, ...]  # powers over (m, kg, s, A, K, mol, cd)
    scale: Scale = "linear"  # Literal["linear", "log", "offset"]


def _unit_dimensions() -> dict[str, _Dim]:
    """qname -> exponent vector, derived from the vendored SI model
    once and cached beside the stdlib prebuilt."""
```

Five diagnostics, hanging in `validation.py`'s existing architecture --
`_Checker` gains one method each, driven from `_check_tree` like
`check_expressions`, reusing `_owned_expressions` and the stdlib-aware
`Resolver`:

- `unresolved-unit` (warning): a `QuantityOp.unit` reference that does
  not resolve. Closes the deliberate skip at `validation.py` l. 427
  (finding 3).
- `dimension-mismatch` (warning): `+`, `-`, or a comparison whose
  operands carry conflicting exponent vectors -- `mass + flightTime`,
  `mass < wingSpan`. A warning, not an error, per the spec's own
  "necessary but not sufficient" caveat (§9.8.9): dimension agreement
  can be checked mechanically, quantity-kind agreement cannot.
- `scale-mismatch` (error): `+` or `-` whose operands carry different
  scale tags -- `20 [dBW] + 5 [W]`, `25 [°C] + 298.15 [K]`. An error
  where `dimension-mismatch` is only a warning: dimension agreement is
  heuristic per the spec's caveat, but cross-scale linear arithmetic
  is *never* meaningful. Explicit conversion is always allowed.
- `mixed-units` (warning; active only without the `[units]` extra):
  `+`, `-`, or a comparison over same-dimension operands declared in
  *different units* -- `5.0 [kg] + 3.0 [lbm]`. With the extra, the
  declaration-boundary normalization (below) makes the arithmetic
  correct and the warning moot.
- `anchor-dimension-mismatch` (warning): the scoreboard convention's
  `ramp0`/`ramp1`/`target`/`limit` attributes disagree dimensionally
  with the requirement's `measure` -- a ramp anchored in minutes
  scoring a measure computed in hours is finding 2 wearing a MAUT hat.

Two of the five were settled by explicit maintainer rulings in review:

**RESOLVED (2026-08-25) -- dBW + W (and naive °C).** Exponent vectors
get a scale tag -- `linear`/`log`/`offset` -- seeded from the vendored
library's measurement references (`IntervalScale` -> offset,
`LogarithmicScale` and the `dB` family -> log, everything else
linear). Mixed scales under `+`/`-` are a lint *error*; explicit
conversion is always allowed. The tag also fixes naive Celsius
addition: °C is `offset` where K is `linear`, so a Celsius value can
no longer pose as a linear kelvin in arithmetic -- it must be
converted explicitly (or normalized at the declaration boundary, next
ruling) first. This refines the draft's exponent-vectors-only lint,
which would have flagged dB-family additions only by the accident of
their dimension-one vectors and passed °C + K entirely.

**RESOLVED (2026-08-25) -- kg + lbm.** Split on the `[units]` extra.
With it installed: canonical-SI normalization at the *declaration
boundary* -- evaluating a `QuantityOp` multiplies the declared
magnitude through to canonical SI (linear factors from the derived
table; offset and log scales through real conversion), so instance
slots hold SI floats and mixed same-dimension arithmetic is correct
automatically. Without it: the core tier converts nothing by design,
so the lint *warns* (`mixed-units`, above) on mixed same-dimension
units in one expression. The floats-only invariant survives intact --
normalization runs once per declaration and stores a plain float --
and the boundary-tier claim that bridge values "are already canonical
SI floats" becomes literal rather than aspirational.

### Boundary tier: `longeron[units]`, a typed facade over pint

Everything that actually converts or pretty-prints lives in one module,
`longeron.units`, importable only with the extra (the `MissingExtraError`
pattern `analysis/mdao.py` already uses). pint's `Quantity` is an
implementation detail; no public signature mentions it:

```python
# longeron/units.py -- the [units] facade (sketch); py.typed clean
def convert(value: float, from_unit: str, to_unit: str) -> float: ...
def si_value(value: float, unit: str) -> float: ...  # (25.0, "°C") -> 298.15
def si_unit(unit: str) -> str: ...  # "min" -> "s"; "dBm" -> "W"
def format_quantity(value: float, unit: str, *, precision: int = 3) -> str: ...
def om_unit(unit: str) -> str | None: ...  # OpenMDAO dialect; None = not expressible
def with_units(df: pd.DataFrame, units: Mapping[str, str]) -> pd.DataFrame: ...
```

Unit strings are the *model's* vocabulary -- `"SI::kg"`, `"kg"`,
`"°C"`, `"dBm"` -- mapped to pint spellings by a registry keyed by
qualified name, seeded from the same derived unit table the lint uses.
The pint `UnitRegistry` is a lazy module-level singleton (its 89 ms
construction cost is paid once, never per call).

**RESOLVED (2026-08-25) -- foreign unit packages.** The mapping is a
registry keyed by qualified name, and dimension vectors + SI factors
are *derived from the model's own definitional algebra* (finding 4),
exactly as the lint already derives them for the vendored SI. A user
or third-party unit package that follows the stdlib pattern --
definitional expressions (`kg*m/s^2`), `ConversionByPrefix`/
`ConversionByConvention`, measurement-reference scales -- therefore
works with *no mapping table at all*. Where derivation cannot reach,
the registry accepts user-registered overrides, and the facade passes
`ureg.define(...)` through to pint for the boundary-side spelling. The
draft's recommendation (seed the alias table from the derived unit
table) already matched; the ruling extends it from the vendored
packages to any package shaped like them, and adds the
override/`define` seam.

Conversion points, concretely:

- **OpenMDAO bridge.** `_expr_component.setup` and `calc_component`
  gain `units=om_unit(...)` on `add_input`/`add_output`; `build_problem`'s
  free-attribute `IndepVarComp` outputs likewise. Values crossing the
  bridge are already canonical SI floats (the declaration-boundary
  normalization ratified in the core tier), so the `units=` string is
  the SI unit's OM spelling (`"kg"`, `"m/s"`, `"degK"`) -- OM's N2 diagram
  and `add_design_var(units=...)` start working, and OM never sees a
  dialect it does not own. Where OM has no spelling (`dB` -- verified
  unsupported), `om_unit` returns `None` and the variable stays
  unitless, exactly as today. This resolves the OM-interplay concern:
  longeron converts, OM receives OM.
- **Scoreboard.** Tooltips show `raw` through `format_quantity` in the
  declared display unit; ramp anchors declared in one unit score
  measures computed in another through one `convert` at *build* time
  (never per-cell). A display-only `unit : String` attribute convention
  is landing in parallel; it migrates cleanly: when the measured
  attribute carries a real stdlib unit reference, the display unit is
  *derived* from the model and the `unit` string becomes a presentation
  override -- kept indefinitely as the escape hatch, checked by
  `anchor-dimension-mismatch` when it conflicts.
- **Tables.** `with_units` applies pint-pandas dtypes (`pint[m]`,
  verified against pandas 3.0.5) to M0 `to_dict` frames and trade-study
  tables -- unit-aware column arithmetic for notebook users who opted
  in, plain float frames for everyone else.

## Static dimensional checking from Python

Could mypy catch `mass + flightTime`? Three routes, honestly assessed:

**(a) The runtime lint over model expressions -- now.** The core tier's
`dimension-mismatch` already catches time+length in calc bodies,
constraints, and attribute values *with no Python typing at all*: the
check runs over M1 expressions at `validate()` time, so it protects
pure-model users, CLI users, and CI equally. This is the only route
that sees the model's own arithmetic, and it ships first.

**(b) Generated typed facades -- the 0.11+ path.** A future `longeron
codegen` emits typed Python classes from a model: `class Battery` with
`mass: Mass`, `flightTime: Duration`. The dimension types are opaque
nominal classes in the stubs (plain `float` subclasses at runtime, zero
overhead) with a *generated, finite* overload matrix over the closed set
of dimensions the model actually uses:

```python
# generated stub (sketch)
class Mass:
    def __add__(self, other: Mass) -> Mass: ...
    @overload
    def __mul__(self, other: float) -> Mass: ...  # scaling is safe
    @overload
    def __mul__(self, other: Acceleration) -> Force: ...  # products the model uses
    def __truediv__(self, other: Duration) -> MassFlow: ...
```

`battery.mass + battery.flightTime` becomes a standard mypy *and*
pyright error -- no plugin, no dependency, because the matrix is finite
and enumerated rather than computed by dimension algebra in the type
system. The facade is independently valuable (autocomplete, IDE
navigation, rename safety over model-derived code); dimensional safety
rides along for free.

**(c) A mypy plugin doing genuine dimension algebra -- rejected.** It
is the most powerful option and the worst engineering: plugins are
coupled to mypy internals that break across releases, and pyright users
-- most IDE users -- get nothing. A maintenance liability purchased for
one type-checker's users.

Recommendation: (a) now, (b) as the 0.11+ path behind its own design
doc, (c) rejected.

## Performance

Where quantity objects are *allowed to exist*: inside `longeron.units`
(pint registry and intermediates), inside pint-pandas frames returned by
`with_units`, and in scoreboard/bridge *setup* code that runs once per
build. Where only floats exist: `Interpreter.eval` and everything it
feeds -- instance slots, M0 populations and roll-ups, `compute()` inner
loops, trade-study enumeration. The measured ~430× scalar overhead and
463 ms import are why this fence exists; the design keeps both out of
every path that runs per-evaluation rather than per-build.

Cost of the design itself: the interpreter's `QuantityOp` branch already
exists (zero delta without the `[units]` extra; with it, the ratified
declaration-boundary normalization is one float multiply where the
annotation is evaluated, never per roll-up); the lint adds one
validation pass over expressions (validation is never in an evaluation
loop); the derived unit table is
built once and cached like the stdlib prebuilt.

Micro-benchmark plan (to be run at implementation, not before):

1. **Interpreter neutrality.** `instantiate` + `rollup` throughput on
   the notebook-07 UAV model, with and without `[SI::...]` annotations
   on every attribute -- target: indistinguishable within noise.
2. **Validation delta.** `validate()` wall time on the largest corpus
   model with the dimension lint on/off -- target: <10% over the
   existing expression checks.
3. **Facade steady state.** `convert()` per-call cost after registry
   warm-up (scratch measurement: ~34 µs) and first-call cost including
   the lazy registry (~550 ms import+init) -- documented, amortized,
   and kept out of `import longeron`.
4. **Bridge overhead.** `build_problem` + one `run_model` with and
   without `units=` kwargs -- OM does its own conversion bookkeeping;
   confirm it stays in setup, not in `compute`.

## What we deliberately do not build

- **No custom unit algebra beyond exponent vectors.** The core tier
  computes dimension vectors, never conversion chains; conversion is
  the boundary tier's job, and pint's.
- **No runtime quantity types in the interpreter or M0.** No
  `Quantity` class, no operator overloading, no unit-carrying slots --
  the fence is the feature.
- **No astropy**, per the maintainer, despite its quality.
- **No unit-string parser for arbitrary user text.** Units come from
  the model's stdlib references; the facade's alias table maps model
  vocabulary to pint, not free-form strings to anything.
- **No automatic rewriting of user models.** Longeron never converts a
  declared `250.0 [mm]` into `0.25 [m]` in source; canonicalization
  happens at evaluation boundaries, display stays declared. (Already
  matched the kg + lbm ruling: with the `[units]` extra that
  canonicalization *is* the declaration-boundary normalization;
  without it, values stay as declared and the lint warns.)
- **No mypy plugin** (route (c) above).

## Open questions for the maintainer

The maintainer approved this document on 2026-08-25 and ruled on three
questions raised in review (dBW + W scale mixing, foreign unit
packages, kg + lbm); those rulings are folded into their sections
above and marked RESOLVED. The five questions below were not
separately contested -- their recommendations stand with the approved
document, and implementation treats them as the working plan.

1. **Vendor how much more of the quantities library?** Options: nothing;
   `USCustomaryUnits` only (30 KB); or `USCustomaryUnits` +
   `ISQMechanics` + `ISQSpaceTime` + `ISQThermodynamics` (~224 KB, and
   `force`/`speed`/`power`/`temperature` resolve). *Recommendation:* the
   four-file option. It closes finding 5 for the engineering models this
   tool targets; the remaining eight ISQ files (~688 KB of atomic
   physics and characteristic numbers) stay out until someone asks.
   Measure the `prebuilt.json` load delta before merging.
2. **Is `unresolved-unit` on by default?** It will warn on existing
   models that use ad-hoc unit tokens not in the vendored library.
   *Recommendation:* yes, as a warning -- that nudge is the point, and
   bare `[kg]`-style references resolve silently once the library
   ships. Severity matches `unresolved-reference`.
3. **Does the OM bridge pass `units=` always or opt-in?**
   *Recommendation:* always, best-effort per variable: mapped units get
   the kwarg, unmapped (`om_unit() is None`) stay unitless. Partial
   adoption must never break an existing Problem; a `units=False`
   escape hatch on `build_problem` guards against OM dialect surprises.
4. **Is pint the right boundary backend, given OM units is already in
   `[mdao]`?** *Recommendation:* yes. OM's library fails the
   completeness bar (no dB family, no gallon -- verified) and is an
   untyped private module of an optional heavy dependency; pint's
   closure is four small pure-Python packages. OM units remains the
   *target dialect* at the OM boundary only.
5. **Should the typed-facade codegen (route (b)) be its own design
   effort?** *Recommendation:* yes, separate doc. It has independent
   scope (class generation, naming, regeneration workflow, packaging of
   generated stubs) and independent value; this design only reserves
   the dimension-type story so the two compose.

## References

- OMG Systems Modeling Language (SysML) v2.0, Part 1: §7.7.1 (printed
  p. 45), §9.8 (printed pp. 576-631), esp. §9.8.3.2.16-17 (printed
  p. 592), §9.8.6-9.8.7 (printed p. 616), §9.8.9 (printed pp. 624-628).
- Longeron surfaces: {mod}`longeron.validation`,
  {mod}`longeron.interpreter`, {mod}`longeron.m0`,
  {mod}`longeron.analysis.mdao`, {mod}`longeron.analysis.scoreboard`,
  `src/longeron/_stdlib/quantities/` (vendored library subset).
- Sibling designs: [view persistence](view-persistence.md) (the
  API-projection value gap), [M0 interpretations](m0-interpretations.md)
  (floats-only populations), [OCL stance](ocl-stance.md).
- Verified library versions: pint 0.25.3, pint-pandas 0.8.0, unyt 3.1.0,
  OpenMDAO 3.45.0, numpy 2.5.2, pandas 3.0.5.
