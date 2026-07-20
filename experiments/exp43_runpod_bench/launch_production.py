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
# Parent relaxation job is selected by --parent-stem (reads JOB_ID_<stem>); defaults to the
# original 3x6x400 bench for back-compat. The production child id is written to
# JOB_ID_<stem>_production.
DEFAULT_PARENT_STEM = "3x6x400"

TIMESTEP_FS = 4.0

# The card we are actually given, every time: the 4090 we ask for first is never free in
# EU-RO-1 and RunPod falls through to this one. Secure price, live-checked 2026-07-14.
PRO_4500_SECURE_USD_PER_HR = 0.74

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prod")


# ⚠️ PRODUCTION IS NOT AS FAST AS THE RELAXATION, and sizing it off the relaxation's rate
# is how this run was mis-sized by 2x. Production DELIBERATELY runs a more expensive
# integrator (build_production_conf):
#
#   fullElectFrequency 1 (relax: 2)  — PME EVERY step. At 4 fs that is PME every 4 fs,
#                                      matching the Aksimentiev reference. fullElect 2
#                                      would be PME every 8 fs, past the r-RESPA
#                                      resonance-stability limit. NOT negotiable.
#   stepspercycle 10 (relax: 20)     — 40 fs pairlist rebuild. Deliberate.
#
# MEASURED: relaxation fast chunks 26.4 ms/step; production 50.0 ms/step on the same card
# and system. Some of that gap was I/O waste (now fixed — see _production_output_freqs),
# but the physics difference is real and permanent. Always cost production from a
# PRODUCTION measurement, never from the relaxation's.
PRODUCTION_PENALTY = 1.35   # conservative, applied when only a relaxation rate is known


