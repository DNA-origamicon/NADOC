"""Re-minimize an isolated bonded diagnostic on the relaxed-Drude surface."""

from pathlib import Path
import argparse
import json
import sys

import numpy as np
import openmm as mm
from openmm import unit as u
from scipy.optimize import OptimizeResult

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import (
    AdiabaticNonbonded,
    write,
    source,
    checked,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--recovery", type=Path, required=True)
    p.add_argument("--stage", type=Path, required=True)
    args = p.parse_args()
    r = args.stage.resolve()
    if (r / "geometry_assessment.json").exists():
        raise FileExistsError(r / "geometry_assessment.json")
    policy = json.loads((r / "policy.json").read_text())
    electrostatics = (
        checked(policy["electrostatics"]) if policy.get("electrostatics") else None
    )
    model = AdiabaticNonbonded(args.recovery, electrostatics)
    (r / "geometry_snapshot.py").write_text(Path(__file__).read_text())
    selected = json.loads((r / "selected_response_fit.json").read_text())
    system = mm.XmlSerializer.deserialize(
        (r / "basis/linear_fit_system.xml").read_text()
    )
    integrator = mm.VerletIntegrator(0.001)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
    for record in selected["parameters"]:
        context.setParameter(record["name"], record["coefficient"])
    manifest = json.loads(
        (r / "responses/minimum/linear_response_manifest.json").read_text()
    )
    from backend.parameterization.photoproduct_qm import parse_xyz

    xyz = np.array(
        [
            a[1:]
            for a in parse_xyz(
                checked(manifest["sources"]["target_geometry"]).read_text()
            )[0]
        ]
    )

    def evaluate(flat):
        coords = flat.reshape(-1, 3)
        e, g = model.energy_gradient(coords)
        context.setPositions(coords * u.angstrom)
        state = context.getState(getEnergy=True, getForces=True)
        e += state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
        g -= np.array(
            state.getForces(asNumpy=True).value_in_unit(
                u.kilocalorie_per_mole / u.angstrom
            )
        ).reshape(-1)
        return e, g

    initial_e, initial_g = evaluate(xyz.reshape(-1))
    # Reject invalid Drude trial points and cap each nuclear step at 0.02 A.
    # Unrestricted L-BFGS's initial unit-length trial can leave the model domain.
    current = xyz.reshape(-1).copy()
    energy, gradient = initial_e, initial_g
    inverse = np.eye(len(current)) / 1000
    rejected = 0
    success = False
    stalled_steps = 0
    message = "iteration limit"
    for iteration in range(2000):
        if max(abs(gradient)) < 1e-5:
            success = True
            message = "nuclear gradient converged"
            break
        direction = -inverse @ gradient
        if direction @ gradient >= 0:
            inverse = np.eye(len(current)) / 1000
            direction = -inverse @ gradient
        direction *= min(
            1.0, 0.02 / max(np.linalg.norm(direction.reshape(-1, 3), axis=1))
        )
        alpha = 1.0
        for _ in range(40):
            trial = current + alpha * direction
            try:
                trial_e, trial_g = evaluate(trial)
                if trial_e <= energy + 1e-4 * alpha * (gradient @ direction):
                    break
            except ValueError:
                rejected += 1
            alpha *= 0.5
        else:
            message = "line search could not find a valid descending step"
            break
        s, y = trial - current, trial_g - gradient
        sy = float(s @ y)
        if sy > 1e-12:
            v = np.eye(len(current)) - np.outer(s, y) / sy
            inverse = v @ inverse @ v.T + np.outer(s, s) / sy
        current, energy, gradient = trial, trial_e, trial_g
        stalled_steps = stalled_steps + 1 if np.max(abs(s)) < 1e-10 else 0
        if stalled_steps >= 20:
            # Stop reporting numerical motion as useful relaxation. This is
            # failure unless the original force criterion is independently met.
            success = bool(max(abs(gradient)) < 1e-5)
            message = (
                "nuclear gradient converged"
                if success
                else "20 consecutive sub-1e-10 A steps without force convergence"
            )
            break
    result = OptimizeResult(
        x=current,
        fun=energy,
        jac=gradient,
        success=success,
        message=message,
        nit=iteration + 1,
    )
    opt = result.x.reshape(-1, 3)
    np.savetxt(r / "minimized_nuclear_coordinates_angstrom.txt", opt)
    plan = json.loads((r / "bonded_fit_plan.json").read_text())
    idx = model.d._atom_index()
    stereo = []
    for item in plan["stereochemical_impropers"]:
        atomids = [idx[a] for a in item["ordered_atoms_candidate"]]
        a, b, c, d = opt[atomids]
        v = float(np.dot(b - a, np.cross(c - a, d - a)))
        stereo.append(
            {
                "center": item["stereocenter"],
                "volume": v,
                "passed": bool(np.sign(v) == np.sign(item["observed_signed_volume"])),
            }
        )
    heavy = np.arange(20)
    a, b = opt[heavy] - opt[heavy].mean(0), xyz[heavy] - xyz[heavy].mean(0)
    left, _, right = np.linalg.svd(a.T @ b)
    rot = left @ np.diag([1, 1, np.linalg.det(left @ right)]) @ right
    rmsd = float(np.sqrt(np.mean(np.sum((a @ rot - b) ** 2, axis=1))))
    bonds = []
    for a, b in model.d._bonds():
        old, new = np.linalg.norm(xyz[a] - xyz[b]), np.linalg.norm(opt[a] - opt[b])
        bonds.append(
            {
                "atoms": [model.d.ATOM_NAMES[a], model.d.ATOM_NAMES[b]],
                "qm_angstrom": float(old),
                "mm_angstrom": float(new),
                "error_angstrom": float(new - old),
            }
        )
    maximum = max(abs(v["error_angstrom"]) for v in bonds)
    report = {
        "status": "diagnostic_geometry_passed"
        if result.success and maximum <= 0.03 and all(v["passed"] for v in stereo)
        else "diagnostic_geometry_failed",
        "simulation_ready": False,
        "gate_effect": "none",
        "optimizer_success": bool(result.success),
        "optimizer_message": str(result.message),
        "iterations": int(result.nit),
        "invalid_drude_trials_rejected": rejected,
        "initial_energy_kcal_mol": initial_e,
        "final_energy_kcal_mol": float(result.fun),
        "initial_gradient_rms": float(np.sqrt(np.mean(initial_g**2))),
        "final_gradient_rms": float(np.sqrt(np.mean(result.jac**2))),
        "final_gradient_max_abs": float(np.max(abs(result.jac))),
        "gradient_max_abs_limit": 1e-5,
        "stalled_steps": stalled_steps,
        "heavy_atom_rmsd_angstrom": rmsd,
        "maximum_bond_error_angstrom": maximum,
        "bond_error_limit_angstrom": 0.03,
        "stereocenters": stereo,
        "bonds": bonds,
        "sources": {
            "selected": source(r / "selected_response_fit.json"),
            "code": source(__file__),
        },
    }
    write(r / "geometry_assessment.json", report)
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in ("bonds", "sources")}, indent=2
        )
    )


if __name__ == "__main__":
    main()
