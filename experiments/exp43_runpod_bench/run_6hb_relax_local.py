#!/usr/bin/env python
"""Run the 6hb_2xT geometric+FixB relaxation ladder LOCALLY (Track 2: the 4fs-safe rebuild for the
size-independent SNUPI extra_base_co validation). Same runner as run_2xT_local.py: minimise (no-ENM)
-> ENM rebuild from declashed coords -> GPU-resident probe -> every segment with Tier-A early-stop.
178k atoms, ~8x smaller than the 24hb, so the ladder is a few hours. Detached: keep alive so the
runner's background thread lives. Reads the seeded job id from JOB_ID_6hb_2xT_seeded.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, "/home/jojo/Work/NADOC")
from backend.core.md_job import MdJob, MdStatus
from backend.core import namd_runner

WS = Path("/home/jojo/Work/NADOC/workspace")
JOB_ID = (Path(__file__).parent / "JOB_ID_6hb_2xT_seeded").read_text().strip()

job = MdJob.load(JOB_ID, WS)
job.execution_target = "local"
if job.status in (MdStatus.completed, MdStatus.failed, MdStatus.stopped):
    job.status = MdStatus.queued
job.save(WS)
print(f"[6hb-relax] starting {JOB_ID} on the local GPU: {len(job.segments)} segments, "
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
        print(f"[6hb-relax] status={j.status.value} seg[{j.current_segment_idx}]={seg}"
              + (f" err={j.error}" if j.error else ""), flush=True)
        last = tag
    if not running and j.status.value not in ("running", "preparing"):
        print(f"[6hb-relax] DONE status={j.status.value}", flush=True)
        break
