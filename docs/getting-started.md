# Getting started

## Install

`longeron` requires Python 3.10+ and has one hard dependency, the ANTLR
runtime. The generated parsers ship with the package, so installing and
using it needs no Java toolchain:

```bash
pip install longeron
```

The import name is `longeron`:

```python
import longeron
```

### Optional extras

Everything beyond parse/validate/execute/export sits behind extras, so
the core install stays light:

| Extra | Enables | Pulls in |
|---|---|---|
| `ecore` | OMG spec-metamodel projection ({mod}`longeron.ecore`) and Systems Modeling API JSON ({mod}`longeron.api`) | `pyecore` |
| `rdf` | RDF projection + SPARQL ({mod}`longeron.rdf`) | `rdflib` |
| `replay` | simulation/action replay widget ({mod}`longeron.replay`) | `anywidget` |
| `mdao` | OpenMDAO sizing bridge ({mod}`longeron.analysis.mdao`) | `openmdao` |
| `trades` | CP-SAT architecture trade studies ({mod}`longeron.analysis.trades`) | `ortools` |
| `smt` | requirement-consistency checks on Z3 ({mod}`longeron.analysis.smt`) | `z3-solver` |
| `viz` | trade-study figures + parallel-coordinates widget ({mod}`longeron.analysis.viz`) | `matplotlib`, `anywidget` |
| `cad` | cadquery solid export, for example STEP ({mod}`longeron.analysis.geometry`) | `cadquery` (~1 GB OCC kernel) |
| `docs` | build this documentation site | `sphinx`, `myst-nb`, `furo`, ... |
| `dev` | tests, lint, type-checking, notebook execution | `pytest`, `ruff`, `mypy`, solvers, ... |

```bash
pip install "longeron[mdao,trades,smt,viz]"   # the full analysis stack
```

The LLM retrieval substrate ({mod}`longeron.rag`) deliberately needs
**no extra**. Chunking, neighborhoods, and keyword search are stdlib
only, so the substrate works in any install.

Two features need more than an extra. Interactive diagrams
({mod}`longeron.diagrams`) need the vendored ipyelk from a source
checkout (`pip install -e vendor/ipyelk`). Headless SVG/PNG rendering
({mod}`longeron.render`) needs `node` on `PATH`.

### From source

```bash
git clone https://github.com/sanbales/longeron
cd longeron
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" -e vendor/ipyelk
make check        # ruff + mypy + full test suite
```

Or with [pixi](https://pixi.sh), which adds a locked toolchain (node,
the ANTLR tool, a JDK, JupyterLab) on top:

```bash
pixi run check    # lint + mypy + tests
pixi run lab      # JupyterLab in notebooks/
pixi run docs     # build this documentation site
```

The [development guide](guides/contributing.md) documents every task,
the git hooks, and the notebook conventions.

## Quickstart: parse → validate → simulate

```python
import longeron

model = longeron.loads("""
    package Demo {
        part def Vehicle {
            attribute mass : Real = 1200.0;
            attribute maxMass : Real = 2000.0;
            assert constraint massLimit { mass <= maxMass }
        }
        state def Power {
            entry; then off;
            state off;
            transition first off accept start then on;
            state on;
        }
    }
""")

# validate -- dangling references, typos, duplicate names, cycles; names
# resolve against the vendored standard library (that bare `Real` passes)
for diagnostic in longeron.validate(model):
    print(diagnostic)  # a clean model prints nothing

# execute
interp = longeron.Interpreter(model)
vehicle = interp.instantiate("Demo::Vehicle")
interp.check(vehicle)[0].passed  # True (mass <= maxMass)

result = interp.simulate("Demo::Power", events=["start"])
result.final_state  # 'on'
```

From here:

- the [tutorials](tutorials/index.md) walk every capability in depth,
  with executed outputs;
- the [guides](guides/index.md) cover one task per page, from the
  [CLI](guides/cli.md) to [choosing an analysis](guides/analysis.md);
- the [API reference](reference/index.md) documents each module;
- the [architecture page](architecture.md) explains how the pieces fit.
