# Vendored ipyelk

Source: https://github.com/jupyrdf/ipyelk
Tag: v2.1.1 (65c08ad lineage)
License: BSD-3-Clause (see LICENSE.txt)

Vendored for local TLC: install with `pip install -e vendor/ipyelk` (the
pixi environments do this automatically). The prebuilt JupyterLab extension
(`src/_d/share/...`) is grafted from the ipyelk 2.1.1 PyPI wheel because the
git tree only carries the TypeScript sources; regenerating it needs a
node/yarn toolchain (`js/`).

Local patches are tracked in this repo: `git log -- vendor/ipyelk`.
