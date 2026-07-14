#!/usr/bin/env python3
"""Spawn the production child off the completed relaxation and run it on a fresh pod.

Production is a SEPARATE CHILD JOB seeded from the relaxation's final checkpoint — not
extra segments bolted onto the parent. It is sized to whatever the REMAINING budget buys,
read from the cumulative spend ledger (the in-code kill-switch is per-POD and would
happily hand this second pod the full $15 all over again).

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/launch_production.py [--ns N] [--dry-run]

Three things that were WRONG before this ran (all now fixed + pinned):
  * the child must inherit execution_target="runpod" — else it runs on the desktop GPU;
  * the child must inherit archive_path — else its trajectory lands on the 20 GB system
    disk (routes_md now inherits it from the parent);
  * seeding reads parent.job_dir(), which returns the ARCHIVE path once archived.
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
from backend.core.runpod_script import plan_execution  # noqa: E402
from backend.core.runpod_supervisor import min_name_for, n_atoms_for  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

WORKSPACE = ROOT / "workspace"
NETWORK_VOLUME = "77pnhye88p"
PARENT_ID = (Path(__file__).parent / "JOB_ID_3x6x400").read_text().strip()
CHILD_ID_FILE = Path(__file__).parent / "JOB_ID_3x6x400_production"

TIMESTEP_FS = 4.0

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prod")


def size_production_ns(remaining_usd: float, usd_per_hr: float, s_per_step: float) -> float:
    """How much production the money left actually buys.

    Deliberately derived from the MEASURED s/step of the relaxation, never the predicted
    one. Everything upstream of this was a 4090 extrapolation; the PRO 4500 Blackwell is
    a different card and the whole point of watching the first segment was to replace the
    guess with a number.
    """
    hours = remaining_usd / usd_per_hr
    steps = hours * 3600.0 / s_per_step
    return steps * TIMESTEP_FS * 1e-6      # fs -> ns


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ns", type=float, default=None,
                    help="production length; default = whatever the remaining budget buys")
    ap.add_argument("--s-per-step", type=float, required=True,
                    help="MEASURED seconds/step from the relaxation log")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    if not key and not args.dry_run:
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2

    parent = MdJob.load(PARENT_ID, WORKSPACE)
    if parent.status != MdStatus.completed:
        log.error("parent is %s, not completed — refusing to seed production from it",
                  parent.status)
        return 1

    ledger = SpendLedger(Path(parent.archive_path) / "spend.json")
    n_atoms = n_atoms_for(parent, WORKSPACE)
    plan = plan_execution(n_atoms)
    rate = plan["gpu"].usd_per_hour

    remaining = ledger.remaining()      # already nets off the $1.50 teardown reserve
    ns = args.ns if args.ns is not None else size_production_ns(remaining, rate, args.s_per_step)
    steps = int(ns * 1e6 / TIMESTEP_FS)
    hours = steps * args.s_per_step / 3600.0

    log.info("spent so far : $%.2f  (cap $15.00)", ledger.spent())
    log.info("remaining    : $%.2f  after the teardown reserve", remaining)
    log.info("measured     : %.1f ms/step  (%.1f ns/day at %g fs)",
             args.s_per_step * 1000, TIMESTEP_FS * 1e-6 / args.s_per_step * 86400, TIMESTEP_FS)
    log.info("production   : %.2f ns = %s steps ~ %.1f h ~ $%.2f",
             ns, f"{steps:,}", hours, hours * rate)

    if hours * rate > remaining:
        log.error("that does not fit the remaining budget — refusing")
        return 1
    if ns < 0.5:
        log.error("only %.2f ns affordable; that is not worth a pod. STOPPING.", ns)
        return 1
    if args.dry_run:
        log.info("dry run — no pod created")
        return 0

    # Spawn the child through the REAL route, so it gets the same target/archive/seed
    # inheritance the app would give it (and so any bug here is a bug users would hit).
    from backend.api import routes_md
    result = await routes_md.spawn_md_production(
        parent.job_id,
        routes_md.ProductionRunRequest(
            length_ns=ns, autostart=False, execution_target="runpod",
        ),
    )
    child = MdJob.load(result["job"]["job_id"], WORKSPACE)
    CHILD_ID_FILE.write_text(child.job_id + "\n")

    log.info("child        : %s  target=%s  archived=%s",
             child.job_id, child.execution_target, child.archived)
    log.info("child dir    : %s", child.job_dir(WORKSPACE))
    assert child.execution_target == "runpod", "child must NOT fall back to the local GPU"
    assert child.archived, "child must inherit the archive — else the trajectory hits /"

    client = RunpodClient(key)
    pod_seen: list[str] = []

    def _on_pod(pid: str) -> None:
        pod_seen.append(pid)
        log.info("POD %s IS NOW BILLING", pid)
        ledger.open_pod(pid, rate, note=f"production {ns:.2f} ns")

    try:
        status = await run_job_on_pod(
            child, WORKSPACE,
            client=client,
            network_volume_id=NETWORK_VOLUME,
            min_name=min_name_for(child, WORKSPACE),
            n_atoms=n_atoms,
            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")],
            poll_s=60.0,
            interruptible=False,
            on_pod=_on_pod,
            budget_usd=remaining,
        )
    finally:
        for pid in pod_seen:
            try:
                await client.terminate_pod(pid)
            except Exception as exc:  # noqa: BLE001
                log.error("could not confirm pod %s terminated: %s", pid, exc)
            ledger.close_pod(pid)
        live = [p for p in await client.list_pods() if not p.is_destroyed]
        log.info("live pods after teardown: %d %s", len(live),
                 "OK nothing billing" if not live else f"*** STILL BILLING {[p.id for p in live]}")
        await client.aclose()

    log.info("status: %s", status)
    log.info("\n%s", ledger.summary())
    return 0 if status == MdStatus.completed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
