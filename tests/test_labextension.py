"""Packaging truth for the JupyterLab launcher extension (``npm/``).

The launcher tile ships INSIDE the longeron wheel as data files: the
committed federated build ``npm/_d/share/jupyter/labextensions/longeron``
plus ``npm/install.json``, mapped by the repo-root ``setup.py`` (see its
docstring for why setuptools needs one).  These tests pin the invariants
a broken rebuild or a stale commit would silently violate; the CLICK
behavior itself is the browser tier's job
(``tests/browser/test_browser_launcher.py``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import longeron

REPO = Path(__file__).resolve().parents[1]
NPM = REPO / "npm"
BUILD = NPM / "_d" / "share" / "jupyter" / "labextensions" / "longeron"


def _build_package() -> dict:
    return dict(json.loads((BUILD / "package.json").read_text(encoding="utf-8")))


def test_built_extension_is_present_and_loadable() -> None:
    """The committed build carries a valid federated-extension manifest."""

    package = _build_package()
    assert package["name"] == "longeron"
    build_meta = package["jupyterlab"]["_build"]
    # the remoteEntry file JupyterLab actually loads must exist
    assert (BUILD / build_meta["load"]).is_file()
    assert build_meta["extension"] == "./extension"


def test_extension_version_matches_the_wheel() -> None:
    """npm/package.json, the built manifest, and longeron.__version__ agree."""

    source = json.loads((NPM / "package.json").read_text(encoding="utf-8"))
    assert source["version"] == longeron.__version__
    assert _build_package()["version"] == longeron.__version__


def test_install_json_names_the_python_package() -> None:
    """`jupyter labextension list` points uninstalls at pip, not npm."""

    data = json.loads((NPM / "install.json").read_text(encoding="utf-8"))
    assert data["packageName"] == "longeron"
    assert data["packageManager"] == "python"


def test_setup_data_files_cover_the_whole_build() -> None:
    """Every built file (plus install.json) lands under the data path."""

    spec = importlib.util.spec_from_file_location("longeron_setup", REPO / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # __name__ != "__main__": no setup() call

    mapping = dict(module.labextension_data_files())
    target_root = "share/jupyter/labextensions/longeron"
    assert all(target.startswith(target_root) for target in mapping)
    assert "npm/install.json" in mapping[target_root]
    shipped = {source for sources in mapping.values() for source in sources}
    built = {path.relative_to(REPO).as_posix() for path in BUILD.rglob("*") if path.is_file()}
    assert built, "the committed build is empty"
    assert built <= shipped


def test_tile_icon_matches_the_app_monogram() -> None:
    """The tile's svg is the sidebar tab's monogram, shape for shape.

    ``longeron.widgets.app._ICON_SVG`` is the identity users learn from the
    docked panel's tab; the launcher tile must not drift from it.
    """

    from longeron.widgets.app import _ICON_SVG

    index_ts = (NPM / "src" / "index.ts").read_text(encoding="utf-8")
    for line in _ICON_SVG.strip().splitlines():
        assert line.strip() in index_ts, f"icon shape missing from npm/src/index.ts: {line.strip()}"
