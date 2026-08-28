"""Units: the derived table (core tier) and the pint facade (boundary tier).

The core-tier tests need nothing beyond the stdlib: every vector and
factor is derived from the vendored quantities library's own definitional
algebra (``newton = kg*m/s^2`` survives in the model).  The facade tests
skip cleanly when pint is absent -- the CI posture -- and run for real in
an environment with the ``[units]`` extra installed.
"""

import importlib.util
from fractions import Fraction

import pytest

import longeron
from longeron import units as U
from longeron.errors import MissingExtraError

HAVE_PINT = importlib.util.find_spec("pint") is not None
HAVE_PINT_PANDAS = importlib.util.find_spec("pint_pandas") is not None
requires_pint = pytest.mark.skipif(not HAVE_PINT, reason="pint not installed ([units] extra)")


@pytest.fixture
def clean_registry():
    """Isolate user registrations (module-level override state)."""

    U._clear_registered_units()
    yield
    U._clear_registered_units()


def dim_of(name):
    info = U.standard_unit_table().lookup(name)
    assert info is not None, f"{name!r} missing from the derived table"
    return info


class TestDerivedTable:
    """Vectors and SI factors derived from the stdlib's own algebra."""

    def test_basis_comes_from_the_model_system_of_units(self):
        # SI.sysml: baseUnits = (m, kg, s, A, K, mol, cd)
        assert U.standard_unit_table().base_symbols == ("m", "kg", "s", "A", "K", "mol", "cd")

    def test_base_units_seed_unit_vectors(self):
        kg = dim_of("kg")
        assert kg.qname == "SI::kilogram"
        assert kg.factor == 1.0
        assert kg.dim.exp == (0, 1, 0, 0, 0, 0, 0)

    def test_newton_from_its_definitional_expression(self):
        # `attribute <N> newton : ForceUnit = kg*m/s^2` -- ForceUnit itself
        # dangles (ISQMechanics is not vendored) but the algebra survives
        newton = dim_of("N")
        assert newton.dim.exp == (1, 1, -2, 0, 0, 0, 0)
        assert newton.factor == 1.0

    def test_watt_through_the_derivation_chain(self):
        # W = J/s, J = N*m, N = kg*m/s^2: three fixed-point rounds deep
        watt = dim_of("W")
        assert watt.dim.exp == (2, 1, -3, 0, 0, 0, 0)
        assert watt.factor == 1.0

    def test_minute_conversion_by_convention(self):
        minute = dim_of("min")
        assert minute.dim.exp == (0, 0, 1, 0, 0, 0, 0)
        assert minute.factor == 60.0
        assert dim_of("h").factor == 3600.0  # h = 60 min, transitively

    def test_prefixed_units_conversion_by_prefix(self):
        assert dim_of("mm").factor == pytest.approx(1e-3)
        assert dim_of("km").factor == pytest.approx(1e3)
        assert dim_of("mm").dim == dim_of("m").dim

    def test_gram_derived_by_inverting_the_kilogram_prefix(self):
        # gram declares nothing; kg = kilo*g is inverted onto it
        gram = dim_of("g")
        assert gram.dim == dim_of("kg").dim
        assert gram.factor == pytest.approx(1e-3)

    def test_compound_unit_spellings(self):
        kmh = dim_of("km/h")
        assert kmh.dim.exp == (1, 0, -1, 0, 0, 0, 0)
        assert kmh.factor == pytest.approx(1000.0 / 3600.0)
        assert dim_of("W⋅h").factor == pytest.approx(3600.0)

    def test_decibel_is_log_scale(self):
        db = dim_of("dB")
        assert db.scale == "log"
        assert db.dim.is_dimensionless

    def test_celsius_interval_scale_is_offset(self):
        absolute = dim_of("°C_abs")
        assert absolute.scale == "offset"
        assert absolute.offset == pytest.approx(273.15)
        assert absolute.dim == dim_of("K").dim

    def test_celsius_display_unit_inherits_the_offset_tag(self):
        # the ratified ruling: °C must not pose as a linear kelvin, so the
        # interval scale's display unit is tagged offset too
        celsius = dim_of("°C")
        assert celsius.scale == "offset"
        assert celsius.offset == pytest.approx(273.15)
        assert dim_of("K").scale == "linear"

    def test_quantity_vocabulary_from_power_factors(self):
        table = U.standard_unit_table()
        mass = table.quantity_dimension("ISQBase::mass")
        assert mass is not None and mass.exp == (0, 1, 0, 0, 0, 0, 0)
        duration = table.quantity_dimension("DurationValue")
        assert duration is not None and duration.exp == (0, 0, 1, 0, 0, 0, 0)
        temp_unit = table.quantity_dimension("TemperatureDifferenceUnit")
        assert temp_unit is not None and temp_unit.exp == (0, 0, 0, 0, 1, 0, 0)

    def test_lookup_accepts_qualified_and_bare_spellings(self):
        table = U.standard_unit_table()
        entries = {table.lookup(k) for k in ("kg", "kilogram", "SI::kg", "SI::kilogram")}
        assert len(entries) == 1 and None not in entries

    def test_aliases_reach_their_targets(self):
        assert dim_of("metric ton").qname == "SI::tonne"
        assert dim_of("arcmin").qname == "SI::minute (angle)"

    def test_full_derivation_coverage(self):
        # every unit-shaped attribute of the vendored library derives;
        # a refusal here means the stdlib gained a shape the derivation
        # cannot read -- extend it rather than special-casing
        U.standard_unit_table()
        assert U._STANDARD_REFUSED == ()

    def test_format_dim(self):
        table = U.standard_unit_table()
        assert table.format_dim(dim_of("N").dim) == "m·kg/s^2"
        assert table.format_dim(dim_of("one").dim) == "1"

    def test_dim_algebra_is_closed_over_fractions(self):
        newton = dim_of("N").dim
        metre = dim_of("m").dim
        pascal = newton / (metre * metre)
        assert pascal == dim_of("Pa").dim
        assert (metre**2).exp[0] == Fraction(2)
        root = metre ** Fraction(1, 2)
        assert root.exp[0] == Fraction(1, 2)


