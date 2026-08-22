"""L9: every optional-extra guard raises one type -- MissingExtraError.

Each test simulates the missing import (``sys.modules[name] = None`` makes
``import name`` raise ImportError) and checks that the guard surfaces a
:class:`~longeron.errors.MissingExtraError` carrying the uniform
``pip install "longeron[extra]"`` hint.  The exception is deliberately both
a ``SysMLError`` and an ``ImportError``, so handlers written against either
convention keep working.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from longeron.errors import MissingExtraError, SysMLError


def _block(monkeypatch, *modules: str) -> None:
    for name in modules:
        monkeypatch.setitem(sys.modules, name, None)


def test_missing_extra_error_is_both_import_and_sysml_error():
    err = MissingExtraError("a feature", "somepkg", "extra")
    assert isinstance(err, ImportError)
    assert isinstance(err, SysMLError)
    assert str(err) == 'a feature needs somepkg; install it with: pip install "longeron[extra]"'
    assert err.extra == "extra"
    assert err.command == 'pip install "longeron[extra]"'


def test_diagrams_needs_ipyelk(monkeypatch):
    _block(monkeypatch, "ipyelk")
    monkeypatch.delitem(sys.modules, "longeron.diagrams", raising=False)
    with pytest.raises(MissingExtraError, match=r"pip install -e vendor/ipyelk"):
        importlib.import_module("longeron.diagrams")


def test_replay_widget_needs_anywidget(monkeypatch):
    from longeron import replay

    monkeypatch.setattr(replay, "_WIDGET_CLS", None)
    _block(monkeypatch, "anywidget")
    with pytest.raises(MissingExtraError, match=r"longeron\[replay\]"):
        replay._widget_class()


def test_viz_figures_need_matplotlib(monkeypatch):
    from longeron.analysis import viz

    _block(monkeypatch, "matplotlib", "matplotlib.pyplot")
    with pytest.raises(MissingExtraError, match=r"longeron\[viz\]"):
        viz._plt()


def test_parcoords_needs_anywidget(monkeypatch):
    from longeron.analysis import viz

    monkeypatch.setattr(viz, "_PC_CLS", None)
    _block(monkeypatch, "anywidget")
    with pytest.raises(MissingExtraError, match=r"longeron\[viz\]"):
        viz._parcoords_class()


def test_dashboard_needs_ipywidgets(monkeypatch):
    from longeron.analysis import dashboard

    _block(monkeypatch, "ipywidgets")
    with pytest.raises(MissingExtraError, match=r"longeron\[viz\]"):
        dashboard._ipywidgets()


def test_moe_scatter_needs_anywidget(monkeypatch):
    from longeron.analysis import dashboard

    monkeypatch.setattr(dashboard, "_SCATTER_CLS", None)
    _block(monkeypatch, "anywidget")
    with pytest.raises(MissingExtraError, match=r"longeron\[viz\]"):
        dashboard._scatter_class()


def test_structure_widgets_need_anywidget(monkeypatch):
    from longeron.analysis import structure

    monkeypatch.setattr(structure, "_WIDGET_CLS", {})
    _block(monkeypatch, "anywidget")
    with pytest.raises(MissingExtraError, match=r"longeron\[viz\]"):
        structure._payload_widget("kind", "", "", "doc")


def test_viewer3d_needs_anywidget(monkeypatch):
    from longeron.analysis import viewer3d

    monkeypatch.setattr(viewer3d, "_VIEWER_CLS", None)
    _block(monkeypatch, "anywidget")
    with pytest.raises(MissingExtraError, match=r"longeron\[viz\]"):
        viewer3d._viewer_class()


def test_mdao_needs_openmdao(monkeypatch):
    from longeron.analysis import mdao

    _block(monkeypatch, "openmdao", "openmdao.api")
    with pytest.raises(MissingExtraError, match=r"longeron\[mdao\]"):
        mdao._om()


def test_smt_needs_z3(monkeypatch):
    from longeron.analysis import smt

    _block(monkeypatch, "z3")
    with pytest.raises(MissingExtraError, match=r"longeron\[smt\]"):
        smt._z3()


def test_trades_needs_ortools(monkeypatch):
    from longeron.analysis import trades

    _block(monkeypatch, "ortools", "ortools.sat", "ortools.sat.python")
    with pytest.raises(MissingExtraError, match=r"longeron\[trades\]"):
        trades._cp()


def test_geometry_needs_cadquery(monkeypatch):
    from longeron.analysis import geometry

    _block(monkeypatch, "cadquery")
    with pytest.raises(MissingExtraError, match=r"longeron\[cad\]"):
        geometry.to_cadquery(prop_diameter_in=5.0, motor_mass=0.03, battery_mass=0.2, esc_mass=0.01)


def test_server_needs_fastapi(monkeypatch, tmp_path):
    from longeron import server

    _block(monkeypatch, "fastapi")
    with pytest.raises(MissingExtraError, match=r"longeron\[server\]"):
        server.create_app(tmp_path)


def test_serve_needs_uvicorn(monkeypatch, tmp_path):
    from longeron import server

    _block(monkeypatch, "uvicorn")
    with pytest.raises(MissingExtraError, match=r"longeron\[server\]"):
        server.serve(tmp_path)


def test_client_needs_httpx(monkeypatch):
    from longeron.client import Client

    _block(monkeypatch, "httpx")
    with pytest.raises(MissingExtraError, match=r"longeron\[client\]"):
        Client()


def test_push_commit_model_projection_needs_pyecore(monkeypatch):
    import longeron
    from longeron.client import Client

    # make `from .api import to_api_records` fail inside the guard
    _block(monkeypatch, "longeron.api")
    client = Client(http=object())  # never used before the guard fires
    with pytest.raises(MissingExtraError, match=r"longeron\[ecore\]"):
        client.push_commit("proj", longeron.loads("package P;"))


def test_ecore_spec_metamodel_needs_pyecore(monkeypatch):
    from longeron import ecore

    ecore.spec_metamodel.cache_clear()
    ecore._resource_set.cache_clear()
    _block(monkeypatch, "pyecore", "pyecore.resources")
    try:
        with pytest.raises(MissingExtraError, match=r"longeron\[ecore\]"):
            ecore.spec_metamodel()
    finally:
        ecore.spec_metamodel.cache_clear()
        ecore._resource_set.cache_clear()


def test_rdf_needs_rdflib(monkeypatch):
    from longeron import rdf

    _block(monkeypatch, "rdflib")
    with pytest.raises(MissingExtraError, match=r"longeron\[rdf\]"):
        rdf._require_rdflib()


def test_missing_node_executable_stays_a_plain_sysml_error(monkeypatch):
    """The `node` binary is an environment prerequisite, not a pip extra,
    so render._find_node deliberately raises SysMLError (not
    MissingExtraError)."""

    from longeron import render

    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(SysMLError) as exc:
        render._find_node()
    assert not isinstance(exc.value, MissingExtraError)


def test_all_extra_guards_share_one_message_shape(monkeypatch):
    """The uniform contract: '<feature> needs <package>; install it with:'."""

    from longeron.client import Client

    _block(monkeypatch, "httpx")
    with pytest.raises(MissingExtraError) as exc:
        Client()
    assert "; install it with: " in str(exc.value)
    assert 'pip install "longeron[client]"' in str(exc.value)
