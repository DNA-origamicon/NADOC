#!/usr/bin/env python
"""PHASE 4 — end-to-end: NADOC rents a GPU, runs a NAMD ladder on it, and destroys it.

This is the first time the whole chain runs for real:

    plan_execution → create pod → wait for SSH → stage package → render chain script
    → launch detached → poll status/heartbeat/progress → fetch results → TERMINATE

It uses the REAL 6hb package but rewrites the ladder to a few hundred steps, so the run
is minutes and cents rather than hours and dollars. Everything else — the staging, the
chain script, the polling, the teardown — is exactly what a production job does.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) python experiments/exp43_runpod_bench/e2e_runpod_job.py

⚠️ It creates a real, billing pod. It terminates it in a `finally`, but if this process is
SIGKILLed mid-run, check `GET /api/runpod/pods` (or the RunPod console) for a survivor.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.md_job import MdSegmentStatus, MdStatus, new_job  # noqa: E402
from backend.core.runpod_api import RunpodClient  # noqa: E402
from backend.core.runpod_executor import run_job_on_pod  # noqa: E402
from backend.core.runpod_script import plan_execution  # noqa: E402
from backend.core.runpod_supervisor import n_atoms_for  # noqa: E402

NETWORK_VOLUME = "77pnhye88p"
SRC_PKG = Path(
    "workspace/md_jobs/a81b371be69d/package/6hb_sim_v2_namd_solvated"
)
SCRATCH = Path("workspace/bench_fixtures/e2e_runpod")

MIN_STEPS = 4800    # the REAL minimisation. 240 left the build clashes in and dynamics
                    # blew up at step 1 ("Atoms moving too fast") — the exact failure
                    # NADOC's own memory warns about. Do not shortcut it.
SEG_STEPS = 1200     # a real segment is 240,000
STEM = "6hb_sim_v2"


def build_tiny_job():
    """Copy the real 6hb package and shrink the ladder to a couple of minutes."""
    ws = SCRATCH
    if ws.exists():
        shutil.rmtree(ws)
    job = new_job("6hb_sim_v2", "equilibrium_aware_namd", STEM,
                  f"package/{SRC_PKG.name}")
    job.execution_target = "runpod"
    pkg = job.package_dir(ws)
    pkg.mkdir(parents=True)

    # Only what the min + first relax segment actually reference. (restraints_dna_heavy
    # is unused — every conf says `constraints off` — and k0.1/k0.01 belong to later
    # stages. Staging them would triple the upload for nothing.)
    keep = [
        f"{STEM}.psf", f"{STEM}_hmr.psf", f"{STEM}.pdb",
        f"{STEM}_k0.5.enm.extra", "mgh_extrabonds.txt", "manifest.json",
    ]
    for name in keep:
        src = SRC_PKG / name
        if src.exists():
            shutil.copy2(src, pkg / name)
    shutil.copytree(SRC_PKG / "forcefield", pkg / "forcefield")

    min_name = f"{STEM}_00_min_enm_k0p5"
    seg_name = f"{STEM}_01_300K_NPT_ENM_k0p5_p10"

    min_conf = (SRC_PKG / f"{min_name}.conf").read_text()
    min_conf = re.sub(r"(?im)^minimize\s+\d+", f"minimize           {MIN_STEPS}", min_conf)
    (pkg / f"{min_name}.conf").write_text(min_conf)

    seg_conf = (SRC_PKG / f"{seg_name}.conf").read_text()
    seg_conf = re.sub(r"(?im)^run\s+\d+", f"run                {SEG_STEPS}", seg_conf)
    (pkg / f"{seg_name}.conf").write_text(seg_conf)

    job.segments = [
        MdSegmentStatus(name=seg_name, stage="01_300K_NPT_ENM_k0p5",
                        percent=10.0, steps=SEG_STEPS)
    ]
    return job, ws, min_name


async def main() -> int:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2

    job, ws, min_name = build_tiny_job()
    # Use the SAME reader production uses. (A fixed-size head read misses !NATOM:
    # psfgen writes one REMARKS line per patch, so the !NTITLE block is huge.)
    n_atoms = n_atoms_for(job, ws)

    plan = plan_execution(n_atoms)
    print(f"design      : {job.design_name}  ({n_atoms:,} atoms)")
    print(f"sizing      : {plan['gpu'].label}  ${plan['gpu'].usd_per_hour}/hr  — {plan['reason']}")
    print(f"ladder      : minimise {MIN_STEPS} steps → 1 segment × {SEG_STEPS} steps")
    print(f"job         : {job.job_id}\n")

    client = RunpodClient(key)
    t0 = time.time()
    pod_seen: list[str] = []
    try:
        status = await run_job_on_pod(
            job, ws,
            client=client,
            network_volume_id=NETWORK_VOLUME,
            min_name=min_name,
            n_atoms=n_atoms,
            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")],
            poll_s=15.0,
            interruptible=False,   # a spot reclaim mid-smoke-test just muddies the signal
            on_pod=lambda pid: (pod_seen.append(pid), print(f"pod         : {pid} (BILLING)")),
        )
    finally:
        # Belt and braces: run_job_on_pod terminates in its own finally, but if anything
        # escaped it, kill the pod here. A survivor bills until a human notices.
        for pid in pod_seen:
            try:
                await client.terminate_pod(pid)
            except Exception as exc:  # noqa: BLE001
                print(f"  !! could not confirm pod {pid} terminated: {exc}")
        live = [p for p in await client.list_pods() if not p.is_terminated]
        print(f"\nlive pods after teardown: {len(live)}  "
              f"{'✓ nothing billing' if not live else '*** STILL BILLING: ' + str([p.id for p in live])}")
        await client.aclose()

    mins = (time.time() - t0) / 60
    print(f"\nstatus      : {status}")
    print(f"wall        : {mins:.1f} min   (~${mins / 60 * plan['gpu'].usd_per_hour:.2f})")
    if job.error:
        print(f"error       : {job.error}")

    out = job.package_dir(ws) / "output"
    coors = sorted(p.name for p in out.glob("*.coor")) if out.exists() else []
    print(f"fetched     : {len(coors)} .coor files back from the pod")
    for c in coors:
        print(f"   {c}")

    ok = status == MdStatus.completed and len(coors) >= 2
    print(f"\n{'E2E PASS ✓' if ok else 'E2E FAIL ✗'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
