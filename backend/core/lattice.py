"""
Honeycomb lattice utilities for bundle generation.

Implements caDNAno-compatible honeycomb lattice geometry and scaffold
direction rules.  Square lattice support is deferred (DTP-3).

Coordinate conventions
----------------------
- Helices run along the +Z axis.
- Lattice positions are in the XY plane.
- Row indices increase in +Y; column indices increase in +X.
- Parity: even_parity = (row % 2) == (col % 2)

Scaffold direction rule (caDNAno)
----------------------------------
- Even parity cell  → scaffold strand is FORWARD (5′→3′ along +Z, bp 0 → bp N-1)
- Odd  parity cell  → scaffold strand is REVERSE  (5′→3′ along -Z, bp N-1 → bp 0)

References
----------
- caDNAno2 source: virtualhelix.py, isDrawn5to3()
- Honeycomb lattice geometry: cadnano/cadnano2/data/lattice.py
"""

from __future__ import annotations

import math
from typing import List, Tuple

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_LATTICE_RADIUS,
    HONEYCOMB_ROW_PITCH,
)
from backend.core.models import Design, DesignMetadata, Direction, Domain, Helix, LatticeType, Strand, Vec3


# ── Parity and scaffold direction ─────────────────────────────────────────────


def honeycomb_cell_value(row: int, col: int) -> int:
    """Return the honeycomb cell classification value.

    Uses the unified rule ``(row + col % 2) % 3``:

    - 0  →  valid cell, scaffold runs FORWARD  (5′ at bp 0)
    - 1  →  valid cell, scaffold runs REVERSE  (5′ at bp N-1)
    - 2  →  hole (no helix placed here)

    This ensures every pair of adjacent valid cells is antiparallel,
    which is required for scaffold crossovers between neighbouring helices.
    """
    return (row + col % 2) % 3


def is_valid_honeycomb_cell(row: int, col: int) -> bool:
    """Return True if the cell (row, col) is a valid helix position."""
    return honeycomb_cell_value(row, col) != 2


def scaffold_direction_for_cell(row: int, col: int) -> Direction:
    """Return the scaffold strand direction for a honeycomb lattice cell.

    Assumes the cell is valid (cell_value != 2).
    """
    return Direction.FORWARD if honeycomb_cell_value(row, col) == 0 else Direction.REVERSE


# ── Lattice position ───────────────────────────────────────────────────────────


def honeycomb_position(row: int, col: int) -> Tuple[float, float]:
    """Return the XY centre of helix (row, col) in nanometres.

    caDNAno honeycomb coordinate system:
    - Even-column helices are offset +HONEYCOMB_LATTICE_RADIUS in Y relative
      to odd-column helices within the same row.

    Returns (x, y) in nm.
    """
    x = col * HONEYCOMB_COL_PITCH
    # Even-parity cells (matching column parity) sit one radius higher.
    if (col % 2) == 0:
        y = row * HONEYCOMB_ROW_PITCH + HONEYCOMB_LATTICE_RADIUS
    else:
        y = row * HONEYCOMB_ROW_PITCH
    return x, y


# ── Bundle design factory ──────────────────────────────────────────────────────


