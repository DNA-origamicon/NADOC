"""Run two independently audited anti sugar targets; isolated from release assets."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from experiments.cpd_published_comparator.trigger_dna_review import save

QM = Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python")
SEED = REPO / ".development-artifacts/cpd-repaired-anti-fragments-v1"


def prepare(root):
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError(
            "Cannot prepare unattended QM without the completion executable"
        )
    root.mkdir(exist_ok=False, parents=True)
    shutil.copy2(__file__, root / "executed_source.py")
    write(
        root / "watcher_config.json", {"codex_executable": str(Path(codex).resolve())}
    )
    old_plan = json.loads((SEED / "qm_plan.json").read_text())
    assessment = json.loads(checked(old_plan["seed_assessment"]).read_text())
    assert assessment["all_fragment_seed_checks_passed"]
    for row in assessment["records"]:
        model = json.loads(checked(row["model_manifest"]).read_text())
        for record in model["outputs"].values():
            checked(record)
        folder = root / f"endpoint-{row['endpoint']}"
        folder.mkdir()
        subset = {**assessment, "records": [row]}
        write(folder / "seed_assessment.json", subset)
        shutil.copy2(
            REPO / "experiments/cpd_drude_recovery/optimize_repaired_fragments.py",
            folder / "qm_worker.py",
        )
        plan = {
            **old_plan,
            "worker": source(folder / "qm_worker.py"),
            "seed_assessment": source(folder / "seed_assessment.json"),
            "parent_seed_assessment": old_plan["seed_assessment"],
            "scope": "Fresh optimization from screened anti seed; shared bonded QM target, not an accepted additive or Drude model.",
        }
        write(folder / "qm_plan.json", plan)
    write(
        root / "campaign_plan.json",
        {
            "product_id": "tt-cpd-cis-anti-i",
            "simulation_ready": False,
            "stage": "two neutral 49-atom glycosidic targets, frozen-core DF-MP2/6-31G(d)",
            "expected_seconds": 21600,
            "overdue_seconds": 32400,
            "resources": "two workers, four threads and 4 GiB Psi4 each; 14 GiB service cap; 12-hour hard limit",
            "next_gates": [
                "native convergence and independent sugar/lesion audit",
                "minimum certification and additive core/boundary joint fit",
                "independent conformer/water regression and engine equivalence",
                "full nucleotide then interstrand-context replicated explicit-solvent validation",
            ],
            "source": source(SEED / "qm_plan.json"),
        },
    )


def run(root):
    state = {
        "state": "running",
        "pid": os.getpid(),
        "records": [],
        "started_at": time.time(),
        "simulation_ready": False,
    }
    save(root / "status.json", state)
    # Arm supervision before starting any expensive calculation.
    watcher = subprocess.Popen(
        [
            "/usr/bin/python3",
            str(REPO / "experiments/cpd_anti_additive/watch.py"),
            "--root",
            str(root),
            "--thread",
            os.environ["CODEX_THREAD_ID"],
        ]
    )
    deadline = time.monotonic() + 15
    while not (root / "completion_wake.json").exists():
        if watcher.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("Completion watcher did not arm")
        time.sleep(0.1)

    def endpoint(number):
        folder = root / f"endpoint-{number}"
        with (folder / "run.log").open("w") as log:
            result = subprocess.run(
                [str(QM), str(folder / "qm_worker.py")],
                cwd=folder,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            audit = subprocess.run(
                [
                    str(QM),
                    str(
                        REPO
                        / "experiments/cpd_drude_recovery/audit_repaired_fragment_qm.py"
                    ),
                    "--root",
                    str(folder),
                ],
                cwd=REPO,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        path = folder / "independent_qm_geometry_audit.json"
        report = json.loads(path.read_text()) if path.exists() else {}
        return {
            "endpoint": number,
            "worker_exit": result.returncode,
            "audit_exit": audit.returncode,
            "passed": result.returncode == 0
            and audit.returncode == 0
            and report.get("all_endpoints_passed") is True,
            "audit": source(path) if path.exists() else None,
        }

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            state["records"] = list(pool.map(endpoint, (1, 2)))
        state["state"] = (
            "complete" if all(r["passed"] for r in state["records"]) else "failed"
        )
    except Exception as exc:
        state.update(state="failed", error=repr(exc))
        raise
    finally:
        state["finished_at"] = time.time()
        save(root / "status.json", state)
    watcher.wait(timeout=45)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    (prepare if args.prepare else run)(args.root.resolve())
