#!/usr/bin/env python3
"""Benchmark 24hb_0xT on a cloud GPU using the LOCAL namd3 binary.

Purpose: a same-binary, same-structure, same-config comparison of the LOCAL machine vs a
cloud instance of the SAME silicon, so the ONLY variable is the environment (thermals, power
limit, background load, PCIe) — i.e. "is my local box leaving performance on the table?".

Why the local binary and not the volume one: the RunPod volume NAMD is 3.0.2p1, built for
sm_80/89/90/120 (NO sm_86), and a different NAMD version. The local build (Dec-2025 git,
sm_86, CUDA statically linked — only libtcl8.6/libfftw3f are dynamic) is what actually runs
on the 3080 Ti, so shipping it is the apples-to-apples control.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
      python experiments/exp43_runpod_bench/bench_local_binary.py \
        "NVIDIA GeForce RTX 3080 Ti" --cloud COMMUNITY --label "3080 Ti" --local-ms 28.2
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import (  # noqa: E402
    DEFAULT_ALLOWED_CUDA, DEFAULT_IMAGE, RunpodClient,
)
from backend.core.runpod_executor import namd_threads  # noqa: E402
from experiments.exp43_runpod_bench.campaign_common import (  # noqa: E402
    campaign_ledger, campaign_log, confirmed_pod,
)
from experiments.exp43_runpod_bench.runpod_confirm import confirm_job_launched  # noqa: E402

LOCAL_NAMD = Path.home() / "Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3"
PKG_TAR = Path("/media/jojo/Archive/nadoc_bench_pkg/24hb_0xT_bench.tar.gz")
WORKDIR = "/root/24hb_0xT"
NAMD_REMOTE = "/root/namd3_local"
TIMESTEP_FS = 4.0
# libtcl8.6 + libfftw3f are the only dynamic NAMD deps not already in the image.
DEP_INSTALL = ("apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "
               "libtcl8.6 libfftw3-single3 >/dev/null 2>&1; echo done")


def nsday(ms_step: float) -> float:
    return TIMESTEP_FS * 1e-6 / (ms_step / 1000) * 86400


def payload(name: str, gpu_id: str, cloud: str) -> dict:
    return {
        "name": name, "imageName": DEFAULT_IMAGE, "computeType": "GPU",
        "cloudType": cloud, "gpuTypeIds": [gpu_id], "gpuCount": 1,
        "containerDiskInGb": 40, "ports": ["22/tcp"],
        "interruptible": cloud == "COMMUNITY",   # community is spot; a 2-min bench survives
        "allowedCudaVersions": list(DEFAULT_ALLOWED_CUDA),
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("gpu_id")
    ap.add_argument("--cloud", default="COMMUNITY", choices=["COMMUNITY", "SECURE"])
    ap.add_argument("--label", default="local-binary")
    ap.add_argument("--local-ms", type=float, default=28.2, help="local ms/step to compare")
    ap.add_argument("--steps", type=int, default=2000)
    args = ap.parse_args()

    if not LOCAL_NAMD.exists() or not PKG_TAR.exists():
        print(f"missing {LOCAL_NAMD if not LOCAL_NAMD.exists() else PKG_TAR}", file=sys.stderr)
        return 2

    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger, clog = campaign_ledger(), campaign_log()
    clog.require_clean()
    result = {"ms_step": None, "note": ""}
    name = f"nadoc-bench-{args.label.lower().replace(' ', '-')}"
    try:
        async with confirmed_pod(client, ledger, clog, payload(name, args.gpu_id, args.cloud),
                                 f"bench {args.label} (local namd3)", usd_hr_hint=0.4) as (pod, conn):
            gpu = (await conn.run("nvidia-smi --query-gpu=name,compute_cap --format=csv,noheader")).stdout.strip()
            print(f"  {args.label}: pod {pod.id} at ${pod.cost_per_hr}/hr  GPU='{gpu}'")

            for src, dst in ((LOCAL_NAMD, NAMD_REMOTE), (PKG_TAR, f"/root/{PKG_TAR.name}")):
                t0 = time.time()
                await conn.sftp_put(str(src), dst)
                print(f"  {args.label}: uploaded {src.name} "
                      f"({Path(src).stat().st_size/1e6:.0f} MB) in {time.time()-t0:.0f}s")
            print(f"  {args.label}: installing libtcl8.6 + libfftw3f ...")
            await conn.run(DEP_INSTALL, timeout=300)
            await conn.run(f"chmod +x {NAMD_REMOTE}; cd /root && tar -xzf {PKG_TAR.name}",
                           timeout=300)

            vcpus = int((await conn.run("nproc")).stdout.strip() or 8)
            threads = namd_threads(vcpus)
            print(f"  {args.label}: launching LOCAL namd3 +p{threads} on {vcpus} vCPU")
            await conn.run(
                f"cd {WORKDIR} || exit 90; setsid nohup {NAMD_REMOTE} +p{threads} "
                f"+setcpuaffinity +devices 0 bench.conf > bench.log 2>&1 < /dev/null & echo $!")

            launch = clog.record(await confirm_job_launched(conn, WORKDIR, "bench.log", settle=20.0))
            if not launch.verified:
                tail = (await conn.run(f"tail -c 6000 {WORKDIR}/bench.log")).stdout
                result["note"] = "launch not confirmed: " + (launch.evidence.get("error") or "")[:100]
                print(f"  {args.label}: LAUNCH NOT CONFIRMED — {launch.evidence.get('error','')[:160]}")
                print(f"  --- bench.log tail ---\n{tail[-1500:]}")
                return 1

            log_txt = ""
            for _ in range(40):
                await asyncio.sleep(10)
                log_txt = (await conn.run(f"tail -c 60000 {WORKDIR}/bench.log")).stdout
                if "no kernel image is available" in log_txt:
                    result["note"] = "WRONG ARCH"; return 1
                fatal = re.search(r"(?m)^FATAL ERROR:.*", log_txt)
                if fatal:
                    result["note"] = fatal.group(0)[:80]
                    print(f"  {args.label}: {result['note']}"); return 1
                if len(re.findall(r"Benchmark time:.*?s/step", log_txt)) >= 3:
                    break
            m = re.findall(r"Benchmark time:.*?([\d.]+)\s+s/step", log_txt)
            if not m:
                result["note"] = "no benchmark line"; return 1
            result["ms_step"] = sum(float(x) for x in m[-3:]) / len(m[-3:]) * 1000
    finally:
        await client.aclose()

    print("\n" + "=" * 66)
    print(f"24hb_0xT (1.32M atoms) — LOCAL namd3 (Dec-2025 git), production 4 fs")
    print("=" * 66)
    if result["ms_step"]:
        c, l = result["ms_step"], args.local_ms
        print(f"local  3080 Ti : {l:6.1f} ms/step   {nsday(l):5.1f} ns/day")
        print(f"cloud  {args.label:8s}: {c:6.1f} ms/step   {nsday(c):5.1f} ns/day")
        ratio = l / c
        verdict = ("local ~matches cloud (well-optimized)" if 0.9 <= ratio <= 1.1
                   else f"cloud {ratio:.2f}x FASTER — local likely throttled/loaded"
                   if ratio > 1.1 else f"local {1/ratio:.2f}x faster than cloud (cloud host slower)")
        print(f"ratio (local/cloud ms/step) = {ratio:.2f}  ->  {verdict}")
    else:
        print(f"cloud run failed: {result['note']}")
    print(f"\nreview queue: {len(clog.open_reviews())}   campaign total ${ledger.spent():.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
