"""Audit completed training targets; leave validation energies sealed by default.

This verifies execution/provenance and CP arithmetic, not force-field accuracy.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit_output(text, result, *, orbital_basis="cc-pVQZ"):
    expected_nbf = {"cc-pVQZ": "1695", "cc-pVTZ": "882"}.get(orbital_basis)
    if expected_nbf is None:
        raise ValueError("Unsupported orbital basis for this audited molecule")
    """Cross-check raw component energies against the machine-readable CP result."""
    energies = [
        float(x)
        for x in re.findall(r"^\s*Total Energy\s*=\s*([-+0-9.]+)\s*\[Eh\]", text, re.M)
    ]
    if len(energies) != 3 or not all(math.isfinite(x) for x in energies):
        raise ValueError("Expected three finite unscaled MP2 component energies")
    if text.count("Energy and wave function converged.") != 3:
        raise ValueError("Missing converged SCF components")
    if "Counterpoise Corrected (CP) energies" not in text:
        raise ValueError("Missing explicit counterpoise output")
    # This batch is specifically the 36-nucleus capped anti dimer plus water.
    occupations = [
        tuple(map(int, row))
        for row in re.findall(
            r"^\s*PAIRS\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+\s+\d+\s+\d+", text, re.M
        )
    ]
    if occupations != [(1, 5, 4), (20, 74, 54), (21, 79, 58)]:
        raise ValueError("Unexpected frozen-core occupations or component order")
    if re.findall(r"NBF\s*=\s*(\d+)", text) != [expected_nbf] * 3:
        raise ValueError(f"Components do not use the same full {orbital_basis} basis")
    if text.count(f"Blend: {orbital_basis.upper()}\n") != 3:
        raise ValueError("Unexpected orbital basis")
    values = result["variables"]
    expected = [
        values[k]
        for k in (
            "N-BODY (2)@(1, 2) TOTAL ENERGY",
            "N-BODY (1)@(1, 2) TOTAL ENERGY",
            "N-BODY (1, 2)@(1, 2) TOTAL ENERGY",
        )
    ]
    if any(
        not math.isfinite(v) or abs(a - v) > 1e-10 for a, v in zip(energies, expected)
    ):
        raise ValueError("Raw component energies disagree with result variables")
    cp = energies[2] - energies[0] - energies[1]
    reported = [
        result["cp_interaction_hartree"],
        values["CP-CORRECTED INTERACTION ENERGY"],
    ]
    if any(not math.isfinite(v) or abs(cp - v) > 1e-10 for v in reported):
        raise ValueError("Counterpoise subtraction disagrees with reported energy")
    kcal = result["cp_interaction_kcal_mol"]
    if not math.isfinite(kcal) or abs(kcal - cp * 627.5094740631) > 1e-7:
        raise ValueError("Energy conversion disagrees")
    return {"component_energies_hartree": energies, "reconstructed_cp_hartree": cp}


def audit_batch(root):
    root = Path(root)
    batch = json.loads((root / "batch.json").read_text())
    worker_hash = digest(root / "worker.py")
    if worker_hash != batch["worker"]["sha256"]:
        raise ValueError("Worker changed after freezing the batch")
    if batch["energy_scale"] != 1 or batch["distance_offset"] != 0:
        raise ValueError("Unexpected empirical target transformation")
    records = []
    for case in batch["cases"]:
        if case["partition"] != "training":
            continue  # Do not read validation target values during training recovery.
        folder = root / "results" / case["id"]
        if not (folder / "result.json").exists():
            continue
        for source in [case["source_manifest"], *case["geometry_sources"].values()]:
            if digest(source["path"]) != source["sha256"]:
                raise ValueError("Geometry provenance changed")
        result = json.loads((folder / "result.json").read_text())
        if (
            result["case_id"] != case["id"]
            or result["psi4_version"] != "1.11"
            or result["batch_sha256"] != digest(root / "batch.json")
            or result["worker_sha256"] != worker_hash
        ):
            raise ValueError("Result identity/version/provenance mismatch")
        evidence = audit_output((folder / "output.dat").read_text(), result)
        if "reference_kcal_mol" in case:
            delta = abs(result["cp_interaction_kcal_mol"] - case["reference_kcal_mol"])
            if delta > 1e-5:
                raise ValueError("Portability reference failed")
            evidence["portability_difference_kcal_mol"] = delta
        records.append(
            {
                "case_id": case["id"],
                "execution_audit_passed": True,
                "result_sha256": digest(folder / "result.json"),
                "output_sha256": digest(folder / "output.dat"),
                **evidence,
            }
        )
    return {
        "simulation_ready": False,
        "gate_effect": "none",
        "scope": "Training-only execution/provenance/CP arithmetic; not a force-field validation gate",
        "validation_values_read": False,
        "completed_training_audits": records,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    assessment = audit_batch(args.root)
    (args.root / "training_execution_audit.json").write_text(
        json.dumps(assessment, indent=2) + "\n"
    )
    print(f"Audited {len(assessment['completed_training_audits'])} training targets")
