"""Compare independent scan outputs against frozen predictions, without refitting."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, checked, write

HARTREE_KCAL = 627.5094740631
BOHR_ANGSTROM = 0.529177210903


def qm_values(result, direction):
    energy = float(result["energy_hartree"])
    gradient = np.asarray(result["gradient_hartree_bohr"], dtype=float)
    direction = np.asarray(direction, dtype=float)
    if (
        gradient.shape != (36, 3)
        or direction.shape != gradient.shape
        or not np.isfinite(gradient).all()
        or not np.isfinite(direction).all()
        or not np.isfinite(energy)
    ):
        raise ValueError("Invalid scan energy, gradient or coordinate direction")
    return energy * HARTREE_KCAL, float(
        np.sum(gradient * direction) * HARTREE_KCAL / BOHR_ANGSTROM
    )


def main(root):
    plan_path = root / "plan.json"
    plan = json.loads(plan_path.read_text())
    predictions_path = root / "frozen_mm_predictions.json"
    predictions = json.loads(predictions_path.read_text())
    if checked(predictions["plan"]) != plan_path.resolve():
        raise ValueError("Prediction plan mismatch")
    for model in predictions["models"]:
        checked(model["fit"])
        checked(model["bonded_system"])
        checked(model["electrostatics"])
    checked(plan["worker"])
    reference = json.loads(checked(plan["reference"]).read_text())["properties"]
    hessian = (
        np.asarray(reference["return_hessian"]).reshape(108, 108)
        * HARTREE_KCAL
        / BOHR_ANGSTROM**2
    )
    missing = []
    qms = {}
    sources = []
    for case in plan["cases"]:
        folder = root / case["id"]
        result_path = folder / "result.json"
        if not result_path.exists():
            missing.append(case["id"])
            continue
        result = json.loads(result_path.read_text())
        if (
            result["case_id"] != case["id"]
            or result["plan_sha256"] != source(plan_path)["sha256"]
            or result["worker_sha256"] != plan["worker"]["sha256"]
            or result["psi4_version"] != "1.11"
        ):
            raise ValueError("QM scan provenance mismatch")
        # Energy/gradient marker is written only after the native gradient returns.
        text = (folder / "output.dat").read_text()
        if "Energy and wave function converged." not in text or "DF-MP2" not in text:
            raise ValueError("Missing native SCF/MP2 evidence")
        qm_values(result, np.zeros((36, 3)))
        qms[case["id"]] = result
        sources.extend([source(result_path), source(folder / "output.dat")])
    models = []
    if "reference" in qms:
        zero = qms["reference"]
        e0 = float(zero["energy_hartree"]) * HARTREE_KCAL
        g0 = np.asarray(zero["gradient_hartree_bohr"]) * HARTREE_KCAL / BOHR_ANGSTROM
        for model in predictions["models"]:
            lookup = {row["case_id"]: row for row in model["rows"]}
            rows = []
            for case in plan["cases"][1:]:
                if case["id"] not in qms:
                    continue
                direction = np.asarray(case["direction"])
                delta = case["displacement_angstrom"]
                q = direction.ravel()
                energy, gradient = qm_values(qms[case["id"]], direction)
                curvature = float(q @ hessian @ q)
                slope0 = float(np.sum(g0 * direction))
                row = {
                    "case_id": case["id"],
                    "endpoint": case["endpoint"],
                    "regime": case["regime"],
                    "displacement_angstrom": delta,
                    "qm_relative_energy_kcal_mol": energy - e0,
                    "qm_projected_gradient_kcal_mol_angstrom": gradient,
                    "harmonic_reference_relative_energy_kcal_mol": slope0 * delta
                    + 0.5 * curvature * delta**2,
                    "harmonic_reference_projected_gradient_kcal_mol_angstrom": slope0
                    + curvature * delta,
                }
                mm = lookup[case["id"]]
                if mm["status"] == "evaluated":
                    row.update(
                        mm_relative_energy_kcal_mol=mm["relative_energy_kcal_mol"],
                        energy_error_kcal_mol=mm["relative_energy_kcal_mol"]
                        - (energy - e0),
                        projected_gradient_error_kcal_mol_angstrom=mm[
                            "projected_gradient_kcal_mol_angstrom"
                        ]
                        - gradient,
                    )
                else:
                    row.update(mm_status=mm["status"], reason=mm["reason"])
                rows.append(row)
            groups = []
            for endpoint in [1, 2]:
                for regime in ["near_equilibrium", "extended_challenge"]:
                    available = [
                        r
                        for r in rows
                        if r["endpoint"] == endpoint and r["regime"] == regime
                    ]
                    scored = [r for r in available if "energy_error_kcal_mol" in r]
                    item = {
                        "endpoint": endpoint,
                        "regime": regime,
                        "qm_points": len(available),
                        "mm_points": len(scored),
                        "expected_points": 6 if regime == "near_equilibrium" else 2,
                    }
                    if scored:
                        for key in [
                            "energy_error_kcal_mol",
                            "projected_gradient_error_kcal_mol_angstrom",
                        ]:
                            v = np.array([r[key] for r in scored])
                            item[key + "_rms"] = float(np.sqrt(np.mean(v**2)))
                            item[key + "_max_abs"] = float(abs(v).max())
                    groups.append(item)
            models.append({"fit": model["fit"], "rows": rows, "groups": groups})
    report = {
        "simulation_ready": False,
        "gate_effect": "none",
        "status": "complete_diagnostic_no_acceptance_asserted"
        if not missing
        else "incomplete_diagnostic",
        "complete_qm_coverage": not missing,
        "missing_cases": missing,
        "completed_qm_cases": len(qms),
        "models": models,
        "plan": source(plan_path),
        "predictions": source(predictions_path),
        "sources": sources,
        "code": source(Path(__file__)),
        "interpretation": "New target evidence, no refitting. Partial aggregate errors are descriptive only; all near and extended points must remain reported.",
    }
    write(root / "scan_assessment.json", report)
    print("QM coverage", len(qms), "/", len(plan["cases"]))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    main(p.parse_args().root.resolve())
