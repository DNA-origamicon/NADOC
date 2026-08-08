"""Detached entry point for a single SNUPI FEM solve.

Launched by :func:`backend.core.snupi_runner.start_job` in its OWN session
(``start_new_session=True``) so the multi-minute ``predict_shape`` solve survives a
``uvicorn --reload`` restart of the dev server: the reloader signals only the server's
process group, not this detached child.  All communication is through the filesystem —
the worker reads ``job.json`` + ``design.json`` from the job dir and writes
``display.json`` / ``rmsf.json`` and the terminal status back, which the (possibly
restarted) server picks up via ``reconcile_snupi_status``.

Run as::

    python -m backend.core.snupi_worker <workspace_dir> <job_id>

with the repo root as cwd (start_job passes ``cwd=_REPO_ROOT``).  All heavy lifting lives
in :func:`backend.core.snupi_runner.solve_and_cache`, which writes the terminal status
itself and never raises — this module is a thin process shell around it.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(workspace_dir: str, job_id: str) -> int:
    ws = Path(workspace_dir)
    from backend.core.snupi_job import SnupiJob, SnupiStatus
    from backend.core.snupi_runner import solve_and_cache

    try:
        job = SnupiJob.load(job_id, ws)
    except Exception as exc:  # noqa: BLE001
        print(f"snupi worker: cannot load job {job_id!r}: {exc}", file=sys.stderr)
        return 2

    # solve_and_cache writes completed/failed to the job dir itself; never raises.  If the
    # process is killed mid-solve (stop_job / a hard reload of a NON-detached run) it simply
    # never returns and the server's reconcile marks the orphan stopped.
    solve_and_cache(job, ws)
    return 0 if job.status == SnupiStatus.completed else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            "usage: python -m backend.core.snupi_worker <workspace_dir> <job_id>",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
