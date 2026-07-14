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
import re
import sys
from pathlib import Path
from typing import Optional

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

# The card we are actually given, every time: the 4090 we ask for first is never free in
# EU-RO-1 and RunPod falls through to this one. Secure price, live-checked 2026-07-14.
PRO_4500_SECURE_USD_PER_HR = 0.74

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prod")


def measured_s_per_step(parent: MdJob, workspace: Path) -> Optional[float]:
    """Read the real 4 fs GPU-resident rate out of the relaxation's own NAMD logs.

    Production runs the SAME integrator as the relaxation's fast chunks (4 fs + HMR +
    GPUresident), so the parent's logs are a direct measurement — no extrapolation from a
    4090 and no separate benchmark pod.

    Deliberately ignores the 00_min (2 fs) and the SOFT first chunk (1 fs, offload, no
    GPUresident, flexible H bonds): those run a different integrator entirely, and the
    soft chunk measured 43-51 ms/step against the fast path's ~21. Sizing production off
    the wrong one would halve or double the run.
    """
    pkg = parent.package_dir(workspace)
    rates: list[float] = []
    for log_path in sorted(pkg.glob("*.log")) + sorted(pkg.parent.glob("*.log")):
        name = log_path.stem
        if "_00_min" in name or name.endswith("_01_300K_NPT_ENM_k0p5_p10"):
            continue                      # 2 fs minimisation / 1 fs soft chunk
        found = re.findall(r"Benchmark time:.*?([\d.]+)\s+s/step", log_path.read_text(errors="ignore"))
        rates += [float(x) for x in found]
    if not rates:
        return None
    # The last few benchmark lines are the settled ones; NAMD's first is warm-up.
    return sum(rates[-3:]) / len(rates[-3:])


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
    ap.add_argument("--s-per-step", type=float, default=None,
                    help="MEASURED s/step. Default: read it from the relaxation's own logs.")
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

    # Plan against the rate we will ACTUALLY be charged, not the cheapest card we ask
    # for. gpuTypeIds is a fallback list: we ask for a $0.69 4090 and RunPod has given us
    # a $0.74 PRO 4500 on every single pod tonight, because the 4090 is never free in
    # EU-RO-1. Sizing off $0.69 would quietly under-budget by 7% — in the unsafe
    # direction. Guess HIGH; the ledger books the pod's real rate afterwards anyway.
    rate = max(float(plan["gpu"].usd_per_hour), PRO_4500_SECURE_USD_PER_HR)

    s_per_step = args.s_per_step or measured_s_per_step(parent, WORKSPACE)
    if not s_per_step:
        log.error("no 4 fs GPU-resident benchmark line in the relaxation logs — pass "
                  "--s-per-step explicitly rather than let me guess")
        return 1

    remaining = ledger.remaining()      # already nets off the $1.50 teardown reserve
    ns = args.ns if args.ns is not None else size_production_ns(remaining, rate, s_per_step)
    steps = int(ns * 1e6 / TIMESTEP_FS)
    hours = steps * s_per_step / 3600.0

    log.info("spent so far : $%.2f  (cap $15.00)", ledger.spent())
    log.info("remaining    : $%.2f  after the teardown reserve", remaining)
    log.info("measured     : %.1f ms/step  (%.1f ns/day at %g fs)%s",
             s_per_step * 1000, TIMESTEP_FS * 1e-6 / s_per_step * 86400, TIMESTEP_FS,
             "" if args.s_per_step else "   [read from the relaxation's own logs]")
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
