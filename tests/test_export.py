"""Export tests: JSON and textual notation, including round-trips."""

import json

import pytest

import longeron
from longeron import model as M

ROUND_TRIP_SOURCES = [
    "package Empty;",
    """
    package P {
        doc /* documentation text */
        private import Lib::*;
        part def A { attribute x : Real = 1.0; }
        part def B :> A {
            attribute x : Real :>> A::x = 2.0;
            part nested : A[2..4] ordered;
        }
    }
    """,
    """
    package Calc {
        calc def F {
            in a : Real;
            in b : Real = 1.0;
            attribute scale : Real = 2.0;
            return : Real = (a + b) * scale;
        }
        constraint def Positive { in v : Real; v > 0.0 }
    }
    """,
    """
    package Act {
        action def Go {
            in n : Integer;
            out r : Integer;
            assign r := 0;
            for i in 1..n {
                assign r := r + i;
            }
            while r > 100.0 {
                assign r := r - 1;
            }
            if r == 0 {
                assign r := -1;
            } else {
                assign r := r * 2;
            }
            send r via channel;
            accept go : GoSignal;
            terminate;
        }
    }
    """,
    """
    package Sm {
        state def M {
            entry; then a;
            state a {
                entry assign counter := counter + 1;
                do log;
                exit reset;
            }
            transition first a accept sig : Signal if counter < 5 then b;
            state b;
            transition t2 first b accept stop then a;
        }
    }
    """,
    """
    package Req {
        requirement def R {
            subject s : Thing;
            assume constraint { s.mass > 0.0 }
            require constraint limit { s.mass <= 100.0 }
            actor operator : Person;
        }
        enum def Level { low; high; }
    }
    """,
    """
    package Misc {
        part def 'Quoted Name' {
            attribute 'my attr' : Real = if true ? 1.0 else 2.0;
        }
        part sys {
            part a;
            part b;
            connect a to b;
            bind a = b;
            first a then b;
        }
        dependency Client from a to b;
    }
    """,
]


@pytest.mark.parametrize("source", ROUND_TRIP_SOURCES)
def test_round_trip(source):
    """parse -> print -> parse again must preserve the model structure."""

    model1 = longeron.loads(source)
    text = longeron.to_sysml(model1)
    model2 = longeron.loads(text, source_name="<reprint>")
    d1, d2 = longeron.to_dict(model1), longeron.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2, f"round-trip mismatch for:\n{text}"


def test_json_export(vehicle_model):
    data = json.loads(longeron.to_json(vehicle_model))
    assert data["@type"] == "Model"
    pkg = data["members"][0]
    assert pkg["name"] == "Vehicles"
    vehicle = next(m for m in pkg["members"] if m.get("name") == "Vehicle")
    assert vehicle["kind"] == "part"
    mass = next(m for m in vehicle["members"] if m.get("name") == "mass")
    assert mass["value"]["expr"]["text"] == "1200.0"


def test_expression_dict():
    expr = longeron.parse_expression("1 + 2 * x")
    data = longeron.to_dict(expr)
    assert data["@expr"] == "Binary"
    assert data["op"] == "+"
    assert data["right"]["op"] == "*"
    assert data["text"] == "1 + 2 * x"


def test_expression_precedence_printing():
    cases = [
        "(1 + 2) * 3",
        "1 + 2 * 3",
        "2 ** 3 ** 4",  # left-assoc in this grammar
        "not (a and b)",
        "a and not b",
        "-x ** 2",
        "(if c ? 1 else 2) + 5",
        "x->select { in v; v > 2 }->size()",
        "items#(2)",
        "a.b.c + 1",
    ]
    for text in cases:
        expr = longeron.parse_expression(text)
        printed = longeron.ast.expr_to_text(expr)
        reparsed = longeron.parse_expression(printed)
        assert longeron.to_dict(expr) == longeron.to_dict(reparsed), (
            f"{text!r} printed as {printed!r} which parses differently"
        )


def test_quoted_name_export():
    model = longeron.loads("package 'Nice Name' { part def 'part one'; }")
    text = longeron.to_sysml(model)
    assert "'Nice Name'" in text
    assert "'part one'" in text


def test_reserved_word_names_quoted():
    pkg = M.Package(name="state")  # reserved word as a name
    model = M.Model()
    model.add(pkg)
    text = longeron.to_sysml(model)
    assert "'state'" in text
    longeron.loads(text)


def test_unsupported_round_trip():
    src = """
package P {
    interface def I { end a : PA; end b : PB; }
    view def V;
}
"""
    model = longeron.loads(src)
    text = longeron.to_sysml(model)
    model2 = longeron.loads(text)
    assert longeron.to_dict(model.members[0]) == longeron.to_dict(model2.members[0])


# ---------------------------------------------------------------------------
# workspace (directory) save-back
# ---------------------------------------------------------------------------

PARTS_SOURCE = """\
// hand-written header comment (only rewritten files lose comments)
package Parts {
    part def Motor {
        attribute mass : Real = 0.05;
    }
}
"""

