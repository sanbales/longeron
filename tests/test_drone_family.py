"""The MultiRotor branch of examples/deepscout, end to end.

One abstract MultiRotor, five configurations -- QuadCopter, TriCopter,
HexaCopter, OctoCopter, CoaxX8 -- and the axes they trade: mass, usable
thrust, hover current, endurance, cruise speed, motor-out tolerance,
cost, the payload envelope (which limit binds, and what redundancy
costs in kg), and still-air range.
The tests pin the family matrix (no configuration wins everything), the
N-arm parametric geometry each configuration renders to, the
config-keyed scene seam, the M0 population fan-outs, and the verify
tiers' family-level catches (the quad's motor-out violation, the hexa's
exact payload ceiling, the X8's proven-safe envelope).
"""

import math
from pathlib import Path

import pytest

import longeron
from longeron.analysis import geometry, link, mission3d
from longeron.analysis.grand import drone_scene

EXAMPLES = Path(__file__).parent.parent / "examples"

CONFIGS = ("QuadCopter", "TriCopter", "HexaCopter", "OctoCopter", "CoaxX8")

#: the hand-computed stock design point (same derivation as
#: tests/test_mission3d.py -- the quad's numbers must stay bit-identical)
THRUST_N = 0.097 * 1.225 * (0.75 * 935.0 * 11.1 / 60.0) ** 2.0 * 0.254**4.0
BAY_KG = 0.39 + 0.012 + 0.039 + 0.032 + 0.017 + 0.028 + 0.08 + 0.05
QUAD_MASS = 0.282 + BAY_KG + 4.0 * 0.055 + 4.0 * 0.015 + 0.2

ATLANTA = [
    (33.7813, -84.3833, 350.0),
    (33.7885, -84.3785, 390.0),
    (33.7900, -84.3695, 380.0),
    (33.7838, -84.3690, 360.0),
    (33.7770, -84.3825, 350.0),
]

STOCK = {"prop_diameter_in": 10.0, "motor_mass": 0.055, "battery_mass": 0.39, "esc_mass": 0.012}
STOCK_CAMERA = {
    "x": 0.06,
    "y": 0.0,
    "z": 0.0,
    "azimuth": 0.0,
    "elevation": -15.0,
    "fieldOfView": 50.0,
}


@pytest.fixture(scope="module")
def model():
    return longeron.load(EXAMPLES / "deepscout", cache=False)


@pytest.fixture(scope="module")
def interp(model):
    return longeron.Interpreter(model)


@pytest.fixture(scope="module")
def instances(interp):
    return {name: interp.instantiate(f"Rotorcraft::{name}") for name in CONFIGS}


