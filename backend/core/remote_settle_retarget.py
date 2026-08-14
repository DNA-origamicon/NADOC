"""Re-reference settle restraints to a completed NAMD minimization.

This module is deliberately stdlib-only: the local runner imports the function below,
and remote executors stage this very file on compute nodes.  Keeping one implementation
prevents the local and remote coordinate-column rewrites from drifting apart.
"""

from __future__ import annotations

import argparse
import struct
from pathlib import Path


def retarget_pdb_coordinates(coor_path: Path, src_pdb: Path, dst_pdb: Path) -> int:
    """Replace PDB coordinate columns with the matching NAMD binary coordinates."""
    raw = coor_path.read_bytes()
    if len(raw) < 4:
        raise RuntimeError(f"Invalid NAMD coordinate file: {coor_path}")
    n = struct.unpack("<i", raw[:4])[0]
    expected = 4 + n * 24
    if n < 0 or len(raw) < expected:
        raise RuntimeError(
            f"Invalid NAMD coordinate file: expected at least {expected} bytes, "
            f"found {len(raw)}"
        )
    xyz = struct.iter_unpack("<3d", raw[4:expected])

    out: list[str] = []
    ai = 0
    for line in src_pdb.read_text().splitlines(keepends=True):
        if line.startswith(("ATOM", "HETATM")):
            try:
                x, y, z = next(xyz)
            except StopIteration as exc:
                raise RuntimeError(
                    f"Atom count mismatch: PDB has more than {n} ATOM/HETATM lines"
                ) from exc
            ai += 1
            line = f"{line[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}"
        out.append(line)
    if ai != n:
        raise RuntimeError(
            f"Atom count mismatch: PDB has {ai} ATOM/HETATM lines, .coor has {n}"
        )
    dst_pdb.write_text("".join(out))
    return ai


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coor", type=Path)
    parser.add_argument("pdb", type=Path)
    args = parser.parse_args()
    n = retarget_pdb_coordinates(args.coor, args.pdb, args.pdb)
    print(f"Retargeted settle restraints to minimized coordinates ({n} atoms).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
