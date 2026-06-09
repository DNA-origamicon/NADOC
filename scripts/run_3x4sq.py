#!/usr/bin/env python3
"""
Standalone runner for the 3x4SQ MD job.

Resets the job to segment 0 (minimization output already exists) and
runs all segments sequentially, checking health gates after each one.
Intended to be launched from the NADOC project root:

  python scripts/run_3x4sq.py [--from-segment SEG_NAME] [--threads N]

--from-segment  Resume from a named segment (skips earlier ones without re-running).
                Defaults to the first segment (re-runs from the start of dynamics).
--threads       NAMD thread count. Default: 16.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# ── Project root on sys.path ──────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob, MdStatus
from backend.core.namd_runner import run_job

# ── Constants ─────────────────────────────────────────────────────────────────
JOB_ID    = "26b0a0407302"
WORKSPACE = ROOT / "workspace"

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s %(levelname)s %(message)s",
    datefmt = "%H:%M:%S",
    stream  = sys.stdout,
)
log = logging.getLogger("run_3x4sq")


def reset_job(job: MdJob, from_segment: str | None, threads: int) -> int:
    """Reset job state; return the segment index to start from."""
    job.threads = threads
    job.status  = MdStatus.queued
    job.error   = None
    job.health_samples = []

    start_idx = 0
    if from_segment:
        names = [s.name for s in job.segments]
        if from_segment not in names:
            log.error("--from-segment %r not found in manifest. Valid names:", from_segment)
            for n in names:
                log.error("  %s", n)
            sys.exit(1)
        start_idx = names.index(from_segment)
        log.info("Resuming from segment index %d: %s", start_idx, from_segment)

    job.current_segment_idx = start_idx
    for i, s in enumerate(job.segments):
        if i < start_idx:
            s.status = "done"   # treat earlier segments as complete
        else:
            s.status = "pending"
    job.save(WORKSPACE)
    return start_idx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-segment", default=None,
                        help="Resume from named segment (skip earlier ones)")
    parser.add_argument("--threads", type=int, default=16,
                        help="NAMD thread count (default 16)")
    args = parser.parse_args()

    job = MdJob.load(JOB_ID, WORKSPACE)
    log.info("Loaded job %s  design=%s  protocol=%s", JOB_ID, job.design_name, job.protocol)
    log.info("Package: %s", job.package_dir(WORKSPACE))
    log.info("Segments: %d total", len(job.segments))

    reset_job(job, args.from_segment, args.threads)

    t0 = time.time()
    log.info("=" * 60)
    log.info("Starting run_job coroutine ...")
    log.info("=" * 60)

    asyncio.run(run_job(job, WORKSPACE))

    # Reload final state
    job = MdJob.load(JOB_ID, WORKSPACE)
    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("FINAL STATUS: %s  (%.0f s elapsed)", job.status.value, elapsed)
    if job.error:
        log.error("Error: %s", job.error)

    log.info("Health samples:")
    for h in job.health_samples:
        flag = "PASS" if h.passed else "FAIL"
        log.info(
            "  [%s] %s  c1=%.3f wc=%.3f  %s",
            flag, h.segment,
            h.c1_paired_fraction or 0.0,
            h.wc_ref_relative_fraction or 0.0,
            h.reason or "",
        )

    sys.exit(0 if job.status == MdStatus.completed else 1)


if __name__ == "__main__":
    main()
