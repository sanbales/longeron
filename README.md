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
| **Define** | Parse SysML v2 textual notation into a fully-typed Python object model, import a model from its JSON export, or build models programmatically from dataclasses. Multi-file workspaces merge under one root; a content-addressed cache makes warm loads ~1000x faster. |
| **Export** | Serialize any model to JSON, back to parseable SysML v2 text, project it onto KerML, or emit OMG Systems-Modeling-API JSON records. Parse → print → parse round-trips preserve the model; JSON → model → JSON is lossless. |
| **Validate** | `sysml2.validate()` / `sysml2 lint`: dangling references, expression-name typos, duplicate names, specialization cycles, state-machine problems. |
| **Execute** | Evaluate expressions, run `calc` definitions, instantiate `part` definitions (against the bundled standard library if you opt in), check constraints and requirements, run `action` definitions with succession-driven control flow, and simulate hierarchical/parallel state machines with a clock. |
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
make check        # ruff + mypy + 310 tests
```

Optional: `pip install -e ".[ecore]"` enables the OMG spec-metamodel
projection and API JSON (pyecore); `pre-commit install` wires ruff+mypy
into every commit.

### With pixi (optional)

The repo also carries `[tool.pixi]` config in `pyproject.toml` (dependency
truth stays in `[project]`; pixi adds the locked toolchain on top):

```bash
pixi run check          # lint + mypy + tests in a locked environment
pixi run -e py310 test  # any supported Python: py310 | py311 | py312 | py313
pixi run parsers        # regenerate ANTLR parsers -- no manual Java setup:
                        # conda-forge's antlr 4.13.2 ships the tool + JDK
pixi run stdlib | demo | coverage | format
```

CI runs entirely on pixi (`prefix-dev/setup-pixi`, cached by `pixi.lock`):
a `check` job (lint + mypy + coverage), a test matrix across the four
Python environments, and a grammar-regen job that fails if the committed
parsers drift from the `.g4` sources. The `parsers` task is
input/output-cached locally and produces byte-identical output.

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

A complete walk-through lives in `examples/demo.py`, and five executable
tutorials live in [`notebooks/`](notebooks/):

| Notebook | Covers |
|---|---|
| `01_define_and_explore` | parsing, the object model, programmatic authoring, workspaces |
| `02_export_and_interchange` | SysML/JSON round-trips, save/load, KerML, spec metamodel, API JSON |
| `03_calculations_and_constraints` | expressions, calcs, instantiation, constraints, requirements, the full loop |
| `04_actions_and_states` | action graphs, hierarchical/parallel state machines, time |
| `05_stdlib_and_validation` | the vendored standard library, `sysml2 lint` |

The notebooks are executed by the test suite (`tests/test_notebooks.py`) and
can be refreshed with `pixi run notebooks`.

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

Built models are cached (as JSON — the same lossless schema as `to_json`,
never pickles) in `~/.cache/sysml2` (override with `$SYSML2_CACHE_DIR`),
keyed by source content plus a fingerprint of the generated parser and
builder code — edits, grammar regeneration, and package upgrades invalidate
cleanly. Caching is on by default for directories, off for single files
(`cache=` overrides; `sysml2.clear_cache()` wipes it). Warm directory loads
are ~1000x faster than cold parses with the ANTLR Python runtime.

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
    validation.py          sysml2 lint / validate()
    stdlib.py + _stdlib/   vendored OMG standard library (+ prebuilt pickle)
    ecore.py + _spec/      projection onto the OMG spec metamodel (pyecore)
    api.py                 OMG Systems Modeling API JSON interchange
    interpreter.py         evaluation, instantiation, actions, states, snapshot
    cli.py                 the `sysml2` console command
examples/                  drone.sysml + kernel.kerml + demo.py
tests/                     310 pytest tests (84% coverage)
.github/workflows/ci.yml   pixi-based: check + test matrix (3.10-3.13)
                           + grammar-regen drift check (antlr/JDK from lock)
Makefile                   make check = ruff + mypy + pytest (venv/pip route)
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

This is a modeling sandbox, not a full KerML semantic engine. What executes:

- **Actions**: bodies without successions run in declaration order. Bodies
  with explicit successions (`first start then a; first a then b;`) run as
  a control-flow graph: unreachable steps do not execute, `decide` nodes
  choose the first satisfied guard (with `else` fallback), guarded loops
  back-edge, and `fork`/`join` branches run sequentially in declaration
  order (no interleaving). `accept after d` / `accept at t` advance the
  action's clock (`ActionResult.time`); `accept when c` raises on a false
  condition (a would-be deadlock).
- **State machines** are hierarchical: composite states enter through their
  own `entry; then S;` transition, inner states get the first chance to
  consume an event, and exits cascade innermost-first. `parallel` states
  activate all child regions concurrently (`SimulationResult.active_states`).
  Time triggers (`accept after`/`accept at`) fire when a plain number in the
  event list advances the simulation clock; `accept when c` transitions fire
  as soon as their condition holds.
- Quantities evaluate to their magnitude: `10 [SI::m]` evaluates to `10`.
- **Standard library**: a curated subset of the official model library ships
  with the package (all 21 Systems Library files + core Quantities/Units +
  a KerML-kernel shim; see `sysml2/_stdlib/README.md`). Opt in with
  `sysml2.add_standard_library(model)` or `--stdlib` on the CLI: library
  types resolve (`Parts::Part`, `ISQ::mass`, `SI::kg`), `public import`
  re-exports and aliases follow, and `istype` checks work against library
  definitions. A bundled prebuilt pickle makes loading instant; the KerML
  Kernel Libraries themselves are not loaded (KerML is parse-only), so
  inherited library defaults that need unimplemented kernel functions
  degrade to `None` instead of failing. The prebuilt ships as plain JSON
  (`_stdlib/prebuilt.json`) — inspectable text, no pickles anywhere.
- Multiplicity expansion: exact bounds (`[4]`) expand fully; ranges
  populate their lower bound (`[0..*]` gives an empty list), which keeps
  the library's self-referential compositions finite.

## Spec-metamodel projection and API interchange

With the `ecore` extra installed, models project onto the OMG abstract
syntax (the pilot implementation's `SysML.ecore`, 175 metaclasses, vendored
under `sysml2/_spec/`):

```python
from sysml2 import ecore, api

spec = ecore.to_spec(model)      # reified memberships, FeatureTyping, ...
spec.report                       # what was covered / skipped
spec.save_xmi("model.xmi")       # EMF XMI

api.to_api_json(model)            # OMG Systems Modeling API records
api.from_api_json(text)           # records -> spec instances
```

Both are structural prototypes: names, flags, ownership, and
specialization/typing relationships are mapped; expression trees are not
(counted in `SpecReport`, never silently dropped).

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