class TestFamilyMatrix:
    """The model's own numbers: the trade the maintainer asked for."""

    def test_quad_stock_numbers_bit_identical(self, instances):
        # the T2/tutorial pins: adding the family must not move the quad
        quad = instances["QuadCopter"].slots
        assert quad["thrustPerRotor"] == THRUST_N
        assert quad["usableThrust"] == 4.0 * THRUST_N * 0.59
        assert quad["totalMass"] == QUAD_MASS
        assert quad["cruiseTilt"] == 25.0
        assert quad["maxCruiseSpeed"] == pytest.approx(19.972, abs=0.001)
        assert quad["effectiveRotorCount"] == 4.0  # the new attribute is inert

    def test_tricopter_story_unchanged(self, instances):
        tri = instances["TriCopter"].slots
        assert tri["cruiseTilt"] == 11.0  # the yaw-servo authority cap
        assert tri["maxCruiseSpeed"] == pytest.approx(12.43, abs=0.01)
        assert tri["effectiveRotorCount"] * tri["thrustPerRotor"] > tri["totalMass"] * 9.81

    def test_hexa_design_point(self, instances):
        hexa = instances["HexaCopter"].slots
        assert hexa["totalMass"] == pytest.approx(1.758, abs=0.001)
        assert hexa["usableThrust"] == pytest.approx(6.0 * THRUST_N * 0.59)
        assert hexa["hoverCurrent"] == pytest.approx(15.11, abs=0.01)
        assert hexa["maxCruiseSpeed"] == pytest.approx(19.95, abs=0.01)
        assert hexa["motorOutUsableThrust"] == pytest.approx(4.0 * THRUST_N * 0.59)
        assert hexa["totalCost"] == pytest.approx(670.0)

    def test_octo_design_point(self, instances):
        # the flat-8 ring: eight isolated discs, the family's richest
        # motor-out margin, and the price of eight of everything
        octo = instances["OctoCopter"].slots
        assert octo["rotorCount"] == 8.0
        assert octo["effectiveRotorCount"] == 8.0  # no coax wake penalty
        assert octo["totalMass"] == pytest.approx(2.040, abs=0.001)
        assert octo["usableThrust"] == pytest.approx(8.0 * THRUST_N * 0.59)
        assert octo["hoverCurrent"] == pytest.approx(16.32, abs=0.01)
        assert octo["maxCruiseSpeed"] == pytest.approx(20.18, abs=0.01)
        # the balanced six survive the worst failure -- richer than the
        # hexa's balanced four against a lighter craft
        assert octo["motorOutUsableThrust"] == pytest.approx(6.0 * THRUST_N * 0.59)
        assert octo["motorOutUsableThrust"] > octo["totalMass"] * 9.81
        assert octo["totalCost"] == pytest.approx(732.0)  # the family's biggest invoice

    def test_x8_coax_penalty_is_visible(self, instances):
        x8 = instances["CoaxX8"].slots
        assert x8["effectiveRotorCount"] == pytest.approx(7.4)  # 4 + 4 x 0.85
        assert x8["totalMass"] == pytest.approx(1.702, abs=0.001)
        assert x8["usableThrust"] == pytest.approx(7.4 * THRUST_N * 0.59)
        # eight motors draw MORE at hover than the quad's four (13.35 A),
        # despite the lighter per-motor loading: the wake penalty, in amps
        assert x8["hoverCurrent"] == pytest.approx(14.05, abs=0.01)
        assert x8["maxCruiseSpeed"] == pytest.approx(21.08, abs=0.01)
        assert x8["motorOutUsableThrust"] == pytest.approx(6.4 * THRUST_N * 0.59)
        assert x8["totalCost"] == pytest.approx(692.0)

    def test_constraints_hold_for_every_config(self, interp, instances):
        for name, instance in instances.items():
            for result in interp.check(instance):
                assert result.passed, (name, result.name)

    def test_failsafe_verdicts_split_the_family(self, interp, instances):
        verdicts = {
            name: interp.check_requirement("DeepScout::FailSafeHover", subject=inst).satisfied
            for name, inst in instances.items()
        }
        assert verdicts == {
            "QuadCopter": False,  # the balanced pair cannot lift it
            "TriCopter": False,  # no balanced set survives any failure
            "HexaCopter": True,  # flies on the balanced four
            "OctoCopter": True,  # flies on the balanced six, margin to spare
            "CoaxX8": True,  # the pair's survivor keeps the station
        }

    def test_flight_envelope_holds_for_every_config(self, interp, instances):
        for name, instance in instances.items():
            result = interp.check_requirement("DeepScout::FlightEnvelope", subject=instance)
            assert result.satisfied, name

    def test_mission_verdicts(self, interp):
        minutes = {
            name: mission3d.mission_values(
                interp, ATLANTA, ground_alt=300.0, assembly=f"Rotorcraft::{name}"
            )["missionMinutes"]
            for name in CONFIGS
        }
        assert minutes["QuadCopter"] == pytest.approx(4.24, abs=0.01)
        assert minutes["HexaCopter"] == pytest.approx(4.24, abs=0.01)
        assert minutes["OctoCopter"] == pytest.approx(4.20, abs=0.01)
        assert minutes["CoaxX8"] == pytest.approx(4.07, abs=0.01)
        assert minutes["TriCopter"] > 6.0  # the tri busts the budget

    def test_no_config_wins_everything(self, instances):
        """The point of the family: every configuration wins at least
        one axis and loses at least one."""

        slots = {name: inst.slots for name, inst in instances.items()}
        endurance = {n: s["hoverMinutes"] for n, s in slots.items()}
        cost = {n: s["totalCost"] for n, s in slots.items()}
        cruise = {n: s["maxCruiseSpeed"] for n, s in slots.items()}
        max_payload = {n: s["maxPayload"] for n, s in slots.items()}
        rng = {n: s["cruiseRange"] for n, s in slots.items()}
        # the payload a craft can carry THROUGH a motor failure: the
        # failsafe inversion clipped to the admissible envelope
        survivable = {n: min(s["failsafePayload"], s["maxPayload"]) for n, s in slots.items()}
        redundant = {n: s["motorOutUsableThrust"] > s["totalMass"] * 9.81 for n, s in slots.items()}

        winners = {
            "endurance": max(endurance, key=endurance.get),
            "price": min(cost, key=cost.get),
            "cruise": max(cruise, key=cruise.get),
            "payload": max(max_payload, key=max_payload.get),
            "range": max(rng, key=rng.get),
            "survivable payload": max(survivable, key=survivable.get),
        }
        assert winners == {
            "endurance": "QuadCopter",
            "price": "TriCopter",
            # the X8's speed edges the quad's endurance range by 0.06 km
            # -- but the X8 already loses on cost
            "cruise": "CoaxX8",
            "range": "CoaxX8",
            "payload": "HexaCopter",
            # the octo's crown: 0.76 kg through a failure, against the
            # X8's envelope-clipped 0.498 and the hexa's 0.4445
            "survivable payload": "OctoCopter",
        }
        assert redundant == {
            "QuadCopter": False,
            "TriCopter": False,
            "HexaCopter": True,
            "OctoCopter": True,
            "CoaxX8": True,
        }
        # every configuration wins at least one axis...
        assert set(winners.values()) == set(CONFIGS)
        # ...and each winner loses somewhere else
        assert min(endurance, key=endurance.get) == "OctoCopter"
        assert max(cost, key=cost.get) == "OctoCopter"
        assert min(cruise, key=cruise.get) == "TriCopter"
        assert min(rng, key=rng.get) == "TriCopter"
        assert min(max_payload, key=max_payload.get) == "QuadCopter"
        assert min(survivable, key=survivable.get) == "TriCopter"
        losers = {min(endurance, key=endurance.get), max(cost, key=cost.get)}
        assert "OctoCopter" in losers  # eight of everything is not free

    def test_satisfy_edges(self, model):
        from longeron import model as M

        edges = {
            (e.subsets[0], e.by)
            for e in model.find("Rotorcraft").members
            if isinstance(e, M.SatisfyUsage)
        }
        assert ("FailSafeHover", "HexaCopter") in edges
        assert ("FailSafeHover", "OctoCopter") in edges
        assert ("FailSafeHover", "CoaxX8") in edges
        assert ("FailSafeHover", "QuadCopter") not in edges  # the missing edge
        assert ("FailSafeHover", "TriCopter") not in edges
        assert ("mission", "TriCopter") not in edges


