# longeron (JupyterLab extension)

The JupyterLab **launcher tile** for [Longeron](https://github.com/sanbales/longeron)
(`pip install longeron` — the Python wheel ships this prebuilt extension, so
there is nothing to install from npm).

Click the **Longeron** tile (launcher category *Other*) and the extension:

1. starts — or reconnects to — one dedicated console session on the constant
   path `longeron-app`, using the server's default Python kernelspec;
2. executes `longeron.app.open(layout="lab")` in it, which docks the model
   workbench into the LEFT sidebar (no notebook required);
3. reports progress as toasts: in-progress while the kernel boots, success
   when the sidebar is up, and the kernel's own error (with the
   `pip install "longeron[explorer]"` hint when the import failed) otherwise.

A second click reuses the same session: the kernel-side `open()` is
idempotent, so it reveals the existing sidebar panel instead of duplicating
it. The console tab is the app's engine room — its namespace keeps the
returned handle bound as `app`.

## Layout

- `src/index.ts` — the single plugin (`longeron:launcher`): the `LabIcon`
  (the monogram from `longeron.app._ICON_SVG`, drift-guarded by
  `tests/test_labextension.py`), the `longeron:launch` command, and the
  `ILauncher`/`ICommandPalette` registrations.
- `_d/share/jupyter/labextensions/longeron/` — the COMMITTED federated
  build (the `jupyterlab.outputDir`), mirroring how `vendor/ipyelk` ships
  its `src/_d` build inside a wheel. The repo-root `setup.py` maps this
  tree (plus `install.json`) into the wheel as data files, so
  `pip install longeron` places it under
  `{sys.prefix}/share/jupyter/labextensions/longeron/`.

## Rebuilding

```bash
cd npm
jlpm install   # jupyterlab >= 4.1 provides jlpm (e.g. `pixi run` env)
jlpm build     # tsc -> lib/, then `jupyter labextension build .` -> _d/
```

Then commit the refreshed `_d/` output. Editable installs do **not** place
data files: for a dev environment run `pixi run sync-labextension`, which
rsyncs both this build and the vendored jupyter-elk build over the served
copies in `.pixi/envs/*/share/jupyter/labextensions/`.
