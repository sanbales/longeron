"""Units: dimension vectors, scale tags, and the ``[units]`` facade.

Two tiers live in this module (design: ``docs/design/units.md``):

**Core tier (stdlib only).**  Dimension vectors over the SI base --
tuples of :class:`~fractions.Fraction` powers -- each tagged with a
*scale* (``linear`` / ``offset`` / ``log``).  The unit table is *derived
from the vendored standard library's own definitional algebra*: base
units come from the model's ``SystemOfUnits`` declaration, derived units
evaluate their definitional expressions (``newton = kg*m/s^2``) in unit
space, prefixed units follow ``ConversionByPrefix``, conventional units
follow ``ConversionByConvention``, ``IntervalScale`` seeds the
``offset`` tag (and marks its display unit, so a Celsius value can never
pose as a linear kelvin), and the dB family seeds ``log``.  Any user or
third-party unit package shaped like the standard library derives the
same way, with no mapping table; :func:`register_unit` covers the rest.
The dimensional lint in :mod:`longeron.validation` runs entirely on this
tier -- no third-party dependency.

**Boundary tier (``pip install "longeron[units]"`` = pint).**  A typed
facade over pint for everything that actually converts or
pretty-prints: :func:`convert`, :func:`si_value`, :func:`si_unit`,
:func:`format_quantity`, :func:`om_unit`, :func:`with_units`.  pint's
``Quantity`` never appears in a public signature -- floats and unit
strings in, floats out.  The pint registry is a lazy module-level
singleton seeded from the same derived unit table the lint uses;
:func:`define` passes a raw pint definition through for boundary-side
spellings the derivation cannot reach.

The interpreter invariant is untouched: evaluation, instance slots, M0
populations, and ``compute()`` bodies see only plain floats.  Everything
here is validation-time or boundary-time.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import TYPE_CHECKING, Any, Literal

from . import ast as A
from . import model as M
from .errors import MissingExtraError

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

__all__ = [
    "Dim",
    "UnitInfo",
    "UnitTable",
    "convert",
    "define",
    "derive_units",
    "format_quantity",
    "om_unit",
    "register_unit",
    "si_unit",
    "si_value",
    "standard_unit_table",
    "unit_table",
    "units_extra_available",
    "with_units",
]

Scale = Literal["linear", "offset", "log"]

#: bare names / symbols seeding the ``log`` scale tag.  The vendored SI
#: declares the dB family as dimension-one units, not full
#: ``LogarithmicScale``s (its ``LogarithmicScale`` def is never used), so
#: the tag is seeded by name per the ratified design; any symbol starting
#: with ``dB`` (dBW, dBm, ...) is also tagged.
_LOG_UNIT_NAMES = frozenset(
    {"dB", "decibel", "bel", "Np", "neper", "oct", "octave", "dec", "decade"}
)


# ---------------------------------------------------------------------------
# Core tier: dimension vectors and the derived unit table
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dim:
    """An exponent vector over a system's base units.

    ``exp`` holds one :class:`~fractions.Fraction` power per base unit,
    in the order the system of units declares them (for the vendored SI:
    ``m, kg, s, A, K, mol, cd``).  Closed under multiply / divide /
    rational power -- exactly the quantity-dimension arithmetic of SysML
    v2 §9.8.9.
    """

    exp: tuple[Fraction, ...]

    def __mul__(self, other: Dim) -> Dim:
        return Dim(tuple(a + b for a, b in zip(self.exp, other.exp, strict=True)))

    def __truediv__(self, other: Dim) -> Dim:
        return Dim(tuple(a - b for a, b in zip(self.exp, other.exp, strict=True)))

    def __pow__(self, power: Fraction | int) -> Dim:
        return Dim(tuple(a * power for a in self.exp))

    @property
    def is_dimensionless(self) -> bool:
        return not any(self.exp)


@dataclass(frozen=True)
class UnitInfo:
    """One unit's derived semantics: vector, SI factor, scale tag.

    ``factor`` and ``offset`` map a magnitude in this unit to canonical
    SI: ``si = value * factor + offset`` (linear and offset scales; the
    ``log`` scale needs real conversion, which is the boundary tier's
    job).  ``qname`` is the qualified name keyed on long names
    (``SI::kilogram``); ``symbol`` is the short name (``kg``).
    """

    qname: str
    dim: Dim
    factor: float = 1.0
    offset: float = 0.0
    scale: Scale = "linear"
    symbol: str | None = None
    name: str | None = None

    @property
    def label(self) -> str:
        return self.symbol or self.name or self.qname


class UnitTable:
    """Units and quantity dimensions derived from a model.

    Lookup accepts qualified names on either the long name or the symbol
    (``SI::kilogram``, ``SI::kg``) and bare names (``kg``,
    ``kilogram``).  ``quantity_dimension`` answers for quantity
    vocabulary -- quantity attributes (``ISQBase::mass``), quantity value
    definitions (``MassValue``), and unit definitions (``MassUnit``) --
    which the lint uses to type attributes declared by quantity
    subsetting.  User-registered overrides (:func:`register_unit`) are
    consulted first.
    """

    def __init__(self, base_symbols: tuple[str, ...] = ()):
        #: symbols of the base units, in vector order (``('m', 'kg', ...)``)
        self.base_symbols = base_symbols
        self._by_key: dict[str, UnitInfo] = {}
        self._quantities: dict[str, Dim] = {}

    # -- construction -----------------------------------------------------

    def add(self, info: UnitInfo, *aliases: str) -> None:
        keys = [info.qname]
        prefix = info.qname.rsplit("::", 1)[0] + "::" if "::" in info.qname else ""
        for short in (info.symbol, info.name):
            if short:
                keys += [short, prefix + short] if prefix else [short]
        keys.extend(aliases)
        for key in keys:
            self._by_key.setdefault(key, info)
        self._by_key[info.qname] = info  # own qname always wins

    def add_quantity(self, qname: str, dim: Dim, *aliases: str) -> None:
        for key in (qname, *aliases):
            self._quantities.setdefault(key, dim)
        self._quantities[qname] = dim

    def _absorb(self, other: UnitTable) -> None:
        for key, info in other._by_key.items():
            self._by_key.setdefault(key, info)
        for key, dim in other._quantities.items():
            self._quantities.setdefault(key, dim)

    # -- lookup -------------------------------------------------------------

    def lookup(self, ref: str) -> UnitInfo | None:
        """The unit named ``ref`` (qualified or bare), or ``None``."""

        override = _OVERRIDES.get(ref)
        if override is not None:
            return override
        found = self._by_key.get(ref)
        if found is None and "::" in ref:
            found = self._by_key.get(ref.rsplit("::", 1)[-1])
        return found

    def quantity_dimension(self, qname: str) -> Dim | None:
        """Dimension of a quantity attribute / value def / unit def."""

        found = self._quantities.get(qname)
        if found is None and "::" in qname:
            found = self._quantities.get(qname.rsplit("::", 1)[-1])
        return found

    @property
    def dimensionless(self) -> Dim:
        return Dim(tuple(Fraction(0) for _ in self.base_symbols))

    def format_dim(self, dim: Dim) -> str:
        """Render a vector as an SI-base formula: ``kg·m/s^2``; ``1``."""

        if not self.base_symbols:
            return "?"
        num = [(sym, p) for sym, p in zip(self.base_symbols, dim.exp, strict=False) if p > 0]
        den = [(sym, -p) for sym, p in zip(self.base_symbols, dim.exp, strict=False) if p < 0]

        def part(sym: str, p: Fraction) -> str:
            return sym if p == 1 else f"{sym}^{p}"

        text = "·".join(part(s, p) for s, p in num) or "1"
        if den:
            text += "/" + "·".join(part(s, p) for s, p in den)
        return text


# module-level override registry (consulted before every derived table)
_OVERRIDES: dict[str, UnitInfo] = {}
# raw pint definitions queued for the lazy registry (boundary tier)
_PINT_DEFINITIONS: list[str] = []
# explicit model-vocabulary -> pint-spelling overrides
_PINT_SPELLINGS: dict[str, str] = {}


def register_unit(
    qname: str,
    *,
    dim: Mapping[str, int | Fraction] | Dim | None = None,
    factor: float = 1.0,
    offset: float = 0.0,
    scale: Scale = "linear",
    symbol: str | None = None,
    aliases: tuple[str, ...] = (),
    pint: str | None = None,
) -> UnitInfo:
    """Register (or override) a unit the derivation cannot reach.

    ``dim`` maps base-unit symbols to powers (``{"m": 1, "s": -2}``) or
    is a ready :class:`Dim` over the standard basis.  ``pint`` names the
    boundary-side spelling for the ``[units]`` facade (e.g. ``"dBm"``);
    for spellings pint does not know, pass a raw definition through
    :func:`define` as well.  The override is keyed on ``qname``, the
    symbol, and every alias, and wins over derived entries everywhere
    (lint and facade alike).
    """

    table = standard_unit_table()
    if isinstance(dim, Dim):
        vector = dim
    elif dim is not None:
        n = len(table.base_symbols)
        axis = {sym: i for i, sym in enumerate(table.base_symbols)}
        exp = [Fraction(0)] * n
        for sym, power in dim.items():
            exp[axis[sym]] = Fraction(power)
        vector = Dim(tuple(exp))
    else:
        vector = table.dimensionless
    info = UnitInfo(
        qname=qname,
        dim=vector,
        factor=factor,
        offset=offset,
        scale=scale,
        symbol=symbol,
        name=qname.rsplit("::", 1)[-1],
    )
    for key in (qname, qname.rsplit("::", 1)[-1], symbol, *aliases):
        if key:
            _OVERRIDES[key] = info
    if pint is not None:
        for key in (qname, qname.rsplit("::", 1)[-1], symbol, *aliases):
            if key:
                _PINT_SPELLINGS[key] = pint
    return info


def _clear_registered_units() -> None:
    """Reset user registrations (test hook)."""

    _OVERRIDES.clear()
    _PINT_DEFINITIONS.clear()
    _PINT_SPELLINGS.clear()
    global _PINT_REGISTRY
    _PINT_REGISTRY = None


# -- derivation from the model's own definitional algebra -------------------


class _Underivable(Exception):
    """A definitional expression references something not yet derived."""


def _member_value(element: M.Namespace, redefined: str) -> A.Expr | None:
    """Value of the member redefining (or named) ``redefined``."""

    for member in element.members:
        if not isinstance(member, M.Usage) or member.value is None:
            continue
        names = [r.rsplit("::", 1)[-1] for r in member.redefines]
        if member.name:
            names.append(member.name)
        if redefined in names:
            return member.value.expr
    return None


def _conversion_member(element: M.Namespace) -> tuple[str | None, M.Usage | None]:
    """The ``unitConversion`` redefinition member and its kind, if any."""

    for member in element.members:
        if not isinstance(member, M.Usage):
            continue
        names = [r.rsplit("::", 1)[-1] for r in member.redefines] + [member.name]
        if "unitConversion" in names:
            kind = member.types[0].rsplit("::", 1)[-1] if member.types else None
            return kind, member
    return None, None


def _type_names(usage: M.Definition | M.Usage) -> list[str]:
    refs = usage.supers if isinstance(usage, M.Definition) else usage.types
    return [t.rsplit("::", 1)[-1] for t in refs]


def _eval_number(expr: A.Expr) -> float:
    """Numeric constant folding for conversion factors (``27316/100``)."""

    if isinstance(expr, A.Literal) and isinstance(expr.value, (int, float)):
        return float(expr.value)
    if isinstance(expr, A.Unary) and expr.op in ("+", "-"):
        value = _eval_number(expr.operand)
        return -value if expr.op == "-" else value
    if isinstance(expr, A.Binary):
        left, right = _eval_number(expr.left), _eval_number(expr.right)
        ops = {
            "+": lambda: left + right,
            "-": lambda: left - right,
            "*": lambda: left * right,
            "/": lambda: left / right,
            "^": lambda: left**right,
            "**": lambda: left**right,
        }
        if expr.op in ops:
            return float(ops[expr.op]())
    raise _Underivable(expr)


class _Derivation:
    """One pass of unit derivation over a model tree."""

    def __init__(self, model: M.Model, base: UnitTable | None):
        self.model = model
        self.base = base
        self.attributes: list[M.Usage] = []
        self.definitions: list[M.Definition] = []
        self.symbols: dict[str, M.Usage] = {}  # bare name -> attribute usage
        self.entries: dict[int, UnitInfo] = {}  # id(usage) -> derived info
        self.prefixes: dict[int, float] = {}  # id(prefix usage) -> factor
        self.refused: list[M.Usage] = []
        self._dimensionless = Dim(())
        for element in model.iter_tree():
            if (
                isinstance(element, M.Usage)
                and element.kind == "attribute"
                and isinstance(element.owner, M.Package)
            ):
                # the stdlib pattern declares units, prefixes, and quantity
                # vocabulary as package-level attributes; def-internal
                # structural features (mRef, referenceUnit, ...) are not units
                self.attributes.append(element)
                for name in (element.name, element.short_name):
                    if name:
                        self.symbols.setdefault(name, element)
            elif isinstance(element, M.Definition):
                self.definitions.append(element)

    # -- local + global name lookup ------------------------------------------

    def _resolve_ref(self, parts: tuple[str, ...], context: M.Element) -> M.Usage | None:
        name = parts[-1]
        node: M.Element | None = context
        while node is not None:  # lexical scope first (handles shadowing)
            if isinstance(node, M.Namespace):
                found = node.member_named(name)
                if isinstance(found, M.Usage):
                    return found
            node = node.owner
        return self.symbols.get(name)

    def _info_for(self, parts: tuple[str, ...], context: M.Element) -> UnitInfo | None:
        target = self._resolve_ref(parts, context)
        if target is not None:
            found = self.entries.get(id(target))
            if found is not None:
                return found
            if target in self.refused or id(target) in self.entries:
                return None
        if self.base is not None:  # e.g. a user package referencing SI::kg
            return self.base.lookup("::".join(parts))
        return None

    # -- unit-space expression evaluation ------------------------------------

    def _eval_unit_expr(self, expr: A.Expr, context: M.Element) -> tuple[Dim, float]:
        if isinstance(expr, A.FeatureRef):
            info = self._info_for(expr.parts, context)
            if info is None:
                raise _Underivable(expr)
            return info.dim, info.factor
        if isinstance(expr, A.Literal) and isinstance(expr.value, (int, float)):
            return self._dimensionless, float(expr.value)
        if isinstance(expr, A.Unary) and expr.op in ("+", "-"):
            dim, factor = self._eval_unit_expr(expr.operand, context)
            return dim, -factor if expr.op == "-" else factor
        if isinstance(expr, A.Binary) and expr.op in ("*", "/", "^", "**"):
            ldim, lf = self._eval_unit_expr(expr.left, context)
            if expr.op == "*":
                rdim, rf = self._eval_unit_expr(expr.right, context)
                return ldim * rdim, lf * rf
            if expr.op == "/":
                rdim, rf = self._eval_unit_expr(expr.right, context)
                return ldim / rdim, lf / rf
            power = Fraction(_eval_number(expr.right)).limit_denominator(1000)
            return ldim**power, lf ** float(power)
        if isinstance(expr, A.Constructor):  # `one = new DimensionOneUnit()`
            return self._dimensionless, 1.0
        raise _Underivable(expr)

    # -- the derivation ---------------------------------------------------------

    def run(self) -> UnitTable:
        basis = self._find_basis()
        if basis is None:
            if self.base is None:
                return UnitTable()
            base_symbols = self.base.base_symbols
            seeded: list[M.Usage] = []
        else:
            base_symbols, seeded = basis
        self._dimensionless = Dim(tuple(Fraction(0) for _ in base_symbols))
        table = UnitTable(base_symbols)

        for i, usage in enumerate(seeded):
            exp = tuple(Fraction(1 if j == i else 0) for j in range(len(base_symbols)))
            self.entries[id(usage)] = self._info(usage, Dim(exp), 1.0, "linear")

        self._derive_prefixes()
        candidates = [u for u in self.attributes if id(u) not in self.entries if self._is_unit(u)]
        pending = candidates
        progress = True
        while progress and pending:
            progress = False
            still: list[M.Usage] = []
            for usage in pending:
                info = self._try_derive(usage)
                if info is not None:
                    self.entries[id(usage)] = info
                    progress = True
                else:
                    still.append(usage)
            # reverse hop: kg = kilo·g seeds g even though g has no conversion
            progress = self._derive_reversed(still) or progress
            pending = [u for u in still if id(u) not in self.entries]
        self.refused = pending

        self._tag_scales()
        for info in self.entries.values():
            table.add(info)
        self._add_aliases(table)
        self._derive_quantities(table, base_symbols)
        if self.base is not None:
            table._absorb(self.base)
        return table

    def _info(
        self, usage: M.Usage, dim: Dim, factor: float, scale: Scale, offset: float = 0.0
    ) -> UnitInfo:
        return UnitInfo(
            qname=usage.qualified_name or usage.label,
            dim=dim,
            factor=factor,
            offset=offset,
            scale=scale,
            symbol=usage.short_name,
            name=usage.name,
        )

    def _find_basis(self) -> tuple[tuple[str, ...], list[M.Usage]] | None:
        """Base units from the model's own ``SystemOfUnits`` declaration."""

        for usage in self.attributes:
            if "SystemOfUnits" not in _type_names(usage):
                continue
            expr = _member_value(usage, "baseUnits")
            if not isinstance(expr, A.SequenceExpr):
                continue
            seeded: list[M.Usage] = []
            for item in expr.items:
                if not isinstance(item, A.FeatureRef):
                    return None
                target = self._resolve_ref(item.parts, usage)
                if target is None:
                    return None
                seeded.append(target)
            symbols = tuple(u.short_name or u.name or "?" for u in seeded)
            return symbols, seeded
        return None

    def _is_unit(self, usage: M.Usage) -> bool:
        names = _type_names(usage)
        if any(n.endswith("Unit") for n in names):
            return True
        if "IntervalScale" in names or "LogarithmicScale" in names:
            return True
        kind, _ = _conversion_member(usage)
        return kind in ("ConversionByPrefix", "ConversionByConvention")

    def _derive_prefixes(self) -> None:
        for usage in self.attributes:
            if "UnitPrefix" in _type_names(usage):
                expr = _member_value(usage, "conversionFactor")
                if expr is not None:
                    try:
                        self.prefixes[id(usage)] = _eval_number(expr)
                    except _Underivable:
                        pass

    def _conversion(self, usage: M.Usage) -> tuple[Dim, float] | None:
        """(dim, si-factor) via a ``unitConversion`` member, if derivable now."""

        kind, conv = _conversion_member(usage)
        if conv is None:
            return None
        ref = _member_value(conv, "referenceUnit")
        if ref is None:
            return None
        dim, ref_factor = self._eval_unit_expr(ref, usage)
        if kind == "ConversionByPrefix":
            prefix_expr = _member_value(conv, "prefix")
            if not isinstance(prefix_expr, A.FeatureRef):
                raise _Underivable(conv)
            prefix = self._resolve_ref(prefix_expr.parts, usage)
            if prefix is None or id(prefix) not in self.prefixes:
                raise _Underivable(prefix_expr)
            return dim, self.prefixes[id(prefix)] * ref_factor
        factor_expr = _member_value(conv, "conversionFactor")
        factor = _eval_number(factor_expr) if factor_expr is not None else 1.0
        return dim, factor * ref_factor

    def _try_derive(self, usage: M.Usage) -> UnitInfo | None:
        try:
            conversion = self._conversion(usage)
            if conversion is not None:
                return self._info(usage, *conversion, "linear")
            if "IntervalScale" in _type_names(usage):
                unit_expr = _member_value(usage, "unit")
                if unit_expr is None:
                    return None
                dim, factor = self._eval_unit_expr(unit_expr, usage)
                return self._info(usage, dim, factor, "offset", self._scale_offset(usage))
            if usage.value is not None:
                dim, factor = self._eval_unit_expr(usage.value.expr, usage)
                return self._info(usage, dim, factor, "linear")
        except _Underivable:
            return None
        return None

    def _scale_offset(self, usage: M.Usage) -> float:
        """An interval scale's zero shift, from its definitional members
        (``zeroDegreeCelsiusInKelvin = 273.15 [K]``)."""

        for member in usage.members:
            if not isinstance(member, M.Usage) or member.value is None:
                continue
            expr = member.value.expr
            if isinstance(expr, A.QuantityOp) and isinstance(expr.unit, A.FeatureRef):
                try:
                    base = _eval_number(expr.base)
                    _, factor = self._eval_unit_expr(expr.unit, usage)
                except _Underivable:
                    continue
                return base * factor
        return 0.0

    def _derive_reversed(self, pending: list[M.Usage]) -> bool:
        """Invert known prefix/convention conversions onto their reference
        (``kg = kilo·g`` gives ``g`` a vector even though ``g`` declares
        nothing)."""

        progress = False
        for usage in self.attributes:
            info = self.entries.get(id(usage))
            if info is None:
                continue
            kind, conv = _conversion_member(usage)
            if conv is None:
                continue
            ref = _member_value(conv, "referenceUnit")
            if not isinstance(ref, A.FeatureRef):
                continue
            target = self._resolve_ref(ref.parts, usage)
            if target is None or id(target) in self.entries or target not in pending:
                continue
            try:
                if kind == "ConversionByPrefix":
                    prefix_expr = _member_value(conv, "prefix")
                    if not isinstance(prefix_expr, A.FeatureRef):
                        continue
                    prefix = self._resolve_ref(prefix_expr.parts, usage)
                    if prefix is None or id(prefix) not in self.prefixes:
                        continue
                    factor = self.prefixes[id(prefix)]
                else:
                    factor_expr = _member_value(conv, "conversionFactor")
                    factor = _eval_number(factor_expr) if factor_expr is not None else 1.0
            except _Underivable:
                continue
            self.entries[id(target)] = self._info(target, info.dim, info.factor / factor, "linear")
            progress = True
        return progress

    def _tag_scales(self) -> None:
        """Seed ``log`` (dB family) and propagate ``offset`` from every
        interval scale to its display unit (the ratified °C ruling)."""

        by_id = self.entries
        for key, info in list(by_id.items()):
            names = {n for n in (info.symbol, info.name) if n}
            if names & _LOG_UNIT_NAMES or any(n.startswith("dB") for n in names):
                by_id[key] = replace(info, scale="log")
        for usage in self.attributes:
            scale_info = by_id.get(id(usage))
            if scale_info is None or scale_info.scale != "offset":
                continue
            unit_expr = _member_value(usage, "unit")
            if not isinstance(unit_expr, A.FeatureRef):
                continue
            target = self._resolve_ref(unit_expr.parts, usage)
            if target is not None and id(target) in by_id:
                display = by_id[id(target)]
                if display.scale == "linear":
                    by_id[id(target)] = replace(display, scale="offset", offset=scale_info.offset)

    def _add_aliases(self, table: UnitTable) -> None:
        for element in self.model.iter_tree():
            if not isinstance(element, M.Alias) or not element.name:
                continue
            owner = element.owner
            if not isinstance(owner, M.Namespace):
                continue
            target = owner.member_named(element.target.rsplit("::", 1)[-1])
            if isinstance(target, M.Usage) and id(target) in self.entries:
                table.add(self.entries[id(target)], element.name)

    def _derive_quantities(self, table: UnitTable, base_symbols: tuple[str, ...]) -> None:
        """Quantity vocabulary: unit defs (``MassUnit``), value defs
        (``MassValue``), and quantity attributes (``ISQBase::mass``), from
        the ``QuantityPowerFactor`` structure and the ``baseQuantities``
        declaration."""

        axis = self._quantity_axes(len(base_symbols))
        if not axis:
            return
        unit_defs: dict[str, Dim] = {}
        for definition in self.definitions:
            dim = self._power_factor_dim(definition, axis, len(base_symbols))
            if dim is not None:
                qname = definition.qualified_name or definition.label
                unit_defs[definition.label] = dim
                table.add_quantity(qname, dim, definition.label)
        value_defs: dict[str, Dim] = {}
        for definition in self.definitions:
            mref = None
            for member in definition.members:
                if isinstance(member, M.Usage) and "mRef" in [
                    r.rsplit("::", 1)[-1] for r in member.redefines
                ]:
                    mref = member
                    break
            if mref is None or not mref.types:
                continue
            dim = unit_defs.get(mref.types[0].rsplit("::", 1)[-1])
            if dim is not None:
                qname = definition.qualified_name or definition.label
                value_defs[definition.label] = dim
                table.add_quantity(qname, dim, definition.label)
        for usage in self.attributes:
            for type_name in _type_names(usage):
                dim = value_defs.get(type_name)
                if dim is not None and usage.qualified_name:
                    table.add_quantity(usage.qualified_name, dim, usage.label)
                    break

    def _quantity_axes(self, n: int) -> dict[str, int]:
        """Base-quantity symbol -> vector axis, via ``baseQuantities``."""

        for usage in self.attributes:
            if "SystemOfQuantities" not in _type_names(usage):
                continue
            expr = _member_value(usage, "baseQuantities")
            if not isinstance(expr, A.SequenceExpr) or len(expr.items) != n:
                continue
            axes: dict[str, int] = {}
            for i, item in enumerate(expr.items):
                if isinstance(item, A.FeatureRef):
                    axes[item.parts[-1]] = i
            return axes
        return {}

    def _power_factor_dim(
        self, definition: M.Definition, axis: dict[str, int], n: int
    ) -> Dim | None:
        exp = [Fraction(0)] * n
        found = False
        for member in definition.members:
            if not isinstance(member, M.Usage) or "QuantityPowerFactor" not in _type_names(member):
                continue
            quantity = _member_value(member, "quantity")
            exponent = _member_value(member, "exponent")
            symbol: str | None = None
            if isinstance(quantity, A.ChainAccess):
                symbol = quantity.parts[-1]
            elif isinstance(quantity, A.FeatureRef):
                symbol = quantity.parts[-1]
            if symbol is None or symbol not in axis:
                continue
            try:
                power = Fraction(_eval_number(exponent)) if exponent is not None else Fraction(1)
            except _Underivable:
                continue
            exp[axis[symbol]] += power
            found = True
        return Dim(tuple(exp)) if found else None


