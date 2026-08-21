"""KerML projection tests: to_kerml output must parse with the KerML grammar."""

import pytest
from conftest import ACTION_MODEL, STATE_MODEL, VEHICLE_MODEL

import longeron


@pytest.mark.parametrize("source", [VEHICLE_MODEL, ACTION_MODEL, STATE_MODEL])
def test_kerml_output_parses(source):
    model = longeron.loads(source)
    kerml_text = longeron.to_kerml(model)
    result = longeron.parse_kerml_text(kerml_text)
    assert result.language == "kerml"


def test_kerml_projection_keywords():
    model = longeron.loads("""
        package P {
            part def Vehicle :> Machine { attribute mass : Real = 10.0; }
            attribute def Mass;
            calc def Twice { in x : Real; return : Real = 2.0 * x; }
            constraint def Positive;
            action def Go;
            connection def Link;
            part v : Vehicle;
        }
    """)
    text = longeron.to_kerml(model)
    assert "struct Vehicle specializes Machine" in text
    assert "feature mass : Real = 10.0;" in text
    assert "datatype Mass;" in text
    assert "function Twice" in text
    assert "in feature x : Real;" in text
    assert "predicate Positive;" in text
    assert "behavior Go;" in text
    assert "assoc struct Link;" in text
    assert "feature v : Vehicle;" in text
    longeron.parse_kerml_text(text)


def test_kerml_constraints_become_invariants():
    model = longeron.loads("""
        package P {
            part def V {
                attribute m : Real = 1.0;
                assert constraint limit { m < 10.0 }
            }
        }
    """)
    text = longeron.to_kerml(model)
    assert "inv limit { m < 10.0 }" in text
    longeron.parse_kerml_text(text)


def test_kerml_omits_behavioral_statements():
    model = longeron.loads("""
        package P {
            action def Go { in x : Real; assign x := x + 1.0; }
        }
    """)
    text = longeron.to_kerml(model)
    assert "omitted" in text
    longeron.parse_kerml_text(text)


def test_kerml_from_json_definition():
    """KerML can be generated from just the JSON definition."""

    json_text = longeron.to_json(longeron.loads(VEHICLE_MODEL))
    kerml_text = longeron.to_kerml(longeron.from_json(json_text))
    longeron.parse_kerml_text(kerml_text)
    assert "struct Vehicle" in kerml_text


def test_kerml_via_save(tmp_path):
    model = longeron.loads("package K { part def X; }")
    path = tmp_path / "out.kerml"
    longeron.save(model, path)
    assert "struct X;" in path.read_text()
    longeron.parse_kerml_text(path.read_text())
