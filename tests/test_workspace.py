"""Multi-file workspace loading and the content-addressed model cache."""

import json

import pytest

import longeron
from longeron import model as M
from longeron import workspace
from longeron.errors import BuildError

LIB_SOURCE = """
package Units {
    attribute def Mass;
    attribute gravity : Real = 9.81;
    calc def Weight { in m : Real; return : Real = m * gravity; }
}
"""

APP_SOURCE = """
package App {
    private import Units::*;
    part def Payload {
        attribute mass : Real = 12.0;
        attribute weight : Real = Weight(m = mass);
    }
}
"""


@pytest.fixture()
def workspace_dir(tmp_path):
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "units.sysml").write_text(LIB_SOURCE)
    (tmp_path / "app.sysml").write_text(APP_SOURCE)
    (tmp_path / "notes.kerml").write_text("package Ignored;")
    return tmp_path


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path_factory, monkeypatch):
    cache_root = tmp_path_factory.mktemp("longeron-cache")
    monkeypatch.setenv("LONGERON_CACHE_DIR", str(cache_root))
    return cache_root


class TestLoadDir:
    def test_merges_files(self, workspace_dir):
        model = longeron.load_dir(workspace_dir)
        assert model.find("Units") is not None
        assert model.find("App::Payload") is not None

    def test_kerml_files_ignored(self, workspace_dir):
        model = longeron.load_dir(workspace_dir)
        assert model.find("Ignored") is None

    def test_cross_file_imports_resolve(self, workspace_dir):
        model = longeron.load_dir(workspace_dir)
        interp = longeron.Interpreter(model)
        payload = interp.instantiate("App::Payload")
        assert payload.slots["weight"] == pytest.approx(12.0 * 9.81)

    def test_non_recursive(self, workspace_dir):
        model = longeron.load_dir(workspace_dir, recursive=False)
        assert model.find("App") is not None
        assert model.find("Units") is None

    def test_empty_dir_raises(self, tmp_path):
        with pytest.raises(BuildError, match=r"no \.sysml files"):
            longeron.load_dir(tmp_path)

    def test_owners_rewired(self, workspace_dir):
        model = longeron.load_dir(workspace_dir)
        for member in model.members:
            assert member.owner is model

    def test_generic_load_accepts_dir(self, workspace_dir):
        model = longeron.load(workspace_dir)
        assert model.find("App::Payload") is not None


class TestLoadMany:
    def test_explicit_files(self, workspace_dir):
        model = longeron.load_many(
            [workspace_dir / "lib" / "units.sysml", workspace_dir / "app.sysml"]
        )
        interp = longeron.Interpreter(model)
        assert interp.call("Units::Weight", m=2.0) == pytest.approx(19.62)

    def test_mixed_json_and_sysml(self, workspace_dir, tmp_path):
        lib = longeron.load_file(workspace_dir / "lib" / "units.sysml")
        json_path = tmp_path / "units.json"
        longeron.save(lib, json_path)
        model = longeron.load_many([json_path, workspace_dir / "app.sysml"])
        interp = longeron.Interpreter(model)
        payload = interp.instantiate("App::Payload")
        assert payload.slots["weight"] == pytest.approx(117.72)

    def test_empty_raises(self):
        with pytest.raises(BuildError, match="no files"):
            longeron.load_many([])


