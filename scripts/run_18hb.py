#!/usr/bin/env python3
"""Headless launcher + resumer for the 18hb production MD run.

This drives the *real* production pipeline (psfgen full topology → GROMACS
solvation → Aksimentiev ENM slow-release ladder k=0.5→0.1→0.01→k=0) with no
dependency on the uvicorn dev server, so it can run for days under ``nohup`` and
be relaunched losslessly from NAMD checkpoints by the monitoring loop.

Usage (from project root):

    # Fresh: create the job, prep (solvate + configs), then run the ladder.
    python scripts/run_18hb.py

    # Resume: reconcile the persisted job and continue from its last checkpoint.
    python scripts/run_18hb.py --resume

Design decisions (see memory/project_md_prep_relaxation.md exp29):
  * salt_mode=custom + 50 mM NaCl on 12.5 mM Mg/MGH/CUFIX — exp29's electrostatic
    screening win (the single biggest k=0-survival lever, saturates ~50 mM).
  * minimize_steps=24000 — exp29 Cycle 1's adopted cheap default.
  * 18hb has no extra bases → declash auto-off; full-topology strict production.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.md_protocols import (
    EQUILIBRIUM_AWARE_PROTOCOL,
    prepare_equilibrium_aware_namd,
)
from backend.core.models import Design
from backend.core.namd_runner import reconcile_job_status, run_job

WORKSPACE = ROOT / "workspace"
DESIGN_PATH = WORKSPACE / "18hb.nadoc"
DESIGN_SOURCE = "18hb.nadoc"  # workspace-relative, recorded on the job
EXP_DIR = ROOT / "experiments" / "exp30_18hb_production"
JOB_ID_FILE = EXP_DIR / "JOB_ID"

# Production knobs (documented above).
ION_CONC_MM = 50.0
MG_CONC_MM = 12.5
MINIMIZE_STEPS = 24_000
THREADS = 16
DEVICES = "0"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("run_18hb")


def _count_psf_atoms(package_dir: Path) -> int | None:
    """Return NATOM from the solvated PSF, or None if not found."""
    for psf in sorted(package_dir.rglob("*.psf")):
        for line in psf.read_text(errors="replace").splitlines():
            if "!NATOM" in line:
                try:
                    return int(line.split()[0])
                except (ValueError, IndexError):
                    return None
    return None


def prepare_fresh() -> MdJob:
    """Create a new job and run the (blocking) solvation + config-gen prep."""
    if not DESIGN_PATH.exists():
        raise SystemExit(f"Design not found: {DESIGN_PATH}")
    design = Design.model_validate_json(DESIGN_PATH.read_text())
    name = (design.metadata.name or "18hb").replace(" ", "_")

    sequenced = sum(
        sum(1 for c in (s.sequence or "") if c.upper() in "ACGT")
        for s in design.strands
    )
    if sequenced == 0:
        raise SystemExit(
            "Design has no sequence assigned — every base would be THY and the "
            "topology would be physically meaningless. Assign a scaffold sequence "
            "(e.g. M13mp18) and staples before running."
        )

    job = new_job(
        design_name=name,
        protocol=EQUILIBRIUM_AWARE_PROTOCOL,
        name_stem="",
        package_subdir="",
        threads=THREADS,
        devices=DEVICES,
        design_source_path=DESIGN_SOURCE,
    )
    job.status = MdStatus.preparing
    job.save(WORKSPACE)
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    JOB_ID_FILE.write_text(job.job_id + "\n")
    log.info("Created job %s (design=%s); wrote %s", job.job_id, name, JOB_ID_FILE)

    log.info(
        "Preparing (psfgen full topology → GROMACS solvate @ %g mM NaCl + %g mM Mg → "
        "ENM ladder configs, minimize=%d steps)...",
        ION_CONC_MM,
        MG_CONC_MM,
        MINIMIZE_STEPS,
    )
    t0 = time.time()
    try:
        package_subdir, name_stem, segments = prepare_equilibrium_aware_namd(
            design,
            job.job_dir(WORKSPACE),
            ion_conc_mM=ION_CONC_MM,
            mg_conc_mM=MG_CONC_MM,
            salt_mode="custom",
            minimize_steps=MINIMIZE_STEPS,
            declash=False,
        )
    except Exception as exc:
        job.status = MdStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(WORKSPACE)
        log.exception("Preparation FAILED for %s", job.job_id)
        raise SystemExit(1) from exc

    job.package_subdir = package_subdir
    job.name_stem = name_stem
    job.segments = [
        MdSegmentStatus(
            name=s.name,
            stage=s.stage,
            percent=s.percent,
            steps=s.steps,
            status="pending",
        )
        for s in segments
    ]
    job.status = MdStatus.queued
    job.save(WORKSPACE)

    natoms = _count_psf_atoms(job.job_dir(WORKSPACE) / "package")
    log.info(
        "Prep done in %.0fs: package=%s name_stem=%s segments=%d solvated_atoms=%s",
        time.time() - t0,
        package_subdir,
        name_stem,
        len(segments),
        f"{natoms:,}" if natoms else "unknown",
    )
    for s in segments:
        log.info("  segment %-32s steps=%d (%s)", s.name, s.steps, s.stage)
    return job


def load_existing() -> MdJob:
    if not JOB_ID_FILE.exists():
        raise SystemExit(
            f"No {JOB_ID_FILE}; run without --resume to create a job first."
        )
    job_id = JOB_ID_FILE.read_text().strip()
    job = MdJob.load(job_id, WORKSPACE)
    job = reconcile_job_status(job, WORKSPACE)
    log.info(
        "Resuming job %s status=%s segment_idx=%d",
        job_id,
        job.status,
        job.current_segment_idx,
    )
    return job


def main() -> None:
    ap = argparse.ArgumentParser(description="18hb production MD launcher/resumer")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="Resume the persisted job (JOB_ID file) from its last NAMD checkpoint.",
    )
    args = ap.parse_args()

    job = load_existing() if args.resume else prepare_fresh()

    if job.status in (MdStatus.completed, MdStatus.failed, MdStatus.stopped):
        log.info("Job %s is terminal (%s); nothing to run.", job.job_id, job.status)
        return

    log.info(
        "Launching ladder for %s (threads=%d device=%s)...",
        job.job_id,
        THREADS,
        DEVICES,
    )
    asyncio.run(run_job(job, WORKSPACE))
    final = reconcile_job_status(MdJob.load(job.job_id, WORKSPACE), WORKSPACE)
    log.info(
        "run_job returned. Final status: %s (segment_idx=%d)",
        final.status,
        final.current_segment_idx,
    )


if __name__ == "__main__":
    main()
