"""Run the frozen fresh ESP campaign locally, gated by reference portability."""

import argparse
import fcntl
import importlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, checked, write

PSI4 = "/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4"
SERVICE = "nadoc-cpd-fresh-esp-portability-v1.service"


def read_result(folder):
    text = (folder / "output.dat").read_text()
    if (
        "Psi4 exiting successfully" not in text
        or "Energy and wave function converged." not in text
    ):
        raise ValueError("QM output did not complete successfully")
    matches = re.findall(
        r"^NADOC_DIPOLE_AU\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", text, re.M
    )
    if len(matches) != 1:
        raise ValueError("Missing or ambiguous dipole marker")
    dipole = np.array(matches[0], dtype=float)
    esp = np.loadtxt(folder / "grid_esp.dat")
    grid = np.loadtxt(folder / "grid.dat")
    if (
        esp.shape != (len(grid),)
        or not np.isfinite(esp).all()
        or not np.isfinite(dipole).all()
    ):
        raise ValueError("Invalid ESP/dipole values")
    return esp, dipole


def portability_metrics(esp, dipole, reference_esp, reference_dipole):
    if esp.shape != reference_esp.shape or not all(
        np.isfinite(v).all() for v in (esp, dipole, reference_esp, reference_dipole)
    ):
        raise ValueError("Nonfinite or mismatched portability data")
    return {
        "esp_rms_au": float(np.sqrt(np.mean((esp - reference_esp) ** 2))),
        "dipole_vector_error_au": float(np.linalg.norm(dipole - reference_dipole)),
    }


