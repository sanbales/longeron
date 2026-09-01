"""Object-valued analysis I/O in the OpenMDAO bridge.

The ratified ``docs/design/mdao-objects.md``: entity binding (tier 1,
discrete cases as M0 individuals), interpretation snapshots (result
recording), object-flow conventions (tier 2, M0-keyed payloads +
picklability), the ``FileArtifact`` file boundary (tier 3), and
item-flow wiring derivation (tier 4).
"""

import hashlib
import json
import pickle
from pathlib import Path

import pytest

pytest.importorskip("openmdao")

import longeron
from longeron import m0
from longeron.analysis import AnalysisError, mdao
from longeron.analysis.mdao import FileArtifact

EXAMPLES = Path(__file__).parent.parent / "examples"

#: typed variants (catalog part defs carry the values) -- the shape the
#: interpretation path resolves exactly today
CATALOG = """
package Cat {
    item def Motor {
        attribute mass : Real;
        attribute kv : Real;
    }
    item def EcoM :> Motor {
        attribute mass : Real = 0.03;
        attribute kv : Real = 2400.0;
    }
    item def HeavyM :> Motor {
        attribute mass : Real = 0.09;
        attribute kv : Real = 900.0;
    }
    variation item def MotorChoice :> Motor {
        variant item eco : EcoM;
        variant item heavy : HeavyM;
    }
    item def Prop {
        attribute diameter : Real;
    }
    item def SmallP :> Prop { attribute diameter : Real = 0.08; }
    item def LargeP :> Prop { attribute diameter : Real = 0.12; }
    variation item def PropChoice :> Prop {
        variant item small : SmallP;
        variant item large : LargeP;
    }
    part def Rig {
        part motor : MotorChoice;
        part props : PropChoice[2];
        attribute wire : Real = 0.01;
        attribute total : Real = wire + motor.mass + 2.0 * props.diameter * 0.1;
        attribute speedTerm : Real = motor.kv / 1000.0;
        assert constraint massBudget { total <= 0.1 }
    }
}
"""

#: inline ``:>>`` body redefinitions on typed variants -- the shape the
#: precursors' trades fix (design Q5) makes trustworthy
REDEF_CATALOG = """
package Redef {
    item def Motor {
        attribute mass : Real = 0.05;
        attribute kv : Real = 1000.0;
    }
    variation item def MotorChoice :> Motor {
        variant item light : Motor { :>> mass = 0.03; :>> kv = 2400.0; }
        variant item heavy : Motor { :>> mass = 0.09; :>> kv = 900.0; }
    }
    part def Rig {
        part motor : MotorChoice;
        attribute total : Real = 0.01 + motor.mass;
    }
}
"""


def _variant_bundles_fixed() -> bool:
    """Whether the trades variant-bundle fix (main: 81d8145) is present:
    inline body redefinitions survive into ``VariationPoint`` bundles."""

    from longeron.analysis import trades

    try:
        study = trades.TradeStudy(longeron.loads(REDEF_CATALOG), "Redef::Rig")
        return study.points["motor"].variants.get("light", {}).get("mass") == 0.03
    except Exception:
        return False


#: activates automatically once this branch lands on top of the precursors
requires_variant_bundle_fix = pytest.mark.skipif(
    not _variant_bundles_fixed(),
    reason="awaiting the trades variant-bundle fix (design Q5): variant "
    "body redefinitions must survive into VariationPoint bundles",
)

TOTAL_ECO_SMALL = 0.01 + 0.03 + 2.0 * 0.08 * 0.1
TOTAL_HEAVY_LARGE = 0.01 + 0.09 + 2.0 * 0.12 * 0.1


@pytest.fixture()
def catalog():
    return longeron.loads(CATALOG)


@pytest.fixture()
def rig(catalog):
    build = mdao.build_problem(catalog, "Cat::Rig")
    build.problem.run_model()
    return build


# ---------------------------------------------------------------------------
# tier 1: entity binding
# ---------------------------------------------------------------------------


