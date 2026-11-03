"""Detached oxDNA protocol owner; communication uses durable job files/mailboxes."""
from __future__ import annotations

import asyncio
import signal
import sys
from pathlib import Path

from backend.core import simulation_runtime as runtime
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus
from backend.core.oxdna_runner import load_stage_specs, run_job


async def execute(job, workspace, lease):
    loop = asyncio.get_running_loop()
    task = asyncio.create_task(run_job(job, workspace, load_stage_specs(job.job_dir(workspace))))
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)

    async def watch_stop():
        while not task.done():
            if lease.stop_requested():
                task.cancel()
                return
            await asyncio.sleep(0.1)

    watcher = asyncio.create_task(watch_stop())
    try:
        await task
    except asyncio.CancelledError:
        job.status = OxdnaStatus.stopped
        job.error = None
        job.oxdna_pid = None
        job.save(workspace)
    except Exception as exc:
        job.status = OxdnaStatus.failed
        job.error = f"oxDNA worker failed: {exc}"
        job.save(workspace)
        raise
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(sig)


def main(workspace_dir, job_id):
    workspace = Path(workspace_dir).resolve()
    with runtime.use_workspace(workspace), runtime.worker_lease(runtime.job_path("oxdna_jobs", job_id, workspace)) as lease:
        if lease is None:
            return 0
        job = OxdnaJob.load(job_id, workspace)
        if lease.stop_requested():
            job.status = OxdnaStatus.stopped
            job.save(workspace)
            return 0
        asyncio.run(execute(job, workspace, lease))
        return 0 if job.status == OxdnaStatus.completed else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m backend.core.oxdna_worker <workspace> <job_id>")
    raise SystemExit(main(*sys.argv[1:]))
