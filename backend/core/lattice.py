"""
Honeycomb lattice utilities for bundle generation.

Implements caDNAno-compatible honeycomb lattice geometry and scaffold
direction rules.

Coordinate conventions (caDNAno2 — adopted verbatim)
-----------------------------------------------------
- Helices run along the +Z axis.
- Lattice positions are in the XY plane.
- Cell (0,0) is at (x=0, y=0).  Column indices increase in +X.
- Row indices increase in −Y (y = −row × ROW_PITCH − stagger), so row 0
  sits at the top of the view when looking from +Z with Y-up (Three.js).
  This matches caDNAno2's Qt y-down convention: row 0 at top, rows downward.
- Parity: even_parity = (row + col) % 2 == 0  (cadnano2: isEvenParity)

Scaffold direction rule (caDNAno2 — adopted verbatim)
------------------------------------------------------
- Even parity cell  → scaffold strand is FORWARD (5′→3′ along +Z)
- Odd  parity cell  → scaffold strand is REVERSE  (5′→3′ along −Z)

Phase offset convention (cadnano2-derived)
------------------------------------------
- FORWARD helix phase_offset = π/2  (90°): backbone points in +X at bp=0
  → matches cadnano2 even-parity arrow pointing right at bp=0
- REVERSE helix phase_offset = 2π/3 (120°): reverse-strand backbone points
  in −X at bp=0, consistent with cadnano2 odd-parity arrow pointing left.

References
----------
- caDNAno2 source: honeycombpart.py, virtualhelix.py
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_HELIX_SPACING,
    HONEYCOMB_LATTICE_RADIUS,
    HONEYCOMB_ROW_PITCH,
    SQUARE_COL_PITCH,
    SQUARE_ROW_PITCH,
    SQUARE_TWIST_PER_BP_RAD,
)
from backend.core.models import Crossover, Design, DesignMetadata, Direction, Domain, HalfCrossover, Helix, LatticeType, OverhangSpec, Strand, StrandType, Vec3
from backend.core.sequences import domain_bp_range


# ── Global bp_start helper ────────────────────────────────────────────────────


def _helix_global_bp_start(axis_start: "Vec3", axis_end: "Vec3") -> int:
    """Compute the global bp_start from helix axis geometry.

    The global bp_start is defined as round(dot(axis_start, axis_hat) / BDNA_RISE_PER_BP),
    where axis_hat is the unit vector from axis_start to axis_end.

    For helices starting at the design origin (axis_start along-axis component = 0),
    bp_start = 0.  For offset helices (e.g. a second segment starting at Z=14 nm),
    bp_start = round(14.0 / 0.334) = 42.

    This ensures the invariant:
        axis_point(global_bp) = axis_start + (global_bp - bp_start) * BDNA_RISE_PER_BP * axis_hat
    """
    ax = np.array([axis_end.x - axis_start.x,
                   axis_end.y - axis_start.y,
                   axis_end.z - axis_start.z], dtype=float)
    length = float(np.linalg.norm(ax))
    if length < 1e-12:
        return 0
    hat = ax / length
    start = np.array([axis_start.x, axis_start.y, axis_start.z], dtype=float)
    return round(float(np.dot(start, hat)) / BDNA_RISE_PER_BP)


# ── Parity and scaffold direction ─────────────────────────────────────────────


def honeycomb_cell_value(row: int, col: int) -> int:
    """Return the honeycomb cell parity value (cadnano2 convention).

    Uses the parity rule ``(row + col) % 2``:

    - 0  →  even parity, scaffold runs FORWARD  (5′ at bp 0)
    - 1  →  odd  parity, scaffold runs REVERSE  (5′ at bp N-1)

    All cells are valid — there are no holes in cadnano2's coordinate system.
    Adjacent cells always have opposite parities, guaranteeing every
    nearest-neighbour pair is antiparallel.
    """
    return (row + col) % 2


def is_valid_honeycomb_cell(row: int, col: int) -> bool:
    """Return True — all cells are valid in cadnano2's honeycomb coordinate system."""
    return True


def scaffold_direction_for_cell(row: int, col: int) -> Direction:
    """Return the scaffold strand direction for a honeycomb lattice cell.

    caDNAno2 convention: even parity (row + col) % 2 == 0 → FORWARD; odd → REVERSE.
    """
    return Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE


# ── Lattice position ───────────────────────────────────────────────────────────


def honeycomb_position(row: int, col: int) -> Tuple[float, float]:
    """Return the XY centre of helix (row, col) in nanometres.

    Standard right-handed coordinates (origin at row=0, col=0):
      x =  col × COL_PITCH
      y =  row × ROW_PITCH + LATTICE_RADIUS   if odd parity
      y =  row × ROW_PITCH                    if even parity

    Row 0, col 0 (even parity) is at the origin.  Increasing row → increasing y.

    Returns (x, y) in nm.
    """
    x   = col * HONEYCOMB_COL_PITCH
    odd = (row + col) % 2
    y   = row * HONEYCOMB_ROW_PITCH + (HONEYCOMB_LATTICE_RADIUS if odd else 0.0)
    return x, y


# ── Square lattice helpers ────────────────────────────────────────────────────


def square_cell_direction(row: int, col: int) -> Direction:
    """Return the scaffold direction for a square lattice cell.

    caDNAno2 convention: even parity (row + col) % 2 == 0 → FORWARD, else REVERSE.
    """
    return Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE


def square_position(row: int, col: int) -> Tuple[float, float]:
    """Return the XY centre of helix (row, col) on a 2.25 nm square grid.

    Standard right-handed coordinates: x = col × PITCH, y = row × PITCH.
    Row 0, col 0 is at the origin; both x and y increase positively.
    Returns (x, y) in nm.
    """
    return col * SQUARE_COL_PITCH, row * SQUARE_ROW_PITCH


def _lattice_position(row: int, col: int, lattice_type: "LatticeType") -> Tuple[float, float]:  # type: ignore[name-defined]
    """Dispatch to the correct position function for the given lattice type."""
    if lattice_type == LatticeType.SQUARE:
        return square_position(row, col)
    return honeycomb_position(row, col)


def _lattice_direction(row: int, col: int, lattice_type: "LatticeType") -> Direction:  # type: ignore[name-defined]
    """Dispatch to the correct scaffold direction function for the given lattice type."""
    if lattice_type == LatticeType.SQUARE:
        return square_cell_direction(row, col)
    return scaffold_direction_for_cell(row, col)


def _lattice_phase_offset(direction: Direction, lattice_type: "LatticeType") -> float:  # type: ignore[name-defined]
    """Return the phase offset (radians at bp=0) for a helix of the given direction.

    Derived from cadnano2's twistOffset so that at bp=0 the backbone position
    matches cadnano2's slice-view arrow direction (helix_angle == SVG_angle), plus a
    half-bp-twist Holliday Junction correction: real DNA origami minimises the distance
    between the two crossover strands, which shifts every helix by +½ bp of twist.

    HC  (twistOffset=0°, correction=+17.15°):    FORWARD=107.15°, REVERSE=77.15°
    SQ  (twistOffset=196.875°, correction=+16.875°): FORWARD=303.75°, REVERSE=273.75°

    Formula: phase_offset = SVG_scaffold_base + ½·twist_per_bp
    """
    if lattice_type == LatticeType.SQUARE:
        base = math.radians(286.875) if direction == Direction.FORWARD else math.radians(256.875)
        return base + SQUARE_TWIST_PER_BP_RAD / 2
    base = math.radians(90.0) if direction == Direction.FORWARD else math.radians(60.0)
    return base + BDNA_TWIST_PER_BP_RAD / 2


def _lattice_twist(lattice_type: "LatticeType") -> float:  # type: ignore[name-defined]
    """Return twist_per_bp_rad for the given lattice type."""
    if lattice_type == LatticeType.SQUARE:
        return SQUARE_TWIST_PER_BP_RAD
    return BDNA_TWIST_PER_BP_RAD


def helix_canonical_axis(
    helix: "Helix",  # type: ignore[name-defined]
    lattice_type: "LatticeType",  # type: ignore[name-defined]
) -> "tuple[float, float, float, float]":
    """Return (x, y, base_phase_offset, twist_per_bp_rad) derived from helix.grid_pos.

    The (x, y) values are the canonical XY centre of the helix in nanometres,
    computed from the lattice formula.  base_phase_offset is the phase at
    global bp index 0 (caller must add bp_start * twist to get the phase
    baked for geometry.py's local-bp=0 convention).

    Raises ValueError when helix.grid_pos is None.
    Used by deformation.py to normalise grid-derived helices before geometry.
    """
    if helix.grid_pos is None:
        raise ValueError(f"Helix {helix.id!r} has no grid_pos")
    row, col  = helix.grid_pos
    x, y      = _lattice_position(row, col, lattice_type)
    direction = _lattice_direction(row, col, lattice_type)
    phase     = _lattice_phase_offset(direction, lattice_type)
    twist     = _lattice_twist(lattice_type)
    return x, y, phase, twist


# ── Bundle design factory ──────────────────────────────────────────────────────


