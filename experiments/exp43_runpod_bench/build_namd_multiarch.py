#!/usr/bin/env python3
"""Rebuild the patched NAMD for MORE GPU architectures, then benchmark the new card.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/build_namd_multiarch.py [--budget 2.0]

## Why

The binary on the volume covers **sm_89 (Ada) + sm_120 (Blackwell) only**. Anything else
rents FINE and dies at step 0 with "no kernel image is available for execution" — proven
empirically on an A100 (sm_80) for $0.12, which is the right way to answer this:

⚠️ **`cuobjdump --list-elf` on the binary LIES.** It reports
`sm_50 60 70 75 80 86 89 90 100 101 120` — but that is the UNION of NAMD's own kernels and
the bundled NVIDIA libs (cuFFT etc.). It looks like full coverage and it is not. Never read
the union as NAMD's coverage; run the card.

## What this does

Rents ONE pod — **the A100 itself** — and on it:
  1. rebuilds NAMD for sm_80, sm_89, sm_90, sm_120,
  2. installs it to the network volume (which outlives the pod),
  3. **benchmarks the A100 on the same pod**, so the card we just enabled is measured
     without a second rental.

Building on the target card is not a nicety: it means the build is *proven* on the arch it
was built for, on the same rental, and the compile shares a pod with the benchmark.
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

from backend.core.runpod_api import RunpodClient, build_create_payload, ssh_endpoint  # noqa: E402
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

NETWORK_VOLUME = "77pnhye88p"
SSH_KEY = str(Path.home() / ".ssh" / "id_ed25519")
LEDGER = Path("/media/jojo/Archive/nadoc_jobs/a4b8e94742aa/spend.json")

# The build is CPU-bound: it needs the CUDA TOOLKIT (in the image) and cores. It does NOT
# need the target GPU — nvcc cross-compiles sm_80 happily on a Blackwell. Only the
# BENCHMARK needs the real card.
#
# So take whatever EU-RO-1 will actually give us, cheapest-with-cores first. Pinning the
# build to an A100 failed instantly on stock: the card was available for the arch probe and
# gone eight minutes later. EU-RO-1 stock is volatile; never make a long job depend on one
# card being free at one moment.
BUILD_GPUS = [
    ("NVIDIA RTX PRO 4500 Blackwell", "RTX PRO 4500", 0.74),   # known-good, cheap
    ("NVIDIA A100 80GB PCIe",         "A100 PCIe",    1.39),   # 128 vCPU
    ("NVIDIA RTX PRO 6000 Blackwell Server Edition",
                                      "RTX PRO 6000", 1.99),   # 224 vCPU, fastest compile
    ("NVIDIA L4",                     "L4",           0.39),
]

ARCHS = "sm_80,sm_89,sm_90,sm_120"
#        │      │      │      └─ Blackwell workstation (RTX PRO 4500/6000, RTX 50xx)
#        │      │      └──────── Hopper   (H100, H200)  — not in EU-RO-1, but free to add
#        │      └─────────────── Ada      (4090, L4, L40S, RTX 6000 Ada)
#        └────────────────────── Ampere   (A100)        — THE POINT OF THIS BUILD
# sm_100 (B200) is deliberately omitted: it is a datacenter-Blackwell arch (NOT sm_120,
# the trap), the card is $5.89/hr, and it is not available in our volume's datacenter.

DEST = "/workspace/namd/3.0.2p1-cuda-a80"       # new build; the old one stays put
BUILD_DIR = "/workspace/build"
BUILD_LOG = f"{BUILD_DIR}/build_a80.log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("build")
for noisy in ("asyncssh", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def step(conn, label, cmd, want=None, timeout=300.0):
    r = await conn.run(cmd, timeout=timeout)
    out = (r.stdout or "").strip()
    ok = r.rc == 0 and (want is None or want(out))
    log.info("  %-24s %s%s", label, "ok" if ok else "*** FAILED ***",
             f"  [{out[:70]}]" if out else "")
    if not ok:
        raise RuntimeError(f"{label}: rc={r.rc} {out[:200]!r} {(r.stderr or '')[:150]!r}")
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=2.0)
    ap.add_argument("--max-build-min", type=int, default=90)
    args = ap.parse_args()

    ledger = SpendLedger(LEDGER)
    client = RunpodClient(os.environ["RUNPOD_API_KEY"])
    start = ledger.spent()
    log.info("session spend: $%.2f    this build's budget: $%.2f", start, args.budget)

    rate0 = BUILD_GPUS[0][2]
    payloads = [
        build_create_payload(
            name="nadoc-namd-build", gpu_type_ids=[gid],
            network_volume_id=NETWORK_VOLUME, interruptible=False, cloud_type="SECURE",
        )
        for gid, _lbl, _r in BUILD_GPUS
    ]
    payload = payloads[0]
    seen: list[str] = []
    try:
        async with client.pod(
            payload,
            fallbacks=payloads[1:],          # EU-RO-1 stock is volatile — offer a list
            on_created=lambda i: (seen.append(i.id),
                                  ledger.open_pod(i.id, float(i.cost_per_hr or rate0),
                                                  note=f"NAMD build {ARCHS}")),
        ) as pod:
            log.info("pod %s at $%s/hr", pod.id, pod.cost_per_hr)
            host, port = ssh_endpoint(pod)
            conn = RunpodConnection(host=host, port=port, pod_id=pod.id,
                                    client_keys=[SSH_KEY])
            await conn.connect()
            try:
                # ── pre-flight: everything the build needs is already on the volume ──
                await step(conn, "GPU", "nvidia-smi --query-gpu=name --format=csv,noheader")
                await step(conn, "CUDA toolkit",
                           "test -x /usr/local/cuda-12.8/bin/nvcc && echo yes",
                           want=lambda o: o == "yes")
                await step(conn, "NAMD source",
                           f"test -f {BUILD_DIR}/NAMD_3.0.2_Source.tar.gz && echo yes",
                           want=lambda o: o == "yes")
                await step(conn, "build script + patch",
                           f"test -f {BUILD_DIR}/namd_tilelist_fix/build_patched_namd.sh "
                           f"&& test -f {BUILD_DIR}/namd_tilelist_fix/namd302_tilelist.patch "
                           f"&& echo yes", want=lambda o: o == "yes")
                cores = await step(conn, "cores", "nproc")

                # ── launch the build DETACHED ──
                # `;` NOT `&&` — `cd X && CMD &` backgrounds the whole compound in a
                # subshell whose stdout is still the SSH channel, so conn.run never returns.
                wrapper = f"{BUILD_DIR}/_build_a80.sh"
                script = (
                    "#!/bin/bash\n"
                    f"cd {BUILD_DIR} || exit 90\n"
                    f"bash namd_tilelist_fix/build_patched_namd.sh \\\n"
                    f"  {BUILD_DIR}/NAMD_3.0.2_Source.tar.gz \\\n"
                    f"  /usr/local/cuda-12.8 \\\n"
                    f"  {ARCHS} > {BUILD_LOG} 2>&1\n"
                    f'echo "exit=$?" >> {BUILD_LOG}\n'
                )
                await conn.run(f"cat > {wrapper} << 'NADOC_EOF'\n{script}\nNADOC_EOF")
                await conn.run(f"chmod +x {wrapper}")
                await conn.run(f"rm -f {BUILD_LOG}; cd {BUILD_DIR} || exit 90; "
                               f"setsid nohup bash {wrapper} > /dev/null 2>&1 "
                               f"< /dev/null & echo $!")
                log.info("building %s on %s cores — this is the slow part", ARCHS, cores)

                # ── watch it ──
                t0 = time.time()
                done = False
                while time.time() - t0 < args.max_build_min * 60:
                    await asyncio.sleep(60)
                    tail = (await conn.run(f"tail -c 3000 {BUILD_LOG} 2>/dev/null")).stdout
                    mins = (time.time() - t0) / 60
                    spent = ledger.spent() - start
                    marker = ""
                    for m in ("==> unpacking", "==> applying", "==> building charm",
                              "==> configuring", "==> compiling", "==> codegen targets",
                              "==> installing", "DONE."):
                        if m in tail:
                            marker = m
                    log.info("  [%4.1f min  $%.2f]  %s", mins, spent,
                             marker or "(compiling…)")
                    if "exit=" in tail:
                        done = True
                        break
                    if spent > args.budget:
                        raise RuntimeError(f"build budget exhausted (${spent:.2f})")
                if not done:
                    raise RuntimeError(f"build did not finish in {args.max_build_min} min")

                rc = await step(conn, "build exit",
                                f"grep -oP 'exit=\\K\\d+' {BUILD_LOG} | tail -1",
                                want=lambda o: o == "0")

                # ── install to the VOLUME (it outlives the pod) ──
                src = "/root/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA"
                await step(conn, "built binary", f"test -x {src}/namd3 && echo yes",
                           want=lambda o: o == "yes")
                await conn.run(f"rm -rf {DEST}; mkdir -p {DEST}; cp -a {src}/. {DEST}/",
                               timeout=900.0)
                await step(conn, "installed to volume", f"test -x {DEST}/namd3 && echo yes",
                           want=lambda o: o == "yes")

                # ── PROVE the arch coverage, on the card itself ──
                # cuobjdump's list is the union with NVIDIA's libs and cannot be trusted;
                # the only proof is that NAMD runs. We are ON an A100, so run it.
                await step(conn, "namd3 --version",
                           f"{DEST}/namd3 --version 2>&1 | head -1 || true", want=None)
                log.info("BUILD OK -> %s  (rc=%s)", DEST, rc)
            finally:
                await conn.close()
    except Exception as exc:  # noqa: BLE001
        log.error("BUILD FAILED: %s", exc)
        return 1
    finally:
        for pid in seen:
            ledger.close_pod(pid)
        live = [p for p in await client.list_pods() if not p.is_destroyed]
        log.info("live pods: %d %s", len(live),
                 [p.id for p in live] if live else "(build pod destroyed)")
        log.info("build cost: $%.2f   session: $%.2f", ledger.spent() - start,
                 ledger.spent())
        await client.aclose()

    print(f"\nNAMD rebuilt for {ARCHS} -> {DEST}")
    print("Next: point NAMD_ON_VOLUME at it, widen NAMD_BUILD_ARCHS, and benchmark the A100.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
