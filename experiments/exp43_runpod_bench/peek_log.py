#!/usr/bin/env python3
"""Cheap read of a NAMD segment log off the EU-RO-1 network volume — no compute, cheapest
card, minutes. Identifies the failing atom of a segment that died on the pod, WITHOUT a full
re-run. Uses ``confirmed_pod`` so the pod's destruction is confirmed (no idle billing).

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
      python experiments/exp43_runpod_bench/peek_log.py <job_id> <segment_substr>
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient, build_create_payload  # noqa: E402
from experiments.exp43_runpod_bench.campaign_common import (  # noqa: E402
    campaign_ledger, campaign_log, confirmed_pod,
)

NETWORK_VOLUME = "77pnhye88p"
# RTX PRO 4500 first: the ladder proved it boots reliably in EU-RO-1. Cheaper cards there
# sometimes come up RUNNING but never start sshd (wasted a 10-min wait_for_ssh once).
PEEK_GPUS = ["NVIDIA RTX PRO 4500 Blackwell", "NVIDIA RTX 4000 Ada Generation",
             "NVIDIA L4", "NVIDIA RTX 2000 Ada Generation"]


async def main() -> int:
    if len(sys.argv) < 3:
        print("usage: peek_log.py <job_id> <segment_substr>", file=sys.stderr)
        return 2
    job_id, seg = sys.argv[1], sys.argv[2]
    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger, clog = campaign_ledger(), campaign_log()

    payloads = [build_create_payload(name="nadoc-peek", gpu_type_ids=[g],
                                     network_volume_id=NETWORK_VOLUME, interruptible=False,
                                     cloud_type="SECURE") for g in PEEK_GPUS]
    try:
        async with confirmed_pod(client, ledger, clog, payloads[0], "peek-log",
                                 fallbacks=payloads[1:], usd_hr_hint=0.4) as (pod, conn):
            print(f"pod {pod.id} up at ${pod.cost_per_hr}/hr", flush=True)
            base = f"/workspace/nadoc_jobs/{job_id}"
            logs = (await conn.run(
                f"find {base} -name '*{seg}*.log' 2>/dev/null")).stdout.strip()
            print(f"=== logs matching '{seg}' ===\n{logs or '(none found)'}", flush=True)
            for lg in [l for l in logs.splitlines() if l.strip()]:
                dump = await conn.run(
                    f"echo '===== {lg} ====='; "
                    f"grep -inE 'velocity is|moving too fast|FATAL|ERROR|Constraint' {lg!r} "
                    f"| head -40; echo '----- tail -----'; tail -20 {lg!r}")
                print(dump.stdout, flush=True)
            # also list what completed on the volume (which stages produced a .coor)
            coors = (await conn.run(
                f"ls -1 {base}/*/output/*.coor 2>/dev/null | sed 's#.*/##' | sort")).stdout
            print(f"=== completed .coor on the volume ===\n{coors}", flush=True)
    finally:
        await client.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