def derive_units(model: M.Model, *, base: UnitTable | None = None) -> UnitTable:
    """Derive a :class:`UnitTable` from ``model``'s definitional algebra.

    Works on any model shaped like the vendored quantities library
    (finding 4 of the design): a ``SystemOfUnits`` with ``baseUnits``
    seeds the basis, ``ConversionByPrefix`` / ``ConversionByConvention``
    members inherit their reference unit's vector, derived units evaluate
    their definitional expressions in unit space, and ``IntervalScale`` /
    the dB family seed the scale tags.  ``base`` supplies an existing
    table (usually the standard one) whose basis and entries the new
    units may reference -- so a user package declaring
    ``pound : MassUnit`` against ``kg`` derives with no mapping table.
    """

    return _Derivation(model, base).run()


_STANDARD_TABLE: UnitTable | None = None
_STANDARD_REFUSED: tuple[str, ...] = ()


def standard_unit_table() -> UnitTable:
    """The unit table derived from the vendored standard library (cached).

    Returns an empty table when the standard library cannot load --
    callers degrade exactly like validation does.
    """

    global _STANDARD_TABLE, _STANDARD_REFUSED
    if _STANDARD_TABLE is None:
        try:
            from . import stdlib as stdlib_module

            derivation = _Derivation(stdlib_module.standard_library_model(cache=True), None)
            _STANDARD_TABLE = derivation.run()
            _STANDARD_REFUSED = tuple(u.qualified_name or u.label for u in derivation.refused)
        except Exception:
            _STANDARD_TABLE = UnitTable()
    return _STANDARD_TABLE