def measured_s_per_step(parent: MdJob, workspace: Path) -> Optional[float]:
    """Read the 4 fs GPU-resident rate out of the relaxation's own NAMD logs.

    ⚠️ This is the RELAXATION's rate. Production runs a more expensive integrator by
    design (see PRODUCTION_PENALTY above) — the caller MUST inflate it, or size from a
    real production log.

    Deliberately ignores the 00_min (2 fs) and the SOFT first chunk (1 fs, offload, no
    GPUresident, flexible H bonds): those run a different integrator entirely, and the
    soft chunk measured 43-51 ms/step against the fast path's 26.4. Sizing off the wrong
    one halves or doubles the run.
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
    ap.add_argument("--dcd-freq", type=int, default=None,
                    help="DCD output interval (steps) for the production run. Default = "
                         "PRODUCTION_DCD_FREQ (2500 = every 10 ps at 4 fs). Lower for denser "
                         "sampling to feed fluctuation-based parameter extraction (FEM/SNUPI).")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--budget", type=float, default=None,
                    help="override the per-parent ledger's remaining $ (fit check + on-pod "
                         "kill-switch). Use when the stale campaign cap reads $0 but the run "
                         "is separately authorised.")
    ap.add_argument("--parent-stem", default=DEFAULT_PARENT_STEM,
                    help="relaxation job to seed production from; reads JOB_ID_<stem> "
                         "(e.g. 24hb_0xT, 24hb_1xT_seeded). Default: the 3x6x400 bench.")
    ap.add_argument("--gpu-prefs", default=None,
                    help="ORDERED, comma-separated GPU preference by label "
                         "(e.g. 'RTX 6000 Ada,RTX 5090,RTX PRO 4500'). Replaces the default "
                         "cheapest-first fallback with EXACTLY these cards in THIS order — "
                         "RunPod rents the first one available in the volume's datacenter. "
                         "No cheaper card outside the list is offered. Cost/rate size from "
                         "the FIRST (preferred) card.")
    args = ap.parse_args()

    if args.gpu_prefs:
        # Restrict + REORDER the whole planner (this launcher's sizing call AND the
        # executor's pod_payloads_for) to exactly the requested cards, preserving priority.
        # plan_execution -> recommend_gpus is resolved against runpod_script's module globals
        # at call time, and recommend_gpus keeps the candidate ORDER (it does not re-sort),
        # so patching the name there hands RunPod our priority list without touching core
        # signatures or the pinned GPU table.
        import backend.core.runpod_script as _rs  # noqa: E402
        # Cards benchmarked on this system but not in the pinned cheapest-first table.
        # Exact RunPod key + measured price from logs/bench_5090_3090.log (2026-07-15).
        _EXTRA = {
            "RTX 5090": _rs.GpuType("NVIDIA GeForce RTX 5090", "RTX 5090",
                                    32_768, 0.99, "sm_120"),
        }
        _by_label = {g.label: g for g in _rs.GPU_TYPES} | _EXTRA
        wanted = [s.strip() for s in args.gpu_prefs.split(",") if s.strip()]
        unknown = [w for w in wanted if w not in _by_label]
        if unknown:
            log.error("unknown --gpu-prefs label(s) %s; known: %s", unknown,
                      ", ".join(sorted(_by_label)))
            return 2
        ordered = tuple(_by_label[w] for w in wanted)
        _orig_recommend = _rs.recommend_gpus

        def _pref_recommend(n_atoms, **kw):  # keeps VRAM/arch/price filtering, our order
            kw["candidates"] = ordered
            return _orig_recommend(n_atoms, **kw)

        _rs.recommend_gpus = _pref_recommend
        log.info("GPU preference (in order): %s",
                 " > ".join(f"{g.label} ${g.usd_per_hour:.2f}/hr" for g in ordered))
    parent_id = (Path(__file__).parent / f"JOB_ID_{args.parent_stem}").read_text().strip()
    child_id_file = Path(__file__).parent / f"JOB_ID_{args.parent_stem}_production"

    key = os.environ.get("RUNPOD_API_KEY")
    if not key and not args.dry_run:
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2

    parent = MdJob.load(parent_id, WORKSPACE)
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

    s_per_step = args.s_per_step
    src = "given"
    if not s_per_step:
        relax = measured_s_per_step(parent, WORKSPACE)
        if not relax:
            log.error("no 4 fs GPU-resident benchmark line in the relaxation logs — pass "
                      "--s-per-step (a PRODUCTION rate) explicitly rather than let me guess")
            return 1
        # Inflate: production's integrator is more expensive BY DESIGN. Sizing off the
        # relaxation's rate is exactly how this run was mis-sized 2x.
        s_per_step = relax * PRODUCTION_PENALTY
        src = f"relaxation {relax*1000:.1f} ms/step x {PRODUCTION_PENALTY} production penalty"

    # ``--budget`` overrides the per-parent ledger's remaining. The original campaign ledger
    # carries a stale $120 cap that reads $0 remaining after two full 50 ns runs; a
    # user-directed continuation with its own budget must not be blocked by that. When set,
    # this value is BOTH the fit check below AND the on-pod kill-switch (budget_usd) — a real
    # bound, just a fresh one.
    remaining = args.budget if args.budget is not None else ledger.remaining()
    ns = args.ns if args.ns is not None else size_production_ns(remaining, rate, s_per_step)
    steps = int(ns * 1e6 / TIMESTEP_FS)
    hours = steps * s_per_step / 3600.0

    log.info("spent so far : $%.2f  (cap $15.00)", ledger.spent())
    log.info("remaining    : $%.2f  after the teardown reserve", remaining)
    log.info("rate         : %.1f ms/step  (%.1f ns/day at %g fs)   [%s]",
             s_per_step * 1000, TIMESTEP_FS * 1e-6 / s_per_step * 86400, TIMESTEP_FS, src)
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
            dcd_freq=args.dcd_freq,
        ),
    )
    child = MdJob.load(result["job"]["job_id"], WORKSPACE)
    child_id_file.write_text(child.job_id + "\n")

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