class TestCache:
    def test_cache_hit_creates_entry(self, workspace_dir, isolated_cache):
        longeron.load_file(workspace_dir / "app.sysml", cache=True)
        entries = list(isolated_cache.glob("*.json"))
        assert len(entries) == 1

    def test_cached_model_equivalent(self, workspace_dir):
        first = longeron.load_dir(workspace_dir)
        second = longeron.load_dir(workspace_dir)  # cache hit
        assert longeron.to_dict(second) == longeron.to_dict(first)
        interp = longeron.Interpreter(second)
        payload = interp.instantiate("App::Payload")
        assert payload.slots["weight"] == pytest.approx(117.72)

    def test_content_change_invalidates(self, workspace_dir, isolated_cache):
        path = workspace_dir / "app.sysml"
        longeron.load_file(path, cache=True)
        path.write_text(APP_SOURCE.replace("12.0", "99.0"))
        model = longeron.load_file(path, cache=True)
        mass = model.find("App::Payload::mass")
        assert mass.value.expr.to_text() == "99.0"
        assert len(list(isolated_cache.glob("*.json"))) == 2

    def test_corrupt_cache_entry_ignored(self, workspace_dir, isolated_cache):
        path = workspace_dir / "app.sysml"
        longeron.load_file(path, cache=True)
        entry = next(iter(isolated_cache.glob("*.json")))
        entry.write_bytes(b"not json {{{")
        model = longeron.load_file(path, cache=True)
        assert model.find("App::Payload") is not None

    def test_wrong_payload_ignored(self, workspace_dir, isolated_cache):
        path = workspace_dir / "app.sysml"
        longeron.load_file(path, cache=True)
        entry = next(iter(isolated_cache.glob("*.json")))
        entry.write_text(json.dumps({"not": "a model"}))
        model = longeron.load_file(path, cache=True)
        assert isinstance(model, M.Model)

    def test_cache_entries_are_readable_json(self, workspace_dir, isolated_cache):
        longeron.load_file(workspace_dir / "app.sysml", cache=True)
        entry = next(iter(isolated_cache.glob("*.json")))
        data = json.loads(entry.read_text())
        assert data["@type"] == "Model"  # to_json schema, not a pickle

    def test_load_defaults(self, workspace_dir, isolated_cache):
        # single file: cached by default
        longeron.load(workspace_dir / "app.sysml")
        assert len(list(isolated_cache.glob("*.json"))) == 1
        # directory: cached by default too
        longeron.load(workspace_dir)
        assert len(list(isolated_cache.glob("*.json"))) > 1

    def test_load_cache_opt_out(self, workspace_dir, isolated_cache):
        longeron.load(workspace_dir / "app.sysml", cache=False)
        longeron.load_file(workspace_dir / "app.sysml", cache=False)
        assert not list(isolated_cache.glob("*.json"))

    def test_single_file_warm_load_hits_cache(self, workspace_dir, isolated_cache):
        first = longeron.load(workspace_dir / "app.sysml")
        second = longeron.load(workspace_dir / "app.sysml")  # cache hit
        assert longeron.to_dict(second) == longeron.to_dict(first)
        assert len(list(isolated_cache.glob("*.json"))) == 1

    def test_clear_cache(self, workspace_dir, isolated_cache):
        longeron.load_dir(workspace_dir)
        assert list(isolated_cache.glob("*.json"))
        removed = longeron.clear_cache()
        assert removed >= 1
        assert not list(isolated_cache.glob("*.json"))

    def test_fingerprint_stable(self):
        assert workspace._fingerprint() == workspace._fingerprint()

    def test_fingerprint_depends_on_module_bytes(self, monkeypatch, tmp_path):
        # the cache key must change when the code that shapes built models
        # changes, or stale cached models survive upgrades
        from longeron import builder

        monkeypatch.setattr(workspace, "_FINGERPRINT", None)
        baseline = workspace._fingerprint()
        fake = tmp_path / "builder.py"
        fake.write_bytes(b"# a mutated builder\n")
        monkeypatch.setattr(builder, "__file__", str(fake))
        monkeypatch.setattr(workspace, "_FINGERPRINT", None)
        assert workspace._fingerprint() != baseline

    def test_fingerprint_depends_on_version(self, monkeypatch):
        import longeron as pkg

        monkeypatch.setattr(workspace, "_FINGERPRINT", None)
        baseline = workspace._fingerprint()
        monkeypatch.setattr(pkg, "__version__", "0.0.0-test")
        monkeypatch.setattr(workspace, "_FINGERPRINT", None)
        assert workspace._fingerprint() != baseline


class TestCacheDirEnv:
    """The override chain: LONGERON_CACHE_DIR, then $XDG_CACHE_HOME/longeron,
    then ~/.cache/longeron."""

    def test_longeron_var_is_primary(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "new"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
        assert workspace.cache_dir() == tmp_path / "new"

    def test_pre_rename_var_ignored(self, monkeypatch, tmp_path):
        # the pre-rename SYSML2_CACHE_DIR fallback was removed in 0.9.1
        # (the sysml2 name was ceded to OpenMBEE); it must do nothing now
        monkeypatch.delenv("LONGERON_CACHE_DIR", raising=False)
        monkeypatch.setenv("SYSML2_CACHE_DIR", str(tmp_path / "old"))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert workspace.cache_dir() == tmp_path / "longeron"

    def test_xdg_fallback(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LONGERON_CACHE_DIR", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert workspace.cache_dir() == tmp_path / "longeron"

    def test_home_fallback(self, monkeypatch):
        monkeypatch.delenv("LONGERON_CACHE_DIR", raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        assert workspace.cache_dir().parts[-2:] == (".cache", "longeron")


class TestCLI:
    def test_export_directory(self, workspace_dir, capsys):
        from longeron.cli import main

        assert main(["export", str(workspace_dir), "--format", "sysml"]) == 0
        out = capsys.readouterr().out
        assert "package App" in out
        assert "package Units" in out

    def test_calc_from_directory(self, workspace_dir, capsys):
        from longeron.cli import main

        assert main(["calc", str(workspace_dir), "Units::Weight", "m=3.0"]) == 0
        assert "29.4" in capsys.readouterr().out

    def test_parse_directory(self, workspace_dir, capsys):
        from longeron.cli import main

        assert main(["parse", str(workspace_dir)]) == 0
        out = capsys.readouterr().out
        assert out.count("OK:") == 2

    def test_no_cache_flag(self, workspace_dir, isolated_cache, capsys):
        from longeron.cli import main

        assert main(["export", str(workspace_dir), "--no-cache"]) == 0
        assert not list(isolated_cache.glob("*.json"))


class TestCacheHousekeeping:
    def test_clear_cache_removes_legacy_pickles(self, isolated_cache):
        (isolated_cache / "old.pkl").write_bytes(b"legacy")
        assert longeron.clear_cache() == 1
        assert not list(isolated_cache.glob("*.pkl"))

    def test_clear_cache_without_a_cache_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path / "never-created"))
        assert longeron.clear_cache() == 0
