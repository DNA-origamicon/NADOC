import asyncio, sys, glob
from pathlib import Path
sys.path.insert(0, "/home/jojo/Work/NADOC")
from backend.core.runpod_api import RunpodClient, ssh_endpoint
from backend.core.runpod_conn import RunpodConnection
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger
POD = "gcptdv331ilquk"; WD = "/workspace/xover_work"
async def go():
    c = RunpodClient(Path.home().joinpath(".runpod_key").read_text().strip())
    conn = None
    try:
        pod = {p.id: p for p in await c.list_pods()}.get(POD)
        if pod is None: print("pod gone"); return
        h, p = ssh_endpoint(pod)
        conn = RunpodConnection(host=h, port=p, pod_id=pod.id, client_keys=[str(Path.home()/".ssh/id_ed25519")])
        await conn.connect()
        dcd = (await conn.run("ls -1 /workspace/nadoc_jobs/71043149ebab/output/*production*.dcd 2>/dev/null | head -1")).stdout.strip()
        print("replica DCD:", dcd, flush=True)
        # recipe + deps already staged in WD from the prior run; start=175 (post-eq at dcdfreq 2500 = 1.75 ns)
        r = await conn.run(f"cd {WD} && nice -n 15 python3 crossover_worker.py {dcd} xover_recipe.npz 175", timeout=3600)
        print("REPLICA RESULT:", (r.stdout or "").strip()[-1600:], flush=True)
        if r.rc: print("STDERR:", (r.stderr or "")[-500:], flush=True)
    finally:
        if conn is not None:
            try: await conn.close()
            except Exception: pass
        try:
            await c.terminate_pod(POD)
            for f in sorted(glob.glob("/media/jojo/Archive/nadoc_jobs/*/spend.json")):
                try: SpendLedger(Path(f)).close_pod(POD)
                except Exception: pass
            left = [x.id for x in await c.list_pods() if not x.is_destroyed]
            print(f"reaped {POD}; still on account: {left or 'none'}", flush=True)
        except Exception as e:
            print(f"REAP FAILED for {POD}: {e} — reap by hand (reap.py --kill)!", flush=True)
        await c.aclose()
asyncio.run(go())
