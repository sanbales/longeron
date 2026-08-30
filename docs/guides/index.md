# Guides

Each guide covers one task end to end. For executable walk-throughs, use
the [tutorials](../tutorials/index.md). For signatures and docstrings, use
the [API reference](../reference/index.md).

| Guide | Use it when you want to |
|---|---|
| [Command line](cli.md) | run any `longeron` subcommand, with every flag and exit code |
| [Workspaces & caching](workspaces.md) | load multi-file projects and control the model cache |
| [API server & client](api-server.md) | serve a workspace over the OMG Systems Modeling API, or fetch/push models from one |
| [Validation](validation.md) | lint a model and act on each diagnostic code |
| [Evidence](evidence.md) | cite the documents behind a model's values, and verify the citations |
| [Grammar conformance](grammar.md) | know exactly where the parser follows, patches, or deviates from the OMG grammar |
| [Notation coverage](notation-coverage.md) | know exactly which SysML v2 graphical notations the diagrams draw, and which they do not |
| [Choosing an analysis](analysis.md) | pick between trade studies, MDAO sizing, SMT checks, and RDF/RAG queries |
| [Development](contributing.md) | build, test, and contribute — including the notebook conventions |

```{toctree}
:hidden:
:maxdepth: 1

cli
workspaces
api-server
validation
evidence
grammar
notation-coverage
analysis
contributing
```