class TestPayloadEnvelope:
    """maxPayload, failsafePayload, and the payload-range axis: the
    carrying-capacity numbers the family matrix was missing."""

    def test_which_limit_binds(self, instances):
        # emptyMass backs the stock payload out of the roll-up, and
        # maxPayload is the lesser of the two ceilings
        for name, inst in instances.items():
            s = inst.slots
            assert s["emptyMass"] == pytest.approx(s["totalMass"] - 0.2), name
            assert s["maxPayload"] == min(s["mtowPayload"], s["thrustLimitPayload"]), name
        # the tri runs out of thrust before it runs out of book MTOW;
        # every other envelope is closed by the takeoff-weight limit
        binding = {
            n: "thrust" if i.slots["thrustLimitPayload"] < i.slots["mtowPayload"] else "MTOW"
            for n, i in instances.items()
        }
        assert binding == {
            "QuadCopter": "MTOW",
            "TriCopter": "thrust",
            "HexaCopter": "MTOW",
            "OctoCopter": "MTOW",
            "CoaxX8": "MTOW",
        }

    def test_max_payload_values(self, instances):
        expected = {
            "QuadCopter": 0.290,  # 1.5 kg MTOW - 1.210 kg empty
            "TriCopter": 0.3042,  # 3 x thrust / (1.8 g) - 1.110 kg empty
            "HexaCopter": 0.842,  # 2.4 kg MTOW - 1.558 kg empty
            "OctoCopter": 0.760,  # 2.6 kg allowance - 1.840 kg empty
            "CoaxX8": 0.498,  # 2.0 kg MTOW - 1.502 kg empty
        }
        for name, value in expected.items():
            assert instances[name].slots["maxPayload"] == pytest.approx(value, abs=0.0005), name

    def test_failsafe_payload_prices_redundancy(self, instances):
        fs = {n: i.slots["failsafePayload"] for n, i in instances.items()}
        # negative: the quad and the tri fail motor-out hover even empty
        # (the quad's hunt shrinks its catch to payloadMass = 0.0)
        assert fs["QuadCopter"] < 0.0
        assert fs["TriCopter"] < 0.0
        # the hexa's redundancy price in kg: motor-out flying keeps only
        # 0.44 of its 0.84 kg envelope
        assert fs["HexaCopter"] == pytest.approx(0.4445, abs=0.0005)
        assert fs["HexaCopter"] < instances["HexaCopter"].slots["maxPayload"]
        # the X8 keeps its WHOLE envelope: its motor-out ceiling sits far
        # past the takeoff limit (prove's UNSAT-safe verdict, as algebra)
        assert fs["CoaxX8"] > instances["CoaxX8"].slots["maxPayload"]
        # the flat octo keeps its whole envelope too -- and its envelope
        # is half again the X8's
        assert fs["OctoCopter"] > instances["OctoCopter"].slots["maxPayload"]
        assert fs["OctoCopter"] == pytest.approx(1.164, abs=0.001)

    def test_failsafe_payload_is_the_verdict_boundary(self, interp, instances):
        # FailSafeHover flips exactly at failsafePayload
        edge = instances["HexaCopter"].slots["failsafePayload"]
        below = interp.instantiate("Rotorcraft::HexaCopter", payloadMass=edge - 1e-6)
        above = interp.instantiate("Rotorcraft::HexaCopter", payloadMass=edge + 1e-6)
        assert interp.check_requirement("DeepScout::FailSafeHover", subject=below).satisfied
        assert not interp.check_requirement("DeepScout::FailSafeHover", subject=above).satisfied

    def test_failsafe_payload_agrees_with_hunts_bisected_edge(self, model, instances):
        # the closed-form boundary must agree with verify.hunt's
        # oracle-bisected edge on the same requirement
        pytest.importorskip("hypothesis")
        from longeron.analysis import verify

        report = verify.hunt(
            model,
            "Rotorcraft::HexaCopter",
            requirements=("DeepScout::FailSafeHover",),
            free=("payloadMass",),
            seed=0,
            max_examples=60,
        )
        edge = next(b for b in report.boundaries if "motorOutHover" in b.violated)
        assert instances["HexaCopter"].slots["failsafePayload"] == pytest.approx(
            edge.value, abs=0.001
        )

    def test_x8_envelope_bound_matches_the_proof(self, instances):
        # verify.prove pins the X8's exact envelope bound at 249/500 kg
        # from takeoffMassLimit; the model's mtowPayload IS that bound
        assert instances["CoaxX8"].slots["mtowPayload"] == pytest.approx(249.0 / 500.0)
        assert instances["CoaxX8"].slots["maxPayload"] == pytest.approx(0.498)

    def test_cruise_range_at_reference_payload(self, instances):
        # 20% landing reserve on the pack, the max-cruise draw, and the
        # stock 0.2 kg payload
        expected = {
            "QuadCopter": 19.43,
            "TriCopter": 13.14,
            "HexaCopter": 17.14,
            "OctoCopter": 16.05,
            "CoaxX8": 19.49,
        }
        for name, km in expected.items():
            s = instances[name].slots
            assert s["reserveFraction"] == 0.2
            assert s["cruiseMinutes"] == pytest.approx(
                5200.0 * 0.8 / (s["cruiseCurrent"] * 1000.0) * 60.0
            ), name
            assert s["cruiseRange"] == pytest.approx(km, abs=0.01), name
            assert s["payloadRangeKgKm"] == pytest.approx(0.2 * s["cruiseRange"]), name

    def test_range_falls_as_payload_grows(self, interp, instances):
        # every configuration's payload-range curve is monotone falling
        # (speed rises ~sqrt(mass) at the capped tilt, the draw rises
        # ~mass^1.5, so range goes as 1/mass)
        for name in CONFIGS:
            ceiling = instances[name].slots["maxPayload"]
            ranges = [
                interp.instantiate(f"Rotorcraft::{name}", payloadMass=p).slots["cruiseRange"]
                for p in (0.0, ceiling / 2.0, ceiling)
            ]
            assert ranges[0] > ranges[1] > ranges[2], name

    def test_quad_and_x8_range_curves_cross(self, interp):
        # empty, the lighter quad out-ranges the X8; at the reference
        # payload the X8's faster cruise has already taken the lead
        quad_empty = interp.instantiate("Rotorcraft::QuadCopter", payloadMass=0.0).slots
        x8_empty = interp.instantiate("Rotorcraft::CoaxX8", payloadMass=0.0).slots
        assert quad_empty["cruiseRange"] > x8_empty["cruiseRange"]
        quad_ref = interp.instantiate("Rotorcraft::QuadCopter").slots
        x8_ref = interp.instantiate("Rotorcraft::CoaxX8").slots
        assert x8_ref["cruiseRange"] > quad_ref["cruiseRange"]


