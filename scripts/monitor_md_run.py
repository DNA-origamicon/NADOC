#!/usr/bin/env python3
"""One-shot health + explosion snapshot for a NADOC NAMD MD job (READ-ONLY).

Appends a timestamped row to ``workspace/md_jobs/<job>/MONITOR_LOG.md``, updates a
small STATE file (for progress deltas between checks), prints a one-line VERDICT, and
exits with a code the overnight watchdog acts on:

  0  COMPLETED / RUNNING_PROGRESSING / PREPARING / FIRST_LOOK   (healthy)
  2  RUNNING_STALLED                                            (alive on disk, no progress)
  3  FAILED / EXPLODED                                          (terminal — stop, inspect)

Explosion = any of: NaN/Inf in the latest ENERGY line, |TOTAL| absurd (>1e12), a
temperature runaway (>450 K on a non-minimization stage), or a NAMD error/abort marker
in the log tail. Progress = newest NAMD log grew (or the stage advanced) since last check.

Usage:  python scripts/monitor_md_run.py <job_id> [--workspace DIR]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob, MdStatus
from backend.core.namd_metrics import parse_namd_log

# NAMD error / abort markers (specific, to avoid matching benign "Info:" lines).
_ERR = re.compile(r"ERROR:|FATAL|Abnormal|Aborting|fatal error|Exiting prematurely|segmentation", re.I)
# NaN/Inf as standalone numeric tokens (lowercase, as NAMD prints them in blown-up energies).
_NANINF = re.compile(r"(?<![A-Za-z])(nan|inf)(?![A-Za-z])")
_TEMP_RUNAWAY_K = 450.0     # NPT stages target 300 K; minimization has TEMP≈0


def _gpu() -> str:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15).stdout.strip().splitlines()
        return out[0].replace(" ", "") if out else "n/a"
    except Exception:
        return "n/a"


def _newest_log(pkg: Path):
    logs = [p for p in pkg.rglob("*.log")] if pkg else []
    return max(logs, key=lambda p: p.stat().st_mtime) if logs else None


def _namd_alive_for(jobdir: Path) -> bool:
    """True if a live namd3 process has its cwd inside this job's dir. This is the
    AUTHORITATIVE 'is it running' signal — it trumps a stale persisted job.status,
    which can read 'failed' from a prior attempt while a fresh run is progressing."""
    try:
        pids = subprocess.run(["pgrep", "-f", "namd3"], capture_output=True,
                              text=True, timeout=10).stdout.split()
    except Exception:
        return False
    for pid in pids:
        try:
            if str(jobdir.resolve()) in os.readlink(f"/proc/{pid}/cwd"):
                return True
        except OSError:
            continue
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--workspace", default=str(ROOT / "workspace"))
    a = ap.parse_args()

    ws = Path(a.workspace)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    jobdir = ws / "md_jobs" / a.job_id
    mlog = jobdir / "MONITOR_LOG.md"
    state_f = jobdir / "MONITOR_STATE.json"

    try:
        job = MdJob.load(a.job_id, ws)          # READ-ONLY (never reconcile/save)
    except Exception as exc:
        print(f"{now}  VERDICT=NO_JOB ({exc})")
        return 3

    pkg = next((p for p in (jobdir / "package").glob("*") if p.is_dir()), None)
    cur_log = _newest_log(pkg) if pkg else None
    stage = cur_log.stem if cur_log else "-"

    total = temp = None
    exploded = False
    reason = ""
    if cur_log is not None:
        try:
            m = parse_namd_log(cur_log)
            total, temp = m.total_energy_kcal, m.temperature_k
        except Exception:
            pass
        tail = "\n".join(cur_log.read_text(errors="replace").splitlines()[-80:])
        energy_tail = "\n".join(l for l in tail.splitlines() if l.startswith("ENERGY:"))
        if _ERR.search(tail):
            exploded, reason = True, "namd-error-in-log"
        elif _NANINF.search(energy_tail):
            exploded, reason = True, "nan/inf-energy"
        elif total is not None and (total != total or abs(total) > 1e12):
            exploded, reason = True, "total-energy-absurd"
        elif temp is not None and temp > _TEMP_RUNAWAY_K and "min" not in stage.lower():
            exploded, reason = True, f"TEMP={temp:.0f}K-runaway"

    size = cur_log.stat().st_size if cur_log else 0
    prev = {}
    if state_f.exists():
        try:
            prev = json.loads(state_f.read_text())
        except Exception:
            pass
    prev_stage, prev_size = prev.get("stage"), prev.get("log_size", -1)
    progressed = (stage != prev_stage) or (size > prev_size)
    namd_alive = _namd_alive_for(jobdir)

    # Priority: explosion > live-and-healthy > terminal persisted status > stall.
    # A LIVE namd process (with a progressing, non-exploding log) is authoritative —
    # it overrides a stale job.status=='failed' left by an earlier attempt.
    if exploded:
        verdict, code = f"EXPLODED({reason})", 3
    elif namd_alive:
        verdict, code = ("RUNNING_PROGRESSING" if progressed or prev_stage is None
                         else "RUNNING_ALIVE_LOGQUIET"), 0
    elif job.status == MdStatus.completed:
        verdict, code = "COMPLETED", 0
    elif job.status == MdStatus.failed:
        verdict, code = "FAILED", 3
    elif job.status == MdStatus.preparing:
        verdict, code = "PREPARING", 0
    elif progressed:
        verdict, code = "RUNNING_PROGRESSING", 0          # between segments, process momentarily down
    elif prev_stage is None:
        verdict, code = "FIRST_LOOK", 0
    else:
        verdict, code = "RUNNING_STALLED", 2

    ts = f"TOT={total:.0f}" if total is not None else "TOT=-"
    tp = f"T={temp:.0f}K" if temp is not None else "T=-"
    row = (f"| {now} | {job.status} | {job.current_segment_idx}/{len(job.segments)} "
           f"{stage} | {ts} {tp} | namd={'Y' if namd_alive else 'N'} gpu={_gpu()} | {verdict} |\n")
    if not mlog.exists():
        mlog.write_text(f"# MD run monitor — job {a.job_id}\n\n"
                        "| time | status | seg / stage | energy | gpu | verdict |\n"
                        "|---|---|---|---|---|---|\n")
    with mlog.open("a") as f:
        f.write(row)
    state_f.write_text(json.dumps({"stage": stage, "log_size": size, "ts": now}))

    print(f"{now}  VERDICT={verdict}  stage={stage} {ts} {tp}")
    return code


if __name__ == "__main__":
    sys.exit(main())
