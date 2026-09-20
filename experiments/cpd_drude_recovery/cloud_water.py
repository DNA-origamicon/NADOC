"""Run a prepared water-QM batch with cumulative cost and independent teardown."""

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.core.runpod_api import (
    RunpodClient,
    build_create_payload,
    resolve_api_key,
    ssh_endpoint,
    termination_deadline,
)
from backend.core.runpod_conn import RunpodConnection
from backend.core.runpod_oxdna import CampaignLedger
import httpx
from backend.core.runpod_watchdog import start_watchdog_service
from scripts.runpod_photoproduct_hessian import (
    _cgroup_probe_command,
    _parse_cgroup_limits,
)
from experiments.cpd_drude_recovery.campaign import source, write


async def run(root):
    root = root.resolve()
    plan = json.loads((root / "batch.json").read_text())
    if (root / "launch.json").exists():
        raise FileExistsError("Existing launch must be reconciled before any retry")
    key = resolve_api_key().value
    if not key:
        raise ValueError("No RunPod credential")
    sshkey = Path.home() / ".ssh/id_ed25519"
    if not sshkey.is_file():
        raise ValueError("No registered SSH key file")
    ledger = CampaignLedger(root / "spend_ledger.json", cap_usd=4.0)
    if ledger.open_pod_ids():
        raise ValueError("An existing campaign pod is still open")
    query = '{ cpuFlavors { id ramMultiplier specifics(input:{instanceId:"cpu3m-8-64"}) { stockStatus securePrice } } }'
    async with httpx.AsyncClient(timeout=20) as session:
        response = await session.post(
            "https://api.runpod.io/graphql",
            params={"api_key": key},
            json={"query": query},
            headers={"User-Agent": "Mozilla/5.0 NADOC/1.0"},
        )
        response.raise_for_status()
        body = response.json()
    if body.get("errors"):
        raise ValueError("Resource-specific CPU quote query failed")
    write(root / f"quote_{time.time_ns()}.json", body)
    flavor = next(r for r in body["data"]["cpuFlavors"] if r["id"] == "cpu3m")
    quote = flavor["specifics"]
    rate = quote["securePrice"]
    if (
        flavor["ramMultiplier"] != 8
        or quote["stockStatus"] not in {"Low", "Medium", "High"}
        or not 0 < rate <= 0.9
    ):
        raise ValueError("No bounded live CPU quote")
    # $4 working cap includes a conservative disk charge; $1 remains unspent
    # for billing granularity, teardown latency and any applicable surcharges.
    lifetime = min(6 * 3600, int(ledger.remaining_usd() / (rate + 0.03) * 3600) - 600)
    ledger.authorize(rate + 0.03, lifetime)
    payload = build_create_payload(
        name="nadoc-cpd-water-budget5",
        gpu_type_ids=[],
        network_volume_id=None,
        cloud_type="SECURE",
        container_disk_gb=80,
    )
    for field in (
        "gpuTypeIds",
        "gpuCount",
        "gpuTypePriority",
        "minRAMPerGPU",
        "minVCPUPerGPU",
        "allowedCudaVersions",
    ):
        payload.pop(field, None)
    payload.update(
        computeType="CPU", cpuFlavorIds=["cpu3m"], vcpuCount=8, supportPublicIp=True
    )
    deadline = termination_deadline(lifetime)
    snapshot = root / f"controller_{time.time_ns()}.py"
    snapshot.write_text(Path(__file__).read_text())
    write(
        root / "launch.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "quote": quote,
            "payload": payload,
            "hard_total_budget_usd": 5,
            "working_ledger_cap_usd": 4,
            "storage_rate_reserve_per_hour": 0.03,
            "deadline": deadline,
            "lifetime_seconds": lifetime,
            "batch": source(root / "batch.json"),
            "controller": source(snapshot),
        },
    )
    client = RunpodClient(key, audit_dir=root)

    async def record_failed_http(response):
        if response.status_code >= 400:
            await response.aread()
            (root / f"http_error_{time.time_ns()}.txt").write_text(response.text)

    client._client.event_hooks.setdefault("response", []).append(record_failed_http)
    pod_id = None

    def created(info):
        nonlocal pod_id
        pod_id = info.id
        actual = info.cost_per_hr
        # Start the independent kill authority immediately at creation.
        unit = start_watchdog_service(
            pod_id=info.id,
            owner_pid=os.getpid(),
            deadline=deadline,
            audit_dir=root,
            campaign_ledger=root / "spend_ledger.json",
            campaign_cap_usd=4,
            poll_seconds=10,
        )
        write(
            root / "pod.json",
            {"id": info.id, "actual_compute_rate": actual, "watchdog_unit": unit},
        )
        ledger.open_pod(
            info.id,
            (actual if actual else 10) + 0.03,
            note="CPD budget $5; rate includes disk reserve",
        )
        if not actual or actual > 0.9:
            raise ValueError("Actual rate is missing or exceeds authorized quote range")
        ledger.authorize(actual + 0.03, lifetime)

    try:
        async with client.pod(
            payload, on_created=created, wait_timeout_s=420, terminate_on_exit=True
        ) as pod:
            endpoint = ssh_endpoint(pod)
            conn = RunpodConnection(
                host=endpoint[0],
                port=endpoint[1],
                pod_id=pod.id,
                client_keys=[str(sshkey)],
            )
            await conn.connect()
            try:
                probe = await conn.run(_cgroup_probe_command(), timeout=30)
                (root / "resource_probe.txt").write_text(probe.stdout)
                rows = probe.stdout.splitlines()
                if len(rows) == 3 and rows[1].split()[0] == "max":
                    rows[1] = "max"
                limits = _parse_cgroup_limits("\n".join(rows))
                # CPU Pods are VMs: their physical guest RAM can be the bound
                # even when no narrower container memory cgroup is configured.
                guest = await conn.run(
                    "awk '/^MemTotal:/ {print $2 * 1024}' /proc/meminfo", timeout=20
                )
                guest_bytes = int(float(guest.stdout.strip()))
                limits["guest_physical_memory_bytes"] = guest_bytes
                cgroup_memory = limits["cgroup_memory_limit_bytes"]
                limits["effective_memory_bytes"] = (
                    min(guest_bytes, cgroup_memory) if cgroup_memory else guest_bytes
                )
                write(root / "remote_limits.json", limits)
                memory = limits["effective_memory_bytes"]
                if (
                    limits["cgroup_cpu_limit"] < 8
                    or memory is None
                    or memory < 56 * 1024**3
                ):
                    raise ValueError(
                        "Pod does not provide eight CPUs and at least 56 GiB enforceable RAM"
                    )
                remote = "/workspace/cpd_budget5"
                await conn.mkdir_p(remote)
                # Pod-side independent deadline survives loss of the workstation.
                guard = root / "remote_guard.py"
                guard.write_text(
                    "import pathlib,time,urllib.request,urllib.error\n"
                    + "key=pathlib.Path('/root/cpd-kill-key').read_text().strip()\n"
                    + f"deadline={datetime.fromisoformat(deadline.replace('Z', '+00:00')).timestamp()!r}\n"
                    + f"url='https://rest.runpod.io/v1/pods/{pod.id}'\n"
                    + "pathlib.Path('/workspace/cpd_budget5/guard_armed').write_text('armed')\n"
                    + "terminal=None\n"
                    + "while True:\n"
                    + " if pathlib.Path('/workspace/cpd_budget5/exit_code').exists() and terminal is None: terminal=time.time()+120\n"
                    + " if time.time()>=deadline or (terminal is not None and time.time()>=terminal):\n"
                    + "  try:\n"
                    + "   request=urllib.request.Request(url,method='DELETE',headers={'Authorization':'Bearer '+key,'User-Agent':'curl/8.5.0'})\n"
                    + "   urllib.request.urlopen(request,timeout=20).close()\n"
                    + "   break\n"
                    + "  except urllib.error.HTTPError as error:\n"
                    + "   if error.code==404: break\n"
                    + "  except Exception: pass\n"
                    + " time.sleep(10)\n"
                )
                await conn.sftp_put(
                    str(Path.home() / ".runpod_key_kill"), "/root/cpd-kill-key"
                )
                await conn.run("chmod 600 /root/cpd-kill-key", timeout=20)
                await conn.sftp_put(str(guard), remote + "/remote_guard.py")
                await conn.run(
                    f"cd {remote}; nohup python3 remote_guard.py > guard.log 2>&1 < /dev/null &",
                    timeout=20,
                )
                await asyncio.sleep(2)
                check = await conn.run(f"test -f {remote}/guard_armed", timeout=20)
                if check.rc:
                    raise ValueError("Pod-side independent cost deadline did not arm")
                for filename in ("worker.py", "batch.json"):
                    await asyncio.wait_for(
                        conn.sftp_put(str(root / filename), remote + "/" + filename),
                        timeout=60,
                    )
                setup = """set -euo pipefail
mkdir -p /workspace/cpd_budget5/tools
cd /workspace/cpd_budget5/tools
curl -LsSf https://micro.mamba.pm/api/micromamba/linux-64/2.3.3 | tar -xj bin/micromamba
MAMBA_ROOT_PREFIX=/workspace/cpd_budget5/tools/mamba-root bin/micromamba create -y -p /workspace/cpd_budget5/tools/qm -c conda-forge python=3.12 psi4=1.11
/workspace/cpd_budget5/tools/qm/bin/python -c 'import psi4; assert psi4.__version__ == "1.11"'
"""
                response = await conn.run(setup, timeout=900)
                (root / "setup.log").write_text(
                    response.stdout + "\n" + response.stderr
                )
                if response.rc:
                    raise ValueError("QM environment setup failed")
                script = root / "remote.sh"
                script.write_text(
                    "#!/bin/bash\ncd /workspace/cpd_budget5\nexport OPENBLAS_NUM_THREADS=8 OMP_NUM_THREADS=8 MKL_NUM_THREADS=8\n/workspace/cpd_budget5/tools/qm/bin/python worker.py > worker.log 2>&1\necho $? > exit_code\n"
                )
                await conn.sftp_put(str(script), remote + "/run.sh")
                pid = await conn.launch_detached(remote + "/run.sh", remote)
                write(
                    root / "running.json",
                    {
                        "pid": pid,
                        "pod": pod.id,
                        "remote": remote,
                        "started_epoch": time.time(),
                    },
                )
                completed = set()
                while True:
                    state = await conn.run(
                        f"cd {remote}; test ! -f exit_code || cat exit_code; find results -name result.json 2>/dev/null || true",
                        timeout=30,
                    )
                    lines = state.stdout.splitlines()
                    for line in lines:
                        if (
                            line.startswith("results/")
                            and line.endswith("/result.json")
                            and line not in completed
                        ):
                            case = line.split("/")[1]
                            if case not in {r["id"] for r in plan["cases"]}:
                                raise ValueError("Unexpected remote result")
                            dest = root / "results" / case
                            dest.mkdir(parents=True, exist_ok=True)
                            for filename in ("result.json", "output.dat"):
                                await asyncio.wait_for(
                                    conn.sftp_get(
                                        remote + "/results/" + case + "/" + filename,
                                        str(dest / filename),
                                    ),
                                    timeout=60,
                                )
                            completed.add(line)
                            print("Fetched", case, flush=True)
                    if lines and lines[0].isdigit():
                        await asyncio.wait_for(
                            conn.sftp_get(
                                remote + "/worker.log", str(root / "worker.log")
                            ),
                            timeout=30,
                        )
                        write(
                            root / "batch_exit.json",
                            {
                                "exit_code": int(lines[0]),
                                "completed_cases": len(completed),
                                "simulation_ready": False,
                                "gate_effect": "none",
                            },
                        )
                        break
                    if not await conn.pid_alive(pid):
                        raise ValueError(
                            "Remote worker vanished without completion marker"
                        )
                    if ledger.remaining_usd() < 0.25:
                        raise ValueError("Reached reserved teardown budget")
                    await asyncio.sleep(15)
            finally:
                await conn.close()
    except Exception as error:
        write(
            root / "failure.json",
            {
                "type": type(error).__name__,
                "reason": str(error)[:500],
                "simulation_ready": False,
                "gate_effect": "none",
            },
        )
        raise
    finally:
        try:
            if pod_id:
                await client.terminate_pod(
                    pod_id, reason="cpd_budget5_controller_finally"
                )
                pods = await client.list_pods()
                absent = all(p.id != pod_id for p in pods)
                if absent:
                    ledger.close_pod(pod_id)
                write(
                    root / "teardown.json",
                    {
                        "pod_id": pod_id,
                        "provider_absent": absent,
                        "ledger_estimated_cost_usd_including_disk_reserve": ledger.spent_usd(),
                        "remaining_campaign_usd": ledger.remaining_usd(),
                        "other_pod_count": len(pods),
                    },
                )
        finally:
            await client.aclose()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    asyncio.run(run(p.parse_args().root))
