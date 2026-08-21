"""Spike tests: SysML part trees / calcs -> OpenMDAO Problems."""

from pathlib import Path

import pytest

pytest.importorskip("openmdao")

import sysml2
from sysml2.analysis import mdao

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def drone():
    return sysml2.load(EXAMPLES / "drone.sysml", cache=False)


class TestCalcComponent:
    def test_calc_as_component(self, drone):
        import openmdao.api as om

        interp = sysml2.Interpreter(drone)
        prob = om.Problem(reports=False)
        prob.model.add_subsystem("hover", mdao.calc_component(interp, "Drone::HoverTime"))
        prob.setup()
        prob.set_val("hover.capacity", 5200.0)
        prob.run_model()
        assert prob.get_val("hover.result")[0] == pytest.approx(26.0)
        # default input (current = 12000.0) was picked up from the model
        assert prob.get_val("hover.current")[0] == pytest.approx(12000.0)

    def test_non_calc_rejected(self, drone):
        interp = sysml2.Interpreter(drone)
        with pytest.raises(sysml2.analysis.AnalysisError):
            mdao.calc_component(interp, "Drone::QuadCopter")


@pytest.fixture(scope="module")
def build(drone):
    build = mdao.build_problem(drone, "Drone::QuadCopter", requirements=("Drone::FlightEnvelope",))
    build.problem.run_model()
    return build


class TestBuildProblem:
    def test_part_tree_evaluates(self, build):
        assert build.problem.get_val("totalMass")[0] == pytest.approx(1.24)
        assert build.problem.get_val("chassis.mass")[0] == pytest.approx(0.42)

    def test_constraint_margins(self, build):
        p = build.problem
        assert p.get_val("takeoffMassLimit_margin")[0] == pytest.approx(0.26)
        assert p.get_val("canHover_margin")[0] == pytest.approx(36.0 - 1.24 * 9.81)

    def test_requirement_margin(self, build):
        # ThrustToWeight(36, 1.24) - 1.8, computed through the calc def
        expected = 36.0 / (1.24 * 9.81) - 1.8
        assert build.problem.get_val("hoverMargin_margin")[0] == pytest.approx(expected)
        assert "FlightEnvelope::hoverMargin" in build.constraints

    def test_what_if_propagates(self, drone):
        build = mdao.build_problem(drone, "Drone::QuadCopter")
        p = build.problem
        p.set_val("payloadMass", 0.9)
        p.run_model()
        assert p.get_val("totalMass")[0] == pytest.approx(1.94)
        assert p.get_val("takeoffMassLimit_margin")[0] == pytest.approx(-0.44)

    def test_bookkeeping(self, build):
        assert "payloadMass" in build.independents
        assert "battery.mass" in build.independents
        assert "totalMass" in build.derived
        assert build.gaps == []


@pytest.fixture(scope="module")
def missions(request):
    import sys

    sys.path.insert(0, str(EXAMPLES))  # 'uav_aero:...' entry points
    request.addfinalizer(lambda: sys.path.remove(str(EXAMPLES)))
    return sysml2.load(EXAMPLES / "uav_missions.sysml", cache=False)