def run(root):
    lock = (root / "worker.lock").open("w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    inventory = json.loads((root / "frozen_inventory.json").read_text())
    checked(inventory["plan"])
    for record in inventory["inputs"] + inventory["grids"]:
        checked(record)
    plan = json.loads((root / "plan.json").read_text())
    frozen = checked(plan["frozen_parameters"])
    fit = json.loads(frozen.read_text())
    charges = json.loads(checked(fit["permanent_charges"]).read_text())["charges_e"]
    deadline = time.monotonic() + 1900
    while True:
        state = subprocess.run(
            [
                "systemctl",
                "--user",
                "show",
                SERVICE,
                "-p",
                "ActiveState",
                "-p",
                "Result",
                "-p",
                "ExecMainStatus",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        if "ActiveState=active" not in state and "ActiveState=activating" not in state:
            break
        if time.monotonic() > deadline:
            raise TimeoutError("Reference still running; do not duplicate")
        time.sleep(10)
    if "Result=success" not in state or "ExecMainStatus=0" not in state:
        raise ValueError("Reference service failed; no fresh cases launched")
    zero_esp, zero_dip = read_result(root / "case-000")
    ref_esp = np.loadtxt(checked(plan["baseline_reference_esp"]))
    ref_dip = np.array(
        json.loads(checked(plan["baseline_reference_audit"]).read_text())["dipole_au"]
    )
    metrics = portability_metrics(zero_esp, zero_dip, ref_esp, ref_dip)
    passed = (
        metrics["esp_rms_au"] <= plan["portability_esp_rms_limit_au"]
        and metrics["dipole_vector_error_au"]
        <= plan["portability_dipole_vector_limit_au"]
    )
    write(
        root / "portability_assessment.json",
        {
            "passed": passed,
            "metrics": metrics,
            "simulation_ready": False,
            "gate_effect": "none",
            "output": source(root / "case-000/output.dat"),
        },
    )
    if not passed:
        raise ValueError("Local DFT portability failed; no fresh cases launched")
    print("Local DFT portability passed", metrics, flush=True)
    results = []
    for case in plan["cases"]:
        checked(plan["frozen_parameters"])
        checked(case["input"])
        folder = root / f"case-{case['case_id']:03d}"
        if (folder / "output.dat").exists():
            raise FileExistsError(
                "Existing fresh output needs reconciliation; refusing overwrite"
            )
        started = time.time()
        write(
            root / "progress.json",
            {
                "state": "running",
                "case_id": case["case_id"],
                "completed_cases": len(results),
                "started_epoch": started,
                "simulation_ready": False,
            },
        )
        with (folder / "runner.log").open("w") as log:
            subprocess.run(
                [
                    PSI4,
                    "-i",
                    "input.dat",
                    "-o",
                    "output.dat",
                    "-n",
                    "8",
                    "-s",
                    str(folder / "scratch"),
                ],
                cwd=folder,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=1800,
            )
        esp, dip = read_result(folder)
        result = {
            "case_id": case["case_id"],
            "dipole_au": dip.tolist(),
            "elapsed_seconds": time.time() - started,
            "input": source(folder / "input.dat"),
            "output": source(folder / "output.dat"),
            "esp": source(folder / "grid_esp.dat"),
            "simulation_ready": False,
            "gate_effect": "none",
        }
        write(folder / "case_audit.json", result)
        results.append(result)
        print("Completed fresh case", case["case_id"], flush=True)
    checked(plan["frozen_parameters"])
    sys.path.insert(0, str(frozen.parent))
    d = importlib.import_module("drude_model")
    assert Path(d.__file__).resolve().parent == frozen.parent
    params = fit["parameters"]
    model = d.AntiCpdDrudeModel(
        charges, params["alpha_angstrom3"], params["thole"], params["anisotropy"]
    )
    model.set_external_charge(0)
    baseline = model.relax()
    grid = np.loadtxt(root / "case-000/grid.dat")
    records = []
    maxdisp = float(baseline["maximum_displacement_angstrom"])
    for case in plan["cases"]:
        esp, dip = read_result(root / f"case-{case['case_id']:03d}")
        qe, qd = esp - zero_esp, dip - zero_dip
        pe, pd, state = model.response(
            np.array(case["position_angstrom"]), grid, baseline
        )
        if np.linalg.norm(qe) == 0 or np.linalg.norm(qd) == 0:
            raise ValueError("Zero target response")
        records.append(
            {
                "case_id": case["case_id"],
                "surface_scale": case["surface_scale"],
                "response_relative_rms": float(
                    np.linalg.norm(pe - qe) / np.linalg.norm(qe)
                ),
                "dipole_change_relative_error": float(
                    np.linalg.norm(pd - qd) / np.linalg.norm(qd)
                ),
            }
        )
        maxdisp = max(maxdisp, float(state["maximum_displacement_angstrom"]))
    response = float(
        np.sqrt(np.mean([r["response_relative_rms"] ** 2 for r in records]))
    )
    dipole = float(
        np.sqrt(np.mean([r["dipole_change_relative_error"] ** 2 for r in records]))
    )
    ratio = response / fit["fit_metrics"]["fit_response_relative_rms"]
    acc = plan["acceptance"]
    checks = {
        "all_24_cases": len(records) == 24,
        "fresh_response": response <= acc["holdout_response_relative_rms_max"],
        "fresh_dipole_response": dipole
        <= acc["holdout_dipole_change_relative_rms_max"],
        "fresh_to_training_ratio": ratio
        <= acc["holdout_to_fit_relative_rms_ratio_max"],
        "drude_domain": maxdisp
        <= plan["bounds"]["maximum_relaxed_drude_displacement_angstrom"],
    }
    write(
        root / "assessment.json",
        {
            "passed_fresh_response_checks": all(checks.values()),
            "checks": checks,
            "metrics": {
                "response_relative_rms": response,
                "dipole_change_relative_rms": dipole,
                "fresh_to_training_ratio": ratio,
                "maximum_drude_displacement_angstrom": maxdisp,
            },
            "records": records,
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": "Fresh perturbations on one capped anti-CPD geometry; not conformer, bonded, water, nucleotide or DNA validation",
            "frozen_parameters": plan["frozen_parameters"],
            "model": source(frozen.parent / "drude_model.py"),
            "runner": source(Path(__file__)),
        },
    )
    write(
        root / "progress.json",
        {
            "state": "completed",
            "completed_cases": len(results),
            "simulation_ready": False,
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    args = p.parse_args()
    try:
        run(args.root.resolve())
    except Exception as error:
        write(
            args.root / "failure.json",
            {
                "error_type": type(error).__name__,
                "reason": str(error),
                "simulation_ready": False,
                "gate_effect": "none",
            },
        )
        raise
