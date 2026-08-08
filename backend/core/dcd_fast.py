"""O(1) last-frame reader for fixed-record DCD trajectories.

The live MD-display only needs the LATEST frame of a run, but MDAnalysis'
``Universe.load_new`` rebuilds the whole frame-offset index by walking the file —
O(file size), and pathological on a multi-GB DCD that NAMD is still appending to
(repeated "seek failed, recalculating offsets" retries that pin a core).

A DCD is a fixed-record format: after the header every frame is exactly the same
number of bytes (a function of the atom count and the unit-cell flag, both constant
for a run).  So the last complete frame's byte offset is pure arithmetic from the
file size — no scan.  This module parses the header once and seeks straight to a
frame, reading a few hundred KB regardless of trajectory length.

Scope: the common NAMD/CHARMM case (no fixed atoms).  ``read_layout`` raises
``UnsupportedDCD`` for anything it can't safely treat as fixed-record (fixed atoms,
4D, bad magic), so callers fall back to the MDAnalysis path.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np


class UnsupportedDCD(Exception):
    """The DCD isn't a plain fixed-record layout — caller should fall back."""


@dataclass(frozen=True)
class DcdLayout:
    endian: str  # "<" or ">"
    n_atoms: int
    has_cell: bool
    header_bytes: int
    frame_bytes: int
    n_frames: int
    istart: int
    nsavc: int
    delta_ps: float  # timestep between saved frames, in ps (0 if unknown)
    first_ps: float  # simulation time of frame 0 = istart·dt, in ps (0 if unknown)


