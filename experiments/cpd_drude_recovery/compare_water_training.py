"""Compare frozen native-LJ predictions with audited training-only CP energies."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write


def main(root, predictions, audit, refinement):
    root.mkdir(exist_ok=False)
    pred = json.loads(predictions.read_text())
    checked(pred["policy"])
    stationary = json.loads(refinement.read_text())
    assert checked(stationary["input_predictions"]) == predictions.resolve()
    refined = {r["case_id"]: r for r in stationary["records"]}
    training = {
        r["case_id"]: r for r in pred["records"] if r["partition"] == "training"
    }
    targets = json.loads(audit.read_text())
    assert targets["validation_values_read"] is False
    records = []
    for target in targets["completed_training_audits"]:
        assert target["execution_audit_passed"]
        case = training[target["case_id"]]
        result = audit.parent / "results" / case["case_id"] / "result.json"
        checked({"path": str(result), "sha256": target["result_sha256"]})
        mm = refined[case["case_id"]]
        assert mm["numerical_domain_passed"]
        qm = target["reconstructed_cp_hartree"] * 627.5094740631
        records.append(
            {
                "case_id": case["case_id"],
                "qm_cp_kcal_mol": qm,
                "mm_kcal_mol": mm["total_interaction_kcal_mol"],
                "mm_minus_qm_kcal_mol": mm["total_interaction_kcal_mol"] - qm,
            }
        )
    errors = np.array([r["mm_minus_qm_kcal_mol"] for r in records])
    write(
        root / "assessment.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "validation_values_read": False,
            "scope": "Partial training comparison at frozen 1.8 A geometries, native LJ and corrected frozen electrostatics. No fit, shift, target scaling, or validation claim.",
            "sources": [
                source(p) for p in (predictions, audit, refinement, Path(__file__))
            ],
            "completed_training_cases": len(records),
            "planned_training_cases": len(training),
            "rmse_kcal_mol": float(np.sqrt(np.mean(errors**2)))
            if len(errors)
            else None,
            "records": records,
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for name in ("root", "predictions", "audit", "refinement"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    main(
        a.root.resolve(),
        a.predictions.resolve(),
        a.audit.resolve(),
        a.refinement.resolve(),
    )