class TestEntityBinding:
    def test_variation_members_become_discrete_inputs(self, rig):
        assert rig.entities == {"motor": "Cat::MotorChoice", "props": "Cat::PropChoice"}
        # the implicit anonymous interpretation (design Q1): first variants
        assert rig.interpretation is not None
        assert rig.interpretation.selection == {"motor": "eco", "props": "small"}
        assert rig.problem.get_val("total")[0] == pytest.approx(TOTAL_ECO_SMALL)
        assert rig.problem.get_val("massBudget_margin")[0] == pytest.approx(0.1 - TOTAL_ECO_SMALL)
        assert "total" in rig.derived and "speedTerm" in rig.derived
        assert "wire" in rig.independents

    def test_explicit_interpretation_pins_the_case(self, catalog):
        case = m0.interpret(catalog, "Cat::Rig", selection={"motor": "heavy", "props": "large"})
        build = mdao.build_problem(catalog, "Cat::Rig", interpretation=case)
        build.problem.run_model()
        assert build.interpretation is case
        assert build.problem.get_val("total")[0] == pytest.approx(TOTAL_HEAVY_LARGE)
        assert build.problem.get_val("massBudget_margin")[0] < 0.0

    def test_mismatched_interpretation_is_loud(self, catalog):
        other = m0.interpret(catalog, "Cat::EcoM")
        with pytest.raises(AnalysisError, match="cannot seed"):
            mdao.build_problem(catalog, "Cat::Rig", interpretation=other)

    def test_set_val_rebinds_between_runs(self, catalog, rig):
        heavy = m0.interpret(catalog, "Cat::HeavyM").root
        rig.problem.set_val("motor", heavy)
        rig.problem.run_model()
        assert rig.problem.get_val("total")[0] == pytest.approx(TOTAL_ECO_SMALL + 0.06)

    def test_bind_entity_by_qname(self, rig):
        mdao.bind_entity(rig, "motor", "Cat::HeavyM")
        rig.problem.run_model()
        assert rig.problem.get_val("total")[0] == pytest.approx(TOTAL_ECO_SMALL + 0.06)
        assert rig.problem.get_val("speedTerm")[0] == pytest.approx(0.9)

    def test_bind_variant_usage_keeps_body_redefinitions(self):
        model = longeron.loads(REDEF_CATALOG)
        build = mdao.build_problem(model, "Redef::Rig")
        mdao.bind_entity(build, "motor", "Redef::MotorChoice::heavy")
        build.problem.run_model()
        assert build.problem.get_val("total")[0] == pytest.approx(0.01 + 0.09)

    def test_unknown_feature_is_loud(self, rig):
        with pytest.raises(AnalysisError, match="not an entity input"):
            mdao.bind_entity(rig, "engine", "Cat::HeavyM")

    def test_conformance_is_checked(self, catalog, rig):
        with pytest.raises(AnalysisError, match="does not conform"):
            mdao.bind_entity(rig, "motor", "Cat::SmallP")
        with pytest.raises(AnalysisError, match="variation definition"):
            mdao.bind_entity(rig, "motor", "Cat::MotorChoice")

    def test_unpicklable_payload_is_loud(self, catalog, rig):
        poisoned = m0.interpret(catalog, "Cat::HeavyM").root
        poisoned.slots["callback"] = lambda x: x  # a live handle, e.g. an OCC solid
        with pytest.raises(AnalysisError, match="'motor' is not picklable"):
            mdao.bind_entity(rig, "motor", poisoned)

    def test_scalar_models_are_unchanged(self):
        drone = longeron.load(EXAMPLES / "deepscout", cache=False)
        build = mdao.build_problem(drone, "Rotorcraft::QuadCopter")
        build.problem.run_model()
        # no variation points: no interpretation materialized, no entities
        assert build.interpretation is None
        assert build.entities == {}
        assert build.problem.get_val("totalMass")[0] == pytest.approx(1.41)

    def test_interpretation_parity_on_scalar_model(self):
        drone = longeron.load(EXAMPLES / "deepscout", cache=False)
        plain = mdao.build_problem(
            drone, "Rotorcraft::QuadCopter", requirements=("DeepScout::FlightEnvelope",)
        )
        seeded = mdao.build_problem(
            drone,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FlightEnvelope",),
            interpretation=m0.interpret(drone, "Rotorcraft::QuadCopter"),
        )
        assert sorted(seeded.independents) == sorted(plain.independents)
        assert sorted(seeded.derived) == sorted(plain.derived)
        assert seeded.gaps == plain.gaps
        for build in (plain, seeded):
            build.problem.run_model()
        for name in ("totalMass", "hoverMargin_margin", "takeoffMassLimit_margin"):
            assert seeded.problem.get_val(name)[0] == pytest.approx(plain.problem.get_val(name)[0])

    def test_external_binding_with_entity_args_is_rejected(self):
        model = longeron.loads("""
            package P {
                metadata def ExternalAnalysis { attribute component : String; }
                calc def Boost {
                    @ExternalAnalysis { component = "nowhere:Nothing"; }
                    in m : Real;
                }
                item def Motor { attribute mass : Real; }
                item def BigM :> Motor { attribute mass : Real = 2.0; }
                variation item def Choice :> Motor { variant item big : BigM; }
                part def A {
                    part motor : Choice;
                    attribute boosted : Real = Boost(m = motor.mass);
                }
            }
        """)
        with pytest.raises(AnalysisError, match="entity argument"):
            mdao.build_problem(model, "P::A")