class TestFamilyGeometry:
    """N-arm parametric geometry: the maintainer's 3-arm question."""

    def test_arm_angles(self):
        third = math.pi / 3
        assert geometry._arm_angles(3) == [third, -third, math.pi]
        eighth = math.pi / 8
        assert geometry._arm_angles(8)[:2] == [eighth, -eighth]
        assert len(set(geometry._arm_angles(8))) == 8
        assert geometry._arm_angles(4) == [
            math.pi / 4,
            -math.pi / 4,
            3 * math.pi / 4,
            -3 * math.pi / 4,
        ]
        assert geometry._arm_angles(6) == [
            math.pi / 6,
            -math.pi / 6,
            math.pi / 2,
            -math.pi / 2,
            5 * math.pi / 6,
            -5 * math.pi / 6,
        ]
        with pytest.raises(Exception, match="3 arms"):
            geometry._arm_angles(2)

    def test_tricopter_arms_at_120_degrees_with_a_boom(self):
        """The answer to 'are they spaced 120 degrees?': yes -- and the
        rear station rides the longer tail boom."""

        mesh = geometry.drone_geometry(**STOCK, arm_count=3, split_instances=True)
        discs = mesh["discs"]
        assert [d["part"] for d in discs] == ["prop1", "prop2", "prop3"]
        angles = [math.degrees(math.atan2(d["center"][2], d["center"][0])) for d in discs]
        assert angles[0] == pytest.approx(60.0, abs=0.01)  # centres round to 1e-5 m
        assert angles[1] == pytest.approx(-60.0, abs=0.01)
        assert abs(angles[2]) == pytest.approx(180.0, abs=0.01)
        radii = [math.hypot(d["center"][0], d["center"][2]) for d in discs]
        assert radii[0] == pytest.approx(radii[1], rel=1e-4)
        assert radii[2] == pytest.approx(geometry._TRI_BOOM_RATIO * radii[0], rel=1e-3)
        # the tail boom points straight back: -x, zero z
        assert discs[2]["center"][0] < 0
        assert discs[2]["center"][2] == pytest.approx(0.0, abs=1e-9)

    def test_hexa_arms_at_60_degrees_discs_clear(self):
        mesh = geometry.drone_geometry(**STOCK, arm_count=6, split_instances=True)
        discs = mesh["discs"]
        assert len(discs) == 6
        radius = math.hypot(discs[0]["center"][0], discs[0]["center"][2])
        spacing = 10.0 * geometry.IN + 0.02
        # 6 arms: circle radius equals the adjacent spacing exactly
        assert radius == pytest.approx(spacing, abs=2e-5)  # centres round to 1e-5 m
        assert geometry.disc_overlap(mesh, engine="mesh") == 0.0

    def test_derived_footprints_order_the_family(self):
        def spans(**kw):
            mesh = geometry.drone_geometry(**STOCK, **kw)
            (x0, _y0, z0), (x1, _y1, z1) = mesh["bounds"]
            return x1 - x0, z1 - z0

        tri, quad = spans(arm_count=3), spans()
        hexa, x8 = spans(arm_count=6), spans(coaxial=True)
        octo = spans(arm_count=8)
        assert quad == x8  # the X8 packs 8 rotors in the quad's footprint
        assert hexa[0] > quad[0] and hexa[1] > quad[1]  # the hexa is honestly wider
        assert octo[0] > hexa[0] and octo[1] > hexa[1]  # the ring out-spans them all
        assert tri[0] > quad[0]  # the tail boom stretches the tri lengthwise

    def test_coax_stacks_two_discs_per_arm(self):
        mesh = geometry.drone_geometry(**STOCK, coaxial=True, split_instances=True)
        discs = mesh["discs"]
        assert [d["part"] for d in discs] == [f"prop{i}" for i in range(1, 9)]
        upper = {d["center"][1] for d in discs[:4]}
        lower = {d["center"][1] for d in discs[4:]}
        assert len(upper) == len(lower) == 1
        assert min(upper) > 0 > max(lower)  # a plane above the arms, one below
        # pair members share their arm's (x, z) station
        for up, low in zip(discs[:4], discs[4:], strict=True):
            assert up["center"][0] == low["center"][0]
            assert up["center"][2] == low["center"][2]
        # nothing intrudes into any of the eight discs (the lower plane
        # clears the battery brick thanks to the standoff drop)
        assert geometry.disc_overlap(mesh, engine="mesh") == 0.0

    def test_coax_split_is_a_pure_repartition(self):
        merged = geometry.drone_geometry(**STOCK, coaxial=True)
        split = geometry.drone_geometry(**STOCK, coaxial=True, split_instances=True)
        merged_by_name = {p["name"]: p for p in merged["parts"]}
        split_by_name = {p["name"]: p for p in split["parts"]}
        for kind in ("motor", "prop"):
            vertices: list[float] = []
            faces: list[int] = []
            for i in range(1, 9):
                part = split_by_name[f"{kind}{i}"]
                offset = len(vertices) // 3
                vertices += part["vertices"]
                faces += [f + offset for f in part["faces"]]
            assert vertices == merged_by_name[f"{kind}s"]["vertices"]
            assert faces == merged_by_name[f"{kind}s"]["faces"]
        assert split["bounds"] == merged["bounds"]

    def test_family_lineup_folds_two_by_two(self):
        meshes = [
            geometry.drone_geometry(**STOCK, arm_count=3),
            geometry.drone_geometry(**STOCK),
            geometry.drone_geometry(**STOCK, arm_count=6),
            geometry.drone_geometry(**STOCK, coaxial=True),
        ]
        scene = geometry.lineup(meshes, labels=["tri", "quad", "hexa", "x8"])
        assert [entry["text"] for entry in scene["labels"]] == ["tri", "quad", "hexa", "x8"]
        prefixes = {p["name"].split(":")[0] for p in scene["parts"]}
        assert prefixes == {"tri", "quad", "hexa", "x8"}

    def test_cad_twin_matches_the_family(self):
        pytest.importorskip("cadquery")
        for kw, rotors in (({"arm_count": 3}, 3), ({"arm_count": 6}, 6), ({"coaxial": True}, 8)):
            assembly = geometry.to_cadquery(**STOCK, **kw)
            names = {child.name for child in assembly.children}
            expected = {"frame", "battery", "esc"}
            expected |= {f"motor{i}" for i in range(1, rotors + 1)}
            expected |= {f"prop{i}" for i in range(1, rotors + 1)}
            assert names == expected, kw

    def test_coax_solids_match_the_mesh_footprint(self):
        pytest.importorskip("cadquery")
        mesh = geometry.drone_geometry(**STOCK, coaxial=True, split_instances=True)
        by_name = {part["name"]: part for part in mesh["parts"]}
        solids = {
            child.name: geometry._shape(child.obj)
            for child in geometry.to_cadquery(**STOCK, coaxial=True).children
        }
        for name in ("motor5", "prop5", "motor8", "prop8"):  # the lower pair members
            (lo, hi) = geometry._part_aabb(by_name[name])
            box = solids[name].BoundingBox()
            for axis, (a, b) in enumerate(
                ((box.xmin, box.xmax), (box.ymin, box.ymax), (box.zmin, box.zmax))
            ):
                assert a == pytest.approx(lo[axis], abs=1e-4), (name, axis)
                assert b == pytest.approx(hi[axis], abs=1e-4), (name, axis)

    def test_belly_camera_sees_the_coax_lower_discs(self):
        """A real installation finding the quad never shows: the X8's
        lower forward discs poke into the down-looking camera's view
        cone (the exact-CAD boolean catches the wafer-thin discs the
        mesh quadrature under-reads)."""

        pytest.importorskip("cadquery")
        quad = geometry.drone_geometry(**STOCK, split_instances=True, camera=STOCK_CAMERA)
        assert geometry.camera_occlusion(quad, engine="cad") == 0.0
        x8 = geometry.drone_geometry(
            **STOCK, coaxial=True, split_instances=True, camera=STOCK_CAMERA
        )
        report = geometry.occlusion_report(x8, engine="cad")
        assert report["occludedFraction"] > 0.0
        assert set(report["obstructions"]) <= {"prop5", "prop6", "motor5", "motor6"}


