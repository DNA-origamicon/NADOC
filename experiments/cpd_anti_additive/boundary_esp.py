"""Local additive anti electrostatic targets for both audited sugar fragments."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from backend.parameterization.photoproduct_esp import generate_esp_job, audit_esp_job
from backend.parameterization.photoproduct_qm import run_psi4_job
from experiments.cpd_anti_additive.core_baseline import checked, source, write

ART = REPO / ".development-artifacts"


def prepare(root):
    root.mkdir(exist_ok=False)
    shutil.copyfile(__file__, root / "executed_source.py")
    cases = []
    for endpoint, parent, frequency in [
        (
            1,
            ART / "cpd-anti-additive-next-v2/endpoint1_optimized_model_audit.json",
            ART / "cpd-anti-additive-next-v2/endpoint1-frequency/frequency_audit.json",
        ),
        (
            2,
            ART / "cpd-anti-endpoint2-frequency-v2/optimized_model_audit.json",
            ART / "cpd-anti-endpoint2-frequency-v2/frequency/frequency_audit.json",
        ),
    ]:
        a = json.loads(parent.read_text())
        f = json.loads(frequency.read_text())
        assert f["status"] == "passed_candidate_harmonic_minimum"
        assert f["model_id"] == a["model_id"]
        for key in ["cartesian_hessian", "output", "effective_run_record"]:
            checked(f[key])
        checked(a["independent_audit"])
        generate_esp_job(
            product_id=a["product_id"],
            model_id=a["model_id"],
            xyz_path=checked(a["optimized_xyz"]),
            atom_map=a["atom_map"],
            parent_manifest_path=parent,
            output_dir=root / f"endpoint-{endpoint}",
            memory_gib=3,
            threads=4,
            protocol_path=REPO
            / "backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json",
        )
        cases.append(
            dict(endpoint=endpoint, frequency=source(frequency), parent=source(parent))
        )
    write(
        root / "plan.json",
        dict(
            cases=cases,
            scope="HF/6-31G(d) ESP and dipole training targets; not charge validation or release",
            simulation_ready=False,
        ),
    )


def run(root):
    os.sched_setaffinity(0, set(range(8)))
    plan = json.loads((root / "plan.json").read_text())

    def one(c):
        checked(c["frequency"])
        checked(c["parent"])
        folder = root / f"endpoint-{c['endpoint']}"
        run_psi4_job(
            job_dir=folder,
            psi4_executable=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/psi4"),
            scratch_dir=root / f"scratch-{c['endpoint']}",
        )
        audit = audit_esp_job(folder)
        assert audit["status"] == "complete_candidate"
        assert audit["dipole"]["required"] and audit["dipole"]["vector"] is not None
        return audit

    with ThreadPoolExecutor(max_workers=2) as pool:
        records = list(pool.map(one, plan["cases"]))
    write(root / "assessment.json", dict(records=records, simulation_ready=False))
    print([r["status"] for r in records], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["prepare", "run"])
    p.add_argument("root", type=Path)
    a = p.parse_args()
    (prepare if a.action == "prepare" else run)(a.root.resolve())
