#!/usr/bin/env python3
"""
create_nadoc_pdb.py — Create a single-helix NADOC design at a given honeycomb
                      lattice cell and export it as a GROMACS-ready PDB.

The scaffold sequence is set to CCTCTAGAGG (10 nt, self-complementary —
same as PDB 1ZEW chains A and B).  The staple is the Watson-Crick complement
derived automatically.

Usage:
    python scripts/create_nadoc_pdb.py --row 0 --col 0 --out /tmp/nadoc_0_0.pdb
    python scripts/create_nadoc_pdb.py --row 0 --col 1 --out /tmp/nadoc_0_1.pdb
    python scripts/create_nadoc_pdb.py --row 1 --col 1 --out /tmp/nadoc_1_1.pdb
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.core.lattice import make_bundle_design
from backend.core.models import LatticeType
from backend.core.sequences import assign_custom_scaffold_sequence, assign_staple_sequences
from backend.core.pdb_export import export_pdb

# 1ZEW chain A sequence (10 nt, self-complementary palindrome)
# Residues 1-10: DC DC DT DC DT DA DG DA DG DG  →  5'-CCTCTAGAGG-3'
_1ZEW_SEQUENCE = "CCTCTAGAGG"

_LATTICE_TYPE = LatticeType.HONEYCOMB


def create_and_export(row: int, col: int, output_path: str) -> None:
    parity = (row + col) % 2
    direction = "FORWARD" if parity == 0 else "REVERSE"

    print(f"[design]  cell ({row},{col}), parity={parity}, scaffold direction={direction}")
    print(f"          sequence: 5'-{_1ZEW_SEQUENCE}-3'  ({len(_1ZEW_SEQUENCE)} nt)")

    # Create a single-helix design with both scaffold and staple
    design = make_bundle_design(
        cells        = [(row, col)],
        length_bp    = len(_1ZEW_SEQUENCE),
        name         = f"1zew_like_{row}_{col}",
        plane        = "XY",
        strand_filter= "both",
        lattice_type = _LATTICE_TYPE,
    )

    # Print helix info
    h = design.helices[0]
    print(f"          helix id: {h.id}")
    print(f"          axis_start: ({h.axis_start.x:.3f}, {h.axis_start.y:.3f}, {h.axis_start.z:.3f}) nm")
    print(f"          axis_end:   ({h.axis_end.x:.3f}, {h.axis_end.y:.3f}, {h.axis_end.z:.3f}) nm")

    # Print strand info
    for s in design.strands:
        dom = s.domains[0]
        print(f"          strand {s.id}: type={s.strand_type}, "
              f"domain dir={dom.direction.value}, bp {dom.start_bp}→{dom.end_bp}")

    # Assign scaffold sequence (5'→3' order along the scaffold strand's traversal)
    design, total_nt, padded = assign_custom_scaffold_sequence(design, _1ZEW_SEQUENCE)
    if padded > 0:
        print(f"  WARNING: {padded} scaffold positions padded with N")
    print(f"[seq]     scaffold {total_nt} nt assigned; padded={padded}")

    # Derive staple sequences (Watson-Crick complement antiparallel)
    design = assign_staple_sequences(design)

    # Print final sequences
    for s in design.strands:
        print(f"          {s.id}: 5'-{s.sequence}-3'")

    # Export as PDB
    print(f"[export]  writing {output_path} …")
    pdb_text = export_pdb(design)

    with open(output_path, "w") as fh:
        fh.write(pdb_text)

    # Count atoms and chains
    atoms  = [ln for ln in pdb_text.splitlines() if ln.startswith("ATOM")]
    chains = sorted({ln[21] for ln in atoms})
    print(f"          {len(atoms)} atoms, chains: {', '.join(chains)}")
    print(f"[done]    {output_path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--row", type=int, required=True, help="Lattice row")
    ap.add_argument("--col", type=int, required=True, help="Lattice column")
    ap.add_argument("--out", required=True, help="Output PDB path")
    args = ap.parse_args()

    create_and_export(args.row, args.col, args.out)


if __name__ == "__main__":
    main()
