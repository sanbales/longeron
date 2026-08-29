"""Spike tests: variation/variant catalogs -> CP-SAT architecture trades."""

from itertools import pairwise
from pathlib import Path

import pytest

pytest.importorskip("ortools")

import longeron
from longeron.analysis import trades

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def catalog():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def study(catalog):
    return trades.TradeStudy(catalog, "ScoutSizing::TradeQuad")


class TestModelIntrospection:
    def test_variation_points(self, study):
        assert set(study.points) == {"motors", "props", "battery", "esc"}
        assert study.points["motors"].count == 4
        assert set(study.points["motors"].variants) == {"emax2306", "tmotorF60", "sunnySky2212"}
        assert study.points["motors"].variants["emax2306"]["mass"] == 0.033

    def test_derived_attributes(self, study):
        assert [n for n, _ in study.derived_order] == [
            "totalMass",
            "totalCost",
            "totalThrust",
            "hoverMinutes",
        ]

    def test_constraints_found(self, study):
        assert "cellMatch" in study.constraint_names
        assert "enduranceReq" in study.constraint_names


class TestEnumeration:
    def test_feasible_count(self, study):
        archs = study.enumerate()
        # hand check: tmotorF60 fails endurance; emax needs esc45 + 5" props;
        # sunnySky lifts only with the 10" apc1045 (a 5" prop on the 920
        # rpm/V cruiser makes ~1 N/rotor) and takes either ESC -> 2 + 2 of 54
        assert len(archs) == 4
        assert all(a.verified for a in archs)
        motors = {a.selection["motors"] for a in archs}
        assert motors == {"emax2306", "sunnySky2212"}
        # thrust is motor x prop: every sunnySky mix flies the big slow-fly
        assert all(
            a.selection["props"] == "apc1045"
            for a in archs
            if a.selection["motors"] == "sunnySky2212"
        )

    def test_compatibility_rules_hold(self, study):
        for a in study.enumerate():
            if a.selection["motors"] == "emax2306":
                assert a.selection["esc"] == "esc45"  # escCurrent
                assert a.selection["battery"] == "lipo4s1500"  # cellMatch
                assert a.selection["props"] != "apc1045"  # propFit (10" > 5.1")

    def test_exact_metrics(self, study):
        archs = {tuple(sorted(a.selection.items())): a for a in study.enumerate()}
        key = tuple(
            sorted(
                {
                    "motors": "sunnySky2212",
                    "props": "apc1045",
                    "battery": "lipo3s2200",
                    "esc": "esc20",
                }.items()
            )
        )
        a = archs[key]
        assert a.metrics["totalCost"] == pytest.approx(122.0)
        assert a.metrics["totalMass"] == pytest.approx(1.019)
        assert a.metrics["hoverMinutes"] == pytest.approx(15.0)
        # thrust through the motor x prop parametric: 4 * kt * term * d^4
        assert a.metrics["totalThrust"] == pytest.approx(4.0 * 0.1 * 0.0083 * 10.0**4)


