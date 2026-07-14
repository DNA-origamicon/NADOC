#!/usr/bin/env python3
"""RE-ATTACH to a pod whose launcher died, and see it through: poll → fetch → DESTROY.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/supervise.py <job_id>

Why this exists: the launcher owns the ``finally`` that destroys the pod. It died on a
transient DNS failure mid-poll (now retried in ``runpod_api._request``, but the pod it
abandoned is still out there). NAMD is DETACHED — ``setsid``, output on the network volume
— so the science keeps running perfectly well without a supervisor. What does NOT keep
running is anything that will ever turn the meter off.

So: adopt the pod. Same poll → fetch → destroy as ``run_job_on_pod``, minus the
provisioning, and hardened so no single network error can orphan it a second time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob, MdStatus  # noqa: E402
from backend.core.runpod_api import RunpodClient, ssh_endpoint  # noqa: E402
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from backend.core.runpod_executor import fetch_results, poll_job  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import (  # noqa: E402
    HARD_CAP_USD,
    SpendLedger,
)

WORKSPACE = ROOT / "workspace"
POLL_S = 60.0
KEY = Path.home() / ".ssh" / "id_ed25519"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("supervise")
logging.getLogger("asyncssh").setLevel(logging.WARNING)


async def main() -> int:
    job_id = sys.argv[1] if len(sys.argv) > 1 else None
    if not job_id:
        print("usage: supervise.py <job_id>", file=sys.stderr)
        return 2
    api_key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()

    job = MdJob.load(job_id, WORKSPACE)
    ledger = SpendLedger(Path(job.archive_path) / "spend.json")
    client = RunpodClient(api_key)

    pod_id = job.runpod_pod_id
    try:
        pods = [p for p in await client.list_pods() if not p.is_destroyed]
        if not pods:
            log.info("no pod on the account — nothing to supervise. Nothing is billing.")
            return 0
        pod = next((p for p in pods if p.id == pod_id), pods[0])
        log.info("adopting pod %s ($%s/hr), job %s", pod.id, pod.cost_per_hr, job.job_id)
        if pod.id not in ledger.live_pods():
            ledger.open_pod(pod.id, float(pod.cost_per_hr or 0.74), note="relax (adopted)")

        endpoint = ssh_endpoint(pod)
        if endpoint is None:
            log.error("pod %s has no SSH endpoint — destroying it, it can do nothing", pod.id)
            await client.terminate_pod(pod.id)
            return 1
        host, port = endpoint
        conn = RunpodConnection(host=host, port=port, pod_id=pod.id, client_keys=[str(KEY)])
        await conn.connect()

        while True:
            try:
                state = await poll_job(job, conn=conn)
            except Exception as exc:  # noqa: BLE001
                # A poll failure is NOT a reason to abandon a pod — abandoning it is how
                # we got here. Log, sleep, try again; the SSH layer reconnects.
                log.warning("poll failed (%s) — retrying", exc)
                await asyncio.sleep(POLL_S)
                continue

            job.save(WORKSPACE)
            spent = ledger.spent()
            log.info("state=%s segment=%s alive=%s stale=%s  spent=$%.2f / $%.2f",
                     state.get("state"), state.get("segment"), state.get("alive"),
                     state.get("stale"), spent, HARD_CAP_USD)

            # poll_job REPORTS; the caller decides. Same interpretation as
            # run_job_on_pod's loop — a supervisor that got this wrong would poll a
            # finished ladder forever and bill for an idle GPU until the budget backstop.
            st = state.get("state")
            if st == "completed":
                job.status = MdStatus.completed
                break
            if st == "failed":
                job.status = MdStatus.failed
                job.error = f"NAMD failed at segment {state.get('segment')}"
                break
            if st == "lifetime":
                job.status = MdStatus.paused
                job.resumable = True
                job.error = "Pod hit its maximum lifetime; resume to continue."
                break
            if not state.get("alive") and state.get("stale"):
                job.status = MdStatus.paused
                job.resumable = True
                job.error = "Pod stopped mid-run; resume from the checkpoint."
                break
            if spent > HARD_CAP_USD:
                log.error("BUDGET EXCEEDED ($%.2f) — killing the pod NOW", spent)
                break
            await asyncio.sleep(POLL_S)

        log.info("ladder finished: %s — fetching results", job.status)
        try:
            await fetch_results(job, WORKSPACE, conn=conn)
        except Exception as exc:  # noqa: BLE001
            log.error("fetch FAILED (%s) — the outputs are still on the network volume "
                      "under /workspace/nadoc_jobs/%s and survive the pod", exc, job.job_id)
        await conn.close()

    finally:
        # The whole point of this script.
        for p in [p for p in await client.list_pods() if not p.is_destroyed]:
            log.info("destroying pod %s", p.id)
            try:
                await client.terminate_pod(p.id)
            except Exception as exc:  # noqa: BLE001
                log.error("could not destroy %s: %s — DO IT BY HAND", p.id, exc)
            ledger.close_pod(p.id)
        left = [p for p in await client.list_pods() if not p.is_destroyed]
        log.info("live pods: %d %s", len(left),
                 "— nothing billing" if not left else f"*** STILL BILLING {[p.id for p in left]}")
        log.info("\n%s", ledger.summary())
        await client.aclose()

    job.save(WORKSPACE)
    return 0 if job.status == MdStatus.completed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
