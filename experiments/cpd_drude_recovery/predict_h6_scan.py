"""Record frozen-model scan predictions before using new QM scan results."""

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


def main(root, recovery):
    destination = root / "frozen_mm_predictions.json"
    if destination.exists():
        raise FileExistsError(destination)
    plan = json.loads((root / "plan.json").read_text())
    results = []
    for record in plan["frozen_models"]:
        fit_path = checked(record)
        stage = fit_path.parent
        fit = json.loads(fit_path.read_text())
        policy = json.loads((stage / "policy.json").read_text())
        model = AdiabaticNonbonded(recovery, checked(policy["electrostatics"]))
        system_path = stage / "basis/linear_fit_system.xml"
        system = mm.XmlSerializer.deserialize(system_path.read_text())
        integrator = mm.VerletIntegrator(0.001)
        context = mm.Context(
            system, integrator, mm.Platform.getPlatformByName("Reference")
        )
        for parameter in fit["parameters"]:
            context.setParameter(parameter["name"], parameter["coefficient"])
        rows = []
        for case in plan["cases"]:
            coords = np.array(
                [
                    [float(v) for v in line.split()[1:]]
                    for line in case["molecule"].splitlines()
                    if len(line.split()) == 4
                ]
            )
            assert coords.shape == (36, 3)
            try:
                energy, gradient = model.energy_gradient(coords)
                context.setPositions(coords * u.angstrom)
                state = context.getState(getEnergy=True, getForces=True)
                energy += state.getPotentialEnergy().value_in_unit(
                    u.kilocalorie_per_mole
                )
                gradient = gradient.reshape(36, 3) - np.asarray(
                    state.getForces(asNumpy=True).value_in_unit(
                        u.kilocalorie_per_mole / u.angstrom
                    )
                )
                rows.append(
                    {
                        "case_id": case["id"],
                        "status": "evaluated",
                        "energy_kcal_mol": float(energy),
                        "gradient_kcal_mol_angstrom": gradient.tolist(),
                        "projected_gradient_kcal_mol_angstrom": float(
                            np.sum(gradient * np.array(case["direction"]))
                        )
                        if "direction" in case
                        else None,
                    }
                )
            except ValueError as error:
                rows.append(
                    {
                        "case_id": case["id"],
                        "status": "outside_evaluator_domain",
                        "reason": str(error),
                    }
                )
        assert rows[0]["status"] == "evaluated"
        for row in rows:
            if row["status"] == "evaluated":
                row["relative_energy_kcal_mol"] = (
                    row["energy_kcal_mol"] - rows[0]["energy_kcal_mol"]
                )
        results.append(
            {
                "fit": record,
                "bonded_system": source(system_path),
                "electrostatics": policy["electrostatics"],
                "rows": rows,
            }
        )
        del context, integrator, model
    write(
        destination,
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "plan": source(root / "plan.json"),
            "code": source(Path(__file__)),
            "models": results,
            "qm_scan_targets_read": False,
        },
    )
    print("Frozen predictions recorded for", len(results), "models")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--recovery", type=Path, required=True)
    a = p.parse_args()
    main(a.root.resolve(), a.recovery.resolve())