# ---------------------------------------------------------------------------
# tier 1: the trades machinery as the discrete-case source
# ---------------------------------------------------------------------------


class TestEntityCases:
    @pytest.fixture()
    def study(self, catalog):
        from longeron.analysis import trades

        return trades.TradeStudy(catalog, "Cat::Rig")

    def test_cartesian_cases_of_individuals(self, study):
        cases = mdao.entity_cases(study)
        assert len(cases) == 4  # 2 motors x 2 props
        names = {name for case in cases for name, _ in case}
        assert names == {"motor", "props"}
        first = dict(cases[0])
        assert isinstance(first["motor"], m0.Individual)
        assert first["motor"].get("mass") == pytest.approx(0.03)
        # stable, position-independent identities
        assert first["motor"].id == "Cat::MotorChoice::eco#0"

    def test_point_subset_and_unknown_point(self, study):
        assert len(mdao.entity_cases(study, "motor")) == 2
        with pytest.raises(AnalysisError, match="unknown variation point"):
            mdao.entity_cases(study, "engine")

    def test_doe_over_entity_cases(self, catalog, study):
        import openmdao.api as om

        build = mdao.build_problem(catalog, "Cat::Rig", setup=False)
        prob = build.problem
        prob.model.add_design_var("motor")
        prob.model.add_design_var("props")
        prob.model.add_objective("total")
        prob.driver = om.DOEDriver(om.ListGenerator(mdao.entity_cases(study)))
        prob.setup()
        prob.run_driver()
        # the last case in declaration order is heavy x large
        assert prob.get_val("total")[0] == pytest.approx(TOTAL_HEAVY_LARGE)

    @requires_variant_bundle_fix
    def test_cases_agree_with_fixed_trade_bundles(self):
        """entity_cases and the FIXED VariationPoint bundles are the same
        currency: variant body redefinitions present in both."""

        from longeron.analysis import trades

        model = longeron.loads(REDEF_CATALOG)
        study = trades.TradeStudy(model, "Redef::Rig")
        for case in mdao.entity_cases(study, "motor"):
            individual = dict(case)["motor"]
            variant = individual.definition.name
            bundle = study.points["motor"].variants[variant]
            assert bundle  # the pre-fix bug: empty bundles
            for attr, value in bundle.items():
                assert individual.get(attr) == pytest.approx(value)

    @requires_variant_bundle_fix
    def test_bound_case_matches_interpreter_exact_metrics(self):
        """A rebound OM case reproduces the trade study's interpreter-exact
        metrics (which the fix computes from the variant usage's body)."""

        from longeron.analysis import trades

        model = longeron.loads(REDEF_CATALOG)
        study = trades.TradeStudy(model, "Redef::Rig")
        build = mdao.build_problem(model, "Redef::Rig")
        mdao.bind_entity(build, "motor", "Redef::MotorChoice::heavy")
        build.problem.run_model()
        exact = study.evaluate({"motor": "heavy"}).metrics["total"]
        assert build.problem.get_val("total")[0] == pytest.approx(exact)


# ---------------------------------------------------------------------------
# result recording: interpretation snapshots
# ---------------------------------------------------------------------------


