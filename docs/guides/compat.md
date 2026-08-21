# Migrating from `sysml2`

The project was renamed in 0.3.0: the distribution and the import
package are both `longeron`. Nothing pre-rename breaks. Every `sysml2`
name keeps working, without deprecation warnings, through the mappings
below.

## The name map

| Pre-rename | Now | Status of the old name |
|---|---|---|
| `import sysml2` | `import longeron` | works: a built-in compatibility shim |
| `sysml2` console command | `longeron` console command | works: installed as an alias entry point |
| `sysml2` PyPI distribution | `longeron` PyPI distribution | works: kept as a metadata-only alias that depends on `longeron` |
| `$SYSML2_CACHE_DIR` | `$LONGERON_CACHE_DIR` | works: still honored, after the new name |
| `~/.cache/sysml2` cache entries | `~/.cache/longeron` | cold on first load: the default cache directory changed, so the first post-rename load re-parses and re-caches |

## How the shim works

The package ships `src/sysml2/`, a compatibility shim, alongside
`longeron`. `import sysml2` hands back longeron's own module objects,
never copies. A meta-path finder resolves any submodule
(`sysml2.analysis.trades`, `from sysml2 import diagrams`) to the
matching `longeron` module.

Because both names share one set of module objects, module state and
`isinstance` checks agree across them. A `Model` built through
`longeron.loads` is the same class an old `sysml2` code path sees:

```python
import longeron, sysml2

sysml2.model is longeron.model  # True
isinstance(longeron.loads("package P;"), sysml2.model.Model)  # True
```

The shim is silent for now. No `DeprecationWarning` is emitted, and the
`sysml2` name is documented as a supported alias, not a deprecation.

## What to do in your code

Nothing is required. For new code, prefer the `longeron` names:

1. Write `import longeron` in new modules.
2. Call the `longeron` console command in new scripts and CI.
3. If you set a cache override, set `$LONGERON_CACHE_DIR`. Keep
   `$SYSML2_CACHE_DIR` only for environments you cannot update. When
   both are set, `$LONGERON_CACHE_DIR` wins.

Mixed codebases are safe: `sysml2` and `longeron` imports can coexist in
one process, because they resolve to the same modules.
