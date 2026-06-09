#!/usr/bin/env python3
"""Generate dense NAMD extraBonds ENM restraints for DNA-origami equilibration.

This follows the shape of the Maffeo/Yoo/Aksimentiev explicit-solvent protocol
more closely than the sparse local-order ENM: harmonic springs are placed
between nearby non-hydrogen DNA atoms using the reference structure distance as
the rest length.  The NAMD extraBonds atom indices are zero-based.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


DNA_RESNAMES = "DA DT DG DC A T G C ADE THY GUA CYT"


def _format_bond(i: int, j: int, k: float, distance: float) -> str:
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
    ap.add_argument("--cutoff-ang", type=float, default=5.0)
    ap.add_argument(
        "--keep-topology-bonds",
        action="store_true",
        help="Do not filter pairs that duplicate PSF covalent bonds.",
    )
    args = ap.parse_args()

    import MDAnalysis as mda

    u = mda.Universe(str(args.psf), str(args.pdb))
    dna = u.select_atoms(f"resname {DNA_RESNAMES} and not name H*")
    if not len(dna):
        raise RuntimeError("No DNA heavy atoms selected.")

    positions = np.asarray(dna.positions, dtype=np.float32)
    pairs = cKDTree(positions).query_pairs(args.cutoff_ang, output_type="ndarray")
    atom_indices = np.asarray(dna.indices, dtype=np.int64)
    bonded: set[tuple[int, int]] = set()
    if not args.keep_topology_bonds:
        for bond in u.bonds:
            i, j = sorted(int(atom.index) for atom in bond.atoms)
            bonded.add((i, j))

    n_written = 0
    n_skipped_bonded = 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as handle:
        for local_i, local_j in pairs:
            global_i = int(atom_indices[local_i])
            global_j = int(atom_indices[local_j])
            if tuple(sorted((global_i, global_j))) in bonded:
                n_skipped_bonded += 1
                continue
            diff = positions[local_i] - positions[local_j]
            distance = float(np.sqrt(np.dot(diff, diff)))
            handle.write(
                _format_bond(
                    global_i,
                    global_j,
                    args.k,
                    distance,
                )
                + "\n"
            )
            n_written += 1

    report = {
        "psf": str(args.psf),
        "pdb": str(args.pdb),
        "out": str(args.out),
        "n_dna_heavy_atoms": int(len(dna)),
        "n_candidate_pairs": int(len(pairs)),
        "n_restraints": int(n_written),
        "n_skipped_topology_bonds": int(n_skipped_bonded),
        "k": args.k,
        "cutoff_ang": args.cutoff_ang,
        "selection": f"resname {DNA_RESNAMES} and not name H*",
        "note": (
            "Dense non-hydrogen DNA local ENM. This approximates published "
            "intra-helical ENM restraints but does not yet classify helix-local "
            "versus accidental inter-helix contacts."
        ),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {args.out} with {n_written} restraints")
    print(f"Wrote {args.report}")


if __name__ == "__main__":
    main()
