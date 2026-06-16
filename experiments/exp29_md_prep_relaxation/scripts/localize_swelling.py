#!/usr/bin/env python3
"""Localize where the ENM-release melt nucleates: junction-local vs global.

Cycle-3 follow-up. The k=0 melt is build-side; this decides which build-side
hypothesis to chase by asking *which C1' pairs grow* when the restraint steps
down. Global-uniform growth => electrostatic (charge); growth concentrated near
the inserted ss bases / forced ligation => mechanical strain or topological lock.

Target: 6hb_2xT declash job 03302b74a7fa, which held stably through k=0.5
(stage01 p100) then nucleated the melt at the k=0.5->0.1 step-down (stage02 p10).
Comparing those two frames isolates the nucleation, not the end-state rubble.

Reuses md_health.build_c1_pairs so the pairing is byte-identical to the gate.
Distances use minimum-image (defensive vs PBC wrap).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import MDAnalysis as mda

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from backend.core.md_health import build_c1_pairs  # noqa: E402
from backend.core.md_protocols import identify_unpaired_residues  # noqa: E402

# ── targets ──────────────────────────────────────────────────────────────────
# 6hb: melt NUCLEATION — held stable through k=0.5, first loosening at k=0.5→0.1.
# 2hb: full COLLAPSE cross-check — intact at k=0.1 (C1'=93) → melted at k=0 (17%).
_6HB = REPO / "workspace/md_jobs/03302b74a7fa/package/6hb_2xT_namd_solvated"
_2HB = (REPO / "experiments/exp29_md_prep_relaxation/runs/final_taper/package"
        / "2hb_noT_namd_solvated")
TARGETS = {
    "6hb": dict(
        stem="6hb_2xT", job=_6HB,
        stable="output/6hb_2xT_01_300K_NPT_ENM_k0p5_p100.dcd",  # k=0.5 plateau
        melt="output/6hb_2xT_02_300K_NPT_ENM_k0p1_p10.dcd",  # k=0.1 nucleation
        stable_lbl="k0.5plateau", melt_lbl="k0.1",
    ),
    "2hb": dict(
        stem="2hb_noT", job=_2HB,
        stable="output/2hb_noT_s01_k0p1.dcd",  # k=0.1, still intact (C1'=93)
        melt="output/2hb_noT_s08_k0.dcd",  # k=0, full collapse (C1'=17)
        stable_lbl="k0.1intact", melt_lbl="k0melt",
    ),
}
TARGET = sys.argv[1] if len(sys.argv) > 1 else "6hb"
_T = TARGETS[TARGET]
JOB = _T["job"]
PSF = JOB / f"{_T['stem']}.psf"
REF_PDB = JOB / f"{_T['stem']}.pdb"  # declashed reference (post-min rebuild)
STABLE_DCD = JOB / _T["stable"]
MELT_DCD = JOB / _T["melt"]
SLBL, MLBL = _T["stable_lbl"], _T["melt_lbl"]


def _mic_dist(a: np.ndarray, b: np.ndarray, box: np.ndarray | None) -> np.ndarray:
    d = a - b
    if box is not None:
        L = box[:3]
        d -= L * np.round(d / L)
    return np.linalg.norm(d, axis=-1)


def _mean_pair_dist(dcd: Path, psf: Path, c1_idx: np.ndarray, pi, pj):
    """Per-pair C1'-C1' distance averaged over ALL frames (denoise thermal).

    Averages the scalar distance (rotation/translation invariant), not Cartesian
    positions, so molecular tumbling across frames does not corrupt the mean.
    """
    u = mda.Universe(str(psf), str(dcd))
    acc = np.zeros(len(pi))
    nfr = 0
    for _ in u.trajectory:
        box = u.dimensions[:3].copy() if u.dimensions is not None else None
        pos = u.atoms.positions[c1_idx]
        acc += _mic_dist(pos[pi], pos[pj], box)
        nfr += 1
    return acc / max(nfr, 1), nfr


def main() -> int:
    pairs = build_c1_pairs(PSF, REF_PDB)
    # Recover the C1' atom selection (same order build_c1_pairs used internally).
    u_ref = mda.Universe(str(PSF), str(REF_PDB))
    c1_sel = u_ref.select_atoms("name C1'")
    c1_idx = c1_sel.indices
    ref_pos = c1_sel.positions.copy()
    refbox = u_ref.dimensions[:3].copy() if u_ref.dimensions is not None else None

    pi, pj, d0 = pairs.pi, pairs.pj, pairs.d0
    n_pairs = len(pi)

    # --- junction markers: the AUTHORITATIVE ss set the declash protocol excludes
    # (identify_unpaired_residues, 10.8 Å no-partner threshold) = the actual
    # inserted 2xT bases + forced-ligation termini, the real strain sources.
    ss = identify_unpaired_residues(PSF, REF_PDB)  # set of (segid_lastchar, resid_str)
    seg_last = np.array([s[-1] for s in c1_sel.segids])
    resids = c1_sel.resids.astype(int)
    is_junction = np.array(
        [(seg_last[k], str(resids[k])) in ss for k in range(len(c1_idx))]
    )
    junction_pos = ref_pos[is_junction] if is_junction.any() else np.empty((0, 3))
    print(f"# ss markers (identify_unpaired_residues): {len(ss)} residues, "
          f"{int(is_junction.sum())} matched to C1' atoms")

    # per-pair midpoint (reference) and distance to nearest junction marker
    midpts = 0.5 * (ref_pos[pi] + ref_pos[pj])
    if len(junction_pos):
        dist_to_junction = np.array(
            [_mic_dist(m[None, :], junction_pos, refbox).min() for m in midpts]
        )
    else:
        dist_to_junction = np.full(n_pairs, np.nan)

    # --- per-pair C1'-C1' distance, frame-averaged over each stage --------------
    d_stable, n_s = _mean_pair_dist(STABLE_DCD, PSF, c1_idx, pi, pj)  # k=0.5 plateau
    d_melt, n_m = _mean_pair_dist(MELT_DCD, PSF, c1_idx, pi, pj)  # k=0.1 nucleation

    growth = d_melt - d_stable  # the nucleation step: k0.5 plateau -> k0.1
    growth_vs_ref = d_melt - d0

    print(f"# TARGET={TARGET}  n_C1_pairs={n_pairs}  "
          f"n_junction_markers={int(is_junction.sum())}")
    print(f"# frames averaged: {SLBL}={n_s}  {MLBL}={n_m}")
    print(f"# mean C1' dist:  ref={d0.mean():.2f}  {SLBL}={d_stable.mean():.2f}  "
          f"{MLBL}={d_melt.mean():.2f} Å")
    print(f"# paired<12Å frac: {SLBL}={(d_stable<12).mean()*100:.1f}%  "
          f"{MLBL}={(d_melt<12).mean()*100:.1f}%")
    print()

    # --- the decisive test: growth vs distance-to-junction -----------------------
    finite = np.isfinite(dist_to_junction)
    order = np.argsort(dist_to_junction[finite])
    djx = dist_to_junction[finite][order]
    grx = growth[finite][order]

    # bin into near / mid / far thirds by distance-to-junction
    thirds = np.array_split(np.arange(len(djx)), 3)
    print(f"# growth ({SLBL} -> {MLBL}) binned by distance-to-junction:")
    labels = ["NEAR", "MID ", "FAR "]
    for lab, idx in zip(labels, thirds):
        if len(idx) == 0:
            continue
        print(f"#   {lab}  d_junc∈[{djx[idx].min():5.1f},{djx[idx].max():5.1f}]Å  "
              f"n={len(idx):3d}  mean_growth={grx[idx].mean():+5.2f}Å  "
              f"median={np.median(grx[idx]):+5.2f}Å  "
              f"frac_broke(>+1Å)={(grx[idx]>1.0).mean()*100:4.0f}%")
    print()

    # correlation
    if len(djx) > 3:
        r = np.corrcoef(djx, grx)[0, 1]
        print(f"# Pearson r(dist_to_junction, growth) = {r:+.3f}")
        print("#   r<<0  => near-junction pairs grow most  => MECHANICAL/TOPOLOGICAL")
        print("#   r~=0  => growth independent of junction  => GLOBAL/ELECTROSTATIC")
    print()

    # top-10 most-grown pairs and their junction distance
    top = np.argsort(growth)[::-1][:10]
    print("# top-10 most-grown pairs:  pair(resids)  d0  d_k0.1  growth  d_junc")
    for k in top:
        ai, aj = c1_sel[pi[k]], c1_sel[pj[k]]
        print(f"#   {ai.resname}{ai.resid}/{ai.segid}-{aj.resname}{aj.resid}/{aj.segid}"
              f"  d0={d0[k]:5.2f}  d={d_melt[k]:5.2f}  +{growth[k]:4.2f}  "
              f"djunc={dist_to_junction[k]:5.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
