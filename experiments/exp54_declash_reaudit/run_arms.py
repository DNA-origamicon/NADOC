#!/usr/bin/env python3
"""exp54_declash_reaudit — the audit `md_protocols.prepare_mgh_slow_release` has been
waiting on since its "MARKED FOR RE-AUDIT (2026-08-03)" comment: is the declash gentle
tier still necessary for a small 2xT design, now that the geometric build (no oxDNA
position seed) is the standard path and no longer ships the 0.3 A ring clashes that
originally justified it?

THE QUESTION.  `design_requires_extra_base_declash` auto-forces ANY design with 2+
extra bases at one crossover onto the gentle tier (2 fs, rigidBonds all, no HMR, no
GPU-resident fast path) for its WHOLE relaxation ladder. The evidence that set this was
exp49 (2026-07-30): a 25 ps probe, at the ladder's STIFFEST restraint scale (k=0.5)
only. It never reached the k=0.1 / k=0.01 / unrestrained-MGHH handoff — which is
exactly where the ORIGINAL clashed-seed failure happened ("relaxing to k0.1 dumps
[clash energy] 70x over the velocity limit"). This script runs the FULL ladder, not
another short probe, per the audit's own request.

THE TWO ARMS — identical design, identical everything else:
  A (control, today's actual default) — declash=True: the gentle tier engages.
  B (hypothesis) — declash=False: the standard fast (4 fs + HMR + GPU-resident)
    ladder, with NO special clash-avoidance ENM handling at all.

Both run through `namd_runner.run_job` — the SAME production runner a real job goes
through — so health checks (C1' pairing, WC pairing, broken bp) at every 10/50/100%
segment checkpoint, the instability rescue, and RMSD-vs-design tracking
(`design_rmsd_reports`) are the real code path, not a bespoke re-implementation.
`early_stop_relax=False` on both arms so the accelerator cannot skip a stage as
"already plateaued" — every segment actually has to run for the later stages to be
real evidence, not an assumption.

    python experiments/exp54_declash_reaudit/run_arms.py workspace/2hb_2xT.nadoc \\
        -o experiments/exp54_declash_reaudit/runs/2hb_2xT

Runs isolated MdJob records under `<out>/md_jobs/` (a workspace_dir of its own, NOT the
shared `workspace/` the dev server watches) so this cannot collide with anything else
using the app. Arms run SEQUENTIALLY — they share one GPU, and overlapping them would
make the wall-clock comparison meaningless and could itself cause instability.

⚠ This is the FULL ladder per arm, not a short probe — expect hours, not minutes.
Check `nvidia-smi` first; do not run alongside another NAMD job.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core import namd_runner  # noqa: E402
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job  # noqa: E402
from backend.core.md_protocols import (  # noqa: E402
    EQUILIBRIUM_AWARE_PROTOCOL,
    minimization_status,
    prepare_equilibrium_aware_namd,
)
from backend.core.models import Design  # noqa: E402


def _load(path: Path) -> Design:
    return Design.model_validate_json(path.read_text())


def _build(design: Design, out_dir: Path, *, declash: bool, label: str) -> MdJob:
    """Solvate + write every stage conf for one arm, as a real (isolated) MdJob."""
    job = new_job(
        design.metadata.name or "design", EQUILIBRIUM_AWARE_PROTOCOL, "", "",
        threads=16, devices="0",
    )
    job.save(out_dir)
    job_dir = job.job_dir(out_dir)
    # `namd_runner._record_design_rmsd` reads this straight off disk — the same file
    # `_prepare_job_bg` writes for a real job.
    (job_dir / "design.json").write_text(design.model_dump_json())
    print(f"[{label}] building (declash={declash})…", flush=True)
    package_subdir, name_stem, segments = prepare_equilibrium_aware_namd(
        design, job_dir,
        declash=declash,
        force_soft=False,
        fast=True,
        # The accelerator could otherwise mark a later stage "done, skipped" as
        # plateaued without ever running it — exactly the evidence this audit needs.
        early_stop_relax=False,
    )
    job.package_subdir = package_subdir
    job.name_stem = name_stem
    job.segments = [
        MdSegmentStatus(name=s.name, stage=s.stage, percent=s.percent, steps=s.steps,
                         status="pending")
        for s in segments
    ]
    manifest = json.loads((job_dir / package_subdir / "manifest.json").read_text())
    job.minimization = minimization_status(manifest)
    job.status = MdStatus.queued
    job.early_stop_relax = False
    job.save(out_dir)
    print(f"[{label}] built: {len(segments)} segments, package={package_subdir}",
          flush=True)
    return job


async def _run_arm(job: MdJob, out_dir: Path, label: str) -> dict:
    t0 = time.monotonic()
    print(f"[{label}] running full ladder ({len(job.segments)} segments, "
          f"job_id={job.job_id})…", flush=True)
    await namd_runner.run_job(job, out_dir)
    wall_s = time.monotonic() - t0
    job = MdJob.load(job.job_id, out_dir)  # reload the final persisted state
    print(f"[{label}] finished: status={job.status.value} wall={wall_s / 3600:.2f} h",
          flush=True)
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "error": job.error,
        "failure_kind": job.failure_kind,
        "wall_s": round(wall_s, 1),
        "segments": [
            {"name": s.name, "stage": s.stage, "status": s.status, "skipped": s.skipped}
            for s in job.segments
        ],
        "health_samples": [asdict(h) for h in job.health_samples],
        "design_rmsd_reports": job.design_rmsd_reports,
    }


def _summarize(arm: dict) -> None:
    if not arm:
        print("  (not run)")
        return
    print(f"  status={arm['status']} wall={arm['wall_s'] / 3600:.2f} h "
          f"error={arm.get('error') or '—'}")
    for s in arm["segments"]:
        mark = "skip" if s["skipped"] else s["status"]
        if mark != "done":
            print(f"    {s['name']:45s} {mark}")
    last_health = arm["health_samples"][-1] if arm["health_samples"] else None
    if last_health:
        print(f"  last health @ {last_health['segment']}: "
              f"c1={last_health['c1_paired_fraction']} "
              f"wc={last_health['wc_ref_relative_fraction']} "
              f"broken_bp={last_health['broken_bp_count']} passed={last_health['passed']}")
    last_rmsd = arm["design_rmsd_reports"][-1] if arm["design_rmsd_reports"] else None
    if last_rmsd:
        print(f"  last RMSD-vs-design @ {last_rmsd['segment']}: "
              f"{last_rmsd['rmsd_nm']} nm ({last_rmsd['n_atoms']} atoms)")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("design", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--arm", choices=["a", "b", "both"], default="both",
                     help="run only one arm (to split the work across sessions); "
                          "results merge into the same report file")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    design = _load(args.design)
    print(f"design: {args.design.name}", flush=True)

    report_path = args.out / "exp54_report.json"
    report = (json.loads(report_path.read_text()) if report_path.exists()
              else {"design": str(args.design)})

    if args.arm in ("a", "both"):
        job_a = _build(design, args.out, declash=True, label="A(declash)")
        report["arm_a"] = asyncio.run(_run_arm(job_a, args.out, "A(declash)"))
        report_path.write_text(json.dumps(report, indent=2))

    if args.arm in ("b", "both"):
        job_b = _build(design, args.out, declash=False, label="B(no-declash)")
        report["arm_b"] = asyncio.run(_run_arm(job_b, args.out, "B(no-declash)"))
        report_path.write_text(json.dumps(report, indent=2))

    print("\n=== SUMMARY ===")
    print("Arm A (declash=True, today's default):")
    _summarize(report.get("arm_a"))
    print("Arm B (declash=False, the hypothesis):")
    _summarize(report.get("arm_b"))
    print(f"\nreport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
