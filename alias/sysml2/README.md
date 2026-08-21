# sysml2 (alias)

This distribution is an **alias for
[`longeron`](https://pypi.org/project/longeron/)**:

```bash
pip install sysml2   # equivalent to: pip install longeron
```

The primary import name is `longeron`, but the historical name keeps
working — longeron ships a built-in `sysml2` compatibility shim, so **both**
imports below work whether you installed `sysml2` or plain `longeron`
(this alias distribution stays metadata-only):

```python
import longeron   # the real package
import sysml2     # compatibility alias, same module objects
```

Longeron defines, executes, and replays SysML v2 models in Python:
ANTLR-based SysML v2 + KerML parsers, lossless JSON interchange,
stdlib-aware validation with implied specializations, an interpreter
(calcs, constraints, requirements, actions, hierarchical/parallel state
machines with a clock), interactive JupyterLab diagrams, headless SVG/PNG
rendering, and simulation replay over state diagrams.

Code, docs, and issues: https://github.com/sanbales/longeron

> SysML® is a registered trademark of the Object Management Group. This
> project is not affiliated with or endorsed by OMG.
