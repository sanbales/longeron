"""JSON import (from_dict / from_json) and the full read-run-save loop."""

import pytest
from conftest import ACTION_MODEL, STATE_MODEL, VEHICLE_MODEL

import longeron
from longeron import model as M


def _normalized(model):
    data = longeron.to_dict(model)
    data.pop("source_name", None)
    return data


@pytest.mark.parametrize("source", [VEHICLE_MODEL, ACTION_MODEL, STATE_MODEL])
def test_json_round_trip(source):
    model = longeron.loads(source)
    clone = longeron.from_json(longeron.to_json(model))
    assert _normalized(clone) == _normalized(model)


@pytest.mark.parametrize("source", [VEHICLE_MODEL, ACTION_MODEL, STATE_MODEL])
def test_json_to_sysml_text(source):
    """SysML text can be generated from just the JSON definition."""

    json_text = longeron.to_json(longeron.loads(source))
    regenerated = longeron.to_sysml(longeron.from_json(json_text))
    reparsed = longeron.loads(regenerated)
    assert _normalized(reparsed) == _normalized(longeron.loads(source))


def test_json_import_is_executable():
    model = longeron.from_json(longeron.to_json(longeron.loads(VEHICLE_MODEL)))
    interp = longeron.Interpreter(model)
    assert interp.call("Vehicles::TotalMass", 1000.0, 200.0) == 1200.0
    car = interp.instantiate("Vehicles::Vehicle")
    assert car.slots["mass"] == 1200.0
    assert interp.check(car)[0].passed is True


def test_json_import_state_machine():
    model = longeron.from_json(longeron.to_json(longeron.loads(STATE_MODEL)))
    interp = longeron.Interpreter(model)
    result = interp.simulate("Machines::TrafficLight", events=["go"])
    assert result.final_state == "green"


def test_from_dict_single_element():
    part = M.Definition(kind="part", name="Widget")
    part.add(
        M.Usage(
            kind="attribute", name="w", value=M.FeatureValue(longeron.parse_expression("3 + 4"))
        )
    )
    rebuilt = longeron.from_dict(longeron.to_dict(part))
    assert isinstance(rebuilt, M.Definition)
    assert rebuilt.members[0].value.expr.to_text() == "3 + 4"
    assert rebuilt.members[0].owner is rebuilt


def test_from_json_wraps_non_model_root():
    pkg = M.Package(name="Solo")
    model = longeron.from_json(longeron.to_json(pkg))
    assert isinstance(model, M.Model)
    assert model.find("Solo") is not None


def test_from_dict_rejects_garbage():
    with pytest.raises(longeron.BuildError):
        longeron.from_dict({"name": "x"})
    with pytest.raises(longeron.BuildError):
        longeron.from_dict({"@type": "NoSuchElement"})


def test_expression_dict_round_trip():
    cases = [
        "1 + 2 * x",
        "if a ? 1 else 2",
        "(1, 2, 3)->select { in v; v > 1 }->size()",
        "x.y.z + P::c",
        "engine.power [SI::W]",
        "Calc(a = 1, b = 2)",
        "items#(2)",
        "-x ** 2",
        "1..10",
        "*",  # infinity literal
        '"*"',  # a string that looks like infinity
        "null ?? 5",
        "v istype Real and v as Integer > 0",
    ]
    from longeron.ast import expr_from_dict, expr_to_dict

    for text in cases:
        expr = longeron.parse_expression(text)
        rebuilt = expr_from_dict(expr_to_dict(expr))
        assert rebuilt == expr, f"expression {text!r} did not round-trip"


def test_save_and_load(tmp_path):
    model = longeron.loads(VEHICLE_MODEL)
    for suffix in (".sysml", ".json"):
        path = tmp_path / f"m{suffix}"
        longeron.save(model, path)
        reloaded = longeron.load(path)
        assert _normalized(reloaded) == _normalized(model)


def test_full_loop(tmp_path):
    """Read a model, run it, write results back, save, reload, re-check."""

    model = longeron.loads(VEHICLE_MODEL)
    interp = longeron.Interpreter(model)

    # run: instantiate with overrides and evaluate a calc
    car = interp.instantiate("Vehicles::Vehicle", mass=1400.0)
    total = interp.call("Vehicles::TotalMass", vehicleMass=car.slots["mass"], cargoMass=150.0)

    # write results back into the model as a snapshot part
    snapshot = interp.snapshot(car, name="measuredCar")
    snapshot.add(
        M.Usage(
            kind="attribute",
            name="totalWithCargo",
            value=M.FeatureValue(longeron.ast.Literal(total)),
        )
    )
    model.find("Vehicles").add(snapshot)

    # save and reload in both formats
    longeron.save(model, tmp_path / "loop.sysml")
    longeron.save(model, tmp_path / "loop.json")
    for name in ("loop.sysml", "loop.json"):
        reloaded = longeron.load(tmp_path / name)
        interp2 = longeron.Interpreter(reloaded)
        snap = reloaded.find("Vehicles::measuredCar")
        assert snap.types == ["Vehicles::Vehicle"]
        values = interp2.instantiate(snap)
        assert values.slots["mass"] == 1400.0
        assert values.slots["totalWithCargo"] == 1550.0
        assert values.slots["wheels_1"].slots["diameter"] == 0.66


def test_snapshot_kinds(vehicle_interp):
    car = vehicle_interp.instantiate("Vehicles::Vehicle")
    snap = vehicle_interp.snapshot(car, name="snap")
    kinds = {m.name: m.kind for m in snap.members}
    assert kinds["mass"] == "attribute"
    assert kinds["engine"] == "part"
    assert kinds["wheels_1"] == "part"
    text = longeron.to_sysml(snap)
    assert "part snap : Vehicles::Vehicle" in text
