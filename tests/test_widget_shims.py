"""The 0.12 widget-move deprecation shims: old paths work, warn once.

The widget layer consolidated under :mod:`longeron.widgets` (the
catalog ratification's deferred physical moves).  Every pre-move import
path must keep working through a shim that fires ONE
:class:`DeprecationWarning` naming the new home -- and nothing inside
longeron itself may import through a shim: ``import longeron``, the
catalog, and the split compute modules (:mod:`longeron.replay`,
:mod:`longeron.analysis.mission3d`) stay warning-free.
"""

from __future__ import annotations

import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import longeron

pytest.importorskip("anywidget")  # the moved homes are widget modules

REPO = Path(longeron.__file__).resolve().parents[2]

#: module shims: old path -> new home (whole-module moves)
MODULE_SHIMS = {
    "longeron.explorer": "longeron.widgets.explorer",
    "longeron.inspector": "longeron.widgets.inspector",
    "longeron.app": "longeron.widgets.app",
    "longeron.analysis.viewer3d": "longeron.widgets.viewer3d",
}

#: attribute forwarders on split modules: (module, attribute) -> new home
ATTRIBUTE_SHIMS = {
    ("longeron.replay", "replay_widget"): "longeron.widgets.replay",
    ("longeron.analysis.mission3d", "mission_viewer"): "longeron.widgets.mission3d",
    ("longeron.analysis.mission3d", "CESIUM_VERSION"): "longeron.widgets.mission3d",
}


def _run(code: str) -> None:
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


@pytest.mark.parametrize(("old", "new"), sorted(MODULE_SHIMS.items()))
def test_module_shim_warns_once_and_forwards(old, new):
    # a fresh interpreter: the warning fires on FIRST import only
    _run(
        "\n".join(
            [
                "import importlib, warnings",
                "with warnings.catch_warnings(record=True) as caught:",
                "    warnings.simplefilter('always')",
                f"    old = importlib.import_module({old!r})",
                "deps = [w for w in caught if issubclass(w.category, DeprecationWarning)",
                "        and 'longeron' in str(w.message)]",
                "assert len(deps) == 1, [str(w.message) for w in caught]",
                f"assert {new!r} in str(deps[0].message)",
                "with warnings.catch_warnings(record=True) as again:",
                "    warnings.simplefilter('always')",
                f"    importlib.import_module({old!r})",
                "assert not [w for w in again if issubclass(w.category, DeprecationWarning)",
                "            and 'longeron' in str(w.message)], 'the shim warned twice'",
                # the shim forwards: same objects, star names and privates alike
                f"new = importlib.import_module({new!r})",
                "for name in new.__all__:",
                "    assert getattr(old, name) is getattr(new, name), name",
            ]
        )
    )


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_module_shims_forward_private_names():
    import longeron.analysis.viewer3d as old_viewer3d
    import longeron.app as old_app
    import longeron.widgets.app as new_app
    import longeron.widgets.viewer3d as new_viewer3d

    assert old_app._ICON_SVG is new_app._ICON_SVG
    assert old_viewer3d._ESM is new_viewer3d._ESM


@pytest.mark.parametrize(("target", "new_home"), sorted(ATTRIBUTE_SHIMS.items()))
def test_attribute_shim_warns_and_forwards(target, new_home):
    import importlib

    module_name, attribute = target
    module = importlib.import_module(module_name)
    home = importlib.import_module(new_home)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        value = getattr(module, attribute)
    deps = [w for w in caught if issubclass(w.category, DeprecationWarning)]
    assert len(deps) == 1
    assert f"{new_home}.{attribute}" in str(deps[0].message)
    assert value is getattr(home, attribute)


def test_split_modules_import_clean_and_unknown_names_still_raise():
    # importing the compute halves is NOT deprecated
    _run(
        "\n".join(
            [
                "import warnings",
                "with warnings.catch_warnings(record=True) as caught:",
                "    warnings.simplefilter('always')",
                "    import longeron.replay",
                "    import longeron.analysis.mission3d",
                "assert not [w for w in caught if issubclass(w.category, DeprecationWarning)",
                "            and 'longeron' in str(w.message)]",
            ]
        )
    )
    import longeron.analysis.mission3d
    import longeron.replay

    with pytest.raises(AttributeError, match="no_such_name"):
        _ = longeron.replay.no_such_name
    with pytest.raises(AttributeError, match="no_such_name"):
        _ = longeron.analysis.mission3d.no_such_name


def test_longeron_and_the_catalog_import_without_deprecation_warnings():
    # nothing in longeron itself may import through a shim: the package,
    # the catalog, and every catalog entry resolve warning-free
    _run(
        "\n".join(
            [
                "import warnings",
                "with warnings.catch_warnings(record=True) as caught:",
                "    warnings.simplefilter('always')",
                "    import longeron",
                "    import longeron.widgets",
                "    for name in longeron.widgets.__all__:",
                "        getattr(longeron.widgets, name)",
                "deps = [str(w.message) for w in caught",
                "        if issubclass(w.category, DeprecationWarning)",
                "        and 'longeron' in str(w.message)]",
                "assert not deps, deps",
            ]
        )
    )
