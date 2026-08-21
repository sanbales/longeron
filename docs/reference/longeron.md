# Package API & errors

## `longeron`

```{eval-rst}
.. automodule:: longeron
   :no-members:
```

The top level re-exports the everyday API; each object is documented on
its home-module page:

| Area | Names |
|---|---|
| Parse / build | {func}`~longeron.builder.loads`, {func}`~longeron.builder.build_model`, {func}`~longeron.builder.parse_expression`, {func}`~longeron.parser.parse_sysml_text`, {func}`~longeron.parser.parse_kerml_text`, {func}`~longeron.parser.parse_file`, {func}`~longeron.parser.parse_expression_text` |
| Load / cache | {func}`~longeron.workspace.load`, {func}`~longeron.workspace.load_many`, {func}`~longeron.workspace.load_dir`, {func}`~longeron.workspace.load_file`, {func}`~longeron.workspace.merge_models`, {func}`~longeron.workspace.cache_dir`, {func}`~longeron.workspace.clear_cache` |
| Export | {func}`~longeron.export.to_json`, {func}`~longeron.export.to_dict`, {func}`~longeron.export.to_sysml`, {func}`~longeron.export.save`, {func}`~longeron.kerml.to_kerml` |
| Import | {func}`~longeron.importer.from_json`, {func}`~longeron.importer.from_dict` |
| Validate | {func}`~longeron.validation.validate`, {class}`~longeron.validation.Diagnostic` |
| Standard library | {func}`~longeron.stdlib.add_standard_library`, {func}`~longeron.stdlib.standard_library_model` |
| Execute | {class}`~longeron.interpreter.Interpreter`, {class}`~longeron.interpreter.Instance`, {class}`~longeron.interpreter.ActionResult`, {class}`~longeron.interpreter.SimulationResult` |
| Model elements | everything in {mod}`longeron.model` and {mod}`longeron.ast` |

## `longeron.errors`

```{eval-rst}
.. automodule:: longeron.errors
```
