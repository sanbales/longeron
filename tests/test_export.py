"""Export tests: JSON and textual notation, including round-trips."""

import json

import pytest

import sysml2
from sysml2 import model as M

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

    model1 = sysml2.loads(source)
    text = sysml2.to_sysml(model1)
    model2 = sysml2.loads(text, source_name="<reprint>")
    d1, d2 = sysml2.to_dict(model1), sysml2.to_dict(model2)
    d1.pop("source_name", None)
    d2.pop("source_name", None)
    assert d1 == d2, f"round-trip mismatch for:\n{text}"


def test_json_export(vehicle_model):
    data = json.loads(sysml2.to_json(vehicle_model))
    assert data["@type"] == "Model"
    pkg = data["members"][0]
    assert pkg["name"] == "Vehicles"
    vehicle = next(m for m in pkg["members"] if m.get("name") == "Vehicle")
    assert vehicle["kind"] == "part"
    mass = next(m for m in vehicle["members"] if m.get("name") == "mass")
    assert mass["value"]["expr"]["text"] == "1200.0"


def test_expression_dict():
    expr = sysml2.parse_expression("1 + 2 * x")
    data = sysml2.to_dict(expr)
    assert data["@expr"] == "Binary"
    assert data["op"] == "+"
    assert data["right"]["op"] == "*"
    assert data["text"] == "1 + 2 * x"


def test_expression_precedence_printing():
    cases = [
        "(1 + 2) * 3",
        "1 + 2 * 3",
        "2 ** 3 ** 4",       # left-assoc in this grammar
        "not (a and b)",
        "a and not b",
        "-x ** 2",
        "(if c ? 1 else 2) + 5",
        "x->select { in v; v > 2 }->size()",
        "items#(2)",
        "a.b.c + 1",
    ]
    for text in cases:
        expr = sysml2.parse_expression(text)
        printed = sysml2.ast.expr_to_text(expr)
        reparsed = sysml2.parse_expression(printed)
        assert sysml2.to_dict(expr) == sysml2.to_dict(reparsed), (
            f"{text!r} printed as {printed!r} which parses differently")


def test_quoted_name_export():
    model = sysml2.loads("package 'Nice Name' { part def 'part one'; }")
    text = sysml2.to_sysml(model)
    assert "'Nice Name'" in text
    assert "'part one'" in text


def test_reserved_word_names_quoted():
    pkg = M.Package(name="state")  # reserved word as a name
    model = M.Model()
    model.add(pkg)
    text = sysml2.to_sysml(model)
    assert "'state'" in text
    sysml2.loads(text)


def test_unsupported_round_trip():
    src = """
package P {
    interface def I { end a : PA; end b : PB; }
    view def V;
}
"""
    model = sysml2.loads(src)
    text = sysml2.to_sysml(model)
    model2 = sysml2.loads(text)
    assert sysml2.to_dict(model.members[0]) == sysml2.to_dict(model2.members[0])
