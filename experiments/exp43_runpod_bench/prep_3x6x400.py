#!/usr/bin/env python3
"""STEP 1 — build the 3x6x400 NAMD package, straight onto the archive drive.

Prep is CPU work (psfgen → GROMACS solvate → ENM ladder confs → HMR PSF). It is FREE.
Never do it on a rented GPU.

The job is created ALREADY ARCHIVED: ``archived=True`` + ``archive_path`` on the archive
HD, so ``job_dir()`` points there from the very first byte and nothing — not the 1.9M-atom
solvated package, not the overnight trajectory — ever touches the 20 GB system disk.

Ends with the VoltronCore gate: a package with coincident heavy atoms is degenerate
(infinite VDW → NaN) and NAMD will not tell you why, hours later, on a billing pod.

    python experiments/exp43_runpod_bench/prep_3x6x400.py
"""

from __future__ import annotations

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
DESIGN_PATH = WORKSPACE / "3x6x400_test.nadoc"
DESIGN_SOURCE = "3x6x400_test.nadoc"

ARCHIVE_ROOT = Path("/media/jojo/Archive/nadoc_jobs")

# From the brief. salt_mode="screening" + 12.5 mM Mg; 4800-step minimisation is the REAL
# one (240 leaves build clashes in and dynamics blows up at step 1).
ION_CONC_MM = 0.0
MG_CONC_MM = 12.5
SALT_MODE = "screening"
PADDING_NM = 1.2
MINIMIZE_STEPS = 4800
MIN_SCALE = 0.5

JOB_ID_FILE = Path(__file__).parent / "JOB_ID_3x6x400"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prep")


def sanity_gate(pkg: Path, stem: str) -> bool:
    """The VoltronCore gate. ANY coincident heavy-atom pair is fatal — infinite VDW.

    Job f702f4a3282f shipped a package with 279 atoms at 0.000 A and 634k real clashes;
    NAMD died with an uninterpretable NaN after hours. The DESIGN was fine — the PACKAGE
    was degenerate. This runs before a single cent is spent.
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
                # Column 77-78 is the element; fall back to the atom name's first
                # non-digit char for PDBs that leave it blank.
                el = line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]
                heavy.append(el.upper() != "H")

    xyz = np.asarray(xyz, dtype=np.float64)
    heavy = np.asarray(heavy, dtype=bool)
    hv = xyz[heavy]
    log.info("  %d atoms total, %d heavy", len(xyz), len(hv))

    tree = cKDTree(hv)
    # Every heavy pair closer than 0.05 A. A self-match is distance 0 and is excluded by
    # taking only pairs (i<j).
    pairs = tree.query_pairs(r=0.05, output_type="ndarray")
    n_coincident = len(pairs)

    # Nearest non-self neighbour distance for the whole set.
    d, _ = tree.query(hv, k=2)
    min_d = float(d[:, 1].min())

    log.info("  coincident heavy pairs (<0.05 A): %d", n_coincident)
    log.info("  minimum heavy-atom distance     : %.4f A", min_d)

    ok = n_coincident == 0 and min_d > 0.05
    log.info("  GATE: %s", "PASS" if ok else "*** FAIL ***")
    return ok


def main() -> int:
    if not DESIGN_PATH.exists():
        log.error("design not found: %s", DESIGN_PATH)
        return 2
    if not ARCHIVE_ROOT.parent.exists():
        log.error("archive drive not mounted: %s", ARCHIVE_ROOT.parent)
        return 2

    design = Design.model_validate_json(DESIGN_PATH.read_text())

    job = new_job(
        design_name="3x6x400_test",
        protocol=EQUILIBRIUM_AWARE_PROTOCOL,
        name_stem="",
        package_subdir="",
        design_source_path=DESIGN_SOURCE,
    )
    job.execution_target = "runpod"

    # ARCHIVED FROM BIRTH. job_dir() returns archive_path, so prep, staging, fetch and the
    # production child all resolve to the archive HD. The system disk has 20 GB free; a
    # 1.9M-atom production run would fill it overnight.
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
    JOB_ID_FILE.write_text(job.job_id + "\n")
    log.info("job %s  ->  %s", job.job_id, job.archive_path)

    log.info(
        "preparing: psfgen full topology -> GROMACS solvate (%.1f nm pad, %g mM Mg, "
        "salt_mode=%s) -> ENM ladder, minimize=%d steps. Takes a few minutes.",
        PADDING_NM, MG_CONC_MM, SALT_MODE, MINIMIZE_STEPS,
    )
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

    # HMR: 3x heavier hydrogens let the 4 fs timestep be stable. Worth 2x on its own and
    # it composes with GPU-resident.
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

    log.info("PACKAGE OK. job_id=%s", job.job_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
