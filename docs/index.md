# longeron

*The spine of your system model.* `longeron` is a Python package that
defines, exports, imports, and **executes** SysML v2 models. The import
name is `longeron`. The parsers are generated with
ANTLR 4 from combined SysML v2 and KerML grammars, and the full official
SysML-v2-Release corpus parses and builds
([grammar conformance](guides/grammar.md)).

> SysML® is a registered trademark of the Object Management Group. This
> project is not affiliated with or endorsed by OMG, and is not a
> conformance-certified implementation.

## Install

```bash
pip install longeron
```

The core install has one hard dependency, the ANTLR runtime. Solver,
visualization, and interchange features live behind extras
([extras table](getting-started.md#optional-extras)).

## Capabilities

```{include} ../README.md
:start-after: "## Capabilities"
:end-before: "## Installation"
```

## Where to go next

- [Getting started](getting-started.md) — install, extras, and a
  parse → validate → simulate quickstart.
- [Tutorials](tutorials/index.md) — nine executable notebooks. The
  documentation build runs them, so every output on those pages is
  current.
- [Guides](guides/index.md) — one task per page: the
  [command line](guides/cli.md), [workspaces & caching](guides/workspaces.md),
  [validation](guides/validation.md),
  [grammar conformance](guides/grammar.md),
  [choosing an analysis](guides/analysis.md), and
  [development](guides/contributing.md).
- [API reference](reference/index.md) — autodoc pages for every module.
- [Architecture](architecture.md) — how a model flows through the
  package, and what is vendored.
- [Release notes](release-notes.md) — what shipped in each release.

```{toctree}
:hidden:

getting-started
tutorials/index
guides/index
reference/index
architecture
release-notes
```