VEHICLE_SOURCE = """\
package Vehicle {
    private import Parts::*;
    part motor : Motor;
}
"""


@pytest.fixture()
def program_dir(tmp_path):
    (tmp_path / "parts.sysml").write_text(PARTS_SOURCE, encoding="utf-8")
    (tmp_path / "vehicle.sysml").write_text(VEHICLE_SOURCE, encoding="utf-8")
    return tmp_path


class TestWorkspaceSave:
    def test_round_trips_through_the_source_files(self, program_dir):
        from longeron import edit, export, workspace

        model = workspace.load_dir(program_dir, cache=False)
        tracker = edit.track(model)
        edit.rename(model, "Parts::Motor", "Rotor")  # cascades into vehicle.sysml
        edit.set_attribute_value(model, "Parts::Rotor::mass", "0.075", validate=False)
        written = export.save_workspace(model, tracker.changes)
        assert sorted(path.name for path in written) == ["parts.sysml", "vehicle.sysml"]
        # the edits landed in THEIR files...
        assert "0.075" in (program_dir / "parts.sysml").read_text(encoding="utf-8")
        assert "motor : Rotor" in (program_dir / "vehicle.sysml").read_text(encoding="utf-8")
        # ...and reloading the directory reproduces the edited model
        reloaded = workspace.load_dir(program_dir, cache=False)
        assert longeron.to_dict(reloaded) == longeron.to_dict(model)

    def test_only_changed_files_are_rewritten(self, program_dir):
        import os

        from longeron import edit, export, workspace

        model = workspace.load_dir(program_dir, cache=False)
        tracker = edit.track(model)
        untouched = program_dir / "vehicle.sysml"
        before = untouched.read_text(encoding="utf-8")
        os.utime(untouched, (1_000_000_000, 1_000_000_000))  # unambiguous mtime
        edit.set_attribute_value(model, "Parts::Motor::mass", "0.075", validate=False)
        written = export.save_workspace(model, tracker.changes)
        assert [path.name for path in written] == ["parts.sysml"]
        assert untouched.read_text(encoding="utf-8") == before
        assert untouched.stat().st_mtime == 1_000_000_000

    def test_plan_drops_files_already_matching_disk(self, program_dir):
        from longeron import edit, export, workspace

        model = workspace.load_dir(program_dir, cache=False)
        tracker = edit.track(model)
        edit.set_attribute_value(model, "Parts::Motor::mass", "0.075", validate=False)
        export.save_workspace(model, tracker.changes)  # canonicalizes parts.sysml
        # an edit REVERTED before saving: dirty, mappable, nothing to write
        edit.set_attribute_value(model, "Parts::Motor::mass", "0.05", validate=False)
        edit.set_attribute_value(model, "Parts::Motor::mass", "0.075", validate=False)
        tracker.mark_saved()
        edit.set_attribute_value(model, "Parts::Motor::mass", "0.08", validate=False)
        edit.set_attribute_value(model, "Parts::Motor::mass", "0.075", validate=False)
        assert export.workspace_plan(model, tracker.changes) == {}

    def test_member_without_provenance_refuses(self, program_dir):
        from longeron import edit, export, workspace
        from longeron.errors import SysMLError

        model = workspace.load_dir(program_dir, cache=False)
        tracker = edit.track(model)
        edit.set_attribute_value(model, "Parts::Motor::mass", "0.075", validate=False)
        model.add(M.Package(name="Ghost"))  # added after the load: no file
        with pytest.raises(SysMLError, match="Ghost carries no source-file record"):
            export.workspace_plan(model, tracker.changes)
        # a refusal writes NOTHING
        assert "0.075" not in (program_dir / "parts.sysml").read_text(encoding="utf-8")

    def test_unmappable_change_refuses(self, program_dir):
        from longeron import export, workspace
        from longeron.errors import SysMLError

        model = workspace.load_dir(program_dir, cache=False)
        # a change with no usable 'tops' breadcrumb (e.g. recorded by a
        # foreign tool) must refuse, never guess which file to rewrite
        bogus = [("set_value", "Parts::Motor::mass", {"text": "1.0"})]
        with pytest.raises(SysMLError, match="cannot map the tracked edit"):
            export.workspace_plan(model, bogus)

    def test_rename_of_a_top_package_maps_to_its_file(self, program_dir):
        from longeron import edit, export, workspace

        model = workspace.load_dir(program_dir, cache=False)
        tracker = edit.track(model)
        edit.rename(model, "Parts", "Catalog")  # rewrites vehicle's import too
        written = export.save_workspace(model, tracker.changes)
        assert sorted(path.name for path in written) == ["parts.sysml", "vehicle.sysml"]
        assert "package Catalog" in (program_dir / "parts.sysml").read_text(encoding="utf-8")
        reloaded = workspace.load_dir(program_dir, cache=False)
        assert longeron.to_dict(reloaded) == longeron.to_dict(model)
