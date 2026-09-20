"""Independent archived cis-syn additive candidate minimum diagnostic."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from scipy.optimize import root as solve_root
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_openmm_linear_response import (
    mass_weighted_rigid_body_projector,
)
from backend.parameterization.photoproduct_qm import parse_xyz


def main(archive, root):
    root.mkdir(exist_ok=False)
    (root / "source_snapshot.py").write_text(Path(__file__).read_text())
    report_path = archive / "unattended-continuation-report-v3.json"
    report = json.loads(report_path.read_text())
    selected_path = checked(report["selected_candidate"])
    selected = json.loads(selected_path.read_text())
    minimum_path = checked(report["minimum_response"])
    minimum = json.loads(minimum_path.read_text())
    basis_path = checked(report["fit_basis_manifest"])
    basis = json.loads(basis_path.read_text())
    system_path = checked(basis["outputs"]["linear_fit_system"])
    system = mm.XmlSerializer.deserialize(system_path.read_text())
    assert not any(isinstance(f, mm.DrudeForce) for f in system.getForces())
    names = [
        r["stable_atom_key"]
        for r in json.loads(checked(minimum["sources"]["stable_atom_map"]).read_text())
    ]
    index = {n: i for i, n in enumerate(names)}
    xyz = np.array(
        [
            r[1:]
            for r in parse_xyz(
                checked(minimum["sources"]["target_geometry"]).read_text()
            )[0]
        ]
    )
    assert system.getNumParticles() == len(xyz) == len(names) == 36
    integrator = mm.VerletIntegrator(0.001)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
    for p in selected["parameters"]:
        context.setParameter(p["name"], p["coefficient"])
    context.setPositions(xyz * u.angstrom)
    initial = context.getState(getEnergy=True, getForces=True)
    mm.LocalEnergyMinimizer.minimize(context, 1e-7, 20000)
    state = context.getState(getEnergy=True, getForces=True, getPositions=True)
    final = np.asarray(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    forces = np.asarray(
        state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole / u.angstrom)
    )
    projector, rigid_rank = mass_weighted_rigid_body_projector(
        final, np.ones(len(final))
    )
    assert rigid_rank == 6
    eigenvalues, eigenvectors = np.linalg.eigh(projector)
    internal = eigenvectors[:, eigenvalues > 0.5]
    origin = final.ravel().copy()

    def reduced_gradient(delta):
        context.setPositions((origin + internal @ delta).reshape(-1, 3) * u.angstrom)
        f = np.asarray(
            context.getState(getForces=True)
            .getForces(asNumpy=True)
            .value_in_unit(u.kilocalorie_per_mole / u.angstrom)
        )
        return -internal.T @ f.ravel()

    stationary = solve_root(
        reduced_gradient,
        np.zeros(internal.shape[1]),
        method="hybr",
        options={"xtol": 1e-10},
    )
    reduced_gradient(stationary.x)
    hessians = []
    for step in (1e-4, 5e-5):
        h = np.empty((len(stationary.x), len(stationary.x)))
        for j in range(len(stationary.x)):
            plus, minus = stationary.x.copy(), stationary.x.copy()
            plus[j] += step
            minus[j] -= step
            h[:, j] = (reduced_gradient(plus) - reduced_gradient(minus)) / (2 * step)
        hessians.append((h + h.T) / 2)
    reduced_gradient(stationary.x)
    state = context.getState(getEnergy=True, getPositions=True, getForces=True)
    final = np.asarray(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    forces = np.asarray(
        state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole / u.angstrom)
    )
    plan_path = archive / "bonded_fit_plan.json"
    plan = json.loads(plan_path.read_text())
    bonds = set()
    for item in plan["transfer_candidates"]:
        if item["category"] == "bonds":
            bonds.add(tuple(sorted(item["atoms"])))
    for group in plan["uncovered_parameter_groups"]:
        if group["category"] == "bonds":
            for item in group["occurrences"]:
                bonds.add(tuple(sorted(item["atoms"])))
    rows = []
    for pair in sorted(bonds):
        i, j = [index[n] for n in pair]
        r0 = float(np.linalg.norm(xyz[i] - xyz[j]))
        r = float(np.linalg.norm(final[i] - final[j]))
        rows.append(
            {
                "atoms": pair,
                "qm_angstrom": r0,
                "mm_angstrom": r,
                "error_angstrom": r - r0,
            }
        )
    stereo = []
    for item in plan["stereochemical_impropers"]:
        a, b, c, d = final[[index[n] for n in item["ordered_atoms_candidate"]]]
        v = float(np.dot(b - a, np.cross(c - a, d - a)))
        stereo.append(
            {
                "center": item["stereocenter"],
                "volume": v,
                "preserved": bool(
                    np.sign(v) == np.sign(item["observed_signed_volume"])
                ),
            }
        )
    np.savetxt(root / "minimum_angstrom.txt", final)
    write(
        root / "assessment.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "product_id": "tt-cpd-cis-syn",
            "model_family": "additive_CHARMM_candidate",
            "scope": "Unrestrained isolated capped-fragment MM minimum from the archived selected fit. No independent-validation or solution claim; archive selection used validation scores.",
            "initial_energy_kcal_mol": float(
                initial.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
            ),
            "final_energy_kcal_mol": float(
                state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
            ),
            "maximum_force_kcal_mol_angstrom": float(abs(forces).max()),
            "maximum_bond_error_angstrom": max(abs(r["error_angstrom"]) for r in rows),
            "stationary_solver_success": bool(stationary.success),
            "minimum_internal_curvatures_kcal_mol_angstrom2": [
                float(np.linalg.eigvalsh(h).min()) for h in hessians
            ],
            "hessian_halving_relative_error": float(
                np.linalg.norm(hessians[0] - hessians[1]) / np.linalg.norm(hessians[1])
            ),
            "bond_count": len(bonds),
            "crosslinks": [
                pair
                for pair in sorted(bonds)
                if pair[0].split(":")[0] != pair[1].split(":")[0]
            ],
            "bonds": rows,
            "stereocenters": stereo,
            "sources": [
                source(p)
                for p in (
                    report_path,
                    selected_path,
                    minimum_path,
                    basis_path,
                    system_path,
                    plan_path,
                    root / "source_snapshot.py",
                )
            ],
        },
    )
    print(
        "Maximum force",
        abs(forces).max(),
        "maximum bond error",
        max(abs(r["error_angstrom"]) for r in rows),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for n in ("archive", "root"):
        p.add_argument("--" + n, type=Path, required=True)
    a = p.parse_args()
    main(a.archive.resolve(), a.root.resolve())