class TestOptimization:
    def test_minimize_cost(self, study):
        best = study.minimize("totalCost")
        assert best is not None
        assert best.metrics["totalCost"] == pytest.approx(122.0)
        assert best.selection["motors"] == "sunnySky2212"
        assert best.selection["esc"] == "esc20"

    def test_maximize_endurance(self, study):
        best = study.maximize("hoverMinutes")
        assert best is not None
        assert best.metrics["hoverMinutes"] == pytest.approx(15.0)

    def test_pareto_front(self, study):
        front = trades.pareto(
            study.enumerate(), minimize=("totalCost", "totalMass"), maximize=("hoverMinutes",)
        )
        picks = {(a.selection["motors"], a.selection["props"], a.selection["esc"]) for a in front}
        assert ("sunnySky2212", "apc1045", "esc20") in picks  # cheapest
        assert ("emax2306", "hq5x43", "esc45") in picks  # lightest
        assert len(front) == 2

    def test_pareto_two_objective_cost_hover_front(self, study):
        """Regression: the 2D (min cost, max hover) front of the catalog.

        The cheapest feasible mix also hovers longest, so the cost-hover
        front is a *single* point -- the $122 cruiser.  The 0.9 kg racer
        is Pareto-optimal only once mass counts as a third objective; a
        3-objective front projected onto these two axes would wrongly
        include it (that projection was notebook 07's original bug).
        """

        archs = study.enumerate()
        front = trades.pareto(archs, minimize=("totalCost",), maximize=("hoverMinutes",))

        def dominates(b, a):  # brute-force weak dominance cross-check
            return (
                b.metrics["totalCost"] <= a.metrics["totalCost"]
                and b.metrics["hoverMinutes"] >= a.metrics["hoverMinutes"]
            ) and (
                b.metrics["totalCost"] < a.metrics["totalCost"]
                or b.metrics["hoverMinutes"] > a.metrics["hoverMinutes"]
            )

        brute = [a for a in archs if not any(dominates(b, a) for b in archs)]
        key = lambda a: tuple(sorted(a.selection.items()))  # noqa: E731
        assert {key(a) for a in front} == {key(a) for a in brute}
        assert len(front) == 1
        assert front[0].selection == {
            "motors": "sunnySky2212",
            "props": "apc1045",
            "battery": "lipo3s2200",
            "esc": "esc20",
        }
        assert front[0].metrics["totalCost"] == pytest.approx(122.0)
        assert front[0].metrics["hoverMinutes"] == pytest.approx(15.0)

    def test_pareto_keeps_equal_key_duplicates(self):
        a = trades.Architecture({"m": "a"}, {"cost": 1.0, "hover": 5.0})
        b = trades.Architecture({"m": "b"}, {"cost": 1.0, "hover": 5.0})
        c = trades.Architecture({"m": "c"}, {"cost": 2.0, "hover": 4.0})
        front = trades.pareto([a, b, c], minimize=("cost",), maximize=("hover",))
        assert front == [a, b]  # ties survive; c is dominated

    def test_pareto_weak_dominance(self):
        a = trades.Architecture({"m": "a"}, {"cost": 1.0, "hover": 5.0})
        d = trades.Architecture({"m": "d"}, {"cost": 1.0, "hover": 6.0})
        front = trades.pareto([a, d], minimize=("cost",), maximize=("hover",))
        assert front == [d]  # equal on cost, better on hover: dominates


class TestExplainability:
    def test_feasible_has_no_core(self, study):
        assert study.explain() == []

    def test_infeasible_names_conflict(self, catalog):
        picnic = trades.TradeStudy(catalog, "ScoutSizing::PicnicQuad")
        assert picnic.enumerate() == []
        core = picnic.explain()
        assert core  # a sufficient subset is reported...
        assert "longEndurance" in core  # ...naming the impossible requirement


class TestErrors:
    def test_no_variation_points(self, catalog):
        with pytest.raises(longeron.analysis.AnalysisError):
            trades.TradeStudy(catalog, "ScoutSizing::Emax2306")

    def test_unknown_metric(self, study):
        with pytest.raises(longeron.analysis.AnalysisError):
            study.minimize("nope")