class TestRecordCase:
    def test_snapshot_carries_outputs_and_input_stays_pristine(self, rig):
        snapshot = mdao.record_case(rig)
        assert snapshot is not rig.interpretation
        assert snapshot.root.id == "Cat::Rig#0"
        assert snapshot.root.slots["total"] == pytest.approx(TOTAL_ECO_SMALL)
        assert snapshot.root.slots["massBudget_margin"] == pytest.approx(0.1 - TOTAL_ECO_SMALL)
        # the input interpretation is untouched (its 'total' slot kept the
        # population-semantics gap; the snapshot got the problem's value)
        assert rig.interpretation.root.slots["total"] is None

    def test_what_if_and_rebinding_are_recorded(self, catalog, rig):
        prob = rig.problem
        prob.set_val("wire", 0.02)
        mdao.bind_entity(rig, "motor", "Cat::HeavyM")
        prob.run_model()
        snapshot = mdao.record_case(rig)
        assert snapshot.root.slots["wire"] == pytest.approx(0.02)
        assert snapshot.root.slots["total"] == pytest.approx(TOTAL_ECO_SMALL + 0.07)
        # the rebound entity is reflected, positional ids stay stable
        assert snapshot.selection["motor"] == "HeavyM"
        assert snapshot.selection["props"] == "small"
        motor = snapshot.root.slots["motor"]
        assert motor.id == "Cat::Rig#0.motor"
        assert motor.get("mass") == pytest.approx(0.09)
        # re-recording never overwrites evidence: a second run, a second case
        prob.set_val("wire", 0.01)
        prob.run_model()
        second = mdao.record_case(rig)
        assert snapshot.root.slots["wire"] == pytest.approx(0.02)
        assert second.root.slots["wire"] == pytest.approx(0.01)

    def test_lazy_interpretation_on_a_scalar_build(self):
        drone = longeron.load(EXAMPLES / "deepscout", cache=False)
        build = mdao.build_problem(drone, "Rotorcraft::QuadCopter")
        build.problem.run_model()
        assert build.interpretation is None  # nothing asked yet
        snapshot = mdao.record_case(build)
        assert build.interpretation is not None  # record_case asked
        assert snapshot.root.id == "Rotorcraft::QuadCopter#0"
        assert snapshot.root.slots["totalMass"] == pytest.approx(1.41)
        # per-index independents land on the population's individuals
        assert snapshot.root.slots["motors"][0].slots["kV"] == pytest.approx(935.0)

    def test_snapshot_is_json_clean(self, rig):
        snapshot = mdao.record_case(rig)
        payload = json.loads(json.dumps(snapshot.to_dict()))
        assert payload["root"]["total"] == pytest.approx(TOTAL_ECO_SMALL)
        assert payload["root"]["motor"]["@id"] == "Cat::Rig#0.motor"

    def test_scoreboard_scores_a_recorded_case(self, rig):
        from longeron.analysis.scoreboard import scoreboard

        snapshot = mdao.record_case(rig)
        scoring = longeron.loads("""
            package Scoring {
                requirement rigValue {
                    requirement light {
                        attribute weight : Real = 1.0;
                        attribute utility : String = "smaller-is-better";
                        attribute ramp0 : Real = 0.2;
                        attribute ramp1 : Real = 0.0;
                        attribute measure : Real = total;
                    }
                }
            }
        """)
        board = scoreboard(scoring, values=mdao.case_values(snapshot))
        assert board.score == pytest.approx(1.0 - TOTAL_ECO_SMALL / 0.2)

    def test_explicit_outputs_and_recording_gaps(self, rig):
        snapshot = mdao.record_case(rig, outputs={"total": 42.0, "no.such_1.slot": 1.0})
        assert snapshot.root.slots["total"] == 42.0
        assert snapshot.root.slots["wire"] == pytest.approx(0.01)  # untouched
        assert any("no.such_1.slot: not recorded" in gap for gap in snapshot.gaps)


# ---------------------------------------------------------------------------
# tier 2: object-flow conventions (M0 keying, picklability)
# ---------------------------------------------------------------------------


