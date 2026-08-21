# Getting started

## Install

`longeron` requires Python 3.10+ and has a single hard dependency (the
ANTLR runtime). The generated parsers are shipped with the package, so no
Java toolchain is needed to install or use it:

```bash
pip install longeron
```

The import name is `sysml2`:

```python
import sysml2
```

### Optional extras

Everything beyond parse/validate/execute/export sits behind extras, so the
core install stays light:

| Extra | Enables | Pulls in |
|---|---|---|
| `ecore` | OMG spec-metamodel projection ({mod}`sysml2.ecore`) and Systems Modeling API JSON ({mod}`sysml2.api`) | `pyecore` |
| `replay` | simulation/action replay widget ({mod}`sysml2.replay`) | `anywidget` |
| `mdao` | OpenMDAO sizing bridge ({mod}`sysml2.analysis.mdao`) | `openmdao` |
| `trades` | CP-SAT architecture trade studies ({mod}`sysml2.analysis.trades`) | `ortools` |
| `smt` | requirement-consistency checks on Z3 ({mod}`sysml2.analysis.smt`) | `z3-solver` |
| `viz` | trade-study figures + parallel-coordinates widget ({mod}`sysml2.analysis.viz`) | `matplotlib`, `anywidget` |
| `cad` | cadquery solid export, e.g. STEP ({mod}`sysml2.analysis.geometry`) | `cadquery` (~1 GB OCC kernel) |
| `docs` | build this documentation site | `sphinx`, `myst-nb`, `furo`, ... |
| `dev` | tests, lint, type-checking, notebook execution | `pytest`, `ruff`, `mypy`, solvers, ... |

```bash
pip install "longeron[mdao,trades,smt,viz]"   # the full analysis stack
```

Interactive diagrams ({mod}`sysml2.diagrams`) additionally need the
vendored ipyelk from a source checkout (`pip install -e vendor/ipyelk`);
headless SVG/PNG rendering ({mod}`sysml2.render`) needs `node` on `PATH`.

### From source

```bash
git clone https://github.com/sanbales/longeron
cd longeron
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]" -e vendor/ipyelk
make check        # ruff + mypy + full test suite
```

Or with [pixi](https://pixi.sh) (locked toolchain, includes node, the
ANTLR tool + JDK, and JupyterLab):

```bash
pixi run check    # lint + mypy + tests
pixi run lab      # JupyterLab in notebooks/
pixi run docs     # build this documentation site
```

## Quickstart: parse → validate → simulate

```python
import sysml2

model = sysml2.loads("""
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
for diagnostic in sysml2.validate(model):
    print(diagnostic)  # a clean model prints nothing

# execute
interp = sysml2.Interpreter(model)
vehicle = interp.instantiate("Demo::Vehicle")
interp.check(vehicle)[0].passed  # True (mass <= maxMass)

result = interp.simulate("Demo::Power", events=["start"])
result.final_state  # 'on'
```

From here:

- the [tutorials](tutorials/index.md) walk every capability in depth,
  with executed outputs;
- the [API reference](reference/index.md) documents each module;
- the [architecture page](architecture.md) explains how the pieces fit.
