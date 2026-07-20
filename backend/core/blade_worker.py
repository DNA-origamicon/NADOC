"""Detached entry point for a single BLADE relax.

Launched by :func:`backend.core.blade_runner.start_job` in its OWN session
(``start_new_session=True``) so a multi-minute relax survives a ``uvicorn --reload`` restart
of the dev server: the reloader signals only the server's process group, not this detached
child.  All communication is through the filesystem — the worker reads ``job.json`` +
``design.json`` from the job dir and writes ``display.json`` / ``trajectory.json`` and the
terminal status back, which the (possibly restarted) server picks up via
``reconcile_blade_status``.

This process runs in the BACKEND (uv) environment.  It builds the CHARMM topology here — that
needs psfgen but not OpenMM — and then shells the actual relax out to the micromamba ``gpu``
environment's interpreter, because ``openmm``/``parmed`` are not installed in the uv env.  So
the OpenMM process is a GRANDchild of the server; ``stop_job`` group-kills accordingly.

Run as::

    python -m backend.core.blade_worker <workspace_dir> <job_id>

with the repo root as cwd (start_job passes ``cwd=_REPO_ROOT``).  All heavy lifting lives in
:func:`backend.core.blade_runner.relax_and_cache`, which writes the terminal status itself and
never raises — this module is a thin process shell around it.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main(workspace_dir: str, job_id: str) -> int:
    ws = Path(workspace_dir)
    from backend.core.blade_job import BladeJob, BladeStatus
    from backend.core.blade_runner import relax_and_cache

    try:
        job = BladeJob.load(job_id, ws)
    except Exception as exc:  # noqa: BLE001
        print(f"blade worker: cannot load job {job_id!r}: {exc}", file=sys.stderr)
        return 2

    # relax_and_cache writes completed/failed to the job dir itself; never raises.  If the
    # process is killed mid-run (stop_job) it simply never returns and the server's reconcile
    # marks the orphan stopped.
    relax_and_cache(job, ws)
    return 0 if job.status == BladeStatus.completed else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python -m backend.core.blade_worker <workspace_dir> <job_id>",
              file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