class TestExactEvaluation:
    """evaluate()/all_architectures() need only the interpreter."""

    def test_evaluate_feasible_mix(self, study):
        arch = study.evaluate(
            {"motors": "sunnySky2212", "props": "apc1045", "battery": "lipo3s2200", "esc": "esc20"}
        )
        assert arch.verified
        assert arch.metrics["totalCost"] == pytest.approx(122.0)

    def test_evaluate_mismatched_motor_prop_mix(self, study):
        # the point of the motor x prop split: a cruiser motor swinging a
        # 5" racing prop produces ~1 N per rotor and fails thrustMargin,
        # where the old per-motor thrust rating called it feasible
        arch = study.evaluate(
            {"motors": "sunnySky2212", "props": "hq5x43", "battery": "lipo3s2200", "esc": "esc20"}
        )
        assert not arch.verified
        assert "thrustMargin" in arch.violations
        assert arch.metrics["totalThrust"] == pytest.approx(4.0 * 0.21 * 0.0083 * 5.0**4)

    def test_evaluate_infeasible_mix(self, study):
        arch = study.evaluate(
            {"motors": "tmotorF60", "props": "hq5x43", "battery": "lipo6s1300", "esc": "esc45"}
        )
        assert not arch.verified  # fails enduranceReq (4.875 min)
        assert arch.metrics["hoverMinutes"] == pytest.approx(4.875)

    def test_evaluate_validates_selection(self, study):
        with pytest.raises(longeron.analysis.AnalysisError):
            study.evaluate({"motors": "emax2306"})  # missing points
        with pytest.raises(longeron.analysis.AnalysisError):
            study.evaluate(
                {"motors": "nope", "props": "hq5x43", "battery": "lipo4s1500", "esc": "esc45"}
            )
        with pytest.raises(longeron.analysis.AnalysisError):
            study.evaluate(
                {
                    "motors": "emax2306",
                    "props": "hq5x43",
                    "battery": "lipo4s1500",
                    "esc": "esc45",
                    "extra": "x",
                }
            )

    def test_all_architectures_is_the_candidate_space(self, study):
        archs = study.all_architectures()
        assert len(archs) == 54  # 3 * 3 * 3 * 2
        feasible = [a for a in archs if a.verified]
        assert len(feasible) == 4  # matches enumerate()
        enumerated = {tuple(sorted(a.selection.items())) for a in study.enumerate()}
        assert {tuple(sorted(a.selection.items())) for a in feasible} == enumerated


MINI_CATALOG = """
package MiniCatalog {
    part def Widget { attribute factor : Real; attribute cost : Real; }
    part def SmallW :> Widget { attribute factor : Real = 2.0; attribute cost : Real = 1.0; }
    part def BigW :> Widget { attribute factor : Real = 5.0; attribute cost : Real = 4.0; }
    part def Gadget { attribute factor : Real; attribute cost : Real; }
    part def SlowG :> Gadget { attribute factor : Real = 1.0; attribute cost : Real = 2.0; }
    part def FastG :> Gadget { attribute factor : Real = 3.0; attribute cost : Real = 6.0; }
    variation part def WidgetChoice :> Widget {
        variant part smallW : SmallW;
        variant part bigW : BigW;
    }
    variation part def GadgetChoice :> Gadget {
        variant part slowG : SlowG;
        variant part fastG : FastG;
    }
    part def Rig {
        part widget : WidgetChoice;
        part gadget : GadgetChoice;
        attribute power : Real = widget.factor * gadget.factor;
        attribute cost : Real = widget.cost + gadget.cost;
        constraint feasible { (power >= 6.0 and cost <= 10.0) or cost <= 3.5 }
    }
}
"""


class TestVariableProductsAndNestedLogic:
    """var*var multiplication and nested and/or reification in CP-SAT.

    Hand enumeration of the 4 combos:
      smallW+slowG: power  2, cost  3 -> feasible via 'cost <= 3.5'
      smallW+fastG: power  6, cost  7 -> feasible via the and-arm
      bigW+slowG:   power  5, cost  6 -> INFEASIBLE (both arms fail)
      bigW+fastG:   power 15, cost 10 -> feasible via the and-arm
    Swapping and<->or in either position changes the feasible count.
    """

    @pytest.fixture(scope="class")
    def rig(self):
        return trades.TradeStudy(longeron.loads(MINI_CATALOG), "MiniCatalog::Rig")

    def test_feasible_set(self, rig):
        archs = rig.enumerate()
        assert all(a.verified for a in archs)
        combos = {(a.selection["widget"], a.selection["gadget"]) for a in archs}
        assert combos == {("smallW", "slowG"), ("smallW", "fastG"), ("bigW", "fastG")}

    def test_variable_product_metric_is_exact(self, rig):
        archs = {(a.selection["widget"], a.selection["gadget"]): a for a in rig.enumerate()}
        assert archs[("bigW", "fastG")].metrics["power"] == pytest.approx(15.0)
        assert archs[("smallW", "slowG")].metrics["power"] == pytest.approx(2.0)

    def test_optimize_over_the_product(self, rig):
        best = rig.maximize("power")
        assert best is not None
        assert best.selection == {"widget": "bigW", "gadget": "fastG"}
        cheapest = rig.minimize("cost")
        assert cheapest.selection == {"widget": "smallW", "gadget": "slowG"}


