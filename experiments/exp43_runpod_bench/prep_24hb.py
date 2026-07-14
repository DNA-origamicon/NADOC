#!/usr/bin/env python3
"""STEP 1 — build a 24hb NAMD package (one variant), straight onto the archive drive.

Same protocol as prep_3x6x400.py, parameterised by design stem so the three
extra-crossover-base variants (0xT / 1xT / 2xT) are prepped IDENTICALLY. Any drift
between the three packages would show up in the stiffness fit as a fake extra-base
effect, so every knob below is shared and none is per-variant.

Prep is CPU work (psfgen -> GROMACS solvate -> ENM ladder confs -> HMR PSF). It is FREE.
Never do it on a rented GPU. Run the variants SERIALLY — see feedback_no_parallel_gromacs.

    python experiments/exp43_runpod_bench/prep_24hb.py 24hb_0xT
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.job_archive import read_index, _write_index  # noqa: E402
from backend.core.md_job import MdSegmentStatus, MdStatus, new_job  # noqa: E402
from backend.core.md_protocols import (  # noqa: E402
    EQUILIBRIUM_AWARE_PROTOCOL,
    prepare_equilibrium_aware_namd,
    write_hmr_psf,
)
from backend.core.models import Design  # noqa: E402

WORKSPACE = ROOT / "workspace"
ARCHIVE_ROOT = Path("/media/jojo/Archive/nadoc_jobs")

VARIANTS = ("24hb_0xT", "24hb_1xT", "24hb_2xT")

# Shared across all three variants. salt_mode="screening" + 12.5 mM Mg; the 4800-step
# minimisation is the REAL one (240 leaves build clashes in and dynamics blows up at
# step 1).
ION_CONC_MM = 0.0
MG_CONC_MM = 12.5
SALT_MODE = "screening"
PADDING_NM = 1.2
MINIMIZE_STEPS = 4800
MIN_SCALE = 0.5

# THE single biggest free win, and it is a PREP-TIME flag — not a runtime one. `fast`
# writes confs with `GPUresident on`, a 4 fs timestep and the HMR PSF. Without it the
# package runs at 2 fs in offload mode and quietly costs ~4x the money for the same
# science (and the HMR PSF is written but referenced by nothing). preflight.py re-checks.
FAST = True

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prep")


def sanity_gate(pkg: Path, stem: str) -> bool:
    """The VoltronCore gate. ANY coincident heavy-atom pair is fatal — infinite VDW.

    A degenerate package kills NAMD with an uninterpretable NaN, hours later, on a
    billing pod. This runs before a single cent is spent.
    """
    import numpy as np
    from scipy.spatial import cKDTree

    pdb = pkg / f"{stem}.pdb"
    log.info("sanity gate: reading %s", pdb.name)

    xyz, heavy = [], []
    with pdb.open() as fh:
        for line in fh:
            if line.startswith(("ATOM", "HETATM")):
                xyz.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
                el = line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]
                heavy.append(el.upper() != "H")

    xyz = np.asarray(xyz, dtype=np.float64)
    heavy = np.asarray(heavy, dtype=bool)
    hv = xyz[heavy]
    log.info("  %d atoms total, %d heavy", len(xyz), len(hv))

    tree = cKDTree(hv)
    pairs = tree.query_pairs(r=0.05, output_type="ndarray")
    n_coincident = len(pairs)
    d, _ = tree.query(hv, k=2)
    min_d = float(d[:, 1].min())

    log.info("  coincident heavy pairs (<0.05 A): %d", n_coincident)
    log.info("  minimum heavy-atom distance     : %.4f A", min_d)

    ok = n_coincident == 0 and min_d > 0.05
    log.info("  GATE: %s", "PASS" if ok else "*** FAIL ***")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem", choices=VARIANTS, help="design stem to prep")
    args = ap.parse_args()
    stem = args.stem

    design_path = WORKSPACE / f"{stem}.nadoc"
    if not design_path.exists():
        log.error("design not found: %s", design_path)
        return 2
    if not ARCHIVE_ROOT.parent.exists():
        log.error("archive drive not mounted: %s", ARCHIVE_ROOT.parent)
        return 2

    design = Design.model_validate_json(design_path.read_text())

    job = new_job(
        design_name=stem,
        protocol=EQUILIBRIUM_AWARE_PROTOCOL,
        name_stem="",
        package_subdir="",
        design_source_path=f"{stem}.nadoc",
    )
    job.execution_target = "runpod"

    # MANDATORY, not an optimisation. Tier A (WC-gated) is the only tier that can skip the
    # low-restraint stages (k=0.01, MGHH k=0) — and those are half the ladder.
    job.early_stop_relax = True
    job.early_stop_tier = "A"

    # ARCHIVED FROM BIRTH. job_dir() returns archive_path, so prep, staging, fetch and the
    # production child all resolve to the archive HD, never the small system disk.
    job.archived = True
    job.archive_path = str(ARCHIVE_ROOT / job.job_id)
    Path(job.archive_path).mkdir(parents=True, exist_ok=True)

    # load()/list_jobs() find an archived job through the index, not by walking the
    # workspace. Without this entry the backend cannot see the job at all.
    idx = read_index(WORKSPACE, "md_jobs")
    idx[job.job_id] = job.archive_path
    _write_index(WORKSPACE, "md_jobs", idx)

    job.status = MdStatus.preparing
    job.save(WORKSPACE)
    (Path(__file__).parent / f"JOB_ID_{stem}").write_text(job.job_id + "\n")
    log.info("job %s  [%s]  ->  %s", job.job_id, stem, job.archive_path)

    t0 = time.time()
    try:
        package_subdir, name_stem, segments = prepare_equilibrium_aware_namd(
            design,
            job.job_dir(WORKSPACE),
            ion_conc_mM=ION_CONC_MM,
            mg_conc_mM=MG_CONC_MM,
            salt_mode=SALT_MODE,
            padding_nm=PADDING_NM,
            minimize_steps=MINIMIZE_STEPS,
            min_scale=MIN_SCALE,
            fast=FAST,
        )
    except Exception as exc:
        job.status = MdStatus.failed
        job.error = f"Preparation failed: {exc}"
        job.save(WORKSPACE)
        log.exception("PREP FAILED")
        return 1

    job.package_subdir = package_subdir
    job.name_stem = name_stem
    job.segments = [
        MdSegmentStatus(name=s.name, stage=s.stage, percent=s.percent,
                        steps=s.steps, status="pending")
        for s in segments
    ]
    job.status = MdStatus.queued
    job.save(WORKSPACE)
    log.info("prep done in %.1f min", (time.time() - t0) / 60)

    pkg = job.package_dir(WORKSPACE)

    # HMR: 3x heavier hydrogens let the 4 fs timestep be stable.
    src_psf = pkg / f"{name_stem}.psf"
    hmr_psf = pkg / f"{name_stem}_hmr.psf"
    n_hmr = write_hmr_psf(src_psf, hmr_psf)
    log.info("HMR PSF: %s (%d hydrogens repartitioned)", hmr_psf.name, n_hmr)

    manifest = json.loads((pkg / "manifest.json").read_text())
    log.info("min_name : %s", manifest["minimization"]["name"])
    log.info("segments : %d", len(job.segments))
    for s in job.segments:
        log.info("   %-44s %9d steps", s.name, s.steps)

    if not sanity_gate(pkg, name_stem):
        log.error("PACKAGE IS DEGENERATE — refusing to run. Do not spend money on this.")
        job.status = MdStatus.failed
        job.error = "Degenerate package: coincident heavy atoms"
        job.save(WORKSPACE)
        return 1

    log.info("PACKAGE OK. %s job_id=%s", stem, job.job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
