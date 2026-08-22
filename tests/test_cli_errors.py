"""CLI failure modes: expected errors print one line, not a traceback (U2)."""

import pytest

from longeron.cli import main
from longeron.errors import ParseError, ResolutionError


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))


@pytest.fixture
def good(tmp_path):
    path = tmp_path / "good.sysml"
    path.write_text("package G { calc def Twice { in x : Real; return : Real = 2.0 * x; } }")
    return path


@pytest.fixture
def bad(tmp_path):
    path = tmp_path / "bad.sysml"
    path.write_text("package P {\n    part def X {\n")  # unclosed braces
    return path


class TestExpectedErrors:
    def test_missing_file(self, tmp_path, capsys):
        assert main(["lint", str(tmp_path / "nope.sysml")]) == 1
        err = capsys.readouterr().err
        assert err.startswith("error: ")
        assert "nope.sysml" in err
        assert "Traceback" not in err

    def test_syntax_error_is_one_message(self, bad, capsys):
        assert main(["parse", str(bad)]) == 1
        err = capsys.readouterr().err
        assert err.startswith("error: ")
        assert "syntax error(s)" in err
        assert "Traceback" not in err

    def test_syntax_error_at_the_load_boundary(self, bad, capsys):
        assert main(["lint", str(bad)]) == 1
        assert "syntax error(s)" in capsys.readouterr().err

    def test_unresolved_calc_name(self, good, capsys):
        assert main(["calc", str(good), "G::Nope"]) == 1
        err = capsys.readouterr().err
        assert err.startswith("error: ")
        assert "Nope" in err

    def test_malformed_json_input(self, tmp_path, capsys):
        path = tmp_path / "model.json"
        path.write_text("{not json")
        assert main(["export", str(path)]) == 1
        assert capsys.readouterr().err.startswith("error: ")

    def test_happy_path_still_works(self, good, capsys):
        assert main(["calc", str(good), "G::Twice", "x=21"]) == 0
        assert "42" in capsys.readouterr().out


class TestTracebackOptIn:
    def test_traceback_reraises(self, bad):
        with pytest.raises(ParseError):
            main(["parse", str(bad), "--traceback"])

    def test_traceback_on_model_commands(self, good):
        with pytest.raises(ResolutionError):
            main(["calc", str(good), "G::Nope", "--traceback"])


class TestParseDirectory:
    def test_reports_every_file(self, tmp_path, good, bad, capsys):
        assert main(["parse", str(tmp_path)]) == 1
        out = capsys.readouterr().out
        assert "OK: " in out and "good.sysml" in out
        assert "FAIL: " in out and "bad.sysml" in out
        assert "1 of 2 file(s) failed to parse" in out

    def test_all_good_exits_zero(self, tmp_path, good, capsys):
        assert main(["parse", str(tmp_path)]) == 0
        assert "OK: " in capsys.readouterr().out

    def test_usage_errors_still_exit_2(self):
        with pytest.raises(SystemExit) as info:
            main(["frobnicate"])
        assert info.value.code == 2