class TestExternalAnalysisBinding:
    """@ExternalAnalysis: SysML declares the contract, the tool computes."""

    def test_annotation_is_read(self, missions):
        calc = missions.find("UavMissions::Propulsion::CruisePower")
        assert mdao.external_binding(calc) == "uav_aero:CruisePowerPolar"
        assert mdao.external_binding(missions.find("UavMissions::Propulsion::HoverPower")) is None

    def test_default_fidelity_is_the_model_body(self, missions):
        build = mdao.build_problem(missions, "UavMissions::IsrPrime")
        build.problem.run_model()
        # first-order body: buildup CdA parasite + induced at 15 m/s
        assert build.problem.get_val("loiterPowerW")[0] == pytest.approx(78.841, abs=0.01)
        assert build.externals == {}

    def test_external_fidelity_swaps_the_component(self, missions):
        build = mdao.build_problem(
            missions, "UavMissions::IsrPrime", fidelity={"CruisePower": "external"}
        )
        build.problem.run_model()
        power = build.problem.get_val("loiterPowerW")[0]
        assert build.externals == {"loiterPowerW": "uav_aero:CruisePowerPolar"}
        assert power == pytest.approx(84.27, abs=0.5)  # Re + stall terms
        # the external output composes with interpreter-backed components
        station = build.problem.get_val("stationMinutes")[0]
        energy = build.problem.get_val("usableEnergyJ")[0]
        assert station == pytest.approx(energy / (power + 22.0) / 60.0, rel=1e-6)

    def test_qualified_fidelity_key(self, missions):
        build = mdao.build_problem(
            missions,
            "UavMissions::IsrPrime",
            fidelity={"UavMissions::Propulsion::CruisePower": "external"},
        )
        assert build.externals

    def test_fidelity_shifts_the_optimum(self, missions):
        """The lo-fi/hi-fi swap study the mechanism exists for."""

        optima = {}
        for name, fidelity in (("model", None), ("external", {"CruisePower": "external"})):
            build = mdao.build_problem(
                missions, "UavMissions::IsrPrime", setup=False, fidelity=fidelity
            )
            mdao.add_optimization(
                build,
                objective="stationMinutes",
                design_vars={"loiterSpeed": (11.0, 24.0)},
                maximize=True,
            )
            build.problem.setup()
            build.problem.set_val("loiterSpeed", 16.0)
            assert build.problem.run_driver().success
            optima[name] = float(build.problem.get_val("loiterSpeed")[0])
        assert optima["model"] == pytest.approx(11.0, abs=1e-3)  # at stall
        assert optima["external"] > 12.0  # the polar backs off the stall

    def test_unknown_fidelity_key_is_loud(self, missions):
        with pytest.raises(sysml2.analysis.AnalysisError, match="never bound"):
            mdao.build_problem(
                missions, "UavMissions::IsrPrime", fidelity={"CruisePowerr": "external"}
            )

    def test_invalid_fidelity_value_is_loud(self, missions):
        with pytest.raises(sysml2.analysis.AnalysisError, match="'model' or 'external'"):
            mdao.build_problem(missions, "UavMissions::IsrPrime", fidelity={"CruisePower": "hifi"})

    def test_contract_mismatch_is_precise(self, missions, monkeypatch):
        import types

        import openmdao.api as om

        class WrongIo(om.ExplicitComponent):
            def setup(self):
                self.add_input("mass", val=1.0)  # not the declared massKg
                self.add_input("speed", val=1.0)
                self.add_output("power", val=0.0)

            def compute(self, inputs, outputs):
                outputs["power"] = 0.0

        fake = types.ModuleType("fake_aero")
        fake.WrongIo = WrongIo
        monkeypatch.setitem(__import__("sys").modules, "fake_aero", fake)
        calc = missions.find("UavMissions::Propulsion::CruisePower")
        annotation = next(m for m in calc.members if type(m).__name__ == "MetadataUsage")
        value = annotation.members[0].value
        monkeypatch.setattr(value.expr, "value", "fake_aero:WrongIo", raising=False)
        with pytest.raises(sysml2.analysis.AnalysisError) as err:
            mdao.build_problem(
                missions, "UavMissions::IsrPrime", fidelity={"CruisePower": "external"}
            )
        message = str(err.value)
        assert "massKg" in message  # names the declared input it lacks
        assert "mass" in message  # and the undeclared one it has

    def test_bodiless_calc_binds_external_by_default(self, monkeypatch):
        import types

        import openmdao.api as om

        class Doubler(om.ExplicitComponent):
            def setup(self):
                self.add_input("x", val=1.0)
                self.add_output("y", val=0.0)
                self.declare_partials("y", "x", method="fd")

            def compute(self, inputs, outputs):
                outputs["y"] = 2.0 * inputs["x"]

        def doubler_factory():  # ':factory_fn' entry points work too
            return Doubler()

        fake = types.ModuleType("fake_tool")
        fake.doubler_factory = doubler_factory
        monkeypatch.setitem(__import__("sys").modules, "fake_tool", fake)
        model = sysml2.loads("""
            package P {
                metadata def ExternalAnalysis {
                    attribute component : String;
                }
                calc def Double {
                    @ExternalAnalysis {
                        component = "fake_tool:doubler_factory"; }
                    in x : Real;
                    return y : Real;
                }
                part def A {
                    attribute base : Real = 4.0;
                    attribute twice : Real = Double(x = base);
                    attribute more : Real = twice + 1.0;
                }
            }
        """)
        build = mdao.build_problem(model, "P::A")
        build.problem.run_model()
        assert build.problem.get_val("twice")[0] == pytest.approx(8.0)
        assert build.problem.get_val("more")[0] == pytest.approx(9.0)
        assert build.externals == {"twice": "fake_tool:doubler_factory"}
        # 'model' fidelity cannot work without a body -- and says so
        with pytest.raises(sysml2.analysis.AnalysisError, match="no body"):
            mdao.build_problem(model, "P::A", fidelity={"Double": "model"})

    def test_nested_external_invocation_is_rejected(self, monkeypatch):
        import types

        import openmdao.api as om

        class Identity(om.ExplicitComponent):
            def setup(self):
                self.add_input("x", val=1.0)
                self.add_output("y", val=0.0)

            def compute(self, inputs, outputs):
                outputs["y"] = inputs["x"]

        fake = types.ModuleType("fake_nested")
        fake.Identity = Identity
        monkeypatch.setitem(__import__("sys").modules, "fake_nested", fake)
        model = sysml2.loads("""
            package P {
                metadata def ExternalAnalysis {
                    attribute component : String;
                }
                calc def Ident {
                    @ExternalAnalysis { component = "fake_nested:Identity"; }
                    in x : Real;
                    return y : Real;
                }
                part def A {
                    attribute base : Real = 4.0;
                    attribute bad : Real = 1.0 + Ident(x = base);
                }
            }
        """)
        with pytest.raises(sysml2.analysis.AnalysisError, match="larger expression"):
            mdao.build_problem(model, "P::A")

    def test_bad_component_specs_are_loud(self, missions):
        import openmdao.api as om

        with pytest.raises(sysml2.analysis.AnalysisError, match=r"module.*attr"):
            mdao._load_component(om, "no-colon")
        with pytest.raises(sysml2.analysis.AnalysisError, match="cannot import"):
            mdao._load_component(om, "definitely_not_a_module:X")
        with pytest.raises(sysml2.analysis.AnalysisError, match="no attribute"):
            mdao._load_component(om, "uav_aero:Nope")
        with pytest.raises(sysml2.analysis.AnalysisError, match="ExplicitComponent"):
            mdao._load_component(om, "uav_aero:RHO")


