#!/usr/bin/env python
"""End-to-end demo of the longeron package: define, export, execute, full loop.

Run:  python examples/demo.py
"""

import tempfile
from pathlib import Path

import longeron

HERE = Path(__file__).parent


def banner(title: str) -> None:
    print(f"\n{'=' * 64}\n{title}\n{'=' * 64}")


def main() -> None:
    # ----- 1. Define: parse a textual model --------------------------------
    model = longeron.load(HERE / "drone.sysml")
    interp = longeron.Interpreter(model)

    banner("1. Parsed model, re-exported as SysML v2 text (excerpt)")
    print("\n".join(longeron.to_sysml(model).splitlines()[:24]))

    banner("2. JSON export (excerpt)")
    print("\n".join(longeron.to_json(model).splitlines()[:20]))

    # ----- 3. Instantiate & check ------------------------------------------
    banner("3. Instantiate QuadCopter and check constraints")
    drone = interp.instantiate("Drone::QuadCopter")
    print("instance:", drone)
    print("total mass:", drone.get("totalMass"))
    for result in interp.check(drone):
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {result.name}: {result.expression}")

    heavy = interp.instantiate("Drone::QuadCopter", payloadMass=0.6)
    print("\nwith 0.6 kg payload:")
    for result in interp.check(heavy):
        status = "PASS" if result.passed else "FAIL"
        print(f"  [{status}] {result.name}: {result.expression}")

    # ----- 4. Calculations ---------------------------------------------------
    banner("4. Execute calculations")
    print(
        "HoverTime(5200 mAh)          =",
        round(interp.call("Drone::HoverTime", capacity=5200.0), 1),
        "min",
    )
    print(
        "ThrustToWeight(36 N, 1.2 kg) =", round(interp.call("Drone::ThrustToWeight", 36.0, 1.2), 2)
    )

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
        "Drone::FlightStates", events=["launch", "airborne", "low_battery", "touchdown"]
    )
    for step in sim.trace:
        print("  ", step)
    print("final state:", sim.final_state)
    print("launches:", sim.env["launches"])
    print("sent:", [s.payload for s in sim.sends])

    # ----- 8. Programmatic definition ----------------------------------------------
    banner("8. Define a model programmatically and export it")
    from longeron import model as M

    pkg = M.Package(name="Generated")
    sensor = M.Definition(kind="part", name="Sensor")
    sensor.add(
        M.Usage(
            kind="attribute",
            name="rate",
            types=["Real"],
            value=M.FeatureValue(longeron.parse_expression("100.0 * 2")),
        )
    )
    pkg.add(sensor)
    new_model = M.Model()
    new_model.add(pkg)
    print(longeron.to_sysml(new_model))

    # ----- 9. Full loop: run, write results back, save, reload -----------------------
    banner("9. Full loop: run -> snapshot results into the model -> save -> reload")
    out_dir = Path(tempfile.mkdtemp(prefix="longeron-demo-"))
    flown = interp.instantiate("Drone::QuadCopter", payloadMass=0.35)
    snapshot = interp.snapshot(flown, name="asFlown")
    model.find("Drone").add(snapshot)

    longeron.save(model, out_dir / "drone_with_results.sysml")
    longeron.save(model, out_dir / "drone_with_results.json")
    print("saved:", *(str(p) for p in sorted(out_dir.iterdir())), sep="\n  ")

    reloaded = longeron.load(out_dir / "drone_with_results.json")
    print(
        "reloaded from JSON; snapshot mass =",
        longeron.Interpreter(reloaded)
        .instantiate(reloaded.find("Drone::asFlown"))
        .slots["totalMass"],
    )

    # ----- 10. KerML projection --------------------------------------------------------
    banner("10. Project the model onto KerML (and re-parse it as KerML)")
    kerml_text = longeron.to_kerml(model)
    print("\n".join(kerml_text.splitlines()[:14]))
    longeron.parse_kerml_text(kerml_text)
    print("...\nKerML output re-parses cleanly.")


if __name__ == "__main__":
    main()
