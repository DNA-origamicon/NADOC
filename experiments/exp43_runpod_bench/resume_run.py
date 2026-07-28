#!/usr/bin/env python3
"""Re-attach to an ORPHANED VoltronCore pod whose launcher died (session teardown), keep the
deadman heartbeat fresh, monitor NAMD to completion, fetch the trajectory, terminate the pod.

Run FULLY DETACHED so it survives a Claude-session exit (the original launcher was run_in_
background and died with the process):

    RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
      python experiments/exp43_runpod_bench/resume_run.py POD_ID \
      > /media/jojo/Archive/nadoc_voltron_prod/resume.log 2>&1 &
"""
import asyncio
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, "/home/jojo/Work/NADOC")
from backend.core.runpod_api import RunpodClient, ssh_endpoint
from backend.core.runpod_conn import RunpodConnection
from experiments.exp43_runpod_bench.campaign_common import campaign_ledger

WD = "/root/VoltronCore_compact"
HB = "/root/voltron_hb"
STEM = "prod4fs"
SSH = str(Path.home() / ".ssh/id_ed25519")
FETCH_ROOT = Path("/media/jojo/Archive/nadoc_voltron_prod")
TARGET_STEPS = 7_500_000            # 30 ns @ 4 fs
POLL_S = 120
MAX_HOURS = 26.0                    # safety cap on THIS controller (prevents runaway billing)
BLOWUP_RE = re.compile(r"(?mi)^FATAL ERROR:.*|Atoms moving too fast|Constraint failure")


async def _connect(client, pod_id):
    pod = await client.get_pod(pod_id)
    if not pod or pod.is_destroyed:
        return None, None
    host, port = ssh_endpoint(pod)
    conn = RunpodConnection(host=host, port=port, pod_id=pod_id, client_keys=[SSH])
    await conn.connect()
    return pod, conn


async def _sh(conn, cmd, timeout=60):
    return (await conn.run(cmd, timeout=timeout)).stdout


async def main():
    pod_id = sys.argv[1]
    key = (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger = campaign_ledger()
    t0 = time.time()
    status = "unknown"
    print(f"[resume] attaching to {pod_id}", flush=True)
    try:
        pod, conn = await _connect(client, pod_id)
        if conn is None:
            print("[resume] pod gone", flush=True)
            return
        while True:
            # refresh heartbeat EVERY loop so the (buggy but present) deadman never fires
            try:
                await _sh(conn, f"touch {HB}")
                log = await _sh(conn, f"tail -c 4000 {WD}/{STEM}.log 2>/dev/null || tail -c 4000 {WD}/prod.log")
            except Exception as exc:  # noqa: BLE001 — SSH blip: reconnect
                print(f"[resume] ssh blip ({str(exc)[:60]}) — reconnecting", flush=True)
                try:
                    await conn.close()
                except Exception:
                    pass
                pod, conn = await _connect(client, pod_id)
                if conn is None:
                    status = "pod_gone"
                    break
                await asyncio.sleep(POLL_S)
                continue

            steps = [int(m) for m in re.findall(r"TIMING:\s*(\d+)", log)]
            last = max(steps) if steps else 0
            hrs = (time.time() - t0) / 3600.0
            print(f"[resume] step {last:,}/{TARGET_STEPS:,}  {last*4e-6:.2f} ns  ctl {hrs:.1f}h",
                  flush=True)

            if BLOWUP_RE.search(log):
                print(f"[resume] BLOWUP: {BLOWUP_RE.search(log).group(0)[:100]}", flush=True)
                status = "blewup"
                break
            if re.search(r"(?m)^End of program", log) or last >= TARGET_STEPS:
                print("[resume] RUN COMPLETE", flush=True)
                status = "completed"
                break
            if hrs > MAX_HOURS:
                print(f"[resume] controller cap {MAX_HOURS}h — stopping to fetch", flush=True)
                status = "capped"
                break
            await asyncio.sleep(POLL_S)

        # FETCH before teardown
        if conn is not None:
            dst = FETCH_ROOT / pod_id
            dst.mkdir(parents=True, exist_ok=True)
            for ext in (".restart.coor", ".restart.vel", ".restart.xsc"):
                try:
                    await conn.sftp_get(f"{WD}/out/{STEM}{ext}", str(dst / f"{STEM}{ext}"))
                    print(f"[resume] fetched {STEM}{ext}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"[resume] fetch FAILED {STEM}{ext}: {exc}", flush=True)
            try:
                print("[resume] fetching DCD (2.4 GB — billing while it downloads)", flush=True)
                await conn.sftp_get(f"{WD}/out/{STEM}.dcd", str(dst / f"{STEM}.dcd"))
                print("[resume] DCD fetched", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[resume] DCD fetch FAILED: {exc}", flush=True)
            try:
                await conn.close()
            except Exception:  # noqa: BLE001
                pass
    finally:
        # terminate the pod + close the ledger row, no matter what
        try:
            await client.terminate_pod(pod_id)
            ledger.close_pod(pod_id)
            live = [p for p in await client.list_pods() if not p.is_destroyed]
            print(f"[resume] terminated; live pods now: {len(live)}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[resume] TERMINATE FAILED ({exc}) — RUN reap.py --kill MANUALLY", flush=True)
        await client.aclose()
    print(f"[resume] status={status}   results in {FETCH_ROOT / pod_id}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
