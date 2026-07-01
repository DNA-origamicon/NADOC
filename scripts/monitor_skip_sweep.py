#!/usr/bin/env python3
"""Read-only watchdog for the exp31 skip-sweep driver.

Reads the driver's ``results/current.json`` sidecar (active job + expected wall-clock), then
inspects that job's on-disk energy trace to catch a HUNG or EXPLODED run that the in-process
gates would otherwise let sit.  STRICTLY read-only: it parses ``job.json`` and ``energy.dat``
directly and never calls reconcile / stop / start (mirrors ``scripts/monitor_18hb.py``).

Invoke at the 10% and 50% expected-progress marks (the agent schedules it).  Compares the
energy-line count to its own previous snapshot to decide whether the run is advancing.

Prints a ``VERDICT: <state>`` line and appends a row to the experiment's ``MONITOR_LOG.md``.
Exit codes: 0 healthy / idle / done · 2 stalled · 3 exploded / failed.
"""
from __future__ import annotations

import glob
import json
import os
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent.parent
# Experiment dir is overridable so the same read-only monitor serves exp31, exp32, … —
# set EXP_DIR (absolute or repo-relative) to point it at another experiment's results.
EXP = pathlib.Path(os.environ.get("EXP_DIR", HERE / "experiments" / "exp31_skip_twist_curvature_sweep"))
if not EXP.is_absolute():
    EXP = HERE / EXP
CURRENT = EXP / "results" / "current.json"
STATE = EXP / "results" / "monitor_state.json"
MONITOR_LOG = EXP / "MONITOR_LOG.md"

STALL_GRACE_S = 600.0          # no new energy lines for this long (and not terminal) ⇒ stalled


def _log(msg: str) -> None:
    if not MONITOR_LOG.exists():
        MONITOR_LOG.parent.mkdir(parents=True, exist_ok=True)
        MONITOR_LOG.write_text("# exp31 driver log\n\n| time | event |\n|---|---|\n")
    with MONITOR_LOG.open("a") as f:
        f.write(f"| {time.strftime('%Y-%m-%d %H:%M:%S')} | monitor: {msg} |\n")


def _job_dir(workspace: str, job_id: str) -> pathlib.Path | None:
    for cand in (pathlib.Path(workspace) / "oxdna_jobs" / job_id,
                 pathlib.Path(workspace) / "oxdna_jobs_archive" / job_id):
        if cand.exists():
            return cand
    hits = glob.glob(f"{workspace}/**/oxdna_jobs/{job_id}", recursive=True)
    return pathlib.Path(hits[0]) if hits else None


def _job_status(job_dir: pathlib.Path) -> str:
    try:
        return json.loads((job_dir / "job.json").read_text()).get("status", "unknown")
    except Exception:
        return "unknown"


def _newest_energy(job_dir: pathlib.Path):
    """(path, n_lines, last_line) of the most-recently-modified energy.dat under the job."""
    files = glob.glob(f"{job_dir}/**/energy.dat", recursive=True)
    if not files:
        return None, 0, ""
    path = max(files, key=lambda p: pathlib.Path(p).stat().st_mtime)
    try:
        lines = [ln for ln in pathlib.Path(path).read_text().splitlines() if ln.strip()]
    except Exception:
        return path, 0, ""
    return path, len(lines), (lines[-1] if lines else "")


def _verdict(state: str, detail: str, code: int) -> int:
    _log(f"{state} — {detail}")
    print(f"VERDICT: {state}")
    print(detail)
    return code


def main() -> int:
    if not CURRENT.exists():
        return _verdict("IDLE", "no current.json (driver not started or finished)", 0)
    cur = json.loads(CURRENT.read_text() or "{}")
    job_id = cur.get("job_id")
    if cur.get("idle") or not job_id:
        return _verdict("IDLE", "driver between sims (no active job)", 0)

    ws = cur.get("workspace", "")
    label = f"{cur.get('strategy')} Δ={cur.get('delta')} ({cur.get('total_skips')} skips)"
    job_dir = _job_dir(ws, job_id)
    if job_dir is None:
        return _verdict("RUNNING_NOJOBDIR",
                        f"{label}: job {job_id} dir not found yet under {ws}", 0)

    status = _job_status(job_dir)
    _, n_lines, last = _newest_energy(job_dir)
    has_nan = any(tok in last.lower() for tok in ("nan", "inf"))
    elapsed = time.time() - float(cur.get("started_at") or time.time())
    eta = cur.get("expected_wall_s")
    pct = f"{100 * elapsed / eta:.0f}%" if eta else "?"
    detail = (f"{label} | status={status} | energy_lines={n_lines} | "
              f"elapsed={elapsed/60:.1f}m / eta={(eta or 0)/60:.1f}m ({pct}) | last='{last[:60]}'")

    if has_nan:
        return _verdict("EXPLODED", detail + " | NaN/Inf in energy trace", 3)
    if status == "failed":
        return _verdict("FAILED", detail, 3)
    if status in ("completed", "stopped"):
        return _verdict("DONE", detail, 0)

    # progress check vs our own previous snapshot for this job
    prev = {}
    if STATE.exists():
        try:
            prev = json.loads(STATE.read_text())
        except Exception:
            prev = {}
    stalled = (prev.get("job_id") == job_id and prev.get("n_lines") == n_lines and n_lines >= 0
               and (time.time() - float(prev.get("ts", 0))) > STALL_GRACE_S)
    STATE.write_text(json.dumps({"job_id": job_id, "n_lines": n_lines, "ts": time.time()}))
    if stalled:
        return _verdict("STALLED",
                        detail + f" | no new energy lines for >{STALL_GRACE_S/60:.0f}m", 2)
    return _verdict("RUNNING_PROGRESSING", detail, 0)


if __name__ == "__main__":
    sys.exit(main())
