import asyncio, sys
from pathlib import Path
sys.path.insert(0, "/home/jojo/Work/NADOC")
from backend.core.runpod_api import RunpodClient, ssh_endpoint
from backend.core.runpod_conn import RunpodConnection
POD = "ou1vxof3z0wwnm"; OUT = "/workspace/2xT_full.dcd"
LOCAL = Path("/media/jojo/Archive/nadoc_jobs/dab9e728433e/2xT_full.dcd")
async def go():
    c = RunpodClient(Path.home().joinpath(".runpod_key").read_text().strip())
    conn = None
    try:
        pod = {p.id: p for p in await c.list_pods()}.get(POD)
        if pod is None:
            print("pod gone"); return
        h, p = ssh_endpoint(pod)
        conn = RunpodConnection(host=h, port=p, pod_id=pod.id, client_keys=[str(Path.home()/".ssh/id_ed25519")])
        await conn.connect()
        rsize = int((await conn.run(f"stat -c %s {OUT}")).stdout.strip())
        print(f"fetching {rsize/1e9:.2f} GB ...", flush=True)
        await asyncio.wait_for(conn.sftp_get(OUT, str(LOCAL)), timeout=3600)
        ok = LOCAL.stat().st_size == rsize
        print(f"downloaded {LOCAL.stat().st_size/1e9:.2f} GB ({'OK' if ok else 'MISMATCH'})", flush=True)
    finally:
        if conn is not None:
            try: await conn.close()
            except Exception: pass
        try:
            await c.terminate_pod(POD)      # ALWAYS reap the fetch pod — no idle billing
            print(f"reaped {POD}", flush=True)
        except Exception as e:
            print(f"REAP FAILED for {POD}: {e} — reap by hand!", flush=True)
        await c.aclose()
asyncio.run(go())
