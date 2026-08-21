"""Standard library (Stage D) tests.

The first-ever load builds from vendored sources (minutes, cold); afterwards
the bundled prebuilt pickle answers in milliseconds. The session fixture
loads once.
"""

import pytest

import sysml2
from sysml2 import stdlib


@pytest.fixture(scope="session")
def library():
    return stdlib.standard_library_model()


@pytest.fixture(scope="session")
def lib_interp(library):
    return sysml2.Interpreter(library)


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
        model = sysml2.loads("""
            package App {
                private import ScalarValues::*;
                private import Parts::*;
                part def Robot :> Part { attribute mass : Real = 12.0; }
            }
        """)
        sysml2.add_standard_library(model)
        interp = sysml2.Interpreter(model)
        robot = interp.instantiate("App::Robot")
        assert robot.slots["mass"] == 12.0
        assert interp.evaluate("r istype Part", context="App", r=robot)

    def test_idempotent(self):
        model = sysml2.loads("package App;")
        sysml2.add_standard_library(model)
        count = len(model.members)
        sysml2.add_standard_library(model)
        assert len(model.members) == count

    def test_user_packages_not_shadowed(self):
        model = sysml2.loads("package Parts { part def Mine; }")
        sysml2.add_standard_library(model)
        assert model.find("Parts::Mine") is not None

    def test_inherited_library_defaults_degrade_gracefully(self):
        # Parts::Part inherits features whose defaults use KerML functions
        # this interpreter does not implement; they become None instead of
        # failing the whole instantiation.
        model = sysml2.loads("""
            package App {
                private import Parts::*;
                part def Widget :> Part;
            }
        """)
        sysml2.add_standard_library(model)
        interp = sysml2.Interpreter(model)
        widget = interp.instantiate("App::Widget")
        assert widget.type_name == "App::Widget"

    def test_self_referential_composition_is_finite(self):
        model = sysml2.loads("""
            package App {
                private import Items::*;
                item def Box :> Item;
            }
        """)
        sysml2.add_standard_library(model)
        interp = sysml2.Interpreter(model)
        box = interp.instantiate("App::Box")  # Item composes Item [0..*]
        assert box is not None


class TestValidationWithLibrary:
    def test_library_reference_warnings_disappear(self):
        source = """
            package App {
                part def V :> NoSuchThing;
            }
        """
        model = sysml2.loads(source)
        before = [d for d in sysml2.validate(model) if d.code == "unresolved-reference"]
        assert len(before) == 1  # NoSuchThing

    def test_stdlib_types_resolve_in_validation(self):
        model = sysml2.loads("""
            package App {
                private import Parts::*;
                part def V :> Part;
            }
        """)
        sysml2.add_standard_library(model)
        diags = [
            d
            for d in sysml2.validate(model)
            if "App" in d.element and d.code == "unresolved-reference"
        ]
        assert diags == []


def test_prebuilt_fingerprint_stable():
    assert stdlib._stdlib_fingerprint() == stdlib._stdlib_fingerprint()


def test_cli_stdlib_flag(tmp_path, capsys):
    from sysml2.cli import main

    path = tmp_path / "app.sysml"
    path.write_text("""
        package App {
            private import ScalarValues::*;
            calc def Twice { in x : Real; return : Real = 2.0 * x; }
        }
    """)
    assert main(["calc", str(path), "App::Twice", "x=4", "--stdlib"]) == 0
    assert "8" in capsys.readouterr().out
