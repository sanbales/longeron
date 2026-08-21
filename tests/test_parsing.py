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


def test_target_transition_then_clause_parses():
    # regression: upstream grammar put ActionBody before the 'then' clause in
    # targetTransitionUsage, rejecting state-body transitions (grammar patch 6)
    sysml2.parse_sysml_text("state def S { state a; accept s : Sig do action D then b; state b; }")
    sysml2.parse_sysml_text("state def S { entry; then on; state on; then off; state off; }")


def test_library_package_without_standard_parses():
    # regression: upstream grammar required the full 'standard library package'
    # (grammar patch 7)
    sysml2.parse_sysml_text("library package AHFCoreLib { part def X; }")
    sysml2.parse_sysml_text("standard library package SL { part def X; }")


def test_named_send_action_parses():
    # regression: the pilot corpus writes 'action <name> send ...', which the
    # spec BNF omits; we follow the corpus (grammar patch 8)
    sysml2.parse_sysml_text(
        "package P { action def A { action publish send new Publish(t, p) via publicationPort; } }"
    )


def test_metadata_prefixed_enum_value_parses():
    # regression: the pilot corpus writes '#Security enum secret : ...' inside
    # enum bodies, which the release BNF omits (grammar patch 10)
    sysml2.parse_sysml_text("package P { enum def L { a : L = 0; #Security enum b : L = 1; } }")


def test_one_line_multiline_note_parses():
    # regression: SINGLE_LINE_NOTE out-competed MULTILINE_NOTE when the note
    # closed on the same line, swallowing the trailing text (grammar patch 9)
    sysml2.parse_sysml_text("package P { attribute h : Real = ( //* elided */ 4 ); }")
    sysml2.parse_sysml_text("package P; // plain single-line note")
    sysml2.parse_sysml_text("package P; //")
    sysml2.parse_kerml_text("package K { //* elided */ class C; }")


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
