#!/usr/bin/env python
"""Run the 24hb_2xT relaxation ladder LOCALLY on this machine's GPU via the real
namd_runner (minimise -> ENM rebuild -> GPU-resident probe -> every segment, Tier-A
early-stop). Detached: keep this process alive so the runner's background thread lives.
Watch: tail the per-segment logs in the package dir, or `watch.py 336a067ba241 --oneline`.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, "/home/jojo/Work/NADOC")
from backend.core.md_job import MdJob, MdStatus
from backend.core import namd_runner

WS = Path("/home/jojo/Work/NADOC/workspace")
JOB_ID = "336a067ba241"

job = MdJob.load(JOB_ID, WS)
job.execution_target = "local"            # run on THIS GPU, not a pod
if job.status in (MdStatus.completed, MdStatus.failed, MdStatus.stopped):
    job.status = MdStatus.queued
job.save(WS)
print(f"[local-2xT] starting {JOB_ID} on the local GPU: {len(job.segments)} segments, "
      f"early_stop={job.early_stop_relax}/{job.early_stop_tier}", flush=True)

namd_runner.start_job(job, WS)
last = None
while True:
    time.sleep(15)
    running = namd_runner.is_running(JOB_ID)
    j = MdJob.load(JOB_ID, WS)
    tag = (j.status.value, j.current_segment_idx)
    if tag != last:
        seg = j.segments[j.current_segment_idx].name if 0 <= j.current_segment_idx < len(j.segments) else "-"
        print(f"[local-2xT] status={j.status.value} seg[{j.current_segment_idx}]={seg}"
              + (f" err={j.error}" if j.error else ""), flush=True)
        last = tag
    if not running and j.status.value not in ("running", "preparing"):
        print(f"[local-2xT] DONE status={j.status.value}", flush=True)
        break
