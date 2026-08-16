# sysml2-experiments

A Python package that defines, exports, and executes SysML v2 models. The
parsers are generated with ANTLR 4 from combined grammars for SysML v2 and
KerML, taken from
[hivecore-dev/hcf-runtime](https://github.com/hivecore-dev/hcf-runtime)
(`SysML.g4`, `KerML.g4`, with three local patches — see
[Grammar patches](#grammar-patches)).

## Capabilities

| Verb | What you get |
|---|---|
| **Define** | Parse SysML v2 textual notation into a Python object model, or build the model programmatically from dataclasses. |
| **Export** | Serialize any model to JSON or back to parseable SysML v2 text. Parse → print → parse round-trips preserve the model. |
| **Execute** | Evaluate expressions, run `calc` definitions, instantiate `part` definitions, check constraints and requirements, run `action` definitions, and simulate `state` machines. |

KerML support is syntactic: `parse_kerml_text` validates KerML sources and
returns a parse tree. Model building and execution operate on SysML.

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest            # 152 tests
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

## Command line

```bash
sysml2 parse examples/drone.sysml                      # syntax check (.kerml too)
sysml2 export examples/drone.sysml --format sysml      # or json
sysml2 calc examples/drone.sysml Drone::HoverTime capacity=5200
sysml2 check examples/drone.sysml Drone::QuadCopter payloadMass=0.9
sysml2 run examples/drone.sysml Drone::PlanBattery distanceKm=20
sysml2 simulate examples/drone.sysml Drone::FlightStates --events launch,airborne
```

## Project layout

```
grammars/                  SysML.g4 + KerML.g4 (upstream + local patches)
scripts/generate_parsers.py  regenerate src/sysml2/_gen from the grammars
src/sysml2/
    _gen/                  generated ANTLR lexers/parsers (committed)
    parser.py              text -> parse tree, error collection
    builder.py             parse tree -> model (the SysML front-end)
    model.py               model element dataclasses
    ast.py                 expression AST + precedence-aware printer
    export.py              model -> JSON / SysML text
    interpreter.py         evaluation, instantiation, actions, states
    cli.py                 the `sysml2` console command
examples/                  drone.sysml + demo.py
tests/                     152 pytest tests
```

### How a model flows through the package

1. `parser.py` runs the generated ANTLR parser and collects syntax errors.
2. `builder.py` walks the parse tree and produces `model.py` dataclasses.
   Expressions become compact AST nodes (`ast.py`), not parse-tree references.
3. `export.py` renders the model to JSON or back to textual notation.
4. `interpreter.py` resolves qualified names (imports, aliases,
   specialization) and executes the model.

Constructs outside the modeled subset (views, interfaces, flows, metadata
usages) are preserved as `Unsupported` elements that carry their verbatim
source text, so exports never silently drop content.

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

Three deviations from the upstream grammars, each marked with a
`LOCAL PATCH` comment in the `.g4` files:

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
