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

Scope: these checks are a curated set aimed at real modeling mistakes.
They now include a corpus-calibrated selection of the clause-8.3
well-formedness constraints (the [kind-level checks](#kind-level-well-formedness)
below), but they are not an implementation of the OCL constraints
embedded in the OMG spec metamodel, and conformance claims keep those
axes separate (the corpus badge measures *parsing* conformance).
Rationale in the design doc:
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
| `unresolved-reference` | warning | A declared reference does not resolve: `typed by`, `specializes`, `subsets`, `redefines`, `references`, `crosses`, connection/binding ends, `satisfied by`, an import, an alias, a dependency end, a named multiplicity bound (`part p : D[n]` with no `n`), or a `perform` target. |
| `dangling-succession` | warning | A succession end in an action body does not resolve: `first a1 then ghost;` (the action-body analog of `unknown-state`, at reference-check severity). Bottom-guarded: owners whose implied library base is unmapped (`use case`), owners with explicit specializations, and bodies with `terminate`-style declarations are not judged. |
| `dangling-expose` | warning | An `expose` inside a view usage names an element that no longer resolves. Restoring the view ([view persistence](../reference/views.md)) skips such exposes with a warning; this diagnostic surfaces the same condition statically. |
| `dangling-flow` | warning | A `flow` or `message` end (`from` / `to`) does not resolve: `flow of Fuel from tank.nope to engine.fuelIn`. The model layer stores flow ends as verbatim paths, so a dangling end silently disconnects the flow -- diagrams skip the edge, analyses have nothing to bind. A warning, like the other reference checks: the end may live in a file you did not load. |
| `flow-payload-mismatch` | warning | A flow's declared payload typing has no specialization relationship -- in either direction -- with the target end's declared typing: `flow of Water from tank.fuelOut to engine.fuelIn` where `fuelIn : Fuel`. See [Flow connectivity](#flow-connectivity). |
| `unresolved-name` | warning | The leading name of an expression does not resolve. Locals, loop variables, accept payloads, builtin functions, and inherited members are recognized first. Qualified chains through packages and definitions are checked step-wise too (`P::D::nope`, `E::c` with no such literal); chains through *usage* heads are not judged (their member closure is richer than the model's static members). |
| `no-entry-transition` | warning | A state machine declares states but no `entry; then <state>;` transition, so simulation has no starting state. |
| `calc-without-result` | warning | A calc has no result expression and no `return`-directed member with a value. Reference calc usages that delegate to a typed calc stay silent. |
| `unresolved-unit` | warning | A `[unit]` annotation does not resolve -- `= 5.0 [SI::bogusUnit]` or a `[furlongs]` no library defines. Bare stdlib unit names (`[kg]`) resolve through the implicit library hop and stay silent. |
| `dimension-mismatch` | warning | `+`, `-`, or a comparison whose operands carry conflicting dimension vectors: `mass + flightTime`, `mass < wingSpan`. A warning, not an error, per the spec's own "necessary but not sufficient" caveat (§9.8.9) -- dimension agreement can be checked mechanically, quantity-kind agreement cannot. |
| `scale-mismatch` | **error** | `+` or `-` whose operands carry different measurement *scales* (`linear` / `offset` / `log`): `20 [dBW] + 5 [W]`, `25 [°C] + 298.15 [K]`. Cross-scale linear arithmetic is never meaningful; convert explicitly. |
| `mixed-units` | warning | `+`, `-`, or a comparison over same-dimension operands declared in *different units* (`5.0 [kg] + 3.0 [lbm]`, `1.0 [m] + 2.0 [mm]`). Active only without the `[units]` extra: with it, declaration-boundary normalization makes the arithmetic correct and the warning moot. |
| `anchor-dimension-mismatch` | warning | A scoreboard-convention `ramp0` / `ramp1` / `target` / `limit` attribute disagrees with its sibling `measure` -- dimensionally, or (without the `[units]` extra) in declared unit: a ramp anchored in minutes scoring a measure computed in hours. |
| `stdlib-implicit-name` | warning | Only under `strict_imports=True` / `--strict-imports`. A bare standard-library name resolved only through the implicit library-visibility hop. |
| `usage-type` | error | A declared type resolves to a definition of a conflicting kind, or to a package: `attribute a : D` with `D` a part def, `action a : D`, `part p : P` with `P` a package. Pilot: `validateAttributeUsageType`, `validateActionUsageType`, `validateUsageType`. |
| `metadata-usage-type` | error | A metadata annotation (`#Meta part p;`, `@Meta;`) resolves to something other than a metadata definition. Pilot: `validateMetadataUsageType`. Unresolved annotation names stay silent (user-defined keywords may live in unloaded files). |
| `attribute-composite-feature` | error | A composite occurrence feature (part, state, action, port, ...) owned by an attribute definition or usage: `attribute def A { state s; }`. Spec: `validateAttributeDefinitionFeatures` / `validateAttributeUsageFeatures`. Items are deliberately not judged -- the spec's own corpus nests composite items in attribute definitions. |
| `port-composite-usage` | error | A composite (non-`ref`, undirected) part/state/action usage owned by a port definition or usage: `port def Q { part p : D; }`. Directed features (`out item fuel : Fuel;`) are the spec's own port idiom and stay silent. Pilot: `validatePortDefinitionOwnedUsagesNotComposite`. |
| `interface-end-not-port` | error | An interface definition end typed by a non-port definition (`interface def I { end w : W; }` with `W` a part def), or an interface usage end resolving to a non-port usage (`interface i : I connect a to b;` over parts). Pilot: `validateInterfaceDefinitionEnd` / `validateInterfaceUsageEnd`. |
| `connector-end-not-feature` | error | A connector, interface, or binding end resolves to a definition or package rather than a feature: `connect a to D1;`. KerML: a Connector's `relatedFeatures` must be Features. |
| `subsets-non-feature` | error | A subsetting target resolves to a package or a definition: `part p subsets P;`. KerML: `Subsetting::subsettedFeature` must be a Feature. Reference usages (`satisfy R1 by ...`, `verify`, `include`, exhibits) may legally name definitions and are not judged. |
| `redefinition-featuring-types` | error | A redefinition targets a sibling feature (same featuring type) or a package-level feature: `attribute x : Real; attribute y :>> x;`. Pilot: `validateRedefinitionFeaturingTypes`. Redefining an *inherited* same-named feature stays legal. |
| `datatype-specialization` | error | An attribute or enum definition specializes an occurrence definition: `attribute def A :> D;` with `D` a part def. KerML: a DataType may not specialize a Class or Association. |
| `behavior-specialization` | error | A behavior-family definition (action, calc, state, constraint, requirement, case, ...) specializes a structure-family or data definition: `action def A :> D;`. |
| `structure-specialization` | error | A structure-family definition (part, item, port, connection, ...) specializes a behavior-family or data definition. |
| `variant-membership` | error | A `variant` usage owned by a non-variation namespace: `part def D { variant part v; }`. Spec: `validateVariantMembershipOwningNamespace`. |
| `variation-membership` | error | A non-variant usage owned by a `variation` definition or usage. Pilot: `validateDefinitionVariationMembership`. |
| `state-subaction-kind` | error | More than one `entry`, `do`, or `exit` action in one state body. Spec: `validateStateDefinitionStateSubactionKind`. |
| `only-one-subject` | error | More than one `subject` in one requirement/case body. Spec: `validateRequirementDefinitionOnlyOneSubject` and its case twin. |
| `only-one-return-parameter` | error | More than one `return` parameter in one calc/action body. KerML: a Function has exactly one result parameter. |
| `individual-definition` | error | A usage typed by more than one `individual` definition: `individual part p : I1, I2;`. Spec: `validateOccurrenceUsageIndividualDefinition`. |
| `enum-attribute-type` | error | An attribute typed by an enumeration definition carries more than one declared type: `attribute e : E, E;`. Pilot: `validateAttributeUsageEnumerationType`. |
| `send-payload` | error | An anonymous, unrouted `send;` with no payload argument. Pilot: `validateSendActionUsagePayloadArgument`. Named send declarations and routed sends (`send via ... to ...;`) bind their payload elsewhere and stay silent. |
| `exhibit-state-reference` | error | An `exhibit` reference resolves to something other than a state: `part a; exhibit a;`. Spec: `validateExhibitStateUsageReference` ("Must reference a state"). |
| `perform-action-reference` | error | A `perform` reference resolves to something other than an action: `attribute b : Real; perform b;`. Pilot: `validatePerformActionUsageReference` ("Must reference an action"). |
| `multiplicity-bound-type` | error | A literal multiplicity bound that is not a natural number: `part p : D[1.5];`, `D["two"]`. KerML: `validateMultiplicityRangeResultTypes` ("Must have a Natural value"). `*` is an infinity literal and always fine. |
| `multiplicity-bound-order` | error | A literal range whose lower bound exceeds its upper: `part p : D[2..1];` -- an unsatisfiable (empty) range. |

## Kind-level well-formedness

The error rows above from `usage-type` through `multiplicity-bound-order`
implement a corpus-calibrated selection of the SysML v2 clause-8.3
constraints (spec `validate*` names) and the pilot implementation's
validator rules (`SysMLValidator.xtend` / `KerMLValidator.xtend`), under
one contract inherited from the dimensional lint: **only speak when two
known things conflict**. A check fires only when a reference *resolves*
and the resolved element's kind is known to conflict -- a
resolved-but-wrong-kind target is a structural self-contradiction and
therefore an error, while an unresolved reference stays a warning
(`unresolved-reference`), because the target may live in a file you did
not load. Kinds outside the check's vocabulary -- language-extension
definitions, keyword-less `feature`/`ref` usages -- are bottom: no
guessing.

Every check was calibrated against the 309-file OMG corpus, and four
deliberate deviations from the literal rule text keep the spec's own
models clean:

- **Items in attribute bodies are not judged.** The rule says *all*
  features of an attribute definition must be non-composite, but the
  spec's training models nest composite items there
  (`attribute def Show { item picture : Picture; }`).
- **Directed features are never composite-checked** and there is no
  directed-parameter-placement check at all: the pilot's corpus places
  directed features in part definitions and usages (`in item scene;`),
  so SysML textual direction does not map to KerML ParameterMembership.
- **Reference usages may name definitions.** `satisfy R1 by x;` names a
  requirement definition; the pilot mints a usage typed by it.
- **Vendored-library kinds are bottom.** The KerML libraries project
  `datatype` onto the item kind (`Collections::Array`), so kind
  judgments skip targets inside library packages.

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

## Flow connectivity

`flow of Payload from a.out to b.in` stores its ends and payload as
plain text that nothing resolves at parse time, so a typo'd end or a
wrong payload type is invisible until something downstream silently
ignores the flow. Two diagnostics close that gap:

```text
plant.sysml:11:9: warning[dangling-flow] P::Plant: flow source 'tank.nope' does not resolve
plant.sysml:12:9: warning[flow-payload-mismatch] P::Plant: payload 'Water' is incompatible with flow target 'engine.fuelIn' (accepts 'Fuel')
```

**What carries the typing.** The payload's declared type (`flow of
Diesel ...`, `flow of x : Diesel ...`) is checked against the target
end's declared type: the target usage's `typed by`, or -- for messages
to a named accept action (`action receiveIt accept hit : Pong;`) --
the accept's payload typing.

**What counts as incompatible.** Only provably unrelated types warn:
the payload and target types must have *no* specialization relationship
in either direction. A `Diesel` payload flowing into a `Fuel` port is
fine (`Diesel :> Fuel`); a declared `Fuel` payload into a `Diesel` port
is also silent, because the feature may well hold a conforming value at
runtime. Where typing is absent on either side -- an untyped target
feature, a payload feature with no declared type, a payload that does
not resolve -- the check stays silent rather than guess. Like the
dimensional lint, it only speaks when two *known* typings conflict.

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