BODY_CATALOG = """
package BodyCatalog {
    item def Motor { attribute mass : Real = 0.040; attribute cost : Real = 10.0; }
    variation item def MotorChoice :> Motor {
        variant item light : Motor {
            :>> mass = 0.025;
            :>> cost = 18.0;
        }
        variant item heavy : Motor {
            :>> mass = 0.055;
        }
        variant item stock : Motor;
    }
    part def Quad {
        item motors : MotorChoice [4];
        attribute totalMass : Real = 4.0 * motors.mass;
        attribute totalCost : Real = 4.0 * motors.cost;
        assert constraint massOk { totalMass <= 0.2 }
    }
}
"""


class TestVariantBodyRedefinitions:
    """A variant's own body overrides survive into its bundle.

    ``variant item light : Motor { :>> mass = 0.025; }`` must enumerate
    with 0.025, not the type's 0.040 -- instantiating the variant's *type*
    dropped the body redefinitions and silently zeroed such catalogs
    (docs/design/mdao-objects.md, Q5).
    """

    @pytest.fixture(scope="class")
    def quad(self):
        return trades.TradeStudy(longeron.loads(BODY_CATALOG), "BodyCatalog::Quad")

    def test_body_redefinitions_survive_into_bundles(self, quad):
        variants = quad.points["motors"].variants
        assert variants["light"] == {"mass": 0.025, "cost": 18.0}
        # partial body: the redefined slot overrides, the rest inherits
        assert variants["heavy"] == {"mass": 0.055, "cost": 10.0}

    def test_typed_variant_without_body_keeps_type_defaults(self, quad):
        assert quad.points["motors"].variants["stock"] == {"mass": 0.040, "cost": 10.0}

    def test_enumerate_uses_body_values(self, quad):
        archs = {a.selection["motors"]: a for a in quad.enumerate()}
        assert set(archs) == {"light", "stock"}  # heavy: 0.22 > 0.2
        assert all(a.verified for a in archs.values())
        assert archs["light"].metrics["totalMass"] == pytest.approx(0.1)
        assert archs["light"].metrics["totalCost"] == pytest.approx(72.0)
        assert archs["stock"].metrics["totalMass"] == pytest.approx(0.16)

    def test_interpreter_reverification_sees_body_values(self, quad):
        heavy = quad.evaluate({"motors": "heavy"})
        assert heavy.metrics["totalMass"] == pytest.approx(0.22)
        assert heavy.metrics["totalCost"] == pytest.approx(40.0)  # inherited cost
        assert not heavy.verified
        assert heavy.violations == ["massOk"]


MINI_CATALOG_2 = """
package Mini2 {
    part def Widget { attribute factor : Real; attribute cost : Real; }
    part def SmallW :> Widget { attribute factor : Real = 2.0; attribute cost : Real = 1.0; }
    part def BigW :> Widget { attribute factor : Real = 5.0; attribute cost : Real = 4.0; }
    variation part def WidgetChoice :> Widget {
        variant part smallW : SmallW;
        variant part bigW : BigW;
    }
    part def Rig2 {
        part widget : WidgetChoice;
        attribute margin : Real = 10.0 [kg] - widget.cost;
        attribute neg : Real = -widget.factor;
        constraint posMargin { not (margin < 6.5) }
        constraint always { 1.0 < 2.0 }
    }
    part def Rig3 {
        part widget : WidgetChoice;
        constraint impossible { 1.0 > 2.0 }
    }
    part def Rig4 {
        part widget : WidgetChoice;
        attribute broken : Real = widget.factor / 0.0;
        constraint c { broken >= 0.0 }
    }
}
"""


