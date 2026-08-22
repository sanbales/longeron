# Longeron

[![PyPI](https://img.shields.io/pypi/v/longeron)](https://pypi.org/project/longeron/)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)](https://pypi.org/project/longeron/)
[![CI](https://github.com/sanbales/longeron/actions/workflows/ci.yml/badge.svg)](https://github.com/sanbales/longeron/actions/workflows/ci.yml)
[![docs](https://github.com/sanbales/longeron/actions/workflows/docs.yml/badge.svg)](https://sanbales.github.io/longeron/)
[![coverage](https://img.shields.io/endpoint?url=https%3A%2F%2Fsanbales.github.io%2Flongeron%2Fbadges%2Fcoverage.json)](https://github.com/sanbales/longeron/actions/workflows/docs.yml)
[![SysML v2 corpus](https://img.shields.io/badge/SysML%20v2%20corpus-309%2F309-brightgreen)](https://sanbales.github.io/longeron/guides/grammar.html)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue)](https://github.com/sanbales/longeron/blob/main/LICENSE)

*The spine of your system model* — a Python package that defines,
exports, imports, and **executes** SysML v2 models (import name:
`longeron`). The parsers are generated with ANTLR 4 from combined grammars
for SysML v2 and KerML, taken from
[hivecore-dev/hcf-runtime](https://github.com/hivecore-dev/hcf-runtime)
(`SysML.g4`, `KerML.g4`, with local patches — see
[Grammar patches](#grammar-patches)).

> SysML® is a registered trademark of the Object Management Group. This
> project is not affiliated with or endorsed by OMG, and is not a
> conformance-certified implementation.

## Capabilities

| Verb | What you get |
|---|---|
| **Define** | Parse SysML v2 textual notation into a fully-typed Python object model, import a model from its JSON export, or build models programmatically from dataclasses. Multi-file workspaces merge under one root; a content-addressed cache makes warm loads ~1000x faster. |
| **Export** | Serialize any model to JSON, back to parseable SysML v2 text, project it onto KerML, or emit OMG Systems-Modeling-API JSON records. Parse → print → parse round-trips preserve the model; JSON → model → JSON is lossless. |
| **Validate** | `longeron.validate()` / `longeron lint`: dangling references, expression-name typos, duplicate names, specialization cycles, state-machine problems. Names resolve against the vendored standard library (a bare `Real` passes with no import; a typo like `Reall` warns), and plain definitions carry their *implied* specializations (`part def` → `Parts::Part`, `action def` → `Actions::Action`, which is how `start`/`done` resolve); opt out with `stdlib=False` / `--no-stdlib`. |
| **Execute** | Evaluate expressions, run `calc` definitions, instantiate `part` definitions (against the bundled standard library if you opt in), check constraints and requirements, run `action` definitions with succession-driven control flow, and simulate hierarchical/parallel state machines with a clock. |
| **Visualize** | `longeron.diagrams`: interactive ELK diagrams in JupyterLab (structure, state machines, action flow) with click-selection that resolves back to model elements. |
| **Query & retrieve** | Project any model onto RDF (`longeron.rdf`, rdflib) and ask SPARQL questions over structure, specializations, typed attribute values, variation points, and requirements. A dependency-free RAG substrate (`longeron.rag`) chunks the model into stable, re-parseable SysML fragments keyed by qualified name, walks semantic neighborhoods, and does keyword search — retrieval for LLM agents that cite names and resolve them through the interpreter for ground truth. |
| **Serve & sync** | `longeron serve` exposes any workspace as an OMG Systems-Modeling-API server with honest git-backed history: API commits *are* the git commits touching your `.sysml` sources, and pushed changes are materialized as text for you to review and commit — never auto-committed. `longeron.client.Client` fetches models from (and pushes changes to) any pilot-style server, and `/x/` extension endpoints add validate/instantiate/simulate/render over HTTP. |
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
make check        # ruff + mypy + 668 tests
```

Optional: `pip install -e ".[ecore]"` enables the OMG spec-metamodel
projection and API JSON (pyecore), `pip install -e ".[rdf]"` the RDF
projection (rdflib; the `longeron.rag` retrieval substrate needs no extra),
and `pip install -e ".[server]"` / `".[client]"` the Systems Modeling API
server (`longeron serve`) and REST client;
`pre-commit install` wires ruff+mypy
into every commit.

> **Renamed from `sysml2`:** the import package is `longeron` as of 0.3.0.
> The old names still work with no changes — the package ships a built-in
> `sysml2` compatibility shim (`import sysml2` hands back longeron's own
> modules) and keeps the `sysml2` console command; the `sysml2` PyPI
> distribution remains as a metadata-only alias of `longeron`.

### With pixi (optional)

The repo also carries `[tool.pixi]` config in `pyproject.toml` (dependency
truth stays in `[project]`; pixi adds the locked toolchain on top):

```bash
pixi run check          # lint + mypy + tests in a locked environment
pixi run -e py310 test  # any supported Python: py310 | py311 | py312 | py313
pixi run parsers        # regenerate ANTLR parsers -- no manual Java setup:
                        # conda-forge's antlr 4.13.2 ships the tool + JDK
pixi run lab            # JupyterLab in notebooks/ (vendored ipyelk extension
                        # pre-registered -- diagrams render interactively)
pixi run stdlib | demo | coverage | format | notebooks
```

CI runs entirely on pixi (`prefix-dev/setup-pixi`, cached by `pixi.lock`):
a `check` job (lint + mypy + coverage), a test matrix across the four
Python environments, and a grammar-regen job that fails if the committed
parsers drift from the `.g4` sources. The `parsers` task is
input/output-cached locally and produces byte-identical output.

The generated ANTLR parsers are committed under `src/longeron/_gen/`, so no
Java toolchain is needed to install or use the package. Java is only needed
to regenerate the parsers after a grammar change:

```bash
# any Java 11+ works; for example: mamba create -n jdk openjdk
python scripts/generate_parsers.py
```

## Quick start

```python
import longeron

model = longeron.loads("""
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
print(longeron.to_sysml(model))   # regenerated textual notation
print(longeron.to_json(model))    # structured JSON

# --- execute ------------------------------------------------------------
interp = longeron.Interpreter(model)

interp.call("Demo::Double", 21.0)            # -> 42.0
car = interp.instantiate("Demo::Vehicle")    # attributes evaluated
car.get("wheels")                            # -> [Instance, ...] (4 wheels)
interp.check(car)[0].passed                  # -> True (mass <= maxMass)
interp.evaluate("(1, 2, 3)->select { in x; x > 1 }")  # -> [2, 3]
```

Actions and state machines:

```python
model = longeron.loads("""
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
interp = longeron.Interpreter(model)
interp.run_action("Ops::Plan", inputs={"distance": 100.0}).outputs
# -> {'fuel': 8.0}
interp.simulate("Ops::Machine", events=["start"]).final_state
# -> 'on'
```

A complete walk-through lives in `examples/demo.py`, and eight executable
tutorials live in [`notebooks/`](notebooks/):

| Notebook | Covers |
|---|---|
| `01_define_and_explore` | parsing, the object model, programmatic authoring, workspaces |
| `02_export_and_interchange` | SysML/JSON round-trips, save/load, KerML, spec metamodel, API JSON |
| `03_calculations_and_constraints` | expressions, calcs, instantiation, constraints, requirements, the full loop |
| `04_actions_and_states` | action graphs, hierarchical/parallel state machines, time |
| `05_stdlib_and_validation` | the vendored standard library, `longeron lint` |
| `06_interactive_diagrams` | ipyelk structure/state/action diagrams, click-selection |
| `07_analysis_and_trades` | multi-mission UAV trade studies (interpreter-exact), OpenMDAO sizing + external-analysis binding, Z3 requirement consistency, 3D design views |
| `08_semantic_web_and_rag` | RDF projection + SPARQL queries, deterministic retrieval chunks, semantic neighborhoods, keyword search, the agent tool-use loop |

The notebooks are executed by the test suite (`tests/test_notebooks.py`) and
can be refreshed with `pixi run notebooks`.

```bash
python examples/demo.py
```

### The full loop: read → run → save

```python
model = longeron.load("examples/drone.sysml")
interp = longeron.Interpreter(model)

# run
flown = interp.instantiate("Drone::QuadCopter", payloadMass=0.35)

# write computed values back into the model as a bound part usage
model.find("Drone").add(interp.snapshot(flown, name="asFlown"))

# save in any format (inferred from the suffix)
longeron.save(model, "drone_with_results.sysml")
longeron.save(model, "drone_with_results.json")
longeron.save(model, "drone_with_results.kerml")

# the JSON export is lossless: reload and keep executing
again = longeron.load("drone_with_results.json")
longeron.Interpreter(again).instantiate("Drone::QuadCopter")
```

SysML or KerML text can be generated from just the JSON definition:

```python
model = longeron.from_json(json_text)   # or longeron.from_dict(data)
print(longeron.to_sysml(model))
print(longeron.to_kerml(model))         # kernel-language projection
```

### Multi-file projects and caching

`load()` accepts a single `.sysml` file, a `.json` export, or a directory:

```python
model = longeron.load("models/")            # every *.sysml file, merged
model = longeron.load_many(["lib.sysml", "app.json"])   # explicit set
```

Directory loads merge all files under one root namespace, so cross-file
imports (`private import Units::*;`) and qualified references resolve.
Files load in sorted path order for determinism.

Built models are cached (as JSON — the same lossless schema as `to_json`,
never pickles) in `~/.cache/longeron` (override with `$LONGERON_CACHE_DIR`;
the pre-rename `$SYSML2_CACHE_DIR` is still honored),
keyed by source content plus a fingerprint of the generated parser and
builder code — edits, grammar regeneration, and package upgrades invalidate
cleanly. Caching is on by default for directories, off for single files
(`cache=` overrides; `longeron.clear_cache()` wipes it). Warm directory loads
are ~1000x faster than cold parses with the ANTLR Python runtime.

## Command line

```bash
longeron parse examples/drone.sysml                      # syntax check (file or dir)
longeron export examples/drone.sysml --format sysml      # json | sysml | kerml
longeron export model.json --format sysml                # JSON in, SysML out
longeron export models/ --format json                    # whole directory, merged
longeron calc examples/drone.sysml Drone::HoverTime capacity=5200
longeron check examples/drone.sysml Drone::QuadCopter payloadMass=0.9
longeron run examples/drone.sysml Drone::PlanBattery distanceKm=20
longeron simulate examples/drone.sysml Drone::FlightStates --events launch,airborne
```

Every model-consuming command accepts `.sysml`, `.json`, or a directory;
`--no-cache` bypasses the model cache.

## Project layout

```
grammars/                  SysML.g4 + KerML.g4 (upstream + local patches)
scripts/generate_parsers.py  regenerate src/longeron/_gen from the grammars
src/longeron/
    _gen/                  generated ANTLR lexers/parsers (committed)
    parser.py              text -> parse tree, error collection
    builder.py             parse tree -> model (the SysML front-end)
    model.py               model element dataclasses (Literal-typed vocabularies)
    ast.py                 expression AST + precedence-aware printer
    export.py              model -> JSON / SysML text, save()
    importer.py            JSON -> model (lossless round-trip)
    workspace.py           multi-file loading + content-addressed model cache
    kerml.py               model -> KerML projection
    validation.py          longeron lint / validate()
    stdlib.py + _stdlib/   vendored OMG standard library (+ prebuilt JSON)
    ecore.py + _spec/      projection onto the OMG spec metamodel (pyecore)
    api.py                 OMG Systems Modeling API JSON interchange
    rdf.py                 RDF projection + SPARQL convenience (rdflib)
    rag.py                 LLM retrieval substrate: chunks, neighborhoods, search
    diagrams.py            interactive ELK diagrams (ipyelk)
    render.py + _js/       headless SVG/PNG export (vendored elkjs via node)
vendor/ipyelk/             vendored ipyelk 2.1.1 + local fixes (editable)
    interpreter.py         evaluation, instantiation, actions, states, snapshot
    cli.py                 the `longeron` console command
src/sysml2/                compatibility shim: `import sysml2` is longeron
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
  `mypy` runs clean over `src/longeron` (generated code excluded).
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
  a KerML-kernel shim; see `longeron/_stdlib/README.md`). Opt in with
  `longeron.add_standard_library(model)` or `--stdlib` on the CLI: library
  types resolve (`Parts::Part`, `ISQ::mass`, `SI::kg`), `public import`
  re-exports and aliases follow, and `istype` checks work against library
  definitions. A bundled prebuilt JSON snapshot makes loading instant; the KerML
  Kernel Libraries themselves are not loaded (KerML is parse-only), so
  inherited library defaults that need unimplemented kernel functions
  degrade to `None` instead of failing. The prebuilt ships as plain JSON
  (`_stdlib/prebuilt.json`) — inspectable text, no pickles anywhere.
- Multiplicity expansion: exact bounds (`[4]`) expand fully; ranges
  populate their lower bound (`[0..*]` gives an empty list), which keeps
  the library's self-referential compositions finite.

## Interactive diagrams

`longeron.diagrams` renders models as interactive ELK diagrams in JupyterLab
(see `notebooks/06_interactive_diagrams.ipynb`):

```python
from longeron import diagrams

diagrams.structure_diagram(model)                 # defs, compartments, edges
diagrams.state_diagram(model.find("P::Machine"))  # hierarchical states
diagrams.action_diagram(model.find("P::Flow"))    # the executed succession graph
diagrams.diagram(element)                          # dispatch by kind

diagrams.on_select(widget, model, callback)        # clicks -> model elements
```

Node ids are qualified names, so browser selections resolve straight back to
model elements. Layout runs in the browser (elkjs), so diagrams also build
headlessly (tests, nbclient).

The same views export to images without a browser — `longeron.render` runs
the vendored elkjs (0.9.3, EPL-2.0, `longeron/_js/`) in a node subprocess and
draws styled SVG, with PNG via cairosvg (node + cairo ship in the pixi
environments):

```python
from longeron import render

render.to_svg(diagrams.state_diagram(machine), "machine.svg")
render.to_png(model, "model.png")   # builds a view automatically
```

State-machine simulations replay over that same diagram: `longeron.replay`
records a simulation (the `Interpreter.simulate` event protocol -- names
send events, numbers advance the clock) and animates it in the notebook
with play/pause, speed, and scrubbing. Active states light up green,
fired transitions pulse orange, and a readout line follows the scalar
env values. Action executions replay the same way over the action
diagram (`replay_widget` auto-detects action definitions, or pass
`kind="action"`), scrubbing over the executed named steps. Needs the
`replay` extra (`pip install "longeron[replay]"`, anywidget):

```python
from longeron import replay

replay.replay_widget(interp, "Machines::Player",
                     events=["play", 3600.0, "play"])
replay.replay_widget(interp, "Ops::Deploy", inputs={"tested": True})
```

ipyelk is **vendored** (`vendor/ipyelk`, BSD-3-Clause, tag v2.1.1) and
installed editable (`pip install -e vendor/ipyelk`; pixi does this
automatically) so it can be patched as needed. Current local fixes, all
marked `LOCAL PATCH` and tracked by `git log -- vendor/ipyelk`:

1. **Headless-safe scheduling** — `Pipe.schedule_run` raised
   `RuntimeError: no running event loop` outside Jupyter (plain scripts,
   pytest); it now no-ops cleanly when there is no frontend to lay out for.
2. **Prebuilt labextension grafted** — the git tree only carries TypeScript
   sources; the built JupyterLab extension from the 2.1.1 wheel is vendored
   under `src/_d/` so the editable install renders without a node toolchain.

## Spec-metamodel projection and API interchange

With the `ecore` extra installed, models project onto the OMG abstract
syntax (the pilot implementation's `SysML.ecore`, 175 metaclasses, vendored
under `longeron/_spec/`):

```python
from longeron import ecore, api

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
6. **Target transition clause order (SysML.g4).** Upstream put `ActionBody`
   before the `then` clause in `targetTransitionUsage`, so state-body
   transitions like `accept s : Sig then b;` or a bare `then off;` after a
   nested state could not parse. The release BNF (and `transitionUsage`
   itself) put `'then' TransitionSuccessionMember` first and `ActionBody`
   last.
7. **Optional `standard` (SysML.g4).** Upstream required the full
   `standard library package`, rejecting a plain `library package P;`. The
   spec marks `standard` as optional (`isStandard ?= 'standard'`).
8. **Named send nodes (SysML.g4).** The spec declares a send node as
   `ActionUsageDeclaration? 'send' ...` with no `action` keyword, but the
   pilot-implementation corpus writes `action publish send X() via p;`
   (mirroring `acceptNode`, whose `action x accept ...` form is spec-blessed)
   — and this library's own exporter prints named send actions that way. Here
   the release BNF contradicts the corpus; we follow the corpus and accept
   both forms.
9. **One-line multiline notes (both grammars).** `SINGLE_LINE_NOTE`
   (`'//' ~[\r\n]*`) out-competed `MULTILINE_NOTE` (`'//*' .*? '*/'`) via
   ANTLR's longest-match rule whenever the note closed on the same line, so
   `x = ( //* elided */ 4 );` swallowed everything after `*/`. Single-line
   notes now exclude a leading `*`.
10. **Metadata prefixes on enumerated values (SysML.g4).** The release BNF
    declares `EnumeratedValue = 'enum'? Usage` with no extension keywords,
    but the pilot corpus writes `#Security enum secret : Level = 2;` inside
    enum bodies. We follow the corpus and accept `UsageExtensionKeyword*`
    there, as `usagePrefix` already does.

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
