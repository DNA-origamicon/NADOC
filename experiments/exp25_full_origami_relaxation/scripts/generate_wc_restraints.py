#!/usr/bin/env python3
"""Generate Watson-Crick heavy-atom distance restraints for NAMD extraBonds."""

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
    tree = cKDTree(c1.positions)
    used = np.zeros(len(c1), dtype=bool)
    pairs = []
    for i in range(len(c1)):
        if used[i]:
            continue
        candidates = []
        for j in tree.query_ball_point(c1.positions[i], hi):
            if j <= i or used[j] or c1[i].segid == c1[j].segid:
                continue
            d = float(np.linalg.norm(c1.positions[i] - c1.positions[j]))
            if d >= lo:
                candidates.append((d, j))
        if not candidates:
            continue
        _d, j = min(candidates)
        res_a = c1[i].residue
        res_b = c1[j].residue
        hbonds = WC_ATOMS.get((res_a.resname.strip(), res_b.resname.strip()), [])
        atom_pairs = []
        for atom_a, atom_b in hbonds:
            ia = _atom_index(res_a, atom_a)
            ib = _atom_index(res_b, atom_b)
            if ia is not None and ib is not None:
                atom_pairs.append((ia, ib))
        if atom_pairs:
            used[i] = used[j] = True
            pairs.append((res_a, res_b, atom_pairs))
    return pairs


def _bond_line(i: int, j: int, k: float, distance: float) -> str:
    if i > j:
        i, j = j, i
    return f"bond {i:d} {j:d} {k:.4f} {distance:.4f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psf", type=Path, required=True)
    ap.add_argument("--pdb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--k", type=float, default=0.1)
    ap.add_argument("--c1-lo-ang", type=float, default=8.5)
    ap.add_argument("--c1-hi-ang", type=float, default=13.0)
    args = ap.parse_args()

    import MDAnalysis as mda

    u = mda.Universe(str(args.psf), str(args.pdb))
    pairs = _find_pairs(u, args.c1_lo_ang, args.c1_hi_ang)
    lines = []
    for _res_a, _res_b, atom_pairs in pairs:
        for ia, ib in atom_pairs:
            d = float(np.linalg.norm(u.atoms[ia].position - u.atoms[ib].position))
            lines.append(_bond_line(ia, ib, args.k, d))

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        "psf": str(args.psf),
        "pdb": str(args.pdb),
        "out": str(args.out),
        "n_base_pairs": len(pairs),
        "n_restraints": len(lines),
        "k": args.k,
        "c1_lo_ang": args.c1_lo_ang,
        "c1_hi_ang": args.c1_hi_ang,
    }, indent=2) + "\n")
    print(f"Wrote {args.out} with {len(lines)} restraints")
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