def unit_table(model: M.Model | None = None, *, include_standard: bool = True) -> UnitTable:
    """The table for validating ``model``: the standard table extended
    with whatever unit packages the model itself carries."""

    base = standard_unit_table() if include_standard else None
    if model is None:
        return base if base is not None else UnitTable()
    return derive_units(model, base=base)


def units_extra_available() -> bool:
    """True when the ``[units]`` extra (pint) is importable.

    The ``mixed-units`` lint gates on this per the ratified kg + lbm
    ruling: with the extra, declaration-boundary normalization makes
    mixed same-dimension arithmetic correct (the normalization hook is
    the 0.11 interpreter seam); without it, the core tier converts
    nothing by design, so the lint warns.
    """

    try:
        import importlib.util

        return importlib.util.find_spec("pint") is not None
    except Exception:  # pragma: no cover - importlib misbehaving
        return False


# ---------------------------------------------------------------------------
# Boundary tier: the typed facade over pint (`longeron[units]`)
# ---------------------------------------------------------------------------

_PINT_REGISTRY: Any = None

#: pint spellings of the SI base dimensions, in table-basis order --
#: used to sanity-check candidate spellings against derived vectors
_PINT_BASE_DIMS = (
    "[length]",
    "[mass]",
    "[time]",
    "[current]",
    "[temperature]",
    "[substance]",
    "[luminosity]",
)


