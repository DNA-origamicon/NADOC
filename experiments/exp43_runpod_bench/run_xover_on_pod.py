import asyncio, sys
from pathlib import Path
sys.path.insert(0, "/home/jojo/Work/NADOC")
from backend.core.runpod_api import RunpodClient, ssh_endpoint
from backend.core.runpod_conn import RunpodConnection
POD = "gcptdv331ilquk"
DCD = "/workspace/nadoc_jobs/dab9e728433e/output/24hb_2xT_01_production_30ns_k0.dcd"
WD = "/workspace/xover_work"
HERE = Path("/home/jojo/Work/NADOC/experiments/exp43_runpod_bench")
FILES = ["dcd_fast.py", "snupi_step_params.py", "kabsch_frame_test.py", "crossover_worker.py"]
RECIPE = "/tmp/claude-1000/-home-jojo-Work-NADOC/011c3b4d-993f-4381-80b1-96348254e906/scratchpad/xover_recipe.npz"
async def go():
    c = RunpodClient(Path.home().joinpath(".runpod_key").read_text().strip())
    try: pod = {p.id: p for p in await c.list_pods()}.get(POD)
    finally: await c.aclose()
    if pod is None: print("replica pod gone"); return
    h, p = ssh_endpoint(pod)
    conn = RunpodConnection(host=h, port=p, pod_id=pod.id, client_keys=[str(Path.home()/".ssh/id_ed25519")])
    await conn.connect()
    await conn.mkdir_p(WD)
    for f in FILES: await conn.sftp_put(str(HERE/f), f"{WD}/{f}")
    await conn.sftp_put(RECIPE, f"{WD}/xover_recipe.npz")
    chk = await conn.run("python3 -c 'import numpy' 2>&1 && echo OK || echo NO")
    if "OK" not in chk.stdout:
        print("installing numpy on pod ...", flush=True); await conn.run("pip install -q numpy", timeout=400)
    print("processing all post-eq frames on pod ...", flush=True)
    r = await conn.run(f"cd {WD} && nice -n 15 python3 crossover_worker.py {DCD} xover_recipe.npz 375", timeout=5400)
    print("RESULT:", (r.stdout or "").strip()[-2000:], flush=True)
    if r.rc: print("STDERR:", (r.stderr or "")[-600:], flush=True)
    await conn.close()
asyncio.run(go())
