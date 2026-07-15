#!/usr/bin/env python3
"""Prep a 24hb variant with crossover extra bases SEEDED from an oxDNA relax.

The geometric arc-midpoint guess stacks neighbouring extra-base sugars (159 clash pairs on
24hb_1xT), which the declash minimiser relieves by stretching a C4'-C5' bond to ~3.1 A ->
fatal to a 4 fs timestep. Seeding from an oxDNA relaxation places them at their declashed
positions (0 clashes) so 4 fs is stable. See backend/core/oxdna_seed.py.

    python experiments/exp43_runpod_bench/prep_24hb_seeded.py 24hb_1xT <oxdna_job_dir>

For a 0xT design (no extra bases) the oxdna arg is ignored/optional (nothing to seed).
"""
from __future__ import annotations
import argparse, json, logging, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from backend.core.job_archive import read_index, _write_index
from backend.core.md_job import MdSegmentStatus, MdStatus, new_job
from backend.core.md_protocols import (EQUILIBRIUM_AWARE_PROTOCOL,
                                        prepare_equilibrium_aware_namd, write_hmr_psf)
from backend.core.models import Design
from backend.core.namd_topology import extra_base_segid_resids
from backend.core.oxdna_seed import build_ideal_duplex_seeded_model

WORKSPACE = ROOT / "workspace"
ARCHIVE_ROOT = Path("/media/jojo/Archive/nadoc_jobs")
MG_CONC_MM, SALT_MODE, PADDING_NM = 12.5, "screening", 1.2
MINIMIZE_STEPS, MIN_SCALE, FAST = 4800, 0.5, True
# Mass scale-up for the dangling ss extra bases in the 4 fs PSF (slows their fast modes
# below the 4 fs limit; equilibrium-exact). Locally-evidenced at x8; tune on the ladder.
HEAVY_XB_FACTOR = 8.0
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prep")


def make_soft_confs_mass_consistent(pkg: Path, stem: str) -> int:
    """Point the SOFT ladder segment (rigidBonds none + dynamics `run`) at the heavy-HMR
    PSF, so the dangling extra-base masses are CONSISTENT across the soft->4fs boundary.

    Without this, the soft stage runs the extra bases at PHYSICAL mass and the first 4 fs
    stage reads those physical-mass velocities into the 8x-heavier atoms -> 8x kinetic
    energy -> instant "atoms moving too fast".  The soft segment only reads the minimiser's
    ~0 velocities (mass-independent) and heats to 300 K under Langevin, so running it with
    the heavy-HMR masses is correct and seamless.  Minimise confs keep the base PSF (their
    velocities are ~0; no hot hand-off).  Returns the number of confs patched."""
    import re
    n = 0
    for c in pkg.glob(f"{stem}_0[1-9]*.conf"):
        txt = c.read_text()
        if re.search(r"^rigidBonds\s+none", txt, re.M) and re.search(r"^run\s+\d+", txt, re.M):
            new = re.sub(rf"^(structure\s+){re.escape(stem)}\.psf",
                         rf"\g<1>{stem}_hmr.psf", txt, flags=re.M)
            if new != txt:
                c.write_text(new)
                n += 1
    return n


def add_margin_to_confs(pkg: Path, stem: str, margin: float = 3.0) -> int:
    """Insert ``margin <N>`` into every ladder conf that lacks it.

    ``margin`` is patch-size slack that RAISES NAMD's per-atom velocity ceiling; it lets a
    fast-but-not-exploding atom through WITHOUT changing physical results (it affects only
    patch/pairlist sizing, never forces).  On the 2026-07-15 24hb ladder a single TIP3 WATER
    hydrogen — kicked by a local contact, not the extra bases — tripped the default (margin 0)
    ceiling at 1.76x in the k0.1 4 fs stage and killed the run.  A modest margin tolerates such
    marginal solvent trips.  Returns the number of confs patched.  See NAMD_4FS_RATTLE_RESEARCH.md."""
    import re
    n = 0
    for c in pkg.glob(f"{stem}_0[0-9]*.conf"):
        txt = c.read_text()
        if re.search(r"^\s*margin\s", txt, re.M):
            continue
        new = re.sub(r"^(pairlistdist\s+\S+)$", rf"\1\nmargin             {margin:g}",
                     txt, count=1, flags=re.M)
        if new != txt:
            c.write_text(new)
            n += 1
    return n