def make_bundle_design(
    cells: List[Tuple[int, int]],
    length_bp: int,
    name: str = "Bundle",
    plane: str = "XY",
) -> Design:
    """Create a Design from a list of (row, col) honeycomb lattice cells.

    Each cell becomes one Helix running along the axis perpendicular to the
    chosen plane.  Each helix gets one scaffold strand spanning its full length,
    with direction determined by caDNAno scaffold parity rules.

    Parameters
    ----------
    cells:
        List of (row, col) integer pairs selecting helix positions.
    length_bp:
        Number of base pairs per helix.
    name:
        Design name for metadata.
    plane:
        Lattice plane — one of ``"XY"``, ``"XZ"``, or ``"YZ"``.
        Helices run along the axis perpendicular to this plane:

        - ``"XY"`` → helices along Z  (axis_start=(lx,ly,0),      axis_end=(lx,ly,L))
        - ``"XZ"`` → helices along Y  (axis_start=(lx,0,ly),      axis_end=(lx,L,ly))
        - ``"YZ"`` → helices along X  (axis_start=(0,lx,ly),      axis_end=(L,lx,ly))

        where ``lx, ly = honeycomb_position(row, col)`` and ``L = length_bp × rise``.

    Returns
    -------
    A complete Design with helices and scaffold strands.  No crossovers are
    added (those are placed in Phase 3).
    """
    if length_bp < 1:
        raise ValueError(f"length_bp must be >= 1, got {length_bp}")
    if not cells:
        raise ValueError("cells list must not be empty")
    invalid = [(r, c) for r, c in cells if not is_valid_honeycomb_cell(r, c)]
    if invalid:
        raise ValueError(f"Cells are not valid honeycomb positions: {invalid}")
    valid_planes = {"XY", "XZ", "YZ"}
    if plane not in valid_planes:
        raise ValueError(f"plane must be one of {sorted(valid_planes)}, got {plane!r}")

    helix_length_nm = length_bp * BDNA_RISE_PER_BP
    helices: List[Helix] = []
    strands: List[Strand] = []

    for row, col in cells:
        lx, ly = honeycomb_position(row, col)
        helix_id = f"h_{plane}_{row}_{col}"
        scaf_id  = f"scaf_{plane}_{row}_{col}"
        stpl_id  = f"stpl_{plane}_{row}_{col}"

        if plane == "XY":
            axis_start = Vec3(x=lx, y=ly, z=0.0)
            axis_end   = Vec3(x=lx, y=ly, z=helix_length_nm)
        elif plane == "XZ":
            axis_start = Vec3(x=lx, y=0.0,             z=ly)
            axis_end   = Vec3(x=lx, y=helix_length_nm, z=ly)
        else:  # YZ
            axis_start = Vec3(x=0.0,             y=lx, z=ly)
            axis_end   = Vec3(x=helix_length_nm, y=lx, z=ly)

        direction = scaffold_direction_for_cell(row, col)

        # Phase offset: FORWARD helices (cell_value==0) start at 315° so that
        # backbone beads at bp=0 face their REVERSE neighbours, giving 4 valid
        # crossover positions per helix turn (every ~10.5 bp).
        # REVERSE helices (cell_value==1) use phase_offset=0.
        phase_offset = math.radians(315.0) if direction == Direction.FORWARD else 0.0

        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=length_bp,
            phase_offset=phase_offset,
        )
        helices.append(helix)

        # Convention: start_bp = 5′ end, end_bp = 3′ end (regardless of direction).
        if direction == Direction.FORWARD:
            scaf_start, scaf_end = 0, length_bp - 1
        else:
            scaf_start, scaf_end = length_bp - 1, 0

        scaffold = Strand(
            id=scaf_id,
            domains=[Domain(helix_id=helix_id, start_bp=scaf_start, end_bp=scaf_end, direction=direction)],
            is_scaffold=True,
        )
        strands.append(scaffold)

        # Placeholder staple covering the complementary backbone.
        # Direction is opposite to scaffold; start_bp = 5′ end convention.
        staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
        if staple_dir == Direction.FORWARD:
            stpl_start, stpl_end = 0, length_bp - 1
        else:
            stpl_start, stpl_end = length_bp - 1, 0

        staple = Strand(
            id=stpl_id,
            domains=[Domain(helix_id=helix_id, start_bp=stpl_start, end_bp=stpl_end, direction=staple_dir)],
            is_scaffold=False,
        )
        strands.append(staple)

    return Design(
        metadata=DesignMetadata(name=name),
        lattice_type=LatticeType.HONEYCOMB,
        helices=helices,
        strands=strands,
    )
