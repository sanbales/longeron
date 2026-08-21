# Package API & errors

## `sysml2`

```{eval-rst}
.. automodule:: sysml2
   :no-members:
```

The top level re-exports the everyday API; each object is documented on
its home-module page:

| Area | Names |
|---|---|
| Parse / build | {func}`~sysml2.builder.loads`, {func}`~sysml2.builder.build_model`, {func}`~sysml2.builder.parse_expression`, {func}`~sysml2.parser.parse_sysml_text`, {func}`~sysml2.parser.parse_kerml_text`, {func}`~sysml2.parser.parse_file`, {func}`~sysml2.parser.parse_expression_text` |
| Load / cache | {func}`~sysml2.workspace.load`, {func}`~sysml2.workspace.load_many`, {func}`~sysml2.workspace.load_dir`, {func}`~sysml2.workspace.load_file`, {func}`~sysml2.workspace.merge_models`, {func}`~sysml2.workspace.cache_dir`, {func}`~sysml2.workspace.clear_cache` |
| Export | {func}`~sysml2.export.to_json`, {func}`~sysml2.export.to_dict`, {func}`~sysml2.export.to_sysml`, {func}`~sysml2.export.save`, {func}`~sysml2.kerml.to_kerml` |
| Import | {func}`~sysml2.importer.from_json`, {func}`~sysml2.importer.from_dict` |
| Validate | {func}`~sysml2.validation.validate`, {class}`~sysml2.validation.Diagnostic` |
| Standard library | {func}`~sysml2.stdlib.add_standard_library`, {func}`~sysml2.stdlib.standard_library_model` |
| Execute | {class}`~sysml2.interpreter.Interpreter`, {class}`~sysml2.interpreter.Instance`, {class}`~sysml2.interpreter.ActionResult`, {class}`~sysml2.interpreter.SimulationResult` |
| Model elements | everything in {mod}`sysml2.model` and {mod}`sysml2.ast` |

## `sysml2.errors`

```{eval-rst}
.. automodule:: sysml2.errors
```
