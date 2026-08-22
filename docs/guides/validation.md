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

Each diagnostic prints as `severity[code] element: message`:

```text
error[duplicate-name] Demo::Wheel: name 'Wheel' is already used by another member of Demo
warning[unresolved-reference] Demo::Vehicle::mass: typed by 'Reall' does not resolve
```

`element` is the qualified name of the subject element. `validate()`
returns diagnostics sorted errors-first, then by element and code.

Severities draw one line: structural problems that make the model
self-contradictory are errors, and references that merely fail to
resolve are warnings. An unresolved reference is a warning because the
missing target may live in a file you did not load.

## The diagnostic codes

| Code | Severity | Fires when |
|---|---|---|
| `duplicate-name` | error | Two members of one namespace share a name or short name. |
| `specialization-cycle` | error | An element's specialization hierarchy, including implied specializations, reaches the element itself. |
| `unknown-state` | error | A transition names a source or target that is not a state of its machine. |
| `unresolved-reference` | warning | A declared reference does not resolve: `typed by`, `specializes`, `subsets`, `redefines`, `references`, `crosses`, connection/binding ends, `satisfied by`, an import, an alias, or a dependency end. |
| `unresolved-name` | warning | The leading name of an expression does not resolve. Locals, loop variables, accept payloads, builtin functions, and inherited members are recognized first. |
| `no-entry-transition` | warning | A state machine declares states but no `entry; then <state>;` transition, so simulation has no starting state. |
| `calc-without-result` | warning | A calc has no result expression and no `return`-directed member with a value. Reference calc usages that delegate to a typed calc stay silent. |
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

## What validation does not do

Validation is static. It never evaluates expressions, so a constraint
that always fails validates cleanly. To evaluate constraints against an
instance, use
{meth}`Interpreter.check <longeron.interpreter.Interpreter.check>` or
[`longeron check`](cli.md#longeron-check). Type checking of expression
operands is also out of scope.
