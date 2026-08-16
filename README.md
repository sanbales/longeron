# sysml2-experiments

A Python package that defines, exports, imports, and executes SysML v2
models. The parsers are generated with ANTLR 4 from combined grammars for
SysML v2 and KerML, taken from
[hivecore-dev/hcf-runtime](https://github.com/hivecore-dev/hcf-runtime)
(`SysML.g4`, `KerML.g4`, with local patches — see
[Grammar patches](#grammar-patches)).

## Capabilities

| Verb | What you get |
|---|---|
| **Define** | Parse SysML v2 textual notation into a fully-typed Python object model, import a model from its JSON export, or build models programmatically from dataclasses. |
| **Export** | Serialize any model to JSON, back to parseable SysML v2 text, or project it onto KerML. Parse → print → parse round-trips preserve the model; JSON → model → JSON is lossless. |
| **Execute** | Evaluate expressions, run `calc` definitions, instantiate `part` definitions, check constraints and requirements, run `action` definitions, and simulate `state` machines. |
| **Full loop** | Read a model, execute it, snapshot the results back into the model as bound part usages, and save (`.sysml`, `.json`, or `.kerml`). |

The builder covers the full grammar: every construct the SysML grammar
accepts (interfaces, views, flows, allocations, metadata annotations,
satisfy/verify/frame, filtered imports, ...) maps to a model class — there
is no lossy fallback. KerML support is asymmetric by design:
`parse_kerml_text` validates KerML sources syntactically, and `to_kerml`
projects SysML models onto the kernel language.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make check        # ruff + mypy + 216 tests
```

The generated ANTLR parsers are committed under `src/sysml2/_gen/`, so no
Java toolchain is needed to install or use the package. Java is only needed
to regenerate the parsers after a grammar change:

```bash
# any Java 11+ works; for example: mamba create -n jdk openjdk
python scripts/generate_parsers.py
```

## Quick start

```python
import sysml2

model = sysml2.loads("""
    package Demo {
        part def Vehicle {
            attribute mass : Real = 1200.0;
            attribute maxMass : Real = 2000.0;
            part wheels : Wheel[4];
            assert constraint massLimit { mass <= maxMass }
        }
        part def Wheel { attribute diameter : Real = 0.66; }
        calc def Double { in x : Real; return : Real = 2.0 * x; }
    }
""")

# --- export -------------------------------------------------------------
print(sysml2.to_sysml(model))   # regenerated textual notation
print(sysml2.to_json(model))    # structured JSON

# --- execute ------------------------------------------------------------
interp = sysml2.Interpreter(model)

interp.call("Demo::Double", 21.0)            # -> 42.0
car = interp.instantiate("Demo::Vehicle")    # attributes evaluated
car.get("wheels")                            # -> [Instance, ...] (4 wheels)
interp.check(car)[0].passed                  # -> True (mass <= maxMass)
interp.evaluate("(1, 2, 3)->select { in x; x > 1 }")  # -> [2, 3]
```

Actions and state machines:

```python
model = sysml2.loads("""
    package Ops {
        action def Plan {
            in distance : Real;
            out fuel : Real;
            assign fuel := distance * 0.08;
        }
        state def Machine {
            entry; then off;
            state off;
            transition first off accept start then on;
            state on;
        }
    }
""")
interp = sysml2.Interpreter(model)
interp.run_action("Ops::Plan", inputs={"distance": 100.0}).outputs
# -> {'fuel': 8.0}
interp.simulate("Ops::Machine", events=["start"]).final_state
# -> 'on'
```

A complete walk-through lives in `examples/demo.py`:

```bash
python examples/demo.py
```

### The full loop: read → run → save

```python
model = sysml2.load("examples/drone.sysml")
interp = sysml2.Interpreter(model)

# run
flown = interp.instantiate("Drone::QuadCopter", payloadMass=0.35)

# write computed values back into the model as a bound part usage
model.find("Drone").add(interp.snapshot(flown, name="asFlown"))

# save in any format (inferred from the suffix)
sysml2.save(model, "drone_with_results.sysml")
sysml2.save(model, "drone_with_results.json")
sysml2.save(model, "drone_with_results.kerml")

# the JSON export is lossless: reload and keep executing
again = sysml2.load("drone_with_results.json")
sysml2.Interpreter(again).instantiate("Drone::QuadCopter")
```

SysML or KerML text can be generated from just the JSON definition:

```python
model = sysml2.from_json(json_text)   # or sysml2.from_dict(data)
print(sysml2.to_sysml(model))
print(sysml2.to_kerml(model))         # kernel-language projection
```

### Multi-file projects and caching

`load()` accepts a single `.sysml` file, a `.json` export, or a directory:

```python
model = sysml2.load("models/")            # every *.sysml file, merged
model = sysml2.load_many(["lib.sysml", "app.json"])   # explicit set
```

Directory loads merge all files under one root namespace, so cross-file
imports (`private import Units::*;`) and qualified references resolve.
Files load in sorted path order for determinism.

Built models are cached (pickled) in `~/.cache/sysml2` (override with
`$SYSML2_CACHE_DIR`), keyed by source content plus a fingerprint of the
generated parser and builder code — edits, grammar regeneration, and package
upgrades invalidate cleanly. Caching is on by default for directories, off
for single files (`cache=` overrides; `sysml2.clear_cache()` wipes it).
Warm directory loads are ~1000x faster than cold parses with the ANTLR
Python runtime.

## Command line

```bash
sysml2 parse examples/drone.sysml                      # syntax check (file or dir)
sysml2 export examples/drone.sysml --format sysml      # json | sysml | kerml
sysml2 export model.json --format sysml                # JSON in, SysML out
sysml2 export models/ --format json                    # whole directory, merged
sysml2 calc examples/drone.sysml Drone::HoverTime capacity=5200
sysml2 check examples/drone.sysml Drone::QuadCopter payloadMass=0.9
sysml2 run examples/drone.sysml Drone::PlanBattery distanceKm=20
sysml2 simulate examples/drone.sysml Drone::FlightStates --events launch,airborne
```

Every model-consuming command accepts `.sysml`, `.json`, or a directory;
`--no-cache` bypasses the model cache.

## Project layout

```
grammars/                  SysML.g4 + KerML.g4 (upstream + local patches)
scripts/generate_parsers.py  regenerate src/sysml2/_gen from the grammars
src/sysml2/
    _gen/                  generated ANTLR lexers/parsers (committed)
    parser.py              text -> parse tree, error collection
    builder.py             parse tree -> model (the SysML front-end)
    model.py               model element dataclasses (Literal-typed vocabularies)
    ast.py                 expression AST + precedence-aware printer
    export.py              model -> JSON / SysML text, save()
    importer.py            JSON -> model (lossless round-trip)
    workspace.py           multi-file loading + content-addressed model cache
    kerml.py               model -> KerML projection
    interpreter.py         evaluation, instantiation, actions, states, snapshot
    cli.py                 the `sysml2` console command
examples/                  drone.sysml + kernel.kerml + demo.py
tests/                     216 pytest tests
Makefile                   make check = ruff + mypy + pytest
```

### How a model flows through the package

1. `parser.py` runs the generated ANTLR parser and collects syntax errors.
2. `builder.py` walks the parse tree and produces `model.py` dataclasses.
   Expressions become compact AST nodes (`ast.py`), not parse-tree references.
3. `export.py` renders the model to JSON or textual notation; `importer.py`
   reads the JSON back; `kerml.py` projects onto KerML.
4. `interpreter.py` resolves qualified names (imports, aliases,
   specialization) and executes the model; `snapshot` converts runtime
   instances back into model elements.

## Code quality

- **Typing**: modern PEP 585/604 annotations throughout; closed string
  vocabularies (`kind`, `direction`, `visibility`, operators, ...) are
  `typing.Literal` aliases (`model.UsageKind`, `ast.BinaryOp`, ...).
  `mypy` runs clean over `src/sysml2` (generated code excluded).
- **Linting**: `ruff` with `E, W, F, I, UP, B, C4, RUF` rules.
- `make check` runs ruff + mypy + the full test suite.

## Execution semantics (and their limits)

This is a modeling sandbox, not a full KerML semantic engine. The main
simplifications:

- Actions execute in declaration order. Successions (`first a then b`) are
  parsed and preserved, but they do not reorder execution. Fork/join/merge/
  decision nodes are modeled, not executed.
- `accept` pops the next event from the run's event queue and fails if the
  event does not match; there is no blocking or timers (`after`/`at`
  triggers parse but do not wait).
- Quantities evaluate to their magnitude: `10 [SI::m]` evaluates to `10`.
- Standard-library types (`Real`, `Integer`, `Boolean`, `String`) are
  checked structurally against Python values; the KerML standard library is
  not loaded.
- State machines are flat: nested states parse, and their transitions are
  lifted to the top level of the enclosing state definition.
- Multiplicity expansion happens only for exact bounds on parts
  (`part wheels : Wheel[4]` yields a list of 4 instances).

## Grammar patches

Deviations from the upstream grammars, each marked with a ``LOCAL PATCH``
comment in the `.g4` files:

1. **`import` visibility (SysML.g4).** Upstream required a visibility
   keyword before every `import`, which rejects the spec's own examples
   (`import ScalarValues::*;`). Aligned with KerML.g4's optional prefix.
2. **Entry transitions (SysML.g4).** Upstream required `entry; then then S;`
   because `targetSuccession` already contains `then`. The patch accepts the
   spec form `entry; then S;`.
3. **Unary operator precedence (both grammars).** Upstream parsed `-3 + 1`
   as `-(3 + 1)` because the unary alternative sat below the binary
   alternatives with a non-rightmost recursion. The patch moves unary above
   the binary operators, so `-3 + 1` is `(-3) + 1`.
4. **`@` vs `at` (SysML.g4, four sites).** In SysML, `AT` is the keyword
   `at` (trigger times) and the `@` symbol is `AT_SIGN`; upstream used `AT`
   in the metadata and classification rules copied from KerML (where `AT`
   itself is `'@'`). Upstream therefore required `at Safety` instead of
   `@Safety`, and `x at T` instead of `x @ T`.
5. **Flow ends (SysML.g4).** `flowEndSubsetting` dropped the spec's `'.'`
   after `QualifiedName`, so `flow from a.out to b.in` could not parse.

One known deviation from the OMG spec remains, inherited from upstream: the
grammar groups `??`/`or`/`and`/`implies` at one precedence level and
`|`/`&`/`xor` at another, and `**` is left-associative. Parenthesize when in
doubt; the exporter always prints round-trip-safe parentheses.

## Regenerating the parsers

```bash
python scripts/generate_parsers.py
```

The script finds Java via `JAVA_HOME`, `PATH`, or a conda/mamba env, and the
ANTLR 4.13.2 jar via `ANTLR_JAR`, `~/.m2`, or Maven Central. Regenerate
whenever a `.g4` file changes, then run `pytest`.
