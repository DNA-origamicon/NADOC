"""Independent force-based refinement of frozen water predictions; no QM reads."""

import argparse
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
from openmm import unit as u
from scipy.optimize import minimize

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write


def main(root, predictions):
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
    batch = json.loads(checked(policy["batch"]).read_text())
    previous = {r["case_id"]: r for r in old["records"]}
    records = []
    for case in batch["cases"]:
        xyz = np.array(
            [
                [float(v) for v in line.split()[1:]]
                for line in case["molecule"].splitlines()
                if len(line.split()) == 4
            ]
        )
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
        result = minimize(
            objective,
            initial[moving].ravel(),
            method="BFGS",
            jac=True,
            options={"gtol": 1e-7, "maxiter": 1000},
        )
        after, gradient = objective(result.x)
        displacement = float(
            np.linalg.norm(positions[moving] - positions[parents], axis=1).max()
        )
        force = float(abs(gradient).max())
        polar = after - old["isolated_cpd_energy_kcal_mol"]
        total = polar + previous[case["id"]]["lj_kcal_mol"]
        records.append(
            {
                "case_id": case["id"],
                "partition": case["partition"],
                "optimizer_success": bool(result.success),
                "optimizer_message": str(result.message),
                "iterations": int(result.nit),
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
                "change_from_frozen_prediction_kcal_mol": total
                - previous[case["id"]]["total_interaction_kcal_mol"],
                "numerical_domain_passed": bool(force <= 1e-4 and displacement <= 0.2),
            }
        )
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "qm_values_read": False,
        "scope": "Independent BFGS relaxation of Drudes only, identical frozen potential; unchanged numerical limits. No parameter fitting.",
        "input_predictions": source(predictions),
        "script": source(Path(__file__)),
        "records": records,
    }
    write(root / "assessment.json", report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    args = parser.parse_args()
    main(args.root.resolve(), args.predictions.resolve())
