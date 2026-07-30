#!/usr/bin/env python3
"""What did the vacuum ENRG-MD step actually change?

Answers the two questions the vacuum step has to earn its place with:

  1. Did global SHAPE move?  (RMSD after optimal superposition, radius of gyration,
     and r_max / bbox span — the two quantities that set the solvation box, and hence
     the atom count and hence the wall-clock of everything downstream.)
  2. Did LOCAL structure survive?  (Watson-Crick N1-N3 distances across the duplex.)

A vacuum step that moves shape while keeping base pairs is doing its job. One that
moves nothing has nothing to do on this design — which is a fact about the design, not
a failure of the method, and is the expected result for a 2-helix structure.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

#: CHARMM base-ring atoms that carry the Watson-Crick hydrogen bonds.
_WC_ATOM = {"ADE": "N1", "THY": "N3", "GUA": "N1", "CYT": "N3"}
_WC_PARTNER = {"ADE": "THY", "THY": "ADE", "GUA": "CYT", "CYT": "GUA"}
#: A WC N1-N3 pair sits at ~2.8-3.0 A; beyond this the pair has opened.
WC_BROKEN_ANG = 4.0
#: Neighbour search radius when re-identifying pairs geometrically.
WC_SEARCH_ANG = 5.0


def _kabsch_rmsd(a: np.ndarray, b: np.ndarray) -> float:
    """RMSD after optimal rigid superposition — pure shape change, no drift/rotation."""
    a = a - a.mean(axis=0)
    b = b - b.mean(axis=0)
    v, _s, w = np.linalg.svd(a.T @ b)
    d = np.sign(np.linalg.det(v @ w))
    r = v @ np.diag([1.0, 1.0, d]) @ w
    return float(np.sqrt(((a @ r - b) ** 2).sum(axis=1).mean()))


def _shape(pos: np.ndarray) -> dict:
    c = pos.mean(axis=0)
    rel = pos - c
    r = np.linalg.norm(rel, axis=1)
    span = pos.max(axis=0) - pos.min(axis=0)
    return {
        "n_atoms": int(len(pos)),
        "rgyr_ang": float(np.sqrt((r ** 2).mean())),
        "r_max_ang": float(r.max()),
        "bbox_span_ang": [float(x) for x in span],
    }


def _box_atoms(shape: dict, padding_nm: float, n_dna: int) -> dict:
    """Solvated atom count implied by this shape, for both box modes."""
    from backend.core.namd_solvate import estimate_box_atoms

    pad = padding_nm * 10.0
    rot_nm = (2 * shape["r_max_ang"] + 2 * pad) / 10.0
    bb = [(s + 2 * pad) / 10.0 for s in shape["bbox_span_ang"]]
    return {
        "rotation": int(estimate_box_atoms((rot_nm, rot_nm, rot_nm), n_dna)),
        "bbox": int(estimate_box_atoms(tuple(bb), n_dna)),
    }


def _wc_distances(positions: np.ndarray, pairs) -> np.ndarray:
    """N1-N3 distances for a TOPOLOGY-derived pair list, in one frame.

    Geometric pair-finding is not usable here: on an idealised build the geometry is
    perfectly regular, so cutoff matching over-counts (picks up cross-strand neighbours)
    and mutual-nearest under-counts (ties). The design already knows which nucleotides
    are paired — use that, and the same pair list for every frame so the comparison is
    like-for-like.
    """
    if not pairs:
        return np.empty(0)
    idx = np.asarray(pairs, dtype=np.int64)
    return np.linalg.norm(positions[idx[:, 0]] - positions[idx[:, 1]], axis=1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--padding-nm", type=float, default=1.2,
                    help="solvation padding used to project box sizes (Standard = 1.2)")
    args = ap.parse_args()

    import MDAnalysis as mda

    info = json.loads((args.run_dir / "build_info.json").read_text())
    stem = info["stem"]
    psf = args.run_dir / f"{stem}.psf"
    pdb = args.run_dir / f"{stem}.pdb"
    dcd = args.run_dir / "output" / f"{stem}.dcd"
    if not dcd.exists():
        print(f"no trajectory yet at {dcd}", file=sys.stderr)
        return 1

    from build_vacuum import load_design
    from push_bonds import watson_crick_pairs

    design = load_design(Path(info["design"]))
    wc_pairs = watson_crick_pairs(design, pdb.read_text())

    u0 = mda.Universe(str(psf), str(pdb))
    u = mda.Universe(str(psf), str(dcd))
    heavy = "not name H*"
    s0 = u0.select_atoms(heavy)
    s1 = u.select_atoms(heavy)

    start = s0.positions.copy()
    all_start = u0.atoms.positions.copy()
    u.trajectory[-1]
    end = s1.positions.copy()
    all_end = u.atoms.positions.copy()

    sh0, sh1 = _shape(start), _shape(end)
    n_dna = info["n_atoms"]
    b0 = _box_atoms(sh0, args.padding_nm, n_dna)
    b1 = _box_atoms(sh1, args.padding_nm, n_dna)

    wc0 = _wc_distances(all_start, wc_pairs)
    wc1 = _wc_distances(all_end, wc_pairs)

    rmsd = _kabsch_rmsd(start, end)

    print(f"=== vacuum ENRG-MD: {stem} ===")
    print(f"frames {len(u.trajectory)}   heavy atoms {len(s0)}   "
          f"{info['ns']:g} ns @ ENM k={info['enm_k']}, {info['n_push_bonds']} push bonds")
    print()
    print(f"SHAPE   RMSD (superposed)      {rmsd:8.2f} A")
    print(f"        radius of gyration     {sh0['rgyr_ang']:8.2f} -> {sh1['rgyr_ang']:8.2f} A"
          f"   ({100*(sh1['rgyr_ang']/sh0['rgyr_ang']-1):+.1f}%)")
    print(f"        r_max (sets rot. box)  {sh0['r_max_ang']:8.2f} -> {sh1['r_max_ang']:8.2f} A"
          f"   ({100*(sh1['r_max_ang']/sh0['r_max_ang']-1):+.1f}%)")
    print(f"        bbox span              "
          f"{'x'.join(f'{x:.0f}' for x in sh0['bbox_span_ang'])} -> "
          f"{'x'.join(f'{x:.0f}' for x in sh1['bbox_span_ang'])} A")
    print()
    print(f"SOLVATION COST at padding {args.padding_nm:g} nm (estimated atoms)")
    for mode in ("rotation", "bbox"):
        d = 100 * (b1[mode] / b0[mode] - 1) if b0[mode] else 0.0
        print(f"        {mode:<9s} {b0[mode]:>10,} -> {b1[mode]:>10,}   ({d:+.1f}%)")
    print()
    if len(wc0) and len(wc1):
        print(f"BASE PAIRS  {len(wc0)} pairs, from design topology (same list both frames)")
        print(f"        N1-N3 mean            {wc0.mean():8.2f} -> {wc1.mean():8.2f} A")
        print(f"        broken (> {WC_BROKEN_ANG:g} A)      "
              f"{int((wc0 > WC_BROKEN_ANG).sum()):8d} -> {int((wc1 > WC_BROKEN_ANG).sum()):8d}"
              f"   ({100 * (wc1 > WC_BROKEN_ANG).mean():.1f}% at the end)")
    else:
        print("BASE PAIRS  no pairs resolved")

    (args.run_dir / "vacuum_analysis.json").write_text(json.dumps({
        "stem": stem, "rmsd_ang": rmsd, "shape_start": sh0, "shape_end": sh1,
        "box_atoms_start": b0, "box_atoms_end": b1,
        "wc_pairs_start": int(len(wc0)), "wc_pairs_end": int(len(wc1)),
        "wc_broken_start": int((wc0 > WC_BROKEN_ANG).sum()) if len(wc0) else None,
        "wc_broken_end": int((wc1 > WC_BROKEN_ANG).sum()) if len(wc1) else None,
        "padding_nm": args.padding_nm,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