def _require_pint() -> Any:
    try:
        import pint
    except ImportError as err:
        raise MissingExtraError("longeron.units", "pint", "units") from err
    return pint


def _registry() -> Any:
    """The lazy module-level pint registry (built once, ~hundreds of ms)."""

    global _PINT_REGISTRY
    if _PINT_REGISTRY is None:
        pint = _require_pint()
        registry = pint.UnitRegistry()
        for definition in _PINT_DEFINITIONS:
            registry.define(definition)
        _PINT_REGISTRY = registry
    return _PINT_REGISTRY


def define(definition: str) -> None:
    """Pass a raw pint unit definition through to the facade's registry.

    The boundary-side escape hatch of the foreign-packages ruling: where
    derivation cannot reach and pint has no spelling, e.g.
    ``define("furlong = 201.168 * meter = fur")``.  Queued if the lazy
    registry is not built yet.
    """

    _PINT_DEFINITIONS.append(definition)
    if _PINT_REGISTRY is not None:
        _PINT_REGISTRY.define(definition)


def _pint_dimensionality(info: UnitInfo) -> dict[str, float] | None:
    table = standard_unit_table()
    if len(table.base_symbols) != len(_PINT_BASE_DIMS):
        return None
    if len(info.dim.exp) != len(_PINT_BASE_DIMS):
        return None
    return {
        dim: float(power)
        for dim, power in zip(_PINT_BASE_DIMS, info.dim.exp, strict=True)
        if power != 0
    }