class TestEncodingEdges:
    @pytest.fixture(scope="class")
    def mini2(self):
        return longeron.loads(MINI_CATALOG_2)

    def test_negated_comparison_subtraction_and_units(self, mini2):
        # not(margin < 6.5): smallW margin 9.0 passes, bigW margin 6.0 fails;
        # flipping the not-encoding would invert the feasible set
        rig = trades.TradeStudy(mini2, "Mini2::Rig2")
        archs = rig.enumerate()
        assert [a.selection for a in archs] == [{"widget": "smallW"}]
        assert archs[0].metrics["margin"] == pytest.approx(9.0)
        assert archs[0].metrics["neg"] == pytest.approx(-2.0)  # unary minus
        assert str(archs[0]) == "[widget=smallW] margin=9, neg=-2"

    def test_statically_false_constraint_empties_the_space(self, mini2):
        rig = trades.TradeStudy(mini2, "Mini2::Rig3")
        assert rig.enumerate() == []

    def test_division_by_constant_zero_is_rejected(self, mini2):
        rig = trades.TradeStudy(mini2, "Mini2::Rig4")
        with pytest.raises(longeron.analysis.AnalysisError, match="division by constant zero"):
            rig.enumerate()

    def test_non_part_assembly_rejected(self, mini2):
        with pytest.raises(longeron.analysis.AnalysisError, match="is not a part definition"):
            trades.TradeStudy(mini2, "Mini2")


POWER_CATALOG = """
package PowerCatalog {
    part def Prop { attribute d : Real; }
    part def Small :> Prop { attribute d : Real = 2.0; }
    part def Big :> Prop { attribute d : Real = 3.0; }
    variation part def PropChoice :> Prop {
        variant part small : Small;
        variant part big : Big;
    }
    part def Rig {
        part prop : PropChoice;
        attribute quartic : Real = 0.5 * prop.d ** 4.0;
        constraint fits { quartic <= 41.0 }
    }
    part def BadRig {
        part prop : PropChoice;
        attribute root : Real = prop.d ** 0.5;
        constraint c { root >= 0.0 }
    }
}
"""


class TestConstantExponent:
    """`d ** 4.0` unrolls to exact fixed-point multiplication; anything
    that is not a constant non-negative integer exponent is refused."""

    @pytest.fixture(scope="class")
    def power(self):
        return longeron.loads(POWER_CATALOG)

    def test_integer_exponent_unrolls_exactly(self, power):
        rig = trades.TradeStudy(power, "PowerCatalog::Rig")
        archs = {a.selection["prop"]: a for a in rig.enumerate()}
        assert set(archs) == {"small", "big"}
        assert archs["small"].metrics["quartic"] == pytest.approx(8.0)
        assert archs["big"].metrics["quartic"] == pytest.approx(40.5)

    def test_fractional_exponent_is_refused(self, power):
        rig = trades.TradeStudy(power, "PowerCatalog::BadRig")
        with pytest.raises(longeron.analysis.AnalysisError, match="exponent"):
            rig.enumerate()


CALC_CATALOG = """
package CalcCatalog {
    calc def Momentum {
        in massKg : Real;
        in speed : Real = 10.0;
        return : Real = massKg * speed;
    }
    calc def Padded {
        in raw : Real;
        in floorVal : Real;
        return : Real = max(raw, floorVal) + Momentum(massKg = 0.1);
    }
    calc def Looper {
        in x : Real;
        return : Real = Looper(x = x);
    }
    part def Wheel { attribute mass : Real; attribute grip : Real; }
    part def LightW :> Wheel { attribute mass : Real = 1.5; attribute grip : Real = 3.0; }
    part def HeavyW :> Wheel { attribute mass : Real = 4.0; attribute grip : Real = 8.0; }
    variation part def WheelChoice :> Wheel {
        variant part lightW : LightW;
        variant part heavyW : HeavyW;
    }
    part def Cart {
        part wheel : WheelChoice;
        attribute push : Real = Momentum(massKg = wheel.mass, speed = 2.0);
        attribute defaulted : Real = Momentum(wheel.mass);
        attribute padded : Real = Padded(raw = wheel.grip, floorVal = 5.0);
        attribute clipped : Real = min(wheel.grip, 6.0);
        assert constraint pushOk { push <= 6.0 }
    }
    part def LoopCart {
        part wheel : WheelChoice;
        attribute stuck : Real = Looper(x = wheel.mass);
        constraint c { stuck >= 0.0 }
    }
}
"""


