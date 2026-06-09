#!/usr/bin/env python3
"""Generate NAMD extraBonds restraints for DNA-origami local-order equilibration.

This is an origami-style elastic-network approximation: preserve Watson-Crick
base-pair registry and nearest-neighbor base stacking while letting global
origami shape relax more freely than with all-atom positional restraints.

The output is a NAMD extraBonds file with zero-based atom indices:
    bond atom_i atom_j k distance_angstrom
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


SUGAR_PHOSPHATE = {
    "P", "OP1", "OP2", "O1P", "O2P", "O3'", "O5'", "C5'", "C4'", "O4'",
    "C3'", "O3*", "O5*", "C5*", "C4*", "O4*", "C3*", "C2'", "C1'",
    "C2*", "C1*", "H1'", "H2'", "H2''", "H3'", "H4'", "H5'", "H5''",
}


def _c1p(u):
    sel = u.select_atoms("name C1'")
    if not len(sel):
        sel = u.select_atoms("name C1X")
    if not len(sel):
        raise RuntimeError("No C1' atoms found.")
    return sel


def _base_atoms(residue):
    atoms = [
        a for a in residue.atoms
        if not a.name.startswith("H") and a.name.strip() not in SUGAR_PHOSPHATE
    ]
    return atoms


def _res_key(residue) -> tuple[str, int]:
    return (str(residue.segid), int(residue.resid))


def _find_base_pairs(u, lo: float, hi: float):
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
        used[i] = used[j] = True
        pairs.append((c1[i].residue, c1[j].residue, d))
    return pairs


def _bond_line(a, b, k: float, distance: float) -> str:
    i = int(a.index)
    j = int(b.index)
    if i > j:
        i, j = j, i
    return f"bond {i:d} {j:d} {k:.4f} {distance:.4f}"


def _add_pair_restraints(lines, seen, res_a, res_b, *, k: float, cutoff: float, max_per_pair: int):
    atoms_a = _base_atoms(res_a)
    atoms_b = _base_atoms(res_b)
    candidates = []
    for a in atoms_a:
        pa = a.position
        for b in atoms_b:
            d = float(np.linalg.norm(pa - b.position))
            if 2.4 <= d <= cutoff:
                candidates.append((d, a, b))
    candidates.sort(key=lambda x: x[0])
    for d, a, b in candidates[:max_per_pair]:
        key = tuple(sorted((int(a.index), int(b.index))))
        if key in seen:
            continue
        seen.add(key)
        lines.append(_bond_line(a, b, k, d))


def _add_stack_restraints(lines, seen, residues, *, k: float, cutoff: float, max_per_step: int):
    by_seg: dict[str, list] = {}
    for res in residues:
        by_seg.setdefault(str(res.segid), []).append(res)
    for seg_residues in by_seg.values():
        seg_residues.sort(key=lambda r: int(r.resid))
        for r1, r2 in zip(seg_residues, seg_residues[1:]):
            if int(r2.resid) != int(r1.resid) + 1:
                continue
            atoms_a = _base_atoms(r1)
            atoms_b = _base_atoms(r2)
            candidates = []
            for a in atoms_a:
                pa = a.position
                for b in atoms_b:
                    d = float(np.linalg.norm(pa - b.position))
                    if 3.0 <= d <= cutoff:
                        candidates.append((d, a, b))
            candidates.sort(key=lambda x: x[0])
            for d, a, b in candidates[:max_per_step]:
                key = tuple(sorted((int(a.index), int(b.index))))
                if key in seen:
                    continue
                seen.add(key)
                lines.append(_bond_line(a, b, k, d))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psf", type=Path, required=True)
    ap.add_argument("--pdb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--pair-k", type=float, default=0.5)
    ap.add_argument("--stack-k", type=float, default=0.1)
    ap.add_argument("--pair-cutoff-ang", type=float, default=4.2)
    ap.add_argument("--stack-cutoff-ang", type=float, default=4.8)
    ap.add_argument("--max-pair-restraints", type=int, default=6)
    ap.add_argument("--max-stack-restraints", type=int, default=4)
    ap.add_argument("--c1-lo-ang", type=float, default=8.5)
    ap.add_argument("--c1-hi-ang", type=float, default=13.0)
    args = ap.parse_args()

    import MDAnalysis as mda

    u = mda.Universe(str(args.psf), str(args.pdb))
    pairs = _find_base_pairs(u, args.c1_lo_ang, args.c1_hi_ang)
    paired_keys = {_res_key(a) for a, _b, _d in pairs} | {_res_key(b) for _a, b, _d in pairs}
    paired_residues = [res for res in u.residues if _res_key(res) in paired_keys]

    lines: list[str] = []
    seen: set[tuple[int, int]] = set()
    for res_a, res_b, _d in pairs:
        _add_pair_restraints(
            lines, seen, res_a, res_b,
            k=args.pair_k,
            cutoff=args.pair_cutoff_ang,
            max_per_pair=args.max_pair_restraints,
        )
    n_pair_lines = len(lines)
    _add_stack_restraints(
        lines, seen, paired_residues,
        k=args.stack_k,
        cutoff=args.stack_cutoff_ang,
        max_per_step=args.max_stack_restraints,
    )
    n_stack_lines = len(lines) - n_pair_lines

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        "psf": str(args.psf),
        "pdb": str(args.pdb),
        "n_base_pairs": len(pairs),
        "n_pair_restraints": n_pair_lines,
        "n_stack_restraints": n_stack_lines,
        "n_total_restraints": len(lines),
        "pair_k": args.pair_k,
        "stack_k": args.stack_k,
        "pair_cutoff_ang": args.pair_cutoff_ang,
        "stack_cutoff_ang": args.stack_cutoff_ang,
    }, indent=2) + "\n")
    print(f"Wrote {args.out} with {len(lines)} restraints")
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