class TestObjectFlowConventions:
    def test_m0_keyed_payload_joins_downstream(self, catalog):
        """The individual id is the join key from geometry to results."""

        import openmdao.api as om

        from longeron.analysis import geometry

        airframe = m0.interpret(catalog, "Cat::HeavyM").root

        class BuildGeometry(om.ExplicitComponent):
            def setup(self):
                self.add_discrete_input("airframe", val=airframe)
                self.add_discrete_output("mesh", val={})

            def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):
                entity = discrete_inputs["airframe"]
                mesh = {"unit": "m", "parts": [{"name": "body", "vertices": []}]}
                discrete_outputs["mesh"] = geometry.tag_parts(mesh, {"body": entity.id})

        class Rcs(om.ExplicitComponent):
            def setup(self):
                self.add_discrete_input("mesh", val={})
                self.add_discrete_output("per_part", val={})

            def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):
                # a fresh dict, never a mutation of the (aliased) input
                discrete_outputs["per_part"] = {
                    part["key"]: 0.1 for part in discrete_inputs["mesh"]["parts"]
                }

        prob = om.Problem(reports=False)
        prob.model.add_subsystem("build", BuildGeometry())
        prob.model.add_subsystem("rcs", Rcs())
        prob.model.connect("build.mesh", "rcs.mesh")
        prob.setup()
        prob.run_model()
        assert prob.get_val("rcs.per_part") == {airframe.id: 0.1}

    def test_individuals_pickle_within_the_design_budget(self, catalog):
        individual = m0.interpret(catalog, "Cat::HeavyM").root
        assert len(pickle.dumps(individual)) < 100_000  # design: 3-22 KB


# ---------------------------------------------------------------------------
# tier 3: the file boundary
# ---------------------------------------------------------------------------


class TestFileArtifact:
    def test_write_and_hash_roundtrip(self, tmp_path):
        artifact = mdao.write_artifact(
            tmp_path / "mesh.json", '{"unit": "m"}', media_type="application/json"
        )
        assert Path(artifact.path).read_text() == '{"unit": "m"}'
        assert artifact.sha256 == hashlib.sha256(b'{"unit": "m"}').hexdigest()
        assert mdao.file_artifact(artifact.path, "application/json") == artifact
        assert artifact.to_json() == {
            "path": artifact.path,
            "sha256": artifact.sha256,
            "media_type": "application/json",
        }

    def test_recorder_hook_is_lossless(self, tmp_path, catalog):
        """to_json is the make_serializable seam: artifacts and individuals
        record as their full bundles, never as class-name strings."""

        from openmdao.utils.general_utils import make_serializable

        artifact = mdao.write_artifact(tmp_path / "a.bin", b"payload")
        assert make_serializable(artifact) == artifact.to_json()
        individual = m0.interpret(catalog, "Cat::EcoM").root
        recorded = make_serializable(individual)
        assert recorded["@id"] == "Cat::EcoM#0"
        assert recorded["mass"] == pytest.approx(0.03)

    def test_artifact_component_roundtrip(self, tmp_path):
        import openmdao.api as om

        def write_mesh(payload, directory):
            path = Path(directory) / "mesh.json"
            path.write_text(json.dumps(payload, sort_keys=True))
            return path

        class Producer(om.ExplicitComponent):
            def setup(self):
                self.add_input("span", val=2.5)
                self.add_discrete_output("mesh", val={})

            def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):
                discrete_outputs["mesh"] = {"unit": "m", "span": float(inputs["span"][0])}

        class Consumer(om.ExplicitComponent):
            def setup(self):
                self.add_discrete_input("artifact", val=FileArtifact(path="", sha256=""))
                self.add_output("span_back", val=0.0)

            def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):
                artifact = discrete_inputs["artifact"]
                data = Path(artifact.path).read_bytes()  # ExternalCodeComp pattern
                assert hashlib.sha256(data).hexdigest() == artifact.sha256
                outputs["span_back"] = json.loads(data)["span"]

        prob = om.Problem(reports=False)
        prob.model.add_subsystem("producer", Producer())
        prob.model.add_subsystem(
            "writer",
            mdao.artifact_component(write_mesh, tmp_path, media_type="application/json"),
        )
        prob.model.add_subsystem("consumer", Consumer())
        prob.model.connect("producer.mesh", "writer.payload")
        prob.model.connect("writer.artifact", "consumer.artifact")
        prob.setup()
        prob.run_model()
        assert prob.get_val("consumer.span_back")[0] == pytest.approx(2.5)
        first = prob.get_val("writer.artifact")
        prob.run_model()
        # same payload, same hash: the caching identity
        assert prob.get_val("writer.artifact").sha256 == first.sha256

    def test_writer_must_produce_a_file(self, tmp_path):
        import openmdao.api as om

        comp = mdao.artifact_component(
            lambda payload, directory: Path(directory) / "never_written", tmp_path
        )
        prob = om.Problem(reports=False)
        prob.model.add_subsystem("writer", comp)
        prob.setup()
        with pytest.raises(AnalysisError, match="not a file"):
            prob.run_model()


