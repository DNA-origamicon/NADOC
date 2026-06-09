#!/usr/bin/env python3
"""Generate ENRG-style vacuum extraBonds restraints for DNA origami.

The published ENRG DNA-origami vacuum protocol uses two restraint classes:

1. Dense intra-helical elastic-network restraints between nearby non-hydrogen
   DNA atoms to preserve local base pairing and stacking.
2. Inter-helical P-P restraints with k = 1 kcal/mol/A^2 and r0 = 31 A to mimic
   the DNA-DNA repulsion otherwise supplied by electrolyte solution.

The original ENRG server writes design-aware restraints from caDNAno.  This
local generator reconstructs the same restraint classes from the atomistic PDB
when the server-produced .exb file is not available.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


BACKBONE_ONLY = {
    "P", "OP1", "OP2", "O1P", "O2P", "O3'", "O5'", "C5'", "C4'", "O4'",
    "C3'", "C2'", "C1'", "O3*", "O5*", "C5*", "C4*", "O4*", "C3*", "C2*",
    "C1*",
}

WC_RESNAME_PAIRS = {
    ("DA", "DT"), ("DT", "DA"), ("A", "T"), ("T", "A"),
    ("DG", "DC"), ("DC", "DG"), ("G", "C"), ("C", "G"),
}


@dataclass
class Atom:
    index: int
    name: str
    resname: str
    chain: str
    resid: int
    segid: str
    pos: np.ndarray


@dataclass
class Residue:
    key: tuple[str, int, str]
    atoms: list[Atom] = field(default_factory=list)

    def atom(self, *names: str) -> Atom | None:
        wanted = set(names)
        for atom in self.atoms:
            if atom.name in wanted:
                return atom
        return None

    @property
    def c1(self) -> Atom | None:
        return self.atom("C1'", "C1*")

    @property
    def p(self) -> Atom | None:
        return self.atom("P")

    @property
    def non_hydrogen(self) -> list[Atom]:
        return [atom for atom in self.atoms if not atom.name.startswith("H")]


def parse_pdb(path: Path) -> list[Residue]:
    residues: list[Residue] = []
    current_key: tuple[str, int, str, str] | None = None
    atom_index = 0
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM", "HETATM")):
            continue
        name = line[12:16].strip()
        resname = line[17:20].strip()
        chain = line[21].strip()
        resid = int(line[22:26])
        segid = line[72:76].strip() or chain
        xyz = np.array([
            float(line[30:38]),
            float(line[38:46]),
            float(line[46:54]),
        ], dtype=float)
        # PDB atom serials wrap for systems larger than 99,999 atoms.  NAMD
        # extraBonds indices must follow PSF/PDB atom order, so count records.
        index = atom_index
        atom_index += 1
        # Large PDBs can reuse residue ids within a segment after writer-side
        # wrapping.  Treat contiguous PDB residue records as distinct residues
        # instead of merging all equal segid/resid keys across the whole file.
        ordered_key = (segid, resid, chain, resname)
        if ordered_key != current_key:
            residues.append(Residue((segid, resid, chain)))
            current_key = ordered_key
        residues[-1].atoms.append(Atom(index, name, resname, chain, resid, segid, xyz))
    return residues


def parse_psf_bonds(path: Path | None) -> set[tuple[int, int]]:
    if path is None:
        return set()
    lines = path.read_text(errors="replace").splitlines()
    bonds: set[tuple[int, int]] = set()
    for pos, line in enumerate(lines):
        if "!NBOND" not in line:
            continue
        n_bonds = int(line.split()[0])
        values: list[int] = []
        cursor = pos + 1
        while cursor < len(lines) and len(values) < n_bonds * 2:
            values.extend(int(tok) for tok in lines[cursor].split())
            cursor += 1
        for i in range(0, len(values[: n_bonds * 2]), 2):
            a = values[i] - 1
            b = values[i + 1] - 1
            bonds.add(tuple(sorted((a, b))))
        return bonds
    return bonds


def find_base_pairs(residues: list[Residue], lo: float, hi: float) -> list[tuple[Residue, Residue]]:
    c1_res = [res for res in residues if res.c1 is not None]
    coords = np.array([res.c1.pos for res in c1_res])
    tree = cKDTree(coords)
    used = np.zeros(len(c1_res), dtype=bool)
    pairs: list[tuple[Residue, Residue]] = []
    for i, res_i in enumerate(c1_res):
        if used[i]:
            continue
        candidates = []
        for j in tree.query_ball_point(coords[i], hi):
            if j <= i or used[j]:
                continue
            res_j = c1_res[j]
            if res_i.key[0] == res_j.key[0]:
                continue
            if (res_i.atoms[0].resname.strip(), res_j.atoms[0].resname.strip()) not in WC_RESNAME_PAIRS:
                continue
            dist = float(np.linalg.norm(coords[i] - coords[j]))
            if lo <= dist <= hi:
                candidates.append((dist, j))
        if not candidates:
            continue
        _dist, j = min(candidates)
        used[i] = True
        used[j] = True
        pairs.append((res_i, c1_res[j]))
    return pairs


def bond_line(a: Atom, b: Atom, k: float, r0: float) -> str:
    i, j = sorted((a.index, b.index))
    return f"bond {i:d} {j:d} {k:.4f} {r0:.4f}"


def add_dense_between(
    lines: list[str],
    seen: set[tuple[int, int]],
    atoms_a: list[Atom],
    atoms_b: list[Atom],
    *,
    cutoff: float,
    k: float,
    excluded: set[tuple[int, int]],
) -> None:
    for atom_a in atoms_a:
        for atom_b in atoms_b:
            if atom_a.index == atom_b.index:
                continue
            key = tuple(sorted((atom_a.index, atom_b.index)))
            if key in seen or key in excluded:
                continue
            dist = float(np.linalg.norm(atom_a.pos - atom_b.pos))
            if dist <= cutoff:
                seen.add(key)
                lines.append(bond_line(atom_a, atom_b, k, dist))


def build_local_enm(
    residues: list[Residue],
    pairs: list[tuple[Residue, Residue]],
    *,
    cutoff: float,
    k: float,
    excluded: set[tuple[int, int]],
) -> list[str]:
    lines: list[str] = []
    seen: set[tuple[int, int]] = set()

    paired_keys = {a.key for a, _b in pairs} | {b.key for _a, b in pairs}
    for res_a, res_b in pairs:
        add_dense_between(
            lines, seen, res_a.non_hydrogen, res_b.non_hydrogen,
            cutoff=cutoff, k=k, excluded=excluded,
        )

    by_seg: dict[str, list[Residue]] = {}
    for res in residues:
        if res.key in paired_keys:
            by_seg.setdefault(res.key[0], []).append(res)
    for seg_residues in by_seg.values():
        seg_residues.sort(key=lambda res: res.key[1])
        for res_a, res_b in zip(seg_residues, seg_residues[1:]):
            if res_b.key[1] != res_a.key[1] + 1:
                continue
            add_dense_between(
                lines, seen, res_a.non_hydrogen, res_b.non_hydrogen,
                cutoff=cutoff, k=k, excluded=excluded,
            )
    return lines


def build_interhelix(
    pairs: list[tuple[Residue, Residue]],
    *,
    k: float,
    r0: float,
    min_center: float,
    max_center: float,
    max_dz: float,
    max_neighbors: int,
) -> list[str]:
    records = []
    for idx, (res_a, res_b) in enumerate(pairs):
        if res_a.p is None or res_b.p is None:
            continue
        center = 0.5 * (res_a.c1.pos + res_b.c1.pos)
        records.append((idx, center, res_a, res_b))
    centers = np.array([rec[1] for rec in records])
    tree = cKDTree(centers)
    lines: list[str] = []
    seen: set[tuple[int, int]] = set()
    for i, center_i, res_ai, res_bi in records:
        candidates = []
        for rec_j in tree.query_ball_point(center_i, max_center):
            j, center_j, res_aj, res_bj = records[rec_j]
            if j <= i:
                continue
            if abs(float(center_i[2] - center_j[2])) > max_dz:
                continue
            d_center = float(np.linalg.norm(center_i[:2] - center_j[:2]))
            if not (min_center <= d_center <= max_center):
                continue
            candidates.append((abs(d_center - r0), res_aj, res_bj))
        candidates.sort(key=lambda item: item[0])
        for _score, res_aj, res_bj in candidates[:max_neighbors]:
            for atom_i in (res_ai.p, res_bi.p):
                for atom_j in (res_aj.p, res_bj.p):
                    key = tuple(sorted((atom_i.index, atom_j.index)))
                    if key in seen:
                        continue
                    seen.add(key)
                    lines.append(bond_line(atom_i, atom_j, k, r0))
                    break
                else:
                    continue
                break
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdb", type=Path, required=True)
    ap.add_argument("--psf", type=Path, default=None)
    ap.add_argument("--local-out", type=Path, required=True)
    ap.add_argument("--inter-out", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--c1-lo", type=float, default=8.5)
    ap.add_argument("--c1-hi", type=float, default=13.0)
    ap.add_argument("--local-cutoff", type=float, default=5.0)
    ap.add_argument("--local-k", type=float, default=0.1)
    ap.add_argument("--inter-k", type=float, default=1.0)
    ap.add_argument("--inter-r0", type=float, default=31.0)
    ap.add_argument("--inter-min-center", type=float, default=18.0)
    ap.add_argument("--inter-max-center", type=float, default=36.0)
    ap.add_argument("--inter-max-dz", type=float, default=2.5)
    ap.add_argument("--inter-max-neighbors", type=int, default=2)
    args = ap.parse_args()

    residues = parse_pdb(args.pdb)
    psf_bonds = parse_psf_bonds(args.psf)
    pairs = find_base_pairs(residues, args.c1_lo, args.c1_hi)
    local = build_local_enm(
        residues, pairs,
        cutoff=args.local_cutoff,
        k=args.local_k,
        excluded=psf_bonds,
    )
    inter = build_interhelix(
        pairs,
        k=args.inter_k,
        r0=args.inter_r0,
        min_center=args.inter_min_center,
        max_center=args.inter_max_center,
        max_dz=args.inter_max_dz,
        max_neighbors=args.inter_max_neighbors,
    )

    args.local_out.parent.mkdir(parents=True, exist_ok=True)
    args.inter_out.parent.mkdir(parents=True, exist_ok=True)
    args.local_out.write_text("\n".join(local) + "\n")
    args.inter_out.write_text("\n".join(inter) + "\n")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({
        "pdb": str(args.pdb),
        "psf": str(args.psf) if args.psf else None,
        "n_residues": len(residues),
        "n_psf_bonds_excluded": len(psf_bonds),
        "n_base_pairs": len(pairs),
        "n_local_restraints": len(local),
        "n_interhelix_restraints": len(inter),
        "local_k": args.local_k,
        "local_cutoff_A": args.local_cutoff,
        "interhelix_k": args.inter_k,
        "interhelix_r0_A": args.inter_r0,
        "interhelix_center_window_A": [args.inter_min_center, args.inter_max_center],
        "interhelix_max_dz_A": args.inter_max_dz,
        "note": "Design-aware ENRG server .exb was unavailable; restraint classes follow the published protocol but are inferred from PDB geometry.",
    }, indent=2) + "\n")
    print(f"Wrote {args.local_out} ({len(local)} local ENM restraints)")
    print(f"Wrote {args.inter_out} ({len(inter)} inter-helix restraints)")
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