class TestPrefixVocabulary:
    """The model's own prefix algebra (``SIPrefixes``), exposed on the
    table: symbols the stdlib never NAMES (``mg``) decompose through its
    ``UnitPrefix`` declarations -- model-derived, never invented."""

    def test_prefix_factors_come_from_the_model(self):
        # SIPrefixes.sysml: milli's conversionFactor is 1E-3, keyed on
        # both the declared name and the definitional symbol member
        prefixes = U.standard_unit_table().prefixes
        assert prefixes["m"] == pytest.approx(1e-3)
        assert prefixes["milli"] == pytest.approx(1e-3)
        assert prefixes["Ki"] == 1024.0  # the binary family rides along

    def test_mg_decomposes_to_milli_gram(self):
        splits = U.standard_unit_table().prefix_splits("mg")
        assert len(splits) == 1
        key, factor, base = splits[0]
        assert key == "m"
        assert factor == pytest.approx(1e-3)
        assert base.qname == "SI::gram"

    def test_named_units_are_never_decomposed(self):
        # 'mm' IS SI::millimetre: a name the model chose always wins
        assert U.standard_unit_table().prefix_splits("mm") == []

    def test_unknown_symbols_do_not_decompose(self):
        assert U.standard_unit_table().prefix_splits("xyz") == []

    def test_offset_scale_bases_do_not_compose(self):
        # a prefix on an interval scale is not the model's
        # ConversionByPrefix pattern (linear references only)
        assert U.standard_unit_table().prefix_splits("m\u00b0C") == []

    def test_ambiguous_decompositions_list_every_candidate(self):
        # a user package naming 'am' makes 'dam' genuinely ambiguous:
        # deci-am vs deca-m -- both come back, the caller refuses
        model = longeron.loads("""
            package Arms {
                private import MeasurementReferences::*;
                attribute <am> armspan : LengthUnit {
                    :>> unitConversion : ConversionByConvention {
                        :>> referenceUnit = SI::m;
                        :>> conversionFactor = 0.7;
                    }
                }
            }
        """)
        splits = U.unit_table(model).prefix_splits("dam")
        assert {(key, base.qname) for key, _, base in splits} == {
            ("d", "Arms::armspan"),
            ("da", "SI::metre"),
        }

    def test_model_prefixes_ride_along_on_absorb(self):
        model = longeron.loads("package Empty {}")
        assert U.unit_table(model).prefixes["milli"] == pytest.approx(1e-3)


