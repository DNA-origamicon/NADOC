#!/usr/bin/env python3
"""Status snapshot + stall detector for the 18hb production run.

Gathers one consistent snapshot of the run (job status, current segment,
NAMD-checkpoint step progress, latest health sample, launcher/NAMD process
liveness, GPU), appends a row to MONITOR_LOG.md, and prints a one-line VERDICT
the supervising agent (or the twice-daily cron) acts on:

  COMPLETED              — ladder finished (incl. k=0); write the report, stop.
  FAILED                 — terminal failure; read job.error + segment log, fix.
  RUNNING_PROGRESSING    — NAMD checkpoint step advanced since last snapshot.
  RUNNING_STALLED        — running on disk but no live NAMD and no step advance.
  PREPARING              — still solvating / generating configs.
  IDLE_RESUMABLE         — queued/running on disk but nothing alive → relaunch.

Usage:  python scripts/monitor_18hb.py        # snapshot + log + verdict
Exit code: 0 progressing/preparing/completed, 2 stalled/idle, 3 failed.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob, MdStatus
from backend.core.namd_runner import _read_xsc_step, _segment_process_running

WORKSPACE = ROOT / "workspace"
EXP_DIR = ROOT / "experiments" / "exp30_18hb_production"
JOB_ID_FILE = EXP_DIR / "JOB_ID"
MONITOR_LOG = EXP_DIR / "MONITOR_LOG.md"
STATE_FILE = EXP_DIR / "MONITOR_STATE.json"


def _gpu() -> str:
    try:
        out = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            .stdout.strip()
            .splitlines()
        )
        return out[0].replace(" ", "") if out else "n/a"
    except Exception:
        return "n/a"


def _disk_free_gb() -> float:
    """Free space (GB) on the workspace volume. The full DCD trajectory is ~34 GB
    plus resume cont-file duplication, so a shrinking margin is the top run risk."""
    try:
        import shutil as _sh

        return _sh.disk_usage(str(ROOT)).free / 1e9
    except Exception:
        return -1.0


def _launcher_alive() -> bool:
    try:
        r = subprocess.run(
            ["pgrep", "-f", "run_18hb.py"], capture_output=True, text=True, timeout=10
        )
        return r.returncode == 0
    except Exception:
        return False


def _current_xsc_step(job: MdJob) -> int | None:
    """Highest NAMD checkpoint step across the package's restart/xsc files."""
    pkg = job.job_dir(WORKSPACE) / "package"
    best: int | None = None
    for xsc in pkg.rglob("*.xsc"):
        step = _read_xsc_step(xsc)
        if step is not None and (best is None or step > best):
            best = step
    return best


def main() -> int:
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if not JOB_ID_FILE.exists():
        print(f"{now}  VERDICT=NO_JOB (missing {JOB_ID_FILE})")
        return 3
    job_id = JOB_ID_FILE.read_text().strip()
    # READ-ONLY: never reconcile/save here. reconcile_job_status() mutates and
    # persists job state and, run during the minimization phase (when the first
    # dynamics segment has no checkpoint yet), falsely marks the job failed. The
    # authoritative run_job process is the sole writer of completed/failed; the
    # monitor only observes. Recovery reconcile happens in run_18hb.py --resume.
    job = MdJob.load(job_id, WORKSPACE)

    seg = None
    seg_name = "-"
    if 0 <= job.current_segment_idx < len(job.segments):
        seg = job.segments[job.current_segment_idx]
        seg_name = seg.name
    namd_alive = bool(seg and _segment_process_running(seg_name))
    launcher = _launcher_alive()
    xsc_step = _current_xsc_step(job)

    health = job.health_samples[-1] if job.health_samples else None
    c1 = wc = None
    if health is not None:
        # health_samples are MdHealthSample objects (MdJob.load rehydrates them);
        # tolerate a dict too in case of a raw read.
        getter = (
            health.get
            if isinstance(health, dict)
            else lambda k: getattr(health, k, None)
        )
        c1 = getter("c1_paired_fraction")
        wc = getter("wc_ref_relative_fraction")

    prev = {}
    if STATE_FILE.exists():
        try:
            prev = json.loads(STATE_FILE.read_text())
        except Exception:
            prev = {}
    prev_step = prev.get("xsc_step")
    prev_seg = prev.get("seg_name")

    # ── Verdict ───────────────────────────────────────────────────────────────
    if job.status == MdStatus.completed:
        verdict, code = "COMPLETED", 0
    elif job.status == MdStatus.failed:
        verdict, code = "FAILED", 3
    elif job.status == MdStatus.preparing:
        verdict, code = "PREPARING", 0
    elif namd_alive:
        verdict, code = "RUNNING_PROGRESSING", 0
    elif launcher and job.status in (MdStatus.running, MdStatus.queued):
        # launcher up, between segments (NAMD momentarily down) — treat as progressing
        verdict, code = "RUNNING_PROGRESSING", 0
    elif job.status in (MdStatus.running, MdStatus.queued):
        progressed = (
            xsc_step is not None
            and prev_step is not None
            and seg_name == prev_seg
            and xsc_step > prev_step
        )
        if progressed:
            verdict, code = "RUNNING_PROGRESSING", 0
        elif prev_step is None:
            verdict, code = "IDLE_RESUMABLE", 2  # first look, nothing alive → relaunch
        else:
            verdict, code = "RUNNING_STALLED", 2
    elif job.status == MdStatus.stopped:
        verdict, code = "STOPPED", 0
    else:
        verdict, code = "IDLE_RESUMABLE", 2

    c1s = f"{c1 * 100:.1f}%" if isinstance(c1, (int, float)) else "-"
    wcs = f"{wc * 100:.1f}%" if isinstance(wc, (int, float)) else "-"
    row = (
        f"| {now} | {job.status} | {job.current_segment_idx}/{len(job.segments)} "
        f"{seg_name} | {xsc_step if xsc_step is not None else '-'} | {c1s} | {wcs} "
        f"| namd={'Y' if namd_alive else 'N'} launcher={'Y' if launcher else 'N'} "
        f"| gpu={_gpu()} disk={_disk_free_gb():.0f}G | {verdict} |"
    )
    if not MONITOR_LOG.exists():
        EXP_DIR.mkdir(parents=True, exist_ok=True)
        MONITOR_LOG.write_text(
            "# 18hb production monitor log\n\n"
            "| time | status | seg | xsc_step | C1' | WC | procs | gpu | verdict |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
        )
    with MONITOR_LOG.open("a") as fh:
        fh.write(row + "\n")

    STATE_FILE.write_text(
        json.dumps(
            {"xsc_step": xsc_step, "seg_name": seg_name, "ts": now, "verdict": verdict},
            indent=2,
        )
    )

    err = (
        f"  error={job.error!r}"
        if (job.status == MdStatus.failed and job.error)
        else ""
    )
    print(
        f"{now}  job={job_id}  VERDICT={verdict}  status={job.status}  "
        f"seg={job.current_segment_idx}/{len(job.segments)}:{seg_name}  "
        f"xsc={xsc_step}(prev {prev_step})  C1'={c1s} WC={wcs}  "
        f"namd={namd_alive} launcher={launcher}  disk={_disk_free_gb():.0f}G{err}"
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