# ---------------------------------------------------------------------------
# tier 4: item-flow wiring derivation
# ---------------------------------------------------------------------------

FLOW_MODEL = """
package P {
    item def MeshModel;
    item def FineMesh :> MeshModel;
    item def Other;
    action def BuildGeometry { in span : Real; out mesh : MeshModel; }
    action def FineBuild { in span : Real; out mesh : FineMesh; }
    action def RcsAnalysis { in mesh : MeshModel; out rcs : Real; }
    part def Uav {
        attribute span = 2.5;
        action build : BuildGeometry;
        action rcs : RcsAnalysis;
        flow of MeshModel from build.mesh to rcs.mesh;
    }
    part def SubUav :> Uav { }
    part def Dangling {
        action a : BuildGeometry;
        flow of MeshModel from a.mesh to nonexistent.pin;
    }
    part def Mismatch {
        action a : BuildGeometry;
        action b : RcsAnalysis;
        flow of Other from a.mesh to b.mesh;
    }
    part def ConformingSubtype {
        action a : FineBuild;
        action b : RcsAnalysis;
        flow of FineMesh from a.mesh to b.mesh;
    }
    part def UnknownPayload {
        action a : BuildGeometry;
        action b : RcsAnalysis;
        flow of Typo from a.mesh to b.mesh;
    }
    part def ScalarFlow {
        action a : RcsAnalysis;
        action b : BuildGeometry;
        flow of Real from a.rcs to b.span;
    }
    part def ScalarMismatch {
        action a : BuildGeometry;
        action b : RcsAnalysis;
        flow of Real from a.mesh to b.mesh;
    }
    part def WrongWay {
        action a : BuildGeometry;
        action b : RcsAnalysis;
        flow of MeshModel from b.mesh to a.mesh;
    }
    part def Ordered {
        action a : BuildGeometry;
        action b : RcsAnalysis;
        succession flow a.mesh to b.mesh;
    }
}
"""


