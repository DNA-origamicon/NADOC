"""Run and independently audit a prospectively registered endpoint-2 retry."""

import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_drude_recovery.campaign import source, write, checked


def prepare(root):
    root.mkdir(exist_ok=False)
    origin = REPO / ".development-artifacts/cpd-anti-additive-boundary-qm-v2/endpoint-2"
    recovery = REPO / ".development-artifacts/cpd-anti-additive-next-v2"
    audit = json.loads((recovery / "endpoint2_restart_audit.json").read_text())
    assert audit["selected"]["passed"]
    checked(audit["seed"])
    plan = json.loads((origin / "qm_plan.json").read_text())
    worker = (
        REPO / "experiments/cpd_drude_recovery/optimize_repaired_fragments.py"
    ).read_text()
    worker = worker.replace(
        "seed = checked(manifest['outputs']['xyz'])",
        "checked(plan['restart_audit'])\n    seed = checked(plan['restart_seed'])",
    )
    (root / "qm_worker.py").write_text(worker)
    plan.update(
        worker=source(root / "qm_worker.py"),
        restart_seed=source(recovery / "endpoint2_restart.xyz"),
        restart_audit=source(recovery / "endpoint2_restart_audit.json"),
        optimizer_options={
            **plan["optimizer_options"],
            "opt_coordinates": "cartesian",
            "intrafrag_step_limit": 0.05,
            "intrafrag_step_limit_max": 0.1,
            "dynamic_level": 0,
        },
        scope="Unconstrained Cartesian RFO retry from independently screened evaluated step 25; identical electronic method and GAU_TIGHT thresholds. No endpoint-1 rerun.",
        resource_limits=dict(
            threads=4, psi4_memory_gib=4, cgroup_memory_gib=6, runtime_hours=12
        ),
    )
    write(root / "qm_plan.json", plan)
    (root / "runner_snapshot.py").write_text(Path(__file__).read_text())


def run(root):
    python = "/home/jojo/miniforge3/envs/nadoc-qm/bin/python"
    p = subprocess.run([python, str(root / "qm_worker.py")], cwd=root)
    a = subprocess.run(
        [
            python,
            str(REPO / "experiments/cpd_drude_recovery/audit_repaired_fragment_qm.py"),
            "--root",
            str(root),
        ],
        cwd=REPO,
    )
    result = json.loads((root / "independent_qm_geometry_audit.json").read_text())
    write(
        root / "terminal_assessment.json",
        dict(
            worker_exit=p.returncode,
            audit_exit=a.returncode,
            geometry_passed=result["all_endpoints_passed"],
            minimum_certified=False,
            simulation_ready=False,
        ),
    )
    if p.returncode or a.returncode or not result["all_endpoints_passed"]:
        raise RuntimeError("Endpoint-2 retry failed; preserve native outputs and audit")


if __name__ == "__main__":
    root = Path(sys.argv[2]).resolve()
    (prepare if sys.argv[1] == "prepare" else run)(root)