def make_bundle_design(
    cells: List[Tuple[int, int]],
    length_bp: int,
    name: str = "Bundle",
    plane: str = "XY",
    offset_nm: float = 0.0,
    id_suffix: str = "",
    strand_filter: str = "both",
    lattice_type: "LatticeType" = LatticeType.HONEYCOMB,  # type: ignore[name-defined]
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
        Number of base pairs per helix.  May be negative: negative values
        extrude in the -axis direction (axis_end < axis_start along the normal).
        Strand directions are always determined by honeycomb parity regardless
        of sign.
    name:
        Design name for metadata.
    plane:
        Lattice plane — one of ``"XY"``, ``"XZ"``, or ``"YZ"``.
        Helices run along the axis perpendicular to this plane:

        - ``"XY"`` → helices along Z  (axis_start=(lx,ly,offset),  axis_end=(lx,ly,offset+L))
        - ``"XZ"`` → helices along Y  (axis_start=(lx,offset,ly),  axis_end=(lx,offset+L,ly))
        - ``"YZ"`` → helices along X  (axis_start=(offset,lx,ly),  axis_end=(offset+L,lx,ly))

        where ``lx, ly = honeycomb_position(row, col)`` and ``L = length_bp × rise`` (signed).
    offset_nm:
        Starting position along the helix axis in nm.  The helix axis_start
        is placed at this offset.  Defaults to 0.
    id_suffix:
        String appended to generated helix/strand IDs to ensure uniqueness
        when adding segments to an existing design.

    strand_filter:
        Which strands to create per helix.  ``"both"`` (default) creates one
        scaffold and one staple strand.  ``"scaffold"`` creates only the
        scaffold strand.  ``"staples"`` creates only the staple strand.

    Returns
    -------
    A complete Design with helices and the requested strand set.  No crossovers
    are added (those are placed in a later phase).
    """
    include_scaffold = strand_filter in ("both", "scaffold")
    include_staples  = strand_filter in ("both", "staples")
    actual_length = abs(length_bp)
    if actual_length < 1:
        raise ValueError(f"length_bp magnitude must be >= 1, got {length_bp}")
    if not cells:
        raise ValueError("cells list must not be empty")
    valid_planes = {"XY", "XZ", "YZ"}
    if plane not in valid_planes:
        raise ValueError(f"plane must be one of {sorted(valid_planes)}, got {plane!r}")

    helix_length_nm = length_bp * BDNA_RISE_PER_BP  # signed
    helices: List[Helix] = []
    strands: List[Strand] = []

    for row, col in cells:
        lx, ly = _lattice_position(row, col, lattice_type)
        helix_id = f"h_{plane}_{row}_{col}{id_suffix}"
        scaf_id  = f"scaf_{plane}_{row}_{col}{id_suffix}"
        stpl_id  = f"stpl_{plane}_{row}_{col}{id_suffix}"

        if plane == "XY":
            axis_start = Vec3(x=lx, y=ly, z=offset_nm)
            axis_end   = Vec3(x=lx, y=ly, z=offset_nm + helix_length_nm)
        elif plane == "XZ":
            axis_start = Vec3(x=lx, y=offset_nm,               z=ly)
            axis_end   = Vec3(x=lx, y=offset_nm + helix_length_nm, z=ly)
        else:  # YZ
            axis_start = Vec3(x=offset_nm,               y=lx, z=ly)
            axis_end   = Vec3(x=offset_nm + helix_length_nm, y=lx, z=ly)

        direction    = _lattice_direction(row, col, lattice_type)
        phase_offset = _lattice_phase_offset(direction, lattice_type)
        twist        = _lattice_twist(lattice_type)

        bp_start_val = _helix_global_bp_start(axis_start, axis_end)
        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            bp_start=bp_start_val,
            phase_offset=phase_offset,
            twist_per_bp_rad=twist,
            direction=direction,
        )
        helices.append(helix)

        # Convention: start_bp = 5′ end, end_bp = 3′ end (regardless of direction).
        # Domain bp values are global: local 0..N-1 maps to bp_start_val..bp_start_val+N-1.
        if direction == Direction.FORWARD:
            scaf_start, scaf_end = bp_start_val, bp_start_val + actual_length - 1
        else:
            scaf_start, scaf_end = bp_start_val + actual_length - 1, bp_start_val

        if include_scaffold:
            scaffold = Strand(
                id=scaf_id,
                domains=[Domain(helix_id=helix_id, start_bp=scaf_start, end_bp=scaf_end, direction=direction)],
                strand_type=StrandType.SCAFFOLD,
            )
            strands.append(scaffold)

        if include_staples:
            # Placeholder staple covering the complementary backbone.
            # Direction is opposite to scaffold; start_bp = 5′ end convention.
            staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
            if staple_dir == Direction.FORWARD:
                stpl_start, stpl_end = bp_start_val, bp_start_val + actual_length - 1
            else:
                stpl_start, stpl_end = bp_start_val + actual_length - 1, bp_start_val

            staple = Strand(
                id=stpl_id,
                domains=[Domain(helix_id=helix_id, start_bp=stpl_start, end_bp=stpl_end, direction=staple_dir)],
                strand_type=StrandType.STAPLE,
            )
            strands.append(staple)

    return Design(
        metadata=DesignMetadata(name=name),
        lattice_type=lattice_type,
        helices=helices,
        strands=strands,
    )


def _unique_id(base: str, existing: set) -> str:
    """Return *base* if not in *existing*, else *base_0*, *base_1*, …"""
    if base not in existing:
        return base
    i = 0
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


def make_bundle_segment(
    existing_design: Design,
    cells: List[Tuple[int, int]],
    length_bp: int,
    plane: str = "XY",
    offset_nm: float = 0.0,
    strand_filter: str = "both",
) -> Design:
    """Append new helices and strands to *existing_design* and return the combined Design.

    Generates collision-safe IDs by appending ``_1``, ``_2``, … as needed.
    Raises ``ValueError`` for invalid cells/planes or length magnitude < 1.

    Parameters
    ----------
    existing_design:
        The design to extend.
    cells:
        (row, col) pairs to add.
    length_bp:
        Base pairs per new helix.  May be negative (extrudes in -axis direction).
    plane:
        Lattice plane (``"XY"``, ``"XZ"``, or ``"YZ"``).
    offset_nm:
        Position of the new helix segment's axis_start along the plane normal.
    """
    actual_length = abs(length_bp)
    if actual_length < 1:
        raise ValueError(f"length_bp magnitude must be >= 1, got {length_bp}")
    if not cells:
        raise ValueError("cells list must not be empty")
    lt = existing_design.lattice_type
    valid_planes = {"XY", "XZ", "YZ"}
    if plane not in valid_planes:
        raise ValueError(f"plane must be one of {sorted(valid_planes)}, got {plane!r}")

    existing_helix_ids:  set = {h.id for h in existing_design.helices}
    existing_strand_ids: set = {s.id for s in existing_design.strands}

    helix_length_nm = length_bp * BDNA_RISE_PER_BP  # signed
    new_helices: List[Helix] = []
    new_strands: List[Strand] = []

    for row, col in cells:
        lx, ly = _lattice_position(row, col, lt)
        base_hid = f"h_{plane}_{row}_{col}"
        base_sid = f"scaf_{plane}_{row}_{col}"
        base_tid = f"stpl_{plane}_{row}_{col}"

        # IDs must be unique across existing AND newly-added items in this batch.
        all_helix_ids  = existing_helix_ids  | {h.id for h in new_helices}
        all_strand_ids = existing_strand_ids | {s.id for s in new_strands}

        helix_id = _unique_id(base_hid, all_helix_ids)
        scaf_id  = _unique_id(base_sid, all_strand_ids)
        stpl_id  = _unique_id(base_tid, all_strand_ids | {scaf_id})

        if plane == "XY":
            axis_start = Vec3(x=lx, y=ly, z=offset_nm)
            axis_end   = Vec3(x=lx, y=ly, z=offset_nm + helix_length_nm)
        elif plane == "XZ":
            axis_start = Vec3(x=lx, y=offset_nm,                    z=ly)
            axis_end   = Vec3(x=lx, y=offset_nm + helix_length_nm,  z=ly)
        else:  # YZ
            axis_start = Vec3(x=offset_nm,                    y=lx, z=ly)
            axis_end   = Vec3(x=offset_nm + helix_length_nm,  y=lx, z=ly)

        direction    = _lattice_direction(row, col, lt)
        phase_offset = _lattice_phase_offset(direction, lt)
        twist        = _lattice_twist(lt)

        bp_start_val = _helix_global_bp_start(axis_start, axis_end)
        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            bp_start=bp_start_val,
            phase_offset=phase_offset,
            twist_per_bp_rad=twist,
            direction=direction,
        )
        new_helices.append(helix)

        if direction == Direction.FORWARD:
            scaf_start, scaf_end = bp_start_val, bp_start_val + actual_length - 1
        else:
            scaf_start, scaf_end = bp_start_val + actual_length - 1, bp_start_val

        include_scaffold = strand_filter in ("both", "scaffold")
        include_staples  = strand_filter in ("both", "staples")

        if include_scaffold:
            new_strands.append(Strand(
                id=scaf_id,
                domains=[Domain(helix_id=helix_id, start_bp=scaf_start, end_bp=scaf_end, direction=direction)],
                strand_type=StrandType.SCAFFOLD,
            ))

        if include_staples:
            staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
            if staple_dir == Direction.FORWARD:
                stpl_start, stpl_end = bp_start_val, bp_start_val + actual_length - 1
            else:
                stpl_start, stpl_end = bp_start_val + actual_length - 1, bp_start_val

            new_strands.append(Strand(
                id=stpl_id,
                domains=[Domain(helix_id=helix_id, start_bp=stpl_start, end_bp=stpl_end, direction=staple_dir)],
                strand_type=StrandType.STAPLE,
            ))

    return existing_design.copy_with(
        helices=existing_design.helices + new_helices,
        strands=existing_design.strands + new_strands,
    )


def _find_continuation_helix(
    helices: List[Helix],
    row: int,
    col: int,
    plane: str,
    offset_nm: float,
) -> Helix | None:
    """Return the helix at lattice cell (row, col) whose axis START or END is at offset_nm (±5% rise).

    Used to detect coaxial stacking targets for continuation extrusion.
    """
    prefix = f"h_{plane}_{row}_{col}"
    tol = BDNA_RISE_PER_BP * 0.05
    for h in helices:
        # Match exact cell ID ("h_XY_0_1") or a numbered continuation ("h_XY_0_1_2").
        # startswith(prefix) alone is wrong for designs with multi-digit columns: the
        # prefix "h_XY_0_1" is a leading substring of "h_XY_0_10", "h_XY_0_11", etc.
        if not (h.id == prefix or h.id.startswith(prefix + "_")):
            continue
        if plane == "XY":
            end_offset   = h.axis_end.z
            start_offset = h.axis_start.z
        elif plane == "XZ":
            end_offset   = h.axis_end.y
            start_offset = h.axis_start.y
        else:  # YZ
            end_offset   = h.axis_end.x
            start_offset = h.axis_start.x
        if abs(end_offset - offset_nm) < tol or abs(start_offset - offset_nm) < tol:
            return h
    return None


def _find_same_cell_helix(
    helices: List[Helix],
    row: int,
    col: int,
    plane: str,
    offset_nm: float,
) -> "Helix | None":
    """Return the helix at lattice cell (row, col) whose axis END is below offset_nm (gap case).

    Used to detect gap-continuation targets: a cell that already has a helix ending
    below the new extrusion start, leaving a gap between the two domains.
    Only returns a helix whose end is strictly below offset_nm (not adjacent — that case
    is handled by _find_continuation_helix).
    """
    prefix = f"h_{plane}_{row}_{col}"
    tol = BDNA_RISE_PER_BP * 0.05
    for h in helices:
        if not (h.id == prefix or h.id.startswith(prefix + "_")):
            continue
        if plane == "XY":
            end_offset = h.axis_end.z
        elif plane == "XZ":
            end_offset = h.axis_end.y
        else:  # YZ
            end_offset = h.axis_end.x
        if end_offset < offset_nm - tol:
            return h
    return None


def make_bundle_continuation(
    existing_design: Design,
    cells: List[Tuple[int, int]],
    length_bp: int,
    plane: str = "XY",
    offset_nm: float = 0.0,
    strand_filter: str = "both",
    extend_inplace: bool = False,
) -> Design:
    """Append a bundle segment to *existing_design*, continuing existing strands where possible.

    For each cell in *cells*:
    - If a helix at that lattice position ends at *offset_nm* (within ±5% rise): create a
      new helix starting at *offset_nm* and append a new domain to every strand that has
      a domain on the ending helix (continuation mode).
    - Otherwise: create a new helix and new scaffold + staple strands (same as
      ``make_bundle_segment``).

    Parameters
    ----------
    existing_design:
        The design to extend.
    cells:
        (row, col) pairs to extrude.
    length_bp:
        Base pairs per new helix.  May be negative (extrudes in -axis direction).
    plane:
        Lattice plane (``"XY"``, ``"XZ"``, or ``"YZ"``).
    offset_nm:
        Position of the new segment's axis_start along the plane normal.
    """
    actual_length = abs(length_bp)
    if actual_length < 1:
        raise ValueError(f"length_bp magnitude must be >= 1, got {length_bp}")
    if not cells:
        raise ValueError("cells list must not be empty")
    lt = existing_design.lattice_type
    valid_planes = {"XY", "XZ", "YZ"}
    if plane not in valid_planes:
        raise ValueError(f"plane must be one of {sorted(valid_planes)}, got {plane!r}")

    existing_helix_ids:  set = {h.id for h in existing_design.helices}
    existing_strand_ids: set = {s.id for s in existing_design.strands}

    actual_length_nm = actual_length * BDNA_RISE_PER_BP   # always positive
    helix_dir_nm     = length_bp    * BDNA_RISE_PER_BP   # signed — carries user direction
    new_helices:       List[Helix]  = []
    new_strands:       List[Strand] = []   # strands for fresh (non-continuation) cells
    # strand_id → {'prepend': [Domain, ...], 'append': [Domain, ...]}
    domain_additions:  dict         = {}
    # helix_id → replacement Helix (backward extension keeps the same ID, grows axis_start)
    helix_replacements: dict[str, "Helix"] = {}
    # new_helix_id → cont_helix_id: forward non-inplace continuations that need cluster update
    continuation_map: dict[str, str] = {}

    for row, col in cells:
        lx, ly = _lattice_position(row, col, lt)
        base_hid = f"h_{plane}_{row}_{col}"

        all_helix_ids  = existing_helix_ids  | {h.id for h in new_helices}
        all_strand_ids = existing_strand_ids | {s.id for s in new_strands}

        direction    = _lattice_direction(row, col, lt)
        phase_offset = _lattice_phase_offset(direction, lt)

        cont_helix = _find_continuation_helix(existing_design.helices, row, col, plane, offset_nm)
        gap_helix  = (
            None if cont_helix is not None
            else _find_same_cell_helix(existing_design.helices, row, col, plane, offset_nm)
        )

        _tol = BDNA_RISE_PER_BP * 0.05
        if cont_helix is not None:
            if plane == "XY":
                is_end_at_offset = abs(cont_helix.axis_end.z - offset_nm) < _tol
            elif plane == "XZ":
                is_end_at_offset = abs(cont_helix.axis_end.y - offset_nm) < _tol
            else:
                is_end_at_offset = abs(cont_helix.axis_end.x - offset_nm) < _tol
            forward_extrude = is_end_at_offset
        else:
            is_end_at_offset = True
            forward_extrude  = True

        if cont_helix is not None and not forward_extrude:
            # ── Backward continuation: grow the existing helix toward lower offset ──
            #
            # Instead of creating a new helix, we extend axis_start backward and
            # increase length_bp.  With global bp indexing, existing domain bp values
            # are already correct (global) and do NOT need shifting — they represent
            # the same physical positions.  The new backward bps occupy global indices
            # [cont_helix.bp_start - actual_length .. cont_helix.bp_start - 1].
            # Phase continuity is maintained by correcting phase_offset so that each
            # original bp retains its absolute rotational angle at its physical position.
            if plane == "XY":
                new_axis_start = Vec3(x=cont_helix.axis_start.x,
                                      y=cont_helix.axis_start.y,
                                      z=cont_helix.axis_start.z - actual_length_nm)
            elif plane == "XZ":
                new_axis_start = Vec3(x=cont_helix.axis_start.x,
                                      y=cont_helix.axis_start.y - actual_length_nm,
                                      z=cont_helix.axis_start.z)
            else:
                new_axis_start = Vec3(x=cont_helix.axis_start.x - actual_length_nm,
                                      y=cont_helix.axis_start.y,
                                      z=cont_helix.axis_start.z)

            # New bp_start is shifted backward by actual_length.
            new_bp_start = cont_helix.bp_start - actual_length

            # The phase_offset is the rotational angle at local_i=0 (axis_start).
            # With the new axis_start moved backward by actual_length bps, local_i=0
            # now corresponds to the new backward start, and local_i=actual_length
            # corresponds to the original axis_start (old bp_start).
            # The original phase_offset produced angle = phase_offset + 0 * twist at
            # the original local_i=0.  The new local_i=actual_length must produce the
            # same angle, so: new_phase + actual_length * twist = cont_helix.phase_offset
            corrected_phase = (
                cont_helix.phase_offset - actual_length * cont_helix.twist_per_bp_rad
            )
            extended_helix = Helix(
                id=cont_helix.id,
                axis_start=new_axis_start,
                axis_end=cont_helix.axis_end,
                length_bp=cont_helix.length_bp + actual_length,
                bp_start=new_bp_start,
                phase_offset=corrected_phase,
                twist_per_bp_rad=cont_helix.twist_per_bp_rad,
                loop_skips=cont_helix.loop_skips,  # bp_index values are global; unchanged
                direction=cont_helix.direction,
            )
            helix_replacements[cont_helix.id] = extended_helix
            helix_id = cont_helix.id

            # Add domains covering the new backward global bps.
            include_scaffold = strand_filter in ("both", "scaffold")
            include_staples  = strand_filter in ("both", "staples")
            seen_strand_ids: set = set()
            for strand in existing_design.strands:
                if strand.id in seen_strand_ids:
                    continue
                if strand.strand_type == StrandType.SCAFFOLD and not include_scaffold:
                    continue
                if strand.strand_type == StrandType.STAPLE and not include_staples:
                    continue
                for domain in strand.domains:
                    if domain.helix_id == cont_helix.id:
                        d = domain.direction
                        if d == Direction.FORWARD:
                            # FORWARD: 5′=new_bp_start, 3′=cont_helix.bp_start-1
                            new_dom = Domain(
                                helix_id=helix_id,
                                start_bp=new_bp_start,
                                end_bp=cont_helix.bp_start - 1,
                                direction=d)
                            should_prepend = True   # FORWARD: new bps precede existing
                        else:
                            # REVERSE: 5′=cont_helix.bp_start-1, 3′=new_bp_start
                            new_dom = Domain(
                                helix_id=helix_id,
                                start_bp=cont_helix.bp_start - 1,
                                end_bp=new_bp_start,
                                direction=d)
                            should_prepend = False  # REVERSE: new bps follow existing (strand goes high→low)
                        entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                        if should_prepend:
                            entry["prepend"].append(new_dom)
                        else:
                            entry["append"].append(new_dom)
                        seen_strand_ids.add(strand.id)
                        break  # one domain per strand per continuation helix

        elif cont_helix is not None and forward_extrude and extend_inplace:
            # ── Forward in-place: grow the existing helix toward higher offset ──
            #
            # The existing helix's axis_end is shifted forward; length_bp increases.
            # Existing bp indices are unchanged (global).  New bps occupy global
            # [bp_start+old_length .. bp_start+old_length+ext-1].
            old_length = cont_helix.length_bp
            new_global_start = cont_helix.bp_start + old_length  # first new global bp
            if plane == "XY":
                new_axis_end = Vec3(x=cont_helix.axis_end.x,
                                    y=cont_helix.axis_end.y,
                                    z=cont_helix.axis_end.z + actual_length_nm)
            elif plane == "XZ":
                new_axis_end = Vec3(x=cont_helix.axis_end.x,
                                    y=cont_helix.axis_end.y + actual_length_nm,
                                    z=cont_helix.axis_end.z)
            else:
                new_axis_end = Vec3(x=cont_helix.axis_end.x + actual_length_nm,
                                    y=cont_helix.axis_end.y,
                                    z=cont_helix.axis_end.z)
            extended_helix = Helix(
                id=cont_helix.id,
                axis_start=cont_helix.axis_start,
                axis_end=new_axis_end,
                length_bp=old_length + actual_length,
                bp_start=cont_helix.bp_start,
                phase_offset=cont_helix.phase_offset,
                twist_per_bp_rad=cont_helix.twist_per_bp_rad,
                loop_skips=cont_helix.loop_skips,
                direction=cont_helix.direction,
            )
            helix_replacements[cont_helix.id] = extended_helix
            helix_id = cont_helix.id

            include_scaffold = strand_filter in ("both", "scaffold")
            include_staples  = strand_filter in ("both", "staples")
            seen_strand_ids: set = set()
            for strand in existing_design.strands:
                if strand.id in seen_strand_ids:
                    continue
                if strand.strand_type == StrandType.SCAFFOLD and not include_scaffold:
                    continue
                if strand.strand_type == StrandType.STAPLE and not include_staples:
                    continue
                for domain in strand.domains:
                    if domain.helix_id == cont_helix.id:
                        d = domain.direction
                        if d == Direction.FORWARD:
                            # New far bps: global [new_global_start .. new_global_start+ext-1]
                            new_dom = Domain(
                                helix_id=helix_id,
                                start_bp=new_global_start,
                                end_bp=new_global_start + actual_length - 1,
                                direction=d)
                            entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                            entry["append"].append(new_dom)
                        else:
                            # REVERSE: far end is 5' (high global bp).
                            new_dom = Domain(
                                helix_id=helix_id,
                                start_bp=new_global_start + actual_length - 1,
                                end_bp=new_global_start,
                                direction=d)
                            entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                            entry["prepend"].append(new_dom)
                        seen_strand_ids.add(strand.id)
                        break

        elif gap_helix is not None:
            # ── Gap continuation: extend existing helix across a gap ──
            #
            # A helix at the same XY cell ends below offset_nm (not adjacent).
            # Instead of creating a new "h_XY_r_c_0" helix, we extend the existing
            # helix's axis_end to cover the new domain, leaving a bp gap in coverage.
            h = gap_helix
            if plane == "XY":
                h_axis_lo = h.axis_start.z
            elif plane == "XZ":
                h_axis_lo = h.axis_start.y
            else:
                h_axis_lo = h.axis_start.x

            local_bp_offset = round((offset_nm - h_axis_lo) / BDNA_RISE_PER_BP)
            new_length_bp   = local_bp_offset + actual_length
            new_bp_start_val = h.bp_start + local_bp_offset  # global bp of new domain start

            if plane == "XY":
                new_axis_end = Vec3(x=h.axis_end.x, y=h.axis_end.y,
                                    z=h.axis_start.z + new_length_bp * BDNA_RISE_PER_BP)
            elif plane == "XZ":
                new_axis_end = Vec3(x=h.axis_end.x,
                                    y=h.axis_start.y + new_length_bp * BDNA_RISE_PER_BP,
                                    z=h.axis_end.z)
            else:
                new_axis_end = Vec3(x=h.axis_start.x + new_length_bp * BDNA_RISE_PER_BP,
                                    y=h.axis_end.y, z=h.axis_end.z)

            extended_helix = Helix(
                id=h.id,
                axis_start=h.axis_start,
                axis_end=new_axis_end,
                length_bp=new_length_bp,
                bp_start=h.bp_start,
                phase_offset=h.phase_offset,
                twist_per_bp_rad=h.twist_per_bp_rad,
                loop_skips=h.loop_skips,
                direction=h.direction,
            )
            helix_replacements[h.id] = extended_helix
            helix_id = h.id

            # Create NEW scaffold + staple strands for the new domain region.
            include_scaffold = strand_filter in ("both", "scaffold")
            include_staples  = strand_filter in ("both", "staples")
            all_strand_ids_g = existing_strand_ids | {s.id for s in new_strands}
            base_sid = f"scaf_{plane}_{row}_{col}"
            base_tid = f"stpl_{plane}_{row}_{col}"
            scaf_id  = _unique_id(base_sid, all_strand_ids_g)
            stpl_id  = _unique_id(base_tid, all_strand_ids_g | {scaf_id})

            if direction == Direction.FORWARD:
                scaf_start = new_bp_start_val
                scaf_end   = new_bp_start_val + actual_length - 1
            else:
                scaf_start = new_bp_start_val + actual_length - 1
                scaf_end   = new_bp_start_val

            if include_scaffold:
                new_strands.append(Strand(
                    id=scaf_id,
                    domains=[Domain(helix_id=helix_id, start_bp=scaf_start,
                                    end_bp=scaf_end, direction=direction)],
                    strand_type=StrandType.SCAFFOLD,
                ))

            if include_staples:
                staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
                if staple_dir == Direction.FORWARD:
                    stpl_start = new_bp_start_val
                    stpl_end   = new_bp_start_val + actual_length - 1
                else:
                    stpl_start = new_bp_start_val + actual_length - 1
                    stpl_end   = new_bp_start_val

                new_strands.append(Strand(
                    id=stpl_id,
                    domains=[Domain(helix_id=helix_id, start_bp=stpl_start,
                                    end_bp=stpl_end, direction=staple_dir)],
                    strand_type=StrandType.STAPLE,
                ))

        else:
            # ── Forward continuation OR fresh cell: create a new helix ──
            helix_id = _unique_id(base_hid, all_helix_ids)

            if plane == "XY":
                axis_start = Vec3(x=lx, y=ly, z=offset_nm)
                axis_end   = Vec3(x=lx, y=ly, z=offset_nm + helix_dir_nm)
            elif plane == "XZ":
                axis_start = Vec3(x=lx, y=offset_nm,               z=ly)
                axis_end   = Vec3(x=lx, y=offset_nm + helix_dir_nm, z=ly)
            else:  # YZ
                axis_start = Vec3(x=offset_nm,               y=lx, z=ly)
                axis_end   = Vec3(x=offset_nm + helix_dir_nm, y=lx, z=ly)

            bp_start_val = _helix_global_bp_start(axis_start, axis_end)
            helix = Helix(
                id=helix_id,
                axis_start=axis_start,
                axis_end=axis_end,
                length_bp=actual_length,
                bp_start=bp_start_val,
                phase_offset=phase_offset,
                twist_per_bp_rad=_lattice_twist(lt),
                direction=direction,
            )
            new_helices.append(helix)

            if cont_helix is not None:
                # Forward continuation: extend each matching strand with global bp domain.
                continuation_map[helix_id] = cont_helix.id
                include_scaffold = strand_filter in ("both", "scaffold")
                include_staples  = strand_filter in ("both", "staples")
                seen_strand_ids: set = set()
                for strand in existing_design.strands:
                    if strand.id in seen_strand_ids:
                        continue
                    if strand.strand_type == StrandType.SCAFFOLD and not include_scaffold:
                        continue
                    if strand.strand_type == StrandType.STAPLE and not include_staples:
                        continue
                    for domain in strand.domains:
                        if domain.helix_id == cont_helix.id:
                            d = domain.direction
                            if d == Direction.FORWARD:
                                new_dom = Domain(
                                    helix_id=helix_id,
                                    start_bp=bp_start_val,
                                    end_bp=bp_start_val + actual_length - 1,
                                    direction=d)
                                # FORWARD at axis_end → append; at axis_start → prepend
                                should_prepend = not is_end_at_offset
                            else:
                                new_dom = Domain(
                                    helix_id=helix_id,
                                    start_bp=bp_start_val + actual_length - 1,
                                    end_bp=bp_start_val,
                                    direction=d)
                                # REVERSE at axis_end (5′) → prepend; at axis_start (3′) → append
                                should_prepend = is_end_at_offset
                            entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                            if should_prepend:
                                entry["prepend"].append(new_dom)
                            else:
                                entry["append"].append(new_dom)
                            seen_strand_ids.add(strand.id)
                            break  # one domain per strand per continuation helix
            else:
                # Fresh cell: new scaffold + staple strands with global bp values.
                include_scaffold = strand_filter in ("both", "scaffold")
                include_staples  = strand_filter in ("both", "staples")
                base_sid = f"scaf_{plane}_{row}_{col}"
                base_tid = f"stpl_{plane}_{row}_{col}"
                scaf_id  = _unique_id(base_sid, all_strand_ids)
                stpl_id  = _unique_id(base_tid, all_strand_ids | {scaf_id})

                if direction == Direction.FORWARD:
                    scaf_start, scaf_end = bp_start_val, bp_start_val + actual_length - 1
                else:
                    scaf_start, scaf_end = bp_start_val + actual_length - 1, bp_start_val

                if include_scaffold:
                    new_strands.append(Strand(
                        id=scaf_id,
                        domains=[Domain(helix_id=helix_id, start_bp=scaf_start,
                                        end_bp=scaf_end, direction=direction)],
                        strand_type=StrandType.SCAFFOLD,
                    ))

                if include_staples:
                    staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
                    if staple_dir == Direction.FORWARD:
                        stpl_start, stpl_end = bp_start_val, bp_start_val + actual_length - 1
                    else:
                        stpl_start, stpl_end = bp_start_val + actual_length - 1, bp_start_val

                    new_strands.append(Strand(
                        id=stpl_id,
                        domains=[Domain(helix_id=helix_id, start_bp=stpl_start,
                                        end_bp=stpl_end, direction=staple_dir)],
                        strand_type=StrandType.STAPLE,
                    ))

    # Rebuild existing strands: apply prepend/append domain additions.
    # With global bp indexing, backward-extended helices no longer shift their
    # existing domain bp values — they're already global and correct.
    updated_strands: List[Strand] = []
    for strand in existing_design.strands:
        updated = strand
        if strand.id in domain_additions:
            entry = domain_additions[strand.id]
            raw_domains = entry["prepend"] + list(updated.domains) + entry["append"]
            updated = updated.model_copy(update={
                "domains": _merge_adjacent_domains(raw_domains)
            })
        updated_strands.append(updated)

    # Replace backward-extended helices in-place; append any new forward helices.
    final_helices = [
        helix_replacements.get(h.id, h) for h in existing_design.helices
    ] + new_helices

    # Add forward-continuation new helices to the same cluster as their source helix.
    updated_cluster_transforms = list(existing_design.cluster_transforms)
    for new_hid, cont_hid in continuation_map.items():
        for i, ct in enumerate(updated_cluster_transforms):
            if cont_hid in ct.helix_ids and new_hid not in ct.helix_ids:
                updated_cluster_transforms[i] = ct.model_copy(
                    update={"helix_ids": list(ct.helix_ids) + [new_hid]}
                )
                break

    return existing_design.copy_with(
        helices=final_helices,
        strands=updated_strands + new_strands,
        cluster_transforms=updated_cluster_transforms,
    )


def make_bundle_deformed_continuation(
    existing_design: Design,
    cells: List[Tuple[int, int]],
    length_bp: int,
    frame: dict,
    deformed_endpoints: dict,
    plane: str = "XY",
    ref_helix_id: str | None = None,
) -> Design:
    """Append a deformed bundle segment to *existing_design*.

    Positions new helices using the deformed cross-section frame
    (grid_origin, axis_dir, frame_right, frame_up) returned by
    ``deformed_frame_at_bp()``.  Continuation detection uses 3-D proximity
    of deformed helix endpoints (from ``deformed_endpoints``) to each new
    helix's ``axis_start``.

    Parameters
    ----------
    existing_design:
        The design to extend.
    cells:
        (row, col) pairs to extrude.
    length_bp:
        Base pairs per new helix (may be negative — extrudes backward along
        ``axis_dir``).
    frame:
        Dict from ``deformed_frame_at_bp`` — keys: ``grid_origin``,
        ``axis_dir``, ``frame_right``, ``frame_up`` (all lists of 3 floats).
    deformed_endpoints:
        ``helix_id`` → ``{"start": [x,y,z], "end": [x,y,z]}``.  Pass the
        per-helix entries from ``deformed_helix_axes(design)``.
    plane:
        Used for helix/strand ID naming only (no geometric meaning here).
    """
    actual_length = abs(length_bp)
    if actual_length < 1:
        raise ValueError(f"length_bp magnitude must be >= 1, got {length_bp}")
    if not cells:
        raise ValueError("cells list must not be empty")
    grid_origin  = np.array(frame["grid_origin"],  dtype=float)
    axis_dir_raw = np.array(frame["axis_dir"],      dtype=float)
    frame_right  = np.array(frame["frame_right"],   dtype=float)
    frame_up     = np.array(frame["frame_up"],      dtype=float)

    norm = np.linalg.norm(axis_dir_raw)
    axis_dir_unit = axis_dir_raw / norm if norm > 1e-12 else np.array([0., 0., 1.])
    length_nm = length_bp * BDNA_RISE_PER_BP  # signed

    # Build deformed endpoint lookup: list of (helix, start_arr, end_arr)
    ep_list: list = []
    for h in existing_design.helices:
        ep = deformed_endpoints.get(h.id)
        if ep is not None:
            ep_list.append((h, np.array(ep["start"], dtype=float),
                               np.array(ep["end"],   dtype=float)))

    _CONT_TOL = 0.5  # nm — proximity tolerance for continuation matching

    existing_helix_ids:  set = {h.id for h in existing_design.helices}
    existing_strand_ids: set = {s.id for s in existing_design.strands}

    new_helices:      List[Helix]  = []
    new_strands:      List[Strand] = []
    domain_additions: dict         = {}
    # new_helix_id → cont_helix_id for continuation cells needing cluster update
    continuation_map: dict[str, str] = {}

    for row, col in cells:
        lx, ly = honeycomb_position(row, col)
        base_hid = f"h_{plane}_{row}_{col}"

        all_helix_ids  = existing_helix_ids  | {h.id for h in new_helices}
        all_strand_ids = existing_strand_ids | {s.id for s in new_strands}

        helix_id = _unique_id(base_hid, all_helix_ids)

        # Place axis_start at grid_origin + frame_right*lx + frame_up*ly
        start_pos  = grid_origin + frame_right * lx + frame_up * ly
        end_pos    = start_pos + axis_dir_unit * length_nm

        axis_start = Vec3(x=float(start_pos[0]), y=float(start_pos[1]), z=float(start_pos[2]))
        axis_end   = Vec3(x=float(end_pos[0]),   y=float(end_pos[1]),   z=float(end_pos[2]))

        direction    = scaffold_direction_for_cell(row, col)
        phase_offset = math.radians(322.2) if direction == Direction.FORWARD else math.radians(252.2)

        bp_start_val = _helix_global_bp_start(axis_start, axis_end)
        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            bp_start=bp_start_val,
            phase_offset=phase_offset,
            direction=direction,
        )
        new_helices.append(helix)

        # Continuation detection: find existing helix whose deformed endpoint
        # is within _CONT_TOL of start_pos.
        cont_helix       = None
        is_end_at_offset = False
        for h_ex, ep_start, ep_end in ep_list:
            if float(np.linalg.norm(ep_end - start_pos)) < _CONT_TOL:
                cont_helix       = h_ex
                is_end_at_offset = True
                break
            if float(np.linalg.norm(ep_start - start_pos)) < _CONT_TOL:
                cont_helix       = h_ex
                is_end_at_offset = False
                break

        if cont_helix is not None:
            continuation_map[helix_id] = cont_helix.id
            seen_strand_ids: set = set()
            for strand in existing_design.strands:
                if strand.id in seen_strand_ids:
                    continue
                for domain in strand.domains:
                    if domain.helix_id == cont_helix.id:
                        d = domain.direction
                        if d == Direction.FORWARD:
                            new_dom = Domain(helix_id=helix_id,
                                             start_bp=bp_start_val,
                                             end_bp=bp_start_val + actual_length - 1,
                                             direction=d)
                            should_prepend = not is_end_at_offset
                        else:
                            new_dom = Domain(helix_id=helix_id,
                                             start_bp=bp_start_val + actual_length - 1,
                                             end_bp=bp_start_val,
                                             direction=d)
                            should_prepend = is_end_at_offset
                        entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                        if should_prepend:
                            entry["prepend"].append(new_dom)
                        else:
                            entry["append"].append(new_dom)
                        seen_strand_ids.add(strand.id)
                        break
        else:
            # Fresh cell: new scaffold + staple strands with global bp values.
            base_sid = f"scaf_{plane}_{row}_{col}"
            base_tid = f"stpl_{plane}_{row}_{col}"
            scaf_id  = _unique_id(base_sid, all_strand_ids)
            stpl_id  = _unique_id(base_tid, all_strand_ids | {scaf_id})

            if direction == Direction.FORWARD:
                scaf_start, scaf_end = bp_start_val, bp_start_val + actual_length - 1
            else:
                scaf_start, scaf_end = bp_start_val + actual_length - 1, bp_start_val

            new_strands.append(Strand(
                id=scaf_id,
                domains=[Domain(helix_id=helix_id, start_bp=scaf_start,
                                end_bp=scaf_end, direction=direction)],
                strand_type=StrandType.SCAFFOLD,
            ))

            staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
            if staple_dir == Direction.FORWARD:
                stpl_start, stpl_end = bp_start_val, bp_start_val + actual_length - 1
            else:
                stpl_start, stpl_end = bp_start_val + actual_length - 1, bp_start_val

            new_strands.append(Strand(
                id=stpl_id,
                domains=[Domain(helix_id=helix_id, start_bp=stpl_start,
                                end_bp=stpl_end, direction=staple_dir)],
                strand_type=StrandType.STAPLE,
            ))

    # Rebuild the existing strand list, extending those with domain_additions.
    updated_strands: List[Strand] = []
    for strand in existing_design.strands:
        if strand.id in domain_additions:
            updated = strand.model_copy(deep=True)
            entry = domain_additions[strand.id]
            updated.domains = entry["prepend"] + updated.domains + entry["append"]
            updated_strands.append(updated)
        else:
            updated_strands.append(strand)

    # The deformed frame used to place new helices already has the cluster rotation
    # applied (world-space positions).  Any new helix that will join the cluster
    # must be un-rotated back to local frame so the cluster transform at render
    # time brings it to the correct world position.
    #
    # Target cluster: determined by ref_helix_id (covers both fresh and continuation
    # cells extruded from the same blunt end), falling back to per-continuation-helix
    # lookup when ref_helix_id is absent.

    cluster_by_helix: dict[str, object] = {}
    for ct in existing_design.cluster_transforms:
        for hid in ct.helix_ids:
            cluster_by_helix[hid] = ct

    target_cluster = cluster_by_helix.get(ref_helix_id) if ref_helix_id else None

    def _build_R_T(ct: object) -> np.ndarray:
        qx, qy, qz, qw = ct.rotation  # type: ignore[union-attr]
        return np.array([
            [1-2*(qy*qy+qz*qz),    2*(qx*qy+qz*qw),    2*(qx*qz-qy*qw)],
            [   2*(qx*qy-qz*qw), 1-2*(qx*qx+qz*qz),    2*(qy*qz+qx*qw)],
            [   2*(qx*qz+qy*qw),    2*(qy*qz-qx*qw), 1-2*(qx*qx+qy*qy)],
        ], dtype=float)

    corrected_helices: List["Helix"] = []
    for h in new_helices:
        # Determine which cluster this new helix should join.
        cont_hid = continuation_map.get(h.id)
        ct = target_cluster or (cluster_by_helix.get(cont_hid) if cont_hid else None)
        if ct is not None:
            R_T = _build_R_T(ct)
            piv = np.array(ct.pivot,       dtype=float)  # type: ignore[union-attr]
            tr  = np.array(ct.translation, dtype=float)  # type: ignore[union-attr]
            def _to_local(p: "Vec3", _R_T: np.ndarray = R_T,
                          _piv: np.ndarray = piv, _tr: np.ndarray = tr) -> "Vec3":
                v = np.array([p.x, p.y, p.z]) - _piv - _tr
                loc = _R_T @ v + _piv
                return Vec3(x=float(loc[0]), y=float(loc[1]), z=float(loc[2]))
            h = h.model_copy(update={
                "axis_start": _to_local(h.axis_start),
                "axis_end":   _to_local(h.axis_end),
            })
        corrected_helices.append(h)
    new_helices = corrected_helices

    # Update cluster_transforms: add all new helices that belong to a cluster.
    updated_cluster_transforms = list(existing_design.cluster_transforms)
    if target_cluster is not None:
        # All new helices join the target cluster (fresh + continuation).
        new_hids = [h.id for h in new_helices]
        for i, ct in enumerate(updated_cluster_transforms):
            if ct.id == target_cluster.id:  # type: ignore[union-attr]
                to_add = [hid for hid in new_hids if hid not in ct.helix_ids]
                if to_add:
                    updated_cluster_transforms[i] = ct.model_copy(
                        update={"helix_ids": list(ct.helix_ids) + to_add}
                    )
                break
    else:
        # Fallback: continuation-only cluster assignment (no ref_helix_id).
        for new_hid, cont_hid in continuation_map.items():
            for i, ct in enumerate(updated_cluster_transforms):
                if cont_hid in ct.helix_ids and new_hid not in ct.helix_ids:
                    updated_cluster_transforms[i] = ct.model_copy(
                        update={"helix_ids": list(ct.helix_ids) + [new_hid]}
                    )
                    break

    return existing_design.copy_with(
        helices=existing_design.helices + new_helices,
        strands=updated_strands + new_strands,
        cluster_transforms=updated_cluster_transforms,
    )


def _find_strand_at(
    design: Design,
    helix_id: str,
    bp: int,
    direction: Direction,
) -> tuple[Strand, int]:
    """Return (strand, domain_index) for the strand whose domain covers (helix_id, bp, direction).

    Raises ValueError if no strand covers that position.
    """
    for strand in design.strands:
        for di, domain in enumerate(strand.domains):
            if domain.helix_id != helix_id or domain.direction != direction:
                continue
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            if lo <= bp <= hi:
                return strand, di
    raise ValueError(
        f"No strand covers (helix={helix_id!r}, bp={bp}, direction={direction.value})."
    )


def make_nick(
    existing_design: Design,
    helix_id: str,
    bp_index: int,
    direction: Direction,
) -> Design:
    """Create a nick (strand break) at the 3′ side of the specified nucleotide.

    The nucleotide at (helix_id, bp_index, direction) becomes the 3′ terminal of
    the left fragment; the next nucleotide in 5′→3′ order becomes the 5′ terminal
    of the right fragment.

    Two cases:
    • bp_index == domain.end_bp (inter-domain boundary): the strand is split
      between domain[i] and domain[i+1] without modifying any domain.
    • bp_index inside the domain: the domain is split at bp_index.

    Raises ValueError if:
    • No strand covers (helix_id, bp_index, direction).
    • bp_index is already the 3′ terminus of the strand (no next nucleotide).
    """
    strand, domain_idx = _find_strand_at(existing_design, helix_id, bp_index, direction)
    domain = strand.domains[domain_idx]

    is_last_domain     = (domain_idx == len(strand.domains) - 1)
    is_last_bp_of_dom  = (bp_index == domain.end_bp)

    if is_last_domain and is_last_bp_of_dom:
        raise ValueError(
            f"bp_index={bp_index} is the 3′ terminus of the strand — cannot nick there."
        )

    # ── DEBUG ──────────────────────────────────────────────────────────────────────
    # Cell bp=N occupies the square between boundary N and boundary N+1.
    # FORWARD at bp=N → nick at right boundary of cell N (= left boundary of cell N+1)
    # REVERSE at bp=N → nick at left boundary of cell N
    gap_boundary = bp_index + 1 if direction == Direction.FORWARD else bp_index
    print(f"[make_nick] helix={helix_id[:8]} bp={bp_index} dir={direction.value}")
    print(f"[make_nick] domain: start={domain.start_bp} end={domain.end_bp} | gap at boundary={gap_boundary}")

    if is_last_bp_of_dom:
        # Inter-domain split — no domain modification needed.
        left_domains  = list(strand.domains[:domain_idx + 1])
        right_domains = list(strand.domains[domain_idx + 1:])
    else:
        # Within-domain split.
        if direction == Direction.FORWARD:
            # FORWARD: 5′=start_bp (low), 3′=end_bp (high). Next bp after nick → bp_index+1.
            left_dom  = Domain(helix_id=helix_id, start_bp=domain.start_bp,
                               end_bp=bp_index, direction=direction)
            right_dom = Domain(helix_id=helix_id, start_bp=bp_index + 1,
                               end_bp=domain.end_bp, direction=direction)
        else:
            # REVERSE: 5′=start_bp (high), 3′=end_bp (low). Next bp after nick → bp_index-1.
            left_dom  = Domain(helix_id=helix_id, start_bp=domain.start_bp,
                               end_bp=bp_index, direction=direction)
            right_dom = Domain(helix_id=helix_id, start_bp=bp_index - 1,
                               end_bp=domain.end_bp, direction=direction)
        left_domains  = list(strand.domains[:domain_idx]) + [left_dom]
        right_domains = [right_dom] + list(strand.domains[domain_idx + 1:])

    left_3p  = left_domains[-1].end_bp
    right_5p = right_domains[0].start_bp
    print(f"[make_nick] left 3'={left_3p}  right 5'={right_5p}")

    # ── Build new strands ──────────────────────────────────────────────────
    new_strand_left = strand.model_copy(deep=True)
    new_strand_left.domains = left_domains

    right_id = f"{strand.id}_{helix_id}_{bp_index}_r"
    new_strand_right = Strand(
        id=right_id,
        domains=right_domains,
        strand_type=strand.strand_type,
        sequence=None,
    )

    new_strands: List[Strand] = []
    for s in existing_design.strands:
        if s.id == strand.id:
            new_strands.append(new_strand_left)
            new_strands.append(new_strand_right)
        else:
            new_strands.append(s)

    # 3' extensions on the nicked strand must follow the right fragment, which now
    # holds the original 3' terminal.  5' extensions stay with the left fragment
    # (which keeps the original strand ID and 5' terminal).
    new_extensions = [
        ext.model_copy(update={"strand_id": right_id})
        if ext.strand_id == strand.id and ext.end == "three_prime"
        else ext
        for ext in existing_design.extensions
    ]

    return existing_design.copy_with(
        strands=new_strands,
        extensions=new_extensions,
    )


def _find_strand_by_3prime(
    design: Design,
    helix_id: str,
    end_bp: int,
    strand_type: "StrandType" = StrandType.STAPLE,  # type: ignore[name-defined]
) -> "Strand | None":  # type: ignore[name-defined]
    """Return the strand of the given type whose last domain ends at (helix_id, end_bp)."""
    for s in design.strands:
        if s.strand_type != strand_type or not s.domains:
            continue
        last = s.domains[-1]
        if last.helix_id == helix_id and last.end_bp == end_bp:
            return s
    return None


def _find_strand_by_5prime(
    design: Design,
    helix_id: str,
    start_bp: int,
    strand_type: "StrandType" = StrandType.STAPLE,  # type: ignore[name-defined]
) -> "Strand | None":  # type: ignore[name-defined]
    """Return the strand of the given type whose first domain starts at (helix_id, start_bp)."""
    for s in design.strands:
        if s.strand_type != strand_type or not s.domains:
            continue
        first = s.domains[0]
        if first.helix_id == helix_id and first.start_bp == start_bp:
            return s
    return None


def _ligate(design: Design, s1: "Strand", s2: "Strand") -> Design:  # type: ignore[name-defined]
    """Join s2's domains onto the 3' end of s1. Returns updated Design."""
    new_domains = _merge_adjacent_domains(list(s1.domains) + list(s2.domains))
    new_strand = s1.model_copy(update={"domains": new_domains})
    new_strands = [
        new_strand if s.id == s1.id else s
        for s in design.strands
        if s.id != s2.id
    ]
    # When s2 is absorbed: its 3' terminal becomes the merged strand's 3' terminal,
    # so 3' extensions on s2 follow the merged strand (s1.id).  s2's 5' terminal
    # becomes internal, so 5' extensions on s2 are no longer at a terminal — drop them.
    new_extensions = [
        ext.model_copy(update={"strand_id": s1.id})
        if ext.strand_id == s2.id and ext.end == "three_prime"
        else ext
        for ext in design.extensions
        if not (ext.strand_id == s2.id and ext.end == "five_prime")
    ]
    return design.model_copy(update={"strands": new_strands, "extensions": new_extensions})


def _merge_adjacent_domains(domains: list) -> list:
    """Collapse adjacent domains on the same helix with the same direction.

    Two domains are mergeable when they are on the same helix, same direction,
    and their bp ranges are adjacent (end_bp ± 1 == start_bp depending on direction)
    or touching (end_bp == start_bp).

    Returns a new list with merged domains.
    """
    if len(domains) <= 1:
        return list(domains)
    merged = [domains[0]]
    for d in domains[1:]:
        prev = merged[-1]
        if (prev.helix_id == d.helix_id and prev.direction == d.direction
                and prev.overhang_id == d.overhang_id):
            # Check adjacency: for FORWARD end_bp+1==start_bp, for REVERSE end_bp-1==start_bp
            adj = 1 if prev.direction == Direction.FORWARD else -1
            if prev.end_bp + adj == d.start_bp or prev.end_bp == d.start_bp:
                merged[-1] = Domain(
                    helix_id=prev.helix_id,
                    start_bp=prev.start_bp,
                    end_bp=d.end_bp,
                    direction=prev.direction,
                )
                continue
        merged.append(d)
    return merged


def _ligate_and_merge(design: Design, s1: "Strand", s2: "Strand") -> Design:  # type: ignore[name-defined]
    """Like _ligate but also merges the two touching domains at the junction.

    s1's last domain and s2's first domain are adjacent on the same helix with
    the same direction — they are collapsed into a single domain spanning both
    ranges.  This prevents the pathview from rendering an apparent nick at the
    join point.
    """
    dom_a = s1.domains[-1]
    dom_b = s2.domains[0]
    if dom_a.helix_id == dom_b.helix_id and dom_a.direction == dom_b.direction:
        merged_dom = Domain(
            helix_id=dom_a.helix_id,
            start_bp=dom_a.start_bp,
            end_bp=dom_b.end_bp,
            direction=dom_a.direction,
        )
        merged_domains = list(s1.domains[:-1]) + [merged_dom] + list(s2.domains[1:])
    else:
        merged_domains = list(s1.domains) + list(s2.domains)

    new_strand = s1.model_copy(update={"domains": merged_domains, "sequence": None})
    new_strands = [
        new_strand if s.id == s1.id else s
        for s in design.strands
        if s.id != s2.id
    ]
    new_extensions = [
        ext.model_copy(update={"strand_id": s1.id})
        if ext.strand_id == s2.id and ext.end == "three_prime"
        else ext
        for ext in design.extensions
        if not (ext.strand_id == s2.id and ext.end == "five_prime")
    ]
    return design.model_copy(update={"strands": new_strands, "extensions": new_extensions})


def _coaxial_helix_ids(design: Design, helix_id: str) -> list:
    """Return all helix IDs at the same lattice cell as *helix_id* (including itself).

    Two helices are coaxial if they share the same cell prefix (e.g. ``h_XY_0_0``
    and ``h_XY_0_0_0`` both belong to cell (0, 0)).  The cell prefix is the
    ``h_{plane}_{row}_{col}`` portion; any trailing ``_N`` suffix is a segment
    counter added by ``_unique_id``.
    """
    import re
    # Extract the cell prefix: h_{plane}_{row}_{col}
    m = re.match(r'(h_[A-Z]+_-?\d+_-?\d+)', helix_id)
    if not m:
        return [helix_id]
    prefix = m.group(1)
    return [h.id for h in design.helices
            if h.id == prefix or h.id.startswith(prefix + "_")]


def ligate_new_strands(design: Design, new_strand_ids: set) -> Design:
    """Ligate each newly created strand to any adjacent existing strand at bp ±1.

    For each new strand, checks the 3' end then the 5' end for an adjacent
    strand of the same type and direction.  If found, merges them with domain
    consolidation so the pathview renders a continuous strand.

    Searches across coaxial helices (same lattice cell) so that segment-mode
    extrude — which creates a new helix ID — can still ligate with existing
    strands on the original helix.

    Process order: 3' first (new strand is s1, keeps its ID), then 5' (new
    strand is s2, absorbed into the adjacent strand).
    """
    for nid in list(new_strand_ids):
        # Re-lookup: strand may have been absorbed by a prior iteration
        strand = None
        for s in design.strands:
            if s.id == nid:
                strand = s
                break
        if strand is None or not strand.domains:
            continue

        # ── 3' end: new strand's last domain ────────────────────────────
        last = strand.domains[-1]
        adj_3p = last.end_bp + 1 if last.direction == Direction.FORWARD else last.end_bp - 1
        candidate = None
        for hid in _coaxial_helix_ids(design, last.helix_id):
            candidate = _find_strand_by_5prime(design, hid, adj_3p, strand.strand_type)
            if candidate is not None and candidate.id != strand.id:
                if candidate.domains[0].direction == last.direction:
                    break
                candidate = None
            else:
                candidate = None
        if candidate is not None:
            design = _ligate_and_merge(design, strand, candidate)

        # Re-lookup strand after possible merge (it kept its ID as s1)
        strand = None
        for s in design.strands:
            if s.id == nid:
                strand = s
                break
        if strand is None or not strand.domains:
            continue

        # ── 5' end: new strand's first domain ───────────────────────────
        first = strand.domains[0]
        adj_5p = first.start_bp - 1 if first.direction == Direction.FORWARD else first.start_bp + 1
        candidate = None
        for hid in _coaxial_helix_ids(design, first.helix_id):
            candidate = _find_strand_by_3prime(design, hid, adj_5p, strand.strand_type)
            if candidate is not None and candidate.id != strand.id:
                if candidate.domains[-1].direction == first.direction:
                    break
                candidate = None
            else:
                candidate = None
        if candidate is not None:
            design = _ligate_and_merge(design, candidate, strand)

    return design


# ── Crossover-chain ligation ─────────────────────────────────────────────────


def ligate_crossover_chains(design: Design, *, max_length: int | None = None) -> Design:
    """Bulk-ligate all crossover-linked staple fragments into multi-domain strands.

    Walks the crossover graph to find ordered chains (5'→3') and ligates each
    chain into a single multi-domain Strand.  Individual crossover placement
    (place_crossover) now ligates inline per-crossover; this function is kept
    for bulk operations (e.g. cadnano/scadnano import) and is safe to call on
    designs that already have multi-domain strands (chains of length 1 are no-ops).

    If *max_length* is set, a ligation step is skipped when the combined
    strand would exceed that many nucleotides.

    Scaffold strands are not modified.  Crossover records are preserved
    unchanged (they remain valid because ``d0.end_bp == d1.start_bp`` at
    each cross-helix domain boundary).
    """
    # ── 1. Build terminal maps ────────────────────────────────────────────
    five_prime: dict[tuple[str, int, Direction], str] = {}
    three_prime: dict[tuple[str, int, Direction], str] = {}
    strand_map: dict[str, Strand] = {}

    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD or not s.domains:
            continue
        strand_map[s.id] = s
        fd = s.domains[0]
        five_prime[(fd.helix_id, fd.start_bp, fd.direction)] = s.id
        ld = s.domains[-1]
        three_prime[(ld.helix_id, ld.end_bp, ld.direction)] = s.id

    # ── 2. Build directed successor graph from crossover records ──────────
    successor: dict[str, str] = {}
    predecessor: dict[str, str] = {}

    for xo in design.crossovers:
        ha, hb = xo.half_a, xo.half_b
        # Try: 3' on half_a side → 5' on half_b side
        s_from = three_prime.get((ha.helix_id, ha.index, ha.strand))
        s_to = five_prime.get((hb.helix_id, hb.index, hb.strand))
        if s_from is not None and s_to is not None and s_from != s_to:
            successor[s_from] = s_to
            predecessor[s_to] = s_from
            continue
        # Try reverse: 3' on half_b → 5' on half_a
        s_from = three_prime.get((hb.helix_id, hb.index, hb.strand))
        s_to = five_prime.get((ha.helix_id, ha.index, ha.strand))
        if s_from is not None and s_to is not None and s_from != s_to:
            successor[s_from] = s_to
            predecessor[s_to] = s_from

    # ── 3. Walk chains from heads (strands with no predecessor) ───────────
    visited: set[str] = set()
    chains: list[list[str]] = []

    for sid in strand_map:
        if sid in visited or sid in predecessor:
            continue
        chain: list[str] = [sid]
        visited.add(sid)
        cur = sid
        while cur in successor:
            cur = successor[cur]
            if cur in visited:
                break
            chain.append(cur)
            visited.add(cur)
        chains.append(chain)

    # Handle circular chains (all members have predecessors)
    for sid in strand_map:
        if sid not in visited:
            chain = [sid]
            visited.add(sid)
            cur = sid
            while cur in successor:
                cur = successor[cur]
                if cur in visited:
                    break
                chain.append(cur)
                visited.add(cur)
            chains.append(chain)

    # ── 4. Ligate each multi-fragment chain ───────────────────────────────
    result = design
    for chain in chains:
        if len(chain) <= 1:
            continue
        head_id = chain[0]
        for i in range(1, len(chain)):
            head = next(s for s in result.strands if s.id == head_id)
            tail = next(s for s in result.strands if s.id == chain[i])
            if max_length is not None:
                head_nt = sum(abs(d.end_bp - d.start_bp) + 1 for d in head.domains)
                tail_nt = sum(abs(d.end_bp - d.start_bp) + 1 for d in tail.domains)
                if head_nt + tail_nt > max_length:
                    continue
            result = _ligate(result, head, tail)

    return result


def _strand_domain_lens(positions: list) -> list[int]:
    """Return the length of each contiguous helix run in a nucleotide position list."""
    if not positions:
        return []
    lens, count = [], 1
    for i in range(1, len(positions)):
        if positions[i][0] == positions[i - 1][0]:
            count += 1
        else:
            lens.append(count)
            count = 1
    lens.append(count)
    return lens


def _has_sandwich(domain_lens: list[int]) -> bool:
    """True if any interior domain is strictly shorter than both its neighbours.

    A 'sandwich' is the pattern [..., longer, shorter, longer, ...].
    First and last domains cannot be sandwiched (they have only one neighbour).
    Example: [14, 7, 14] → True (7 is sandwiched); [14, 7, 7] → False.
    """
    return any(
        domain_lens[i - 1] > domain_lens[i] and domain_lens[i + 1] > domain_lens[i]
        for i in range(1, len(domain_lens) - 1)
    )


def _strand_nucleotide_positions(strand) -> list[tuple[str, int, "Direction"]]:
    """Return all (helix_id, bp, direction) in 5'→3' order for a strand."""
    positions = []
    for domain in strand.domains:
        h, d = domain.helix_id, domain.direction
        for bp in domain_bp_range(domain):
            positions.append((h, bp, d))
    return positions


def compute_nick_plan_for_strand(
    strand,
    preferred_lengths: "list[int] | None" = None,
    min_length: int = 21,
    max_length: int = 60,
    min_crossover_gap: int = 7,
    crossover_bps: "set[tuple[str, int]] | None" = None,
) -> list[dict]:
    """Return nick positions to break this strand into segments of min_length..max_length nt,
    preferring segment lengths in preferred_lengths, and avoiding the no-sandwich rule.

    NOTE: The primary autobreak path uses tick-mark nicking (make_autobreak) which
    inherently avoids crossover positions.  This preferred-length algorithm is kept
    for compute_nick_plan (UI preview) but is not used by make_nicks_for_autostaple.

    Nicks are returned in REVERSE 5'→3' order so that applying them right-to-left
    preserves the original strand ID for subsequent nicks (make_nick always keeps the
    original ID on the left fragment).

    Parameters
    ----------
    preferred_lengths : list[int]
        Preferred segment lengths, in order of equal priority.  The algorithm
        ranks candidate nick positions by their distance to the nearest preferred
        length.  Defaults to [42, 49] (6 and 7 full 7-bp prebreak periods).
    min_length : int
        Minimum segment length (default 21 nt, one B-DNA helix period).
    max_length : int
        Maximum segment length before nicking is required (default 60 nt).
    min_crossover_gap : int
        Minimum index-distance in nt between a nick and any crossover position
        within the same strand's nucleotide list (default 7).  This is a soft
        preference — falls back when no candidate satisfies the constraint.
    crossover_bps : set of (helix_id, bp_index) tuples
        Protected crossover positions from design.crossovers records.

    Sandwich rule
    -------------
    A strand violates the sandwich rule if any interior domain d satisfies
    len(d-1) > len(d) AND len(d+1) > len(d).  e.g. [14, 7, 14] is forbidden
    but [14, 7, 7] is allowed.  When no nick position avoids a sandwich, the
    constraint is relaxed rather than producing an infinite loop.
    """
    if preferred_lengths is None:
        preferred_lengths = [42, 49]

    positions = _strand_nucleotide_positions(strand)
    total = len(positions)

    # Crossover boundaries: positions where a crossover record exists, plus
    # legacy detection of helix transitions for imported multi-helix strands.
    crossover_indices: list[int] = []
    if crossover_bps:
        for idx in range(total):
            h, bp, _ = positions[idx]
            if (h, bp) in crossover_bps:
                crossover_indices.append(idx)
    for idx in range(1, total):
        if positions[idx][0] != positions[idx - 1][0]:
            crossover_indices.append(idx - 1)

    def _near_crossover(idx: int) -> bool:
        return any(abs(idx - ci) < min_crossover_gap for ci in crossover_indices)

    def _seg_sandwich(nick_i: int, seg_start: int) -> bool:
        return _has_sandwich(_strand_domain_lens(positions[seg_start : nick_i + 1]))

    def _pref_dist(idx: int, seg_start: int) -> int:
        """Distance from idx to the nearest preferred segment boundary."""
        seg_len = idx - seg_start + 1
        return min(abs(seg_len - p) for p in preferred_lengths)

    nick_indices: list[int] = []
    last_break = 0

    while True:
        remaining = total - last_break
        sub_lens = _strand_domain_lens(positions[last_break:])

        # Done when the tail is both short enough AND sandwich-free.
        if remaining <= max_length and not _has_sandwich(sub_lens):
            break

        # Can't split without violating min_length — accept tail as-is.
        if remaining < 2 * min_length:
            break

        max_i = total - min_length - 1
        lo = last_break + min_length - 1
        hi = min(last_break + max_length - 1, max_i)

        if lo > hi:
            # Fallback: use closest preferred length, clamped to valid range.
            best_ideal = last_break + min(preferred_lengths, key=lambda p: abs(remaining - p)) - 1
            nick_i = max(min(best_ideal, max_i), last_break + min_length - 1)
        else:
            # Rank all candidates by distance to nearest preferred length.
            ranked = sorted(range(lo, hi + 1), key=lambda i: _pref_dist(i, last_break))

            nick_i = None
            # Pass 1: prefer positions that avoid both crossovers and sandwiches.
            for candidate in ranked:
                if not _near_crossover(candidate) and not _seg_sandwich(candidate, last_break):
                    nick_i = candidate
                    break
            # Pass 2: relax sandwich — crossover avoidance only.
            if nick_i is None:
                for candidate in ranked:
                    if not _near_crossover(candidate):
                        nick_i = candidate
                        break
            # Final fallback: best preferred position regardless of constraints.
            if nick_i is None:
                nick_i = ranked[0]

        nick_indices.append(nick_i)
        last_break = nick_i + 1

    # Return reversed so applying right-to-left is safe.
    return [
        {"helix_id": positions[idx][0], "bp_index": positions[idx][1], "direction": positions[idx][2]}
        for idx in reversed(nick_indices)
    ]


def compute_nick_plan(
    design: Design,
    preferred_lengths: "list[int] | None" = None,
    min_length: int = 21,
    max_length: int = 60,
    min_crossover_gap: int = 7,
) -> list[dict]:
    """Compute nick positions for ALL non-scaffold strands (UI preview).

    Uses preferred-length ranking (not tick-mark nicking).  The actual autobreak
    path (make_nicks_for_autostaple → make_autobreak) uses tick marks instead.

    Returns a flat list of {helix_id, bp_index, direction} dicts.
    """
    xover_bps: set[tuple[str, int]] = set()
    for xo in design.crossovers:
        xover_bps.add((xo.half_a.helix_id, xo.half_a.index))
        xover_bps.add((xo.half_b.helix_id, xo.half_b.index))

    plan = []
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            continue
        strand_nicks = compute_nick_plan_for_strand(
            strand, preferred_lengths, min_length, max_length, min_crossover_gap, crossover_bps=xover_bps
        )
        # Reverse back to 5'→3' order for display; application order is handled
        # per-strand inside make_nicks_for_autostaple.
        plan.extend(reversed(strand_nicks))
    return plan


def make_nicks_for_autostaple(
    design: Design,
    preferred_lengths: "list[int] | None" = None,
    min_length: int = 21,
    max_length: int = 60,
    min_crossover_gap: int = 7,
) -> Design:
    """Break long staple strands into canonical-length segments (Stage 2 of autostaple).

    Nicks at major tick marks (HC: {0,7,14} mod 21, SQ: {0,8,16,24} mod 32),
    producing the longest segments that fit within max_length.  Exact crossover
    positions are skipped.  Sandwich-aware: prefers nick positions that avoid
    the pattern [longer, shorter, longer] in the resulting strand domains.

    Delegates to make_autobreak which implements tick-mark nicking.
    """
    return make_autobreak(design)


# ── Autobreak: tick-mark nicking ──────────────────────────────────────────────


def make_autobreak(design: Design) -> Design:
    """Nick all non-scaffold strands at major tick marks, producing segments
    as long as possible without exceeding 60 nt.

    Major tick marks:
      HC (period 21): bp % 21 ∈ {0, 7, 14}
      SQ (period 32): bp % 32 ∈ {0, 8, 16, 24}

    The sandwich rule (no long-short-long domain pattern) overrides the length
    preference: if the longest valid segment would create a sandwich, shorter
    candidates are tried.  If no tick-mark position in the window avoids a
    sandwich, the sandwich constraint is relaxed rather than leaving a strand
    longer than 60 nt.
    """
    is_hc    = design.lattice_type == LatticeType.HONEYCOMB
    period   = 21 if is_hc else 32
    tick_set = frozenset({0, 7, 14}) if is_hc else frozenset({0, 8, 16, 24})
    max_len  = 60

    # Protected crossover positions from crossover records.
    xover_bps: set[tuple[str, int]] = set()
    for xo in design.crossovers:
        xover_bps.add((xo.half_a.helix_id, xo.half_a.index))
        xover_bps.add((xo.half_b.helix_id, xo.half_b.index))

    result = design
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            continue
        positions = _strand_nucleotide_positions(strand)
        total = len(positions)
        if total <= max_len:
            continue  # already short enough

        # Collect nick indices in 5'→3' order; applied right-to-left after.
        nick_indices: list[int] = []
        seg_start = 0
        while seg_start < total - 1:
            # Window: indices [seg_start, window_end) — at most max_len nucleotides.
            # Never nick the very last nt of the strand (would leave empty right fragment).
            window_end = min(seg_start + max_len, total - 1)

            chosen: int | None = None
            fallback: int | None = None  # best tick regardless of sandwich

            for i in range(window_end - 1, seg_start - 1, -1):
                h_cur, bp, d = positions[i]
                # make_nick places the gap at boundary bp+1 (FORWARD) or bp (REVERSE).
                # To land the gap on tick mark T we need:
                #   FORWARD: nick at bp = T-1 → check (bp+1) % period
                #   REVERSE: nick at bp = T   → check bp % period
                tick_bp = (bp + 1) if d == Direction.FORWARD else bp
                if (tick_bp % period) not in tick_set:
                    continue
                # Skip if the nick or the tick boundary is a crossover position.
                if (h_cur, bp) in xover_bps or (h_cur, tick_bp) in xover_bps:
                    continue
                # Legacy: also skip helix transitions for imported multi-helix strands.
                if positions[i + 1][0] != h_cur:
                    continue
                if i > 0 and positions[i - 1][0] != h_cur:
                    continue
                if fallback is None:
                    fallback = i
                seg_lens = _strand_domain_lens(positions[seg_start : i + 1])
                if not _has_sandwich(seg_lens):
                    chosen = i
                    break  # longest sandwich-free tick in window

            if chosen is None:
                chosen = fallback   # relax sandwich if unavoidable
            if chosen is None:
                break               # no tick marks at all — leave as-is

            nick_indices.append(chosen)
            seg_start = chosen + 1

        # Apply right-to-left so make_nick keeps original strand ID for earlier nicks.
        for idx in reversed(nick_indices):
            h, bp, d = positions[idx]
            try:
                result = make_nick(result, h, bp, d)
            except ValueError:
                pass  # already a boundary or strand was modified

    # Pass 2: repair nicks where merging adjacent strands would not exceed
    # max_len and would not create a sandwich.
    result = make_merge_short_staples(result, max_merged_length=max_len)

    # Pass 3: re-ligate crossovers that were skipped during the initial
    # ligate_crossover_chains because they would have created circular
    # strands.  After nicking, those halves now belong to different strands
    # and the ligation is valid.  Respect the 60 nt cap.
    result = ligate_crossover_chains(result, max_length=max_len)

    return result


# ── Stage 3: merge short staples ──────────────────────────────────────────────


def make_merge_short_staples(
    design: Design,
    max_merged_length: int = 56,
) -> Design:
    """Stage 3 of the autostaple pipeline: re-merge adjacent short staple strands.

    After Stage 1 (auto_crossover) has placed all canonical DX crossovers, the
    staple strands contain nick boundaries at prebreak positions that were NOT
    consumed by a ligation.  These remaining nicks sit within a single helix:
    the 3′ end of one strand and the 5′ end of the next are consecutive bp
    positions on the same helix in the same direction.

    This pass finds such adjacent pairs whose combined length ≤ max_merged_length
    and whose merged domain sequence is sandwich-free, then removes the nick.
    Candidates are processed longest-first so strands grow as close to the cap as
    possible.  The pass repeats until no further merges are possible.

    Parameters
    ----------
    design:
        Design after Stage 2 (make_nicks_for_autostaple).
    max_merged_length:
        Maximum combined length in nucleotides (default 56).
    """
    result = design

    while True:
        # Build a lookup: (helix_id, bp, direction) → strand for all 5′ ends.
        five_prime: dict[tuple[str, int, "Direction"], "Strand"] = {}  # type: ignore[name-defined]
        for s in result.strands:
            if s.strand_type == StrandType.SCAFFOLD or not s.domains:
                continue
            f = s.domains[0]
            five_prime[(f.helix_id, f.start_bp, f.direction)] = s

        candidates: list[tuple[int, str, str]] = []  # (combined_len, s1_id, s2_id)
        for s1 in result.strands:
            if s1.strand_type == StrandType.SCAFFOLD or not s1.domains:
                continue
            last = s1.domains[-1]
            # The nucleotide immediately after the 3′ end of s1 in its direction.
            if last.direction == Direction.FORWARD:
                next_bp = last.end_bp + 1
            else:  # REVERSE: 5′→3′ goes high→low, so the next bp is one lower.
                next_bp = last.end_bp - 1

            s2 = five_prime.get((last.helix_id, next_bp, last.direction))
            if s2 is None or s2.id == s1.id:
                continue

            pos1 = _strand_nucleotide_positions(s1)
            pos2 = _strand_nucleotide_positions(s2)
            combined = len(pos1) + len(pos2)
            if combined > max_merged_length:
                continue
            if _has_sandwich(_strand_domain_lens(pos1 + pos2)):
                continue
            candidates.append((combined, s1.id, s2.id))

        if not candidates:
            break

        # Sort longest-first so we maximise strand length toward the cap.
        candidates.sort(key=lambda x: -x[0])

        # Apply all non-conflicting merges in one pass (each strand used once).
        merged_ids: set[str] = set()
        any_merge = False
        for _combined, s1_id, s2_id in candidates:
            if s1_id in merged_ids or s2_id in merged_ids:
                continue
            s1 = next((s for s in result.strands if s.id == s1_id), None)
            s2 = next((s for s in result.strands if s.id == s2_id), None)
            if s1 is None or s2 is None:
                continue
            result = _ligate(result, s1, s2)
            merged_ids.add(s1_id)
            merged_ids.add(s2_id)
            any_merge = True

        if not any_merge:
            break

    return result


# ── Scaffold routing ───────────────────────────────────────────────────────────


def _scaffold_direction_from_helix_id(helix_id: str) -> "Direction | None":
    """Derive scaffold direction from helix ID lattice position (h_{plane}_{row}_{col}...)."""
    parts = helix_id.split("_")
    # Format: h  {PLANE}  {row}  {col}  [optional suffix ...]
    if len(parts) < 4:
        return None
    try:
        row = int(parts[2])
        col = int(parts[3])
        return scaffold_direction_for_cell(row, col)
    except (ValueError, IndexError):
        return None


def _get_scaffold_direction(design: Design, helix_id: str) -> "Direction | None":
    """Return the Direction of the scaffold strand on a given helix, or None.

    Falls back to the lattice formula (parsed from helix ID) when no scaffold
    strand is found — needed for helices whose strands were removed mid-operation.
    """
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            for domain in strand.domains:
                if domain.helix_id == helix_id:
                    return domain.direction
    return _scaffold_direction_from_helix_id(helix_id)


def _helix_axis_lo(h: "Helix", plane: str) -> float:
    """Return the minimum axis offset of *h* along the given plane normal."""
    if plane == "XY":
        return min(h.axis_start.z, h.axis_end.z)
    if plane == "XZ":
        return min(h.axis_start.y, h.axis_end.y)
    return min(h.axis_start.x, h.axis_end.x)


def _helix_axis_hi(h: "Helix", plane: str) -> float:
    """Return the maximum axis offset of *h* along the given plane normal."""
    if plane == "XY":
        return max(h.axis_start.z, h.axis_end.z)
    if plane == "XZ":
        return max(h.axis_start.y, h.axis_end.y)
    return max(h.axis_start.x, h.axis_end.x)


def _cells_from_helices(helices: "List[Helix]", plane: str) -> "List[Tuple[int, int]]":
    """Extract unique (row, col) cell pairs from helix IDs in the given plane.

    Helix IDs have the form ``h_{plane}_{row}_{col}[_{suffix}...]``.
    """
    cells: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for h in helices:
        parts = h.id.split("_")
        # parts[0]="h", parts[1]=plane, parts[2]=row, parts[3]=col
        if len(parts) < 4 or parts[1] != plane:
            continue
        try:
            row, col = int(parts[2]), int(parts[3])
        except ValueError:
            continue
        if (row, col) not in seen:
            cells.append((row, col))
            seen.add((row, col))
    return cells


def _overhang_only_helix_ids(design: Design) -> set[str]:
    """Return the set of helix IDs that are exclusively used by overhang domains.

    A helix is "overhang-only" when every domain assigned to it across all
    strands has a non-None ``overhang_id``.  Such helices are single-stranded
    stubs and must be excluded from scaffold routing, extrusion, and end-crossover
    placement.

    Helices that have no domains at all (bare helices) are *not* included —
    only helices with at least one domain, all of which are overhangs.
    """
    from collections import defaultdict
    helix_domains: dict[str, list] = defaultdict(list)
    for strand in design.strands:
        for domain in strand.domains:
            helix_domains[domain.helix_id].append(domain)

    result: set[str] = set()
    for hid, domains in helix_domains.items():
        if domains and all(d.overhang_id is not None for d in domains):
            result.add(hid)
    return result


def _group_helices_by_z_segment(helices: "List[Helix]", plane: str) -> "List[List[Helix]]":
    """Group helices into Z-segments by Z-range overlap.

    Coaxially stacked bundles occupy distinct, non-overlapping Z ranges.
    Helices whose Z-ranges overlap are placed in the same segment; helices
    with a gap between their Z-ranges are placed in separate segments.

    Using overlap (rather than matching lo offsets) handles designs where one
    helix starts a few bp earlier or later than its neighbours — they still
    belong to the same layer and must be routed together.
    """
    tol: float = BDNA_RISE_PER_BP * 0.5

    # Build (lo, hi) intervals for each helix.
    intervals: list[tuple[float, float]] = []
    for h in helices:
        lo = _helix_axis_lo(h, plane)
        hi = _helix_axis_hi(h, plane)
        intervals.append((lo, hi))

    # Union-find: merge any two helices whose Z-intervals overlap.
    parent = list(range(len(helices)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(i)] = find(j)

    for i in range(len(helices)):
        lo_i, hi_i = intervals[i]
        for j in range(i + 1, len(helices)):
            lo_j, hi_j = intervals[j]
            # Overlap if the intervals share more than tol of Z-range.
            overlap = min(hi_i, hi_j) - max(lo_i, lo_j)
            if overlap > tol:
                union(i, j)

    # Collect groups.
    groups: dict[int, list] = {}
    for i, h in enumerate(helices):
        root = find(i)
        groups.setdefault(root, []).append(h)
    return list(groups.values())


def _infer_plane(helices: "List[Helix]") -> str:
    """Infer lattice plane from helix IDs (h_{PLANE}_{row}_{col}...)."""
    for h in helices:
        if "_XY_" in h.id:
            return "XY"
        if "_XZ_" in h.id:
            return "XZ"
        if "_YZ_" in h.id:
            return "YZ"
    return "XY"


def _helix_adjacency_graph(
    design: Design,
    min_end_margin: int = 9,
    *,
    virtual_to_real: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Build XY-adjacency graph for scaffold routing.

    Two helices are adjacent if there is at least one valid scaffold crossover
    candidate between them (backbone beads within MAX_CROSSOVER_REACH_NM with
    ≥ min_end_margin bp from each end).

    Returns hid → sorted list of adjacent hids (sorted by XY centre-to-centre
    distance ascending so the greedy algorithm always picks the nearest neighbour
    in a deterministic order).

    virtual_to_real: optional mapping from virtual helix IDs (e.g. h_XY_2_0_seg0)
    to real helix IDs (e.g. h_XY_2_0).  When provided, it is used as a fallback
    to look up scaffold direction for virtual helices whose IDs don't appear in
    design.strands.
    """
    helices_by_id = {h.id: h for h in design.helices}
    helix_ids = list(helices_by_id.keys())

    scaf_dir: dict[str, Direction | None] = {}
    for hid in helix_ids:
        d = _get_scaffold_direction(design, hid)
        if d is None and virtual_to_real is not None:
            real_hid = virtual_to_real.get(hid, hid)
            d = _get_scaffold_direction(design, real_hid)
        scaf_dir[hid] = d

    # XY centres for distance sorting
    def _xy(h: Helix) -> tuple[float, float]:
        return (h.axis_start.x, h.axis_start.y)

    adjacency: dict[str, list[str]] = {hid: [] for hid in helix_ids}

    for i, hid_a in enumerate(helix_ids):
        for hid_b in helix_ids[i + 1:]:
            dir_a = scaf_dir[hid_a]
            dir_b = scaf_dir[hid_b]
            if dir_a is None or dir_b is None:
                continue
            h_a = helices_by_id[hid_a]
            h_b = helices_by_id[hid_b]
            adjacency[hid_a].append(hid_b)
            adjacency[hid_b].append(hid_a)

    # Sort each neighbour list by XY distance (nearest first) for determinism
    for hid, neighbours in adjacency.items():
        cx, cy = _xy(helices_by_id[hid])
        adjacency[hid] = sorted(
            neighbours,
            key=lambda nb: (helices_by_id[nb].axis_start.x - cx) ** 2
                         + (helices_by_id[nb].axis_start.y - cy) ** 2,
        )

    return adjacency


def _greedy_hamiltonian_path(
    adjacency: dict[str, list[str]],
    start_id: str,
) -> list[str] | None:
    """Greedy nearest-neighbour Hamiltonian path.

    Starts at *start_id* and at each step visits the first unvisited neighbour
    in *adjacency[current]* (neighbours are pre-sorted by XY distance ascending).
    Returns the path if all nodes are visited, None if the greedy walk gets stuck.
    """
    n = len(adjacency)
    visited: set[str] = {start_id}
    path: list[str] = [start_id]

    while len(path) < n:
        current = path[-1]
        moved = False
        for nb in adjacency[current]:
            if nb not in visited:
                visited.add(nb)
                path.append(nb)
                moved = True
                break
        if not moved:
            return None  # stuck — greedy failed

    return path


def _backtrack_hamiltonian_path(
    adjacency: dict[str, list[str]],
    start_id: str,
) -> list[str] | None:
    """Exact Hamiltonian path search via backtracking DFS.

    Neighbours are tried in XY-distance order (pre-sorted in *adjacency*) so the
    first solution found is typically the geographically compact one.  For typical
    DNA origami designs (≤ ~100 helices) this is fast enough to run inline.
    """
    n = len(adjacency)

    def _dfs(path: list[str], visited: set[str]) -> bool:
        if len(path) == n:
            return True
        for nb in adjacency[path[-1]]:
            if nb not in visited:
                visited.add(nb)
                path.append(nb)
                if _dfs(path, visited):
                    return True
                path.pop()
                visited.discard(nb)
        return False

    path: list[str] = [start_id]
    return path if _dfs(path, {start_id}) else None


def compute_scaffold_routing(
    design: Design,
    min_end_margin: int = 9,
) -> list[str] | None:
    """Find a Hamiltonian path through helices for scaffold routing.

    Returns an ordered list of helix_ids starting from the first helix in
    ``design.helices``, or None if no Hamiltonian path exists from that start.

    Algorithm:
      1. Build adjacency: helices as nodes, edges where valid scaffold crossover
         candidates exist (≥ min_end_margin bp from each end).
      2. Greedy nearest-neighbour walk from design.helices[0] (fast path).
      3. If greedy gets stuck, fall back to full backtracking DFS from the
         same start, which is exact but still fast for typical designs (≤ ~100 helices).
    """
    skip = _overhang_only_helix_ids(design)
    helices = [h for h in design.helices if h.id not in skip]
    if not helices:
        return []
    if len(helices) == 1:
        return [helices[0].id]

    sub_design = design.model_copy(update={"helices": helices})
    adjacency = _helix_adjacency_graph(sub_design, min_end_margin)
    start_id  = helices[0].id

    path = _greedy_hamiltonian_path(adjacency, start_id)
    if path is not None:
        return path

    return _backtrack_hamiltonian_path(adjacency, start_id)


def _select_outer_rails(helices: "List[Helix]", plane: str) -> "tuple[str, str]":
    """Select the two outer-rail helix IDs for seam-line routing.

    Outer rails receive no seam crossovers; they run as full-length single domains.

    - **Uniform design** (all helices span the same Z extent): rail_1 = first helix in
      design order (lowest index), rail_2 = last helix (highest index).
    - **Cross-section design** (some helices span only part of the Z extent):
      rail_1 = first full-span helix (lowest design index among helices that cover the
      global Z extremes), rail_2 = last partial helix (highest design index among helices
      that do NOT cover the global Z extremes).
    """
    tol = BDNA_RISE_PER_BP * 0.5
    global_lo = min(_helix_axis_lo(h, plane) for h in helices)
    global_hi = max(_helix_axis_hi(h, plane) for h in helices)

    full_span_ids = {
        h.id for h in helices
        if abs(_helix_axis_lo(h, plane) - global_lo) <= tol
        and abs(_helix_axis_hi(h, plane) - global_hi) <= tol
    }
    partial = [h for h in helices if h.id not in full_span_ids]

    if not partial:
        # Uniform design: first and last by design order.
        return helices[0].id, helices[-1].id

    # Cross-section: lowest-index full-span + highest-index partial.
    full_span_ordered = [h for h in helices if h.id in full_span_ids]
    return full_span_ordered[0].id, partial[-1].id


def _scaffold_midpoints(design: "Design", helix_ids: "set[str]") -> "dict[str, int]":
    """Return the global bp midpoint of existing scaffold coverage on each helix in *helix_ids*.

    Midpoint = (min_bp + max_bp) // 2 across all scaffold domains touching that helix.
    Used to centre seam crossover search on the scaffold strand's actual midpoint rather
    than the helix's geometric centre.
    """
    bp_ranges: dict[str, list[int]] = {}
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        for d in s.domains:
            if d.helix_id in helix_ids:
                bp_ranges.setdefault(d.helix_id, []).extend([d.start_bp, d.end_bp])
    return {
        hid: (min(bps) + max(bps)) // 2
        for hid, bps in bp_ranges.items()
    }


def _scaffold_coverage_regions(
    design: "Design",
    helix_ids: "set[str]",
) -> "dict[str, list[tuple[int, int]]]":
    """Return contiguous scaffold bp coverage regions per helix.

    Returns dict[helix_id → [(lo_bp, hi_bp), ...]] — sorted, merged contiguous
    global bp ranges covered by scaffold strands.  A 'gap' (gap > 1 bp) separates
    distinct regions.  Helices with a single contiguous region return a one-element
    list.  Helices not covered by any scaffold domain are omitted.
    """
    # Collect (lo, hi) intervals per helix from each scaffold domain.
    intervals: dict[str, list[tuple[int, int]]] = {}
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        for d in s.domains:
            if d.helix_id not in helix_ids:
                continue
            lo = min(d.start_bp, d.end_bp)
            hi = max(d.start_bp, d.end_bp)
            intervals.setdefault(d.helix_id, []).append((lo, hi))

    regions: dict[str, list[tuple[int, int]]] = {}
    for hid, ivs in intervals.items():
        # Merge overlapping/adjacent intervals (gap tolerance = 1 bp).
        merged: list[tuple[int, int]] = []
        for lo, hi in sorted(ivs):
            if merged and lo <= merged[-1][1] + 1:
                merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
            else:
                merged.append((lo, hi))
        regions[hid] = merged
    return regions


def _expand_helices_for_seam(
    seg_helices: "list[Helix]",
    coverage_regions: "dict[str, list[tuple[int, int]]]",
    plane: str,
) -> "tuple[list[Helix], dict[str, str]]":
    """Expand merged (gap-continuation) helices into per-region virtual Helix objects.

    For helices with a single scaffold coverage region (or no coverage), the helix
    is returned unchanged with an identity mapping.  For helices with multiple
    non-contiguous regions (gap-continuation helices), a virtual Helix is created
    per region with the correct axis_start, axis_end, length_bp, and bp_start
    reflecting that region's physical extent.

    Returns
    -------
    virtual_helices : list[Helix]
        Replacement list — identity for simple helices, expanded for merged ones.
    virtual_to_real : dict[str, str]
        Maps each virtual helix ID back to the original real helix ID.
        For non-expanded helices: virtual_id == real_id.
    """
    virtual_helices: list[Helix] = []
    virtual_to_real: dict[str, str] = {}

    for h in seg_helices:
        hid = h.id
        regions = coverage_regions.get(hid)
        if not regions or len(regions) <= 1:
            # No expansion needed.
            virtual_helices.append(h)
            virtual_to_real[hid] = hid
            continue

        # Merged helix: split into one virtual helix per scaffold region.
        if plane == "XY":
            h_lo = h.axis_start.z
        elif plane == "XZ":
            h_lo = h.axis_start.y
        else:
            h_lo = h.axis_start.x

        from backend.core.constants import SQUARE_TWIST_PER_BP_RAD as _SQ_TWIST
        _HC_DX_OFFSETS = frozenset({6, 13})
        _HC_PERIOD     = 21
        _is_hc = abs(h.twist_per_bp_rad - _SQ_TWIST) >= 1e-4

        for seg_idx, (lo_bp, hi_bp) in enumerate(regions):
            # For HC gap-continuation helices, extend the virtual segment boundaries
            # into the gap so that scaffold strands reach a valid DX crossover
            # position rather than ending at the raw coverage boundary.
            if _is_hc and seg_idx < len(regions) - 1 and hi_bp % _HC_PERIOD not in _HC_DX_OFFSETS:
                next_seg_lo = regions[seg_idx + 1][0]
                p = hi_bp + 1
                while p % _HC_PERIOD not in _HC_DX_OFFSETS:
                    p += 1
                if p < next_seg_lo:
                    hi_bp = p
            if _is_hc and seg_idx > 0 and lo_bp % _HC_PERIOD not in _HC_DX_OFFSETS:
                prev_seg_hi = regions[seg_idx - 1][1]
                p = lo_bp - 1
                while p % _HC_PERIOD not in _HC_DX_OFFSETS:
                    p -= 1
                if p > prev_seg_hi:
                    lo_bp = p

            virt_id  = f"{hid}_seg{seg_idx}"
            seg_len  = hi_bp - lo_bp + 1
            lo_local = lo_bp - h.bp_start          # local offset from axis_start
            seg_z_lo = h_lo + lo_local * BDNA_RISE_PER_BP
            seg_z_hi = seg_z_lo + seg_len * BDNA_RISE_PER_BP

            if plane == "XY":
                ax_start = Vec3(x=h.axis_start.x, y=h.axis_start.y, z=seg_z_lo)
                ax_end   = Vec3(x=h.axis_end.x,   y=h.axis_end.y,   z=seg_z_hi)
            elif plane == "XZ":
                ax_start = Vec3(x=h.axis_start.x, y=seg_z_lo, z=h.axis_start.z)
                ax_end   = Vec3(x=h.axis_end.x,   y=seg_z_hi, z=h.axis_end.z)
            else:
                ax_start = Vec3(x=seg_z_lo, y=h.axis_start.y, z=h.axis_start.z)
                ax_end   = Vec3(x=seg_z_hi, y=h.axis_end.y,   z=h.axis_end.z)

            phase = h.phase_offset + lo_local * h.twist_per_bp_rad
            virt_h = Helix(
                id=virt_id,
                axis_start=ax_start,
                axis_end=ax_end,
                length_bp=seg_len,
                bp_start=lo_bp,
                phase_offset=phase,
                twist_per_bp_rad=h.twist_per_bp_rad,
                loop_skips=h.loop_skips,
                direction=h.direction,
            )
            virtual_helices.append(virt_h)
            virtual_to_real[virt_id] = hid

    return virtual_helices, virtual_to_real


def _find_seam_routing_path(
    sub_design: "Design",
    full_span_ids: "set[str]",
    min_end_margin: int = 9,
) -> "list[str] | None":
    """Find a Hamiltonian path where every full-span↔partial (cross-Z) transition
    falls at a seam-pair position (odd→even index), not an end-pair position.

    End-pair cross-Z transitions are blocked by the near-Z guard in
    ``scaffold_add_end_crossovers`` and would leave the scaffold split.

    Tries each helix as the starting point (full-span helices first), returning
    the first path where all cross-Z transitions are at odd indices.
    Falls back to the standard greedy Hamiltonian if no perfectly-valid path is
    found.
    """
    helices = sub_design.helices
    adjacency = _helix_adjacency_graph(sub_design, min_end_margin)

    def _cross_z_ok(path: "list[str]") -> bool:
        for i in range(len(path) - 1):
            a_full = path[i] in full_span_ids
            b_full = path[i + 1] in full_span_ids
            if a_full != b_full and i % 2 == 0:
                return False
        return True

    # Try full-span helices first, then partial — same deterministic order
    # as design.helices so that auto_scaffold and scaffold_add_end_crossovers
    # always pick the same starting point.
    ordered_starts = sorted(helices, key=lambda h: (0 if h.id in full_span_ids else 1, helices.index(h)))

    for start_h in ordered_starts:
        path = _greedy_hamiltonian_path(adjacency, start_h.id)
        if path is None:
            path = _backtrack_hamiltonian_path(adjacency, start_h.id)
        if path is not None and _cross_z_ok(path):
            return path

    # No perfectly-valid path found: fall back to the default (helices[0] start)
    path = _greedy_hamiltonian_path(adjacency, helices[0].id)
    if path is None:
        path = _backtrack_hamiltonian_path(adjacency, helices[0].id)
    return path


# ---------------------------------------------------------------------------
# Scaffold routing helpers extracted from auto_scaffold
# ---------------------------------------------------------------------------

def _find_dx_xover(
    h_a: "Helix",
    dir_a: "Direction",
    h_b: "Helix",
    dir_b: "Direction",
    target_bp_b: int,
    plane: str,
) -> "tuple[int, int, int, int]":
    """Return (g_lo_a, g_lo_b, g_hi_a, g_hi_b) for the best DX crossover pair.

    Uses the same geometry-based offset search as
    ``_build_seam_only_scaffold_strands``, minimising the sum of
    backbone–backbone distances at the two DX junctions (lo and lo+1).
    ``target_bp_b`` is the desired global bp on ``h_b`` (midpoint of the segment).
    """
    from backend.core.geometry import nucleotide_positions as _nuc_pos
    _La  = h_a.length_bp
    _Lb  = h_b.length_bp
    _lza = _helix_axis_lo(h_a, plane)
    _lzb = _helix_axis_lo(h_b, plane)
    _dbp = round((_lzb - _lza) / BDNA_RISE_PER_BP)
    _mlo = max(0, _dbp)
    _mhi = min(_La - 2, _Lb - 2 + _dbp)
    _blb = target_bp_b - h_b.bp_start
    _bla = max(_mlo, min(_blb + _dbp, _mhi))
    _pa  = {n.bp_index: n.position for n in _nuc_pos(h_a) if n.direction == dir_a}
    _pb  = {n.bp_index: n.position for n in _nuc_pos(h_b) if n.direction == dir_b}
    _best = _bla
    _bdst = float("inf")
    for _delta in _SEAM_SEARCH_OFFSETS:
        _la = max(_mlo, min(_bla + _delta, _mhi))
        _lb = _la - _dbp
        if _lb < 0 or _lb > _Lb - 2:
            continue
        _gla  = h_a.bp_start + _la
        _glb  = h_b.bp_start + _lb
        _palo = _pa.get(_gla)
        _pblo = _pb.get(_glb)
        _pahi = _pa.get(_gla + 1)
        _pbhi = _pb.get(_glb + 1)
        if _palo is None or _pblo is None or _pahi is None or _pbhi is None:
            continue
        _dist = float(np.linalg.norm(_palo - _pblo)) + float(np.linalg.norm(_pahi - _pbhi))
        if _dist < _bdst:
            _bdst = _dist
            _best = _la
    _lo_a = _best
    _lo_b = _lo_a - _dbp
    return (h_a.bp_start + _lo_a, h_b.bp_start + _lo_b,
            h_a.bp_start + _lo_a + 1, h_b.bp_start + _lo_b + 1)


def _route_merged_cross_section_virt_seg(
    sub_design: "Design",
    virtual_to_real: "dict[str, str]",
    full_virt: "list[Helix]",
    partial_virt: "list[Helix]",
    seam_bp: "int | None",
    plane: str,
    min_end_margin: int,
) -> "list[list[Domain]]":
    """Route a merged cross-section virtual Z-segment via 3-sub-bundle bridge strategy.

    Called only when ``mode == 'seam_line'``, ``is_cross_section`` is True, and
    ``has_merged`` is True, and both ``full_virt`` and ``partial_virt`` are non-empty.

    Returns a list of domain lists — one per scaffold strand.
    The caller assigns strand IDs and creates Strand objects.
    """
    from backend.core.models import Direction, Domain, Strand, StrandType  # noqa: F401

    partial_z_groups = sorted(
        _group_helices_by_z_segment(partial_virt, plane),
        key=lambda g: min(_helix_axis_lo(h, plane) for h in g),
    )

    # ── Step 1: Route 6HB core (full_virt, full Z range) ─────────────────────
    full_virt_by_id = {h.id: h for h in full_virt}
    full_to_real    = {h.id: virtual_to_real.get(h.id, h.id) for h in full_virt}
    full_scaf_dirs: "dict[str, Direction]" = {}
    for _fh in full_virt:
        _d = _get_scaffold_direction(sub_design, full_to_real[_fh.id])
        if _d is None:
            raise ValueError(f"No scaffold direction for {full_to_real[_fh.id]}")
        full_scaf_dirs[_fh.id] = _d

    full_sub_d = sub_design.model_copy(update={"helices": full_virt})
    full_adj   = _helix_adjacency_graph(full_sub_d, min_end_margin)

    _partial_xy = [(h.axis_start.x, h.axis_start.y) for h in partial_virt]

    def _adj_to_partial(fh: "Helix") -> bool:
        for _px, _py in _partial_xy:
            if math.sqrt((fh.axis_start.x - _px) ** 2 + (fh.axis_start.y - _py) ** 2) <= HONEYCOMB_HELIX_SPACING * 1.05:
                return True
        return False

    _full_sorted = sorted(full_virt, key=lambda h: (0 if _adj_to_partial(h) else 1))
    full_path: "list[str] | None" = None
    for _sh in _full_sorted:
        _p = _greedy_hamiltonian_path(full_adj, _sh.id)
        if _p is None:
            _p = _backtrack_hamiltonian_path(full_adj, _sh.id)
        if _p:
            full_path = _p
            break

    def _fallback_no_bridge() -> "list[list[Domain]]":
        """Route each Z group independently, without a bridge crossover."""
        dl_out: "list[list[Domain]]" = []
        if full_path and len(full_path) >= 4:
            _fi = set(full_path[1:-1])
            _inner_real_fb = {full_to_real.get(v, v) for v in _fi}
            _real_mids_fb  = _scaffold_midpoints(sub_design, _inner_real_fb)
            _fm: "dict[str, int]" = {}
            for _v in _fi:
                _r  = full_to_real.get(_v, _v)
                _vh = full_virt_by_id[_v]
                _fm[_v] = (_vh.bp_start + _vh.length_bp // 2) if _v != _r else _real_mids_fb.get(_r, _vh.bp_start + _vh.length_bp // 2)
            _fd = _build_seam_only_scaffold_strands(
                full_path, full_virt_by_id, full_scaf_dirs, seam_bp=seam_bp, plane=plane, midpoints_by_hid=_fm,
            )
            dl_out.extend(
                [d.model_copy(update={"helix_id": full_to_real.get(d.helix_id, d.helix_id)}) for d in dl]
                for dl in _fd
            )
        for _grp in partial_z_groups:
            _gbi = {h.id: h for h in _grp}
            _gtr = {h.id: virtual_to_real.get(h.id, h.id) for h in _grp}
            _gsd = sub_design.model_copy(update={"helices": _grp})
            _ga  = _helix_adjacency_graph(_gsd, min_end_margin, virtual_to_real=virtual_to_real)
            _gp: "list[str] | None" = None
            for _sh in _grp:
                _q = _greedy_hamiltonian_path(_ga, _sh.id) or _backtrack_hamiltonian_path(_ga, _sh.id)
                if _q:
                    _gp = _q
                    break
            if _gp is None or len(_gp) < 4:
                continue
            _gds: "dict[str, Direction]" = {}
            for _v in _gp:
                _dd = _get_scaffold_direction(sub_design, _gtr.get(_v, _v))
                if _dd is None:
                    raise ValueError(f"No scaffold direction for {_gtr.get(_v, _v)}")
                _gds[_v] = _dd
            _gi = set(_gp[1:-1])
            _real_mids_gfb = _scaffold_midpoints(sub_design, {_gtr.get(v, v) for v in _gi})
            _gm_fb: "dict[str, int]" = {}
            for _v in _gi:
                _r  = _gtr.get(_v, _v)
                _vh = _gbi[_v]
                _gm_fb[_v] = (_vh.bp_start + _vh.length_bp // 2) if _v != _r else _real_mids_gfb.get(_r, _vh.bp_start + _vh.length_bp // 2)
            _gdl = _build_seam_only_scaffold_strands(
                _gp, _gbi, _gds, seam_bp=seam_bp, plane=plane, midpoints_by_hid=_gm_fb,
            )
            dl_out.extend(
                [d.model_copy(update={"helix_id": _gtr.get(d.helix_id, d.helix_id)}) for d in dl]
                for dl in _gdl
            )
        return dl_out

    if full_path is None or len(full_path) < 4:
        return _fallback_no_bridge()

    # Compute 6HB domain lists (full Z range) — needed for bridge construction.
    _fi_full         = set(full_path[1:-1])
    _inner_real_full = {full_to_real.get(v, v) for v in _fi_full}
    _real_mids_full  = _scaffold_midpoints(sub_design, _inner_real_full)
    _fm_full: "dict[str, int]" = {}
    for _v in _fi_full:
        _r  = full_to_real.get(_v, _v)
        _vh = full_virt_by_id[_v]
        _fm_full[_v] = (_vh.bp_start + _vh.length_bp // 2) if _v != _r else _real_mids_full.get(_r, _vh.bp_start + _vh.length_bp // 2)
    full_dl = _build_seam_only_scaffold_strands(
        full_path, full_virt_by_id, full_scaf_dirs, seam_bp=seam_bp, plane=plane, midpoints_by_hid=_fm_full,
    )
    full_dl = [
        [d.model_copy(update={"helix_id": full_to_real.get(d.helix_id, d.helix_id)}) for d in dl]
        for dl in full_dl
    ]

    # ── Step 2: Route each 12HB segment (partial helices only) ───────────────
    seg_paths:        "list[list[str] | None]"   = []
    seg_dl_lists:     "list[list[list[Domain]]]" = []
    seg_by_id_list:   "list[dict[str, Helix]]"   = []
    seg_to_real_list: "list[dict[str, str]]"     = []

    for _grp in partial_z_groups:
        _gbi  = {h.id: h for h in _grp}
        _gtr  = {h.id: virtual_to_real.get(h.id, h.id) for h in _grp}
        _gsd  = sub_design.model_copy(update={"helices": _grp})
        _ga   = _helix_adjacency_graph(_gsd, min_end_margin, virtual_to_real=virtual_to_real)
        _pids = {h.id for h in _grp}
        _gp: "list[str] | None" = None
        for _sh in _grp:
            _q = _greedy_hamiltonian_path(_ga, _sh.id) or _backtrack_hamiltonian_path(_ga, _sh.id)
            if _q and _q[-1] in _pids:
                _gp = _q
                break
        if _gp is None:
            for _sh in _grp:
                _q = _greedy_hamiltonian_path(_ga, _sh.id) or _backtrack_hamiltonian_path(_ga, _sh.id)
                if _q:
                    _gp = _q
                    break
        seg_paths.append(_gp)
        seg_by_id_list.append(_gbi)
        seg_to_real_list.append(_gtr)

        if _gp is None or len(_gp) < 4:
            seg_dl_lists.append([])
            continue

        _gds2: "dict[str, Direction]" = {}
        for _v in _gp:
            _dd = _get_scaffold_direction(sub_design, _gtr.get(_v, _v))
            if _dd is None:
                raise ValueError(f"No scaffold direction for {_gtr.get(_v, _v)}")
            _gds2[_v] = _dd
        _gi2         = set(_gp[1:-1])
        _real_mids_g = _scaffold_midpoints(sub_design, {_gtr.get(v, v) for v in _gi2})
        _gm2: "dict[str, int]" = {}
        for _v in _gi2:
            _r  = _gtr.get(_v, _v)
            _vh = _gbi[_v]
            _gm2[_v] = (_vh.bp_start + _vh.length_bp // 2) if _v != _r else _real_mids_g.get(_r, _vh.bp_start + _vh.length_bp // 2)
        _gdl2 = _build_seam_only_scaffold_strands(
            _gp, _gbi, _gds2, seam_bp=seam_bp, plane=plane, midpoints_by_hid=_gm2,
        )
        seg_dl_lists.append([
            [d.model_copy(update={"helix_id": _gtr.get(d.helix_id, d.helix_id)}) for d in dl]
            for dl in _gdl2
        ])

    # ── Step 3: Find bridge pair (6HB core rail ↔ 12HB outer rail) ──────────
    bridge_found = False
    if (
        len(partial_z_groups) == 2
        and seg_paths[0] is not None and len(seg_paths[0]) >= 4
        and seg_paths[1] is not None and len(seg_paths[1]) >= 4
        and seg_dl_lists[0] and seg_dl_lists[1]
    ):
        seg0_path    = seg_paths[0]
        seg1_path    = seg_paths[1]
        seg0_by_id   = seg_by_id_list[0]
        seg1_by_id   = seg_by_id_list[1]
        seg0_to_real = seg_to_real_list[0]
        seg1_to_real = seg_to_real_list[1]
        seg0_dl      = seg_dl_lists[0]
        seg1_dl      = seg_dl_lists[1]

        seg0_rail_vids = [seg0_path[0], seg0_path[-1]]
        seg1_rail_vids = [seg1_path[0], seg1_path[-1]]
        core_rail_vids = [full_path[0], full_path[-1]]

        bridge_core_vid:      "str | None" = None
        bridge_adj_real:      "str | None" = None
        bridge_seg0_vid:      "str | None" = None
        bridge_seg1_vid:      "str | None" = None
        bridge_core_rail_idx: int = 0
        bridge_seg0_rail_idx: int = 0
        bridge_seg1_rail_idx: int = 0

        for _ci, _core_vid in enumerate(core_rail_vids):
            _hcv = full_virt_by_id[_core_vid]
            for _si, _seg0_vid in enumerate(seg0_rail_vids):
                _has0 = seg0_by_id[_seg0_vid]
                if math.sqrt((_hcv.axis_start.x - _has0.axis_start.x) ** 2
                             + (_hcv.axis_start.y - _has0.axis_start.y) ** 2) > HONEYCOMB_HELIX_SPACING * 1.05:
                    continue
                _adj_real = seg0_to_real[_seg0_vid]
                _seg1_match = next(
                    (_v for _v in seg1_rail_vids if seg1_to_real[_v] == _adj_real), None,
                )
                if _seg1_match is None:
                    continue
                _has1 = seg1_by_id[_seg1_match]
                if math.sqrt((_hcv.axis_start.x - _has1.axis_start.x) ** 2
                             + (_hcv.axis_start.y - _has1.axis_start.y) ** 2) > HONEYCOMB_HELIX_SPACING * 1.05:
                    continue
                bridge_core_vid      = _core_vid
                bridge_adj_real      = _adj_real
                bridge_seg0_vid      = _seg0_vid
                bridge_seg1_vid      = _seg1_match
                bridge_core_rail_idx = _ci
                bridge_seg0_rail_idx = _si
                bridge_seg1_rail_idx = seg1_rail_vids.index(_seg1_match)
                bridge_found         = True
                break
            if bridge_found:
                break

    if not bridge_found:
        return _fallback_no_bridge()

    # ── Steps 4-6: Compute DX bridge crossovers and build fragments ──────────
    h_core_v = full_virt_by_id[bridge_core_vid]
    h_adj_s0 = seg0_by_id[bridge_seg0_vid]
    h_adj_s1 = seg1_by_id[bridge_seg1_vid]
    core_real = full_to_real[bridge_core_vid]
    adj_real  = bridge_adj_real
    core_dir  = full_scaf_dirs[bridge_core_vid]
    adj_dir   = _get_scaffold_direction(sub_design, adj_real)
    if adj_dir is None:
        raise ValueError(f"No scaffold direction for {adj_real}")

    _xov0 = _find_dx_xover(h_core_v, core_dir, h_adj_s0, adj_dir,
                            h_adj_s0.bp_start + h_adj_s0.length_bp // 2, plane)
    _xov1 = _find_dx_xover(h_core_v, core_dir, h_adj_s1, adj_dir,
                            h_adj_s1.bp_start + h_adj_s1.length_bp // 2, plane)
    g_lo_core_s0, g_lo_adj_s0, g_hi_core_s0, g_hi_adj_s0 = _xov0
    g_lo_core_s1, g_lo_adj_s1, g_hi_core_s1, g_hi_adj_s1 = _xov1

    core_d  = full_dl[bridge_core_rail_idx][0]
    seg0_d  = seg0_dl[bridge_seg0_rail_idx][0]
    seg1_d  = seg1_dl[bridge_seg1_rail_idx][0]
    core_5p, core_3p = core_d.start_bp, core_d.end_bp
    seg0_5p, seg0_3p = seg0_d.start_bp,  seg0_d.end_bp
    seg1_5p, seg1_3p = seg1_d.start_bp,  seg1_d.end_bp

    from backend.core.models import Direction as _Dir, Domain as _Dom  # noqa: E402
    if core_dir == _Dir.FORWARD:
        frag1 = [
            _Dom(helix_id=core_real, start_bp=core_5p,      end_bp=g_lo_core_s0, direction=_Dir.FORWARD),
            _Dom(helix_id=adj_real,  start_bp=g_lo_adj_s0,  end_bp=seg0_3p,      direction=_Dir.REVERSE),
        ]
        frag2a = [
            _Dom(helix_id=adj_real,  start_bp=seg0_5p,      end_bp=g_hi_adj_s0,  direction=_Dir.REVERSE),
            _Dom(helix_id=core_real, start_bp=g_hi_core_s0, end_bp=g_lo_core_s1, direction=_Dir.FORWARD),
            _Dom(helix_id=adj_real,  start_bp=g_lo_adj_s1,  end_bp=seg1_3p,      direction=_Dir.REVERSE),
        ]
        frag2b = [
            _Dom(helix_id=adj_real,  start_bp=seg1_5p,      end_bp=g_hi_adj_s1,  direction=_Dir.REVERSE),
            _Dom(helix_id=core_real, start_bp=g_hi_core_s1, end_bp=core_3p,      direction=_Dir.FORWARD),
        ]
    else:
        frag1 = [
            _Dom(helix_id=core_real, start_bp=core_5p,      end_bp=g_hi_core_s1, direction=_Dir.REVERSE),
            _Dom(helix_id=adj_real,  start_bp=g_hi_adj_s1,  end_bp=seg1_3p,      direction=_Dir.FORWARD),
        ]
        frag2a = [
            _Dom(helix_id=adj_real,  start_bp=seg1_5p,      end_bp=g_lo_adj_s1,  direction=_Dir.FORWARD),
            _Dom(helix_id=core_real, start_bp=g_lo_core_s1, end_bp=g_hi_core_s0, direction=_Dir.REVERSE),
            _Dom(helix_id=adj_real,  start_bp=g_hi_adj_s0,  end_bp=seg0_3p,      direction=_Dir.FORWARD),
        ]
        frag2b = [
            _Dom(helix_id=adj_real,  start_bp=seg0_5p,      end_bp=g_lo_adj_s0,  direction=_Dir.FORWARD),
            _Dom(helix_id=core_real, start_bp=g_lo_core_s0, end_bp=core_3p,      direction=_Dir.REVERSE),
        ]

    result: "list[list[Domain]]" = [frag1, frag2a, frag2b]
    result.append(full_dl[1 - bridge_core_rail_idx])
    result.extend(full_dl[2:])
    result.append(seg0_dl[1 - bridge_seg0_rail_idx])
    result.extend(seg0_dl[2:])
    result.append(seg1_dl[1 - bridge_seg1_rail_idx])
    result.extend(seg1_dl[2:])
    return result


def _route_standard_virt_seg(
    virt_sub: "Design",
    virt_seg: "list[Helix]",
    virtual_to_real: "dict[str, str]",
    sub_design: "Design",
    mode: str,
    full_span_ids: "set[str]",
    seam_bp: "int | None",
    plane: str,
    min_end_margin: int,
    nick_offset: int,
    scaffold_loops: bool,
) -> "list[list[Domain]]":
    """Route a single virtual Z-segment using standard (non-bridge) logic.

    Handles seam-line cross-section, simple seam-line, and end-to-end modes.
    Returns a list of domain lists — one per scaffold strand.
    """
    is_cross_section = len(full_span_ids) < len(virt_seg)

    if mode == "seam_line" and is_cross_section:
        path = _find_seam_routing_path(virt_sub, full_span_ids, min_end_margin)
        if path is None:
            seg_min_len = min(h.length_bp for h in virt_seg)
            eff_margin  = max(0, (seg_min_len - 1) // 2)
            if eff_margin < min_end_margin:
                path = _find_seam_routing_path(virt_sub, full_span_ids, eff_margin)
    else:
        path = compute_scaffold_routing(virt_sub, min_end_margin=min_end_margin)
        if path is None:
            seg_min_len = min(h.length_bp for h in virt_seg)
            eff_margin  = max(0, (seg_min_len - 1) // 2)
            if eff_margin < min_end_margin:
                path = compute_scaffold_routing(virt_sub, min_end_margin=eff_margin)

    if path is None:
        # Final fallback: per-virtual-helix end-to-end strands.
        result: "list[list[Domain]]" = []
        for virt_h in virt_seg:
            real_hid = virtual_to_real.get(virt_h.id, virt_h.id)
            d = _get_scaffold_direction(sub_design, real_hid)
            if d is None:
                d = _scaffold_direction_from_helix_id(real_hid)
            if d is None:
                continue
            from backend.core.models import Direction as _Dir, Domain as _Dom  # noqa: E402
            if d == _Dir.FORWARD:
                dom = _Dom(helix_id=real_hid, start_bp=virt_h.bp_start,
                           end_bp=virt_h.bp_start + virt_h.length_bp - 1, direction=d)
            else:
                dom = _Dom(helix_id=real_hid, start_bp=virt_h.bp_start + virt_h.length_bp - 1,
                           end_bp=virt_h.bp_start, direction=d)
            result.append([dom])
        return result

    if len(path) <= 1:
        return []

    virt_helices_by_id = {h.id: h for h in virt_seg}
    scaf_dirs: "dict" = {}
    for virt_hid in path:
        real_hid = virtual_to_real.get(virt_hid, virt_hid)
        d = _get_scaffold_direction(sub_design, real_hid)
        if d is None:
            raise ValueError(f"No scaffold direction found for helix {real_hid}")
        scaf_dirs[virt_hid] = d

    if mode == "seam_line":
        inner_virt_ids = set(path[1:-1])
        inner_real_ids = {virtual_to_real.get(v, v) for v in inner_virt_ids}
        real_midpoints = _scaffold_midpoints(sub_design, inner_real_ids)
        midpoints: "dict[str, int]" = {}
        for virt_hid in inner_virt_ids:
            real_hid = virtual_to_real.get(virt_hid, virt_hid)
            virt_h   = virt_helices_by_id[virt_hid]
            if virt_hid != real_hid:
                midpoints[virt_hid] = virt_h.bp_start + virt_h.length_bp // 2
            elif real_hid in real_midpoints:
                midpoints[virt_hid] = real_midpoints[real_hid]
        domain_lists = _build_seam_only_scaffold_strands(
            path, virt_helices_by_id, scaf_dirs, seam_bp=seam_bp, plane=plane,
            midpoints_by_hid=midpoints,
        )
        return [
            [d.model_copy(update={"helix_id": virtual_to_real.get(d.helix_id, d.helix_id)})
             for d in dl]
            for dl in domain_lists
        ]
    else:
        merged = _build_end_to_end_domains(
            path, virt_helices_by_id, scaf_dirs, nick_offset, scaffold_loops=scaffold_loops,
        )
        return [merged]


def auto_scaffold(
    design: Design,
    mode: str = "seam_line",
    nick_offset: int = 7,
    min_end_margin: int = 9,
    scaffold_loops: bool = False,
    seam_bp: int | None = None,
    loop_size: int = 7,
) -> Design:
    """Route the scaffold through all helices and replace per-helix scaffold strands.

    Parameters
    ----------
    design:
        Active design.  Must have an even number of helices (first-version constraint).
    mode:
        ``"seam_line"`` — mid-helix DX crossovers at valid backbone positions (default).
        ``"end_to_end"`` — full-domain concatenation, scaffold traverses each helix end-to-end.
    nick_offset:
        When *scaffold_loops* is False: number of bp from the terminal of helix 1 where
        the scaffold's 5′ end is placed (default 7).
        When *scaffold_loops* is True: ignored for the 5′ placement (scaffold starts at
        the physical terminus of helix 1, i.e. bp 0 or bp N−1).
    min_end_margin:
        For seam-line mode: minimum bp distance from helix ends for mid-helix crossovers.
    scaffold_loops:
        When True (default), the scaffold's 5′ domain is extended to the physical
        terminus of helix 1 (bp 0 for FORWARD, bp N−1 for REVERSE), creating a
        single-stranded loop at that blunt end.  The 3′ end is already at the physical
        terminus of the last helix.  Set to False to reproduce the legacy behaviour
        where the 5′ end is placed at *nick_offset* bp from the terminus.

    Raises
    ------
    ValueError
        If the number of helices is odd, if no Hamiltonian path exists, or if a
        required crossover position cannot be found (seam-line mode).
    """
    if len(design.helices) == 0:
        return design

    if mode not in ("seam_line", "end_to_end"):
        raise ValueError(f"Unknown scaffold routing mode {mode!r}. Use 'seam_line' or 'end_to_end'.")

    skip_ids = _overhang_only_helix_ids(design)
    routable_helices = [h for h in design.helices if h.id not in skip_ids]
    if not routable_helices:
        return design

    plane    = _infer_plane(routable_helices)
    segments = _group_helices_by_z_segment(routable_helices, plane)

    for seg_helices in segments:
        if len(seg_helices) % 2 != 0:
            raise ValueError(
                f"auto_scaffold requires an even number of helices per Z-segment "
                f"(a segment has {len(seg_helices)} helices). "
                "Add or remove a helix so every segment has an even count."
            )

    all_helix_ids = {h.id for h in routable_helices}
    scaf_ids_to_remove: set[str] = {
        s.id for s in design.strands
        if s.strand_type == StrandType.SCAFFOLD and any(d.helix_id in all_helix_ids for d in s.domains)
    }
    old_scaf_ids = sorted(s.id for s in design.strands if s.id in scaf_ids_to_remove)
    base_strands = [s for s in design.strands if s.id not in scaf_ids_to_remove]

    _id_counter: list[int] = [0]

    def _new_scaf_id() -> str:
        j = _id_counter[0]
        _id_counter[0] += 1
        return old_scaf_ids[j] if j < len(old_scaf_ids) else f"scaffold_{j}"

    all_new_strands: list[Strand] = []

    for seg_helices in segments:
        sub_design = design.model_copy(update={"helices": seg_helices})
        all_helix_ids_for_regions = {h.id for h in seg_helices}
        coverage_regions = _scaffold_coverage_regions(sub_design, all_helix_ids_for_regions)
        virt_helices, virtual_to_real = _expand_helices_for_seam(seg_helices, coverage_regions, plane)
        has_merged = len(virt_helices) > len(seg_helices)
        virt_z_segs = (
            _group_helices_by_z_segment(virt_helices, plane) if has_merged else [virt_helices]
        )

        for virt_seg in virt_z_segs:
            virt_sub = sub_design.model_copy(update={"helices": virt_seg})
            tol = BDNA_RISE_PER_BP * 0.5
            global_lo_seg = min(_helix_axis_lo(h, plane) for h in virt_seg)
            full_span_ids = {
                h.id for h in virt_seg
                if abs(_helix_axis_lo(h, plane) - global_lo_seg) <= tol
            }
            is_cross_section = len(full_span_ids) < len(virt_seg)

            if mode == "seam_line" and is_cross_section and has_merged:
                global_hi_seg     = max(_helix_axis_hi(h, plane) for h in virt_seg)
                actually_full_ids = {
                    h.id for h in virt_seg
                    if abs(_helix_axis_lo(h, plane) - global_lo_seg) <= tol
                    and abs(_helix_axis_hi(h, plane) - global_hi_seg) <= tol
                }
                full_virt    = [h for h in virt_seg if h.id in actually_full_ids]
                partial_virt = [h for h in virt_seg if h.id not in actually_full_ids]

                if partial_virt and full_virt:
                    domain_lists = _route_merged_cross_section_virt_seg(
                        sub_design=sub_design,
                        virtual_to_real=virtual_to_real,
                        full_virt=full_virt,
                        partial_virt=partial_virt,
                        seam_bp=seam_bp,
                        plane=plane,
                        min_end_margin=min_end_margin,
                    )
                    all_new_strands.extend(
                        Strand(id=_new_scaf_id(), domains=dl, strand_type=StrandType.SCAFFOLD)
                        for dl in domain_lists
                    )
                    continue

            domain_lists = _route_standard_virt_seg(
                virt_sub=virt_sub,
                virt_seg=virt_seg,
                virtual_to_real=virtual_to_real,
                sub_design=sub_design,
                mode=mode,
                full_span_ids=full_span_ids,
                seam_bp=seam_bp,
                plane=plane,
                min_end_margin=min_end_margin,
                nick_offset=nick_offset,
                scaffold_loops=scaffold_loops,
            )
            all_new_strands.extend(
                Strand(id=_new_scaf_id(), domains=dl, strand_type=StrandType.SCAFFOLD)
                for dl in domain_lists
            )

    from backend.core.crossover_positions import extract_crossovers_from_strands
    new_all_strands = base_strands + all_new_strands
    return design.model_copy(update={
        "strands":    new_all_strands,
        "crossovers": extract_crossovers_from_strands(new_all_strands),
    })


def auto_scaffold_seamless(
    design: Design,
    min_staple_margin: int = 3,
) -> Design:
    """Route scaffold with seamless (no-seam) crossovers — full left + right pass.

    Resets scaffold to per-helix full-span strands, then:

    Phase 1 — left-side crossovers: connects adjacent helix pairs via crossovers
    extended into negative-bp space, producing N/2 two-helix scaffold strands.

    Phase 2 — right-side crossovers: merges those strands by extending rightward
    past each helix boundary and connecting adjacent pairs.  The result is one
    long linear scaffold that zig-zags through the entire design.  The last pair
    that would close the loop is extended but NOT ligated — those two ends become
    the scaffold's 5′ and 3′ termini for sequence assignment.

    Parameters
    ----------
    design:
        Active design.
    min_staple_margin:
        Minimum bp distance from any staple end to the crossover position (default 3).

    Returns
    -------
    Updated Design with a single continuous scaffold strand spanning all helices
    (or as few strands as the lattice topology allows).

    Raises
    ------
    ValueError
        If no left-side crossovers could be placed (e.g. single isolated helix).
    """
    skip_ids     = _overhang_only_helix_ids(design)
    routable     = [h for h in design.helices if h.id not in skip_ids]
    routable_ids = {h.id for h in routable}

    # ── Step 1: reset to per-helix full-span scaffold strands ─────────────────
    # Remove any existing scaffold strands that touch routable helices.
    base_strands = [
        s for s in design.strands
        if not (s.strand_type == StrandType.SCAFFOLD
                and any(d.helix_id in routable_ids for d in s.domains))
    ]

    new_scaffold: list[Strand] = []
    for h in routable:
        if h.grid_pos is None:
            continue
        row, col  = h.grid_pos
        direction = scaffold_direction_for_cell(row, col)
        L         = h.length_bp
        strand_id = h.id.replace("h_", "scaf_", 1)
        if direction == Direction.FORWARD:
            dom = Domain(helix_id=h.id, start_bp=h.bp_start,
                         end_bp=h.bp_start + L - 1, direction=direction)
        else:
            dom = Domain(helix_id=h.id, start_bp=h.bp_start + L - 1,
                         end_bp=h.bp_start, direction=direction)
        new_scaffold.append(Strand(
            id=strand_id,
            domains=[dom],
            strand_type=StrandType.SCAFFOLD,
        ))

    design = design.model_copy(update={"strands": base_strands + new_scaffold})

    # ── Step 2: add left-side crossovers ──────────────────────────────────────
    design = _scaffold_add_left_end_crossovers(design, min_staple_margin)

    # ── Step 3: add right-side crossovers (completes the scaffold loop) ───────
    design = _scaffold_add_right_end_crossovers(design, min_staple_margin)

    from backend.core.crossover_positions import extract_crossovers_from_strands
    return design.model_copy(update={
        "crossovers": extract_crossovers_from_strands(design.strands),
    })


# ── Scaffold upper-bp sets (bow-right / upper of crossover pair) ──────────────
# These are the bp mod period values that are the "upper" of each scaffold
# crossover pair.  An upper bp bows to the right in pathview; a lower bp bows
# to the left.  Used to determine nick positions for middle crossovers.
_HC_SCAF_UPPER: frozenset[int] = frozenset({2, 5, 9, 12, 16, 19})
_SQ_SCAF_UPPER: frozenset[int] = frozenset({0, 3, 5, 8, 11, 13, 16, 19, 21, 24, 27, 29})


def _scaffold_upper_set(lattice_type: LatticeType) -> frozenset[int]:
    return _HC_SCAF_UPPER if lattice_type == LatticeType.HONEYCOMB else _SQ_SCAF_UPPER


def auto_scaffold_basic(
    design: Design,
    min_staple_margin: int = 3,
    scan_bp: int = 48,
) -> Design:
    """Route a single continuous scaffold strand via L/M/R crossover pattern.

    Creates three classes of crossovers:
    - **Left (L)**: ss-loop crossovers extending past ``bp_start`` (even-index pairs
      along the Hamiltonian path).
    - **Middle (M)**: standard DX crossovers inside the helices near their midpoint
      (odd-index pairs along the Hamiltonian path).
    - **Right (R)**: ss-loop crossovers extending past ``bp_end`` (same pairs as L).

    The outermost two helices in the path (``path[0]`` and ``path[-1]``) act as
    "rails": they participate in L/R crossovers but never in M crossovers, so their
    scaffold domains remain straight across the full helix length.

    The final result is **one scaffold strand** with two open termini.

    Parameters
    ----------
    design:
        Active design with staple strands already placed.
    min_staple_margin:
        Minimum bp gap between a crossover position and any staple end (default 3).
    scan_bp:
        Search window (in bp) for valid scaffold crossover positions (default 48).

    Raises
    ------
    ValueError
        If no Hamiltonian path exists or no valid crossover positions are found.
    """
    from backend.core.crossover_positions import extract_crossovers_from_strands
    from collections import defaultdict

    skip_ids     = _overhang_only_helix_ids(design)
    routable     = [h for h in design.helices if h.id not in skip_ids]
    routable_ids = {h.id for h in routable}

    if len(routable) < 2:
        raise ValueError("auto_scaffold_basic requires at least 2 routable helices.")

    # ── Step 0: compute Hamiltonian path and derive L/M pairings ─────────────
    path = compute_scaffold_routing(design)
    if path is None or len(path) < 2:
        raise ValueError("No valid scaffold routing path found for this design.")

    lr_pairs  = [(path[i], path[i + 1]) for i in range(0, len(path) - 1, 2)]
    mid_pairs = [(path[i], path[i + 1]) for i in range(1, len(path) - 1, 2)]
    lr_set    = {(min(a, b), max(a, b)) for a, b in lr_pairs}

    # ── Step 1: reset to per-helix full-span scaffold strands ────────────────
    base_strands = [
        s for s in design.strands
        if not (s.strand_type == StrandType.SCAFFOLD
                and any(d.helix_id in routable_ids for d in s.domains))
    ]

    new_scaffold: list[Strand] = []
    for h in routable:
        if h.grid_pos is None:
            continue
        row, col  = h.grid_pos
        direction = scaffold_direction_for_cell(row, col)
        L         = h.length_bp
        strand_id = h.id.replace("h_", "scaf_", 1)
        if direction == Direction.FORWARD:
            dom = Domain(helix_id=h.id, start_bp=h.bp_start,
                         end_bp=h.bp_start + L - 1, direction=direction)
        else:
            dom = Domain(helix_id=h.id, start_bp=h.bp_start + L - 1,
                         end_bp=h.bp_start, direction=direction)
        new_scaffold.append(Strand(
            id=strand_id,
            domains=[dom],
            strand_type=StrandType.SCAFFOLD,
        ))

    design = design.model_copy(update={"strands": base_strands + new_scaffold})

    # ── Step 2: left ss-loop crossovers (L/R pairs only) ─────────────────────
    design = _scaffold_add_left_end_crossovers(
        design, min_staple_margin, scan_bp, allowed_pairs=lr_set
    )

    # ── Step 3: middle crossovers (mid pairs) ────────────────────────────────
    design = _scaffold_add_middle_crossovers(
        design, mid_pairs, min_staple_margin, scan_bp
    )

    # ── Step 4: right ss-loop crossovers (L/R pairs in path order) ──────────
    # Use a dedicated pass instead of the generic _scaffold_add_right_end_crossovers
    # because after middle crossovers helices may have multiple scaffold domains from
    # different strands, breaking the generic function's helix→strand mapping.
    design = _scaffold_basic_add_right_crossovers(
        design, lr_pairs, min_staple_margin, scan_bp
    )

    # ── Step 5: refresh crossover registry ───────────────────────────────────
    return design.model_copy(update={
        "crossovers": extract_crossovers_from_strands(design.strands),
    })


def _scaffold_add_left_end_crossovers(
    design: Design,
    min_staple_margin: int = 3,
    scan_bp: int = 48,
    allowed_pairs: "set[tuple[str, str]] | None" = None,
) -> Design:
    """Connect adjacent scaffold strand pairs via crossovers on the low-bp side.

    Scans **leftward past each helix's bp_start** (into negative-bp space) for
    the nearest valid scaffold crossover with a lattice-adjacent helix in the
    design.  The scaffold domain is extended to that crossover position, creating
    a single-stranded scaffold loop between the crossover and bp_start.

    The crossover position X satisfies:
      - X < h.bp_start  (strictly outside the helix physical extent)
      - abs(X - staple_end) >= min_staple_margin for all staple ends on either helix

    Uses greedy matching (nearest crossover first) so each scaffold strand gets
    at most one crossover on this side.

    Raises ValueError if no crossovers could be placed.
    """
    from backend.core.crossover_positions import crossover_neighbor
    from collections import defaultdict

    cell_to_helix: dict[tuple[int, int], Helix] = {
        (h.grid_pos[0], h.grid_pos[1]): h
        for h in design.helices
        if h.grid_pos is not None
    }
    helix_map = {h.id: h for h in design.helices}

    # Collect staple end bp positions keyed by helix_id.
    staple_ends_by_helix: dict[str, set[int]] = defaultdict(set)
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        staple_ends_by_helix[first.helix_id].add(first.start_bp)
        staple_ends_by_helix[last.helix_id].add(last.end_bp)

    # Scan all bp positions leftward for every helix, recording the nearest valid
    # crossover per normalised pair key.  No early break — a single helix can reach
    # different lattice neighbours at different bp offsets (e.g. HC (0,2) FORWARD
    # reaches (0,1) at bp%21=20 and (0,3) at bp%21=6), so stopping after the first
    # hit would cause pairs like (0,2)↔(0,3) to go unrecorded.
    pair_to_x: dict[tuple[str, str], int] = {}

    for h in design.helices:
        if h.grid_pos is None:
            continue
        row, col  = h.grid_pos
        ends_h    = staple_ends_by_helix.get(h.id, set())

        for bp in range(h.bp_start - 1, h.bp_start - 1 - scan_bp, -1):
            nb = crossover_neighbor(design.lattice_type, row, col, bp, is_scaffold=True)
            if nb is None or nb not in cell_to_helix:
                continue
            h_nb  = cell_to_helix[nb]
            ends_nb = staple_ends_by_helix.get(h_nb.id, set())

            # Must be more than min_staple_margin bp from any staple end
            # on either helix (the nearest staple end is typically at bp_start).
            all_ends = ends_h | ends_nb
            if any(abs(bp - e) < min_staple_margin for e in all_ends):
                continue

            key = (min(h.id, h_nb.id), max(h.id, h_nb.id))
            if allowed_pairs is not None and key not in allowed_pairs:
                continue
            # Keep the least-negative (nearest to bp_start) position per pair.
            if key not in pair_to_x or bp > pair_to_x[key]:
                pair_to_x[key] = bp
            # Continue scanning — this helix may reach a different neighbour at a
            # farther bp offset, producing an additional entry in pair_to_x.

    if not pair_to_x:
        raise ValueError(
            "No valid left-side scaffold crossover positions found. "
            "Check that the design has adjacent helices in the lattice."
        )

    # Degree-first greedy maximum matching.
    #
    # Build per-helix adjacency lists sorted by bp descending (nearest to bp_start
    # first).  Then iteratively match the helix with the FEWEST available unmatched
    # neighbours — this prevents well-connected internal helices from "stealing" the
    # only partner of an endpoint helix (e.g. in a strip, end-helices have degree 1
    # and must be matched before their single shared neighbour is taken).
    adjacency: dict[str, list[tuple[int, str]]] = {}
    for (aid, bid), bp in pair_to_x.items():
        adjacency.setdefault(aid, []).append((bp, bid))
        adjacency.setdefault(bid, []).append((bp, aid))
    for hid in adjacency:
        adjacency[hid].sort(reverse=True)   # nearest bp first

    unmatched: set[str] = set(adjacency.keys())
    selected:  list[tuple[str, str, int]] = []

    while True:
        # Helices that still have at least one unmatched partner available.
        candidates = {
            hid for hid in unmatched
            if any(n in unmatched for _, n in adjacency[hid])
        }
        if not candidates:
            break
        # Pick the helix with the fewest available unmatched neighbours; break ties
        # deterministically by helix id so results are stable across Python runs.
        best = min(
            candidates,
            key=lambda hid: (len([n for _, n in adjacency[hid] if n in unmatched]), hid),
        )
        for bp, nbr in adjacency[best]:
            if nbr in unmatched:
                unmatched.discard(best)
                unmatched.discard(nbr)
                selected.append((best, nbr, bp))
                break

    if not selected:
        raise ValueError(
            "No adjacent helix pairs could be matched for left-side crossovers."
        )

    # Extend scaffold domains leftward to X and ligate paired strands.
    result = design
    for aid, bid, X in selected:
        dir_a = _get_scaffold_direction(result, aid)

        # Determine which helix carries the FORWARD scaffold (5′ end on the left)
        # and which carries the REVERSE scaffold (3′ end on the left).
        if dir_a == Direction.FORWARD:
            fwd_id, rev_id = aid, bid
        else:
            fwd_id, rev_id = bid, aid

        # Extend FORWARD domain: move 5′ end (start_bp) further left to X.
        result = _set_scaffold_domain_left_end(result, fwd_id, X, Direction.FORWARD)
        # Extend REVERSE domain: move 3′ end (end_bp) further left to X.
        result = _set_scaffold_domain_left_end(result, rev_id, X, Direction.REVERSE)

        # Ligate: REVERSE strand (3′ at X on rev_id) → FORWARD strand (5′ at X on fwd_id).
        s3 = _find_strand_by_3prime(result, rev_id, X, StrandType.SCAFFOLD)
        s5 = _find_strand_by_5prime(result, fwd_id, X, StrandType.SCAFFOLD)
        if s3 is not None and s5 is not None and s3.id != s5.id:
            result = _ligate(result, s3, s5)

    return result


def _extend_scaffold_3prime_terminal(
    design: Design,
    helix_id: str,
    new_end_bp: int,
    direction: Direction,
) -> Design:
    """Extend the 3′ terminal domain (last domain) of the scaffold strand on *helix_id*.

    Unlike ``_set_scaffold_domain_right_end``, this targets only the terminal domain
    (the last domain of a strand), not the first matching domain by helix/direction.
    This is important when a helix has multiple scaffold domains from different strands
    (as occurs after middle crossovers).
    """
    new_strands = []
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD or not s.domains:
            new_strands.append(s)
            continue
        last = s.domains[-1]
        if last.helix_id == helix_id and last.direction == direction:
            new_d = (last.model_copy(update={"end_bp": new_end_bp})
                     if direction == Direction.FORWARD
                     else last.model_copy(update={"start_bp": new_end_bp}))
            new_strands.append(s.model_copy(update={"domains": list(s.domains[:-1]) + [new_d]}))
        else:
            new_strands.append(s)
    return design.model_copy(update={"strands": new_strands})


def _extend_scaffold_5prime_terminal(
    design: Design,
    helix_id: str,
    new_start_bp: int,
    direction: Direction,
) -> Design:
    """Extend the 5′ terminal domain (first domain) of the scaffold strand on *helix_id*.

    Targets only the first domain of a strand, not any interior domain on the same helix.
    """
    new_strands = []
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD or not s.domains:
            new_strands.append(s)
            continue
        first = s.domains[0]
        if first.helix_id == helix_id and first.direction == direction:
            new_d = (first.model_copy(update={"start_bp": new_start_bp})
                     if direction == Direction.REVERSE
                     else first.model_copy(update={"end_bp": new_start_bp}))
            new_strands.append(s.model_copy(update={"domains": [new_d] + list(s.domains[1:])}))
        else:
            new_strands.append(s)
    return design.model_copy(update={"strands": new_strands})


def _scaffold_basic_add_right_crossovers(
    design: Design,
    lr_pairs: "list[tuple[str, str]]",
    min_staple_margin: int = 3,
    scan_bp: int = 48,
) -> Design:
    """Right-side ss-loop crossovers for ``auto_scaffold_basic``.

    Processes LR pairs in path order (not via greedy matching) and uses terminal-domain
    extension helpers to correctly handle helices that have multiple scaffold domains from
    different strands after middle crossovers.

    For each pair:
    - Finds the nearest valid scaffold crossover position X to the right of the helix edge.
    - Extends the FWD 3′ terminal (last domain) and the REV 5′ terminal (first domain) to X.
    - Ligates if they belong to different strands; skips ligation for the same-strand pair
      (which becomes the two open termini).
    """
    from backend.core.crossover_positions import crossover_neighbor
    from collections import defaultdict

    helix_map = {h.id: h for h in design.helices}
    cell_to_helix = {(h.grid_pos[0], h.grid_pos[1]): h
                     for h in design.helices if h.grid_pos is not None}

    staple_ends: dict[str, set[int]] = defaultdict(set)
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        staple_ends[first.helix_id].add(first.start_bp)
        staple_ends[last.helix_id].add(last.end_bp)

    result = design

    for aid, bid in lr_pairs:
        ha = helix_map.get(aid)
        hb = helix_map.get(bid)
        if ha is None or hb is None or ha.grid_pos is None or hb.grid_pos is None:
            continue

        dir_a = _get_scaffold_direction(result, aid)
        fwd_id = aid if dir_a == Direction.FORWARD else bid
        rev_id = bid if dir_a == Direction.FORWARD else aid
        h_fwd = helix_map[fwd_id]
        h_rev = helix_map[rev_id]

        bp_right = h_fwd.bp_start + h_fwd.length_bp
        all_ends = staple_ends.get(fwd_id, set()) | staple_ends.get(rev_id, set())

        # Find nearest valid scaffold crossover to the right of the helix edge.
        chosen_bp: int | None = None
        for bp in range(bp_right, bp_right + scan_bp):
            nb = crossover_neighbor(result.lattice_type, *h_fwd.grid_pos, bp, is_scaffold=True)
            if nb is None or nb != tuple(h_rev.grid_pos):
                continue
            if any(abs(bp - e) < min_staple_margin for e in all_ends):
                continue
            chosen_bp = bp
            break

        if chosen_bp is None:
            continue

        # Extend terminals — use terminal-specific helpers to avoid modifying interior
        # domains that share the same helix after middle crossovers.
        result = _extend_scaffold_3prime_terminal(result, fwd_id, chosen_bp, Direction.FORWARD)
        result = _extend_scaffold_5prime_terminal(result, rev_id, chosen_bp, Direction.REVERSE)

        # Ligate if they're different strands (skip for same-strand = open terminus pair).
        s3 = _find_strand_by_3prime(result, fwd_id, chosen_bp, StrandType.SCAFFOLD)
        s5 = _find_strand_by_5prime(result, rev_id, chosen_bp, StrandType.SCAFFOLD)
        if s3 is not None and s5 is not None and s3.id != s5.id:
            result = _ligate(result, s3, s5)

    return result


def _scaffold_add_middle_crossovers(
    design: Design,
    mid_pairs: "list[tuple[str, str]]",
    min_staple_margin: int = 3,
    scan_bp: int = 48,
) -> Design:
    """Add interior (middle) DX scaffold crossovers for each pair in *mid_pairs*.

    For each pair (aid, bid), scans near the helix midpoint for the nearest valid
    scaffold crossover position, nicks both helices at the crossover, then performs
    two ligations to form the DX crossover structure.

    The two ligations per crossover are:
      1. REV-high (3′ at lower_bp+1) → FWD-right (5′ at lower_bp+1)
      2. FWD-left  (3′ at lower_bp)  → REV-low   (5′ at lower_bp)

    where *lower_bp* is the smaller bp of the crossover pair (lower_bp, lower_bp+1).
    """
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
    from collections import defaultdict

    helix_map = {h.id: h for h in design.helices}
    cell_to_helix = {(h.grid_pos[0], h.grid_pos[1]): h
                     for h in design.helices if h.grid_pos is not None}

    # Staple end positions for margin check
    staple_ends: dict[str, set[int]] = defaultdict(set)
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        staple_ends[first.helix_id].add(first.start_bp)
        staple_ends[last.helix_id].add(last.end_bp)

    upper_set = _scaffold_upper_set(design.lattice_type)
    period = (HC_CROSSOVER_PERIOD if design.lattice_type == LatticeType.HONEYCOMB
              else SQ_CROSSOVER_PERIOD)

    result = design

    for aid, bid in mid_pairs:
        ha = helix_map.get(aid)
        hb = helix_map.get(bid)
        if ha is None or hb is None or ha.grid_pos is None or hb.grid_pos is None:
            continue

        bp_center = ha.bp_start + ha.length_bp // 2
        all_ends = staple_ends.get(aid, set()) | staple_ends.get(bid, set())

        # Scan outward from center for a valid scaffold crossover from ha→hb.
        chosen_bp: int | None = None
        for offset in sorted(range(-scan_bp, scan_bp + 1), key=abs):
            bp = bp_center + offset
            if bp < ha.bp_start or bp >= ha.bp_start + ha.length_bp:
                continue
            nb = crossover_neighbor(result.lattice_type, *ha.grid_pos, bp, is_scaffold=True)
            if nb is None or nb != tuple(hb.grid_pos):
                continue
            if any(abs(bp - e) < min_staple_margin for e in all_ends):
                continue
            chosen_bp = bp
            break

        if chosen_bp is None:
            continue  # no valid middle crossover for this pair — skip

        dir_a = _get_scaffold_direction(result, aid)
        fwd_id = aid if dir_a == Direction.FORWARD else bid
        rev_id = bid if dir_a == Direction.FORWARD else aid

        # Determine lower_bp of the crossover pair (lower_bp, lower_bp+1).
        bp_mod = ((chosen_bp % period) + period) % period
        is_upper = bp_mod in upper_set
        lower_bp = chosen_bp - 1 if is_upper else chosen_bp

        # Nick FWD at lower_bp and REV at lower_bp+1.
        result = make_nick(result, fwd_id, lower_bp, Direction.FORWARD)
        result = make_nick(result, rev_id, lower_bp + 1, Direction.REVERSE)

        # Ligation 1: REV-high (3′ at lower_bp+1) + FWD-right (5′ at lower_bp+1)
        s3_rev = _find_strand_by_3prime(result, rev_id, lower_bp + 1, StrandType.SCAFFOLD)
        s5_fwd = _find_strand_by_5prime(result, fwd_id, lower_bp + 1, StrandType.SCAFFOLD)
        if s3_rev is not None and s5_fwd is not None and s3_rev.id != s5_fwd.id:
            result = _ligate(result, s3_rev, s5_fwd)

        # Ligation 2: FWD-left (3′ at lower_bp) + REV-low (5′ at lower_bp)
        # Re-fetch in case ligation 1 changed strand objects.
        s3_fwd = _find_strand_by_3prime(result, fwd_id, lower_bp, StrandType.SCAFFOLD)
        s5_rev = _find_strand_by_5prime(result, rev_id, lower_bp, StrandType.SCAFFOLD)
        if s3_fwd is not None and s5_rev is not None and s3_fwd.id != s5_rev.id:
            result = _ligate(result, s3_fwd, s5_rev)

    return result


def _set_scaffold_domain_right_end(
    design: Design,
    helix_id: str,
    X: int,
    direction: Direction,
) -> Design:
    """Extend the high-bp boundary of the scaffold domain on *helix_id* to *X*.

    X is expected to be to the RIGHT of (greater than) the current domain boundary,
    extending the scaffold into single-stranded territory beyond bp_start + length_bp.

    For FORWARD direction: sets end_bp   = X (3′ end extends further right).
    For REVERSE direction: sets start_bp = X (5′ end extends further right).
    Only modifies the first matching domain on the helix.
    """
    new_strands = []
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD:
            new_strands.append(s)
            continue
        new_domains = list(s.domains)
        modified = False
        for i, d in enumerate(new_domains):
            if d.helix_id != helix_id or d.direction != direction:
                continue
            if direction == Direction.FORWARD:
                new_domains[i] = d.model_copy(update={"end_bp": X})
            else:
                new_domains[i] = d.model_copy(update={"start_bp": X})
            modified = True
            break
        if modified:
            new_strands.append(s.model_copy(update={"domains": new_domains}))
        else:
            new_strands.append(s)
    return design.model_copy(update={"strands": new_strands})


def _scaffold_add_right_end_crossovers(
    design: Design,
    min_staple_margin: int = 3,
    scan_bp: int = 48,
    allowed_pairs: "set[tuple[str, str]] | None" = None,
) -> Design:
    """Connect adjacent scaffold strand pairs via crossovers on the high-bp side.

    Scans rightward past each helix's right edge (bp_start + length_bp) for
    valid scaffold crossover positions with lattice-adjacent helices.

    Two-phase approach:

    Phase A — cross-strand ligation: pairs whose two helices belong to DIFFERENT
    scaffold strands (before this step) are matched via degree-first greedy and
    ligated, merging strands into one long scaffold chain.

    Phase B — terminal extension: after all ligations, each scaffold strand's
    terminal helices (domains[0] REVERSE and domains[-1] FORWARD) are extended
    rightward to the nearest valid scaffold crossover position.  No ligation is
    performed — these become the scaffold's 5′ and 3′ termini (open ends) for
    sequence assignment.

    For circular designs, the last cross-strand pair that would close the loop is
    detected when its ligation is skipped (s3.id == s5.id) and the two terminal
    helices are handled by Phase B instead.

    Returns design unchanged if no right-side crossover positions are found.
    """
    from backend.core.crossover_positions import crossover_neighbor
    from collections import defaultdict

    cell_to_helix: dict[tuple[int, int], Helix] = {
        (h.grid_pos[0], h.grid_pos[1]): h
        for h in design.helices
        if h.grid_pos is not None
    }
    helix_map = {h.id: h for h in design.helices}

    staple_ends_by_helix: dict[str, set[int]] = defaultdict(set)
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or not s.domains:
            continue
        first, last = s.domains[0], s.domains[-1]
        staple_ends_by_helix[first.helix_id].add(first.start_bp)
        staple_ends_by_helix[last.helix_id].add(last.end_bp)

    # Record scaffold strand assignment BEFORE any modifications so we can
    # distinguish cross-strand pairs (need ligation) from same-strand pairs
    # (already connected via left-side; need extension only for the open terminus).
    helix_to_strand: dict[str, str] = {}
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in s.domains:
            helix_to_strand[dom.helix_id] = s.id

    # Scan rightward, separating cross-strand and same-strand pairs.
    cross_pair_to_x: dict[tuple[str, str], int] = {}

    for h in design.helices:
        if h.grid_pos is None:
            continue
        row, col  = h.grid_pos
        ends_h    = staple_ends_by_helix.get(h.id, set())
        bp_right  = h.bp_start + h.length_bp

        for bp in range(bp_right, bp_right + scan_bp):
            nb = crossover_neighbor(design.lattice_type, row, col, bp, is_scaffold=True)
            if nb is None or nb not in cell_to_helix:
                continue
            h_nb    = cell_to_helix[nb]
            ends_nb = staple_ends_by_helix.get(h_nb.id, set())
            all_ends = ends_h | ends_nb
            if any(abs(bp - e) < min_staple_margin for e in all_ends):
                continue
            key = (min(h.id, h_nb.id), max(h.id, h_nb.id))
            if allowed_pairs is not None and key not in allowed_pairs:
                continue
            # Only record pairs that are in DIFFERENT strands — these need ligation.
            # Same-strand pairs are handled by Phase B (terminal extension).
            if helix_to_strand.get(h.id) == helix_to_strand.get(h_nb.id):
                continue
            if key not in cross_pair_to_x or bp < cross_pair_to_x[key]:
                cross_pair_to_x[key] = bp

    # ── Phase A: degree-first greedy matching on cross-strand pairs ───────────
    result = design
    if cross_pair_to_x:
        adjacency: dict[str, list[tuple[int, str]]] = {}
        for (aid, bid), bp in cross_pair_to_x.items():
            adjacency.setdefault(aid, []).append((bp, bid))
            adjacency.setdefault(bid, []).append((bp, aid))
        for hid in adjacency:
            adjacency[hid].sort()   # ascending: nearest bp first

        unmatched: set[str] = set(adjacency.keys())
        selected:  list[tuple[str, str, int]] = []

        while True:
            candidates = {
                hid for hid in unmatched
                if any(n in unmatched for _, n in adjacency[hid])
            }
            if not candidates:
                break
            best = min(
                candidates,
                key=lambda hid: (len([n for _, n in adjacency[hid] if n in unmatched]), hid),
            )
            for bp, nbr in adjacency[best]:
                if nbr in unmatched:
                    unmatched.discard(best)
                    unmatched.discard(nbr)
                    selected.append((best, nbr, bp))
                    break

        for aid, bid, X in selected:
            dir_a = _get_scaffold_direction(result, aid)
            fwd_id, rev_id = (aid, bid) if dir_a == Direction.FORWARD else (bid, aid)

            result = _set_scaffold_domain_right_end(result, fwd_id, X, Direction.FORWARD)
            result = _set_scaffold_domain_right_end(result, rev_id, X, Direction.REVERSE)

            # Skip ligation if both helices ended up in the same strand
            # (can happen for the last pair in a circular design).
            s3 = _find_strand_by_3prime(result, fwd_id, X, StrandType.SCAFFOLD)
            s5 = _find_strand_by_5prime(result, rev_id, X, StrandType.SCAFFOLD)
            if s3 is not None and s5 is not None and s3.id != s5.id:
                result = _ligate(result, s3, s5)

    # ── Phase B: extend terminal helices of each scaffold strand ──────────────
    # After Phase A ligations the scaffold may consist of fewer, longer strands.
    # Extend each strand's right-side terminal helices (domains[0] REVERSE and
    # domains[-1] FORWARD) to the nearest valid scaffold crossover position,
    # creating single-stranded loops at the open ends.  Do NOT ligate.
    # Only extend if the target bp is beyond the current domain boundary
    # (avoids shrinking a boundary already moved further right by Phase A).
    for s in list(result.strands):
        if s.strand_type != StrandType.SCAFFOLD or not s.domains:
            continue

        for dom, direction in (
            (s.domains[0],  Direction.REVERSE),   # 5′ terminal (right-facing for REV)
            (s.domains[-1], Direction.FORWARD),   # 3′ terminal (right-facing for FWD)
        ):
            if dom.direction != direction:
                continue   # skip if the terminal domain has the other orientation
            h = helix_map.get(dom.helix_id)
            if h is None or h.grid_pos is None:
                continue
            row, col = h.grid_pos
            bp_right = h.bp_start + h.length_bp
            current_right = dom.start_bp if direction == Direction.REVERSE else dom.end_bp

            for bp in range(bp_right, bp_right + scan_bp):
                nb = crossover_neighbor(result.lattice_type, row, col, bp, is_scaffold=True)
                if nb is None or nb not in cell_to_helix:
                    continue
                all_ends = (staple_ends_by_helix.get(dom.helix_id, set()) |
                            staple_ends_by_helix.get(cell_to_helix[nb].id, set()))
                if any(abs(bp - e) < min_staple_margin for e in all_ends):
                    continue
                if bp > current_right:
                    result = _set_scaffold_domain_right_end(
                        result, dom.helix_id, bp, direction
                    )
                break   # take the nearest valid position (even if no extension needed)

    return result


def _set_scaffold_domain_left_end(
    design: Design,
    helix_id: str,
    X: int,
    direction: Direction,
) -> Design:
    """Extend the low-bp boundary of the scaffold domain on *helix_id* to *X*.

    X is expected to be to the LEFT of (less than) the current domain boundary,
    extending the scaffold into single-stranded territory beyond bp_start.

    For FORWARD direction: sets start_bp = X (5′ end extends further left).
    For REVERSE direction: sets end_bp   = X (3′ end extends further left).
    Only modifies the first matching domain on the helix.
    """
    new_strands = []
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD:
            new_strands.append(s)
            continue
        new_domains = list(s.domains)
        modified = False
        for i, d in enumerate(new_domains):
            if d.helix_id != helix_id or d.direction != direction:
                continue
            if direction == Direction.FORWARD:
                new_domains[i] = d.model_copy(update={"start_bp": X})
            else:
                new_domains[i] = d.model_copy(update={"end_bp": X})
            modified = True
            break
        if modified:
            new_strands.append(s.model_copy(update={"domains": new_domains}))
        else:
            new_strands.append(s)
    return design.model_copy(update={"strands": new_strands})


def auto_scaffold_partition(
    design: Design,
    helix_groups: list[list[str]],
    mode: str = "end_to_end",
    nick_offset: int = 7,
    min_end_margin: int = 9,
) -> Design:
    """Route independent scaffold strands for each group of helices.

    Each group is auto-scaffolded independently and the resulting scaffold
    strands replace any existing scaffold strands that covered those helices.
    Helices not in any group are left untouched.

    Parameters
    ----------
    design:
        Active design.
    helix_groups:
        List of lists of helix IDs.  Groups must be disjoint.
    mode:
        Routing mode passed to ``auto_scaffold`` for each group
        (default ``"end_to_end"``).
    nick_offset, min_end_margin:
        Passed to ``auto_scaffold`` for each group.

    Returns
    -------
    Updated Design with one scaffold strand per group (plus any existing
    scaffold strands for uncovered helices).

    Raises
    ------
    ValueError
        If any helix ID is unrecognised, or groups overlap.
    """
    all_ids = {h.id for h in design.helices}
    seen: set[str] = set()
    for grp in helix_groups:
        for hid in grp:
            if hid not in all_ids:
                raise ValueError(f"Helix {hid!r} not found in the design.")
            if hid in seen:
                raise ValueError(
                    f"Helix {hid!r} appears in more than one group. "
                    "Groups must be disjoint."
                )
            seen.add(hid)

    # Remove ALL existing scaffold strands — the caller is replacing them.
    from backend.core.models import StrandType
    base_strands = [s for s in design.strands if s.strand_type != StrandType.SCAFFOLD]
    new_scaffold_strands = []

    for grp in helix_groups:
        grp_set = set(grp)
        sub_helices = [h for h in design.helices if h.id in grp_set]
        if not sub_helices:
            continue
        # Build a minimal sub-design for this group.
        # Keep only strands (staples) that are fully within the group's helices.
        sub_strands = [
            s for s in design.strands
            if s.strand_type != StrandType.SCAFFOLD
            and all(d.helix_id in grp_set for d in s.domains)
        ]
        sub_design = design.model_copy(update={
            "helices": sub_helices,
            "strands": sub_strands,
        })
        try:
            routed_sub = auto_scaffold(
                sub_design,
                mode=mode,
                nick_offset=nick_offset,
                min_end_margin=min_end_margin,
                scaffold_loops=True,
            )
        except ValueError as exc:
            raise ValueError(
                f"Scaffold routing failed for group {grp!r}: {exc}"
            ) from exc

        new_scaffold_strands.extend(
            s for s in routed_sub.strands
            if s.strand_type == StrandType.SCAFFOLD
        )

    # Renumber scaffold IDs globally to avoid collisions across groups.
    renumbered = [
        s.model_copy(update={"id": f"scaffold_{i}"})
        for i, s in enumerate(new_scaffold_strands)
    ]
    from backend.core.crossover_positions import extract_crossovers_from_strands
    new_all_strands = base_strands + renumbered
    return design.model_copy(update={
        "strands":    new_all_strands,
        "crossovers": extract_crossovers_from_strands(new_all_strands),
    })


def auto_scaffold_jointed(
    design: Design,
    mode: str = "end_to_end",
    nick_offset: int = 7,
    min_end_margin: int = 9,
) -> Design:
    """Route scaffold through each arm while preserving manually-placed cross-arm strands.

    Designed for jointed / hinge designs where the user has manually placed scaffold
    strands that connect two or more arms (e.g., hinge joints).  These "fixed" strands
    bridge helices that are separated by a gap in the XY plane and therefore cannot be
    auto-routed by the standard Hamiltonian-path algorithm.

    Algorithm
    ---------
    1. Build XY adjacency graph → find connected components (one per arm).
    2. Identify "fixed" scaffold strands: those whose domains span helices in more than
       one connected component.
    3. Collect "bridge" helix IDs — every helix touched by a fixed strand.
    4. For each component, route the "free" helices (component helices minus bridge
       helices) using ``auto_scaffold``.  Bridge helices are left alone so no scaffold
       domain overlap occurs.
    5. Fixed strands are preserved unchanged.
    6. Ligation pass: for each arm scaffold endpoint, check whether any fixed strand has
       a co-positioned endpoint (same bp value) on an XY-adjacent helix.  If so the
       fixed strand's domains are merged into the arm scaffold (arm scaffold absorbs the
       fixed strand, preserving the arm scaffold's ID).  Only the 3′ end of the arm
       scaffold can absorb the 5′ end of a fixed strand in this pass (the reverse
       direction is left to the user or a future step, as it would flip strand ownership).

    Parameters
    ----------
    design:
        Active design containing at least two disconnected helix groups connected by
        manually placed cross-arm scaffold strands.
    mode:
        Routing mode for the free-helix portions: ``"end_to_end"`` (default) or
        ``"seam_line"``.
    nick_offset:
        Offset in bp from the helix terminus for the scaffold 5′/3′ nick (passed to
        ``auto_scaffold``).
    min_end_margin:
        Minimum bp margin for the Hamiltonian path (default 9).

    Returns
    -------
    Updated Design with per-arm scaffold strands routing the free helices, fixed
    cross-arm strands preserved (or ligated into arm scaffolds where endpoints
    co-locate on XY-adjacent helices).

    Raises
    ------
    ValueError
        If scaffold routing fails for any arm.
    """
    from collections import deque

    if not design.helices:
        return design

    skip_ids = _overhang_only_helix_ids(design)
    routable_helices = [h for h in design.helices if h.id not in skip_ids]
    if not routable_helices:
        return design

    # ── Step 1: connected components via XY adjacency ────────────────────────
    adjacency = _helix_adjacency_graph(design, min_end_margin)
    all_hids = [h.id for h in routable_helices]

    seen: set[str] = set()
    components: list[set[str]] = []
    for start in all_hids:
        if start in seen:
            continue
        comp: set[str] = set()
        queue: deque[str] = deque([start])
        while queue:
            node = queue.popleft()
            if node in comp:
                continue
            comp.add(node)
            seen.add(node)
            for nb in adjacency.get(node, []):
                if nb not in comp:
                    queue.append(nb)
        components.append(comp)

    if len(components) <= 1:
        # Single connected design — delegate to standard routing
        return auto_scaffold(
            design, mode=mode, nick_offset=nick_offset,
            min_end_margin=min_end_margin, scaffold_loops=True,
        )

    # ── Step 2: identify fixed scaffold strands ───────────────────────────────
    comp_for_hid: dict[str, int] = {
        hid: ci for ci, comp in enumerate(components) for hid in comp
    }
    fixed_strand_ids: set[str] = set()
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD or not s.domains:
            continue
        comps_used = {comp_for_hid[d.helix_id] for d in s.domains if d.helix_id in comp_for_hid}
        if len(comps_used) > 1:
            fixed_strand_ids.add(s.id)

    if not fixed_strand_ids:
        # No cross-arm fixed strands — partition by component
        helix_groups = [sorted(c) for c in components]
        return auto_scaffold_partition(
            design, helix_groups=helix_groups, mode=mode,
            nick_offset=nick_offset, min_end_margin=min_end_margin,
        )

    # ── Step 3: bridge helix IDs ──────────────────────────────────────────────
    bridge_hids: set[str] = {
        d.helix_id
        for s in design.strands if s.id in fixed_strand_ids
        for d in s.domains
    }

    # ── Step 3.5: fixed strand endpoint lookups (for junction detection) ──────
    # Map (helix_id, bp) → fixed_strand_id for both 5′ and 3′ endpoints.
    # Used below to identify which free helices border a fixed strand endpoint.
    fixed_by_5prime_global: dict[tuple[str, int], str] = {}
    fixed_by_3prime_global: dict[tuple[str, int], str] = {}
    for s in design.strands:
        if s.id in fixed_strand_ids and s.domains:
            fixed_by_5prime_global[(s.domains[0].helix_id, s.domains[0].start_bp)] = s.id
            fixed_by_3prime_global[(s.domains[-1].helix_id, s.domains[-1].end_bp)] = s.id

    # ── Step 4: route free helices per arm ────────────────────────────────────
    non_fixed_scaffold_ids: set[str] = {
        s.id for s in design.strands
        if s.strand_type == StrandType.SCAFFOLD and s.id not in fixed_strand_ids
    }
    base_strands = [s for s in design.strands if s.id not in non_fixed_scaffold_ids]
    old_scaf_ids = sorted(non_fixed_scaffold_ids)

    _id_counter: list[int] = [0]

    def _new_scaf_id() -> str:
        j = _id_counter[0]
        _id_counter[0] += 1
        return old_scaf_ids[j] if j < len(old_scaf_ids) else f"scaffold_jointed_{j}"

    new_arm_strands: list[Strand] = []

    # Sort components by average Y position of their free helices.
    # Lower-Y components (rows 0–1) are the "upstream" start of the scaffold
    # chain and should use a FWD junction helix (3′ at max_bp, needs reversal).
    # Higher-Y components (rows 6–7) are the "downstream" end and should use a
    # REV junction helix (5′ at max_bp, no reversal).
    _hby_id_all = {h.id: h for h in design.helices}

    def _comp_avg_y(comp: set[str]) -> float:
        fh = [_hby_id_all[hid] for hid in comp if hid in _hby_id_all and hid not in bridge_hids]
        return sum(h.axis_start.y for h in fh) / len(fh) if fh else 0.0

    sorted_comps = sorted(
        [(ci, comp) for ci, comp in enumerate(components) if comp - bridge_hids],
        key=lambda x: _comp_avg_y(x[1]),
    )
    n_sorted = len(sorted_comps)

    for loop_idx, (ci, comp) in enumerate(sorted_comps):
        free_hids = comp - bridge_hids
        # first component = upstream/start of chain → use FWD junction (3′ ligation)
        # last component  = downstream/end of chain → use REV junction (5′ ligation)
        # intermediates default to REV to receive the chain from the previous arm
        prefer_fwd = (loop_idx == 0)
        prefer_rev = (loop_idx == n_sorted - 1) and not prefer_fwd

        free_helices = [h for h in design.helices if h.id in free_hids]
        free_hid_set = set(free_hids)
        # Include existing scaffold strands on free helices so _get_scaffold_direction
        # reads their directions instead of falling back to the lattice formula.
        # The lattice formula gives wrong results for non-standard honeycomb positions
        # (cell value = 2/"hole") that are valid in this design.  Fixed strands are
        # automatically excluded here because their domains include bridge helices
        # which are not in free_hid_set.
        sub_strands = [
            s for s in design.strands
            if all(d.helix_id in free_hid_set for d in s.domains)
        ]
        # ── Junction helix detection ──────────────────────────────────────────
        # A "junction helix" is a free helix adjacent (in the full design) to a
        # bridge helix that has a fixed strand endpoint at this arm's max_bp.
        # Putting the junction helix first in the Hamiltonian path ensures the
        # arm scaffold starts (or ends, after reversal) at the ligation point.
        #
        # junction_fwd_hid: FWD free helix → path starts here → domain list is
        #   reversed after routing → scaffold 3′ ends at max_bp on this helix.
        # junction_rev_hid: REV free helix → path starts here → scaffold 5′
        #   starts at max_bp on this helix (no reversal needed).
        junction_fwd_hid: str | None = None
        junction_rev_hid: str | None = None

        _dir_probe = design.model_copy(update={
            "helices": free_helices,
            "strands": sub_strands,
        })
        _hby_id_local = {h.id: h for h in free_helices}

        for fhid in sorted(free_hids):  # sorted for deterministic junction selection
            fh = _hby_id_local[fhid]
            fh_max_bp = fh.bp_start + fh.length_bp - 1
            fh_dir = _get_scaffold_direction(_dir_probe, fhid)
            for nb_hid in adjacency.get(fhid, []):
                if nb_hid not in bridge_hids:
                    continue
                if fh_dir == Direction.FORWARD and junction_fwd_hid is None:
                    if (nb_hid, fh_max_bp) in fixed_by_5prime_global:
                        junction_fwd_hid = fhid
                if fh_dir == Direction.REVERSE and junction_rev_hid is None:
                    if (nb_hid, fh_max_bp) in fixed_by_3prime_global:
                        junction_rev_hid = fhid

        # Choose which junction type to use based on this arm's chain position.
        # prefer_fwd (upstream/start): use FWD junction so 3′ connects to fixed 5′.
        # prefer_rev (downstream/end): use REV junction so 5′ connects to fixed 3′.
        if prefer_fwd:
            junction_first_hid = junction_fwd_hid or junction_rev_hid
        elif prefer_rev:
            junction_first_hid = junction_rev_hid or junction_fwd_hid
        else:
            # Intermediate arm: prefer REV (receives chain from previous arm).
            junction_first_hid = junction_rev_hid or junction_fwd_hid
        needs_reversal = (
            junction_first_hid is not None and junction_first_hid == junction_fwd_hid
        )

        if junction_first_hid is not None:
            free_helices = (
                [h for h in free_helices if h.id == junction_first_hid]
                + [h for h in free_helices if h.id != junction_first_hid]
            )

        sub_design = design.model_copy(update={
            "helices": free_helices,
            "strands": sub_strands,
        })
        try:
            routed = auto_scaffold(
                sub_design, mode=mode, nick_offset=nick_offset,
                min_end_margin=min_end_margin, scaffold_loops=True,
            )
        except ValueError as exc:
            raise ValueError(
                f"Scaffold routing failed for arm {ci} "
                f"({len(free_hids)} free helices): {exc}"
            ) from exc

        for s in routed.strands:
            if s.strand_type == StrandType.SCAFFOLD:
                if needs_reversal:
                    # Reverse the domain list so the junction helix (FWD, last in
                    # original path) becomes the 3′ end with end_bp = max_bp.
                    # Safe because scaffold_loops=True makes domain bp values
                    # path-position-independent, and adjacency is symmetric.
                    s = s.model_copy(update={"domains": list(reversed(s.domains))})
                new_arm_strands.append(s)

    renumbered_arm = [
        s.model_copy(update={"id": _new_scaf_id()})
        for s in new_arm_strands
    ]

    working = design.model_copy(update={"strands": base_strands + renumbered_arm})

    # ── Step 5: ligation pass ─────────────────────────────────────────────────
    # Connect arm scaffold 3′ ends to fixed strand 5′ ends where they co-locate
    # on XY-adjacent helices (same bp value at the junction).
    working = _ligate_arm_to_fixed(working, fixed_strand_ids, adjacency)

    from backend.core.crossover_positions import extract_crossovers_from_strands
    return working.model_copy(update={
        "crossovers": extract_crossovers_from_strands(working.strands),
    })


def _ligate_arm_to_fixed(
    design: Design,
    fixed_strand_ids: set[str],
    adjacency: dict[str, list[str]],
) -> Design:
    """Ligate arm scaffold 3′ endpoints to adjacent fixed or arm strand 5′ endpoints.

    An arm scaffold strand absorbs a neighbour when its 3′ end (last domain's
    end_bp on helix A) matches the neighbour's 5′ start_bp on helix B, and B is
    XY-adjacent to A (present in adjacency[A]).

    Two neighbour types are checked in priority order:
    1. **Fixed strand** (ARM_3prime → FIXED_5prime): the arm absorbs the fixed
       strand; arm strand ID survives, fixed strand is removed.
    2. **Another arm strand** (ARM_3prime → ARM_5prime): used after a fixed
       strand has been absorbed and the merged arm's 3′ now sits on a bridge
       helix adjacent to the other arm's 5′.  This joins the two arms into one
       continuous scaffold strand.

    Multiple ligations are attempted in sequence until no more matches are found.
    """
    changed = True
    while changed:
        changed = False
        arm_strands = [
            s for s in design.strands
            if s.strand_type == StrandType.SCAFFOLD
            and s.id not in fixed_strand_ids
            and s.domains
        ]
        remaining_fixed = [
            s for s in design.strands
            if s.id in fixed_strand_ids and s.domains
        ]
        # (helix_id, start_bp) → fixed strand
        fixed_by_5prime: dict[tuple[str, int], Strand] = {}  # type: ignore[name-defined]
        for fs in remaining_fixed:
            key = (fs.domains[0].helix_id, fs.domains[0].start_bp)
            fixed_by_5prime[key] = fs

        # (helix_id, start_bp) → arm strand (for cross-arm chain ligation)
        arm_by_5prime: dict[tuple[str, int], Strand] = {}  # type: ignore[name-defined]
        for arm in arm_strands:
            arm_by_5prime[(arm.domains[0].helix_id, arm.domains[0].start_bp)] = arm

        for arm in arm_strands:
            last = arm.domains[-1]
            arm_3prime_hid = last.helix_id
            arm_3prime_bp  = last.end_bp
            neighbours = adjacency.get(arm_3prime_hid, [])
            # Two-pass: check ALL neighbours for ARM-to-ARM first.
            # This ensures that once a fixed strand is absorbed and the arm's 3′
            # lands on a bridge helix, we immediately join the other arm strand
            # rather than chaining into additional same-row bridge fixed strands.
            for nb_hid in neighbours:
                key = (nb_hid, arm_3prime_bp)
                if key in arm_by_5prime and arm_by_5prime[key].id != arm.id:
                    design = _ligate(design, arm, arm_by_5prime[key])
                    changed = True
                    break
            if changed:
                break
            # Second pass: absorb a fixed strand.
            for nb_hid in neighbours:
                key = (nb_hid, arm_3prime_bp)
                if key in fixed_by_5prime:
                    design = _ligate(design, arm, fixed_by_5prime[key])
                    changed = True
                    break
            if changed:
                break

    return design


def _build_seam_line_domains(
    path: list[str],
    helices_by_id: dict,
    scaf_dirs: dict,
    nick_offset: int,
    min_end_margin: int,
    scaffold_loops: bool = True,
    seam_bp: int | None = None,
    loop_size: int = 7,
) -> list[Domain]:
    """Build scaffold domain list for seam-line mode (mid-helix DX crossovers).

    Crossover topology alternates between LOOP crossovers and SEAM crossovers:

    - Even-indexed pairs (0, 2, 4, …): *loop* crossovers placed near the far
      end of the helix (L − 1 − loop_size for FORWARD, loop_size for REVERSE).
      These create U-turns at the bundle terminus.
    - Odd-indexed pairs (1, 3, 5, …): *seam* crossovers placed near *seam_bp*
      (or most-central if *seam_bp* is None).

    Crossover positions respect direction order on each shared helix:
    FORWARD helices require exit_bp > entry_bp; REVERSE require exit_bp < entry_bp.

    When *scaffold_loops* is True the 5′ domain on helix 1 starts at the physical
    terminus (bp 0 or N−1) rather than at *nick_offset*.
    """
    # Collect all valid candidates per pair (not just best one yet)
    all_candidates: list[list[tuple[int, int]]] = []
    for i in range(len(path) - 1):
        hid_a, hid_b = path[i], path[i + 1]
        h_a = helices_by_id[hid_a]
        h_b = helices_by_id[hid_b]
        all_candidates.append([])

    def _pick(candidates: list[tuple[int, int]], target_bp: int | None, h_a: "Helix", h_b: "Helix") -> tuple[int, int]:
        """Pick best candidate: nearest to target_bp (global), or most-central if target is None.

        Candidates contain global bp values; margins are computed in local space.
        """
        if target_bp is not None:
            return min(candidates, key=lambda c: abs(c[0] - target_bp))
        # Most-central: maximise min distance to each helix's terminal in local space.
        return max(candidates, key=lambda c: min(
            c[0] - h_a.bp_start,
            h_a.bp_start + h_a.length_bp - 1 - c[0],
            c[1] - h_b.bp_start,
            h_b.bp_start + h_b.length_bp - 1 - c[1],
        ))

    # Sequentially commit crossover positions, respecting direction order on shared helices.
    # xover_bps[i] = (bp_a on path[i], bp_b on path[i+1]) — values are GLOBAL bp.
    xover_bps: list[tuple[int, int]] = []
    for i, cands in enumerate(all_candidates):
        h_a  = helices_by_id[path[i]]
        h_b  = helices_by_id[path[i + 1]]
        L_a  = h_a.length_bp
        dir_a = scaf_dirs[path[i]]

        # Determine target for this pair: loop (even) vs seam (odd).
        # Target is a global bp value.
        is_loop_pair = (i % 2 == 0)
        if is_loop_pair:
            # Loop crossover near the far end: local (L_a - 1 - loop_size) or loop_size,
            # converted to global by adding h_a.bp_start.
            if dir_a == Direction.FORWARD:
                target = h_a.bp_start + (L_a - 1 - loop_size)
            else:
                target = h_a.bp_start + loop_size
        else:
            target = seam_bp  # None → most-central heuristic (global or None)

        if i == 0:
            best = _pick(cands, target, h_a, h_b)
        else:
            entry_bp = xover_bps[i - 1][1]  # global bp
            if dir_a == Direction.FORWARD:
                filtered = [(a, b) for a, b in cands if a > entry_bp]
            else:
                filtered = [(a, b) for a, b in cands if a < entry_bp]

            if not filtered:
                raise ValueError(
                    f"No valid scaffold crossover on {path[i]} consistent with "
                    f"entry at bp={entry_bp} (direction {dir_a.value}). "
                    f"Available candidates: {cands}"
                )
            best = _pick(filtered, target, h_a, h_b)

        xover_bps.append(best)

    # Build domain list — start_bp = 5′ end, end_bp = 3′ end (model convention).
    # All bp values are GLOBAL (xover_bps are global; terminals computed from bp_start).
    merged_domains: list[Domain] = []
    for i, hid in enumerate(path):
        dir_i = scaf_dirs[hid]
        h     = helices_by_id[hid]
        L     = h.length_bp

        if i == 0:
            # 5′ end: physical terminus when scaffold_loops=True; else nick_offset offset.
            # Global terminal: bp_start (FORWARD near-end) or bp_start+L-1 (REVERSE near-end).
            if scaffold_loops:
                five_prime = h.bp_start if dir_i == Direction.FORWARD else h.bp_start + L - 1
            else:
                five_prime = (h.bp_start + nick_offset
                              if dir_i == Direction.FORWARD
                              else h.bp_start + L - 1 - nick_offset)
            three_prime = xover_bps[0][0]  # global
        elif i == len(path) - 1:
            five_prime  = xover_bps[i - 1][1]  # global
            three_prime = h.bp_start + L - 1 if dir_i == Direction.FORWARD else h.bp_start
        else:
            five_prime  = xover_bps[i - 1][1]  # global
            three_prime = xover_bps[i][0]       # global

        merged_domains.append(Domain(
            helix_id=hid,
            start_bp=five_prime,
            end_bp=three_prime,
            direction=dir_i,
        ))

    return merged_domains


def _build_end_to_end_domains(
    path: list[str],
    helices_by_id: dict,
    scaf_dirs: dict,
    nick_offset: int,
    scaffold_loops: bool = True,
) -> list[Domain]:
    """Build scaffold domain list for end-to-end mode (full helix spans, no mid-helix crossovers).

    The scaffold traverses each helix in full.  When *scaffold_loops* is True
    (default) the 5′ end starts at the physical terminus (bp 0 or N−1) so that
    the terminal base pairs are single-stranded scaffold.  When False the 5′ end
    is placed *nick_offset* bp away from the terminal.
    """
    merged_domains: list[Domain] = []
    for i, hid in enumerate(path):
        dir_i = scaf_dirs[hid]
        h     = helices_by_id[hid]
        L     = h.length_bp

        if i == 0:
            if scaffold_loops:
                five_prime = h.bp_start if dir_i == Direction.FORWARD else h.bp_start + L - 1
            else:
                # nick_offset bp in from the terminal defines the 5′ start (global bp)
                five_prime = (h.bp_start + nick_offset
                              if dir_i == Direction.FORWARD
                              else h.bp_start + L - 1 - nick_offset)
            three_prime = h.bp_start + L - 1 if dir_i == Direction.FORWARD else h.bp_start
        else:
            # Full span of every other helix (global bp)
            five_prime  = h.bp_start if dir_i == Direction.FORWARD else h.bp_start + L - 1
            three_prime = h.bp_start + L - 1 if dir_i == Direction.FORWARD else h.bp_start

        merged_domains.append(Domain(
            helix_id=hid,
            start_bp=five_prime,
            end_bp=three_prime,
            direction=dir_i,
        ))

    return merged_domains


_SEAM_SEARCH_OFFSETS = tuple(range(-21, 22))  # full HC period coverage


def _build_seam_only_scaffold_strands(
    path: list[str],
    helices_by_id: dict,
    scaf_dirs: dict,
    seam_bp: int | None = None,
    plane: str = "XY",
    midpoints_by_hid: "dict[str, int] | None" = None,
) -> list[list[Domain]]:
    """Build scaffold domain lists for seam-only DX routing.

    ``path[0]`` and ``path[-1]`` are *outer-rail* helices that run the full
    helix length as single domains (no seam crossovers).  The remaining inner
    helices are organised into consecutive pairs — (path[1],path[2]),
    (path[3],path[4]), … — each receiving a DX seam motif placed near
    *seam_bp*.

    For square lattice the exact crossover position (lo, lo+1) is taken from
    the 32-bp lookup table — consecutive crossover bp pairs closest to seam_bp.
    For honeycomb the position is chosen from offsets {-14, -7, 0, +7, +14} bp
    relative to *seam_bp* by minimising the sum of backbone-to-backbone
    distances at the two crossover junctions (bp=lo and bp=lo+1).

    - Outer-rail strand : single domain covering bp [0 .. L-1].
    - Low-U strand      : covers bp [0 .. lo] on both inner helices.
    - High-U strand     : covers bp [lo+1 .. L-1] on both inner helices.

    After ``scaffold_add_end_crossovers`` ligates all between-pair junctions
    the result is one continuous scaffold strand.

    Returns a list of domain lists — one per outer rail plus two per inner pair.
    Requires len(path) >= 4 (minimum useful: 6 helices).
    """
    from backend.core.constants import SQUARE_TWIST_PER_BP_RAD
    from backend.core.geometry import nucleotide_positions

    domain_lists: list[list[Domain]] = []

    # ── Outer-rail helices: full-length single domains (global bp) ───────────
    for hid in (path[0], path[-1]):
        d = scaf_dirs[hid]
        h = helices_by_id[hid]
        L = h.length_bp
        start = h.bp_start if d == Direction.FORWARD else h.bp_start + L - 1
        end   = h.bp_start + L - 1 if d == Direction.FORWARD else h.bp_start
        domain_lists.append([Domain(helix_id=hid, start_bp=start, end_bp=end, direction=d)])

    # ── Inner pairs: seam DX crossovers ──────────────────────────────────────
    for i in range(1, len(path) - 2, 2):
        hid_a = path[i]
        hid_b = path[i + 1]
        dir_a = scaf_dirs[hid_a]
        dir_b = scaf_dirs[hid_b]
        L_a = helices_by_id[hid_a].length_bp
        L_b = helices_by_id[hid_b].length_bp

        h_a = helices_by_id[hid_a]
        h_b = helices_by_id[hid_b]
        sq = abs(h_a.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9

        # ── Global-plane seam position ────────────────────────────────────────
        # dbp: signed bp offset of h_b relative to h_a along the helix axis.
        # This is a LOCAL index delta (not global), derived from physical Z difference.
        # For a given candidate lo_a (local on h_a), the co-planar local position on h_b is
        #   lo_b = lo_a − dbp.
        lo_z_a = _helix_axis_lo(h_a, plane)
        lo_z_b = _helix_axis_lo(h_b, plane)
        dbp    = round((lo_z_b - lo_z_a) / BDNA_RISE_PER_BP)  # local index delta

        # Restrict local lo_a so that lo_b = lo_a − dbp stays within [0, L_b − 2].
        min_lo_a = max(0,       dbp)
        max_lo_a = min(L_a - 2, L_b - 2 + dbp)

        if midpoints_by_hid is not None and hid_a in midpoints_by_hid:
            base_lo = midpoints_by_hid[hid_a] - h_a.bp_start
        elif seam_bp is not None:
            base_lo = seam_bp - h_a.bp_start
        else:
            base_lo = L_a // 2
        base_lo_a = max(min_lo_a, min(base_lo, max_lo_a))

        # Backbone positions for the scaffold direction on each helix.
        # After geometry.py change, n.bp_index is GLOBAL; index by global bp.
        pos_a = {
            n.bp_index: n.position
            for n in nucleotide_positions(h_a)
            if n.direction == dir_a
        }
        pos_b = {
            n.bp_index: n.position
            for n in nucleotide_positions(h_b)
            if n.direction == dir_b
        }

        if sq:
            # Square lattice: search every 8 bp within 32 bp of the seam plane.
            lo_start = max(min_lo_a, base_lo_a - 32)
            lo_end   = min(max_lo_a, base_lo_a + 32)
            lo_a_candidates = list(range(lo_start, lo_end + 1, 8))
        else:
            # Honeycomb: search fixed offsets around the global seam position.
            lo_a_candidates = [
                max(min_lo_a, min(base_lo_a + delta, max_lo_a))
                for delta in _SEAM_SEARCH_OFFSETS
            ]

        best_lo_a: int | None = None
        best_dist = float("inf")

        for lo_a in lo_a_candidates:
            lo_b = lo_a - dbp   # co-planar local bp on h_b
            hi_a = lo_a + 1
            hi_b = lo_b + 1
            if lo_b < 0 or lo_b > L_b - 2:
                continue
            # Convert local to global for pos_a/pos_b lookup (keyed by global bp)
            g_lo_a = h_a.bp_start + lo_a
            g_lo_b = h_b.bp_start + lo_b
            g_hi_a = h_a.bp_start + hi_a
            g_hi_b = h_b.bp_start + hi_b
            pa_lo = pos_a.get(g_lo_a)
            pb_lo = pos_b.get(g_lo_b)
            pa_hi = pos_a.get(g_hi_a)
            pb_hi = pos_b.get(g_hi_b)
            if pa_lo is None or pb_lo is None or pa_hi is None or pb_hi is None:
                continue
            dist = (
                float(np.linalg.norm(pa_lo - pb_lo))
                + float(np.linalg.norm(pa_hi - pb_hi))
            )
            if dist < best_dist:
                best_dist = dist
                best_lo_a = lo_a

        if best_lo_a is None:
            best_lo_a = base_lo_a

        lo_a = best_lo_a
        lo_b = lo_a - dbp
        hi_a = lo_a + 1
        hi_b = lo_b + 1

        # Convert local crossover positions to global bp for domain construction.
        g_lo_a = h_a.bp_start + lo_a
        g_lo_b = h_b.bp_start + lo_b
        g_hi_a = h_a.bp_start + hi_a
        g_hi_b = h_b.bp_start + hi_b

        if dir_a == Direction.FORWARD:
            # A = FORWARD (5′→3′ = bp_start_a → bp_start_a+L-1),
            # B = REVERSE (5′→3′ = bp_start_b+L-1 → bp_start_b)
            low_u = [
                Domain(helix_id=hid_a, start_bp=h_a.bp_start, end_bp=g_lo_a, direction=dir_a),
                Domain(helix_id=hid_b, start_bp=g_lo_b,       end_bp=h_b.bp_start, direction=dir_b),
            ]
            high_u = [
                Domain(helix_id=hid_b, start_bp=h_b.bp_start + L_b - 1, end_bp=g_hi_b, direction=dir_b),
                Domain(helix_id=hid_a, start_bp=g_hi_a, end_bp=h_a.bp_start + L_a - 1, direction=dir_a),
            ]
        else:
            # A = REVERSE (5′→3′ = bp_start_a+L-1 → bp_start_a),
            # B = FORWARD (5′→3′ = bp_start_b → bp_start_b+L-1)
            low_u = [
                Domain(helix_id=hid_b, start_bp=h_b.bp_start, end_bp=g_lo_b, direction=dir_b),
                Domain(helix_id=hid_a, start_bp=g_lo_a,       end_bp=h_a.bp_start, direction=dir_a),
            ]
            high_u = [
                Domain(helix_id=hid_a, start_bp=h_a.bp_start + L_a - 1, end_bp=g_hi_a, direction=dir_a),
                Domain(helix_id=hid_b, start_bp=g_hi_b, end_bp=h_b.bp_start + L_b - 1, direction=dir_b),
            ]

        domain_lists.append(low_u)
        domain_lists.append(high_u)

    return domain_lists


# ── Scaffold end-loop operations ───────────────────────────────────────────────




def scaffold_nick(
    design: Design,
    nick_offset: int = 7,
) -> Design:
    """Nick the scaffold on the first helix (by sorted ID) at *nick_offset* bp from the near end.

    For FORWARD helices: nick after bp ``nick_offset - 1``, placing the scaffold 5′ at
    ``nick_offset`` (e.g., nick_offset=7 → 5′ at bp 7, 7 bp from the near terminus).

    For REVERSE helices: nick at bp ``nick_offset``, leaving a ``nick_offset``-bp
    single-stranded near loop (bp 0..nick_offset-1) at the blunt end.

    This operation is designed to be applied to the per-helix scaffold before seam
    routing.  After ``auto_scaffold`` replaces the scaffold strands, call this
    function again on the resulting design to reposition the 5′ terminus.
    """
    if not design.helices:
        return design
    target_helix = min(design.helices, key=lambda h: h.id)
    hid = target_helix.id
    direction = _get_scaffold_direction(design, hid)
    if direction is None:
        return design
    # nick_bp is a global bp index: offset from the helix's near-end terminal.
    # FORWARD: near-end = bp_start, nick after bp_start + nick_offset - 1
    # REVERSE: near-end = bp_start + L - 1, nick at bp_start + L - 1 - nick_offset
    h = target_helix
    if direction == Direction.FORWARD:
        nick_bp = h.bp_start + nick_offset - 1
    else:
        nick_bp = h.bp_start + h.length_bp - 1 - nick_offset
    try:
        return make_nick(design, hid, nick_bp, direction)
    except ValueError:
        return design


def _extend_interior_scaffold_endpoints(
    design: Design,
    length_bp: int,
    extend_far: bool,
) -> Design:
    """Extend interior scaffold strand endpoints into gap regions.

    Gap-continuation helices have scaffold strands that start or end mid-helix.
    This function extends those interior endpoints by *length_bp* bp.

    extend_far=True  — far-facing endpoints (toward high bp):
        FORWARD strand: interior 3′ end (last domain end_bp, high bp)
        REVERSE strand: interior 5′ end (first domain start_bp, high bp)
    extend_far=False — near-facing endpoints (toward low bp):
        FORWARD strand: interior 5′ end (first domain start_bp, low bp)
        REVERSE strand: interior 3′ end (last domain end_bp, low bp)
    """
    helix_by_id = {h.id: h for h in design.helices}
    strand_map: dict[str, Strand] = {}

    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD or not strand.domains:
            continue

        domains = list(strand.domains)
        modified = False

        if extend_far:
            # Far-facing: FORWARD 3′ end (last domain end_bp, increases)
            last = domains[-1]
            h = helix_by_id.get(last.helix_id)
            if h and last.overhang_id is None and last.direction == Direction.FORWARD:
                helix_last = h.bp_start + h.length_bp - 1
                if h.bp_start < last.end_bp < helix_last:
                    new_end = min(last.end_bp + length_bp, helix_last)
                    domains[-1] = Domain(
                        helix_id=last.helix_id, start_bp=last.start_bp,
                        end_bp=new_end, direction=last.direction)
                    modified = True

            # Far-facing: REVERSE 5′ end (first domain start_bp, increases)
            first = domains[0]
            h = helix_by_id.get(first.helix_id)
            if h and first.overhang_id is None and first.direction == Direction.REVERSE:
                helix_last = h.bp_start + h.length_bp - 1
                if h.bp_start < first.start_bp < helix_last:
                    new_start = min(first.start_bp + length_bp, helix_last)
                    domains[0] = Domain(
                        helix_id=first.helix_id, start_bp=new_start,
                        end_bp=first.end_bp, direction=first.direction)
                    modified = True
        else:
            # Near-facing: FORWARD 5′ end (first domain start_bp, decreases)
            first = domains[0]
            h = helix_by_id.get(first.helix_id)
            if h and first.overhang_id is None and first.direction == Direction.FORWARD:
                if h.bp_start < first.start_bp < h.bp_start + h.length_bp - 1:
                    new_start = max(first.start_bp - length_bp, h.bp_start)
                    domains[0] = Domain(
                        helix_id=first.helix_id, start_bp=new_start,
                        end_bp=first.end_bp, direction=first.direction)
                    modified = True

            # Near-facing: REVERSE 3′ end (last domain end_bp, decreases)
            last = domains[-1]
            h = helix_by_id.get(last.helix_id)
            if h and last.overhang_id is None and last.direction == Direction.REVERSE:
                if h.bp_start < last.end_bp < h.bp_start + h.length_bp - 1:
                    new_end = max(last.end_bp - length_bp, h.bp_start)
                    domains[-1] = Domain(
                        helix_id=last.helix_id, start_bp=last.start_bp,
                        end_bp=new_end, direction=last.direction)
                    modified = True

        if modified:
            strand_map[strand.id] = Strand(
                id=strand.id,
                strand_type=strand.strand_type,
                domains=domains,
                color=strand.color,
            )

    if not strand_map:
        return design

    updated_strands = [strand_map.get(s.id, s) for s in design.strands]
    return design.copy_with(
        strands=updated_strands,
    )


def _subgroup_by_offset(
    helices: "List[Helix]",
    plane: str,
    use_hi: bool,
) -> "List[tuple[float, List[Helix]]]":
    """Sub-group helices by their individual axis-lo (use_hi=False) or axis-hi (use_hi=True).

    Returns a list of (offset, [helix, ...]) pairs.  Helices within *tol* of
    the same offset are merged into one group.  This handles designs where a
    minority of helices are shorter or differently positioned than the rest —
    each distinct end-offset gets its own continuation call.
    """
    tol = BDNA_RISE_PER_BP * 0.5
    groups: list[tuple[float, list]] = []
    for h in helices:
        off = _helix_axis_hi(h, plane) if use_hi else _helix_axis_lo(h, plane)
        matched = next((g for g in groups if abs(g[0] - off) < tol), None)
        if matched is not None:
            matched[1].append(h)
        else:
            groups.append((off, [h]))
    return groups


def scaffold_extrude_near(
    design: Design,
    length_bp: int = 10,
    plane: str | None = None,
) -> Design:
    """Extend all near-end helices backward by exactly *length_bp* bp.

    Each helix subgroup at the near end is extended by exactly *length_bp* bp
    from its own current near-end position, regardless of other subgroups.

    Staple strands are NOT extended.
    """
    if not design.helices:
        return design
    skip = _overhang_only_helix_ids(design)
    helices = [h for h in design.helices if h.id not in skip]
    if not helices:
        return design
    plane = plane or _infer_plane(helices)
    segments = _group_helices_by_z_segment(helices, plane)
    near_seg = min(segments, key=lambda seg: min(_helix_axis_lo(h, plane) for h in seg))
    result = _extend_interior_scaffold_endpoints(design, length_bp, extend_far=False)
    for near_offset, group_helices in _subgroup_by_offset(near_seg, plane, use_hi=False):
        cells = _cells_from_helices(group_helices, plane)
        if not cells:
            continue
        result = make_bundle_continuation(
            result, cells, -length_bp,
            plane=plane, offset_nm=near_offset, strand_filter="scaffold",
        )
    return result


def scaffold_extrude_far(
    design: Design,
    length_bp: int = 10,
    plane: str | None = None,
) -> Design:
    """Extend all far-end helices forward by exactly *length_bp* bp.

    Each helix subgroup at the far end is extended by exactly *length_bp* bp
    from its own current far-end position, regardless of other subgroups.

    Staple strands are NOT extended.
    """
    if not design.helices:
        return design
    skip = _overhang_only_helix_ids(design)
    helices = [h for h in design.helices if h.id not in skip]
    if not helices:
        return design
    plane = plane or _infer_plane(helices)
    segments = _group_helices_by_z_segment(helices, plane)
    far_seg = max(segments, key=lambda seg: max(_helix_axis_hi(h, plane) for h in seg))
    result = _extend_interior_scaffold_endpoints(design, length_bp, extend_far=True)
    for far_offset, group_helices in _subgroup_by_offset(far_seg, plane, use_hi=True):
        cells = _cells_from_helices(group_helices, plane)
        if not cells:
            continue
        result = make_bundle_continuation(
            result, cells, length_bp,
            plane=plane, offset_nm=far_offset, strand_filter="scaffold",
            extend_inplace=True,
        )
    return result


def scaffold_add_end_crossovers(
    design: Design,
    min_end_margin: int = 1,
) -> Design:
    """Ligate outer-rail + inner U-strands into one continuous scaffold strand.

    After ``auto_scaffold`` with mode ``seam_line``, the design contains:

    - **path[0]** and **path[-1]**: full-length outer-rail strands.
    - **path[1..N-2]** inner pairs: each pair has a low-U (endpoints at bp 0)
      and a high-U (endpoints at bp L-1).

    This function ligates at the *even-indexed* between-pair junctions —
    path[0]↔path[1], path[2]↔path[3], path[4]↔path[5], … — at both bp 0
    (near) and bp L-1 (far).  Each junction uses the same helix pair at both
    ends, ensuring every crossover is between bases at the same position.

    The result is **one** continuous scaffold strand:

    - 5′ at path[-1] bp(L-1) → … → path[0] bp 0 → path[0] bp(L-1) → … → 3′ at path[-2] bp(L-1)
      (exact terminus depends on path direction; call ``scaffold_nick`` to set the nick).

    To set the final 5′/3′ termini, call ``scaffold_nick`` after this function.

    Parameters
    ----------
    min_end_margin:
        Minimum bp margin used when computing the Hamiltonian path.  Set to 1
        (not the usual 9) because the path must match the one used in
        ``auto_scaffold`` — if the seam routing was run with a small helix, this
        allows path recovery.  The path is used only to determine ligation order,
        not to place crossovers.
    """
    if not design.helices:
        return design

    skip = _overhang_only_helix_ids(design)
    helices = [h for h in design.helices if h.id not in skip]
    if not helices:
        return design

    plane = _infer_plane(helices)
    segments = _group_helices_by_z_segment(helices, plane)

    result = design
    for seg_helices in segments:
        if len(seg_helices) < 2:
            continue

        sub_design = result.model_copy(update={"helices": seg_helices})

        # Expand merged (gap-continuation) helices into per-region virtual helices,
        # mirroring what auto_scaffold does so that path + junction bp values match.
        all_helix_ids_for_regions = {h.id for h in seg_helices}
        coverage_regions = _scaffold_coverage_regions(sub_design, all_helix_ids_for_regions)
        virt_helices, virtual_to_real = _expand_helices_for_seam(seg_helices, coverage_regions, plane)
        has_merged = len(virt_helices) > len(seg_helices)

        # Re-group virtual helices by Z so disconnected sub-segments (gap-continuation)
        # are each routed independently, mirroring what auto_scaffold does.
        virt_z_segs = (
            _group_helices_by_z_segment(virt_helices, plane) if has_merged else [virt_helices]
        )

        for virt_seg in virt_z_segs:
            virt_sub = sub_design.model_copy(update={"helices": virt_seg})

            _ec_tol = BDNA_RISE_PER_BP * 0.5
            _ec_gs_lo = min(_helix_axis_lo(h, plane) for h in virt_seg)
            _ec_gs_hi = max(_helix_axis_hi(h, plane) for h in virt_seg)

            # ── has_merged bridge case ─────────────────────────────────────────
            # When virt_seg contains both full-range and partial virtual helices
            # (gap-continuation design), mirror the auto_scaffold has_merged
            # sub-bundle split: route 6HB core + Z-grouped 12HB segments
            # separately so the path matches what auto_scaffold built.
            _ec_full_ids = {
                h.id for h in virt_seg
                if abs(_helix_axis_lo(h, plane) - _ec_gs_lo) <= _ec_tol
                and abs(_helix_axis_hi(h, plane) - _ec_gs_hi) <= _ec_tol
            }
            _ec_full_virt    = [h for h in virt_seg if h.id in _ec_full_ids]
            _ec_partial_virt = [h for h in virt_seg if h.id not in _ec_full_ids]

            if has_merged and _ec_partial_virt and _ec_full_virt:
                # ── Helper: apply near/far end ligations for one sub-path ─────
                def _apply_end_ligations_ec(
                    sub_path: "list[str]",
                    sub_by_id: "dict[str, Helix]",
                    sub_dirs: "dict[str, Direction]",
                    sub_vtr: "dict[str, str]",
                ) -> None:
                    nonlocal result
                    for _i in range(0, len(sub_path) - 1, 2):
                        _vid_a  = sub_path[_i]
                        _vid_b  = sub_path[_i + 1]
                        _dir_a  = sub_dirs.get(_vid_a)
                        if _dir_a is None:
                            continue
                        _rid_a  = sub_vtr.get(_vid_a, _vid_a)
                        _rid_b  = sub_vtr.get(_vid_b, _vid_b)
                        _ha     = sub_by_id[_vid_a]
                        _hb     = sub_by_id[_vid_b]
                        _lo_a   = _helix_axis_lo(_ha, plane)
                        _lo_b   = _helix_axis_lo(_hb, plane)
                        _near_z = max(_lo_a, _lo_b)
                        _nbp_a  = round((_near_z - _lo_a) / BDNA_RISE_PER_BP) + _ha.bp_start
                        _nbp_b  = round((_near_z - _lo_b) / BDNA_RISE_PER_BP) + _hb.bp_start
                        if abs(_lo_a - _lo_b) <= _ec_tol:
                            if _dir_a == Direction.REVERSE:
                                _h3, _b3, _h5, _b5 = _rid_a, _nbp_a, _rid_b, _nbp_b
                            else:
                                _h3, _b3, _h5, _b5 = _rid_b, _nbp_b, _rid_a, _nbp_a
                            _s3 = _find_strand_by_3prime(result, _h3, _b3, StrandType.SCAFFOLD)
                            _s5 = _find_strand_by_5prime(result, _h5, _b5, StrandType.SCAFFOLD)
                            if _s3 is not None and _s5 is not None and _s3.id != _s5.id:
                                result = _ligate(result, _s3, _s5)
                        _hi_a = _helix_axis_hi(_ha, plane)
                        _hi_b = _helix_axis_hi(_hb, plane)
                        if abs(_hi_a - _hi_b) <= _ec_tol:
                            _La, _Lb = _ha.length_bp, _hb.length_bp
                            if _dir_a == Direction.FORWARD:
                                _h3f, _b3f = _rid_a, _ha.bp_start + _La - 1
                                _h5f, _b5f = _rid_b, _hb.bp_start + _Lb - 1
                            else:
                                _h3f, _b3f = _rid_b, _hb.bp_start + _Lb - 1
                                _h5f, _b5f = _rid_a, _ha.bp_start + _La - 1
                            _s3f = _find_strand_by_3prime(result, _h3f, _b3f, StrandType.SCAFFOLD)
                            _s5f = _find_strand_by_5prime(result, _h5f, _b5f, StrandType.SCAFFOLD)
                            if _s3f is not None and _s5f is not None and _s3f.id != _s5f.id:
                                result = _ligate(result, _s3f, _s5f)

                # ── 6HB core sub-bundle ────────────────────────────────────────
                _ecf_by_id  = {h.id: h for h in _ec_full_virt}
                _ecf_vtr    = {h.id: virtual_to_real.get(h.id, h.id) for h in _ec_full_virt}
                _ecf_dirs: dict[str, Direction] = {}
                for _fh in _ec_full_virt:
                    _d = _get_scaffold_direction(sub_design, _ecf_vtr[_fh.id])
                    if _d is not None:
                        _ecf_dirs[_fh.id] = _d

                _partial_xy_ec = [
                    (h.axis_start.x, h.axis_start.y) for h in _ec_partial_virt
                ]

                def _adj_to_partial_ec(fh: Helix) -> bool:
                    for _px, _py in _partial_xy_ec:
                        _dx = fh.axis_start.x - _px
                        _dy = fh.axis_start.y - _py
                        if math.sqrt(_dx * _dx + _dy * _dy) <= HONEYCOMB_HELIX_SPACING * 1.05:
                            return True
                    return False

                _full_sorted_ec = sorted(
                    _ec_full_virt, key=lambda h: (0 if _adj_to_partial_ec(h) else 1)
                )
                _full_sub_ec = sub_design.model_copy(update={"helices": _ec_full_virt})
                _full_adj_ec = _helix_adjacency_graph(_full_sub_ec, min_end_margin)
                _full_path_ec: list[str] | None = None
                for _sh in _full_sorted_ec:
                    _p = _greedy_hamiltonian_path(_full_adj_ec, _sh.id)
                    if _p is None:
                        _p = _backtrack_hamiltonian_path(_full_adj_ec, _sh.id)
                    if _p:
                        _full_path_ec = _p
                        break
                if _full_path_ec and len(_full_path_ec) >= 2:
                    _apply_end_ligations_ec(_full_path_ec, _ecf_by_id, _ecf_dirs, _ecf_vtr)

                # ── 12HB segment sub-bundles ───────────────────────────────────
                _partial_z_grps = sorted(
                    _group_helices_by_z_segment(_ec_partial_virt, plane),
                    key=lambda g: min(_helix_axis_lo(h, plane) for h in g),
                )
                for _grp in _partial_z_grps:
                    _grp_by_id = {h.id: h for h in _grp}
                    _grp_vtr   = {h.id: virtual_to_real.get(h.id, h.id) for h in _grp}
                    _grp_dirs: dict[str, Direction] = {}
                    for _v in _grp_by_id:
                        _d = _get_scaffold_direction(sub_design, _grp_vtr.get(_v, _v))
                        if _d is not None:
                            _grp_dirs[_v] = _d
                    _grp_sub = sub_design.model_copy(update={"helices": _grp})
                    _grp_adj = _helix_adjacency_graph(_grp_sub, min_end_margin)
                    _grp_path_ec: list[str] | None = None
                    for _sh in _grp:
                        _q = _greedy_hamiltonian_path(_grp_adj, _sh.id)
                        if _q is None:
                            _q = _backtrack_hamiltonian_path(_grp_adj, _sh.id)
                        if _q:
                            _grp_path_ec = _q
                            break
                    if _grp_path_ec and len(_grp_path_ec) >= 2:
                        _apply_end_ligations_ec(
                            _grp_path_ec, _grp_by_id, _grp_dirs, _grp_vtr
                        )
                continue  # skip single-path logic for this virt_seg

            # ── Standard path recovery (non-has_merged) ───────────────────────
            # Mirror the same path selection used by auto_scaffold seam_line:
            # for cross-section designs, use _find_seam_routing_path so cross-Z
            # transitions land at seam-pair (odd) positions, not end-pair (even) positions.
            tol = _ec_tol
            global_lo_seg = _ec_gs_lo
            full_span_ids = {
                h.id for h in virt_seg
                if abs(_helix_axis_lo(h, plane) - global_lo_seg) <= tol
            }
            is_cross_section = len(full_span_ids) < len(virt_seg)

            if is_cross_section:
                path = _find_seam_routing_path(virt_sub, full_span_ids, min_end_margin)
            else:
                path = compute_scaffold_routing(virt_sub, min_end_margin=min_end_margin)
            if path is None or len(path) < 2:
                continue

            virt_helices_by_id = {h.id: h for h in virt_seg}
            scaf_dirs = {
                virt_hid: _get_scaffold_direction(sub_design, virtual_to_real.get(virt_hid, virt_hid))
                for virt_hid in path
            }

            # Between-pair junctions: path[0]↔path[1], path[2]↔path[3], ...
            # Each junction: near-end ligation (REVERSE_3'@near_bp → FORWARD_5'@near_bp)
            #                far-end  ligation (FORWARD_3'@bpL → REVERSE_5'@bpL)
            # For merged helices, virtual IDs are remapped to real IDs for strand lookups;
            # bp values are computed from virtual helix geometry (= global bp of the region).
            for i in range(0, len(path) - 1, 2):
                virt_hid_odd  = path[i]
                virt_hid_even = path[i + 1]
                dir_odd  = scaf_dirs[virt_hid_odd]
                dir_even = scaf_dirs[virt_hid_even]
                real_hid_odd  = virtual_to_real.get(virt_hid_odd,  virt_hid_odd)
                real_hid_even = virtual_to_real.get(virt_hid_even, virt_hid_even)

                # Per-helix near-end bp: global bp index at the shared near-Z boundary.
                h_odd  = virt_helices_by_id[virt_hid_odd]
                h_even = virt_helices_by_id[virt_hid_even]
                lo_z_odd  = _helix_axis_lo(h_odd,  plane)
                lo_z_even = _helix_axis_lo(h_even, plane)
                near_z    = max(lo_z_odd, lo_z_even)
                near_bp_odd  = round((near_z - lo_z_odd)  / BDNA_RISE_PER_BP) + h_odd.bp_start
                near_bp_even = round((near_z - lo_z_even) / BDNA_RISE_PER_BP) + h_even.bp_start

                # Near-end: only ligate if both helices start at the same Z (same Z-subgroup).
                _near_tol = BDNA_RISE_PER_BP * 0.5
                if abs(lo_z_odd - lo_z_even) <= _near_tol:
                    if dir_odd == Direction.REVERSE:
                        hid_3 = real_hid_odd;  bp_3 = near_bp_odd
                        hid_5 = real_hid_even; bp_5 = near_bp_even
                    else:
                        hid_3 = real_hid_even; bp_3 = near_bp_even
                        hid_5 = real_hid_odd;  bp_5 = near_bp_odd

                    s3 = _find_strand_by_3prime(result, hid_3, bp_3, StrandType.SCAFFOLD)
                    s5 = _find_strand_by_5prime(result, hid_5, bp_5, StrandType.SCAFFOLD)
                    if s3 is not None and s5 is not None and s3.id != s5.id:
                        result = _ligate(result, s3, s5)

                # Far-end: only ligate if both virtual helices end at the same Z.
                # Skips (full ↔ seg0) and (seg0 ↔ seg1) pairs that differ in axis_hi,
                # which would otherwise create crossovers spanning the gap region.
                hi_z_odd  = _helix_axis_hi(h_odd,  plane)
                hi_z_even = _helix_axis_hi(h_even, plane)
                _far_tol  = BDNA_RISE_PER_BP * 0.5
                if abs(hi_z_odd - hi_z_even) <= _far_tol:
                    L_odd  = h_odd.length_bp
                    L_even = h_even.length_bp
                    if dir_odd == Direction.FORWARD:
                        hid_3f = real_hid_odd;  bp_3f = h_odd.bp_start  + L_odd  - 1
                        hid_5f = real_hid_even; bp_5f = h_even.bp_start + L_even - 1
                    else:
                        hid_3f = real_hid_even; bp_3f = h_even.bp_start + L_even - 1
                        hid_5f = real_hid_odd;  bp_5f = h_odd.bp_start  + L_odd  - 1

                    s3f = _find_strand_by_3prime(result, hid_3f, bp_3f, StrandType.SCAFFOLD)
                    s5f = _find_strand_by_5prime(result, hid_5f, bp_5f, StrandType.SCAFFOLD)
                    if s3f is not None and s5f is not None and s3f.id != s5f.id:
                        result = _ligate(result, s3f, s5f)

    from backend.core.crossover_positions import extract_crossovers_from_strands
    return result.model_copy(update={
        "crossovers": extract_crossovers_from_strands(result.strands),
    })


# ── Scaffold split ────────────────────────────────────────────────────────────


def scaffold_split(
    design: Design,
    strand_id: str,
    helix_id: str,
    bp_position: int,
) -> Design:
    """Split a scaffold strand into two by placing a nick at the given position.

    Both resulting strands retain ``strand_type=SCAFFOLD``.  This is a thin
    wrapper around ``make_nick`` that validates the target strand type.

    Parameters
    ----------
    design:
        Active design.
    strand_id:
        ID of the scaffold strand to split.
    helix_id:
        Helix on which the nick should be placed.
    bp_position:
        Global bp index where the nick is inserted.

    Returns
    -------
    Updated Design with the scaffold strand split into two.

    Raises
    ------
    ValueError
        If the strand is not a scaffold strand or the position is invalid.
    """
    from backend.core.models import StrandType

    strand = next((s for s in design.strands if s.id == strand_id), None)
    if strand is None:
        raise ValueError(f"Strand {strand_id!r} not found in the design.")
    if strand.strand_type != StrandType.SCAFFOLD:
        raise ValueError(
            f"Strand {strand_id!r} is not a scaffold strand "
            f"(strand_type={strand.strand_type!r}). Only scaffold strands can be split."
        )

    # Determine direction from the domain covering (helix_id, bp_position).
    domain = next(
        (
            d for d in strand.domains
            if d.helix_id == helix_id
            and (
                (d.direction.value == "FORWARD" and d.start_bp <= bp_position <= d.end_bp)
                or (d.direction.value == "REVERSE" and d.end_bp <= bp_position <= d.start_bp)
            )
        ),
        None,
    )
    if domain is None:
        raise ValueError(
            f"Position (helix={helix_id!r}, bp={bp_position}) is not within "
            f"any domain of strand {strand_id!r}."
        )

    return make_nick(design, helix_id, bp_position, domain.direction)


# ── Overhang extrusion ────────────────────────────────────────────────────────


def make_overhang_extrude(
    design: Design,
    helix_id: str,
    bp_index: int,
    direction: Direction,
    is_five_prime: bool,
    neighbor_row: int,
    neighbor_col: int,
    length_bp: int,
) -> Design:
    """Extrude a staple-only overhang from a nick into an unoccupied neighbour cell.

    Creates a new helix at (neighbor_row, neighbor_col) with ``length_bp`` base
    pairs and prepends/appends a new staple domain to the existing staple strand
    at the 5′/3′ nick position.

    The new helix bp 0 is placed at the same Z-coordinate as ``bp_index`` on the
    original helix.  The crossover is at bp 0 on the new helix; the strand
    traverses the overhang helix away from that junction.

    Raises ValueError if:
    - The helix is not found.
    - No staple strand has its 5′/3′ end at (helix_id, bp_index, direction).
    - length_bp < 1.
    """
    if length_bp < 1:
        raise ValueError(f"length_bp must be ≥ 1, got {length_bp}.")

    # ── Find original helix ──────────────────────────────────────────────────
    orig_helix: Helix | None = next((h for h in design.helices if h.id == helix_id), None)
    if orig_helix is None:
        raise ValueError(f"Helix {helix_id!r} not found.")

    # ── Find the staple strand whose 5′/3′ end is at (helix_id, bp_index) ───
    strand: Strand | None = None
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or not s.domains:
            continue
        first = s.domains[0]
        last  = s.domains[-1]
        if is_five_prime:
            if first.helix_id == helix_id and first.start_bp == bp_index and first.direction == direction:
                strand = s
                break
        else:
            if last.helix_id == helix_id and last.end_bp == bp_index and last.direction == direction:
                strand = s
                break
    if strand is None:
        end_label = "5′" if is_five_prime else "3′"
        raise ValueError(
            f"No staple strand has its {end_label} end at "
            f"(helix={helix_id!r}, bp={bp_index}, direction={direction.value})."
        )

    # ── Geometry of the nick Z-position ─────────────────────────────────────
    # For XY-plane helices the axis is in Z; rise per bp may be negative if
    # the helix was built in −Z direction.
    # IMPORTANT: bp_index is a *global* index; axis_point uses the *local*
    # index (global − bp_start) so that designs with bp_start > 0 (e.g.
    # caDNAno imports) place the overhang at the correct absolute Z.
    axis_z_span  = orig_helix.axis_end.z - orig_helix.axis_start.z
    rise         = BDNA_RISE_PER_BP if axis_z_span >= 0 else -BDNA_RISE_PER_BP
    local_orig_i = bp_index - orig_helix.bp_start
    z_nick       = orig_helix.axis_start.z + local_orig_i * rise

    # U-turn rule: the overhang strand on helix B must be antiparallel to the
    # original strand at the nick.
    #
    # The strand's 5'→3' Z direction at the nick:
    #   FORWARD strand on a +Z helix → +Z  (strand_z_dir = +1)
    #   REVERSE strand on a +Z helix → −Z  (strand_z_dir = −1)
    #
    # For a 3′ nick the strand exits in strand_z_dir; the overhang must go in
    # the opposite direction so the two arms of the U run antiparallel.
    # For a 5′ nick the strand enters in strand_z_dir; the overhang must go in
    # the same direction (which is again antiparallel to the entering strand,
    # because it arrives from that direction and turns around at the nick).
    #
    # Result:
    #   3′ nick, FORWARD (+Z) → overhang −Z     3′ nick, REVERSE (−Z) → overhang +Z
    #   5′ nick, FORWARD (+Z) → overhang +Z     5′ nick, REVERSE (−Z) → overhang −Z
    z_dir         = 1 if axis_z_span >= 0 else -1
    strand_z_dir  = z_dir if direction == Direction.FORWARD else -z_dir
    overhang_z_dir = strand_z_dir if is_five_prime else -strand_z_dir
    length_nm     = length_bp * BDNA_RISE_PER_BP

    # ── Neighbour cell XY position ───────────────────────────────────────────
    nx, ny = honeycomb_position(neighbor_row, neighbor_col)

    # ── New domain direction ─────────────────────────────────────────────────
    # The crossover is at the new helix's near-end (local bp 0).
    # 5′ nick → new domain 3′ end at near bp  → REVERSE
    # 3′ nick → new domain 5′ end at near bp  → FORWARD
    # Domain bp values are global: use bp_start of the new helix.
    new_dir = Direction.REVERSE if is_five_prime else Direction.FORWARD

    # ── Phase offset for new helix ───────────────────────────────────────────
    # local_orig_i already computed above for z_nick.
    theta   = orig_helix.phase_offset + local_orig_i * BDNA_TWIST_PER_BP_RAD
    if overhang_z_dir > 0:
        phase_new = (math.pi + theta) % (2 * math.pi)
    else:
        phase_new = (-theta) % (2 * math.pi)

    # ── New helix ID (collision-safe) ────────────────────────────────────────
    existing_ids = {h.id for h in design.helices}
    base_id      = f"h_XY_{neighbor_row}_{neighbor_col}"
    new_helix_id = base_id
    if new_helix_id in existing_ids:
        i = 1
        while f"{base_id}_{i}" in existing_ids:
            i += 1
        new_helix_id = f"{base_id}_{i}"

    new_axis_start = Vec3(x=nx, y=ny, z=z_nick)
    new_axis_end   = Vec3(x=nx, y=ny, z=z_nick + overhang_z_dir * length_nm)
    # Anchor bp_start to the parent's bp_index so the overhang junction
    # aligns in the cadnano 2D path view regardless of Z direction.
    new_bp_start   = bp_index
    new_helix = Helix(
        id           = new_helix_id,
        axis_start   = new_axis_start,
        axis_end     = new_axis_end,
        bp_start     = new_bp_start,
        phase_offset = phase_new,
        length_bp    = length_bp,
        direction    = new_dir,
    )

    # Domain bp values are global (near-end = new_bp_start, far-end = new_bp_start + L - 1)
    if new_dir == Direction.FORWARD:
        new_start_bp, new_end_bp = new_bp_start, new_bp_start + length_bp - 1
    else:
        new_start_bp, new_end_bp = new_bp_start + length_bp - 1, new_bp_start

    # ── Overhang ID ──────────────────────────────────────────────────────────
    end_tag     = "5p" if is_five_prime else "3p"
    overhang_id = f"ovhg_{helix_id}_{bp_index}_{end_tag}"

    new_domain = Domain(
        helix_id    = new_helix_id,
        start_bp    = new_start_bp,
        end_bp      = new_end_bp,
        direction   = new_dir,
        overhang_id = overhang_id,
    )

    # ── OverhangSpec ─────────────────────────────────────────────────────────
    overhang_spec = OverhangSpec(
        id        = overhang_id,
        helix_id  = new_helix_id,
        strand_id = strand.id,
    )
    # Replace any existing spec with the same id (idempotent re-extrude)
    existing_overhangs = [o for o in design.overhangs if o.id != overhang_id]
    new_overhangs = existing_overhangs + [overhang_spec]

    # ── Register crossover between parent and overhang helix ────────────────
    # The junction is at bp_index on both helices (ensured by new_bp_start above).
    ovhg_xover = Crossover(
        half_a=HalfCrossover(helix_id=helix_id,     index=bp_index, strand=direction),
        half_b=HalfCrossover(helix_id=new_helix_id,  index=bp_index, strand=new_dir),
    )
    new_crossovers = list(design.crossovers) + [ovhg_xover]

    # ── Extend the strand ────────────────────────────────────────────────────
    new_strand = strand.model_copy(deep=True)
    if strand.sequence is not None:
        # Preserve existing sequence; pad with 'N' for the new overhang bases.
        overhang_pad = "N" * length_bp
        if is_five_prime:
            new_strand.sequence = overhang_pad + strand.sequence
        else:
            new_strand.sequence = strand.sequence + overhang_pad
    if is_five_prime:
        new_strand.domains = [new_domain] + list(new_strand.domains)
    else:
        new_strand.domains = list(new_strand.domains) + [new_domain]

    new_helices = list(design.helices) + [new_helix]
    new_strands = [new_strand if s.id == strand.id else s for s in design.strands]

    # ── Add new helix to the same cluster as the parent helix ────────────────
    new_cluster_transforms = list(design.cluster_transforms)
    for i, ct in enumerate(new_cluster_transforms):
        if helix_id in ct.helix_ids and new_helix_id not in ct.helix_ids:
            new_cluster_transforms[i] = ct.model_copy(
                update={"helix_ids": list(ct.helix_ids) + [new_helix_id]}
            )
            break

    return design.model_copy(update={
        "helices":            new_helices,
        "strands":            new_strands,
        "crossovers":         new_crossovers,
        "overhangs":          new_overhangs,
        "deformations":       design.deformations,
        "cluster_transforms": new_cluster_transforms,
    })


# ── Strand-end resize (interactive drag extrusion / trim) ─────────────────────


def _scaffold_coverage_by_helix(design: Design) -> dict[str, tuple[int, int]]:
    """Return ``{helix_id: (lo_bp, hi_bp)}`` for every helix that has scaffold coverage.

    Multiple scaffold domains on the same helix are merged into a single range.
    """
    coverage: dict[str, tuple[int, int]] = {}
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE:
            for dom in strand.domains:
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                if dom.helix_id in coverage:
                    prev_lo, prev_hi = coverage[dom.helix_id]
                    coverage[dom.helix_id] = (min(prev_lo, lo), max(prev_hi, hi))
                else:
                    coverage[dom.helix_id] = (lo, hi)
    return coverage



def _reconcile_inline_overhangs(
    strands_by_id: dict,
    overhangs_by_id: dict,
    modified: list[tuple[str, str]],
    scaf_cov: dict[str, tuple[int, int]],
) -> None:
    """Detect/remove inline overhang splits on modified strand terminal domains.

    For each ``(strand_id, end)`` pair in *modified* that belongs to a staple strand:

    1. If the current terminal domain is already tagged with our inline overhang ID,
       **merge** it back into the adjacent scaffold domain (undo the previous split)
       and remove the stale OverhangSpec.  The existing ``sequence``/``label`` values
       are preserved so a later re-split can restore them.

    2. If, after the merge, the terminal domain still extends beyond scaffold
       coverage on its helix, **split** it into a scaffold-covered portion and an
       overhang portion.  Tag the overhang domain with ``ovhg_inline_{strand_id}_{end}``
       and upsert an OverhangSpec (preserving any sequence/label the user already set).

    Mutates *strands_by_id* and *overhangs_by_id* in-place.
    """
    _INLINE = "ovhg_inline_"

    for strand_id, end in modified:
        strand = strands_by_id.get(strand_id)
        if strand is None or strand.strand_type != StrandType.STAPLE:
            continue
        domains = list(strand.domains)
        if not domains:
            continue

        is_5p = end == "5p"
        term_idx = 0 if is_5p else len(domains) - 1
        term_dom = domains[term_idx]

        # Scaffold-free helices: overhang tagging is owned exclusively by
        # autodetect_overhangs.  Skip here to avoid clobbering that tagging.
        if term_dom.helix_id not in scaf_cov:
            continue

        ovhg_id = f"{_INLINE}{strand_id}_{end}"

        # ── Merge previous inline overhang (undo prior split) ─────────────────
        existing_spec = overhangs_by_id.get(ovhg_id)   # capture before deletion
        if term_dom.overhang_id == ovhg_id:
            adj_idx = term_idx + 1 if is_5p else term_idx - 1
            if 0 <= adj_idx < len(domains) and domains[adj_idx].helix_id == term_dom.helix_id:
                first  = domains[min(term_idx, adj_idx)]
                second = domains[max(term_idx, adj_idx)]
                merged = first.model_copy(update={
                    "start_bp":   first.start_bp,
                    "end_bp":     second.end_bp,
                    "overhang_id": None,
                })
                lo = min(term_idx, adj_idx)
                domains[lo : lo + 2] = [merged]
            else:
                domains[term_idx] = term_dom.model_copy(update={"overhang_id": None})
            overhangs_by_id.pop(ovhg_id, None)
            term_idx = 0 if is_5p else len(domains) - 1
            term_dom = domains[term_idx]

        # ── Check for scaffold-boundary overhang ──────────────────────────────
        helix_id = term_dom.helix_id
        if helix_id not in scaf_cov:
            strands_by_id[strand_id] = strand.model_copy(update={"domains": domains})
            continue

        scaf_lo, scaf_hi = scaf_cov[helix_id]
        is_fwd = term_dom.direction == Direction.FORWARD
        new_ovhg: Domain | None = None

        # Each branch only fires when the domain *partially* overlaps scaffold.
        # If the entire domain is outside scaffold coverage (both start_bp and
        # end_bp on the same side of the boundary), no split is warranted — the
        # domain is a legitimate terminal on an unscaffolded region of the helix.
        # Without this guard the "scaffold part" would be a zero- or
        # negative-length domain with start/end swapped, producing spurious
        # strand geometry (the "filled-in gap" / circular-strand artefact).

        if is_5p and is_fwd:
            # 5' of FORWARD = start_bp (low side). Partial overlap: start below
            # scaf_lo but end still within coverage.
            if term_dom.start_bp < scaf_lo <= term_dom.end_bp:
                new_ovhg   = term_dom.model_copy(update={"end_bp": scaf_lo - 1, "overhang_id": ovhg_id})
                scaf_part  = term_dom.model_copy(update={"start_bp": scaf_lo, "overhang_id": None})
                domains[term_idx : term_idx + 1] = [new_ovhg, scaf_part]

        elif is_5p and not is_fwd:
            # 5' of REVERSE = start_bp (high side). Partial overlap: start above
            # scaf_hi but end still within coverage.
            if term_dom.start_bp > scaf_hi >= term_dom.end_bp:
                new_ovhg   = term_dom.model_copy(update={"end_bp": scaf_hi + 1, "overhang_id": ovhg_id})
                scaf_part  = term_dom.model_copy(update={"start_bp": scaf_hi, "overhang_id": None})
                domains[term_idx : term_idx + 1] = [new_ovhg, scaf_part]

        elif not is_5p and is_fwd:
            # 3' of FORWARD = end_bp (high side). Partial overlap: end above
            # scaf_hi but start still within coverage.
            if term_dom.end_bp > scaf_hi >= term_dom.start_bp:
                scaf_part  = term_dom.model_copy(update={"end_bp": scaf_hi, "overhang_id": None})
                new_ovhg   = term_dom.model_copy(update={"start_bp": scaf_hi + 1, "overhang_id": ovhg_id})
                domains[term_idx : term_idx + 1] = [scaf_part, new_ovhg]

        else:
            # 3' of REVERSE = end_bp (low side). Partial overlap: end below
            # scaf_lo but start still within coverage.
            if term_dom.end_bp < scaf_lo <= term_dom.start_bp:
                scaf_part  = term_dom.model_copy(update={"end_bp": scaf_lo, "overhang_id": None})
                new_ovhg   = term_dom.model_copy(update={"start_bp": scaf_lo - 1, "overhang_id": ovhg_id})
                domains[term_idx : term_idx + 1] = [scaf_part, new_ovhg]

        if new_ovhg is not None:
            overhangs_by_id[ovhg_id] = OverhangSpec(
                id=ovhg_id,
                helix_id=helix_id,
                strand_id=strand_id,
                sequence=existing_spec.sequence if existing_spec else None,
                label=existing_spec.label    if existing_spec else None,
            )

        strands_by_id[strand_id] = strand.model_copy(update={"domains": domains})


def autodetect_overhangs(design: Design) -> Design:
    """Detect and register terminal domains on scaffold-free helices as inline overhangs.

    For each staple strand whose 5′ or 3′ terminal domain lies on a helix with
    **no scaffold coverage at all**, and where at least one other domain is on a
    scaffold-covered helix (i.e. the strand is attached to the bundle), create an
    ``OverhangSpec`` and tag the domain with ``ovhg_inline_{strand_id}_{5p|3p}``.

    Already-tagged domains (``overhang_id`` is set) are left unchanged.  This
    complements ``_reconcile_inline_overhangs``, which handles the case where a
    terminal domain extends *beyond* scaffold coverage on the *same* helix.
    """
    scaf_cov = _scaffold_coverage_by_helix(design)
    strands_by_id: dict[str, Strand] = {s.id: s for s in design.strands}
    overhangs_by_id: dict[str, OverhangSpec] = {o.id: o for o in design.overhangs}
    _INLINE = "ovhg_inline_"

    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or len(strand.domains) < 2:
            continue
        # Must be anchored to the bundle (≥1 domain on a scaffold-covered helix)
        if not any(d.helix_id in scaf_cov for d in strand.domains):
            continue

        domains = list(strand.domains)
        changed = False

        for end, term_idx in (("5p", 0), ("3p", len(domains) - 1)):
            term_dom = domains[term_idx]
            if term_dom.overhang_id is not None:
                continue  # already tagged — preserve existing annotation
            if term_dom.helix_id in scaf_cov:
                continue  # scaffold-covered helix: handled by _reconcile_inline_overhangs

            ovhg_id = f"{_INLINE}{strand.id}_{end}"
            domains[term_idx] = term_dom.model_copy(update={"overhang_id": ovhg_id})
            overhangs_by_id[ovhg_id] = OverhangSpec(
                id=ovhg_id,
                helix_id=term_dom.helix_id,
                strand_id=strand.id,
            )
            changed = True

        if changed:
            strands_by_id[strand.id] = strand.model_copy(update={"domains": domains})

    return design.copy_with(
        strands=[strands_by_id[s.id] for s in design.strands],
        overhangs=list(overhangs_by_id.values()),
    )


def autodetect_all_overhangs(design: Design) -> Design:
    """Run the complete overhang auto-detection pipeline on a freshly imported design.

    Two detection passes are needed because overhangs can arise in two ways:

    Pass 1 — scaffold-free helices (``autodetect_overhangs``):
        A staple terminal domain sits entirely on a helix that carries no scaffold
        at all.  The function tags it with ``ovhg_inline_{strand_id}_{5p|3p}`` and
        creates an OverhangSpec.  This is the typical case for dedicated overhang
        stub helices in NADOC-native designs.

    Pass 2 — extends-beyond-scaffold-boundary on a scaffold-carrying helix
        (``_reconcile_inline_overhangs`` applied to all staple ends):
        A staple terminal domain shares a helix with the scaffold but its bp
        range extends *beyond* the scaffold coverage boundary.  ``autodetect_overhangs``
        explicitly skips these (``if term_dom.helix_id in scaf_cov: continue``) and
        defers to ``_reconcile_inline_overhangs``, which normally only runs during
        ``resize_strand_ends``.  Calling it here with every staple strand end as
        "modified" performs the initial split on import.

    This function is idempotent: already-tagged domains (``overhang_id`` set) are
    left unchanged by both passes.
    """
    # Pass 1: scaffold-free helix overhangs
    design = autodetect_overhangs(design)

    # Pass 2: domains that extend beyond scaffold boundary on scaffold-covered helices
    strands_by_id:  dict[str, Strand]       = {s.id: s for s in design.strands}
    overhangs_by_id: dict[str, OverhangSpec] = {o.id: o for o in design.overhangs}
    scaf_cov = _scaffold_coverage_by_helix(design)

    all_modified: list[tuple[str, str]] = [
        (s.id, end)
        for s in design.strands
        if s.strand_type == StrandType.STAPLE
        for end in ("5p", "3p")
    ]
    _reconcile_inline_overhangs(strands_by_id, overhangs_by_id, all_modified, scaf_cov)

    # Assign default labels OH1, OH2, … to any overhang that has no label yet.
    # Sort by id for deterministic ordering across runs.
    oh_counter = 1
    for ovhg_id in sorted(overhangs_by_id):
        ovhg = overhangs_by_id[ovhg_id]
        if not ovhg.label:
            overhangs_by_id[ovhg_id] = ovhg.model_copy(update={"label": f"OH{oh_counter}"})
        oh_counter += 1

    return design.copy_with(
        strands=[strands_by_id[s.id] for s in design.strands],
        overhangs=list(overhangs_by_id.values()),
    )


def resize_strand_ends(design: Design, entries: list[dict]) -> Design:
    """Resize one or more strand terminal domains by *delta_bp* each.

    Each entry dict must have::

        strand_id : str        – which strand to modify
        helix_id  : str        – the helix the terminal domain sits on
        end       : '5p'|'3p'  – which terminus to move
        delta_bp  : int        – signed bp offset (positive = toward higher global bp)

    The terminal domain's ``start_bp`` (for the 5′ end) or ``end_bp`` (for the
    3′ end) is shifted by *delta_bp*.  If the new bp lies outside the helix's
    current bp range the helix axis is grown to accommodate it, maintaining
    phase continuity.

    Helix growth logic mirrors ``make_bundle_continuation``'s backward /
    forward in-place extension: the axis endpoint moves by
    ``|extra| * BDNA_RISE_PER_BP`` nm along the existing axis direction, and
    ``bp_start`` / ``length_bp`` are updated accordingly.
    """
    import math as _math

    helices_by_id: dict[str, Helix] = {h.id: h for h in design.helices}
    strands_by_id: dict[str, Strand] = {s.id: s for s in design.strands}
    overhangs_by_id: dict[str, OverhangSpec] = {o.id: o for o in design.overhangs}
    modified: list[tuple[str, str]] = []   # (strand_id, '5p'|'3p') for reconciliation

    for entry in entries:
        strand = strands_by_id[entry["strand_id"]]
        helix  = helices_by_id[entry["helix_id"]]
        delta  = int(entry["delta_bp"])
        end    = entry["end"]   # '5p' or '3p'

        if not strand.domains:
            continue

        domains = list(strand.domains)

        if end == "5p":
            term_dom   = domains[0]
            cur_bp     = term_dom.start_bp
            new_bp     = cur_bp + delta
            new_domain = term_dom.model_copy(update={"start_bp": new_bp})
            domains[0] = new_domain
        else:  # '3p'
            term_dom   = domains[-1]
            cur_bp     = term_dom.end_bp
            new_bp     = cur_bp + delta
            new_domain = term_dom.model_copy(update={"end_bp": new_bp})
            domains[-1] = new_domain

        # ── Grow helix if needed ──────────────────────────────────────────────
        ax = helix.axis_start
        bx = helix.axis_end
        # Unit vector along helix axis (axis_start → axis_end)
        dx = bx.x - ax.x;  dy = bx.y - ax.y;  dz = bx.z - ax.z
        length_nm = _math.sqrt(dx*dx + dy*dy + dz*dz)
        if length_nm < 1e-9:
            ux = uy = 0.0; uz = 1.0
        else:
            ux = dx / length_nm;  uy = dy / length_nm;  uz = dz / length_nm

        helix_end_bp = helix.bp_start + helix.length_bp - 1   # last valid global bp

        if new_bp < helix.bp_start:
            # Grow backward (axis_start moves in -axis direction)
            extra = helix.bp_start - new_bp
            new_axis_start = Vec3(
                x=ax.x - extra * BDNA_RISE_PER_BP * ux,
                y=ax.y - extra * BDNA_RISE_PER_BP * uy,
                z=ax.z - extra * BDNA_RISE_PER_BP * uz,
            )
            corrected_phase = helix.phase_offset - extra * helix.twist_per_bp_rad
            helix = Helix(
                id=helix.id,
                axis_start=new_axis_start,
                axis_end=helix.axis_end,
                length_bp=helix.length_bp + extra,
                bp_start=new_bp,
                phase_offset=corrected_phase,
                twist_per_bp_rad=helix.twist_per_bp_rad,
                loop_skips=helix.loop_skips,
                direction=helix.direction,
            )
        elif new_bp > helix_end_bp:
            # Grow forward (axis_end moves in +axis direction)
            extra = new_bp - helix_end_bp
            new_axis_end = Vec3(
                x=bx.x + extra * BDNA_RISE_PER_BP * ux,
                y=bx.y + extra * BDNA_RISE_PER_BP * uy,
                z=bx.z + extra * BDNA_RISE_PER_BP * uz,
            )
            helix = Helix(
                id=helix.id,
                axis_start=helix.axis_start,
                axis_end=new_axis_end,
                length_bp=helix.length_bp + extra,
                bp_start=helix.bp_start,
                phase_offset=helix.phase_offset,
                twist_per_bp_rad=helix.twist_per_bp_rad,
                loop_skips=helix.loop_skips,
                direction=helix.direction,
            )

        strand = strand.model_copy(update={"domains": domains, "sequence": None})
        strands_by_id[strand.id] = strand
        helices_by_id[helix.id]  = helix
        modified.append((entry["strand_id"], end))

    # ── Trim helices whose strand coverage has shrunk ────────────────────────
    # The grow logic above only extends helix axes. If a terminal was dragged
    # inward (new_bp within the existing helix bounds), the axis endpoints must
    # be updated to match the new coverage — otherwise arrows and blunt-end
    # rings stay at the old positions.
    all_updated_strands = [strands_by_id.get(s.id, s) for s in design.strands]
    for h_id, helix in list(helices_by_id.items()):
        lo_bp: int | None = None
        hi_bp: int | None = None
        for s in all_updated_strands:
            for dom in s.domains:
                if dom.helix_id != h_id:
                    continue
                bp_lo = min(dom.start_bp, dom.end_bp)
                bp_hi = max(dom.start_bp, dom.end_bp)
                lo_bp = bp_lo if lo_bp is None else min(lo_bp, bp_lo)
                hi_bp = bp_hi if hi_bp is None else max(hi_bp, bp_hi)
        if lo_bp is None:
            continue
        old_lo = helix.bp_start
        old_hi = helix.bp_start + helix.length_bp - 1
        if lo_bp == old_lo and hi_bp == old_hi:
            continue  # dimensions unchanged (also covers the grow cases)
        ax, bx = helix.axis_start, helix.axis_end
        t0 = (lo_bp - old_lo) / helix.length_bp
        t1 = (hi_bp - old_lo + 1) / helix.length_bp
        def _t(a: float, b: float, t: float) -> float: return a + t * (b - a)
        helices_by_id[h_id] = helix.model_copy(update={
            "bp_start":     lo_bp,
            "length_bp":    hi_bp - lo_bp + 1,
            "axis_start":   Vec3(x=_t(ax.x, bx.x, t0), y=_t(ax.y, bx.y, t0), z=_t(ax.z, bx.z, t0)),
            "axis_end":     Vec3(x=_t(ax.x, bx.x, t1), y=_t(ax.y, bx.y, t1), z=_t(ax.z, bx.z, t1)),
            "phase_offset": helix.phase_offset + (lo_bp - old_lo) * helix.twist_per_bp_rad,
        })

    # ── Reconcile inline overhangs ────────────────────────────────────────────
    scaf_cov = _scaffold_coverage_by_helix(design)
    _reconcile_inline_overhangs(strands_by_id, overhangs_by_id, modified, scaf_cov)

    new_strands  = [strands_by_id.get(s.id, s) for s in design.strands]
    new_helices  = [helices_by_id.get(h.id, h) for h in design.helices]
    new_overhangs = list(overhangs_by_id.values())

    return design.model_copy(update={
        "strands":      new_strands,
        "helices":      new_helices,
        "overhangs":    new_overhangs,
        "deformations": design.deformations,
    })
