"""Stationary-force refinement of frozen water predictions; no QM reads."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from openmm import unit as u
from scipy.optimize import root as solve_root

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write


def main(root, predictions, design):
    root.mkdir(exist_ok=False)
    old = json.loads(predictions.read_text())
    policy = json.loads(checked(old["policy"]).read_text())
    frozen = checked(policy["frozen"])
    sys.path.insert(0, str(frozen.parent))
    evaluator = checked(policy["adapted_evaluator"])
    spec = importlib.util.spec_from_file_location(
        "water_refinement_evaluator", evaluator
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.PolarizationEnergy()
    moving = np.array([*model.cpd_drudes, model.water_drude])
    parents = np.array([*range(len(model.cpd_drudes)), model.water_o])
    checked(policy["batch"])
    batch = json.loads(design.read_text())
    checked(batch["source_batch"])
    checked(batch["source_native_pairs"])
    previous = {r["case_id"]: r for r in old["records"]}
    records = []
    for case in batch["cases"]:
        xyz = np.array(case["geometry_angstrom"])
        assert np.max(abs(xyz[:36] - model.atom_xyz)) < 1e-9
        model._minimize(model._positions(xyz[-3:]))
        positions = np.asarray(
            model.context.getState(getPositions=True)
            .getPositions(asNumpy=True)
            .value_in_unit(u.angstrom)
        ).copy()
        initial = positions.copy()

        def objective(x):
            positions[moving] = x.reshape(-1, 3)
            model.context.setPositions(positions * u.angstrom)
            state = model.context.getState(getEnergy=True, getForces=True)
            energy = state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
            forces = np.asarray(
                state.getForces(asNumpy=True).value_in_unit(
                    u.kilocalorie_per_mole / u.angstrom
                )
            )
            return float(energy), -forces[moving].ravel()

        before, gradient = objective(initial[moving].ravel())
        result = solve_root(
            lambda x: objective(x)[1],
            initial[moving].ravel(),
            method="hybr",
            options={"xtol": 1e-10},
        )
        curvatures = []
        for step in (1e-5, 5e-6):
            hessian = np.empty((len(result.x), len(result.x)))
            for j in range(len(result.x)):
                plus = result.x.copy()
                minus = result.x.copy()
                plus[j] += step
                minus[j] -= step
                hessian[:, j] = (objective(plus)[1] - objective(minus)[1]) / (2 * step)
            curvatures.append(
                float(np.linalg.eigvalsh((hessian + hessian.T) / 2).min())
            )
        after, gradient = objective(result.x)
        displacement = float(
            np.linalg.norm(positions[moving] - positions[parents], axis=1).max()
        )
        force = float(abs(gradient).max())
        polar = after - old["isolated_cpd_energy_kcal_mol"]
        lj = 0.0
        for i, pair in enumerate(policy["pairs"].values()):
            six = (pair["rmin_angstrom"] / np.linalg.norm(xyz[i] - xyz[36])) ** 6
            lj += pair["epsilon_kcal_mol"] * (six**2 - 2 * six)
        total = polar + lj
        records.append(
            {
                "case_id": case["id"],
                "partition": "prospective_radial_training_geometry",
                "contact_distance_angstrom": case["contact_distance_angstrom"],
                "lj_kcal_mol": float(lj),
                "electrostatic_and_induction_kcal_mol": float(polar),
                "optimizer_success": bool(result.success),
                "optimizer_message": str(result.message),
                "function_evaluations": int(result.nfev),
                "minimum_drude_hessian_eigenvalues_kcal_mol_angstrom2": curvatures,
                "energy_change_kcal_mol": after - before,
                "maximum_drude_force_kcal_mol_angstrom": force,
                "maximum_drude_displacement_angstrom": displacement,
                "maximum_fixed_site_movement_angstrom": float(
                    abs(
                        positions[np.setdiff1d(np.arange(len(positions)), moving)]
                        - initial[np.setdiff1d(np.arange(len(positions)), moving)]
                    ).max()
                ),
                "total_interaction_kcal_mol": total,
                "change_from_original_1p8_prediction_kcal_mol": total
                - previous[case["source_case_id"]]["total_interaction_kcal_mol"]
                if case["reuses_existing_geometry"]
                else None,
                "numerical_domain_passed": bool(
                    force <= 1e-4 and displacement <= 0.2 and min(curvatures) > 0
                ),
            }
        )
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "qm_values_read": False,
        "scope": "Independent stationary-force solution and two-step curvature check of Drudes only, identical frozen potential; unchanged numerical limits. No parameter fitting.",
        "input_predictions": source(predictions),
        "radial_design": source(design),
        "script": source(Path(__file__)),
        "records": records,
    }
    write(root / "assessment.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    args = parser.parse_args()
    main(args.root.resolve(), args.predictions.resolve(), args.design.resolve())
