#!/usr/bin/env python3
"""Resume an EXISTING, partially-run job on a fresh pod, then DESTROY the pod.

Unlike launch_production.py (which SPAWNS A NEW child from a relaxation parent), this runs
`run_job_on_pod` on a job that already exists and is partway through a segment. The chain
script is idempotent: a segment with no final `.coor` resumes from its own restart files
(via remote_resume_conf), so this finishes the remaining steps rather than restarting.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/resume_job.py <job_id> [--budget 5]

Use for: a production run whose pod died / hit budget at <100% (e.g. 3x6x400 at 90%).

⚠️ CREATES A REAL, BILLING POD. Teardown reaps ONLY the pods THIS process created
(pod_seen) — never a blanket sweep. supervise.py is the standby net; do NOT attach it to a
healthy launcher (it destroys the pod mid-stage — see LESSONS L10).
"""

from __future__ import annotations

import argparse
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
from backend.core.runpod_supervisor import min_name_for, n_atoms_for  # noqa: E402
from experiments.exp43_runpod_bench.balance import BalanceUnavailable, fetch_balance  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

WORKSPACE = ROOT / "workspace"
NETWORK_VOLUME = "77pnhye88p"   # EU-RO-1 (both 3x6x400 and 24hb live here)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("resume")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--budget", type=float, default=5.0, help="this pod's budget cap ($)")
    args = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2

    job = MdJob.load(args.job_id, WORKSPACE)
    assert job.archived and job.archive_path, "job must be archived"
    assert job.execution_target == "runpod"

    # THE MONEY GATE — fails loud, not safe.
    try:
        bal, rate = fetch_balance()
    except BalanceUnavailable as exc:
        log.error("cannot read balance: %s — REFUSING (LESSONS L1)", exc)
        return 2
    log.info("balance   : $%.2f  (billing $%.4f/hr elsewhere)", bal, rate)
    if bal < args.budget:
        log.error("REFUSING: balance $%.2f < pod budget $%.2f", bal, args.budget)
        return 2

    n_atoms = n_atoms_for(job, WORKSPACE)
    ledger = SpendLedger(Path(job.archive_path) / "spend.json")
    log.info("resuming  : %s  (%s atoms)  -> %s", job.job_id, f"{n_atoms:,}", job.archive_path)
    log.info("segments  : %s", ", ".join(f"{s.name}:{s.status}" for s in (job.segments or [])))

    client = RunpodClient(key)
    pod_seen: list[str] = []

    def _on_pod(pid: str) -> None:
        pod_seen.append(pid)
        log.info("POD %s IS NOW BILLING", pid)
        ledger.open_pod(pid, rate if rate > 0 else 0.74, note=f"resume {job.design_name}")

    try:
        status = await run_job_on_pod(
            job, WORKSPACE,
            client=client,
            network_volume_id=NETWORK_VOLUME,
            min_name=min_name_for(job, WORKSPACE),
            n_atoms=n_atoms,
            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")],
            poll_s=60.0,
            interruptible=False,          # ON-DEMAND: a reclaim restarts the segment top
            on_pod=_on_pod,
            budget_usd=args.budget,
        )
    finally:
        for pid in pod_seen:              # ONLY my pods — never a blanket sweep
            try:
                await client.terminate_pod(pid)
            except Exception as exc:  # noqa: BLE001
                log.error("could not confirm pod %s terminated: %s", pid, exc)
            ledger.close_pod(pid)
        mine = [p for p in await client.list_pods()
                if not p.is_destroyed and p.id in pod_seen]
        log.info("my pods after teardown: %d %s", len(mine),
                 "OK nothing of mine billing" if not mine else f"*** STILL BILLING {[p.id for p in mine]}")
        await client.aclose()

    log.info("status: %s", status)
    log.info("\n%s", ledger.summary())
    return 0 if status == MdStatus.completed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
