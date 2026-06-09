"""Write a NAMD constraint-reference PDB from a binary coordinate restart."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psf", type=Path, required=True)
    ap.add_argument("--coor", type=Path, required=True)
    ap.add_argument("--template-pdb", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--beta", type=float, default=1.0)
    args = ap.parse_args()

    import MDAnalysis as mda

    u = mda.Universe(str(args.psf), str(args.coor), format="NAMDBIN")
    coords = u.atoms.positions

    atom_lines = [
        line.rstrip("\n")
        for line in args.template_pdb.read_text(errors="replace").splitlines()
        if line.startswith(("ATOM  ", "HETATM"))
    ]
    if len(atom_lines) != len(coords):
        raise SystemExit(f"Template atom count {len(atom_lines)} != coordinate count {len(coords)}")

    out_lines: list[str] = []
    atom_i = 0
    for raw in args.template_pdb.read_text(errors="replace").splitlines():
        if raw.startswith(("ATOM  ", "HETATM")):
            x, y, z = coords[atom_i]
            line = (
                f"{raw[:30]}{x:8.3f}{y:8.3f}{z:8.3f}"
                f"  1.00{args.beta:6.2f}{raw[66:]}"
            )
            out_lines.append(line)
            atom_i += 1
        else:
            out_lines.append(raw)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines) + "\n")


if __name__ == "__main__":
    main()
