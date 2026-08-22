# Command-line reference

The package installs one console command, `longeron`. It also installs
`sysml2`, the same program under the pre-rename name (see
[Migrating from sysml2](compat.md)). The eight subcommands map onto the
Python API one-to-one, so anything the command line does, a script can do.

| Subcommand | Does | Python equivalent |
|---|---|---|
| [`parse`](#longeron-parse) | syntax-check `.sysml`/`.kerml` sources | {func}`~longeron.parser.parse_file` |
| [`lint`](#longeron-lint) | validate a model and print diagnostics | {func}`~longeron.validation.validate` |
| [`export`](#longeron-export) | serialize a model to JSON, SysML, KerML, or API JSON | {func}`~longeron.export.to_json`, ... |
| [`calc`](#longeron-calc) | invoke a `calc def` as a function | {meth}`Interpreter.call <longeron.interpreter.Interpreter.call>` |
| [`check`](#longeron-check) | instantiate a `part def` and check its constraints | {meth}`Interpreter.instantiate <longeron.interpreter.Interpreter.instantiate>` + `check` |
| [`run`](#longeron-run) | execute an `action def` | {meth}`Interpreter.run_action <longeron.interpreter.Interpreter.run_action>` |
| [`simulate`](#longeron-simulate) | simulate a `state def` | {meth}`Interpreter.simulate <longeron.interpreter.Interpreter.simulate>` |
| [`serve`](#longeron-serve) | serve a workspace over the Systems Modeling API | {func}`~longeron.server.serve` |

## Model inputs and shared options

Every subcommand except `parse` takes a model input as its first argument.
The input takes one of three forms:

- a `.sysml` file, which is parsed and built;
- a `.json` export, which is imported losslessly;
- a directory, from which every `*.sysml` file is loaded and merged
  (see [Workspaces & caching](workspaces.md)).

The same subcommands share two options:

| Option | Effect |
|---|---|
| `--no-cache` | Bypass the [model cache](workspaces.md#the-model-cache) and parse from source. |
| `--stdlib` | Add the vendored [standard library](../reference/stdlib.md) to the loaded model, so library types resolve during execution. |

Every subcommand also accepts `--traceback` (see
[Errors and exit codes](#errors-and-exit-codes)).

`--stdlib` mutates the loaded model. `lint` does not need it: the
validator consults the standard library through its resolver by default
(see [Validation](validation.md#names-resolve-against-the-standard-library)),
and library-package internals are never the subject of diagnostics, so
`--stdlib` does not change what `lint` reports.

### `name=value` arguments

`calc`, `check`, and `run` accept trailing `name=value` arguments. Each
value is parsed as JSON when possible, and kept as a string otherwise.
For example, `capacity=5200` binds the number `5200`, `tested=true` binds
`True`, and `label=alpha` binds the string `"alpha"`.

## Errors and exit codes

Expected failures -- a missing or unreadable file, a syntax error, an
unknown qualified name, a malformed `.json` input, a missing optional
extra -- print a single `error: ...` line to stderr and exit `1`, without
a Python traceback:

```console
$ longeron calc examples/drone.sysml Drone::Nope
error: Drone has no member 'Nope'
```

Pass `--traceback` (any subcommand) to re-raise the underlying exception
with its full traceback. Genuinely unexpected errors -- bugs -- always
show their traceback.

| Code | Meaning |
|---|---|
| `0` | Success. For `check`: no constraint failed. For `lint`: no error (and, with `--strict`, no warning). |
| `1` | `lint` found errors (or warnings under `--strict`), `check` found a failed constraint, `parse` found no matching files in a directory or any file failed to parse, or an expected failure was reported (`error: ...` on stderr). |
| `2` | Command-line usage error (reported by argparse). |

## `longeron parse`

`parse` syntax-checks a source file, or every source file under a
directory, without building a model:

```console
$ longeron parse examples/drone.sysml
OK: examples/drone.sysml parses as sysml
```

| Option | Effect |
|---|---|
| `--kerml` | Force the KerML grammar. On a directory, check `**/*.kerml` instead of `**/*.sysml`. |
| `--tree` | Print the raw ANTLR parse tree for a single file. |

The grammar is chosen from the file suffix unless `--kerml` forces it.
In directory mode every file is reported -- failures print as `FAIL:`
lines with their syntax errors and do not stop the sweep; the exit code
is `1` when any file failed.
KerML support is parse-and-validate only. The builder, and therefore
every other subcommand, consumes SysML sources (see
[Grammar conformance](grammar.md)).

## `longeron lint`

`lint` validates a model and prints one line per diagnostic, then a
summary line:

```console
$ longeron lint demo.sysml
demo.sysml:3:5: error[duplicate-name] Demo::Wheel: name 'Wheel' is already used by another member of Demo
demo.sysml:5:9: warning[unresolved-reference] Demo::Vehicle::mass: typed by 'Reall' does not resolve
1 error(s), 1 warning(s)
```

The `file:line:column` prefix comes from parsing; models rebuilt from a
`.json` export or from a warm [model cache](workspaces.md#the-model-cache)
entry carry no source positions, so their diagnostics print without the
prefix. Pass `--no-cache` to re-parse and get positions back.

| Option | Effect |
|---|---|
| `--strict` | Treat warnings as errors: exit `1` when any diagnostic exists. |
| `--strict-imports` | Additionally warn (`stdlib-implicit-name`) when a bare standard-library name is used without an import. |
| `--no-stdlib` | Do not resolve names against the standard library. Every library reference then warns. |

The [Validation guide](validation.md) documents every diagnostic code,
its severity, and how name resolution works.

## `longeron export`

`export` serializes a model and writes it to stdout, or to `--output`:

```console
$ longeron export examples/drone.sysml --format sysml     # regenerated text
$ longeron export model.json --format sysml               # JSON in, SysML out
$ longeron export models/ --format json -o merged.json    # directory, merged
```

| Option | Effect |
|---|---|
| `--format {json,sysml,kerml,api}` | Output format (default `json`). `api` emits OMG Systems Modeling API records and needs the `ecore` extra. |
| `--no-derived` | With `--format api`: omit the derived `source`/`target` relationship endpoint arrays (emitted by default; pilot-API consumers need them for navigation). |
| `-o`, `--output PATH` | Write to a file instead of stdout. |

JSON round-trips are lossless. SysML output re-parses to the same model.
KerML is a one-way projection. See the
[interchange reference](../reference/interchange.md).

## `longeron calc`

`calc` invokes a `calc def` as a function and prints the result:

```console
$ longeron calc examples/drone.sysml Drone::HoverTime capacity=5200
26.0
```

The positional `name` is the qualified name of the calc. Trailing
`name=value` pairs bind its `in` parameters.

## `longeron check`

`check` instantiates a `part def`, prints the instance as JSON, and then
checks every constraint and requirement against it:

```console
$ longeron check examples/drone.sysml Drone::QuadCopter payloadMass=0.9
{ ... the instance, as JSON ... }
[FAIL] assert takeoffMassLimit: totalMass <= maxTakeoffMass
[PASS] assert canHover: 4.0 * 9.0 > totalMass * 9.81
$ echo $?
1
```

Each verdict line reads `[PASS]`, `[FAIL]`, or `[SKIP]` (a requirement
whose assumptions do not hold is skipped). Trailing `name=value` pairs
override attribute values, which makes `check` a one-line what-if tool.
If any constraint fails, the command exits `1`.

## `longeron run`

`run` executes an `action def` and prints the step trace, the outputs,
and any sent payloads:

```console
$ longeron run examples/drone.sysml Drone::PlanBattery distanceKm=20
  assign requiredWh := 7.4
  ...
outputs: {"requiredWh": 7.4, ...}
```

| Option | Effect |
|---|---|
| `--events NAMES` | Comma-separated event names, delivered to `accept` steps in order. |

Trailing `name=value` pairs bind the action's `in` parameters.

## `longeron simulate`

`simulate` starts a `state def`, feeds it events, and prints the
transition trace:

```console
$ longeron simulate examples/drone.sysml Drone::FlightStates --events launch,airborne
  idle --launch--> takingOff
  takingOff --airborne--> flying
final state: flying
```

| Option | Effect |
|---|---|
| `--events NAMES` | Comma-separated event names, sent in order. |

Events the machine cannot consume are reported on an
`ignored events:` line. The `--events` list carries event names only.
To advance the simulation clock for `accept after`/`accept at` triggers,
use the Python API, where a plain number in the `events` list advances
the clock ({meth}`~longeron.interpreter.Interpreter.simulate`).

## `longeron serve`

`serve` exposes a workspace as a git-backed [OMG Systems Modeling API
server](api-server.md) (requires `pip install "longeron[server]"`):

```console
$ longeron serve path/to/models --port 9000
INFO:     Uvicorn running on http://127.0.0.1:9000 (Press CTRL+C to quit)
```

| Option | Effect |
|---|---|
| `path` | Directory (or single `.sysml` file) to serve; defaults to `.`. |
| `--host ADDR` | Bind address. Defaults to `127.0.0.1`: the server is local-first and does **no authentication**. |
| `--port N` | Port; defaults to `9000` (the pilot-server convention). |

Unlike the other subcommands, `serve` takes no `--no-cache`/`--stdlib`
options: it always loads through the model cache, and it blocks until
interrupted. See [API server & client](api-server.md) for the resource
model, the git-commit mapping, and the `/x/` extension endpoints.
