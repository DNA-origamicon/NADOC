#!/usr/bin/env python3
"""MD A/B: does repairing the catenated seed survive a real NAMD relaxation ladder?

Two arms per design, everything else identical:

  fixed      — the repaired build (current default): reciprocal crossover pairs unlinked
  catenated  — the repair switched off, so the seed ships entangled (Lk = +/-1).
               Requires allow_catenated_seed=True; this is the whole point of that flag.

The question the arms answer is NOT "does it run" — the catenated 2hb job ran fine at
99.8 ns/day and reported c1_paired_fraction = 1.0.  It is whether the entanglement is
still there at the end, measured directly:

  * Lk per reciprocal pair, at the seed and after EVERY completed segment;
  * the standard C1'/WC health the runner already records.

A linking number cannot change under continuous deformation, so the expected result is
Lk pinned at +/-1 for the whole catenated arm and 0 for the whole fixed arm.  Anything
else is informative: Lk changing mid-run would mean a strand passed through another.

    python experiments/exp45_extra_base_catenation/run_ab.py            # all four arms
    python experiments/exp45_extra_base_catenation/run_ab.py --designs 2hb_1xT
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

from backend.core import namd_runner
from backend.core.atomistic import build_atomistic_model
from backend.core.job_archive import _write_index, read_index
from backend.core.junction_topology import (
    catenation_in_frame, catenation_report, package_connector_rows, read_namd_coor,
)
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job
from backend.core.md_protocols import (
    EQUILIBRIUM_AWARE_PROTOCOL, prepare_equilibrium_aware_namd, write_hmr_psf,
)
from backend.core.models import Design
from backend.core.namd_topology import extra_base_segid_resids

WORKSPACE = ROOT / "workspace"
ARCHIVE_ROOT = Path("/media/jojo/Archive/NADOC_archive")
HERE = Path(__file__).resolve().parent

MG_CONC_MM, SALT_MODE, PADDING_NM = 12.5, "screening", 1.2
MINIMIZE_STEPS, MIN_SCALE, FAST = 4800, 0.5, True
HEAVY_XB_FACTOR = 8.0          # Fix B — see memory/project_extra_base_4fs_geometric_fixb.md

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ab")


class repair_disabled:
    """Reproduce the pre-fix builder: joint solve, no catenation repair."""

    def __enter__(self):
        import backend.core.atomistic as _a
        import backend.core.atomistic_minimisers as _m
        self._orig = _a._repair_catenated_pairs
        _a._repair_catenated_pairs = lambda *a, **k: {
            "n_pairs": 0, "n_repaired": 0, "n_unrepaired": 0, "repairs": []}
        _m._XB_CACHE.clear()
        return self

    def __exit__(self, *exc):
        import backend.core.atomistic as _a
        import backend.core.atomistic_minimisers as _m
        _a._repair_catenated_pairs = self._orig
        _m._XB_CACHE.clear()
        return False


def build_seed(design: Design, arm: str):
    if arm == "catenated":
        with repair_disabled():
            return build_atomistic_model(design, include_proteins=True)
    return build_atomistic_model(design, include_proteins=True)


def prep_arm(stem: str, arm: str) -> dict:
    design = Design.model_validate_json((WORKSPACE / f"{stem}.nadoc").read_text())
    seed_model = build_seed(design, arm)

    seed_report = catenation_report(design, model=seed_model)
    log.info("[%s/%s] seed: %d catenated of %d reciprocal pairs",
             stem, arm, seed_report["n_catenated"], seed_report["n_reciprocal_pairs"])

    job = new_job(design_name=f"{stem}_{arm}", protocol=EQUILIBRIUM_AWARE_PROTOCOL,
                  name_stem="", package_subdir="",
                  design_source_path=f"{stem}.nadoc")
    job.execution_target = "local"
    job.early_stop_relax = True
    job.early_stop_tier = "A"
    job.archived = True
    job.archive_path = str(ARCHIVE_ROOT / job.job_id)
    idx = read_index(WORKSPACE, "md_jobs")
    idx[job.job_id] = job.archive_path
    _write_index(WORKSPACE, "md_jobs", idx)      # MANDATORY: else the backend can't see it
    job.status = MdStatus.preparing
    job.save(WORKSPACE)

    package_subdir, name_stem, segments = prepare_equilibrium_aware_namd(
        design, job.job_dir(WORKSPACE),
        ion_conc_mM=0.0, mg_conc_mM=MG_CONC_MM, salt_mode=SALT_MODE,
        padding_nm=PADDING_NM, minimize_steps=MINIMIZE_STEPS, min_scale=MIN_SCALE,
        fast=FAST, atomistic_model=seed_model,
        allow_catenated_seed=(arm == "catenated"),
    )
    job.package_subdir, job.name_stem = package_subdir, name_stem
    job.segments = [MdSegmentStatus(name=s.name, stage=s.stage, percent=s.percent,
                                    steps=s.steps, status="pending") for s in segments]
    pkg = job.package_dir(WORKSPACE)

    # Fix B — the standard prep path calls write_hmr_psf WITHOUT heavy_residues, which
    # LIGHTENS the dangling extra bases' C5'/C5M and blows the 4 fs step.  Scale them up
    # instead (thermodynamically free: equilibrium fluctuations are mass-independent).
    heavy_xb = extra_base_segid_resids(seed_model, pkg / f"{name_stem}.psf")
    n_h = write_hmr_psf(pkg / f"{name_stem}.psf", pkg / f"{name_stem}_hmr.psf",
                        heavy_residues=heavy_xb, heavy_factor=HEAVY_XB_FACTOR)
    log.info("[%s/%s] Fix B: %d H repartitioned, %d extra-base residues heavy (x%g)",
             stem, arm, n_h, len(heavy_xb), HEAVY_XB_FACTOR)

    job.status = MdStatus.queued
    job.save(WORKSPACE)
    return {"job_id": job.job_id, "stem": stem, "arm": arm,
            "package_dir": str(pkg), "name_stem": name_stem,
            "seed_catenation": seed_report}


def _done_segments(job) -> int:
    return sum(1 for s in job.segments if s.status == "done")


def run_and_watch(job_id: str, timeout_s: float = 5400,
                  max_segments: int | None = None) -> str:
    """Run the job, then STOP it cleanly on the segment cap or the timeout.

    The cap matters for an unattended queue: the full ENM ladder is ~2 h for even a 2hb,
    and simply abandoning a job at a timeout would leave its NAMD running while the next
    arm starts a second one on the same GPU.  The question these arms answer — does the
    linking number stay put through relaxation — is settled by the stages that DID run,
    so a bounded arm is still a valid measurement.
    """
    job = MdJob.load(job_id, WORKSPACE)
    namd_runner.start_job(job, WORKSPACE)
    t0 = time.time()
    reason = "completed"
    while True:
        time.sleep(20)
        if not namd_runner.is_running(job_id):
            break
        cur = MdJob.load(job_id, WORKSPACE)
        if max_segments is not None and _done_segments(cur) >= max_segments:
            reason = f"segment cap ({max_segments})"
            break
        if time.time() - t0 > timeout_s:
            reason = f"timeout ({timeout_s:.0f}s)"
            break

    if namd_runner.is_running(job_id):
        log.info("[%s] stopping: %s", job_id, reason)
        try:
            namd_runner.stop_job(job_id, WORKSPACE)
        except Exception as exc:  # noqa: BLE001
            log.warning("stop_job failed: %s", exc)
        for _ in range(30):
            if not namd_runner.is_running(job_id):
                break
            time.sleep(2)

    job = MdJob.load(job_id, WORKSPACE)
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    log.info("[%s] %d/%d segments done (%s), status=%s",
             job_id, _done_segments(job), len(job.segments), reason, status)
    return status


def measure(entry: dict) -> dict:
    """Lk at the seed PDB and after every completed segment."""
    design = Design.model_validate_json(
        (WORKSPACE / f"{entry['stem']}.nadoc").read_text())
    pkg = Path(entry["package_dir"])
    stem = entry["name_stem"]
    conns = package_connector_rows(design, pkg / f"{stem}.pdb")

    import numpy as np

    def pdb_xyz(p):
        return np.array([(float(l[30:38]), float(l[38:46]), float(l[46:54]))
                         for l in Path(p).read_text().splitlines()
                         if l.startswith(("ATOM", "HETATM"))])

    frames = [("00_seed_pdb", pdb_xyz(pkg / f"{stem}.pdb"))]
    for coor in sorted((pkg / "output").glob("*.coor")):
        if ".restart" in coor.name:
            continue
        try:
            frames.append((coor.stem.replace(f"{stem}_", ""), read_namd_coor(coor)))
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read %s: %s", coor.name, exc)

    # Chronological, not alphabetical: "..._p100" sorts before "..._p50".
    def _order(name):
        pct = 0
        if name.endswith("_p10"): pct = 10
        elif name.endswith("_p50"): pct = 50
        elif name.endswith("_p100"): pct = 100
        return (name.split("_p")[0], pct)
    frames = [frames[0]] + sorted(frames[1:], key=lambda f: _order(f[0]))

    out = []
    reference = None
    for label, xyz in frames:
        rep = catenation_in_frame(conns, xyz, reference=reference)
        if reference is None:
            reference = rep["gauss_open"]      # the seed is the topology reference
        out.append({"frame": label, "n_catenated": rep["n_catenated"],
                    "lk": [c["lk_int"] for c in rep["catenated"]],
                    "g_open": rep["gauss_open"], "n_changed": rep["n_changed"]})
        log.info("[%s/%s] %-34s catenated=%d Lk=%s changed=%d",
                 entry["stem"], entry["arm"], label, rep["n_catenated"],
                 [c["lk_int"] for c in rep["catenated"]], rep["n_changed"])
    return {"n_connectors": len(conns), "frames": out}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--designs", nargs="+", default=["2hb_1xT", "2hb_2xT"])
    ap.add_argument("--arms", nargs="+", default=["fixed", "catenated"])
    ap.add_argument("--timeout-s", type=float, default=2700)
    ap.add_argument("--max-segments", type=int, default=None,
                    help="stop each arm cleanly after this many completed segments")
    ap.add_argument("--out", type=Path, default=HERE / "ab_results.json")
    args = ap.parse_args(argv)

    results = []
    for stem in args.designs:
        for arm in args.arms:
            log.info("=== %s / %s ===", stem, arm)
            try:
                entry = prep_arm(stem, arm)
            except Exception as exc:  # noqa: BLE001
                log.error("prep failed for %s/%s: %s: %s", stem, arm,
                          type(exc).__name__, exc)
                results.append({"stem": stem, "arm": arm, "error": str(exc)})
                args.out.write_text(json.dumps(results, indent=2))
                continue
            entry["final_status"] = run_and_watch(
                entry["job_id"], args.timeout_s, args.max_segments)
            log.info("[%s/%s] finished with status=%s", stem, arm, entry["final_status"])
            try:
                entry["catenation"] = measure(entry)
            except Exception as exc:  # noqa: BLE001
                log.error("measure failed: %s: %s", type(exc).__name__, exc)
                entry["catenation"] = {"error": str(exc)}
            results.append(entry)
            args.out.write_text(json.dumps(results, indent=2, default=str))

    args.out.write_text(json.dumps(results, indent=2, default=str))
    log.info("wrote %s", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
