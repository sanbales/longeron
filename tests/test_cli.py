"""CLI subcommands through ``main()``: check, run, simulate, export, parse,
serve wiring, and value parsing.  Failure modes live in test_cli_errors.py.
"""

import json

import pytest
from conftest import ACTION_MODEL, STATE_MODEL, VEHICLE_MODEL

from longeron.cli import main


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path_factory, monkeypatch):
    monkeypatch.setenv("LONGERON_CACHE_DIR", str(tmp_path_factory.mktemp("cache")))


@pytest.fixture
def vehicle_file(tmp_path):
    path = tmp_path / "vehicle.sysml"
    path.write_text(VEHICLE_MODEL)
    return path


@pytest.fixture
def action_file(tmp_path):
    path = tmp_path / "actions.sysml"
    path.write_text(ACTION_MODEL)
    return path


@pytest.fixture
def state_file(tmp_path):
    path = tmp_path / "machines.sysml"
    path.write_text(STATE_MODEL)
    return path


class TestCheck:
    def test_pass_prints_instance_and_verdicts(self, vehicle_file, capsys):
        assert main(["check", str(vehicle_file), "Vehicles::Vehicle"]) == 0
        out = capsys.readouterr().out
        assert "[PASS] assert massLimit: mass <= maxMass" in out
        instance = json.loads(out[: out.index("[PASS]")])
        assert instance["@type"] == "Vehicles::Vehicle"
        assert instance["mass"] == 1200.0

    def test_fail_exits_one(self, vehicle_file, capsys):
        assert main(["check", str(vehicle_file), "Vehicles::Vehicle", "mass=99999"]) == 1
        assert "[FAIL] assert massLimit" in capsys.readouterr().out

    def test_unevaluable_constraint_is_skip_not_fail(self, tmp_path, capsys):
        path = tmp_path / "broken.sysml"
        path.write_text(
            "package Broken { part def Box {"
            " attribute mass : Real = 1.0;"
            " constraint c { mass < noSuchLimit } } }"
        )
        assert main(["check", str(path), "Broken::Box"]) == 0
        assert "[SKIP] constraint c" in capsys.readouterr().out


class TestRun:
    def test_outputs_and_trace(self, action_file, capsys):
        assert main(["run", str(action_file), "Behaviors::ComputeFuel", "distance=100"]) == 0
        out = capsys.readouterr().out
        assert '"fuelUsed": 8.0' in out
        assert "assign fuelUsed" in out  # the trace is printed

    def test_events_and_sends(self, action_file, capsys):
        assert (
            main(["run", str(action_file), "Behaviors::Radio", "code=21", "--events", "Ping"]) == 0
        )
        out = capsys.readouterr().out
        assert "sends: ['42']" in out

    def test_non_jsonable_output_falls_back_to_repr(self, tmp_path, capsys):
        path = tmp_path / "enumout.sysml"
        path.write_text(
            "package E { enum def Color { red; green; }"
            " action def Pick { out c : Color; assign c := Color::red; } }"
        )
        assert main(["run", str(path), "E::Pick"]) == 0
        out = capsys.readouterr().out
        assert "red" in out  # EnumValue rendered via repr, not a TypeError


class TestSimulate:
    def test_trace_and_final_state(self, state_file, capsys):
        rc = main(
            [
                "simulate",
                str(state_file),
                "Machines::TrafficLight",
                "--events",
                "go,caution,stop",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "final state: red" in out
        assert "--go--> green" in out

    def test_ignored_events_reported(self, state_file, capsys):
        rc = main(["simulate", str(state_file), "Machines::TrafficLight", "--events", "bogus"])
        assert rc == 0  # ignored events are reported, not fatal
        out = capsys.readouterr().out
        assert "ignored events: ['bogus']" in out


class TestExport:
    def test_sysml_round_trips_to_stdout(self, vehicle_file, capsys):
        assert main(["export", str(vehicle_file), "--format", "sysml"]) == 0
        assert "part def Vehicle :> Machine" in capsys.readouterr().out

    def test_kerml_projection(self, vehicle_file, capsys):
        assert main(["export", str(vehicle_file), "--format", "kerml"]) == 0
        assert "struct Vehicle specializes Machine" in capsys.readouterr().out

    def test_json_to_output_file(self, vehicle_file, tmp_path, capsys):
        target = tmp_path / "model.json"
        assert main(["export", str(vehicle_file), "-o", str(target)]) == 0
        assert capsys.readouterr().out == ""  # -o writes the file, not stdout
        data = json.loads(target.read_text(encoding="utf-8"))
        assert any(e.get("name") == "Vehicles" for e in data["members"])

    def test_api_format(self, vehicle_file, capsys):
        pytest.importorskip("pyecore")
        assert main(["export", str(vehicle_file), "--format", "api"]) == 0
        records = json.loads(capsys.readouterr().out)
        assert any(r.get("declaredName") == "Vehicle" for r in records)


class TestParse:
    def test_single_file_ok_line(self, vehicle_file, capsys):
        assert main(["parse", str(vehicle_file)]) == 0
        assert "parses as sysml" in capsys.readouterr().out

    def test_tree_output(self, vehicle_file, capsys):
        assert main(["parse", str(vehicle_file), "--tree"]) == 0
        assert "rootNamespace" in capsys.readouterr().out

    def test_empty_directory_exits_one(self, tmp_path, capsys):
        (tmp_path / "empty").mkdir()
        assert main(["parse", str(tmp_path / "empty")]) == 1
        assert "no *.sysml files under" in capsys.readouterr().out

    def test_kerml_flag_forces_grammar(self, tmp_path, capsys):
        path = tmp_path / "kernel.kerml"
        path.write_text("package K { classifier Thing; }")
        assert main(["parse", str(path), "--kerml"]) == 0
        assert "parses as kerml" in capsys.readouterr().out


class TestServe:
    def test_wiring_passes_path_host_and_port(self, tmp_path, monkeypatch):
        pytest.importorskip("fastapi")
        import longeron.server as server_module

        calls = {}

        def fake_serve(path, host, port):
            calls["args"] = (path, host, port)

        monkeypatch.setattr(server_module, "serve", fake_serve)
        assert main(["serve", str(tmp_path), "--host", "0.0.0.0", "--port", "9123"]) == 0
        assert calls["args"] == (str(tmp_path), "0.0.0.0", 9123)


class TestValueParsing:
    def test_non_json_argument_stays_a_string(self, tmp_path, capsys):
        path = tmp_path / "echo.sysml"
        path.write_text('package G { calc def Echo { in s : String; return : String = s + "!"; } }')
        assert main(["calc", str(path), "G::Echo", "s=hello"]) == 0
        assert "hello!" in capsys.readouterr().out

    def test_missing_equals_is_a_usage_error(self, vehicle_file):
        with pytest.raises(SystemExit):
            main(["calc", str(vehicle_file), "Vehicles::TotalMass", "oops"])
