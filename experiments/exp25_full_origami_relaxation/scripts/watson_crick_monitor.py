#!/usr/bin/env python3
"""Watson-Crick heavy-atom base-pair monitor for DNA-origami trajectories.

The monitor uses canonical donor/acceptor heavy-atom pairs as a hydrogen-bond
proxy, which is closer to published origami analysis than a C1' distance alone.
It reports the fraction of reference base pairs whose heavy-atom H-bond proxy
still satisfies a distance cutoff in the analysed frame.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


WC_ATOMS = {
    ("DA", "DT"): [("N1", "N3"), ("N6", "O4")],
    ("DT", "DA"): [("N3", "N1"), ("O4", "N6")],
    ("A", "T"): [("N1", "N3"), ("N6", "O4")],
    ("T", "A"): [("N3", "N1"), ("O4", "N6")],
    ("DG", "DC"): [("N1", "N3"), ("N2", "O2"), ("O6", "N4")],
    ("DC", "DG"): [("N3", "N1"), ("O2", "N2"), ("N4", "O6")],
    ("G", "C"): [("N1", "N3"), ("N2", "O2"), ("O6", "N4")],
    ("C", "G"): [("N3", "N1"), ("O2", "N2"), ("N4", "O6")],
}


def _c1p(u):
    sel = u.select_atoms("name C1'")
    if not len(sel):
        sel = u.select_atoms("name C1X")
    if not len(sel):
        raise RuntimeError("No C1' atoms found.")
    return sel


def _atom_index(residue, name: str) -> int | None:
    for atom in residue.atoms:
        if atom.name.strip() == name:
            return int(atom.index)
    return None


def _find_pairs(u, lo: float, hi: float):
    c1 = _c1p(u)
    pos = c1.positions
    tree = cKDTree(pos)
    used = np.zeros(len(pos), dtype=bool)
    pairs = []
    for i in range(len(pos)):
        if used[i]:
            continue
        cands = []
        for j in tree.query_ball_point(pos[i], hi):
            if j <= i or used[j] or c1[i].segid == c1[j].segid:
                continue
            d = float(np.linalg.norm(pos[i] - pos[j]))
            if d >= lo:
                cands.append((d, j))
        if not cands:
            continue
        d, j = min(cands)
        res_a = c1[i].residue
        res_b = c1[j].residue
        hbonds = WC_ATOMS.get((res_a.resname.strip(), res_b.resname.strip()), [])
        atom_pairs = []
        ref_distances = []
        for atom_a, atom_b in hbonds:
            ia = _atom_index(res_a, atom_a)
            ib = _atom_index(res_b, atom_b)
            if ia is not None and ib is not None:
                atom_pairs.append((ia, ib))
                ref_distances.append(float(np.linalg.norm(u.atoms[ia].position - u.atoms[ib].position)))
        if atom_pairs:
            used[i] = used[j] = True
            pairs.append({
                "res_a": f"{res_a.segid}:{res_a.resname}{res_a.resid}",
                "res_b": f"{res_b.segid}:{res_b.resname}{res_b.resid}",
                "atom_pairs": atom_pairs,
                "ref_distances": ref_distances,
                "c1_distance_ang": d,
            })
    return pairs


def _frame_metrics(u, pairs, cutoff_ang: float, ref_delta_ang: float):
    pos = u.atoms.positions
    box = u.trajectory.ts.dimensions
    L = box[:3] if box is not None and len(box) >= 3 and np.all(box[:3] > 0) else None
    pair_ok = []
    ref_relative_ok = []
    mean_hbond = []
    max_hbond = []
    ref_mean_hbond = []
    ref_max_hbond = []
    for pair in pairs:
        distances = []
        for ia, ib in pair["atom_pairs"]:
            diff = pos[ia] - pos[ib]
            if L is not None:
                diff -= L * np.round(diff / L)
            distances.append(float(np.sqrt((diff * diff).sum())))
        arr = np.asarray(distances)
        ref = np.asarray(pair["ref_distances"])
        pair_ok.append(bool(np.all(arr <= cutoff_ang)))
        ref_relative_ok.append(bool(np.all(arr <= ref + ref_delta_ang)))
        mean_hbond.append(float(arr.mean()))
        max_hbond.append(float(arr.max()))
        ref_mean_hbond.append(float(ref.mean()))
        ref_max_hbond.append(float(ref.max()))
    return {
        "absolute_paired_fraction": float(np.mean(pair_ok)) if pair_ok else 0.0,
        "absolute_paired_percent": float(np.mean(pair_ok) * 100.0) if pair_ok else 0.0,
        "ref_relative_paired_fraction": float(np.mean(ref_relative_ok)) if ref_relative_ok else 0.0,
        "ref_relative_paired_percent": float(np.mean(ref_relative_ok) * 100.0) if ref_relative_ok else 0.0,
        "mean_hbond_proxy_ang": float(np.mean(mean_hbond)) if mean_hbond else 0.0,
        "p90_max_hbond_proxy_ang": float(np.percentile(max_hbond, 90)) if max_hbond else 0.0,
        "max_hbond_proxy_ang": float(np.max(max_hbond)) if max_hbond else 0.0,
        "reference_mean_hbond_proxy_ang": float(np.mean(ref_mean_hbond)) if ref_mean_hbond else 0.0,
        "reference_p90_max_hbond_proxy_ang": float(np.percentile(ref_max_hbond, 90)) if ref_max_hbond else 0.0,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psf", type=Path, required=True)
    ap.add_argument("--ref-pdb", type=Path, required=True)
    ap.add_argument("--dcd", type=Path, default=None)
    ap.add_argument("--frame", type=int, default=-1)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cutoff-ang", type=float, default=3.6)
    ap.add_argument("--ref-delta-ang", type=float, default=0.75)
    ap.add_argument("--c1-lo-ang", type=float, default=8.5)
    ap.add_argument("--c1-hi-ang", type=float, default=13.0)
    args = ap.parse_args()

    import MDAnalysis as mda

    ref = mda.Universe(str(args.psf), str(args.ref_pdb))
    pairs = _find_pairs(ref, args.c1_lo_ang, args.c1_hi_ang)
    if args.dcd:
        u = mda.Universe(str(args.psf), str(args.ref_pdb), str(args.dcd))
        u.trajectory[args.frame]
        frame = int(u.trajectory.frame)
    else:
        u = ref
        frame = 0
    metrics = _frame_metrics(u, pairs, args.cutoff_ang, args.ref_delta_ang)
    result = {
        "psf": str(args.psf),
        "ref_pdb": str(args.ref_pdb),
        "dcd": str(args.dcd) if args.dcd else None,
        "frame": frame,
        "n_pairs": len(pairs),
        "cutoff_ang": args.cutoff_ang,
        "ref_delta_ang": args.ref_delta_ang,
        **metrics,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
