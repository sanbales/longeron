"""A 'higher-fidelity' cruise-power analysis for the UAV missions demo.

``UavMissions::CruisePower`` (examples/uav_missions.sysml) declares this
component through its ``@ExternalAnalysis`` annotation: the calc def's
``in`` parameters are the I/O contract, its body is the first-order model
(parasite CdA + span-efficiency induced drag), and this module is the tool
that refines it.  ``longeron.analysis.mdao.build_problem`` validates the
declared parameter names against the component's actual inputs/outputs
and swaps it in per calc with ``fidelity={"CruisePower": "external"}``.

The refinement is synthetic but physically shaped -- what a panel code or
wind-tunnel fit would disagree with the drag-polar sketch about:

* Reynolds scaling: profile drag grows as (Re / 5e5)^-0.11 (turbulent
  skin friction), so slow flight on a small chord is draggier per unit
  area than the fixed-CdA model claims;
* stall-adjacent drag rise: separation adds 0.02 * (CL / 1.05)^8, which
  punishes the slow, high-CL corner the first-order model rewards.

Both corrections push the best-endurance loiter speed *up* and shave the
predicted station time -- the fidelity-swap story in notebook 07.

Requires the ``mdao`` extra (openmdao).
"""

from __future__ import annotations

from math import pi

import openmdao.api as om

RHO = 1.225  # kg/m^3, sea level
MU = 1.81e-5  # Pa*s, dynamic viscosity of air
RE_REF = 5.0e5  # Reynolds number the catalog CdA values are quoted at
CL_STALL = 1.05  # stall-onset lift coefficient of the catalog wings


class CruisePowerPolar(om.ExplicitComponent):
    """Reynolds/stall-aware drag polar behind the CruisePower contract."""

    def setup(self) -> None:
        self.add_input("massKg", val=1.0)
        self.add_input("speed", val=15.0)
        self.add_input("dragArea", val=0.03)  # CdA, m^2
        self.add_input("span", val=2.0)
        self.add_input("wingArea", val=0.5)
        self.add_input("spanEff", val=0.9)  # Oswald e x wingtip-prop bonus
        self.add_input("propEff", val=0.7)
        self.add_output("power", val=0.0)  # W, electrical
        self.declare_partials("power", "*", method="fd")

    def compute(self, inputs, outputs) -> None:  # type: ignore[no-untyped-def]
        mass = float(inputs["massKg"][0])
        speed = float(inputs["speed"][0])
        drag_area = float(inputs["dragArea"][0])
        span = float(inputs["span"][0])
        area = float(inputs["wingArea"][0])
        span_eff = float(inputs["spanEff"][0])
        prop_eff = float(inputs["propEff"][0])

        q = 0.5 * RHO * speed * speed
        weight = mass * 9.81
        cl = weight / (q * area)
        chord = area / span
        aspect = span * span / area

        reynolds = RHO * speed * chord / MU
        cd0 = (drag_area / area) * (reynolds / RE_REF) ** -0.11
        cdi = cl * cl / (pi * aspect * span_eff)
        cd_stall = 0.02 * (cl / CL_STALL) ** 8

        drag = q * area * (cd0 + cdi + cd_stall)
        outputs["power"] = drag * speed / prop_eff