class TestConfigKeyedScene:
    """The diagram -> 3D seam, keyed by configuration (the NB10 fix)."""

    def test_every_config_bakes_its_own_build(self, model):
        expected_discs = {
            "QuadCopter": 4,
            "TriCopter": 3,
            "HexaCopter": 6,
            "OctoCopter": 8,
            "CoaxX8": 8,
        }
        for name, count in expected_discs.items():
            mesh, part_map = drone_scene(model, f"Rotorcraft::{name}")
            assert len(mesh["discs"]) == count, name
            assert part_map["frame"] == f"Rotorcraft::{name}#0.chassis"

    def test_tricopter_scene_maps_the_boom_motor(self, model):
        mesh, part_map = drone_scene(model, "Rotorcraft::TriCopter")
        assert part_map["motor1"] == "Rotorcraft::TriCopter#0.frontMotors#0"
        assert part_map["motor2"] == "Rotorcraft::TriCopter#0.frontMotors#1"
        assert part_map["motor3"] == "Rotorcraft::TriCopter#0.tailMotor"
        # the tail motor renders at the boom station: behind the origin
        tail = next(p for p in mesh["parts"] if p["name"] == "motor3")
        assert max(tail["vertices"][0::3]) < 0

    def test_coax_scene_pairs_uppers_and_lowers(self, model):
        _mesh, part_map = drone_scene(model, "Rotorcraft::CoaxX8")
        assert part_map["motor1"] == "Rotorcraft::CoaxX8#0.upperMotors#0"
        assert part_map["motor5"] == "Rotorcraft::CoaxX8#0.lowerMotors#0"
        assert part_map["prop8"] == "Rotorcraft::CoaxX8#0.propellers#7"

    def test_owning_config_resolves_selections(self, model):
        for selected, expected in (
            ("Rotorcraft::TriCopter::tailMotor", "Rotorcraft::TriCopter"),
            ("Rotorcraft::TriCopter", "Rotorcraft::TriCopter"),
            ("Rotorcraft::CoaxX8::upperMotors", "Rotorcraft::CoaxX8"),
            ("Rotorcraft::HexaCopter::phaseLeads", "Rotorcraft::HexaCopter"),
            ("DeepScout::MultiRotor::battery", "DeepScout::MultiRotor"),
        ):
            config = link.owning_config(model, selected)
            assert config is not None and config.qualified_name == expected
        assert link.owning_config(model, "Rotorcraft") is None

    def test_selection_to_scene_round_trip(self, model):
        """The maintainer's NB10 flow: select the tricopter's tail motor
        anywhere, get the TRICOPTER's geometry."""

        config = link.owning_config(model, model.find("Rotorcraft::TriCopter::tailMotor"))
        mesh, _part_map = drone_scene(model, config.qualified_name)
        assert len(mesh["discs"]) == 3


