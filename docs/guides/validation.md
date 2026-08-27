# Validation

{func}`longeron.validate` walks a model and returns
{class}`~longeron.validation.Diagnostic` records. The same checks run on
the command line as [`longeron lint`](cli.md#longeron-lint). This guide
documents every diagnostic code, how name resolution works, and the two
strict modes.

Validation never mutates the model. The standard library, when
consulted, is only visible to the resolver. `library` packages inside
the model itself (including a merged-in standard library) are treated
the same way: they are resolution context, never the subject of
diagnostics.

Scope: these checks are a curated set aimed at real modeling mistakes
-- they are not an implementation of the OCL well-formedness
constraints embedded in the OMG spec metamodel, and conformance claims
keep those axes separate (the corpus badge measures *parsing*
conformance). Rationale in the design doc:
[The OCL stance](../design/ocl-stance.md).

## Reading a diagnostic

Each diagnostic prints as `file:line:column: severity[code] element: message`:

```text
demo.sysml:3:5: error[duplicate-name] Demo::Wheel: name 'Wheel' is already used by another member of Demo
demo.sysml:5:9: warning[unresolved-reference] Demo::Vehicle::mass: typed by 'Reall' does not resolve
```

`element` is the qualified name of the subject element. The position
prefix is the subject's declaration site, stamped by the builder while
parsing: the `location` field of {class}`~longeron.validation.Diagnostic`
is a {class}`~longeron.errors.SourceLocation` (line and column are
1-based) or `None`. Elements built programmatically or rebuilt from
JSON -- including [model cache](workspaces.md#the-model-cache) hits --
carry no position, and their diagnostics print without the prefix
(`longeron lint --no-cache` re-parses to get positions back).
`validate()` returns diagnostics sorted errors-first, then by element
and code.

Severities draw one line: structural problems that make the model
self-contradictory are errors, and references that merely fail to
resolve are warnings. An unresolved reference is a warning because the
missing target may live in a file you did not load.

## The diagnostic codes

| Code | Severity | Fires when |
|---|---|---|
| `duplicate-name` | error | Two members of one namespace share a name or short name. |
| `specialization-cycle` | error | An element's specialization hierarchy (`specializes` / `typed by` / `subsets`, including implied specializations) reaches the element itself. Redefinitions (`:>>`) are not specialization edges: redefining a same-named inherited feature is not a cycle. |
| `unknown-state` | error | A transition names a source or target that is not a state of its machine. |
| `unresolved-reference` | warning | A declared reference does not resolve: `typed by`, `specializes`, `subsets`, `redefines`, `references`, `crosses`, connection/binding ends, `satisfied by`, an import, an alias, or a dependency end. |
| `dangling-expose` | warning | An `expose` inside a view usage names an element that no longer resolves. Restoring the view ([view persistence](../reference/views.md)) skips such exposes with a warning; this diagnostic surfaces the same condition statically. |
| `unresolved-name` | warning | The leading name of an expression does not resolve. Locals, loop variables, accept payloads, builtin functions, and inherited members are recognized first. |
| `no-entry-transition` | warning | A state machine declares states but no `entry; then <state>;` transition, so simulation has no starting state. |
| `calc-without-result` | warning | A calc has no result expression and no `return`-directed member with a value. Reference calc usages that delegate to a typed calc stay silent. |
| `unresolved-unit` | warning | A `[unit]` annotation does not resolve -- `= 5.0 [SI::bogusUnit]` or a `[furlongs]` no library defines. Bare stdlib unit names (`[kg]`) resolve through the implicit library hop and stay silent. |
| `dimension-mismatch` | warning | `+`, `-`, or a comparison whose operands carry conflicting dimension vectors: `mass + flightTime`, `mass < wingSpan`. A warning, not an error, per the spec's own "necessary but not sufficient" caveat (§9.8.9) -- dimension agreement can be checked mechanically, quantity-kind agreement cannot. |
| `scale-mismatch` | **error** | `+` or `-` whose operands carry different measurement *scales* (`linear` / `offset` / `log`): `20 [dBW] + 5 [W]`, `25 [°C] + 298.15 [K]`. Cross-scale linear arithmetic is never meaningful; convert explicitly. |
| `mixed-units` | warning | `+`, `-`, or a comparison over same-dimension operands declared in *different units* (`5.0 [kg] + 3.0 [lbm]`, `1.0 [m] + 2.0 [mm]`). Active only without the `[units]` extra: with it, declaration-boundary normalization makes the arithmetic correct and the warning moot. |
| `anchor-dimension-mismatch` | warning | A scoreboard-convention `ramp0` / `ramp1` / `target` / `limit` attribute disagrees with its sibling `measure` -- dimensionally, or (without the `[units]` extra) in declared unit: a ramp anchored in minutes scoring a measure computed in hours. |
| `stdlib-implicit-name` | warning | Only under `strict_imports=True` / `--strict-imports`. A bare standard-library name resolved only through the implicit library-visibility hop. |

## Names resolve against the standard library

Unless disabled, unresolved names get a second chance against the
vendored [standard library](../reference/stdlib.md). A bare `Real`, with
no import at all, validates silently, because KerML grants standard
library packages implicit visibility from every namespace. A misspelled
`Reall` still warns.

The `stdlib` parameter (and `--no-stdlib` on the CLI) controls this
fallback:

| Value | Behavior |
|---|---|
| `None` (default) | Attach the library to the resolver when it loads. If it cannot load, degrade to resolution without it. |
| `True` | Force the library. Raise if it cannot load. |
| `False` / `--no-stdlib` | Never consult the library. Every library reference then warns. |

### Implied specializations resolve inherited names

The SysML v2 specification requires every definition kind to specialize
a base element of the Systems Model Library, even when the model text
declares no specialization. The resolver honors these implied
specializations, so library members inherited through them resolve in
expressions. This is why `start` and `done` resolve inside a plain
`action def`: the action implicitly specializes `Actions::Action`, which
owns them.

The full map is
{data}`longeron.interpreter.IMPLIED_SPECIALIZATIONS`. Representative
entries:

| Declared kind | Implied definition base | Implied usage subsetting |
|---|---|---|
| `part def` / `part` | `Parts::Part` | `Parts::parts` |
| `action def` / `action` | `Actions::Action` | `Actions::actions` |
| `attribute def` / `attribute` | `ScalarValues::DataValue` | — |
| `requirement def` / `requirement` | `Requirements::RequirementCheck` | `Requirements::requirementChecks` |
| `state def` / `state` | `States::StateAction` | `States::stateActions` |

## The two strict modes

The CLI exposes two independent tightening flags:

| Flag | Effect |
|---|---|
| `--strict` | Exit `1` when any warning exists, not only errors. The diagnostics themselves are unchanged. This is the CI gate. |
| `--strict-imports` | Emit `stdlib-implicit-name` for bare standard-library names that resolve only through the implicit library-visibility hop. Qualified names (`ScalarValues::Real`) and explicitly imported names stay silent. Use it when your team requires every dependency to be spelled out. |

`--strict` is a CLI policy about the exit code. In the Python API,
apply the same policy by checking severities yourself:

```python
diagnostics = longeron.validate(model)
errors = [d for d in diagnostics if d.severity == "error"]
```

`strict_imports=True` is the API spelling of `--strict-imports`
({func}`~longeron.validation.validate`).

## The dimensional lint

The five unit diagnostics above implement the core tier of the
[units design](../design/units.md). The interpreter deliberately
evaluates `5.0 [SI::kg] + 30.0 [SI::min]` to `35.0` -- units are
annotations, and evaluation sees only floats -- so the lint is where
that bug class gets caught:

```text
warning[dimension-mismatch] P::Drone::nonsense: operands of '+' have different dimensions: 'kg' [kg] vs 'min' [s]
```

**Where dimensions come from.** {mod}`longeron.units` derives an
exponent-vector table from the vendored quantities library's *own
definitional algebra*: the `SystemOfUnits` declaration seeds the basis
(`m, kg, s, A, K, mol, cd`), derived units evaluate their definitional
expressions (`newton = kg*m/s^2`) in unit space,
`ConversionByPrefix` / `ConversionByConvention` members inherit their
reference unit's vector, and `IntervalScale` / the dB family seed the
scale tags. A user package shaped like the standard library -- typed
units with definitional expressions or conversions -- derives the same
way with no mapping table; {func}`longeron.units.register_unit` covers
anything derivation cannot reach.

**What carries a dimension.** A `[unit]` annotation on a value; an
attribute whose value expression has one (transitively, through
redefinition and subsetting chains); and quantity subsetting or typing
(`attribute mass :> ISQ::mass`, `attribute d : LengthValue`). Unknown
dimensions are bottom and propagate silently -- a bare `35.0` could be
anything, so the lint only speaks when two *known* vectors conflict.
Scaling by a bare numeric literal keeps the known operand's dimension
(`2.0 * mass` is still a mass).

**Scales outrank dimensions.** Every unit carries a scale tag:
`linear` (almost everything), `offset` (interval scales -- `°C`, and
any unit an interval scale displays through), `log` (`dB` and
anything spelled `dB...`, `oct`, `dec`, `Np`). Mixing scales under
`+`/`-` is an **error** where a dimension mismatch is only a warning:
`25 [°C] + 298.15 [K]` is wrong by 273.15 no matter how temperature-
shaped both sides are. Convert explicitly (the `[units]` extra's
{func}`longeron.units.convert`) or model in kelvin.

Validation stays static and float-free: the lint reads annotations and
declarations, never evaluates, and adds one pass over the same owned
expressions the name checks already walk. With `stdlib=False` the
derived table is limited to units the model itself declares, and
library references warn as `unresolved-unit` like every other library
name.

## What validation does not do

Validation is static. It never evaluates expressions, so a constraint
that always fails validates cleanly. To evaluate constraints against an
instance, use
{meth}`Interpreter.check <longeron.interpreter.Interpreter.check>` or
[`longeron check`](cli.md#longeron-check). Type checking of expression
operands is also out of scope.