def _pint_unit(unit: str) -> Any:
    """Map model vocabulary (``SI::kg``, ``kg``, ``°C``, ``dBm``) to a
    pint unit, deriving a definition from the unit table when pint has
    no spelling of its own."""

    registry = _registry()
    spelling = _PINT_SPELLINGS.get(unit)
    if spelling is not None:
        return registry.Unit(spelling)
    info = standard_unit_table().lookup(unit)
    candidates = []
    if info is not None:
        candidates += [c for c in (info.symbol, info.name) if c]
    candidates.append(unit.rsplit("::", 1)[-1])
    expected = _pint_dimensionality(info) if info is not None else None
    for candidate in candidates:
        for text in (candidate, candidate.replace("⋅", "*")):
            try:
                found = registry.Unit(text)
            except Exception:
                continue
            if expected is not None and not _dimensionality_matches(found, expected, registry):
                continue  # e.g. a name collision on pint's side
            return found
    if info is not None and info.scale != "log":
        return registry.Unit(_define_from_table(info, registry))
    raise ValueError(f"unit {unit!r} has no pint spelling (register_unit/define one)")


def _dimensionality_matches(unit: Any, expected: dict[str, float], registry: Any) -> bool:
    try:
        actual = dict(registry.get_dimensionality(unit))
    except Exception:
        return True  # log units etc.: trust the spelling
    return {k: float(v) for k, v in actual.items()} == expected


