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
        prob.model.add_subsystem("hover",
                                 mdao.calc_component(interp, "Drone::HoverTime"))
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
    build = mdao.build_problem(drone, "Drone::QuadCopter",
                               requirements=("Drone::FlightEnvelope",))
    build.problem.run_model()
    return build


class TestBuildProblem:
    def test_part_tree_evaluates(self, build):
        assert build.problem.get_val("totalMass")[0] == pytest.approx(1.24)
        assert build.problem.get_val("chassis.mass")[0] == pytest.approx(0.42)

    def test_constraint_margins(self, build):
        p = build.problem
        assert p.get_val("takeoffMassLimit_margin")[0] == pytest.approx(0.26)
        assert p.get_val("canHover_margin")[0] == pytest.approx(
            36.0 - 1.24 * 9.81)

    def test_requirement_margin(self, build):
        # ThrustToWeight(36, 1.24) - 1.8, computed through the calc def
        expected = 36.0 / (1.24 * 9.81) - 1.8
        assert build.problem.get_val("hoverMargin_margin")[0] == \
            pytest.approx(expected)
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


class TestOptimization:
    def test_maximize_payload(self, drone):
        build = mdao.build_problem(drone, "Drone::QuadCopter", setup=False,
                                   requirements=("Drone::FlightEnvelope",))
        mdao.add_optimization(build, objective="payloadMass",
                              design_vars={"payloadMass": (0.0, 3.0)},
                              maximize=True)
        p = build.problem
        p.setup()
        p.set_val("payloadMass", 0.1)
        result = p.run_driver()
        assert result.success
        # takeoffMassLimit binds: totalMass = 1.04 + payload <= 1.5
        assert p.get_val("payloadMass")[0] == pytest.approx(0.46, abs=1e-6)
        assert p.get_val("totalMass")[0] == pytest.approx(1.5, abs=1e-6)