class TestFamilyM0:
    """The population fan-outs T5 prints side by side."""

    def test_individual_fan_out_per_config(self, model):
        from longeron import m0

        counts = {}
        for name in CONFIGS:
            population = m0.interpret(model, f"Rotorcraft::{name}")
            counts[name] = len(population.individuals("ScoutParts::F450Kit::Motor"))
            per_motor = 0.055
            expected = counts[name] * per_motor
            total = 0.0
            for feature in ("motors", "frontMotors", "tailMotor", "upperMotors", "lowerMotors"):
                if feature in population.root.slots:
                    total += population.rollup(f"sum({feature}.mass)")
            assert total == pytest.approx(expected), name
        assert counts == {
            "QuadCopter": 4,
            "TriCopter": 3,
            "HexaCopter": 6,
            "OctoCopter": 8,
            "CoaxX8": 8,
        }

    def test_octo_and_x8_share_a_count_but_not_a_shape(self, model):
        from longeron import m0

        octo = m0.interpret(model, "Rotorcraft::OctoCopter")
        x8 = m0.interpret(model, "Rotorcraft::CoaxX8")
        # same motor count, different populations: one flat [8], two [4]s
        assert len(octo.root.slots["motors"]) == 8
        assert len(x8.root.slots["upperMotors"]) == len(x8.root.slots["lowerMotors"]) == 4

    def test_coax_pair_ids(self, model):
        from longeron import m0

        population = m0.interpret(model, "Rotorcraft::CoaxX8")
        uppers = [ind.id for ind in population.root.slots["upperMotors"]]
        lowers = [ind.id for ind in population.root.slots["lowerMotors"]]
        assert uppers == [f"Rotorcraft::CoaxX8#0.upperMotors#{i}" for i in range(4)]
        assert lowers == [f"Rotorcraft::CoaxX8#0.lowerMotors#{i}" for i in range(4)]