def _define_from_table(info: UnitInfo, registry: Any) -> str:
    """Define a table-derived unit in pint from its SI decomposition."""

    name = "_longeron_" + "".join(c if c.isalnum() else "_" for c in info.qname)
    try:
        registry.Unit(name)
        return name  # already defined
    except Exception:
        pass
    base = _si_base_expression(info.dim) or "dimensionless"
    if info.scale == "offset":
        registry.define(f"{name} = {info.factor} * {base}; offset: {info.offset / info.factor}")
    else:
        registry.define(f"{name} = {info.factor} * {base}")
    return name


def _si_base_expression(dim: Dim, *, power_op: str = "**", kelvin: str = "K") -> str:
    table = standard_unit_table()
    parts: list[str] = []
    for symbol, power in zip(table.base_symbols, dim.exp, strict=False):
        if power == 0:
            continue
        spelled = kelvin if symbol == "K" else symbol
        parts.append(spelled if power == 1 else f"{spelled}{power_op}{_power_text(power)}")
    return " * ".join(parts)


def _power_text(power: Fraction) -> str:
    if power.denominator == 1:
        return str(power.numerator)
    return f"({power.numerator}/{power.denominator})"


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert ``value`` between units of the model's vocabulary.

    Handles linear, offset, and logarithmic scales through pint:
    ``convert(25.0, "°C", "K") == 298.15``,
    ``convert(3.0, "dBm", "mW") ≈ 1.995``.  Requires the ``[units]``
    extra; raises :class:`~longeron.errors.MissingExtraError` without it.
    """

    registry = _registry()
    quantity = registry.Quantity(value, _pint_unit(from_unit))
    return float(quantity.to(_pint_unit(to_unit)).magnitude)


def si_value(value: float, unit: str) -> float:
    """The magnitude of ``value [unit]`` in canonical SI:
    ``si_value(25.0, "°C") == 298.15``, ``si_value(30.0, "min") == 1800.0``."""

    registry = _registry()
    quantity = registry.Quantity(value, _pint_unit(unit))
    return float(quantity.to_base_units().magnitude)


def si_unit(unit: str) -> str:
    """The canonical SI spelling of ``unit``'s dimension:
    ``si_unit("min") == "s"``; ``si_unit("dBm") == "W"``.

    Prefers the shortest *named* coherent SI unit from the derived table
    (``W``, not ``kg*m**2/s**3``); falls back to pint's base-unit
    spelling for dimensions the table has no name for."""

    registry = _registry()
    base = registry.Quantity(1.0, _pint_unit(unit)).to_base_units().units
    named = _named_si_symbol(base, registry)
    if named is not None:
        return named
    text = f"{base:~}".replace(" ", "")
    return text or "1"


def _named_si_symbol(base_units: Any, registry: Any) -> str | None:
    """The shortest coherent named SI unit matching a pint dimensionality."""

    axis = {name: i for i, name in enumerate(_PINT_BASE_DIMS)}
    exp = [Fraction(0)] * len(_PINT_BASE_DIMS)
    try:
        for name, power in dict(registry.get_dimensionality(base_units)).items():
            if name not in axis:
                return None
            exp[axis[name]] = Fraction(power).limit_denominator(1000)
    except Exception:
        return None
    dim = Dim(tuple(exp))
    table = standard_unit_table()
    if len(table.base_symbols) != len(_PINT_BASE_DIMS):
        return None
    if dim.is_dimensionless:
        return "1"
    candidates = {
        info.label
        for info in table._by_key.values()
        if info.scale == "linear" and info.factor == 1.0 and info.dim == dim
    }
    if not candidates:
        return None
    return min(candidates, key=lambda label: (len(label), label))


def format_quantity(value: float, unit: str, *, precision: int = 3) -> str:
    """``value`` in its *declared* display unit: ``format_quantity(0.254,
    "m") == '0.254 m'``.  Display only -- no conversion, no pint needed."""

    info = standard_unit_table().lookup(unit)
    label = info.label if info is not None else unit.rsplit("::", 1)[-1]
    return f"{value:.{precision}g} {label}"


#: OpenMDAO spellings for non-coherent units OM's own library knows;
#: everything else is composed from the SI base or stays unitless
_OM_ALIASES = {
    "min": "min",
    "h": "h",
    "d": "d",
    "g": "g",
    "L": "L",
    "mm": "mm",
    "cm": "cm",
    "km": "km",
    "nm": "nm",
    "mL": "mL",
    "kW": "kW",
    "kJ": "kJ",
    "MJ": "MJ",
    "GJ": "GJ",
    "mN": "mN",
    "km/h": "km/h",
    "rad": "rad",
    "°": "deg",
    "eV": "eV",
    "°C": "degC",
    "°C_abs": "degC",
    "°F": "degF",
}


def om_unit(unit: str) -> str | None:
    """The OpenMDAO dialect spelling of ``unit``, or ``None`` when OM has
    no equivalent (log-scale units, dimensionless, unknowns) -- the
    variable then stays unitless, exactly as today.  Pure table lookup:
    needs neither pint nor OpenMDAO installed."""

    info = standard_unit_table().lookup(unit)
    if info is None:
        return None
    if info.scale == "log":
        return None  # verified unsupported by OM's units library
    for name in (info.symbol, info.name, unit.rsplit("::", 1)[-1]):
        if name in _OM_ALIASES:
            return _OM_ALIASES[name]
    if info.dim.is_dimensionless:
        return None
    if info.scale == "linear" and math.isclose(info.factor, 1.0):
        return _si_base_expression(info.dim, kelvin="degK") or None
    return None


def with_units(df: pd.DataFrame, units: Mapping[str, str]) -> pd.DataFrame:
    """A copy of ``df`` with pint-pandas dtypes applied per column:
    ``with_units(frame, {"mass": "kg", "flightTime": "min"})``.

    Column arithmetic then carries units (and raises on dimensional
    nonsense).  Requires the ``[units]`` extra (pint + pint-pandas)."""

    _registry()  # MissingExtraError first if pint itself is absent
    try:
        import pint_pandas
    except ImportError as err:
        raise MissingExtraError("longeron.units.with_units", "pint-pandas", "units") from err
    pint_pandas.PintType.ureg = _registry()
    out = df.copy()
    for column, unit in units.items():
        out[column] = out[column].astype(f"pint[{_pint_unit(unit):~}]")
    return out
