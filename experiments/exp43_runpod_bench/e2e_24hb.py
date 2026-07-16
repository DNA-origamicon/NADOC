#!/usr/bin/env python
"""Tiny full-cycle RunPod test for a 24hb package: rents a GPU, runs the WHOLE ladder
(minimise + every segment) truncated to a few hundred steps, fetches, and destroys the
pod. Exercises exactly what a 50 ns run does — stage -> minimise -> [rebuild is local-only]
-> GPU-resident probe -> every ladder rung -> fetch -> teardown — for cents, so we can
confirm the cycle completes and validate each step before committing to the real run.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) python experiments/exp43_runpod_bench/e2e_24hb.py <stem> <job_id>

Creates a real billing pod; terminates it in `finally`. If SIGKILLed mid-run, check reap.py.
"""
from __future__ import annotations
import asyncio, os, re, shutil, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job  # noqa: E402
from backend.core.job_archive import read_index, _write_index  # noqa: E402
from backend.core.runpod_api import RunpodClient  # noqa: E402
from backend.core.runpod_executor import run_job_on_pod  # noqa: E402
from backend.core.runpod_supervisor import n_atoms_for  # noqa: E402

WORKSPACE = ROOT / "experiments" / "exp43_runpod_bench" / "workspace_e2e"
NETWORK_VOLUME = "77pnhye88p"
ARCHIVE = Path("/media/jojo/Archive/nadoc_scratch/e2e_24hb")
MIN_STEPS = 2400     # a real minimise is 4800; the geometric build is clean so 2400 suffices here
SEG_STEPS = 800      # a real segment is 120k-600k; 800 exercises the stage in seconds


def build_tiny(stem: str, src_job_id: str):
    src = MdJob.load(src_job_id, ROOT / "workspace")
    src_pkg = src.package_dir(ROOT / "workspace")
    name_stem = src.name_stem
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    job = new_job(design_name=stem, protocol="equilibrium_aware_namd",
                  name_stem=name_stem, package_subdir=src.package_subdir,
                  design_source_path=f"{stem}.nadoc")
    job.execution_target = "runpod"
    job.early_stop_relax = False   # tiny segments have too few frames for the WC gate; run them all
    job.archived = True
    job.archive_path = str(ARCHIVE / job.job_id)
    Path(job.archive_path).mkdir(parents=True, exist_ok=True)
    idx = read_index(WORKSPACE, "md_jobs"); idx[job.job_id] = job.archive_path
    _write_index(WORKSPACE, "md_jobs", idx)
    dst_pkg = job.package_dir(WORKSPACE)
    dst_pkg.mkdir(parents=True, exist_ok=True)

    # copy every package file EXCEPT the multi-GB DCDs / prior output
    for p in src_pkg.iterdir():
        if p.is_dir():
            if p.name in ("forcefield", "scripts"):
                shutil.copytree(p, dst_pkg / p.name, dirs_exist_ok=True)
        elif p.suffix not in (".dcd",):
            shutil.copy2(p, dst_pkg / p.name)
    (dst_pkg / "output").mkdir(exist_ok=True)

    # truncate the minimise + every segment conf
    min_name = f"{name_stem}_00_min_enm_k0p5"
    mc = (dst_pkg / f"{min_name}.conf")
    mc.write_text(re.sub(r"(?im)^minimize\s+\d+", f"minimize           {MIN_STEPS}", mc.read_text()))
    segs = []
    for seg in src.segments:
        cf = dst_pkg / f"{seg.name}.conf"
        if cf.exists():
            cf.write_text(re.sub(r"(?im)^run\s+\d+", f"run                {SEG_STEPS}", cf.read_text()))
            segs.append(MdSegmentStatus(name=seg.name, stage=seg.stage, percent=seg.percent, steps=SEG_STEPS))
    job.segments = segs
    return job, min_name


async def main() -> int:
    key = os.environ.get("RUNPOD_API_KEY")
    if not key:
        print("RUNPOD_API_KEY not set", file=sys.stderr); return 2
    stem, src_job_id = sys.argv[1], sys.argv[2]
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    job, min_name = build_tiny(stem, src_job_id)
    n_atoms = n_atoms_for(job, WORKSPACE)
    print(f"stem={stem}  src_job={src_job_id}  tiny_job={job.job_id}")
    print(f"atoms={n_atoms:,}  ladder=minimise {MIN_STEPS} + {len(job.segments)} segs x {SEG_STEPS} steps\n")

    client = RunpodClient(key); pod_seen: list[str] = []; t0 = time.time()
    try:
        status = await run_job_on_pod(
            job, WORKSPACE, client=client, network_volume_id=NETWORK_VOLUME,
            min_name=min_name, n_atoms=n_atoms,
            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")],
            poll_s=20.0, interruptible=False, budget_usd=5.0,
            on_pod=lambda pid: (pod_seen.append(pid), print(f"POD {pid} BILLING")))
    finally:
        for pid in pod_seen:
            try: await client.terminate_pod(pid)
            except Exception as e: print(f"  !! terminate {pid}: {e}")
        live = [p for p in await client.list_pods() if not p.is_destroyed and p.id in pod_seen]
        print(f"\nlive pods after teardown: {len(live)} {'OK nothing billing' if not live else '*** STILL BILLING '+str([p.id for p in live])}")
        await client.aclose()

    mins = (time.time() - t0) / 60
    out = job.package_dir(WORKSPACE) / "output"
    coors = sorted(p.name for p in out.glob("*.coor")) if out.exists() else []
    print(f"\nstatus={status}  wall={mins:.1f} min")
    if job.error: print(f"error: {job.error}")
    print(f"fetched {len(coors)} .coor (one per completed step):")
    for c in coors: print(f"   {c}")
    # validation: minimise + every segment produced a checkpoint, job completed, no pod left
    expect = 1 + len(job.segments)
    ok = status == MdStatus.completed and len(coors) >= expect and not live
    print(f"\n{'E2E PASS ✓' if ok else 'E2E FAIL ✗'}  (expected >= {expect} coor, got {len(coors)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
