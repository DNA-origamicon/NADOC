#!/usr/bin/env python3
"""Fetch the NAMD build off the EU-RO-1 network volume to local, so it can travel to any
region's container-disk pod. This is also the first end-to-end exercise of the confirmation
lifecycle (setup -> job -> terminate), on the cheapest card available.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) python experiments/exp43_runpod_bench/fetch_namd.py

The binary + its bundled libs live in /workspace/namd/3.0.2p1-cuda-a80/ (covers sm_80/89/
90/120 — H100/H200 are sm_90, so this same build runs them). We tar the whole dir on the
pod and SFTP it down; the local tar then rides to each bench pod's container disk.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient, build_create_payload  # noqa: E402
from experiments.exp43_runpod_bench.campaign_common import (  # noqa: E402
    CAMPAIGN_DIR, campaign_ledger, campaign_log, confirmed_pod,
)
from experiments.exp43_runpod_bench.runpod_confirm import Receipt, guarded_step  # noqa: E402

NETWORK_VOLUME = "77pnhye88p"                 # EU-RO-1, holds the NAMD build
NAMD_DIR_REMOTE = "/workspace/namd/3.0.2p1-cuda-a80"
LOCAL_TAR = Path("/media/jojo/Archive/nadoc_bench_pkg/namd_cuda.tar.gz")
# cheapest EU-RO-1 cards first; availability churns, so offer several.
FETCH_GPUS = ["NVIDIA RTX 4000 Ada Generation", "NVIDIA L4", "NVIDIA RTX PRO 4500 Blackwell"]


async def main() -> int:
    if LOCAL_TAR.exists() and LOCAL_TAR.stat().st_size > 50_000_000:
        print(f"NAMD tar already local: {LOCAL_TAR} "
              f"({LOCAL_TAR.stat().st_size/1e6:.0f} MB) — nothing to fetch")
        return 0

    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger, clog = campaign_ledger(), campaign_log()
    clog.require_clean()

    payloads = [build_create_payload(name="nadoc-fetch-namd", gpu_type_ids=[g],
                                     network_volume_id=NETWORK_VOLUME, interruptible=False,
                                     cloud_type="SECURE") for g in FETCH_GPUS]
    try:
        async with confirmed_pod(client, ledger, clog, payloads[0], "fetch-namd",
                                 fallbacks=payloads[1:], usd_hr_hint=0.74) as (pod, conn):
            print(f"pod {pod.id} up at ${pod.cost_per_hr}/hr")
            # verify the build is there, then tar it on the pod (server-side, free)
            chk = await conn.run(f"test -x {NAMD_DIR_REMOTE}/namd3 && echo yes || echo no")
            if "yes" not in chk.stdout:
                raise RuntimeError(f"NAMD binary not found at {NAMD_DIR_REMOTE}/namd3")
            print("taring NAMD build on the pod ...")
            await conn.run(
                f"cd /workspace/namd && tar -czf /root/namd_cuda.tar.gz 3.0.2p1-cuda-a80",
                timeout=900)
            rsize = (await conn.run("stat -c %s /root/namd_cuda.tar.gz")).stdout.strip()

            # 'launch' receipt for the fetch = the tarball exists on the pod with real bytes
            async with guarded_step("launch", pod.id, clog) as step:
                verified = rsize.isdigit() and int(rsize) > 50_000_000
                step.receipt(Receipt("launch", pod.id, verified,
                                     {"remote_tar_bytes": rsize, "path": NAMD_DIR_REMOTE},
                                     time.time()))

            print(f"downloading {int(rsize)/1e6:.0f} MB -> {LOCAL_TAR} ...")
            t0 = time.time()
            await conn.sftp_get("/root/namd_cuda.tar.gz", str(LOCAL_TAR))
            dt = time.time() - t0
            lsize = LOCAL_TAR.stat().st_size
            ok = lsize == int(rsize)
            print(f"downloaded {lsize/1e6:.0f} MB in {dt:.0f}s "
                  f"({'size match' if ok else 'SIZE MISMATCH'})")
            if not ok:
                clog.flag("download", pod.id,
                          reason=f"local {lsize} != remote {rsize}")
                raise RuntimeError("download size mismatch — NAMD tar incomplete")
    finally:
        await client.aclose()

    print(f"\nconfirmations: {clog.confirmations}")
    print(f"review queue:  {len(clog.open_reviews())} ent(ies)")
    print(ledger.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
