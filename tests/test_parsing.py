"""Parsing front-end tests (SysML + KerML grammars)."""

import pytest

import sysml2


def test_parse_simple_package():
    result = sysml2.parse_sysml_text("package P;")
    assert result.language == "sysml"


def test_parse_error_reports_position():
    with pytest.raises(sysml2.ParseError) as exc:
        sysml2.parse_sysml_text("package P { part def }")
    assert exc.value.issues
    assert exc.value.issues[0].line == 1


def test_parse_error_trailing_garbage():
    with pytest.raises(sysml2.ParseError):
        sysml2.parse_sysml_text("package P; garbage garbage ((")


def test_unqualified_import_parses():
    # regression: upstream grammar required a visibility keyword before import
    sysml2.parse_sysml_text("package P { import Other::*; }")


def test_entry_then_parses():
    # regression: upstream grammar needed 'then then S;' for entry transitions
    sysml2.parse_sysml_text("state def S { entry; then off; state off; }")


def test_parse_expression():
    result = sysml2.parse_expression_text("1 + 2 * x")
    assert result.tree is not None


def test_parse_expression_rejects_garbage():
    with pytest.raises(sysml2.ParseError):
        sysml2.parse_expression_text("1 + + ;;")


def test_parse_kerml():
    result = sysml2.parse_kerml_text("""
        package Kernel {
            classifier Thing;
            class Occurrence specializes Thing;
            datatype Real;
            feature things : Thing[0..*];
        }
    """)
    assert result.language == "kerml"


def test_parse_kerml_error():
    with pytest.raises(sysml2.ParseError):
        sysml2.parse_kerml_text("classifier {{{{")


def test_kerml_model_building_not_supported():
    result = sysml2.parse_kerml_text("package K;")
    with pytest.raises(sysml2.BuildError):
        sysml2.build_model(result)


def test_parse_file(tmp_path):
    path = tmp_path / "m.sysml"
    path.write_text("package FromFile { part def X; }")
    model = sysml2.load(path)
    assert model.find("FromFile::X") is not None