def read_layout(path) -> DcdLayout:
    """Parse the DCD header and derive the fixed-record layout + frame count.

    Reads only the header (~a few hundred bytes) plus the file size."""
    path = Path(path)
    size = path.stat().st_size
    with open(path, "rb") as fh:
        head = fh.read(4)
        if len(head) < 4:
            raise UnsupportedDCD("file too small for a DCD header")
        # Endianness from the first Fortran record marker (the CORD block = 84 bytes).
        if struct.unpack("<i", head)[0] == 84:
            endian = "<"
        elif struct.unpack(">i", head)[0] == 84:
            endian = ">"
        else:
            raise UnsupportedDCD("not a DCD (bad leading record marker)")

        magic = fh.read(4)
        if magic != b"CORD":
            raise UnsupportedDCD(f"bad DCD magic {magic!r}")
        icntrl = struct.unpack(f"{endian}20i", fh.read(80))
        fh.read(4)  # trailing marker of record 1

        istart, nsavc = icntrl[1], icntrl[2]
        nfixed = icntrl[8]
        charmm_ver = icntrl[19]
        has_cell = bool(icntrl[10]) and charmm_ver > 0
        four_dims = bool(icntrl[11])
        # DELTA: float32 for CHARMM/NAMD (icntrl[9] reinterpreted), in AKMA time units.
        if charmm_ver > 0:
            delta_akma = struct.unpack(
                f"{endian}f", struct.pack(f"{endian}i", icntrl[9])
            )[0]
        else:
            delta_akma = 0.0
        step_ps = float(delta_akma) * 0.04888821  # AKMA → ps, per integrator step
        delta_ps = step_ps * nsavc  # ps per saved frame
        # Absolute time of the first saved frame.  Continuation segments (.contN.dcd)
        # start at ISTART != 0, so frame time is first_ps + idx·delta_ps, not idx·delta_ps.
        first_ps = step_ps * istart

        if nfixed != 0:
            raise UnsupportedDCD("fixed atoms (NFIXED>0) — variable-size frames")
        if four_dims:
            raise UnsupportedDCD("4D trajectory")

        # Record 2: title block — leading marker tells us its length.
        m2 = struct.unpack(f"{endian}i", fh.read(4))[0]
        fh.seek(m2 + 4, 1)  # skip title content + trailing marker

        # Record 3: NATOM.
        fh.read(4)  # leading marker (=4)
        n_atoms = struct.unpack(f"{endian}i", fh.read(4))[0]
        fh.read(4)  # trailing marker
        header_bytes = fh.tell()

    if n_atoms <= 0:
        raise UnsupportedDCD(f"non-positive atom count {n_atoms}")
    cell_bytes = (4 + 48 + 4) if has_cell else 0  # int32 + 6 doubles + int32
    coord_block = 4 + 4 * n_atoms + 4  # int32 + n floats + int32
    frame_bytes = cell_bytes + 3 * coord_block
    n_frames = max(0, (size - header_bytes) // frame_bytes)
    return DcdLayout(
        endian,
        n_atoms,
        has_cell,
        header_bytes,
        frame_bytes,
        int(n_frames),
        istart,
        nsavc,
        delta_ps,
        first_ps,
    )


def read_frame(path, layout: DcdLayout, frame_idx: int):
    """Read one frame's coordinates by direct seek — no scan.

    Returns ``(coords, cell)`` with ``coords`` an ``(n_atoms, 3)`` float32 array in
    Å and ``cell`` the 6 raw unit-cell doubles (or None).  Raises ``IndexError`` for
    an out-of-range/torn frame so the caller can fall back one frame.
    """
    if frame_idx < 0 or frame_idx >= layout.n_frames:
        raise IndexError(f"frame {frame_idx} out of range (n_frames={layout.n_frames})")
    e, n = layout.endian, layout.n_atoms
    off = layout.header_bytes + frame_idx * layout.frame_bytes
    with open(path, "rb") as fh:
        fh.seek(off)
        buf = fh.read(layout.frame_bytes)
    if len(buf) < layout.frame_bytes:
        raise IndexError("trailing frame is torn / not fully written")

    pos = 0
    cell = None
    if layout.has_cell:
        m0 = struct.unpack_from(f"{e}i", buf, pos)[0]
        pos += 4
        if m0 != 48:
            raise IndexError("bad unit-cell record marker")
        cell = np.array(struct.unpack_from(f"{e}6d", buf, pos), dtype=np.float64)
        pos += 48
        pos += 4  # trailing marker

    def _axis() -> np.ndarray:
        nonlocal pos
        m = struct.unpack_from(f"{e}i", buf, pos)[0]
        pos += 4
        if m != 4 * n:
            raise IndexError("bad coordinate-block marker (size mismatch)")
        a = np.frombuffer(buf, dtype=np.dtype(e + "f4"), count=n, offset=pos).astype(
            np.float32
        )
        pos += 4 * n + 4  # data + trailing marker
        return a

    x, y, z = _axis(), _axis(), _axis()
    return np.column_stack((x, y, z)).astype(np.float32), cell


def cell_to_dimensions(cell: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """CHARMM/NAMD 6 raw cell doubles → MDAnalysis-style ``[a,b,c,alpha,beta,gamma]``
    (Å + degrees). Stored order is ``[A, cos γ, B, cos β, cos α, C]``."""
    if cell is None:
        return None
    a, cg, b, cb, ca, c = (float(v) for v in cell)

    def _ang(cos_v: float) -> float:
        # Orthorhombic boxes store 0 (→ 90°). Some writers store the angle in degrees
        # directly (value > 1 can't be a cosine) — pass those through.
        if abs(cos_v) > 1.0:
            return cos_v
        return float(np.degrees(np.arccos(max(-1.0, min(1.0, cos_v)))))

    return np.array([a, b, c, _ang(ca), _ang(cb), _ang(cg)], dtype=np.float64)


# ── Writer ────────────────────────────────────────────────────────────────────
#
# A trajectory export writes the same structure N times.  As multi-MODEL PDB that is ~80
# ASCII bytes per atom per frame; as DCD it is 12 binary bytes — plus the topology travels
# once, in a companion single-frame PDB, instead of being re-serialised every frame.
# ChimeraX reads the pair with:  open s.pdb   then   open t.dcd structureModel #1
#
# Emits the plain fixed-record CHARMM layout `read_layout` above accepts: no fixed atoms,
# no 4D, unit cell optional.  Frames are appended one at a time, so a writer's peak memory
# is one frame regardless of trajectory length.

_DCD_TITLE = b"NADOC composite trajectory export".ljust(80)[:80]


def write_header(
    fh,
    n_atoms: int,
    n_frames: int,
    *,
    istart: int = 0,
    nsavc: int = 1,
    delta: float = 1.0,
    title: bytes = _DCD_TITLE,
) -> None:
    """Write the three DCD header records to a binary file object.

    ``n_frames`` goes in the NSET field. A composite NADOC trajectory splices stages with
    different integrator settings, so there is no single meaningful timestep: DELTA is
    written as 1.0 and NSAVC as 1, i.e. "frame index", not physical time. Viewers use these
    only to label the frame slider.
    """
    if n_atoms <= 0:
        raise ValueError(f"n_atoms must be positive, got {n_atoms}")
    icntrl = [0] * 20
    icntrl[0] = int(n_frames)  # NSET
    icntrl[1] = int(istart)  # ISTART
    icntrl[2] = int(nsavc)  # NSAVC
    icntrl[3] = int(n_frames) * int(nsavc)  # NSTEP
    icntrl[8] = 0  # NFIXED — none, so frames are fixed-size
    icntrl[9] = struct.unpack("<i", struct.pack("<f", float(delta)))[0]
    icntrl[10] = 0  # no unit-cell record
    icntrl[11] = 0  # not 4D
    icntrl[19] = 24  # CHARMM version marker (>0 = CHARMM-style)

    fh.write(struct.pack("<i", 84))
    fh.write(b"CORD")
    fh.write(struct.pack("<20i", *icntrl))
    fh.write(struct.pack("<i", 84))

    block = title.ljust(80)[:80]
    fh.write(struct.pack("<i", 4 + len(block)))
    fh.write(struct.pack("<i", 1))  # NTITLE
    fh.write(block)
    fh.write(struct.pack("<i", 4 + len(block)))

    fh.write(struct.pack("<i", 4))
    fh.write(struct.pack("<i", int(n_atoms)))
    fh.write(struct.pack("<i", 4))


def append_frame(fh, xyz) -> None:
    """Append one frame. ``xyz`` is ``(n_atoms, 3)`` in ANGSTROMS (DCD's unit — callers
    holding nm must scale). Written as three separate x/y/z blocks, as the format requires."""
    arr = np.ascontiguousarray(xyz, dtype="<f4")
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(f"expected an (n_atoms, 3) array, got {arr.shape}")
    marker = struct.pack("<i", 4 * arr.shape[0])
    for axis in range(3):
        fh.write(marker)
        fh.write(np.ascontiguousarray(arr[:, axis]).tobytes())
        fh.write(marker)


def write_trajectory(
    path, n_atoms: int, frames_iter, n_frames: int, **header_kw
) -> int:
    """Write a whole DCD from an iterable of ``(n_atoms, 3)`` Angstrom arrays.

    ``n_frames`` is the COUNT DECLARED IN THE HEADER, written before any frame is seen (the
    header is fixed-size and comes first). If the iterable turns out shorter — a frame
    skipped for a topology mismatch — the header is rewritten with the true count on close,
    so NSET never overstates the file. Returns the number of frames actually written.
    """
    written = 0
    with open(path, "wb") as fh:
        write_header(fh, n_atoms, n_frames, **header_kw)
        for xyz in frames_iter:
            append_frame(fh, xyz)
            written += 1
        if written != n_frames:
            fh.seek(0)
            write_header(fh, n_atoms, written, **header_kw)
    return written
