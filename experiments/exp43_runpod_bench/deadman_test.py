"""Live test of the pod-side deadman's switch WITHOUT injecting any secret — proves
whether a pod can self-terminate using only its auto-injected pod-scoped credentials
(runpodctl / RUNPOD_API_KEY). If it can, the production deadman needs no key to ever
leave this machine.

Flow: rent cheap pod -> launch deadman.py (TOL=60s) -> keep heartbeat FRESH ~40s
(must stay alive) -> STOP heartbeat -> watch for self-termination (~60-100s later).
finally: if the pod is still alive, reap it (so a deadman failure can't leak billing).

  RUNPOD_API_KEY=$(cat ~/.runpod_key) python deadman_test.py
"""
import asyncio
import sys
import time
from pathlib import Path

REPO = Path("/home/jojo/Work/NADOC")
EXP43 = REPO / "experiments/exp43_runpod_bench"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(EXP43))
from backend.core.runpod_api import RunpodClient, build_create_payload, ssh_endpoint  # noqa: E402
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from backend.core.runpod_script import recommend_gpus  # noqa: E402

SSH_KEY = str(Path.home() / ".ssh/id_ed25519")
VOLUME_ID = "77pnhye88p"
WD = "/workspace/blade_capture"
HB = "/workspace/controller_heartbeat"


async def pod_alive(client, pid):
    try:
        p = await client.get_pod(pid)
        return p is not None and not p.is_terminated and not p.is_destroyed
    except Exception:
        # get_pod 404 after termination -> treat as gone
        try:
            return pid in {p.id for p in await client.list_pods() if not p.is_destroyed}
        except Exception:
            return None


async def main():
    key = (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    gpus = recommend_gpus(770219, gpu_resident=False, max_usd_per_hour=0.80)
    gpu_ids = [g.key for g in gpus]
    kill_key_file = Path.home() / ".runpod_key_kill"
    env = {}
    if kill_key_file.exists():
        env["RUNPOD_KILL_KEY"] = kill_key_file.read_text().strip()
    print(f"kill-key injected via payload env: {bool(env)}", flush=True)
    payload = build_create_payload(name="nadoc-bench-blade-deadmantest", gpu_type_ids=gpu_ids,
                                   network_volume_id=VOLUME_ID, interruptible=False,
                                   cloud_type="SECURE", container_disk_gb=20, env=env or None)
    booked = {"id": None}
    def on_created(info):
        booked["id"] = info.id
        print(f"POD CREATED {info.id} (billing on)", flush=True)

    result = "UNKNOWN"
    try:
        async with client.pod(payload, fallbacks=[], on_created=on_created) as pod:
            host, port = ssh_endpoint(pod)
            print(f"POD UP {pod.id} {host}:{port} ${pod.cost_per_hr}/hr", flush=True)
            conn = RunpodConnection(host=host, port=port, pod_id=pod.id, client_keys=[SSH_KEY])
            await conn.connect()

            # what credentials does the pod actually have? (SSH env vs PID-1 env vs runpodctl)
            env = await conn.run(
                "echo SSH_POD_ID=$RUNPOD_POD_ID; echo SSH_HAS_KEY=${RUNPOD_API_KEY:+yes}; "
                "echo PID1_POD_ID=$(tr '\\0' '\\n' < /proc/1/environ | sed -n 's/^RUNPOD_POD_ID=//p'); "
                "echo PID1_HAS_KEY=$(tr '\\0' '\\n' < /proc/1/environ | grep -c '^RUNPOD_API_KEY='); "
                "echo PID1_HAS_KILLKEY=$(tr '\\0' '\\n' < /proc/1/environ | grep -c '^RUNPOD_KILL_KEY='); "
                "which runpodctl >/dev/null && echo RUNPODCTL=yes || echo RUNPODCTL=no", timeout=30)
            print(f"--- pod creds ---\n{(env.stdout or '').strip()}", flush=True)

            await conn.mkdir_p(WD)
            await conn.run(f"date +%s > {HB}", timeout=20)
            await conn.sftp_put(str(EXP43 / "deadman.py"), f"{WD}/deadman.py")
            # Pass POD_ID EXPLICITLY (SSH env lacks it); NO key injected -> deadman falls back
            # to the pod-scoped RUNPOD_API_KEY from /proc/1/environ + runpodctl == the zero-secret path.
            launch = (f"cd {WD}; RUNPOD_POD_ID={pod.id} DEADMAN_TOL_S=60 DEADMAN_POLL_S=10 "
                      f"CTRL_HEARTBEAT={HB} "
                      f"setsid nohup python3 deadman.py > deadman.stdout 2>&1 < /dev/null & echo $!")
            r = await conn.run(launch, timeout=30)
            print(f"deadman launched pid={(r.stdout or '').strip()}", flush=True)

            # keep heartbeat FRESH ~40s: pod MUST stay alive
            for _ in range(4):
                await asyncio.sleep(10)
                await conn.run(f"date +%s > {HB}", timeout=20)
            alive = await pod_alive(client, pod.id)
            print(f"[fresh-phase] pod alive with fresh heartbeat: {alive} (expect True)", flush=True)
            dm = await conn.run(f"cat {WD}/deadman.log 2>/dev/null", timeout=20)
            print(f"--- deadman.log (fresh) ---\n{(dm.stdout or '').strip()}", flush=True)

            # STOP refreshing -> deadman should fire ~TOL+POLL later
            print("[stopping heartbeat] watching for SELF-TERMINATION ...", flush=True)
            t_stop = time.time()
            terminated = False
            for _ in range(16):  # up to ~4 min
                await asyncio.sleep(15)
                alive = await pod_alive(client, pod.id)
                dt = int(time.time() - t_stop)
                print(f"  [+{dt}s] pod alive={alive}", flush=True)
                if alive is False:
                    print(f"SELF-TERMINATED after {dt}s of silence -> zero-secret deadman WORKS", flush=True)
                    result = "SELF_TERMINATED"; terminated = True; booked["id"] = None; break
            if not terminated:
                print("NO self-termination in window -> pod-scoped creds CANNOT self-terminate", flush=True)
                result = "NO_SELF_TERMINATE"
    finally:
        try:
            if booked["id"]:
                print(f"reaping test pod {booked['id']} (deadman did not fire)", flush=True)
                await client.terminate_pod(booked["id"])
            left = [p.id for p in await client.list_pods() if not p.is_destroyed]
            print(f"LIVE PODS AFTER: {left}", flush=True)
        except Exception as e:
            print(f"reap-verify warn: {e}", flush=True)
        await client.aclose()
    print(f"DEADMAN_TEST_RESULT={result}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
