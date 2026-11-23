"""Compute-node entry point. Uses the same prepared snapshots and solvers as local jobs."""
import sys
from pathlib import Path


def main(engine, workspace, job_id):
    workspace = Path(workspace)
    if engine == "snupi":
        from backend.core.snupi_worker import main as run
        return run(str(workspace), job_id)
    if engine == "mrdna":
        from backend.core.mrdna_job import MrdnaJob
        from backend.core.mrdna_runner import _run_job
        from backend.core.simulation_runtime import worker_lease
        with worker_lease(workspace / "mrdna_jobs" / job_id) as lease:
            if lease is None:
                return 1
            _run_job(MrdnaJob.load(job_id, workspace), workspace)
        return 0 if MrdnaJob.load(job_id, workspace).status.value == "completed" else 1
    raise ValueError("Unknown solver")


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
