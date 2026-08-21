"""The ``sysml2`` compatibility alias (the package was renamed to longeron).

Exercises the shim in ``src/sysml2/__init__.py``: top-level import,
submodule imports (machinery path), from-imports (module ``__getattr__``
path), identity with the real longeron modules, and the CLI entry point.
"""

import importlib
import subprocess
import sys

import pytest

import longeron
import sysml2


def test_top_level_import_matches_longeron():
    assert sysml2.__version__ == longeron.__version__
    assert sysml2.__all__ == list(longeron.__all__)
    # same objects, not re-implementations
    assert sysml2.loads is longeron.loads
    assert sysml2.Interpreter is longeron.Interpreter
    assert sysml2.SysMLError is longeron.SysMLError


def test_top_level_api_works_through_the_alias():
    model = sysml2.loads("package P { part def V { attribute m : Real = 2.0; } }")
    assert sysml2.Interpreter(model).instantiate("P::V").slots["m"] == 2.0
    assert "part def V" in sysml2.to_sysml(model)


def test_submodule_import_statement():
    import sysml2.analysis.trades
    import sysml2.rdf

    assert sysml2.rdf is importlib.import_module("longeron.rdf")
    assert sysml2.analysis.trades is importlib.import_module("longeron.analysis.trades")
    # aliased entries land in sys.modules under both names, as the SAME module
    assert sys.modules["sysml2.rdf"] is sys.modules["longeron.rdf"]
    # and the real module is not renamed by the aliasing
    assert sys.modules["longeron.rdf"].__name__ == "longeron.rdf"
    assert sys.modules["longeron.rdf"].__spec__.name == "longeron.rdf"


def test_from_import():
    from sysml2.workspace import cache_dir

    from sysml2 import diagrams, replay

    assert diagrams is importlib.import_module("longeron.diagrams")
    assert replay is importlib.import_module("longeron.replay")
    assert cache_dir is longeron.workspace.cache_dir


def test_missing_submodule_raises_under_the_alias_name():
    with pytest.raises(ImportError):
        importlib.import_module("sysml2.no_such_module")
    with pytest.raises(AttributeError):
        sysml2.no_such_attribute  # noqa: B018


def test_cli_entry_point_is_longerons():
    from sysml2.cli import main

    assert main is longeron.cli.main


def test_alias_works_in_a_fresh_interpreter():
    # `import sysml2` FIRST (before any longeron import) must also work
    code = (
        "import sysml2, sysml2.rdf, longeron\n"
        "assert sysml2.loads is longeron.loads\n"
        "assert sysml2.rdf is longeron.rdf\n"
        "m = sysml2.loads('package P { part def X; }')\n"
        "assert 'part def X' in sysml2.to_sysml(m)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
