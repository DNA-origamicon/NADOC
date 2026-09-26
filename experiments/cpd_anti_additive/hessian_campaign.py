"""Select CPU layout using useful gradient batches, then finish/audit the Hessian."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from scripts.run_local_photoproduct_hessian import _run_task, run_local_batch
from backend.parameterization.photoproduct_distributed_hessian import (
    checkpoint_distributed_hessian_pairs,
)
from experiments.cpd_drude_recovery.campaign import write, source

ART = REPO / ".development-artifacts"
QM = Path("/home/jojo/miniforge3/envs/nadoc-qm/bin/python")


def wait_for_service(root):
    status = json.loads((root / "status.json").read_text())
    if status["state"] not in ("complete", "failed"):
        # System Python supplies pidfd_open, unlike the pinned conda QM Python.
        code = "import os,select,sys\ntry: f=os.pidfd_open(int(sys.argv[1]))\nexcept ProcessLookupError: sys.exit(0)\nselect.select([f],[],[])\nos.close(f)"
        subprocess.run(["/usr/bin/python3", "-c", code, str(status["pid"])], check=True)
    status = json.loads((root / "status.json").read_text())
    if status["state"] != "complete":
        raise RuntimeError(f"Prerequisite benchmark failed: {root}")


def main(root):
    root.mkdir(exist_ok=False)
    shutil.copy2(__file__, root / "executed_source.py")
    write(root / "stage.json", dict(stage="waiting_for_scaling_results"))
    for name in ("cpd-anti-scaling-service-v1", "cpd-anti-scaling3-service-v1"):
        wait_for_service(ART / name)
    serial = json.loads(
        (ART / "cpd-anti-thread-scaling-v1/assessment.json").read_text()
    )["records"]
    serial.append(json.loads((ART / "cpd-anti-thread3-v1/assessment.json").read_text()))
    plan_path = (
        ART
        / "cpd-anti-additive-next-v2/endpoint1-hessian/distributed_hessian_plan.json"
    ).resolve()
    plan = json.loads(plan_path.read_text())
    folder = plan_path.parent
    checkpoint_distributed_hessian_pairs(
        source_plan_path=(
            ART / "cpd-anti-thread-scaling-v1/threads-2/distributed_hessian_plan.json"
        ).resolve(),
        destination_plan_path=plan_path,
        output_path=root / "reference_checkpoint.json",
    )
    # Keep endpoint-2 on physical cores 12..15. No SMT siblings in the Hessian pilot.
    os.sched_setaffinity(0, set(range(12)))
    pilots = []
    offset = 1
    timings = {r["threads"]: r["wall_seconds"] for r in serial}
    layouts = [(3, 4), (4, 3)]
    if 4 / timings[2] > max(3 / timings[4], 4 / timings[3]) * 1.05:
        layouts.append((4, 2))
    write(
        root / "policy.json",
        dict(
            serial_timings=serial,
            pilot_layouts=layouts,
            selection="Prefer 3x4 unless measured concurrent throughput improves by more than 10%; maximum four 3-GiB workers; reserve four physical cores for endpoint-2.",
            resources="Hessian cores 0..11, optimization cores 12..15; one BLAS thread per worker; no SMT oversubscription",
            simulation_ready=False,
        ),
    )
    for workers, threads in layouts:
        tasks = plan["tasks"][offset : offset + workers]
        offset += workers
        os.environ["OMP_NUM_THREADS"] = str(threads)
        write(
            root / "stage.json",
            dict(stage="concurrent_throughput_pilot", workers=workers, threads=threads),
        )
        start = time.monotonic()

        def task_run(task):
            return _run_task(
                task=task,
                plan_path=plan_path,
                root=folder,
                qm_python=QM,
                scratch_root=root / "scratch",
                threads=threads,
                memory_gib=3,
            )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            records = list(pool.map(task_run, tasks))
        elapsed = time.monotonic() - start
        pilots.append(
            dict(
                workers=workers,
                threads=threads,
                wall_seconds=elapsed,
                gradients_per_hour=len(tasks) * 3600 / elapsed,
                records=records,
            )
        )
        write(root / "pilot_progress.json", dict(records=pilots))
    preferred = pilots[0]
    fastest = max(pilots, key=lambda p: p["gradients_per_hour"])
    selected = (
        fastest
        if fastest["gradients_per_hour"] > 1.1 * preferred["gradients_per_hour"]
        else preferred
    )
    write(
        root / "scheduling_decision.json",
        dict(
            selected=selected,
            pilots=pilots,
            reason="Measured concurrent throughput; 10% practical improvement threshold, bounded memory; no scientific gate changed.",
            sources=[source(root / "policy.json")],
        ),
    )
    os.environ["OMP_NUM_THREADS"] = str(selected["threads"])
    write(
        root / "stage.json",
        dict(
            stage="production_displaced_gradients",
            workers=selected["workers"],
            threads=selected["threads"],
        ),
    )
    args = argparse.Namespace(
        plan=plan_path,
        job_dir=(ART / "cpd-anti-additive-next-v2/endpoint1-frequency").resolve(),
        scratch_root=root / "scratch",
        output=root / "hessian_batch_report.json",
        qm_python=QM,
        max_parallel=selected["workers"],
        threads=selected["threads"],
        memory_gib=3,
        storage_root=None,
        wait_for_report=None,
        wait_for_service=None,
        wait_poll_seconds=30,
    )
    from experiments.cpd_anti_additive.adaptive_gradients import run as run_adaptive

    shutil.copy2(
        REPO / "experiments/cpd_anti_additive/adaptive_gradients.py",
        root / "adaptive_gradients_snapshot.py",
    )
    run_adaptive(
        plan_path,
        root,
        selected,
        timings,
        QM,
        ART / "cpd-anti-endpoint2-service-v1/status.json",
    )
    # All immutable gradient pairs are now complete. Reuse the established engine
    # assembly and scientific frequency audit; this call launches no gradients.
    report = run_local_batch(args)
    write(root / "stage.json", dict(stage="terminal", status=report["status"]))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