@pytest.fixture(scope="module")
def grouped(missions):
    build = mdao.build_problem(
        missions, "UavMissions::IsrPrime", requirements=("UavMissions::IsrStation",)
    )
    build.problem.run_model()
    return build


class TestDisciplineGrouping:
    """The SysML package structure IS the N2 grouping: an attribute whose
    value invokes a calc def living in a discipline package lands in an
    OpenMDAO group named after that package (outputs promoted, so flat
    names keep working); calcs beside the part def are shared context
    and stay flat."""

    def test_disciplines_follow_the_calc_packages(self, grouped):
        assert grouped.disciplines == {
            "Aerodynamics": ["dragArea"],
            "Structures": ["sparWall", "sparMassKg"],
            "Propulsion": ["hoverPowerW", "usableEnergyJ", "loiterPowerW"],
            "Performance": ["stationMinutes"],
        }

    def test_components_live_inside_their_groups(self, grouped):
        from openmdao.core.component import Component

        paths = {s.pathname for s in grouped.problem.model.system_iter(recurse=True, typ=Component)}
        assert "Aerodynamics.dragArea_comp" in paths
        assert "Structures.sparWall_comp" in paths
        assert "Propulsion.loiterPowerW_comp" in paths
        assert "Performance.stationMinutes_comp" in paths
        # requirement/constraint margins stay at the system level
        assert "aboveStall_margin_comp" in paths
        assert "IsrStation_stationFloor_margin_comp" in paths

    def test_flat_promoted_names_keep_working(self, grouped):
        p = grouped.problem
        assert p.get_val("stationMinutes")[0] == pytest.approx(147.386, abs=0.01)
        assert p.get_val("dragArea")[0] == pytest.approx(0.019574, abs=1e-6)
        assert p.get_val("massKg")[0] == pytest.approx(5.5528, abs=1e-3)

    def test_external_component_joins_its_discipline(self, missions):
        from openmdao.core.component import Component

        build = mdao.build_problem(
            missions, "UavMissions::IsrPrime", fidelity={"CruisePower": "external"}
        )
        paths = {s.pathname for s in build.problem.model.system_iter(recurse=True, typ=Component)}
        assert "Propulsion.loiterPowerW_ext" in paths
        assert "loiterPowerW" in build.disciplines["Propulsion"]

    def test_shared_context_calcs_stay_flat(self, drone):
        # drone.sysml keeps its calcs beside the parts: no grouping
        build = mdao.build_problem(drone, "Drone::QuadCopter")
        assert build.disciplines == {}


class TestOptimization:
    def test_maximize_payload(self, drone):
        build = mdao.build_problem(
            drone, "Drone::QuadCopter", setup=False, requirements=("Drone::FlightEnvelope",)
        )
        mdao.add_optimization(
            build, objective="payloadMass", design_vars={"payloadMass": (0.0, 3.0)}, maximize=True
        )
        p = build.problem
        p.setup()
        p.set_val("payloadMass", 0.1)
        result = p.run_driver()
        assert result.success
        # takeoffMassLimit binds: totalMass = 1.04 + payload <= 1.5
        assert p.get_val("payloadMass")[0] == pytest.approx(0.46, abs=1e-6)
        assert p.get_val("totalMass")[0] == pytest.approx(1.5, abs=1e-6)
