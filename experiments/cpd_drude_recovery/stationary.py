"""Locally polish a relaxed diagnostic and test its internal Hessian curvature."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import (
    AdiabaticNonbonded,
    checked,
    source,
    write,
)
from backend.parameterization.photoproduct_openmm_linear_response import (
    mass_weighted_rigid_body_projector,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stage", type=Path, required=True)
    p.add_argument("--recovery", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    r = args.stage.resolve()
    args.output.mkdir(exist_ok=False)
    (args.output / "stationary_snapshot.py").write_text(Path(__file__).read_text())
    policy = json.loads((r / "policy.json").read_text())
    model = AdiabaticNonbonded(args.recovery, checked(policy["electrostatics"]))
    selected = json.loads((r / "selected_response_fit.json").read_text())
    prior = json.loads((r / "geometry_assessment.json").read_text())
    system = mm.XmlSerializer.deserialize(
        (r / "basis/linear_fit_system.xml").read_text()
    )
    integrator = mm.VerletIntegrator(0.001)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
    for item in selected["parameters"]:
        context.setParameter(item["name"], item["coefficient"])
    initial = np.loadtxt(r / "minimized_nuclear_coordinates_angstrom.txt")
    xyz = initial.copy()

    def gradient(x):
        _, g = model.energy_gradient(x)
        context.setPositions(x * u.angstrom)
        state = context.getState(getForces=True)
        return g - np.asarray(
            state.getForces(asNumpy=True).value_in_unit(
                u.kilocalorie_per_mole / u.angstrom
            )
        ).reshape(-1)

    def hessian(x, step):
        h = np.empty((x.size, x.size))
        for k in range(x.size):
            a, b = x.reshape(-1).copy(), x.reshape(-1).copy()
            a[k] += step
            b[k] -= step
            h[:, k] = (gradient(a.reshape(-1, 3)) - gradient(b.reshape(-1, 3))) / (
                2 * step
            )
        return (h + h.T) / 2

    history = []
    for iteration in range(5):
        # Unit masses give an ordinary Cartesian rigid-body complement here;
        # eigenvalues below measure curvature, not vibrational frequencies.
        proj, rigid_rank = mass_weighted_rigid_body_projector(xyz, np.ones(len(xyz)))
        values, vectors = np.linalg.eigh(proj)
        z = vectors[:, values > 0.5]
        h = hessian(xyz, 5e-5)
        internal = z.T @ h @ z
        eigenvalues = np.linalg.eigvalsh(internal)
        g = gradient(xyz)
        history.append(
            {
                "iteration": iteration,
                "gradient_max_abs": float(max(abs(g))),
                "minimum_internal_curvature": float(eigenvalues[0]),
                "rigid_rank": rigid_rank,
            }
        )
        if eigenvalues[0] <= 0:
            raise ValueError(
                "Nonpositive internal curvature; Newton minimum polishing is not justified"
            )
        if max(abs(g)) < 1e-5:
            break
        delta = -z @ np.linalg.solve(internal, z.T @ g)
        if max(np.linalg.norm(delta.reshape(-1, 3), axis=1)) > 0.005:
            raise ValueError(
                "Local correction exceeds the 0.005 A diagnostic neighborhood"
            )
        trial = xyz + delta.reshape(-1, 3)
        if np.linalg.norm(gradient(trial)) >= np.linalg.norm(g):
            raise ValueError("Newton correction does not improve stationarity")
        xyz = trial
    else:
        raise ValueError("Local Newton polishing did not converge in five iterations")
    # Independent step-halving check at the final point, not just the QM geometry.
    hhalf = hessian(xyz, 2.5e-5)
    fd_error = float(np.linalg.norm(hhalf - h) / np.linalg.norm(hhalf))
    eigenvalues = np.linalg.eigvalsh(z.T @ hhalf @ z)
    g = gradient(xyz)
    idx = model.d._atom_index()
    bonds = []
    for bond in prior["bonds"]:
        a, b = [idx[name] for name in bond["atoms"]]
        distance = float(np.linalg.norm(xyz[a] - xyz[b]))
        bonds.append(
            {
                **bond,
                "mm_angstrom": distance,
                "error_angstrom": distance - bond["qm_angstrom"],
            }
        )
    plan = json.loads((r / "bonded_fit_plan.json").read_text())
    stereo = []
    for item in plan["stereochemical_impropers"]:
        a, b, c, d = xyz[[idx[name] for name in item["ordered_atoms_candidate"]]]
        volume = float(np.dot(b - a, np.cross(c - a, d - a)))
        stereo.append(
            {
                "center": item["stereocenter"],
                "volume": volume,
                "passed": bool(
                    np.sign(volume) == np.sign(item["observed_signed_volume"])
                ),
            }
        )
    maximum = max(abs(b["error_angstrom"]) for b in bonds)
    numerical = bool(max(abs(g)) < 1e-5 and fd_error < 0.001 and eigenvalues[0] > 0)
    np.savetxt(args.output / "stationary_coordinates_angstrom.txt", xyz)
    np.savetxt(args.output / "nuclear_hessian_kcal_mol_angstrom2.txt", hhalf)
    np.savetxt(args.output / "internal_curvatures_kcal_mol_angstrom2.txt", eigenvalues)
    write(
        args.output / "assessment.json",
        {
            "status": "stationary_geometry_passed"
            if numerical and maximum <= 0.03 and all(v["passed"] for v in stereo)
            else "stationary_geometry_failed",
            "simulation_ready": False,
            "gate_effect": "none",
            "numerical_local_minimum_passed": numerical,
            "final_gradient_max_abs": float(max(abs(g))),
            "gradient_max_abs_limit": 1e-5,
            "hessian_step_halving_relative_error": fd_error,
            "hessian_step_halving_limit": 0.001,
            "minimum_internal_curvature_kcal_mol_angstrom2": float(eigenvalues[0]),
            "maximum_atom_correction_angstrom": float(
                max(np.linalg.norm(xyz - initial, axis=1))
            ),
            "maximum_bond_error_angstrom": maximum,
            "bond_error_limit_angstrom": 0.03,
            "bonds": bonds,
            "stereocenters": stereo,
            "history": history,
            "sources": {
                "prior_geometry": source(r / "geometry_assessment.json"),
                "selected": source(r / "selected_response_fit.json"),
                "code": source(args.output / "stationary_snapshot.py"),
            },
            "interpretation": "Local minimum and geometry diagnostic only; no independent QM vibrational/PES or solution acceptance.",
        },
    )
    print(
        "Numerical local minimum:",
        numerical,
        "maximum bond error:",
        maximum,
        "gradient max:",
        max(abs(g)),
        flush=True,
    )


if __name__ == "__main__":
    main()
