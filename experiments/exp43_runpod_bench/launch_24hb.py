#!/usr/bin/env python3
"""Rent a GPU, run a 24hb variant's relaxation ladder on it, fetch it, DESTROY the pod.

Same protocol as launch_relax.py, parameterised by variant, plus two changes:

1. **Prefers the RTX PRO 6000.** The stock GPU_TYPES order is price-ascending, so
   plan_execution() would hand RunPod a 4090-first priority list. Compute does NOT scale
   with cost here (2.7x price -> 2.0x speed), so the PRO 6000 is ~34% worse per ns but
   HALF the wall-clock, and wall-clock is the binding constraint. The user approved it.
   The cheaper cards stay in the list as fallbacks: EU-RO-1 stock churns by the minute.
   We reorder a LOCAL COPY of the priority list — the shared GPU_TYPES table is untouched.

2. **Refuses to launch if the balance cannot cover the run.** RunPod destroys every pod at
   zero balance; a multi-day run that dies at 80% wastes everything spent to that point.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/launch_24hb.py 24hb_0xT

⚠️ CREATES A REAL, BILLING POD. If this process is SIGKILLed mid-run the pod SURVIVES —
`supervise.py` is the safety net; always attach it. The teardown below reaps ONLY the pods
THIS launcher created (`pod_seen`): a cleanup routine must never have a blast radius larger
than what it owns. `reap.py --kill` is the all-pods panic button and is opt-in on purpose.
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

from backend.core import runpod_script  # noqa: E402
from backend.core.md_job import MdJob, MdStatus  # noqa: E402
from backend.core.runpod_api import RunpodClient  # noqa: E402
from backend.core.runpod_executor import run_job_on_pod  # noqa: E402
from backend.core.runpod_supervisor import min_name_for, n_atoms_for  # noqa: E402
from experiments.exp43_runpod_bench.balance import BalanceUnavailable, fetch_balance  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

WORKSPACE = ROOT / "workspace"
NETWORK_VOLUME = "77pnhye88p"   # PINS the datacenter to EU-RO-1

# Wall-clock-first priority. Every one of these is an arch the multi-arch NAMD build
# covers (sm_80/89/90/120) and holds 1.32M atoms GPU-resident.
PREFERRED_ORDER = (
    "NVIDIA RTX PRO 6000 Blackwell Server Edition",  # $1.99  12.6 ms/step  <- want this
    "NVIDIA A100 80GB PCIe",                         # $1.39
    "NVIDIA RTX PRO 5000 Blackwell",                 # $0.96
    "NVIDIA RTX 6000 Ada Generation",                # $0.77
    "NVIDIA RTX PRO 4500 Blackwell",                 # $0.74  25.4 ms/step  (stock fallback)
    "NVIDIA GeForce RTX 4090",                       # $0.69
)

# The ladder's SHARE of the balance, not the whole thing — production is a SECOND pod.
# Tier A bridged 4/4 stages at p10 last time (~10x cut), so expect ~$5; this bounds the
# disaster if it never bridges. The on-pod kill-switch derives wall-clock from the LIVE
# rate of the card we actually got, so it is a real bound, not a hope.
RELAX_BUDGET_USD = 25.00

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("relax24")


# The stock ceiling is $1.00/hr, which EXCLUDES the PRO 6000 ($1.99) and the A100 ($1.39)
# outright — the card the user approved cannot be rented by the default policy at all, and
# the fallback list would silently have landed us on a 4090. Lifted just far enough to admit
# the PRO 6000; anything above it (H100/H200/B200) stays barred — and is absent from EU-RO-1
# anyway. The ceiling exists so "whatever is available" can't rent a monster for a duplex;
# raising it deliberately, for one run, is not the same as removing it.
MAX_USD_PER_HOUR = 2.10


def _plan_fast(n_atoms: int) -> dict:
    """plan_execution(), but wall-clock-first and with the ceiling raised to admit the
    PRO 6000. Same shape, same VRAM + arch filters — only the ORDER and the price cap move.
    """
    by_key = {g.key: g for g in runpod_script.GPU_TYPES}
    ordered = tuple(
        [by_key[k] for k in PREFERRED_ORDER if k in by_key]
        + [g for g in runpod_script.GPU_TYPES if g.key not in PREFERRED_ORDER]
    )
    for resident in (True, False):
        gpus = runpod_script.recommend_gpus(
            n_atoms,
            gpu_resident=resident,
            candidates=ordered,               # <- fastest first, not cheapest first
            max_usd_per_hour=MAX_USD_PER_HOUR,
        )
        if gpus:
            return {
                "gpu": gpus[0],
                "gpus": gpus,
                "gpu_resident": resident,
                "reason": f"wall-clock-first: {gpus[0].label}, resident={resident}",
            }
    raise RuntimeError(f"no GPU fits {n_atoms:,} atoms under ${MAX_USD_PER_HOUR}/hr")


def _prefer_fast_cards() -> None:
    """Install the wall-clock-first plan into the module that ACTUALLY calls it.

    runpod_executor does `from runpod_script import plan_execution`, so the name is bound
    into ITS namespace at import — rebinding runpod_script.plan_execution alone would be a
    silent no-op (it was: the first attempt still planned a 4090). Patch both.
    """
    from backend.core import runpod_executor
    runpod_script.plan_execution = _plan_fast
    runpod_executor.plan_execution = _plan_fast


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem", help="e.g. 24hb_0xT")
    ap.add_argument("--budget", type=float, default=RELAX_BUDGET_USD)
    args = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2

    job_id = (Path(__file__).parent / f"JOB_ID_{args.stem}").read_text().strip()
    job = MdJob.load(job_id, WORKSPACE)
    assert job.archived and job.archive_path, "job must be archived — see prep_24hb.py"
    assert job.execution_target == "runpod"
    assert job.early_stop_relax and job.early_stop_tier == "A", (
        "Tier-A early-stop is MANDATORY: without it this ladder is ~10x the money"
    )

    # THE MONEY GATE. Fails loud: an unreadable balance REFUSES, it does not shrug.
    try:
        bal, rate = fetch_balance()
    except BalanceUnavailable as exc:
        log.error("cannot read the RunPod balance: %s", exc)
        log.error("REFUSING to launch — see LESSONS L1 (fail-safe means fail-expensive).")
        return 2
    log.info("balance   : $%.2f  (currently billing $%.4f/hr elsewhere)", bal, rate)
    if bal < args.budget:
        log.error("REFUSING: balance $%.2f < this pod's budget $%.2f", bal, args.budget)
        return 2

    _prefer_fast_cards()

    n_atoms = n_atoms_for(job, WORKSPACE)
    min_name = min_name_for(job, WORKSPACE)
    plan = _plan_fast(n_atoms)
    ledger = SpendLedger(Path(job.archive_path) / "spend.json")

    total_steps = sum(s.steps for s in job.segments)
    log.info("design    : %s  (%s atoms)", job.design_name, f"{n_atoms:,}")
    log.info("job       : %s -> %s", job.job_id, job.archive_path)
    log.info("ladder    : %d segments, %s steps (Tier-A early-stop)",
             len(job.segments), f"{total_steps:,}")
    log.info("sizing    : %s  $%s/hr  resident=%s  (priority: %s)",
             plan["gpu"].label, plan["gpu"].usd_per_hour, plan["gpu_resident"],
             ", ".join(g.label for g in plan["gpus"][:3]))
    log.info("budget    : $%.2f for THIS pod (spent so far $%.2f)",
             args.budget, ledger.spent())

    client = RunpodClient(key)
    pod_seen: list[str] = []

    async def _rate_of(pid: str) -> float:
        """What the pod ACTUALLY bills — not what we planned to pay (gpuTypeIds is a
        fallback list; RunPod rents whatever is free)."""
        try:
            pod = await client.get_pod(pid)
            if pod.cost_per_hr:
                return float(pod.cost_per_hr)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read the pod's live rate (%s) — assuming the plan's", exc)
        return float(plan["gpu"].usd_per_hour)

    def _on_pod(pid: str) -> None:
        pod_seen.append(pid)
        log.info("POD %s IS NOW BILLING", pid)
        task = asyncio.get_running_loop().create_task(_rate_of(pid))
        task.add_done_callback(
            lambda t: ledger.open_pod(pid, t.result(), note=f"relax {args.stem}")
        )

    try:
        status = await run_job_on_pod(
            job, WORKSPACE,
            client=client,
            network_volume_id=NETWORK_VOLUME,
            min_name=min_name,
            n_atoms=n_atoms,
            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")],
            poll_s=60.0,
            # ON-DEMAND, not spot: a reclaim restarts the interrupted SEGMENT from its top
            # (no .coor until it completes) and segments are 100k+ steps. One reclaim costs
            # more hours than spot saves dollars.
            interruptible=False,
            on_pod=_on_pod,
            budget_usd=args.budget,
        )
    finally:
        # run_job_on_pod terminates in its own finally; this is belt-and-braces. ONLY the
        # pods this launcher created — never a blanket sweep of the account.
        for pid in pod_seen:
            try:
                await client.terminate_pod(pid)
            except Exception as exc:  # noqa: BLE001
                log.error("could not confirm pod %s terminated: %s", pid, exc)
            ledger.close_pod(pid)
        mine = [p for p in await client.list_pods()
                if not p.is_destroyed and p.id in pod_seen]
        log.info("my pods after teardown: %d %s", len(mine),
                 "OK nothing of mine billing" if not mine
                 else f"*** STILL BILLING: {[p.id for p in mine]}")
        await client.aclose()

    log.info("status    : %s", status)
    if job.error:
        log.error("error     : %s", job.error)
    log.info("\n%s", ledger.summary())
    return 0 if status == MdStatus.completed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
