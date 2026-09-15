"""Measure split NVE restart differences; trajectory identity is not a physics gate.

See NAMD User's Guide, Dynamics (COMmotion), and Merz & Shirts (2018),
doi:10.1371/journal.pone.0202764 for physical integrator validation.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from experiments.gold_interfaces.native import run, read_binary


def probe(package, binary, source="equilibrate", tag="nve", dt=1.):
    run(package, binary, prefix=tag+"_full", steps=40, restart=source, thermostat=False, dt=dt)
    run(package, binary, prefix=tag+"_split1", steps=20, restart=source, thermostat=False, dt=dt)
    run(package, binary, prefix=tag+"_split2", steps=20, restart=tag+"_split1", thermostat=False, dt=dt)
    delta = {}
    for ext in ("coor", "vel"):
        a = read_binary(package/"output"/f"{tag}_full.{ext}")
        b = read_binary(package/"output"/f"{tag}_split2.{ext}")
        delta[ext] = float(np.max(np.abs(a-b)))
    result = {"source": source, "continuous_steps": 40, "split_steps": [20, 20],
              "thermostat": "off", "max_coordinate_difference_A": delta["coor"],
              "max_velocity_difference_A_per_AKMA": delta["vel"],
              "timestep_fs": dt,
              "legacy_threshold_comparison": {
                  "coordinate_A": 1e-4, "velocity_A_per_AKMA": 1e-4,
                  "within": delta["coor"] < 1e-4 and delta["vel"] < 1e-4,
                  "status": "Historical diagnostic only; thresholds have no literature validation"},
              "physical_validation": "not established",
              "interpretation": "Restart sensitivity diagnostic; assess momentum/energy continuity and NVE timestep convergence separately"}
    (package/f"{tag}_restart_fidelity.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result), flush=True)
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("package", type=Path)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--source", default="equilibrate")
    p.add_argument("--tag", default="nve")
    p.add_argument("--dt", type=float, choices=(.5, 1., 2.), default=1.)
    a = p.parse_args()
    probe(a.package, a.binary, source=a.source, tag=a.tag, dt=a.dt)
