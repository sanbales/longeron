"""The longeron.widgets catalog: one import surface for every house widget.

The contract under test:

* every ``__all__`` entry resolves, and each catalog entry IS its home
  module's object (identity, not a copy);
* ``import longeron.widgets`` is lazy (PEP 562): no widget toolkit
  (ipywidgets, anywidget, matplotlib, ipyelk) and no widget home module
  reaches ``sys.modules`` until an entry is touched;
* a missing extra surfaces as :class:`~longeron.errors.MissingExtraError`
  with the pip hint on ACCESS, not at ``import longeron.widgets``;
* the docs catalog table (docs/reference/widgets/index.md) and
  ``__all__`` agree, so the catalog cannot drift from its documentation.
"""

from __future__ import annotations

import importlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import longeron
import longeron.widgets as widgets
from longeron.errors import MissingExtraError

CATALOG = widgets._CATALOG
REPO = Path(longeron.__file__).resolve().parents[2]


def test_all_is_the_catalog_plus_the_resident_module():
    assert set(widgets.__all__) == {*CATALOG, "graph3d"}
    assert widgets.__all__ == sorted(widgets.__all__)
    assert set(widgets.__all__) <= set(dir(widgets))


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_catalog_entry_is_the_home_object(name):
    home, attribute = CATALOG[name]
    assert getattr(widgets, name) is getattr(importlib.import_module(home), attribute)


def test_graph3d_resolves_as_the_resident_module():
    import longeron.widgets.graph3d

    assert widgets.graph3d is longeron.widgets.graph3d


def test_unknown_attribute_raises_attribute_error():
    with pytest.raises(AttributeError, match="no_such_widget"):
        _ = widgets.no_such_widget


def test_import_is_lazy_and_access_opens_the_seam():
    # a fresh interpreter: this test must not depend on what the rest of
    # the suite already imported
    code = "\n".join(
        [
            "import sys",
            "import longeron.widgets",
            "banned = ('ipywidgets', 'anywidget', 'matplotlib', 'ipyelk')",
            "leaked = [m for m in banned if m in sys.modules]",
            "assert not leaked, f'import longeron.widgets pulled {leaked}'",
            "homes = [m for m in sys.modules if m.startswith((",
            "    'longeron.explorer', 'longeron.inspector', 'longeron.app',",
            "    'longeron.diagrams', 'longeron.replay', 'longeron.analysis.',",
            "    'longeron.widgets.graph3d'))]",
            "assert not homes, f'import longeron.widgets pulled {homes}'",
            "longeron.widgets.explore  # first touch imports the home module",
            "assert 'longeron.explorer' in sys.modules",
            "assert 'anywidget' in sys.modules",
            "from longeron.explorer import explore",
            "assert longeron.widgets.explore is explore",
        ]
    )
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    subprocess.run([sys.executable, "-c", code], check=True, env=env)


def test_missing_extra_surfaces_on_access(monkeypatch):
    # the house convention: sys.modules[name] = None makes `import name`
    # raise ImportError, simulating the missing extra
    monkeypatch.setitem(sys.modules, "anywidget", None)
    monkeypatch.delitem(sys.modules, "longeron.explorer", raising=False)
    monkeypatch.delattr(widgets, "explore", raising=False)  # drop the lazy cache
    with pytest.raises(MissingExtraError, match=r'pip install "longeron\[replay\]"'):
        _ = widgets.explore


def test_docs_table_agrees_with_all():
    text = (REPO / "docs" / "reference" / "widgets" / "index.md").read_text()
    rows = re.findall(r"^\| `(\w+)` \|", text, flags=re.MULTILINE)
    assert len(rows) == len(set(rows)), "duplicate rows in the docs catalog table"
    assert set(rows) == set(widgets.__all__) - {"graph3d"}
