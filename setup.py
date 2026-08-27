"""Wheel data files: the prebuilt JupyterLab launcher extension.

Everything declarative lives in ``pyproject.toml``; this file exists ONLY
because setuptools has no pyproject syntax for ``data_files`` -- the
mechanism that places files under ``{sys.prefix}/share/...`` at install
time, which is where JupyterLab discovers federated extensions.  It maps
the COMMITTED build in ``npm/_d`` (see ``npm/README.md``; the layout
mirrors the vendored ipyelk's ``src/_d`` precedent) plus
``npm/install.json`` into the wheel, so ``pip install longeron`` ships the
launcher tile with zero extra steps.

Editable installs do NOT place data files: for dev environments,
``pixi run sync-labextension`` rsyncs the build over the served copies.
"""

from pathlib import Path

from setuptools import setup

HERE = Path(__file__).parent.resolve()

#: the committed federated build (the npm package's jupyterlab.outputDir)
DATA_ROOT = HERE / "npm" / "_d"

#: where JupyterLab looks for the extension, relative to sys.prefix
EXTENSION_DIR = "share/jupyter/labextensions/longeron"


def labextension_data_files() -> list[tuple[str, list[str]]]:
    """``(install dir, [relative source paths])`` for every shipped file."""

    build = DATA_ROOT / EXTENSION_DIR
    if not (build / "package.json").is_file():
        raise SystemExit(
            f"the built labextension is missing from {build}; rebuild it with "
            "`cd npm && jlpm install && jlpm build` (see npm/README.md) -- a "
            "wheel without it would silently drop the launcher tile"
        )
    grouped: dict[str, list[str]] = {EXTENSION_DIR: ["npm/install.json"]}
    for path in sorted(build.rglob("*")):
        if path.is_file():
            target = path.parent.relative_to(DATA_ROOT).as_posix()
            grouped.setdefault(target, []).append(path.relative_to(HERE).as_posix())
    return sorted(grouped.items())


if __name__ == "__main__":
    setup(data_files=labextension_data_files())
