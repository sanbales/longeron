# longeron

*The spine of your system model* — a Python package that defines, exports,
imports, and **executes** SysML v2 models. The distribution is named
`longeron`; the import name is `longeron` (with `sysml2` kept as a
built-in compatibility alias). The parsers are generated with
ANTLR 4 from combined grammars for SysML v2 and KerML (see the
[grammar patches](architecture.md#grammar-patches) for local deviations).

> SysML® is a registered trademark of the Object Management Group. This
> project is not affiliated with or endorsed by OMG, and is not a
> conformance-certified implementation.

## Install

```bash
pip install longeron
```

Optional solver, visualization, and interchange features live behind
extras — see the [extras table](getting-started.md#optional-extras).

## Capabilities

```{include} ../README.md
:start-after: "## Capabilities"
:end-before: "## Installation"
```

## Where to go next

- [Getting started](getting-started.md) — install, extras, and a
  parse → validate → simulate quickstart.
- [Tutorials](tutorials/index.md) — the eight executable notebooks,
  run at docs-build time so every output is current.
- [API reference](reference/index.md) — autodoc pages for every module.
- [Architecture](architecture.md) — how a model flows through the
  package, the analysis stack, and the vendored pieces.
- [Release notes](release-notes.md) — what shipped in 0.2.0 and what is
  queued for 0.3.0.

```{toctree}
:hidden:

getting-started
tutorials/index
reference/index
architecture
release-notes
```
