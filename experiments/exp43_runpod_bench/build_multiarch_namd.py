#!/usr/bin/env python
"""Build a MULTI-ARCH patched NAMD on a rented Blackwell pod, and prove it runs there.

Why: the binary on the volume is sm_89-only (Ada). RunPod's `RTX PRO 4500 Blackwell` is
**32 GB at $0.34/hr with HIGH stock** — same price as a 4090, 33% more VRAM, and actually
available (the 4090 is perpetually "Low", which is what kept giving us
`500 "There are no instances currently available"`). But it is sm_120, so the sm_89
binary rents fine and dies at step 0 with "no kernel image is available".

So: build for sm_89 + sm_120 (+ a PTX fallback so a future card can JIT instead of
hard-failing), verify the cubins, and SMOKE-TEST NAMD ON THE BLACKWELL CARD before
trusting it. Then install to the volume and destroy the pod.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) python experiments/exp43_runpod_bench/build_multiarch_namd.py

⚠️ Creates a real, billing pod. Terminates it in a `finally`.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.runpod_api import (  # noqa: E402
    RunpodClient,
    build_create_payload,
    ssh_endpoint,
)
from backend.core.runpod_conn import RunpodConnection  # noqa: E402

VOLUME = "77pnhye88p"
GPU = "NVIDIA RTX PRO 4500 Blackwell"   # 32 GB, sm_120, $0.34/hr, HIGH stock
ARCHS = "sm_89,sm_120"                  # Ada + Blackwell in one binary
CUDA = "/usr/local/cuda-12.8"           # 12.8 is the FIRST toolkit that can target sm_120
DEST = "/workspace/namd/3.0.2p1-cuda-multi"

KEY = [str(Path.home() / ".ssh" / "id_ed25519")]


async def sh(conn, cmd, timeout=60.0, label=None):
    if label:
        print(f"  {label}", flush=True)
    res = await conn.run(cmd, timeout=timeout)
    return res


async def main() -> int:
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2

    client = RunpodClient(api_key)
    payload = build_create_payload(
        name="nadoc-namd-multiarch-build",
        gpu_type_ids=[GPU],
        network_volume_id=VOLUME,
        interruptible=False,       # do NOT let a 30-min build get reclaimed
        cloud_type="SECURE",   # COMMUNITY has no PRO 4500 in EU-RO-1 (the "High stock" figure is GLOBAL)
        container_disk_gb=60,      # the NAMD build tree is big
    )

    try:
        async with client.pod(payload) as pod:
            print(f"pod {pod.id} — {GPU} @ ${pod.cost_per_hr}/hr (BILLING)", flush=True)
            host, port = ssh_endpoint(pod)
            conn = RunpodConnection(host=host, port=port, pod_id=pod.id, client_keys=KEY)
            await conn.connect()

            r = await sh(conn, "nvidia-smi --query-gpu=name,memory.total,compute_cap "
                               "--format=csv,noheader")
            print(f"  card    : {r.stdout.strip()}", flush=True)
            r = await sh(conn, f"{CUDA}/bin/nvcc --version | tail -2 | head -1")
            print(f"  nvcc    : {r.stdout.strip()}", flush=True)

            # The updated build script lives locally; the volume's copy is the old one.
            await conn.sftp_put(
                "tools/namd_tilelist_fix/build_patched_namd.sh",
                "/workspace/build/namd_tilelist_fix/build_patched_namd.sh",
            )
            await sh(conn, "chmod +x /workspace/build/namd_tilelist_fix/build_patched_namd.sh")

            print(f"\n  building NAMD for {ARCHS} (~30-45 min, multi-arch doubles the nvcc pass)…",
                  flush=True)
            # `cd X && CMD &` re-subshells the launch and that subshell's stdout is
            # still the SSH channel, so conn.run never returns.  launch_detached() gets
            # this right (setsid + `;` + full stdio redirection) — use it, do not
            # hand-roll it (I did, and it hung, twice).
            await conn.sftp_put(
                str(Path(__file__).parent / "_build_multi.sh"),
                "/workspace/build/_build_multi.sh",
            )
            pid = await conn.launch_detached("/workspace/build/_build_multi.sh",
                                             "/workspace/build")
            print(f"  build pid {pid}", flush=True)

            # Poll until the script writes DONE or dies.
            while True:
                await asyncio.sleep(60)
                r = await sh(conn, "tail -1 /workspace/build/build_multi.log")
                alive = await conn.pid_alive(pid)
                tail = r.stdout.strip()[:90]
                print(f"    [{'running' if alive else 'ended  '}] {tail}", flush=True)
                if not alive:
                    break

            r = await sh(conn, "grep -c '^DONE' /workspace/build/build_multi.log || true")
            if "1" not in r.stdout:
                r = await sh(conn, "tail -25 /workspace/build/build_multi.log")
                print("\n  *** BUILD FAILED ***\n" + r.stdout, flush=True)
                return 1

            # ── verify the cubins ───────────────────────────────────────────
            built = "/root/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/namd3"
            r = await sh(
                conn,
                f"{CUDA}/bin/cuobjdump --list-elf {built} | grep -oE 'sm_[0-9]+' "
                "| sort | uniq -c | sort -rn | head -6",
            )
            print("\n  cubins in the new binary (NAMD's own kernels dominate the counts):")
            print("".join(f"    {l}\n" for l in r.stdout.strip().splitlines()), flush=True)

            # ── SMOKE TEST ON THE BLACKWELL CARD ────────────────────────────
            # The only thing that actually proves it: run NAMD, on this card, now.
            print("  smoke-testing NAMD on the Blackwell card (6hb minimisation)…", flush=True)
            await sh(conn, f"mkdir -p {DEST} && cp {built} {DEST}/namd3 && chmod +x {DEST}/namd3")
            r = await sh(
                conn,
                "cd /workspace/bench/packages/6hb && "
                f"sed 's/^minimize .*/minimize 120/' 6hb_sim_v2_00_min_enm_k0p5.conf "
                "> smoke.conf && "
                f"timeout 900 {DEST}/namd3 +p8 +setcpuaffinity +devices 0 smoke.conf "
                "> smoke.log 2>&1; echo rc=$?",
                timeout=1000,
            )
            r = await sh(
                conn,
                "cd /workspace/bench/packages/6hb && "
                "grep -icE 'no kernel image|FATAL' smoke.log; "
                "grep -c '^ENERGY:' smoke.log",
            )
            fatal, frames = (r.stdout.split() + ["?", "?"])[:2]
            print(f"    fatal/no-kernel-image lines: {fatal}", flush=True)
            print(f"    ENERGY frames produced    : {frames}", flush=True)

            ok = fatal == "0" and frames.isdigit() and int(frames) > 0
            if ok:
                print(f"\n  ✓ NAMD RUNS ON BLACKWELL. Installed at {DEST}/namd3", flush=True)
            else:
                r = await sh(conn, "tail -6 /workspace/bench/packages/6hb/smoke.log")
                print("\n  ✗ NAMD did NOT run on this card:\n" + r.stdout, flush=True)
                await sh(conn, f"rm -rf {DEST}")   # don't leave a broken binary on the volume

            await conn.close()
            return 0 if ok else 1
    finally:
        live = [p for p in await client.list_pods() if not p.is_terminated]
        print(f"\nlive pods after teardown: {len(live)} "
              f"{'✓ nothing billing' if not live else '*** ' + str([p.id for p in live])}",
              flush=True)
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