class TestRegistry:
    """User-registerable overrides and foreign unit packages."""

    def test_register_unit_override(self, clean_registry):
        info = U.register_unit(
            "MyUnits::furlong",
            dim={"m": 1},
            factor=201.168,
            symbol="fur",
            aliases=("furlongs",),
        )
        table = U.standard_unit_table()
        assert table.lookup("MyUnits::furlong") is info
        assert table.lookup("fur") is info
        assert table.lookup("furlongs") is info
        assert info.dim == dim_of("m").dim

    def test_register_unit_log_scale(self, clean_registry):
        info = U.register_unit("MyUnits::dBsm", dim={"m": 2}, scale="log", symbol="dBsm")
        assert U.standard_unit_table().lookup("dBsm") is info
        assert info.scale == "log"

    def test_override_wins_over_derived_entries(self, clean_registry):
        stock = U.standard_unit_table().lookup("min")
        assert stock is not None and stock.factor == 60.0
        override = U.register_unit("SI::minute", dim={"s": 1}, factor=61.0, symbol="min")
        assert U.standard_unit_table().lookup("min") is override
        assert U.standard_unit_table().lookup("SI::minute") is override

    def test_foreign_package_derives_with_no_mapping_table(self):
        # the ratified foreign-packages ruling: a package shaped like the
        # stdlib (typed units, ConversionByConvention against SI) derives
        # vectors and factors from its own algebra
        model = longeron.loads("""
            package USMass {
                private import MeasurementReferences::*;
                private import SI::*;
                attribute <lbm> pound : MassUnit {
                    :>> unitConversion : ConversionByConvention {
                        :>> referenceUnit = kg;
                        :>> conversionFactor = 0.45359237;
                    }
                }
                attribute <lbf> 'pound force' : ForceUnit = lbm * 'm/s²' {
                    :>> unitConversion : ConversionByConvention {
                        :>> referenceUnit = N;
                        :>> conversionFactor = 4.448222;
                    }
                }
            }
        """)
        table = U.derive_units(model, base=U.standard_unit_table())
        pound = table.lookup("lbm")
        assert pound is not None
        assert pound.dim == dim_of("kg").dim
        assert pound.factor == pytest.approx(0.45359237)
        force = table.lookup("lbf")
        assert force is not None
        assert force.dim == dim_of("N").dim
        assert force.factor == pytest.approx(4.448222)

    def test_unit_table_extends_standard_with_the_model(self):
        model = longeron.loads("""
            package Depths {
                private import MeasurementReferences::*;
                attribute <ftm> fathom : LengthUnit {
                    :>> unitConversion : ConversionByConvention {
                        :>> referenceUnit = SI::m;
                        :>> conversionFactor = 1.8288;
                    }
                }
            }
        """)
        table = U.unit_table(model)
        fathom = table.lookup("ftm")
        assert fathom is not None and fathom.factor == pytest.approx(1.8288)
        assert table.lookup("kg") is not None  # the standard table rides along


