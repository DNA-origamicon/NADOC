"""Measure the memory-efficient four-worker/three-thread alternative."""

import json
import os
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.run_local_photoproduct_hessian import _run_task
from experiments.cpd_drude_recovery.campaign import write, source

root = Path(sys.argv[1]).resolve()
original = Path(
    ".development-artifacts/cpd-anti-additive-next-v2/endpoint1-hessian"
).resolve()
shutil.copytree(original, root)
(root / "benchmark_source.py").write_text(Path(__file__).read_text())
plan_path = root / "distributed_hessian_plan.json"
plan = json.loads(plan_path.read_text())
task = plan["tasks"][0]
os.environ["OMP_NUM_THREADS"] = "3"
r = _run_task(
    task=task,
    plan_path=plan_path,
    root=root,
    qm_python=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python"),
    scratch_root=root / "scratch",
    threads=3,
    memory_gib=3,
)
run = root / task["run_record"]["path"]
native = json.loads(run.read_text())
write(
    root / "assessment.json",
    dict(
        threads=3,
        wall_seconds=r["elapsed_seconds"],
        gradient_seconds=native["execution"]["elapsed_seconds"],
        run_record=source(run),
    ),
)