def sanity_gate(pkg: Path, stem: str) -> bool:
    import numpy as np
    from scipy.spatial import cKDTree
    xyz, heavy = [], []
    for line in (pkg / f"{stem}.pdb").open():
        if line.startswith(("ATOM", "HETATM")):
            xyz.append((float(line[30:38]), float(line[38:46]), float(line[46:54])))
            el = line[76:78].strip() or line[12:16].strip().lstrip("0123456789")[:1]
            heavy.append(el.upper() != "H")
    xyz = np.asarray(xyz); hv = xyz[np.asarray(heavy, bool)]
    tree = cKDTree(hv)
    n_coincident = len(tree.query_pairs(r=0.05, output_type="ndarray"))
    min_d = float(tree.query(hv, k=2)[0][:, 1].min())
    log.info("gate: %d atoms, %d coincident <0.05A, min heavy dist %.4f A",
             len(xyz), n_coincident, min_d)
    return n_coincident == 0 and min_d > 0.05


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stem")
    ap.add_argument("oxdna_job", nargs="?", help="oxDNA relax JOB ID (for seeding)")
    ap.add_argument("--padding", type=float, default=1.2, help="water padding nm")
    args = ap.parse_args()
    stem = args.stem
    design = Design.model_validate_json((WORKSPACE / f"{stem}.nadoc").read_text())

    seed_model = None
    n_xb = sum(1 for x in design.crossovers if x.extra_bases)
    if n_xb and args.oxdna_job:
        oj = WORKSPACE / "oxdna_jobs" / args.oxdna_job
        conf = next((c for c in (oj/"1_production"/"last_conf.dat", oj/"3_equil"/"last_conf.dat",
                                 oj/"conf.dat") if c.exists()), None)
        ref = oj / "design_ref.dat"
        if conf is None or not ref.exists():
            log.error("no usable oxDNA conf/design_ref under %s", oj); return 2
        log.info("SEEDING extra bases (IDEAL duplex + oxDNA positions) from %s", conf)
        seed_model = build_ideal_duplex_seeded_model(design, str(conf), str(ref))
        log.info("seed atoms=%d (ideal duplex, extra bases declashed, reoriented)", len(seed_model.atoms))
    elif n_xb:
        log.warning("%d extra bases but NO oxDNA job -> geometric guess (will clash at 4fs)", n_xb)

    job = new_job(design_name=stem, protocol=EQUILIBRIUM_AWARE_PROTOCOL,
                  name_stem="", package_subdir="", design_source_path=f"{stem}.nadoc")
    job.execution_target = "runpod"
    job.early_stop_relax = True; job.early_stop_tier = "A"
    job.archived = True; job.archive_path = str(ARCHIVE_ROOT / job.job_id)
    Path(job.archive_path).mkdir(parents=True, exist_ok=True)
    idx = read_index(WORKSPACE, "md_jobs"); idx[job.job_id] = job.archive_path
    _write_index(WORKSPACE, "md_jobs", idx)
    job.status = MdStatus.preparing; job.save(WORKSPACE)
    (Path(__file__).parent / f"JOB_ID_{stem}_seeded").write_text(job.job_id + "\n")
    log.info("job %s [%s] seeded=%s -> %s", job.job_id, stem, seed_model is not None, job.archive_path)

    t0 = time.time()
    try:
        # A SEEDED extra-base design starts from oxDNA-relaxed, geometrically clean
        # extra bases (the seed-builder phosphate fix: 0 catastrophic intra-residue
        # stretches; residual crossover-junction stretches are BELOW the 4 fs-proven
        # 0xT control, which has 384 such junctions and runs 4 fs fine).  So it takes
        # the FAST 4 fs ladder + 4 fs production (pre_declashed=True), exactly like
        # 0xT — NOT the soft 1 fs declash path, which forces 1 fs PRODUCTION and is
        # only needed for an UN-seeded, still-clashed geometric build.  (The old NOTE
        # here predated the seed fix, when the seed itself carried ~6 A stretches.)
        _pre_declashed = seed_model is not None
        package_subdir, name_stem, segments = prepare_equilibrium_aware_namd(
            design, job.job_dir(WORKSPACE), ion_conc_mM=0.0, mg_conc_mM=MG_CONC_MM,
            salt_mode=SALT_MODE, padding_nm=args.padding, minimize_steps=MINIMIZE_STEPS,
            min_scale=MIN_SCALE, fast=FAST, pre_declashed=_pre_declashed,
            atomistic_model=seed_model)
    except Exception as exc:
        job.status = MdStatus.failed; job.error = f"Prep failed: {exc}"; job.save(WORKSPACE)
        log.exception("PREP FAILED"); return 1

    job.package_subdir = package_subdir; job.name_stem = name_stem
    job.segments = [MdSegmentStatus(name=s.name, stage=s.stage, percent=s.percent,
                                    steps=s.steps, status="pending") for s in segments]
    job.status = MdStatus.queued; job.save(WORKSPACE)
    log.info("prep done in %.1f min", (time.time() - t0) / 60)
    pkg = job.package_dir(WORKSPACE)
    # The dangling ss extra bases are made HEAVY (not HMR-lightened) in the fast/4 fs PSF:
    # even with a clean seed their fast heavy-atom torsional modes blow a 4 fs step at
    # step 0, and HMR lightening makes it worse.  Scaling their mass up slows those modes
    # below the 4 fs limit and is thermodynamically FREE (equilibrium fluctuations — the
    # inter-helix stiffness we measure — are mass-independent).  0xT has no extra bases →
    # no heavy set.  See NAMD_4FS_RATTLE_RESEARCH.md; tune HEAVY_XB_FACTOR on the ladder.
    heavy_xb = (extra_base_segid_resids(seed_model, pkg / f"{name_stem}.psf")
                if seed_model is not None else None)
    n = write_hmr_psf(pkg / f"{name_stem}.psf", pkg / f"{name_stem}_hmr.psf",
                      heavy_residues=heavy_xb, heavy_factor=HEAVY_XB_FACTOR)
    log.info("HMR PSF: %d H repartitioned; %d extra-base residues made heavy (x%g)",
             n, len(heavy_xb or ()), HEAVY_XB_FACTOR)
    if heavy_xb:
        n_soft = make_soft_confs_mass_consistent(pkg, name_stem)
        log.info("patched %d soft conf(s) to the heavy-HMR PSF (consistent masses soft->4fs)",
                 n_soft)
    n_margin = add_margin_to_confs(pkg, name_stem)
    log.info("added `margin` to %d conf(s) (velocity-ceiling headroom for marginal solvent trips)",
             n_margin)
    if not sanity_gate(pkg, name_stem):
        job.status = MdStatus.failed; job.error = "Degenerate package"; job.save(WORKSPACE)
        log.error("GATE FAILED"); return 1
    log.info("PACKAGE OK. %s job_id=%s seeded=%s", stem, job.job_id, seed_model is not None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
