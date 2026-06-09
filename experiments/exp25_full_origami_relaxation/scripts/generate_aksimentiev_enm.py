#!/usr/bin/env python3
"""Generate Aksimentiev tutorial-style NAMD ENM extraBonds.

This is a Python port of the tutorial `cadnano2pdb2enm.pl` behavior:

- read ATOM records in PDB order,
- ignore hydrogens, phosphate atoms, O1P/O2P, and atom names containing "'",
- keep base-ring atoms matching N1,C2,N3,C4,C5,C6,N7,C8,N9,
- keep DNA residues DA/DT/DG/DC and ADE/THY/GUA/CYT aliases,
- prefilter residue pairs by base COM distance <= 30 A,
- write NAMD zero-based atom-index springs for atom pairs within `--cut-ang`.

The output line format matches the tutorial:
    bond <atom_i_zero_based> <atom_j_zero_based> <k> <distance_ang>
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


BASE_ATOMS = {"N1", "C2", "N3", "C4", "C5", "C6", "N7", "C8", "N9"}
DNA_RESNAMES = {"ADE", "DA", "THY", "DT", "GUA", "DG", "CYT", "DC"}


@dataclass
class BaseResidue:
    key: tuple[str, str, str]
    atoms: list[tuple[int, str, np.ndarray]] = field(default_factory=list)

    @property
    def com(self) -> np.ndarray:
        return np.mean([pos for _idx, _name, pos in self.atoms], axis=0)


def _parse_pdb(path: Path) -> list[BaseResidue]:
    residues: list[BaseResidue] = []
    by_key: dict[tuple[str, str, str], BaseResidue] = {}
    atom_ordinal = 0
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith("ATOM  "):
            continue
        atom_ordinal += 1
        atom = line[12:16].strip()
        resn = line[17:21].strip()
        chain = line[21:22].strip()
        resid = line[22:26].strip()
        if "H" in atom or atom in {"P", "O1P", "O2P"} or "'" in atom:
            continue
        if atom not in BASE_ATOMS:
            continue
        if resn not in DNA_RESNAMES:
            continue
        try:
            pos = np.array([
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            ], dtype=float)
        except ValueError:
            continue
        key = (chain, resid, resn)
        row = by_key.get(key)
        if row is None:
            row = BaseResidue(key=key)
            by_key[key] = row
            residues.append(row)
        row.atoms.append((atom_ordinal - 1, atom, pos))
    return [res for res in residues if res.atoms]


def _format_k(k: float) -> str:
    return f"{k:.6g}"


def generate(pdb: Path, out: Path, report: Path, *, k: float, cut_ang: float) -> None:
    residues = _parse_pdb(pdb)
    coms = np.array([res.com for res in residues], dtype=float)
    tree = cKDTree(coms)
    residue_pairs = tree.query_pairs(30.0, output_type="ndarray")

    n_bonds = 0
    out.parent.mkdir(parents=True, exist_ok=True)
    k_text = _format_k(k)
    with out.open("w") as handle:
        for ri, rj in residue_pairs:
            res_i = residues[int(ri)]
            res_j = residues[int(rj)]
            for idx_i, _name_i, pos_i in res_i.atoms:
                for idx_j, _name_j, pos_j in res_j.atoms:
                    dx = pos_i - pos_j
                    dist = float(math.sqrt(float(np.dot(dx, dx))))
                    if dist > cut_ang:
                        continue
                    a, b = sorted((idx_i, idx_j))
                    handle.write(f"bond{a:10d}{b:10d}{k_text:>10s}{dist:10.3g}\n")
                    n_bonds += 1

    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({
        "schema": "nadoc.aksimentiev_enm.v1",
        "source_pdb": str(pdb),
        "out": str(out),
        "n_residues_with_base_atoms": len(residues),
        "n_residue_pairs_com_le_30A": int(len(residue_pairs)),
        "n_restraints": n_bonds,
        "k_kcal_mol_A2": k,
        "cut_ang": cut_ang,
        "base_atoms": sorted(BASE_ATOMS),
        "resnames": sorted(DNA_RESNAMES),
        "note": "Python port of cadnano2pdb2enm.pl tutorial ENM selection.",
    }, indent=2) + "\n")
    print(f"Wrote {out} with {n_bonds} restraints")
    print(f"Wrote {report}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--k", type=float, required=True)
    ap.add_argument("--cut-ang", type=float, default=8.0)
    args = ap.parse_args()
    generate(args.pdb, args.out, args.report, k=args.k, cut_ang=args.cut_ang)


if __name__ == "__main__":
    main()
