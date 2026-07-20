"""Resumable sequential supervisor for all exp43 conditions.

Safe to restart: completed jobs are skipped, the currently running job is watched,
and only queued jobs are launched. A failed job or fatal monitor trigger prevents
later conditions from starting.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob
from experiments.exp43_7bp_crossover_transition.monitor import inspect_job

POLL_SECONDS = 60


def main() -> int:
    workspace = ROOT / "workspace"
    registry_path = HERE / "runs" / "registry.json"
    registry = json.loads(registry_path.read_text())
    order = ("no_crossover", "left_crossover", "bracketed_crossovers")
    for condition in order:
        entry = registry["jobs"][condition]
        while True:
            job = MdJob.load(entry["job_id"], workspace)
            status = job.status.value if hasattr(job.status, "value") else str(job.status)
            check = inspect_job(job, workspace)
            fatal = [i for i in check["issues"] if i["severity"] == "fatal"]
            print(json.dumps({"condition": condition, "status": status,
                              "segment": job.current_segment_idx,
                              "fatal_issues": fatal}), flush=True)
            if fatal or status in {"failed", "stopped", "paused"}:
                return 2
            if status == "completed":
                break
            if status == "queued":
                proc = subprocess.run([
                    sys.executable, str(HERE / "run.py"), "launch",
                    "--condition", condition, "--confirm-start",
                    "--workspace", str(workspace),
                ], cwd=ROOT)
                if proc.returncode:
                    return proc.returncode
                continue
            time.sleep(POLL_SECONDS)
    subprocess.run([
        sys.executable, str(HERE / "run.py"), "process",
        "--workspace", str(workspace),
    ], cwd=ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
