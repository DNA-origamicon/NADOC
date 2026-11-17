"""Finite-difference audit of the native CPD force and body-frame torque.

Uses a prepared, provenance-bearing job. Perturbations exist only in memory;
the input configuration is never rewritten.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation
import oxpy


def check(input_path, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    inp = oxpy.InputFile()
    inp.init_from_filename(str(Path(input_path).resolve()))
    for key, name in (
        ("trajectory_file", "trajectory.dat"),
        ("energy_file", "energy.dat"),
        ("lastconf_file", "last_conf.dat"),
        ("log_file", "native.log"),
    ):
        inp[key] = str(output / name)
    inp["steps"] = "0"
    inp["sim_type"] = "MD"
    inp["backend"] = "CPU"
    inp["refresh_vel"] = "true"
    inp["external_forces"] = "false"
    manifest = json.loads(
        (Path(inp["cpd_file"]).parent / "cpd_manifest.json").read_text()
    )
    indices = manifest["endpoints"][0]["particles"]
    manager = oxpy.OxpyManager(inp)
    info = manager.config_info()
    p, q = [info.particles()[i] for i in indices]
    inter = info.interaction
    for part in (p, q):
        part.force = np.zeros(3)
        part.torque = np.zeros(3)
    inter.pair_interaction_bonded(p, q, True, True)
    analytical = [(np.array(x.force).copy(), np.array(x.torque).copy()) for x in (p, q)]
    epsilon = 1e-6
    errors = []
    for part, (force, torque) in zip((p, q), analytical):
        position = np.array(part.pos).copy()
        rotation = np.array(part.orientation).copy()
        for axis in range(3):
            e = np.eye(3)[axis] * epsilon
            part.pos = position + e
            plus = inter.pair_interaction_bonded(p, q, True, False)
            part.pos = position - e
            minus = inter.pair_interaction_bonded(p, q, True, False)
            part.pos = position
            errors.append(abs((minus - plus) / (2 * epsilon) - force[axis]))
            # A right multiplication rotates about the particle's body axis.
            part.orientation = rotation @ Rotation.from_rotvec(e).as_matrix()
            plus = inter.pair_interaction_bonded(p, q, True, False)
            part.orientation = rotation @ Rotation.from_rotvec(-e).as_matrix()
            minus = inter.pair_interaction_bonded(p, q, True, False)
            part.orientation = rotation
            errors.append(abs((minus - plus) / (2 * epsilon) - torque[axis]))
    result = {
        "input": str(input_path),
        "particle_indices": indices,
        "maximum_absolute_derivative_error": max(errors),
        "errors": errors,
        "net_force_norm": float(np.linalg.norm(analytical[0][0] + analytical[1][0])),
        "passed": bool(max(errors) < 1e-4),
    }
    (output / "force_audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
    if not result["passed"]:
        raise ValueError("CPD native derivative audit failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with oxpy.Context():
        check(args.input, args.output)
