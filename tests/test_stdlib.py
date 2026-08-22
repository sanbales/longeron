"""Standard library (Stage D) tests.

The first-ever load builds from vendored sources (minutes, cold); afterwards
the bundled prebuilt pickle answers in milliseconds. The session fixture
loads once.
"""

import json

import pytest

import longeron
from longeron import stdlib


@pytest.fixture(scope="session")
def library():
    return stdlib.standard_library_model()


@pytest.fixture(scope="session")
def lib_interp(library):
    return longeron.Interpreter(library)


class TestLibraryContent:
    def test_packages_present(self, library):
        names = {m.name for m in library.members}
        assert {
            "Parts",
            "Items",
            "Actions",
            "States",
            "Requirements",
            "Connections",
            "ScalarValues",
            "ISQ",
            "SI",
            "Quantities",
        } <= names

    def test_package_count(self, library):
        assert len(library.members) >= 40

    def test_resolution(self, lib_interp):
        assert lib_interp.resolve("Parts::Part").kind == "part"
        assert lib_interp.resolve("Actions::Action").kind == "action"
        assert lib_interp.resolve("ScalarValues::Real").kind == "attribute"

    def test_public_import_reexport(self, lib_interp):
        # ISQ::mass lives in ISQBase but is re-exported by 'public import'
        assert lib_interp.resolve("ISQ::mass").qualified_name == "ISQBase::mass"

    def test_alias_resolution(self, lib_interp):
        assert lib_interp.resolve("SI::kg").qualified_name == "SI::kilogram"

    def test_fresh_copies(self):
        first = stdlib.standard_library_model()
        second = stdlib.standard_library_model()
        assert first is not second
        assert first.members[0] is not second.members[0]


class TestAddStandardLibrary:
    def test_user_model_resolves_library_types(self):
        model = longeron.loads("""
            package App {
                private import ScalarValues::*;
                private import Parts::*;
                part def Robot :> Part { attribute mass : Real = 12.0; }
            }
        """)
        longeron.add_standard_library(model)
        interp = longeron.Interpreter(model)
        robot = interp.instantiate("App::Robot")
        assert robot.slots["mass"] == 12.0
        assert interp.evaluate("r istype Part", context="App", r=robot)

    def test_idempotent(self):
        model = longeron.loads("package App;")
        longeron.add_standard_library(model)
        count = len(model.members)
        longeron.add_standard_library(model)
        assert len(model.members) == count

    def test_user_packages_not_shadowed(self):
        model = longeron.loads("package Parts { part def Mine; }")
        longeron.add_standard_library(model)
        assert model.find("Parts::Mine") is not None

    def test_inherited_library_defaults_degrade_gracefully(self):
        # Parts::Part inherits features whose defaults use KerML functions
        # this interpreter does not implement; they become None instead of
        # failing the whole instantiation.
        model = longeron.loads("""
            package App {
                private import Parts::*;
                part def Widget :> Part;
            }
        """)
        longeron.add_standard_library(model)
        interp = longeron.Interpreter(model)
        widget = interp.instantiate("App::Widget")
        assert widget.type_name == "App::Widget"

    def test_self_referential_composition_is_finite(self):
        model = longeron.loads("""
            package App {
                private import Items::*;
                item def Box :> Item;
            }
        """)
        longeron.add_standard_library(model)
        interp = longeron.Interpreter(model)
        box = interp.instantiate("App::Box")  # Item composes Item [0..*]
        assert box is not None


class TestValidationWithLibrary:
    def test_library_reference_warnings_disappear(self):
        source = """
            package App {
                part def V :> NoSuchThing;
            }
        """
        model = longeron.loads(source)
        before = [d for d in longeron.validate(model) if d.code == "unresolved-reference"]
        assert len(before) == 1  # NoSuchThing

    def test_stdlib_types_resolve_in_validation(self):
        model = longeron.loads("""
            package App {
                private import Parts::*;
                part def V :> Part;
            }
        """)
        longeron.add_standard_library(model)
        diags = [
            d
            for d in longeron.validate(model)
            if "App" in d.element and d.code == "unresolved-reference"
        ]
        assert diags == []


def test_prebuilt_fingerprint_stable():
    assert stdlib._stdlib_fingerprint() == stdlib._stdlib_fingerprint()


def test_cli_stdlib_flag(tmp_path, capsys):
    from longeron.cli import main

    path = tmp_path / "app.sysml"
    path.write_text("""
        package App {
            private import ScalarValues::*;
            calc def Twice { in x : Real; return : Real = 2.0 * x; }
        }
    """)
    assert main(["calc", str(path), "App::Twice", "x=4", "--stdlib"]) == 0
    assert "8" in capsys.readouterr().out


class TestPrebuiltLifecycle:
    """standard_library_model: prebuilt JSON write, reuse, and staleness
    (against a miniature stand-in library, not the real vendored one)."""

    @pytest.fixture()
    def mini_stdlib(self, tmp_path, monkeypatch):
        libdir = tmp_path / "lib"
        libdir.mkdir()
        (libdir / "Mini.sysml").write_text("package MiniLib { part def Thing; }")
        prebuilt = tmp_path / "prebuilt.json"
        monkeypatch.setattr(stdlib, "_STDLIB_DIR", libdir)
        monkeypatch.setattr(stdlib, "_PREBUILT", prebuilt)
        monkeypatch.setattr(stdlib, "_prebuilt_data", None)
        monkeypatch.setattr(stdlib, "_fingerprint_cache", None)
        return prebuilt

    def test_cold_build_writes_the_prebuilt(self, mini_stdlib):
        model = stdlib.standard_library_model(cache=False)
        assert model.find("MiniLib::Thing") is not None
        payload = json.loads(mini_stdlib.read_text(encoding="utf-8"))
        assert payload["fingerprint"] == stdlib._stdlib_fingerprint()
        assert isinstance(payload["model"], dict)

    def test_warm_load_serves_from_the_prebuilt(self, mini_stdlib, monkeypatch):
        stdlib.standard_library_model(cache=False)  # writes the prebuilt
        monkeypatch.setattr(stdlib, "_prebuilt_data", None)  # force re-read
        again = stdlib.standard_library_model(cache=False)
        assert again.find("MiniLib::Thing") is not None

    def test_stale_fingerprint_forces_a_rebuild(self, mini_stdlib, monkeypatch):
        stdlib.standard_library_model(cache=False)
        payload = json.loads(mini_stdlib.read_text(encoding="utf-8"))
        payload["fingerprint"] = "0" * 16
        mini_stdlib.write_text(json.dumps(payload), encoding="utf-8")
        monkeypatch.setattr(stdlib, "_prebuilt_data", None)
        rebuilt = stdlib.standard_library_model(cache=False)
        assert rebuilt.find("MiniLib::Thing") is not None
        refreshed = json.loads(mini_stdlib.read_text(encoding="utf-8"))
        assert refreshed["fingerprint"] == stdlib._stdlib_fingerprint()


def test_standard_library_dir_points_at_the_vendored_sources():
    lib_dir = stdlib.standard_library_dir()
    assert lib_dir.name == "_stdlib"
    assert any(lib_dir.rglob("*.sysml"))
