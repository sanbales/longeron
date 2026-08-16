#!/usr/bin/env python
"""End-to-end demo of the sysml2 package: define, export, execute.

Run:  python examples/demo.py
"""

from pathlib import Path

import sysml2

HERE = Path(__file__).parent


def banner(title: str) -> None:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


def main() -> None:
    # ----- 1. Define: parse a textual model --------------------------------
    model = sysml2.load(HERE / "drone.sysml")
    interp = sysml2.Interpreter(model)

    banner("1. Parsed model, re-exported as SysML v2 text (excerpt)")
    print("\n".join(sysml2.to_sysml(model).splitlines()[:24]))

    banner("2. JSON export (excerpt)")
    print("\n".join(sysml2.to_json(model).splitlines()[:20]))

    # ----- 3. Instantiate & check ------------------------------------------
    banner("3. Instantiate QuadCopter and check constraints")
    drone = interp.instantiate("Drone::QuadCopter")
    print("instance:", drone)
    print("total mass:", drone.get("totalMass"))
    for result in interp.check(drone):
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {result.name}: {result.expression}")

    heavy = interp.instantiate("Drone::QuadCopter", payloadMass=0.8)
    print("\nwith 0.8 kg payload:")
    for result in interp.check(heavy):
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {result.name}: {result.expression}")

    # ----- 4. Calculations ---------------------------------------------------
    banner("4. Execute calculations")
    print("HoverTime(5200 mAh)          =",
          round(interp.call("Drone::HoverTime", capacity=5200.0), 1), "min")
    print("ThrustToWeight(36 N, 1.2 kg) =",
          round(interp.call("Drone::ThrustToWeight", 36.0, 1.2), 2))

    # ----- 5. Requirements ----------------------------------------------------
    banner("5. Check a requirement against an instance")
    result = interp.check_requirement("Drone::FlightEnvelope", subject=drone)
    print("applicable:", result.applicable, "| satisfied:", result.satisfied)

    # ----- 6. Actions -----------------------------------------------------------
    banner("6. Run an action")
    run = interp.run_action("Drone::PlanBattery", inputs={"distanceKm": 10.0})
    print("outputs:", run.outputs)
    for line in run.trace:
        print("  trace:", line)

    # ----- 7. State machine ------------------------------------------------------
    banner("7. Simulate the flight state machine")
    sim = interp.simulate(
        "Drone::FlightStates",
        events=["launch", "airborne", "low_battery", "touchdown"])
    for step in sim.trace:
        print("  ", step)
    print("final state:", sim.final_state)
    print("launches:", sim.env["launches"])
    print("sent:", [s.payload for s in sim.sends])

    # ----- 8. Programmatic definition ----------------------------------------------
    banner("8. Define a model programmatically and export it")
    from sysml2 import model as M

    pkg = M.Package(name="Generated")
    sensor = M.Definition(kind="part", name="Sensor")
    sensor.add(
        M.Usage(kind="attribute", name="rate", types=["Real"],
                value=M.FeatureValue(sysml2.parse_expression("100.0 * 2"))))
    pkg.add(sensor)
    new_model = M.Model()
    new_model.add(pkg)
    print(sysml2.to_sysml(new_model))


if __name__ == "__main__":
    main()
