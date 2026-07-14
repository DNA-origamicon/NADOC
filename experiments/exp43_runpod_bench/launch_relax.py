#!/usr/bin/env python3
"""Rent a GPU, run the 3x6x400 relaxation ladder on it, fetch it back, DESTROY the pod.

Runs unattended. `run_job_on_pod` terminates the pod in a `finally`, and the chain script
carries an independent on-pod kill-switch, so the pod cannot outlive its budget even if
this process dies.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/launch_relax.py

⚠️ CREATES A REAL, BILLING POD. If this process is SIGKILLed mid-run, the pod survives:
check `python experiments/exp43_runpod_bench/watch.py` (or the RunPod console) and
terminate it. The API key lives only in memory here, so nothing else can reap it.
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
from backend.core.runpod_api import RunpodClient  # noqa: E402
from backend.core.runpod_executor import run_job_on_pod  # noqa: E402
from backend.core.runpod_script import plan_execution  # noqa: E402
from backend.core.runpod_supervisor import min_name_for, n_atoms_for  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

WORKSPACE = ROOT / "workspace"
NETWORK_VOLUME = "77pnhye88p"
JOB_ID = (Path(__file__).parent / "JOB_ID_3x6x400").read_text().strip()

# The relaxation's SHARE of the $15, not the whole thing — production is a second pod and
# the cap is cumulative across both. The on-pod kill-switch is derived from this and the
# LIVE rate of the card we actually get, so it is a real wall-clock bound, not a hope.
RELAX_BUDGET_USD = 8.00

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("relax")


async def main() -> int:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2

    job = MdJob.load(JOB_ID, WORKSPACE)
    assert job.archived and job.archive_path, "job must be archived — see prep script"
    assert job.execution_target == "runpod"
    assert job.early_stop_relax and job.early_stop_tier == "A", (
        "Tier-A early-stop is MANDATORY: without it this ladder is ~28 h / ~$21"
    )

    n_atoms = n_atoms_for(job, WORKSPACE)
    min_name = min_name_for(job, WORKSPACE)
    plan = plan_execution(n_atoms)
    ledger = SpendLedger(Path(job.archive_path) / "spend.json")

    total_steps = sum(s.steps for s in job.segments)
    log.info("design    : %s  (%s atoms)", job.design_name, f"{n_atoms:,}")
    log.info("job       : %s -> %s", job.job_id, job.archive_path)
    log.info("ladder    : %d segments, %s steps (4 fs, Tier-A early-stop)",
             len(job.segments), f"{total_steps:,}")
    log.info("sizing    : %s  $%s/hr (secure)  resident=%s",
             plan["gpu"].label, plan["gpu"].usd_per_hour, plan["gpu_resident"])
    log.info("budget    : $%.2f for THIS pod (cap $15 across all pods; spent so far $%.2f)",
             RELAX_BUDGET_USD, ledger.spent())

    client = RunpodClient(key)
    pod_seen: list[str] = []

    def _on_pod(pid: str) -> None:
        pod_seen.append(pid)
        log.info("POD %s IS NOW BILLING", pid)
        ledger.open_pod(pid, plan["gpu"].usd_per_hour, note="relax 3x6x400")

    try:
        status = await run_job_on_pod(
            job, WORKSPACE,
            client=client,
            network_volume_id=NETWORK_VOLUME,
            min_name=min_name,
            n_atoms=n_atoms,
            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")],
            poll_s=60.0,
            # ON-DEMAND, not spot. A reclaim restarts the interrupted SEGMENT from its
            # top (no .coor until it completes) and these segments are hundreds of
            # thousands of steps — one reclaim could cost more hours than spot saves
            # dollars. On-demand removes the reclaim risk entirely.
            interruptible=False,
            on_pod=_on_pod,
            budget_usd=RELAX_BUDGET_USD,
        )
    finally:
        # run_job_on_pod terminates in its own finally; this is the belt-and-braces pass.
        # A survivor bills until a human notices, and only THIS process holds the key.
        for pid in pod_seen:
            try:
                await client.terminate_pod(pid)
            except Exception as exc:  # noqa: BLE001
                log.error("could not confirm pod %s terminated: %s", pid, exc)
            ledger.close_pod(pid)
        live = [p for p in await client.list_pods() if not p.is_destroyed]
        log.info("live pods after teardown: %d %s", len(live),
                 "OK nothing billing" if not live else f"*** STILL BILLING: {[p.id for p in live]}")
        await client.aclose()

    log.info("status    : %s", status)
    if job.error:
        log.error("error     : %s", job.error)
    log.info("\n%s", ledger.summary())

    out = job.package_dir(WORKSPACE) / "output"
    coors = sorted(p.name for p in out.glob("*.coor")) if out.exists() else []
    log.info("fetched   : %d .coor files -> %s", len(coors), out)
    return 0 if status == MdStatus.completed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
