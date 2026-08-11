"""NAMD checkpoint and orientation-restraint helpers.

The former reduced-water re-preparation pipeline has been retired. These helpers remain
because production replicas use them independently of solvent preparation.
"""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np


def read_namd_coor(path: str | Path) -> np.ndarray:
    """Read a NAMD binary coordinate/restart file into an ``(N, 3)`` array."""
    data = Path(path).read_bytes()
    if len(data) < 4:
        raise ValueError(f"{path}: too short to be a NAMD .coor ({len(data)} bytes)")
    for endian in ("<", ">"):
        n = struct.unpack(endian + "i", data[:4])[0]
        if n > 0 and len(data) == 4 + n * 24:
            arr = np.frombuffer(
                data, dtype=np.dtype(endian + "f8"), count=3 * n, offset=4
            )
            return arr.reshape(n, 3).astype(np.float64)
    raise ValueError(
        f"{path}: not a NAMD binary .coor (size {len(data)} inconsistent with any atom count)"
    )


def orientation_restraint_colvars(
    n_dna_atoms: int,
    reference_file: str,
    *,
    force_constant: float = 500.0,
) -> str:
    """Restrain only the DNA's best-fit rigid-body orientation."""
    if n_dna_atoms < 3:
        raise ValueError("orientation restraint needs at least 3 DNA atoms")
    if not str(reference_file).strip():
        raise ValueError("reference_file must not be blank")
    if force_constant <= 0:
        raise ValueError("force_constant must be > 0")
    return (
        "colvar {\n"
        "    name dna_orientation\n"
        "    orientation {\n"
        f"        atoms {{ atomNumbersRange 1-{n_dna_atoms} }}\n"
        f"        refPositionsFile {reference_file}\n"
        "    }\n"
        "}\n"
        "harmonic {\n"
        "    name restrain_dna_orientation\n"
        "    colvars dna_orientation\n"
        "    centers (1.0, 0.0, 0.0, 0.0)\n"
        f"    forceConstant {force_constant:g}\n"
        "}\n"
    )


def write_orientation_reference_xyz(
    path: str | Path, coordinates_ang: np.ndarray, n_dna_atoms: int
) -> None:
    """Write a high-precision DNA-only XYZ reference from a NAMD checkpoint."""
    coords = np.asarray(coordinates_ang, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 3 or coords.shape[0] < n_dna_atoms:
        raise ValueError("checkpoint coordinates do not contain the requested DNA group")
    if n_dna_atoms < 3 or not np.isfinite(coords[:n_dna_atoms]).all():
        raise ValueError("orientation reference coordinates must be finite and non-empty")
    lines = [str(n_dna_atoms), "NADOC production-start DNA orientation reference"]
    lines.extend(
        f"X {x:.10f} {y:.10f} {z:.10f}" for x, y, z in coords[:n_dna_atoms]
    )
    Path(path).write_text("\n".join(lines) + "\n")