class TestCalcInvocationInlining:
    """Calc invocations inline into CP-SAT: named/positional arguments,
    parameter defaults, nested invocations, and native max()/min()."""

    @pytest.fixture(scope="class")
    def cart(self):
        return trades.TradeStudy(longeron.loads(CALC_CATALOG), "CalcCatalog::Cart")

    def test_enumerate_matches_the_interpreter(self, cart):
        got = {a.selection["wheel"] for a in cart.enumerate()}
        want = {a.selection["wheel"] for a in cart.all_architectures() if a.verified}
        assert got == want == {"lightW"}  # heavyW: push 8 > 6

    def test_named_and_positional_and_default_arguments(self, cart):
        arch = cart.evaluate({"wheel": "lightW"})
        assert arch.metrics["push"] == pytest.approx(3.0)  # 1.5 * 2.0
        assert arch.metrics["defaulted"] == pytest.approx(15.0)  # 1.5 * default 10
        best = cart.maximize("defaulted")
        assert best is not None and best.selection == {"wheel": "lightW"}

    def test_nested_invocation_and_max_inside_a_calc(self, cart):
        # Padded = max(grip, 5.0) + Momentum(0.1) = max(grip, 5) + 1
        best = cart.maximize("padded")
        assert best is not None
        assert best.metrics["padded"] == pytest.approx(6.0)  # lightW: max(3,5)+1

    def test_min_encodes_natively(self, cart):
        # heavyW breaks pushOk, so the feasible pool is lightW alone:
        # min(grip 3.0, 6.0) must channel the VARIABLE side through CP-SAT
        best = cart.maximize("clipped")
        assert best is not None
        assert best.selection == {"wheel": "lightW"}
        assert best.metrics["clipped"] == pytest.approx(3.0)

    def test_recursive_invocation_is_refused(self):
        loop = trades.TradeStudy(longeron.loads(CALC_CATALOG), "CalcCatalog::LoopCart")
        with pytest.raises(longeron.analysis.AnalysisError, match="recursive"):
            loop.enumerate()


