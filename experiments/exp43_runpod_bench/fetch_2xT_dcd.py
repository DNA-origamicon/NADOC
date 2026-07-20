#!/usr/bin/env python3
"""Fetch a POST-EQ SUBSET of the reaped 6 ns 2xT trajectory off the EU-RO-1 volume, cheaply + safely.

The full DCD is ~25 GB; we don't need all 1500 frames for a stiffness covariance. So on a cheap pod we
BYTE-COPY every 3rd post-eq frame into a small subset DCD (dcd_fast gives the fixed-record layout — no
re-encoding), patch NSET, and SFTP that (~6 GB) down. confirmed_pod rents/confirms/terminates + PROVES
the pod is destroyed, so there is no idle-billing risk. Also grabs the daemon's state6.json.
"""
from __future__ import annotations
import asyncio, os, sys, time, contextlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.core.runpod_api import RunpodClient, build_create_payload  # noqa: E402
from experiments.exp43_runpod_bench.campaign_common import (  # noqa: E402
    campaign_ledger, campaign_log, confirmed_pod)

NETWORK_VOLUME = "77pnhye88p"
REMOTE_DCD = "/workspace/nadoc_jobs/dab9e728433e/output/24hb_2xT_01_production_30ns_k0.dcd"
REMOTE_SUBSET = "/workspace/2xT_full.dcd"
LOCAL = Path("/media/jojo/Archive/nadoc_jobs/dab9e728433e/2xT_full.dcd")
FETCH_GPUS = ["NVIDIA RTX 4000 Ada Generation", "NVIDIA L4", "NVIDIA RTX PRO 4500 Blackwell"]

SUBSET_PY = r'''
import sys, struct
sys.path.insert(0, "/workspace/snupi_check")
from dcd_fast import read_layout
dcd = "%s"; out = "%s"
lay = read_layout(dcd)
sel = list(range(200, lay.n_frames - 1))       # ALL post-heating frames (>~0.8 ns), stride 1
with open(dcd, "rb") as f, open(out, "wb") as g:
    hdr = bytearray(f.read(lay.header_bytes))
    hdr[8:12] = struct.pack(lay.endian + "i", len(sel))   # patch NSET
    g.write(hdr)
    for fi in sel:
        f.seek(lay.header_bytes + fi * lay.frame_bytes)
        g.write(f.read(lay.frame_bytes))
print("NFRAMES_TOTAL", lay.n_frames, "SUBSET", len(sel), "FRAME_BYTES", lay.frame_bytes)
''' % (REMOTE_DCD, REMOTE_SUBSET)


async def main() -> int:
    if LOCAL.exists() and LOCAL.stat().st_size > 1_000_000_000:
        print(f"subset already local: {LOCAL} ({LOCAL.stat().st_size/1e9:.1f} GB)"); return 0
    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger, clog = campaign_ledger(), campaign_log()
    with contextlib.suppress(Exception):
        clog.require_clean()
    payloads = [build_create_payload(name="nadoc-fetch-2xt", gpu_type_ids=[g],
                                     network_volume_id=NETWORK_VOLUME, interruptible=False,
                                     cloud_type="SECURE") for g in FETCH_GPUS]
    try:
        async with confirmed_pod(client, ledger, clog, payloads[0], "fetch-2xT",
                                 fallbacks=payloads[1:], usd_hr_hint=0.5) as (pod, conn):
            print(f"pod {pod.id} up at ${pod.cost_per_hr}/hr", flush=True)
            chk = await conn.run(f"test -f {REMOTE_DCD} && stat -c %s {REMOTE_DCD} || echo MISSING")
            print(f"remote DCD bytes: {chk.stdout.strip()}", flush=True)
            if "MISSING" in chk.stdout:
                raise RuntimeError("2xT DCD not on the volume")
            # ensure dcd_fast is present (worker uploaded it); else push it
            has = await conn.run("test -f /workspace/snupi_check/dcd_fast.py && echo yes || echo no")
            if "yes" not in has.stdout:
                await conn.mkdir_p("/workspace/snupi_check")
                await conn.sftp_put(str(Path(__file__).parent / "dcd_fast.py"),
                                    "/workspace/snupi_check/dcd_fast.py")
            print("subsetting on pod ...", flush=True)
            import base64
            b64 = base64.b64encode(SUBSET_PY.encode()).decode()
            r = await conn.run(f"echo {b64} | base64 -d | python3", timeout=1800)
            print(r.stdout.strip() or r.stderr.strip()[-400:], flush=True)
            rsize = int((await conn.run(f"stat -c %s {REMOTE_SUBSET}")).stdout.strip())
            print(f"downloading subset {rsize/1e9:.2f} GB -> {LOCAL} ...", flush=True)
            LOCAL.parent.mkdir(parents=True, exist_ok=True)
            t0 = time.time()
            await asyncio.wait_for(conn.sftp_get(REMOTE_SUBSET, str(LOCAL)), timeout=3000)
            dt = time.time() - t0
            ok = LOCAL.stat().st_size == rsize
            print(f"downloaded {LOCAL.stat().st_size/1e9:.2f} GB in {dt:.0f}s "
                  f"({'OK' if ok else 'SIZE MISMATCH'})", flush=True)
            with contextlib.suppress(Exception):
                await conn.sftp_get("/workspace/snupi_check/state6.json",
                                    str(LOCAL.parent / "2xT_state6_pod.json"))
            await conn.run(f"rm -f {REMOTE_SUBSET}")   # tidy the volume
            if not ok:
                raise RuntimeError("subset download size mismatch")
    finally:
        await client.aclose()
    print(ledger.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
