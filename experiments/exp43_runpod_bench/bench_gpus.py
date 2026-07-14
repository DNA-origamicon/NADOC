#!/usr/bin/env python3
"""Calibrate $/ns across every GPU the NAMD build can actually run.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/bench_gpus.py [--budget 2.0] [--steps 2000]

**The number that matters is $/ns, not $/hr.** A cheap slow card can be worse value than a
dear fast one, and we had no way to tell: the measured 11.2 ms/step/Matom fit came from a
4090 and predicted 20.9 ms/step for the 1.94M-atom 3x6x400 — the RTX PRO 4500 Blackwell
actually does 26.4. **The per-Matom fit does not transfer across architectures.** The only
way to know a card's $/ns is to run the real system on it.

Which is now cheap: the relaxed structure is already ON the network volume. A benchmark is
"rent → 2000 steps → destroy", ~5 min and a few cents.

⚠️ **ARCH IS FATAL AND SILENT.** A card outside NAMD_BUILD_ARCHS rents FINE and dies at step
0 with "no kernel image is available for execution". Note especially that **datacenter
Blackwell (B200) is sm_100, NOT sm_120** — it reads as "Blackwell" and will not run. Only
cards whose arch we can positively name are offered here.

Benchmarks the PRODUCTION conf (fullElectFrequency 1, stepspercycle 10) — not the
relaxation's, which is a cheaper integrator and would flatter every card by ~1.35x.

Safety: pods run ONE AT A TIME, each is destroyed in a finally, the sweep stops when its own
budget is exhausted, and everything is written under /workspace/nadoc_bench/ so a live
production job in /workspace/nadoc_jobs/ cannot be touched. (The volume is MooseFS — a
distributed FS built for concurrent mounts — so a bench pod is safe alongside a live run.)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob  # noqa: E402
from backend.core.runpod_api import (  # noqa: E402
    RunpodClient,
    build_create_payload,
    ssh_endpoint,
)
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from backend.core.runpod_executor import NAMD_ON_VOLUME, namd_threads  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import (  # noqa: E402
    HARD_CAP_USD,
    SpendLedger,
)

WORKSPACE = ROOT / "workspace"
NETWORK_VOLUME = "77pnhye88p"
PARENT_ID = (Path(__file__).parent / "JOB_ID_3x6x400").read_text().strip()
BENCH_ROOT = "/workspace/nadoc_bench"
LEDGER = Path("/media/jojo/Archive/nadoc_jobs") / PARENT_ID / "spend.json"
SSH_KEY = str(Path.home() / ".ssh" / "id_ed25519")

TIMESTEP_FS = 4.0

# ⚠️ $/ns ALONE IS THE WRONG METRIC. It ranks a cheap crawling card top: an RTX 4000 Ada at
# $0.26/hr doing 4 ns/day has fine $/ns and is useless — a 5 ns production would take 30
# hours. Wall-clock is a first-class constraint, not a tiebreak. A card is only USABLE if it
# can deliver a target run inside a working window; among usable cards, THEN take the
# cheapest $/ns.
TARGET_NS = 5.0            # the production run we actually want
MAX_WALL_H = 12.0          # ...and the window we want it inside (an overnight)
MIN_USEFUL_NS_DAY = TARGET_NS * 24 / MAX_WALL_H     # = 10 ns/day

# (runpod gpuTypeId, label, sm, $/hr secure). ONLY cards whose arch we can positively name
# and that hold 1.94M atoms GPU-resident (~6.6 GB). Prices live-checked 2026-07-14.
#
# DELIBERATELY ABSENT: A100 (sm_80), H100/H200 (sm_90), B200 (sm_100). Every one of them
# rents fine and dies at step 0. B200 is the trap — "Blackwell", but not sm_120.
CANDIDATES = [
    ("NVIDIA RTX 4000 Ada Generation",      "RTX 4000 Ada",     "sm_89",  0.26),
    ("NVIDIA L4",                            "L4",               "sm_89",  0.39),
    ("NVIDIA RTX PRO 6000 Blackwell Max-Q Workstation Edition",
                                             "RTX PRO 6000 MaxQ", "sm_120", 0.50),
    ("NVIDIA GeForce RTX 4090",              "RTX 4090",         "sm_89",  0.69),
    ("NVIDIA RTX 6000 Ada Generation",       "RTX 6000 Ada",     "sm_89",  0.77),
    ("NVIDIA GeForce RTX 5090",              "RTX 5090",         "sm_120", 0.99),
    ("NVIDIA L40S",                          "L40S",             "sm_89",  0.99),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bench")
for noisy in ("asyncssh", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


async def prepare_bench_dir(conn, parent_remote: str, name_stem: str, steps: int,
                            final_ckpt: str, sdir: str) -> str:
    """Copy the package server-side and write a short production conf. Costs no upload."""
    prod_conf = None
    r = await conn.run(f"ls {parent_remote}/*production*.conf 2>/dev/null | head -1")
    # The relaxation dir has no production conf; take the child's if present, else build
    # from the relaxation's last fast conf. Simplest: use the production child's package.
    r2 = await conn.run(
        f"ls /workspace/nadoc_jobs/*/[!.]*production*.conf 2>/dev/null | head -1")
    prod_conf = (r.stdout.strip() or r2.stdout.strip()).splitlines()[0] if (
        r.stdout.strip() or r2.stdout.strip()) else None
    if not prod_conf:
        raise RuntimeError("no production conf on the volume to benchmark")

    src = prod_conf.rsplit("/", 1)[0]
    await conn.run(f"mkdir -p {sdir}/output")
    # Hardlink/copy the package next to the bench conf — a `cp` ON THE VOLUME, not an upload.
    await conn.run(
        f"cp -n {src}/*.psf {src}/*.pdb {src}/*.txt {sdir}/ 2>/dev/null; "
        f"cp -rn {src}/forcefield {sdir}/ 2>/dev/null; "
        f"cp -n {src}/*.extra {sdir}/ 2>/dev/null; true", timeout=300.0)
    # Seed from the RELAXED final checkpoint (the whole point — this is a real, equilibrated
    # 1.94M-atom system, not a fresh box).
    await conn.run(
        f"cp -n {parent_remote}/output/{final_ckpt}.coor {sdir}/output/ 2>/dev/null; "
        f"cp -n {parent_remote}/output/{final_ckpt}.vel  {sdir}/output/ 2>/dev/null; "
        f"cp -n {parent_remote}/output/{final_ckpt}.xsc  {sdir}/output/ 2>/dev/null; true",
        timeout=300.0)

    # Short run, no trajectory, sparse energies — we want ms/step, nothing else.
    conf = (await conn.run(f"cat {prod_conf}")).stdout
    conf = re.sub(r"(?m)^run\s+\d+", f"run                {steps}", conf)
    conf = re.sub(r"(?m)^outputEnergies\s+\d+", "outputEnergies     200", conf)
    conf = re.sub(r"(?m)^dcdFreq\s+\d+", "dcdFreq            0", conf)
    conf = re.sub(r"(?m)^restartfreq\s+\d+", f"restartfreq        {steps * 10}", conf)
    conf = re.sub(r"(?m)^outputName\s+\S+", "outputName         output/bench", conf)
    conf = re.sub(r"(?m)^bin(Coordinates|Velocities)\s+\S+",
                  lambda m: f"bin{m.group(1)}     output/{final_ckpt}"
                            f".{'coor' if m.group(1) == 'Coordinates' else 'vel'}", conf)
    conf = re.sub(r"(?m)^extendedSystem\s+\S+",
                  f"extendedSystem     output/{final_ckpt}.xsc", conf)
    await conn.run(f"cat > {sdir}/bench.conf << 'NADOC_EOF'\n{conf}\nNADOC_EOF", timeout=120.0)
    return f"{sdir}/bench.conf"


async def bench_one(client, ledger, gpu_id, label, sm, usd_hr, steps, parent_remote,
                    name_stem, final_ckpt) -> dict:
    payload = build_create_payload(
        name=f"nadoc-bench-{slug(label)}",
        gpu_type_ids=[gpu_id],
        network_volume_id=NETWORK_VOLUME,
        interruptible=False,
        cloud_type="SECURE",
    )
    result = {"label": label, "sm": sm, "usd_hr": usd_hr, "ms_step": None, "note": ""}
    t0 = time.time()
    seen: list[str] = []

    def _booked(info):
        # BILLING STARTS HERE — not at the yield. A pod whose host is too old for the
        # image's CUDA boots, never starts sshd, and bills for the whole wait_for_ssh
        # timeout before we destroy it. Booking at the yield made that spend INVISIBLE.
        seen.append(info.id)
        ledger.open_pod(info.id, float(info.cost_per_hr or usd_hr), note=f"bench {label}")

    try:
        async with client.pod(payload, on_created=_booked) as pod:   # destroys in a finally
            rate = float(pod.cost_per_hr or usd_hr)
            result["usd_hr"] = rate
            log.info("%-20s pod %s at $%.2f/hr", label, pod.id, rate)

            host, port = ssh_endpoint(pod)
            conn = RunpodConnection(host=host, port=port, pod_id=pod.id,
                                    client_keys=[SSH_KEY])
            await conn.connect()
            try:
                vcpus = int((await conn.run("nproc")).stdout.strip() or 8)
                sdir = f"{BENCH_ROOT}/{slug(label)}"
                conf = await prepare_bench_dir(conn, parent_remote, name_stem, steps,
                                               final_ckpt, sdir)
                threads = namd_threads(vcpus)
                cmd = (f"cd {sdir} && {NAMD_ON_VOLUME} +p{threads} +setcpuaffinity "
                       f"+devices 0 {conf} > bench.log 2>&1; echo done")
                await conn.run(cmd, timeout=1800.0)
                log_txt = (await conn.run(f"tail -c 60000 {sdir}/bench.log")).stdout

                if "no kernel image is available" in log_txt:
                    result["note"] = "WRONG ARCH — died at step 0"
                    return result
                m = re.findall(r"Benchmark time:.*?([\d.]+)\s+s/step", log_txt)
                if not m:
                    fatal = re.search(r"^FATAL ERROR:.*", log_txt, re.M)
                    result["note"] = (fatal.group(0)[:70] if fatal else "no benchmark line")
                    return result
                # NAMD's first Benchmark line is warm-up; take the settled tail.
                s_per_step = sum(float(x) for x in m[-3:]) / len(m[-3:])
                result["ms_step"] = s_per_step * 1000
            finally:
                await conn.close()
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        result["note"] = ("unavailable in EU-RO-1"
                          if "no instances" in msg else msg[:70])
    finally:
        for pid in seen:
            ledger.close_pod(pid)
        result["pod_min"] = (time.time() - t0) / 60
    return result


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=2000)
    ap.add_argument("--budget", type=float, default=2.0,
                    help="hard cap for the WHOLE sweep, on top of the session ledger")
    ap.add_argument("--only", default="", help="comma-separated labels")
    args = ap.parse_args()

    parent = MdJob.load(PARENT_ID, WORKSPACE)
    parent_remote = f"/workspace/nadoc_jobs/{parent.job_id}"
    final_ckpt = parent.segments[-1].name          # the relaxed structure
    ledger = SpendLedger(LEDGER)
    client = RunpodClient(os.environ["RUNPOD_API_KEY"])

    start_spend = ledger.spent()
    log.info("session spend so far: $%.2f / $%.2f", start_spend, HARD_CAP_USD)
    log.info("sweep budget: $%.2f    seed: %s", args.budget, final_ckpt)

    want = [c for c in CANDIDATES
            if not args.only or c[1] in [s.strip() for s in args.only.split(",")]]
    results = []
    try:
        for gpu_id, label, sm, usd_hr in want:
            spent = ledger.spent() - start_spend
            if spent >= args.budget:
                log.warning("sweep budget exhausted ($%.2f) — stopping", spent)
                break
            if ledger.spent() > HARD_CAP_USD - 1.0:
                log.error("SESSION cap nearly hit ($%.2f) — stopping", ledger.spent())
                break
            r = await bench_one(client, ledger, gpu_id, label, sm, usd_hr, args.steps,
                                parent_remote, parent.name_stem, final_ckpt)
            results.append(r)
            if r["ms_step"]:
                nsday = TIMESTEP_FS * 1e-6 / (r["ms_step"] / 1000) * 86400
                log.info("%-20s %6.1f ms/step  %5.1f ns/day  $%.2f/ns",
                         label, r["ms_step"], nsday, r["usd_hr"] * 24 / nsday)
            else:
                log.warning("%-20s SKIPPED — %s", label, r["note"])
    finally:
        live = [p for p in await client.list_pods() if not p.is_destroyed]
        bench_live = [p for p in live if str(p.raw.get("name", "")).startswith("nadoc-bench")]
        for p in bench_live:
            log.error("bench pod %s SURVIVED — destroying", p.id)
            await client.terminate_pod(p.id)
            ledger.close_pod(p.id)
        await client.aclose()

    def nsday(r):
        return TIMESTEP_FS * 1e-6 / (r["ms_step"] / 1000) * 86400

    ok = [r for r in results if r["ms_step"]]
    for r in ok:
        r["ns_day"] = nsday(r)
        r["usd_ns"] = r["usd_hr"] * 24 / r["ns_day"]
        r["h_for_target"] = TARGET_NS * 24 / r["ns_day"]
        r["usable"] = r["ns_day"] >= MIN_USEFUL_NS_DAY

    print("\n" + "=" * 86)
    print(f"GPU CALIBRATION — 3x6x400, 1.94M atoms, PRODUCTION conf ({args.steps} steps)")
    print(f"target: {TARGET_NS:g} ns inside {MAX_WALL_H:g} h  =>  need "
          f">= {MIN_USEFUL_NS_DAY:.1f} ns/day to be USABLE")
    print("=" * 86)
    hdr = (f"{'card':22s} {'arch':8s} {'$/hr':>6s} {'ms/step':>8s} {'ns/day':>7s} "
           f"{'$/ns':>7s} {'h for ' + format(TARGET_NS, 'g') + 'ns':>10s}   verdict")
    print(hdr)
    print("-" * 86)
    # Cheapest $/ns FIRST, but only among cards fast enough to be usable. The too-slow ones
    # are listed after, however good their $/ns looks — that is the whole point.
    for r in sorted([x for x in ok if x["usable"]], key=lambda x: x["usd_ns"]):
        print(f"{r['label']:22s} {r['sm']:8s} {r['usd_hr']:6.2f} {r['ms_step']:8.1f} "
              f"{r['ns_day']:7.1f} {r['usd_ns']:7.2f} {r['h_for_target']:10.1f}   OK")
    for r in sorted([x for x in ok if not x["usable"]], key=lambda x: x["usd_ns"]):
        print(f"{r['label']:22s} {r['sm']:8s} {r['usd_hr']:6.2f} {r['ms_step']:8.1f} "
              f"{r['ns_day']:7.1f} {r['usd_ns']:7.2f} {r['h_for_target']:10.1f}   "
              f"TOO SLOW — cheap $/ns, but {TARGET_NS:g} ns takes {r['h_for_target']:.0f} h")
    for r in results:
        if not r["ms_step"]:
            print(f"{r['label']:22s} {r['sm']:8s}   --  {r['note']}")

    usable = [x for x in ok if x["usable"]]
    print()
    if usable:
        best_cost = min(usable, key=lambda x: x["usd_ns"])
        best_fast = max(usable, key=lambda x: x["ns_day"])
        print(f"cheapest USABLE : {best_cost['label']}  ${best_cost['usd_ns']:.2f}/ns  "
              f"({best_cost['ns_day']:.1f} ns/day)")
        print(f"fastest USABLE  : {best_fast['label']}  {best_fast['ns_day']:.1f} ns/day  "
              f"(${best_fast['usd_ns']:.2f}/ns)")
    elif ok:
        # NEVER call the cheapest of a bad field "the best". A card that cannot finish the
        # target run in the window is not a candidate, however little it costs per ns.
        print(f"*** NO CARD BENCHMARKED IS USABLE *** (need >= {MIN_USEFUL_NS_DAY:.1f} "
              f"ns/day; best was {max(ok, key=lambda x: x['ns_day'])['ns_day']:.1f})")
    print(f"\nsweep cost: ${ledger.spent() - start_spend:.2f}   "
          f"session total: ${ledger.spent():.2f} / ${HARD_CAP_USD:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
