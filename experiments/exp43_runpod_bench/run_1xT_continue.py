#!/usr/bin/env python3
"""Continue the completed 1xT production (5 ns) another ~4 ns LOCALLY (velocity-preserving continuation
off its restart checkpoint), for better sampling of the extra-base crossover ROTATIONAL stiffness (the
slow junction mode). spawn_md_production makes a child continuation job + start_job runs NAMD on the
local GPU in a background thread — so this process must stay alive (the keep-alive loop below)."""
import asyncio, sys, time
sys.path.insert(0, "/home/jojo/Work/NADOC")
from pathlib import Path
from backend.api.routes_md import spawn_md_production, ProductionRunRequest
from backend.core import namd_runner
from backend.core.md_job import MdJob

WS = Path("/home/jojo/Work/NADOC/workspace")
PARENT = "f14e00b8cacf"           # completed 1xT production @5ns


async def go():
    return await spawn_md_production(PARENT, ProductionRunRequest(
        length_ns=4.0, execution_target="local", dcd_freq=1000, autostart=True))


res = asyncio.run(go())
cid = res["job"]["job_id"]
print(f"[1xT-cont] child {cid} started off {PARENT}: {res['steps']} steps = {res['length_ns']} ns "
      f"(dcd_freq 1000 = 4 ps/frame); ~9 h at 10.4 ns/day", flush=True)

last = None
while True:
    time.sleep(60)
    running = namd_runner.is_running(cid)
    j = MdJob.load(cid, WS)
    tag = (j.status.value, j.current_segment_idx)
    if tag != last:
        print(f"[1xT-cont] status={j.status.value} seg={j.current_segment_idx}"
              + (f" err={j.error}" if j.error else ""), flush=True)
        last = tag
    if not running and j.status.value not in ("running", "preparing"):
        print(f"[1xT-cont] DONE status={j.status.value}", flush=True)
        break
