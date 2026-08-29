# Workspaces & caching

This guide covers loading models from files and directories, how
multi-file merges behave, and how the content-addressed model cache
works. The API reference for everything here is
{mod}`longeron.workspace`.

## `load()` dispatches on the path

{func}`~longeron.workspace.load` is the universal entry point. It
inspects the path and picks the loader:

| Input | Behavior |
|---|---|
| `model.sysml` | Parse the text and build the model. |
| `model.json` | Import a JSON export losslessly ({func}`~longeron.importer.from_json`). |
| a directory | Load every `*.sysml` file beneath it, recursively, and merge the results into one model. |

```python
import longeron

model = longeron.load("models/")  # a whole workspace
model = longeron.load_many(["lib.sysml", "app.json"])  # an explicit set
```

{func}`~longeron.workspace.load_many` loads an explicit list of `.sysml`
and `.json` files and merges them the same way.

## Directory loads merge under one root

A directory load produces one {class}`~longeron.model.Model` whose root
namespace holds the top-level members of every file. Cross-file imports
(`private import Units::*;`) and qualified references therefore resolve,
because every package lives under the same root.

Three rules keep directory loads deterministic:

1. Files load in sorted path order, so the merged member order never
   depends on the filesystem.
2. `.kerml` files are ignored. KerML is parse-and-validate only in this
   package, so KerML sources never contribute model elements.
3. If the directory contains no `.sysml` file, `load` raises
   {class}`~longeron.errors.BuildError` instead of returning an empty
   model.

To merge already-loaded models, use
{func}`~longeron.workspace.merge_models`.

## Saving a workspace back, file by file

A directory load remembers which file every top-level member came from
(`member.source_file`), and {func}`~longeron.export.save_workspace`
uses those breadcrumbs to write edits back **to the files they belong
to** -- the save path behind the model app's Save button for
directory-loaded entries:

```python
import longeron
from longeron import edit, export

model = longeron.load("models/")
tracker = edit.track(model)
edit.set_attribute_value(model, "Parts::Motor::mass", "0.075")
export.save_workspace(model, tracker.changes)  # -> [Path("models/parts.sysml")]
```

The rules, honestly enforced:

1. Every tracked edit ({mod}`longeron.edit`) maps to the top-level
   member(s) it touched; a rename maps to **every** file whose
   references its cascade rewrote.
2. Only mapped files whose regenerated text differs from disk are
   rewritten -- untouched files keep their bytes (and comments; a
   rewritten file is regenerated in {func}`~longeron.export.to_sysml`
   canonical form, exactly like a single-file save).
3. Anything unmappable refuses with {class}`~longeron.errors.SysMLError`
   and **nothing is written**: a top-level member with no recorded
   source file (added after the load), or a change record without a
   usable breadcrumb. The escape hatch is an explicit-path save-as
   ({func}`~longeron.export.save`), which writes one merged file.

{func}`~longeron.export.workspace_plan` returns what a save *would*
write (`{path: new_text}`) without touching disk -- the model app uses
it to put the file names on the Save button's tooltip.

## The model cache

Parsing is the slow step: the ANTLR Python runtime takes seconds per
file, and minutes for the standard library. Built models are therefore
cached on disk. A warm directory load is roughly 1000x faster than a
cold parse.

### What a cache entry is

A cache entry is plain JSON in the same lossless schema as
{func}`~longeron.export.to_json`. There are no pickles anywhere, so a
cache entry is inspectable text and never executes code on load.
Entries are written atomically, so concurrent processes cannot corrupt
the cache.

### How entries are keyed

The entry key combines two fingerprints:

- the SHA-256 of the source text, and
- a fingerprint of the generated parser, the builder, the model classes,
  the expression AST, and the package version.

Editing a source file, regenerating the grammar, or upgrading the
package each produce a new key, so stale entries are never read. Stale
entries are not an error. They sit unused until
{func}`~longeron.workspace.clear_cache` removes them.

### Where the cache lives

The cache directory is resolved in this order:

| Priority | Source | Value |
|---|---|---|
| 1 | `$LONGERON_CACHE_DIR` | that directory |
| 2 | `$XDG_CACHE_HOME` | `$XDG_CACHE_HOME/longeron` |
| 3 | default | `~/.cache/longeron` |

{func}`~longeron.workspace.cache_dir` returns the resolved directory,
and {func}`~longeron.workspace.clear_cache` deletes every entry.

### When caching is on

Caching defaults to on -- for single files as well as directories. The
dominant cold-load cost (ANTLR ATN warmup) is paid per process either
way, so a warm cache hit turns a multi-second CLI invocation into
milliseconds:

```python
longeron.load("models/")  # cached
longeron.load("one.sysml")  # cached too
longeron.load("one.sysml", cache=False)  # parse from source
```

Pass `cache=False` to opt out. On the command line,
`--no-cache` bypasses the cache for any model-consuming subcommand
(see the [CLI reference](cli.md#model-inputs-and-shared-options)).

Caching is best-effort: if the cache directory is not writable, `load`
still returns the built model and simply skips the store.

## The standard library uses the same machinery

{func}`~longeron.stdlib.standard_library_model` ships a prebuilt JSON
snapshot of the vendored standard library, fingerprinted against the
library sources and the model classes. The snapshot loads in
milliseconds. If the fingerprint is stale, the library rebuilds from its
`.sysml` sources through the same workspace cache.
