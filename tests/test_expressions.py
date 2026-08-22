"""Expression evaluation tests."""

import math

import pytest

import longeron
from longeron.errors import EvaluationError


@pytest.fixture(scope="module")
def interp():
    return longeron.Interpreter(
        longeron.loads("""
        package Lib {
            attribute gravity : Real = 9.81;
            enum def Color { red; green; blue; }
            calc def Twice { in x : Real; return : Real = 2.0 * x; }
        }
    """)
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1 + 2 * 3", 7),
        ("(1 + 2) * 3", 9),
        ("2 ** 3", 8),
        ("2 ^ 3", 8),
        ("7 % 3", 1),
        ("10 / 4", 2.5),
        ("-3 + 1", -2),
        ("1 < 2", True),
        ("2 <= 1", False),
        # boundary vectors: equal operands discriminate <= from < and >= from >
        ("1 <= 1", True),
        ("1 >= 1", True),
        ("1 < 1", False),
        ("1 > 1", False),
        ("2 >= 1", True),
        ("1 == 1.0", True),
        ("1 != 2", True),
        ("true and false", False),
        ("false and true", False),
        ("false and false", False),
        ("true and true", True),
        ("true or false", True),
        ("false or false", False),
        ("false or true", True),
        ("false implies false", True),
        ("true implies false", False),
        ("true implies true", True),
        ("true xor true", False),
        ("true xor false", True),
        ("false xor true", True),
        ("false xor false", False),
        ("not false", True),
        ("null === null", True),
        ("null !== null", False),
        ("1 !== 2", True),
        ("false | true", True),  # eager or: no short-circuit
        ("true & false", False),  # eager and
        ("2 as String", "2"),
        ("null ?? 5", 5),
        ("3 ?? 5", 3),
        ("if 1 < 2 ? 10 else 20", 10),
        ('"abc" + "def"', "abcdef"),
        ("1..4", [1, 2, 3, 4]),
        ("(1, 2, 3)", [1, 2, 3]),
        ("(1, (2, 3))", [1, 2, 3]),  # sequences flatten
        ("(5,)", [5]),
        ("(1, 2, 3)#(2)", 2),
        ("(1, 2, 3)->size()", 3),
        ("()->isEmpty()", True),
        ("(1, 2, 3)->includes(2)", True),
        ("(1, 2, 3)->excludes(9)", True),
        ("(1, 2, 3)->head()", 1),
        ("(1, 2, 3)->last()", 3),
        ("(1, 2, 3)->collect { in x; x * 10 }", [10, 20, 30]),
        ("(1, 2, 3, 4)->select { in x; x % 2 == 0 }", [2, 4]),
        ("(1, 2, 3, 4)->reject { in x; x % 2 == 0 }", [1, 3]),
        ("(1, 2, 3)->forAll { in x; x > 0 }", True),
        ("(1, 2, 3)->exists { in x; x > 2 }", True),
        ("(1, 2, 3, 4)->reduce { in a; in b; a + b }", 10),
        ("(1, 2, 3).{ in x; x + 1 }", [2, 3, 4]),
        ("(1, 2, 3).?{ in x; x >= 2 }", [2, 3]),
        ("sqrt(16.0)", 4.0),
        ("abs(-3)", 3),
        ("max(1, 5, 2)", 5),
        ("min((4, 2, 8))", 2),
        ("sum(1..10)", 55),
        ("floor(2.9)", 2),
        ("10 [si]", 10),  # measurement references evaluate to the magnitude
        ("2 istype Integer", True),
        ("2.5 istype Integer", False),
        ("2.5 istype Real", True),
        ('"x" istype String', True),
        ("true istype Boolean", True),
        ("2.9 as Integer", 2),
        ("3 as Real", 3.0),
        ("{ in x; x * x }", None),  # closures evaluate to a callable value
    ],
)
def test_expression(interp, text, expected):
    value = interp.evaluate(text)
    if text.startswith("{"):
        assert value is not None
        return
    assert value == expected
    if isinstance(expected, float):
        assert math.isclose(value, expected)


def test_bindings(interp):
    assert interp.evaluate("x * y + 1", x=3, y=4) == 13


def test_and_short_circuits_on_falsy_left(interp):
    # the right operand divides by zero: it must never be evaluated when the
    # left is false ('and' is conditional; the eager form is '&')
    assert interp.evaluate("false and (1 / 0 == 1)") is False


def test_or_short_circuits_on_truthy_left(interp):
    assert interp.evaluate("true or (1 / 0 == 1)") is True


def test_implies_short_circuits_on_false_antecedent(interp):
    assert interp.evaluate("false implies (1 / 0 == 1)") is True


def test_namespace_constant(interp):
    assert interp.evaluate("gravity * 2", context="Lib") == pytest.approx(19.62)
    assert interp.evaluate("Lib::gravity") == pytest.approx(9.81)


def test_enum_literal(interp):
    value = interp.evaluate("Color::green", context="Lib")
    assert isinstance(value, longeron.EnumValue)
    assert value.name == "green"
    assert interp.evaluate("Color::green == Color::green", context="Lib") is True
    assert interp.evaluate("Color::green == Color::red", context="Lib") is False
    assert interp.evaluate("Color::green istype Color", context="Lib") is True


def test_calc_invocation_in_expression(interp):
    assert interp.evaluate("Twice(21.0)", context="Lib") == 42.0
    assert interp.evaluate("Twice(x = 3.0) + 1.0", context="Lib") == 7.0


def test_unresolved_name(interp):
    with pytest.raises(EvaluationError):
        interp.evaluate("nosuchthing + 1")


def test_index_out_of_range(interp):
    with pytest.raises(EvaluationError):
        interp.evaluate("(1, 2)#(0)")  # 1-based


def test_evaluate_ast_directly(interp):
    expr = longeron.parse_expression("2 + 2")
    assert interp.evaluate(expr) == 4


class TestExprSerializationEdges:
    def test_false_literal_to_text(self):
        assert longeron.parse_expression("false").to_text() == "false"

    def test_body_with_local_attribute_to_text(self):
        text = "(1, 2)->collect { in x; attribute y = x + 1; y }"
        assert longeron.parse_expression(text).to_text() == text

    def test_expr_from_dict_rejects_garbage(self):
        from longeron.ast import expr_from_dict

        assert expr_from_dict(None) is None
        with pytest.raises(ValueError, match="not a serialized expression"):
            expr_from_dict({"nope": 1})
        with pytest.raises(ValueError, match="unknown expression node type"):
            expr_from_dict({"@expr": "Bogus"})