class TestDeriveFlows:
    @pytest.fixture()
    def flow_model(self):
        return longeron.loads(FLOW_MODEL)

    def test_flows_resolve_to_connection_triples(self, flow_model):
        assert mdao.derive_flows(flow_model, "P::Uav") == [
            ("build.mesh", "rcs.mesh", "P::MeshModel")
        ]

    def test_inherited_flows_derive(self, flow_model):
        assert mdao.derive_flows(flow_model, "P::SubUav") == [
            ("build.mesh", "rcs.mesh", "P::MeshModel")
        ]

    def test_dangling_endpoint_is_loud(self, flow_model):
        with pytest.raises(AnalysisError, match=r"'nonexistent\.pin' does not resolve"):
            mdao.derive_flows(flow_model, "P::Dangling")

    def test_payload_mismatch_is_loud(self, flow_model):
        # the same verdict and wording as validate()'s flow-payload-mismatch
        with pytest.raises(AnalysisError, match="incompatible with flow target"):
            mdao.derive_flows(flow_model, "P::Mismatch")

    def test_conforming_subtype_payload_passes(self, flow_model):
        assert mdao.derive_flows(flow_model, "P::ConformingSubtype") == [
            ("a.mesh", "b.mesh", "P::FineMesh")
        ]

    def test_unresolved_payload_stays_silent(self, flow_model):
        # 'only speak when two known things conflict': unknown payload
        # typing wires without a payload verdict (validate() is silent too)
        assert mdao.derive_flows(flow_model, "P::UnknownPayload") == [("a.mesh", "b.mesh", None)]

    def test_scalar_payloads_flow_continuous(self, flow_model):
        assert mdao.derive_flows(flow_model, "P::ScalarFlow") == [("a.rcs", "b.span", "Real")]
        with pytest.raises(AnalysisError, match="incompatible with flow target"):
            mdao.derive_flows(flow_model, "P::ScalarMismatch")

    def test_direction_violation_is_loud(self, flow_model):
        # an mdao-specific strictness: OpenMDAO connects outputs to inputs
        with pytest.raises(AnalysisError, match="not an 'out' parameter"):
            mdao.derive_flows(flow_model, "P::WrongWay")

    def test_succession_flows_are_skipped(self, flow_model):
        assert mdao.derive_flows(flow_model, "P::Ordered") == []

    def test_apply_flows_wires_the_problem(self, flow_model):
        import openmdao.api as om

        class Build(om.ExplicitComponent):
            def setup(self):
                self.add_input("span", val=2.5)
                self.add_discrete_output("mesh", val={})

            def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):
                discrete_outputs["mesh"] = {"span": float(inputs["span"][0])}

        class Rcs(om.ExplicitComponent):
            def setup(self):
                self.add_discrete_input("mesh", val={})
                self.add_output("rcs", val=0.0)

            def compute(self, inputs, outputs, discrete_inputs, discrete_outputs):
                outputs["rcs"] = 0.1 * discrete_inputs["mesh"]["span"]

        prob = om.Problem(reports=False)
        prob.model.add_subsystem("build", Build())
        prob.model.add_subsystem("rcs", Rcs(), promotes_outputs=["rcs"])
        mdao.apply_flows(prob, mdao.derive_flows(flow_model, "P::Uav"))
        prob.setup()
        prob.run_model()
        assert prob.get_val("rcs")[0] == pytest.approx(0.25)

    def test_examples_convention_package(self):
        """The examples-shipped item def FileArtifact (design Q4): flows can
        be typed by the file-boundary convention and derive cleanly."""

        source = (EXAMPLES / "analysis_conventions.sysml").read_text()
        model = longeron.loads(source)
        item = model.find("AnalysisConventions::FileArtifact")
        names = {m.name for m in item.members if getattr(m, "name", None)}
        assert {"path", "sha256", "mediaType"} <= names
        combined = longeron.loads(
            source
            + """
            package Rig {
                private import AnalysisConventions::*;
                action def WriteStep { in recipe : Real; out artifact : FileArtifact; }
                action def RunCfd { in geometry : FileArtifact; out drag : Real; }
                part def Loop {
                    action writer : WriteStep;
                    action solver : RunCfd;
                    flow of FileArtifact from writer.artifact to solver.geometry;
                }
            }
            """
        )
        assert mdao.derive_flows(combined, "Rig::Loop") == [
            ("writer.artifact", "solver.geometry", "AnalysisConventions::FileArtifact")
        ]


# ---------------------------------------------------------------------------
# the mission-catalog integration: the two-level loop's discrete outer layer
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def missions():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


class TestUavIntegration:
    def test_entity_swap_moves_station_minutes(self, missions):
        """The ISR winner mix reproduces IsrPrime's frozen sizing context;
        swapping the motor entity moves the mission answer."""

        case = m0.interpret(
            missions,
            "ScoutMissions::IsrUav",
            selection={
                "airframe": "vtolWing",
                "motors": "mn4006",
                "props": "apc11x55",
                "battery": "liion6s6p",
                "sensor": "zenmuseH20",
                "material": "carbonFiber",
            },
        )
        build = mdao.build_problem(missions, "ScoutMissions::IsrUav", interpretation=case)
        prob = build.problem
        prob.run_model()
        assert sorted(build.entities) == [
            "airframe",
            "battery",
            "material",
            "motors",
            "props",
            "sensor",
        ]
        station_std = float(prob.get_val("stationMinutes")[0])
        assert station_std == pytest.approx(200.35, abs=0.05)  # IsrPrime's freeze
        mdao.bind_entity(build, "motors", "ScoutParts::SunnySkyX4112s")
        prob.run_model()
        station_eco = float(prob.get_val("stationMinutes")[0])
        assert station_eco != pytest.approx(station_std, abs=1.0)
        snapshot = mdao.record_case(build)
        assert snapshot.selection["motors"] == "SunnySkyX4112s"
        assert snapshot.root.slots["stationMinutes"] == pytest.approx(station_eco)
        assert [ind.id for ind in snapshot.root.slots["motors"]] == [
            f"ScoutMissions::IsrUav#0.motors#{i}" for i in range(4)
        ]
        # roll-ups run over the recorded population (4 x SunnySkyX4112s)
        assert snapshot.rollup("sum(motors.mass)") == pytest.approx(4 * 0.183)
