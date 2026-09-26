"""Measure identical real Hessian gradients at 2/4/8 CPU threads, retaining results."""

import json
import os
from pathlib import Path
import shutil
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.run_local_photoproduct_hessian import _run_task
from experiments.cpd_drude_recovery.campaign import write, source


def main(root):
    original = Path(
        ".development-artifacts/cpd-anti-additive-next-v2/endpoint1-hessian"
    ).resolve()
    root.mkdir(exist_ok=False)
    shutil.copy2(__file__, root / "executed_source.py")
    rows = []
    for threads in (2, 4, 8):
        folder = root / f"threads-{threads}"
        shutil.copytree(original, folder)
        plan_path = folder / "distributed_hessian_plan.json"
        plan = json.loads(plan_path.read_text())
        task = plan["tasks"][0]
        os.environ["OMP_NUM_THREADS"] = str(threads)
        start = time.monotonic()
        result = _run_task(
            task=task,
            plan_path=plan_path,
            root=folder,
            qm_python=Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python"),
            scratch_root=folder / "scratch",
            threads=threads,
            memory_gib=3,
        )
        run = folder / task["run_record"]["path"]
        native = json.loads(run.read_text())
        rows.append(
            dict(
                threads=threads,
                wall_seconds=time.monotonic() - start,
                gradient_seconds=native["execution"]["elapsed_seconds"],
                result=result,
                run_record=source(run),
            )
        )
        write(root / "progress.json", dict(records=rows))
    write(
        root / "assessment.json",
        dict(
            records=rows,
            scope="Same hash-identical reference gradient, same memory/method. One timing per setting; concurrent throughput must be checked separately.",
            simulation_ready=False,
        ),
    )
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