class TestNoExtraFacade:
    """Facade pieces that need no pint at all."""

    def test_format_quantity_uses_the_declared_display_unit(self):
        assert U.format_quantity(0.254, "SI::m") == "0.254 m"
        assert U.format_quantity(30.0, "min") == "30 min"
        assert U.format_quantity(5200.0, "mAh") == "5.2e+03 mAh"  # unknown: verbatim
        assert U.format_quantity(1.23456, "kg", precision=2) == "1.2 kg"

    def test_om_unit_dialect(self):
        assert U.om_unit("SI::kg") == "kg"
        assert U.om_unit("m/s") == "m * s**-1"
        assert U.om_unit("min") == "min"  # OM knows minutes natively
        assert U.om_unit("°C") == "degC"
        assert U.om_unit("K") == "degK"
        assert U.om_unit("dB") is None  # verified unsupported by OM
        assert U.om_unit("one") is None  # dimensionless stays unitless
        assert U.om_unit("mAh") is None  # unknowns stay unitless

    @pytest.mark.skipif(
        importlib.util.find_spec("openmdao") is None, reason="openmdao not installed"
    )
    def test_om_spellings_are_valid_openmdao_units(self):
        from openmdao.utils.units import valid_units

        for unit in ("kg", "N", "W", "m/s", "min", "h", "°C", "K", "mm", "km/h", "Pa"):
            spelling = U.om_unit(unit)
            assert spelling is not None, unit
            assert valid_units(spelling), f"{unit} -> {spelling}"

    @pytest.mark.skipif(HAVE_PINT, reason="pint installed; MissingExtraError unreachable")
    def test_convert_without_the_extra_raises_missing_extra(self):
        with pytest.raises(MissingExtraError, match=r"longeron\[units\]"):
            U.convert(1.0, "min", "s")
        with pytest.raises(ImportError):  # it is an ImportError too
            U.si_value(1.0, "min")

    @pytest.mark.skipif(HAVE_PINT, reason="pint installed; MissingExtraError unreachable")
    def test_mixed_units_lint_active_without_the_extra(self):
        assert U.units_extra_available() is False


@requires_pint
class TestFacade:
    """The pint-backed boundary tier (runs with the [units] extra)."""

    def test_convert_linear(self):
        assert U.convert(30.0, "min", "s") == pytest.approx(1800.0)
        assert U.convert(1.0, "SI::kg", "g") == pytest.approx(1000.0)
        assert U.convert(100.0, "km/h", "m/s") == pytest.approx(27.7778, rel=1e-4)

    def test_convert_offset_scale(self):
        assert U.convert(25.0, "°C", "K") == pytest.approx(298.15)
        assert U.convert(273.15, "K", "°C") == pytest.approx(0.0)

    def test_convert_log_scale(self):
        assert U.convert(3.0, "dBm", "mW") == pytest.approx(1.995, rel=1e-3)
        assert U.convert(20.0, "dBW", "W") == pytest.approx(100.0)

    def test_si_value(self):
        assert U.si_value(30.0, "min") == pytest.approx(1800.0)
        assert U.si_value(25.0, "°C") == pytest.approx(298.15)
        assert U.si_value(250.0, "mm") == pytest.approx(0.25)

    def test_si_unit(self):
        assert U.si_unit("min") == "s"
        assert U.si_unit("SI::mm") == "m"
        assert U.si_unit("dBm") == "W"

    def test_model_only_units_get_defined_from_the_table(self):
        # 'W⋅h' is the model's spelling; pint accepts the '*' respelling,
        # and table-derived definitions cover anything it would reject
        assert U.si_value(1.0, "W⋅h") == pytest.approx(3600.0)
        assert U.convert(1.0, "W⋅h", "kJ") == pytest.approx(3.6)

    def test_define_passthrough(self):
        U.define("smoot_test = 1.702 * meter = smt")
        assert U.convert(1.0, "smt", "m") == pytest.approx(1.702)

    def test_mixed_units_gate_reports_available(self):
        assert U.units_extra_available() is True

    @pytest.mark.skipif(not HAVE_PINT_PANDAS, reason="pint-pandas not installed")
    def test_with_units_applies_pint_dtypes(self):
        import pandas as pd

        frame = pd.DataFrame({"mass": [1.0, 2.0], "flightTime": [30.0, 45.0]})
        out = U.with_units(frame, {"mass": "kg", "flightTime": "min"})
        assert str(out["mass"].dtype).startswith("pint[")
        seconds = out["flightTime"].pint.to("s")
        assert float(seconds.iloc[0].magnitude) == pytest.approx(1800.0)
        # the original frame stays plain floats
        assert str(frame["mass"].dtype) == "float64"
