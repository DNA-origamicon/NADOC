"""Seal completed fresh response evidence without changing scientific acceptance."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from experiments.cpd_drude_recovery.run_fresh_esp import read_result


def main(root):
    inventory = json.loads((root / "frozen_inventory.json").read_text())
    plan_path = checked(inventory["plan"])
    for r in inventory["inputs"] + inventory["grids"]:
        checked(r)
    plan = json.loads(plan_path.read_text())
    frozen = checked(plan["frozen_parameters"])
    fit = json.loads(frozen.read_text())
    checked(fit["permanent_charges"])
    assessment_path = root / "assessment.json"
    a = json.loads(assessment_path.read_text())
    checked(a["frozen_parameters"])
    checked(a["model"])
    checked(a["runner"])
    assert len(a["records"]) == 24
    assert {r["case_id"] for r in a["records"]} == {r["case_id"] for r in plan["cases"]}
    sources = [
        source(p)
        for p in (
            root / "frozen_inventory.json",
            plan_path,
            assessment_path,
            root / "portability_assessment.json",
            Path(__file__),
        )
    ]
    for case in plan["cases"]:
        folder = root / f"case-{case['case_id']:03d}"
        path = folder / "case_audit.json"
        audit = json.loads(path.read_text())
        assert audit["case_id"] == case["case_id"]
        for key in ("input", "output", "esp"):
            checked(audit[key])
        _, dip = read_result(folder)
        assert np.allclose(dip, audit["dipole_au"], rtol=0, atol=1e-12)
        sources += [source(path), audit["input"], audit["output"], audit["esp"]]
    read_result(root / "case-000")
    sources += [
        source(root / "case-000" / n)
        for n in ("input.dat", "output.dat", "grid.dat", "grid_esp.dat")
    ]
    metrics = a["metrics"]
    response = float(
        np.sqrt(np.mean([r["response_relative_rms"] ** 2 for r in a["records"]]))
    )
    dipole = float(
        np.sqrt(np.mean([r["dipole_change_relative_error"] ** 2 for r in a["records"]]))
    )
    assert abs(response - metrics["response_relative_rms"]) < 1e-12
    assert abs(dipole - metrics["dipole_change_relative_rms"]) < 1e-12
    ratio = response / fit["fit_metrics"]["fit_response_relative_rms"]
    assert abs(ratio - metrics["fresh_to_training_ratio"]) < 1e-12
    acc = plan["acceptance"]
    checks = {
        "all_24_cases": True,
        "fresh_response": response <= acc["holdout_response_relative_rms_max"],
        "fresh_dipole_response": dipole
        <= acc["holdout_dipole_change_relative_rms_max"],
        "fresh_to_training_ratio": ratio
        <= acc["holdout_to_fit_relative_rms_ratio_max"],
        "drude_domain": metrics["maximum_drude_displacement_angstrom"]
        <= plan["bounds"]["maximum_relaxed_drude_displacement_angstrom"],
    }
    assert (
        checks == a["checks"]
        and all(checks.values()) == a["passed_fresh_response_checks"]
    )
    write(
        root / "sealed_evidence.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": a["scope"],
            "provenance_and_aggregation_audit_passed": True,
            "fresh_response_checks_passed": all(checks.values()),
            "metrics": metrics,
            "checks": checks,
            "sources": sources,
        },
    )
    print(json.dumps({"checks": checks, "metrics": metrics}, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    main(p.parse_args().root.resolve())
