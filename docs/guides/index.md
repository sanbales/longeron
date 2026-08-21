# Guides

Each guide covers one task end to end. For executable walk-throughs, use
the [tutorials](../tutorials/index.md). For signatures and docstrings, use
the [API reference](../reference/index.md).

| Guide | Use it when you want to |
|---|---|
| [Command line](cli.md) | run any `longeron` subcommand, with every flag and exit code |
| [Workspaces & caching](workspaces.md) | load multi-file projects and control the model cache |
| [Validation](validation.md) | lint a model and act on each diagnostic code |
| [Grammar conformance](grammar.md) | know exactly where the parser follows, patches, or deviates from the OMG grammar |
| [Choosing an analysis](analysis.md) | pick between trade studies, MDAO sizing, SMT checks, and RDF/RAG queries |
| [Development](contributing.md) | build, test, and contribute — including the notebook conventions |
| [Migrating from sysml2](compat.md) | keep pre-0.3.0 code, commands, and caches working |

```{toctree}
:hidden:
:maxdepth: 1

cli
workspaces
validation
grammar
analysis
contributing
compat
```