class TestFamilyVerify:
    """hunt and prove exercise the new requirement axis."""

    def test_hunt_finds_the_quad_motor_out_violation(self, model):
        pytest.importorskip("hypothesis")
        from longeron.analysis import verify

        report = verify.hunt(
            model,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FailSafeHover",),
            free=("payloadMass",),
            seed=0,
            max_examples=30,
        )
        assert report.status == "violated"
        assert "FailSafeHover::motorOutHover" in report.violations
        # the shrunk catch: the quad fails motor-out even EMPTY
        assert report.counterexamples[0].bindings == {"payloadMass": 0.0}

    def test_hunt_bisects_the_hexa_payload_ceiling(self, model):
        pytest.importorskip("hypothesis")
        from longeron.analysis import verify

        report = verify.hunt(
            model,
            "Rotorcraft::HexaCopter",
            requirements=("DeepScout::FailSafeHover",),
            free=("payloadMass",),
            seed=0,
            max_examples=60,
        )
        edge = next(b for b in report.boundaries if "motorOutHover" in b.violated)
        assert edge.value == pytest.approx(0.4445, abs=0.001)

    def test_prove_certifies_the_x8_and_condemns_the_quad(self, model):
        pytest.importorskip("z3")
        from fractions import Fraction

        from longeron.analysis import verify

        x8 = verify.prove(
            model,
            "Rotorcraft::CoaxX8",
            requirements=("DeepScout::FailSafeHover",),
            free=("payloadMass",),
        )
        proof = next(p for p in x8.proofs if "motorOutHover" in p.requirement)
        # UNSAT: no payload inside the takeoff-mass envelope can violate
        # FailSafeHover on the X8 -- and the envelope bound is exact
        assert proof.status == "proven-safe"
        assert Fraction(proof.bound) == Fraction(249, 500)  # 0.498 kg payload
        assert "takeoffMassLimit" in proof.binding_constraint

        quad = verify.prove(
            model,
            "Rotorcraft::QuadCopter",
            requirements=("DeepScout::FailSafeHover",),
            free=("payloadMass",),
        )
        catch = next(p for p in quad.proofs if "motorOutHover" in p.requirement)
        assert catch.status == "violation"  # a witness the interpreter confirmed
        assert quad.counterexamples and quad.counterexamples[0].violated == (
            "FailSafeHover::motorOutHover",
        )
