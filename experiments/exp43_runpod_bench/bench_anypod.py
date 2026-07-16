#!/usr/bin/env python3
"""Reusable, confirmation-gated NAMD $/ns benchmark for ANY compatible RunPod GPU.

Container-disk only (no network volume -> not region-pinned), so it reaches H100/H200
wherever RunPod has them. For each card it goes through the campaign lifecycle with a
verified receipt at every money-moving step:

    setup   -> confirm_pod_up          (RUNNING + reachable, not just "create returned")
    launch  -> confirm_job_launched    (NAMD alive + log growing, not "the arch died at 0")
    terminate -> confirm_pod_terminated (gone from the account, not "delete returned 200")

A step that cannot be confirmed lands in the review queue and STOPS the campaign — the whole
point the user asked for: no confirmation code => trigger a review / build a safeguard.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
      python experiments/exp43_runpod_bench/bench_anypod.py --budget 5 \
        [--only "H100 PCIe,H200 SXM"] [--steps 2000]

Prereqs (both free/local, both idempotent):
    python experiments/exp43_runpod_bench/build_bench_package.py   # the 346 MB bench tar
    python experiments/exp43_runpod_bench/fetch_namd.py            # the NAMD tar (one cheap pod)

⚠️ Run pod_watchdog.py in the background FIRST — it is the hard backstop if this driver hangs
mid-upload or dies, the exact orphan-billing failure the runbook catalogues.
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

from backend.core.runpod_api import RunpodClient  # noqa: E402
from backend.core.runpod_executor import namd_threads  # noqa: E402
from experiments.exp43_runpod_bench.campaign_common import (  # noqa: E402
    campaign_ledger, campaign_log, confirmed_pod, container_payload,
)
from experiments.exp43_runpod_bench.runpod_confirm import confirm_job_launched  # noqa: E402

NAMD_TAR = Path("/media/jojo/Archive/nadoc_bench_pkg/namd_cuda.tar.gz")
PKG_TAR = Path("/media/jojo/Archive/nadoc_bench_pkg/24hb_0xT_bench.tar.gz")
NAMD_BIN = "/root/3.0.2p1-cuda-a80/namd3"        # where the NAMD tar extracts
WORKDIR = "/root/24hb_0xT"                        # where the package tar extracts
TIMESTEP_FS = 4.0

# Compute capabilities the NAMD binary was BUILT for (sm_80/89/90/120). A card outside this
# set rents fine and dies at step 0 with "no kernel image is available" — the silent wrong-arch
# trap. We reject it on the compute_cap BEFORE the ~360 MB upload, so a bad card costs seconds,
# not upload-minutes. (E.g. RTX 3090 / A6000 are sm_86 — NOT in the build.)
SUPPORTED_CC = {"8.0", "8.9", "9.0", "12.0"}

# (gpuTypeId, label, sm, $/hr secure). All sm_90 (H100/H200) or sm_89 reference, every arch
# in the build. Ordered high-end first — the campaign the user asked to test.
CARDS = [
    ("NVIDIA H100 PCIe",        "H100 PCIe", "sm_90", 1.99),
    ("NVIDIA H100 80GB HBM3",   "H100 SXM",  "sm_90", 2.69),
    ("NVIDIA H200",             "H200 SXM",  "sm_90", 3.59),
    ("NVIDIA H100 NVL",         "H100 NVL",  "sm_90", 2.59),
    ("NVIDIA L40S",             "L40S",      "sm_89", 0.99),   # value reference, same system
    ("NVIDIA GeForce RTX 5090", "RTX 5090",  "sm_120", 0.69),  # consumer Blackwell — in build
    ("NVIDIA GeForce RTX 3090", "RTX 3090",  "sm_86", 0.22),   # sm_86 — NOT in build (arch gate)
    ("NVIDIA GeForce RTX 4090",        "RTX 4090",     "sm_89",  0.34),  # validate the estimate
    ("NVIDIA RTX PRO 4500 Blackwell",  "RTX PRO 4500", "sm_120", 0.34),  # validate the estimate
    ("NVIDIA RTX 6000 Ada Generation", "RTX 6000 Ada", "sm_89",  0.74),  # in build
    ("NVIDIA RTX A6000",               "RTX A6000",    "sm_86",  0.33),  # sm_86 — arch gate
]


def nsday(ms_step: float) -> float:
    return TIMESTEP_FS * 1e-6 / (ms_step / 1000) * 86400


async def bench_one(client, ledger, clog, gpu_id, label, sm, usd_hr, steps) -> dict:
    result = {"label": label, "sm": sm, "usd_hr": usd_hr, "ms_step": None, "note": ""}
    payload = container_payload(f"nadoc-bench-{label.lower().replace(' ', '-')}", [gpu_id])
    try:
        async with confirmed_pod(client, ledger, clog, payload, f"bench {label}",
                                 usd_hr_hint=usd_hr) as (pod, conn):
            result["usd_hr"] = float(pod.cost_per_hr or usd_hr)
            print(f"  {label}: pod {pod.id} at ${result['usd_hr']}/hr")
            gpu = (await conn.run("nvidia-smi --query-gpu=name --format=csv,noheader")).stdout.strip()
            cc = (await conn.run(
                "nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1")
                ).stdout.strip()
            print(f"  {label}: GPU reports '{gpu}' (compute_cap {cc or '?'})")
            # arch gate BEFORE the upload — reject a wrong-arch card in seconds, not upload-minutes
            if cc and cc not in SUPPORTED_CC:
                result["note"] = (f"arch sm_{cc.replace('.', '')} NOT in NAMD build "
                                  f"(sm_80/89/90/120) — would die at step 0; needs a rebuild")
                result["sm"] = f"sm_{cc.replace('.', '')}"
                print(f"  {label}: SKIP (pre-upload arch gate) — {result['note']}")
                return result
            if not cc:
                print(f"  {label}: WARN could not read compute_cap; proceeding "
                      f"(NAMD will catch a bad arch)")

            # upload NAMD + package to the container disk, extract
            for tar in (NAMD_TAR, PKG_TAR):
                t0 = time.time()
                await conn.sftp_put(str(tar), f"/root/{tar.name}")
                print(f"  {label}: uploaded {tar.name} ({tar.stat().st_size/1e6:.0f} MB) "
                      f"in {time.time()-t0:.0f}s")
            await conn.run("cd /root && tar -xzf namd_cuda.tar.gz && tar -xzf 24hb_0xT_bench.tar.gz",
                           timeout=600)
            if "yes" not in (await conn.run(f"test -x {NAMD_BIN} && echo yes")).stdout:
                raise RuntimeError("NAMD binary missing after extract")

            vcpus = int((await conn.run("nproc")).stdout.strip() or 8)
            threads = namd_threads(vcpus)
            print(f"  {label}: launching NAMD +p{threads} on {vcpus} vCPU")
            await conn.run(
                f"cd {WORKDIR} || exit 90; setsid nohup {NAMD_BIN} +p{threads} "
                f"+setcpuaffinity +devices 0 bench.conf > bench.log 2>&1 < /dev/null & echo $!")

            # NAMD's GPUresident init on 1.32M atoms can take >12s; settle longer, then verify.
            launch = clog.record(await confirm_job_launched(conn, WORKDIR, "bench.log",
                                                            settle=20.0))
            if not launch.verified:
                # Unverified launch => flag a review (done by record()) and SKIP this card —
                # a bad card must not abort the others. Only an unconfirmed TERMINATE (billing)
                # hard-halts the campaign. Capture the full error for the report.
                full = (await conn.run(f"tail -c 6000 {WORKDIR}/bench.log")).stdout
                result["note"] = ("launch not confirmed: "
                                  + (launch.evidence.get("error") or "see log")[:100])
                print(f"  {label}: LAUNCH NOT CONFIRMED — "
                      f"{launch.evidence.get('error','')[:160]}")
                print(f"  {label}: --- bench.log tail ---\n{full[-1500:]}")
                return result

            # poll for settled benchmark lines
            log_txt = ""
            for _ in range(40):                       # up to ~7 min
                await asyncio.sleep(10)
                log_txt = (await conn.run(f"tail -c 60000 {WORKDIR}/bench.log")).stdout
                if "no kernel image is available" in log_txt:
                    result["note"] = "WRONG ARCH — died at step 0"
                    return result
                fatal = re.search(r"(?m)^FATAL ERROR:.*", log_txt)
                if fatal:
                    result["note"] = fatal.group(0)[:80]
                    return result
                marks = re.findall(r"Benchmark time:.*?([\d.]+)\s+s/step", log_txt)
                done = re.search(r"(?m)^(WRITING|End of program)", log_txt)
                if len(marks) >= 3 or done:
                    break
            else:
                result["note"] = "timed out before a benchmark line"
                return result

            m = re.findall(r"Benchmark time:.*?([\d.]+)\s+s/step", log_txt)
            if not m:
                result["note"] = "no benchmark line"
                return result
            result["ms_step"] = sum(float(x) for x in m[-3:]) / len(m[-3:]) * 1000
            print(f"  {label}: {result['ms_step']:.1f} ms/step  "
                  f"{nsday(result['ms_step']):.1f} ns/day  "
                  f"${result['usd_hr']*24/nsday(result['ms_step']):.2f}/ns")
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        result["note"] = ("unavailable" if "no instances" in msg.lower() else msg[:90])
        print(f"  {label}: SKIP — {result['note']}")
    return result


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--only", default="")
    args = ap.parse_args()

    for tar in (NAMD_TAR, PKG_TAR):
        if not tar.exists():
            print(f"missing {tar} — run build_bench_package.py / fetch_namd.py first",
                  file=sys.stderr)
            return 2

    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger, clog = campaign_ledger(), campaign_log()
    clog.require_clean()
    start = ledger.spent()
    print(f"campaign spend so far: ${start:.2f}   budget ${args.budget:.2f}")

    want = [c for c in CARDS
            if not args.only or c[1] in [s.strip() for s in args.only.split(",")]]
    results = []
    try:
        for gpu_id, label, sm, usd_hr in want:
            if ledger.spent() >= args.budget:
                print(f"BUDGET reached (${ledger.spent():.2f}) — stopping before {label}")
                break
            # a card should never be started with < its ~5-min cost of headroom
            if args.budget - ledger.spent() < usd_hr * 0.25:
                print(f"< 15 min headroom for {label} at ${usd_hr}/hr — stopping")
                break
            results.append(await bench_one(client, ledger, clog, gpu_id, label, sm, usd_hr,
                                           args.steps))
            # NB: an unconfirmed TERMINATE raises NoConfirmation from confirmed_pod's teardown
            # and aborts here (billing risk). An unconfirmed launch only logs a review + skips.
    finally:
        # backstop: any campaign pod that somehow survived is destroyed now
        live = [p for p in await client.list_pods()
                if not p.is_destroyed and str(p.raw.get("name", "")).startswith("nadoc-bench")]
        for p in live:
            print(f"!! bench pod {p.id} SURVIVED — destroying")
            await client.terminate_pod(p.id)
            ledger.close_pod(p.id)
        await client.aclose()

    print("\n" + "=" * 78)
    print(f"24hb_0xT (1.32M atoms) — production conf, {args.steps} steps @ 4 fs")
    print("=" * 78)
    print(f"{'card':12s} {'arch':6s} {'$/hr':>6s} {'ms/step':>8s} {'ns/day':>7s} {'$/ns':>7s}")
    print("-" * 78)
    ok = [r for r in results if r["ms_step"]]
    for r in sorted(ok, key=lambda x: x["usd_hr"] * 24 / nsday(x["ms_step"])):
        nd = nsday(r["ms_step"])
        print(f"{r['label']:12s} {r['sm']:6s} {r['usd_hr']:6.2f} {r['ms_step']:8.1f} "
              f"{nd:7.1f} {r['usd_hr']*24/nd:7.2f}")
    for r in results:
        if not r["ms_step"]:
            print(f"{r['label']:12s} {r['sm']:6s}   --   {r['note']}")
    print(f"\ncampaign cost this run: ${ledger.spent()-start:.2f}   "
          f"total ${ledger.spent():.2f}   review queue: {len(clog.open_reviews())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