class TestUavMissionCoverage:
    """The extended mapper against ``examples/deepscout``: the
    shared platform assembly (calc invocations, max(), var*var division)
    now encodes and must agree with the interpreter mix for mix; the
    mission layers' sqrt/pow/conditional physics refuse with a one-line
    verdict naming the innermost unencodable operation."""

    @pytest.fixture(scope="class")
    def uav(self):
        return longeron.load(EXAMPLES / "deepscout", cache=False)

    @pytest.fixture(scope="class")
    def platform(self, uav):
        return trades.TradeStudy(uav, "ScoutMissions::MissionUAV")

    def test_cpsat_agrees_with_the_interpreter_on_the_platform(self, platform):
        """The fixed-point tolerance contract: after the interpreter
        re-verification, CP-SAT's feasible set is EXACTLY the
        interpreter's (no false admits survive, none of the 1280 mixes
        of the crossed catalog is lost to rounding).  The pre-crossing
        platform was 288 mixes / 166 feasible."""

        got = {tuple(sorted(a.selection.items())) for a in platform.enumerate()}
        exact = platform.all_architectures()
        want = {tuple(sorted(a.selection.items())) for a in exact if a.verified}
        assert len(exact) == 8 * 4 * 4 * 5 * 2 == 1280
        assert got == want
        assert len(got) == 434

    def test_optimization_agrees_with_the_interpreter(self, platform):
        best = platform.minimize("baseCost")
        assert best is not None and best.verified
        exact = min(
            (a for a in platform.all_architectures() if a.verified),
            key=lambda a: a.metrics["baseCost"],
        )
        assert best.selection == exact.selection
        assert best.metrics["baseCost"] == pytest.approx(exact.metrics["baseCost"])

    @pytest.mark.parametrize(
        ("assembly", "attribute", "operation"),
        [
            ("IsrUav", "hoverPowerW", "pow(massKg * 9.81, 1.5)"),
            ("InterceptUav", "dashSpeed", "pow"),
            ("LogisticsUav", "outboundPowerW", "conditional"),
        ],
    )
    def test_mission_refusals_name_the_innermost_operation(
        self, uav, assembly, attribute, operation
    ):
        study = trades.TradeStudy(uav, f"ScoutMissions::{assembly}")
        with pytest.raises(longeron.analysis.AnalysisError) as err:
            study.enumerate()
        message = str(err.value)
        assert f"'{attribute}'" in message  # the derived attribute
        assert operation in message  # the innermost unencodable op
        assert "all_architectures" in message  # the exact alternative
        assert len(message) < 260  # a verdict, not an expression dump
        assert "TubeWallForStress" not in message  # encodable parts absent


class TestThrustParametric:
    """The motor x propeller thrust model, across the shipped examples."""

    @pytest.fixture(scope="class")
    def drone_interp(self):
        drone = longeron.load(EXAMPLES / "deepscout", cache=False)
        return longeron.Interpreter(drone)

    def thrust(self, interp, **kwargs):
        return interp.call("DeepScout::PropThrust", **kwargs)

    def test_stock_design_point_matches_the_bench_table(self, drone_interp):
        # the calibrated fit lands on the MT2213 bench table's 850 g
        # (8.34 N) full-throttle point
        stock = self.thrust(drone_interp, kV=935.0, voltage=11.1, diameter=0.254)
        assert stock == pytest.approx(8.324, abs=1e-3)
        assert stock == pytest.approx(0.850 * 9.81, rel=0.02)

    def test_monotonic_in_diameter_over_the_catalog_range(self, drone_interp):
        # 5" .. 12" props at the stock motor: strictly increasing, d^4-fast
        diameters = [n * 0.0254 for n in (5.0, 6.0, 8.0, 10.0, 12.0)]
        values = [self.thrust(drone_interp, kV=920.0, voltage=11.1, diameter=d) for d in diameters]
        assert all(a < b for a, b in pairwise(values))
        assert values[-1] / values[0] == pytest.approx((12.0 / 5.0) ** 4)

    def test_monotonic_in_kv_over_the_catalog_range(self, drone_interp):
        kvs = [700.0, 920.0, 1750.0, 2400.0]
        values = [self.thrust(drone_interp, kV=kv, voltage=11.1, diameter=0.127) for kv in kvs]
        assert all(a < b for a, b in pairwise(values))
        assert values[-1] / values[1] == pytest.approx((2400.0 / 920.0) ** 2)

    def test_catalog_thrust_terms_match_the_parametric(self, catalog, drone_interp):
        # the catalog's per-motor thrustTerm is PropThrust with Ct factored
        # out to the propeller's kt, precomputed to 4 significant digits
        # (PropThrust's own Ct is calibrated to 0.097 -- divide it back out)
        interp = longeron.Interpreter(catalog)
        for motor, kv in (("Emax2306", 2400.0), ("TMotorF60", 1750.0), ("SunnySky2212", 920.0)):
            inst = interp.instantiate(f"ScoutSizing::{motor}")
            expected = (
                self.thrust(drone_interp, kV=kv, voltage=inst.slots["voltage"], diameter=0.0254)
                / 0.097
            )
            assert inst.slots["thrustTerm"] == pytest.approx(expected, rel=5e-3), motor
