"""The top-level ``longeron.*`` namespace is deliberate, not accidental.

Regression for the star export of :mod:`longeron.model`: its ``__all__``
used to be generated from ``dir()``, which swept the module's *imports*
(``typing.Literal``, ``dataclasses.field``, ...) into ``longeron.*``.
The public surface must contain only intentional names.
"""

import longeron
from longeron import model


def test_no_stdlib_imports_leak_into_the_top_level_namespace():
    for leaked in ("Literal", "field", "dataclass", "Iterator", "get_args", "annotations"):
        assert leaked not in longeron.__all__
        assert leaked not in dir(longeron)
        assert leaked not in model.__all__


def test_ast_aliases_stay_off_the_top_level():
    # the AST literal is longeron.ast.Literal; model.py's private aliases
    # (Expr, LiteralExpr) and sentinels must not shadow it at the top level
    for name in ("Expr", "LiteralExpr", "ENTRY_SOURCE"):
        assert name not in longeron.__all__
        assert hasattr(model, name)  # still a module attribute, deliberately


def test_intended_surface_is_exported():
    for name in (
        "loads",
        "load",
        "Interpreter",
        "Instance",
        "validate",
        "to_sysml",
        "to_json",
        "from_json",
        "SysMLError",
        # the model vocabulary, via model.__all__
        "Model",
        "Package",
        "Definition",
        "Usage",
        "FeatureValue",
        "Multiplicity",
        "EnumerationDefinition",
    ):
        assert name in longeron.__all__
        assert hasattr(longeron, name)


def test_every_exported_name_resolves_and_is_unique():
    assert all(hasattr(longeron, name) for name in longeron.__all__)
    assert len(set(longeron.__all__)) == len(longeron.__all__)
    assert all(hasattr(model, name) for name in model.__all__)
