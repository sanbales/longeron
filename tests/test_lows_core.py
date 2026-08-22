"""Regression tests for the 0.6.x adversarial-review fixes (P6, L5-L8, E4, E5)."""

from __future__ import annotations

import pytest

import longeron
from longeron import model as M
from longeron.errors import EvaluationError
from longeron.interpreter import Instance, Interpreter, _Edge, _SuccessionPlan
from longeron.workspace import merge_models

# -- P6: succession-graph edges are indexed by source ------------------------


def test_succession_plan_indexes_edges_by_source():
    edges = [
        _Edge("start", "a", None, False),
        _Edge("a", "b", None, False),
        _Edge("a", "done", None, True),
    ]
    plan = _SuccessionPlan(steps={}, step_ids=set(), edges=edges, initial="a")
    assert plan.edges_from("a") == [edges[1], edges[2]]
    assert plan.edges_from("start") == [edges[0]]
    assert plan.edges_from("nope") == []


def test_succession_graph_still_executes():
    model = longeron.loads(
        """
        package P {
            action def Seq {
                out x : Real;
                action s1 assign x := 1.0;
                action s2 assign x := x + 10.0;
                first start then s1;
                first s1 then s2;
                first s2 then done;
            }
        }
        """
    )
    result = Interpreter(model).run_action("P::Seq")
    assert result.outputs["x"] == 11.0


# -- L6: bindings dict alongside **kwargs sugar -------------------------------


def test_evaluate_accepts_bindings_dict():
    interp = Interpreter(longeron.loads("package P;"))
    assert interp.evaluate("a + b", bindings={"a": 1, "b": 2}) == 3
    # names colliding with reserved parameters are passable via the dict
    assert interp.evaluate("context * 2", bindings={"context": 21}) == 42
    # keyword sugar still works, and wins on overlap
    assert interp.evaluate("a + b", bindings={"a": 1, "b": 0}, b=2) == 3


def test_instantiate_and_check_requirement_accept_bindings_dict():
    model = longeron.loads(
        """
        package P {
            part def V { attribute mass : Real = 1.0; }
            requirement def R {
                attribute limit : Real;
                require constraint c { limit > 0.0 }
            }
        }
        """
    )
    interp = Interpreter(model)
    instance = interp.instantiate("P::V", bindings={"mass": 7.0})
    assert instance.get("mass") == 7.0
    assert interp.instantiate("P::V", mass=9.0).get("mass") == 9.0
    result = interp.check_requirement("P::R", bindings={"limit": 5.0})
    assert result.satisfied is True


# -- E4: Instance.set matches Env.assign's error contract ----------------------


def test_instance_set_raises_evaluation_error_consistently():
    outer = Instance("Outer")
    inner = Instance("Inner")
    outer.slots["inner"] = inner
    outer.slots["mass"] = 1.0

    outer.set("inner.x", 5)  # final slot creation, like Env.assign simple names
    assert inner.slots["x"] == 5

    with pytest.raises(EvaluationError):  # unknown intermediate slot
        outer.set("nope.x", 1)
    with pytest.raises(EvaluationError):  # non-instance mid-path
        outer.set("mass.x.y", 1)
    with pytest.raises(EvaluationError):  # non-instance final container
        outer.set("mass.x", 1)
    assert outer.slots["mass"] == 1.0  # nothing mutated on failure


# -- L8: merge_models no longer mutates its inputs ----------------------------


def test_merge_models_leaves_inputs_untouched():
    a = longeron.loads("package A { part def X; }")
    b = longeron.loads("package B { part def Y; }")
    a_pkg = a.members[0]
    merged = merge_models([a, b])
    assert a_pkg.owner is a  # input ownership intact
    assert a.members[0] is a_pkg
    assert merged.find("A::X") is not None and merged.find("B::Y") is not None
    # and the merge is independent: mutations do not alias the sources
    merged.find("A").add(M.Definition(kind="part", name="Z"))
    assert a.find("A::Z") is None


# -- L5/E5: exporter parameter + dispatch conventions --------------------------


def test_indent_accepts_int_and_str():
    model = longeron.loads("package P { part def X { attribute a : Real; } }")
    two = longeron.to_sysml(model, indent=2)
    assert "\n  part def X {" in two
    assert longeron.to_sysml(model, indent="  ") == two
    kerml_two = longeron.kerml.to_kerml(model, indent=2)
    assert kerml_two == longeron.kerml.to_kerml(model, indent="  ")


def test_save_fmt_keyword(tmp_path):
    model = longeron.loads("package P { part def X; }")
    target = tmp_path / "out.txt"
    longeron.save(model, target, fmt="json")
    assert target.read_text(encoding="utf-8").lstrip().startswith("{")
    with pytest.raises(ValueError):
        longeron.save(model, target, fmt="nope")


def test_kerml_printer_dispatch_matches_isinstance_semantics():
    # subclasses ride their base handler (EnumerationDefinition -> Definition,
    # ConnectionUsage -> Usage); unknown elements still degrade to a comment
    model = longeron.loads(
        """
        package P {
            enum def Color { red; green; }
            part def A; part def B;
            connection def C;
            part a : A; part b : B;
            connection c : C connect a to b;
        }
        """
    )
    text = longeron.kerml.to_kerml(model)
    assert "datatype Color" in text
    assert "omitted" in text  # the connection usage has no kernel projection


# -- L7: API JSON import surface ----------------------------------------------


def test_api_json_import_names():
    api = pytest.importorskip("longeron.api")
    model = longeron.loads("package P { part def X; part x : X; }")
    text = api.to_api_json(model)
    # the model-layer inverse of to_api_json
    clone = api.model_from_api_json(text)
    assert isinstance(clone, M.Model)
    assert clone.find("P::X") is not None
    # the spec-level import, under its explicit name and the legacy aliases
    spec = api.spec_from_api_json(text)
    assert type(spec).__name__ == "SpecModel"
    assert api.from_api_json is api.spec_from_api_json
    assert api.from_api_records is api.spec_from_api_records
