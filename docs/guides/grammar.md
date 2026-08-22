# Grammar conformance

The parsers are generated with ANTLR 4 from combined grammars for
SysML v2 and KerML (`grammars/SysML.g4`, `grammars/KerML.g4`), taken from
[hivecore-dev/hcf-runtime](https://github.com/hivecore-dev/hcf-runtime)
and locally patched. This page states exactly what conforms, what was
patched, and the one known deviation.

> SysML® is a registered trademark of the Object Management Group. This
> project is not affiliated with or endorsed by OMG, and is not a
> conformance-certified implementation.

## The corpus result: 309 of 309 files parse and build

The official
[SysML-v2-Release](https://github.com/Systems-Modeling/SysML-v2-Release)
repository carries a corpus of 309 `.sysml` example files. Every file in
that corpus parses, and every file builds into the object model, with no
lossy fallback. Before grammar patches 6–10, the score was 283 parsed and
280 built.

The corpus itself is not vendored. Two things keep the number honest:

- `scripts/check_corpus.py` reproduces the sweep. It downloads the pinned
  release commit (the same revision the vendored standard library comes
  from), then parses and builds every `.sysml` file in it, printing
  `309/309 files parse and build`. Run it after grammar or builder
  changes; it is not part of the regular test suite.
- Each grammar patch carries regression tests derived from the corpus
  constructs that exposed it (`tests/test_parsing.py`,
  `tests/test_builder.py`). Those derived snippets -- not the full corpus
  -- are what every test run re-checks.

In two places the release BNF and the corpus contradict each other
(patches 8 and 10 below). There the grammar follows the corpus, and the
README entry for the patch records the conflict.

## The patch table

Each patch is marked with a `LOCAL PATCH` comment in the `.g4` files.
The [README](https://github.com/sanbales/longeron#grammar-patches)
carries the full rationale for each; the table below is the summary.

| # | Grammar | Patch |
|---|---|---|
| 1 | SysML | `import` accepts an optional visibility prefix, so the spec's own `import ScalarValues::*;` parses. |
| 2 | SysML | Entry transitions accept the spec form `entry; then S;` (upstream required a doubled `then`). |
| 3 | both | Unary operators bind tighter than binary operators, so `-3 + 1` parses as `(-3) + 1`. |
| 4 | SysML | Metadata and classification use the `@` symbol, keeping the keyword `at` for trigger times (four sites). |
| 5 | SysML | Flow ends accept dotted paths, so `flow from a.out to b.in` parses. |
| 6 | SysML | State-body transitions put the `then` clause before the action body, per the release BNF, so `accept s : Sig then b;` parses. |
| 7 | SysML | `standard` is optional, so a plain `library package P;` parses. |
| 8 | SysML | Named send nodes accept the corpus form `action publish send X() via p;` as well as the spec form. |
| 9 | both | A `//* ... */` note that closes on its own line lexes as a note instead of swallowing the rest of the line. |
| 10 | SysML | Enumerated values accept metadata prefixes, the corpus form `#Security enum secret : Level = 2;`. |

## The known deviation: operator precedence

One deviation from the OMG specification remains, inherited from the
upstream grammars:

- `??`, `or`, `and`, and `implies` share one precedence level, and `|`,
  `&`, and `xor` share another, where the specification separates them;
- `**` is left-associative.

When an expression mixes these operators, parenthesize. The exporter
always prints round-trip-safe parentheses, so exported text never
depends on the deviation.

## Regenerating the parsers

The generated parsers are committed under `src/longeron/_gen/`, so
installing and using the package needs no Java. Regenerate only after a
`.g4` change:

```bash
python scripts/generate_parsers.py    # or: pixi run parsers
```

The script finds Java through `JAVA_HOME`, `PATH`, or a conda/mamba
environment, and the ANTLR 4.13.2 jar through `ANTLR_JAR`, `~/.m2`, or
Maven Central. `pixi run parsers` needs no setup at all: conda-forge's
`antlr` package ships the tool and a JDK, and the task caches on its
inputs and produces byte-identical output. CI fails if the committed
parsers drift from the `.g4` sources.
