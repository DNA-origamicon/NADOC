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
from backend.core.models import Crossover, Design, DesignMetadata, Direction, Domain, DomainRef, HalfCrossover, Helix, LatticeType, OverhangSpec, Strand, StrandType, Vec3
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

    # For re-centered designs (e.g. imported scadnano/cadnano), existing helices may not
    # sit at _lattice_position(r, c, lt) exactly.  Derive the physical offset from the
    # first helix that carries grid_pos so new helices are placed at the correct position.
    _lattice_off_lx = 0.0
    _lattice_off_ly = 0.0
    for _h in existing_design.helices:
        if _h.grid_pos is not None:
            _r0, _c0 = _h.grid_pos
            _lx0, _ly0 = _lattice_position(_r0, _c0, lt)
            if plane == "XY":
                _lattice_off_lx = _h.axis_start.x - _lx0
                _lattice_off_ly = _h.axis_start.y - _ly0
            elif plane == "XZ":
                _lattice_off_lx = _h.axis_start.x - _lx0
                _lattice_off_ly = _h.axis_start.z - _ly0
            else:  # YZ
                _lattice_off_lx = _h.axis_start.y - _lx0
                _lattice_off_ly = _h.axis_start.z - _ly0
            break

    for row, col in cells:
        lx, ly = _lattice_position(row, col, lt)
        lx += _lattice_off_lx
        ly += _lattice_off_ly
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
            grid_pos=(row, col),
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

    # For re-centered designs (e.g. imported scadnano/cadnano), existing helices may not
    # sit at _lattice_position(r, c, lt) exactly.  Derive the physical offset from the
    # first helix that carries grid_pos so new helices are placed at the correct position.
    _lattice_off_lx = 0.0
    _lattice_off_ly = 0.0
    for _h in existing_design.helices:
        if _h.grid_pos is not None:
            _r0, _c0 = _h.grid_pos
            _lx0, _ly0 = _lattice_position(_r0, _c0, lt)
            if plane == "XY":
                _lattice_off_lx = _h.axis_start.x - _lx0
                _lattice_off_ly = _h.axis_start.y - _ly0
            elif plane == "XZ":
                _lattice_off_lx = _h.axis_start.x - _lx0
                _lattice_off_ly = _h.axis_start.z - _ly0
            else:  # YZ
                _lattice_off_lx = _h.axis_start.y - _lx0
                _lattice_off_ly = _h.axis_start.z - _ly0
            break

    for row, col in cells:
        lx, ly = _lattice_position(row, col, lt)
        lx += _lattice_off_lx
        ly += _lattice_off_ly
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
                grid_pos=(row, col),
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
        # Within-domain split.  Propagate overhang_id to the fragment that
        # remains at the strand terminal; the inner fragment becomes regular.
        ovhg = domain.overhang_id
        is_first_domain = (domain_idx == 0)
        # First domain → left_dom stays at 5' terminal → gets overhang_id.
        # Last domain  → right_dom stays at 3' terminal → gets overhang_id.
        # Mid-strand   → shouldn't have overhang_id; drop from both.
        left_ovhg  = ovhg if is_first_domain else None
        right_ovhg = ovhg if is_last_domain else None
        if direction == Direction.FORWARD:
            # FORWARD: 5′=start_bp (low), 3′=end_bp (high). Next bp after nick → bp_index+1.
            left_dom  = Domain(helix_id=helix_id, start_bp=domain.start_bp,
                               end_bp=bp_index, direction=direction,
                               overhang_id=left_ovhg)
            right_dom = Domain(helix_id=helix_id, start_bp=bp_index + 1,
                               end_bp=domain.end_bp, direction=direction,
                               overhang_id=right_ovhg)
        else:
            # REVERSE: 5′=start_bp (high), 3′=end_bp (low). Next bp after nick → bp_index-1.
            left_dom  = Domain(helix_id=helix_id, start_bp=domain.start_bp,
                               end_bp=bp_index, direction=direction,
                               overhang_id=left_ovhg)
            right_dom = Domain(helix_id=helix_id, start_bp=bp_index - 1,
                               end_bp=domain.end_bp, direction=direction,
                               overhang_id=right_ovhg)
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

    # OverhangSpecs: if any overhang domain ended up in the right fragment,
    # remap its OverhangSpec.strand_id to the right fragment's ID.
    right_ovhg_ids = {d.overhang_id for d in right_domains if d.overhang_id}
    new_overhangs = [
        o.model_copy(update={"strand_id": right_id})
        if o.strand_id == strand.id and o.id in right_ovhg_ids
        else o
        for o in existing_design.overhangs
    ]

    return existing_design.copy_with(
        strands=new_strands,
        extensions=new_extensions,
        overhangs=new_overhangs,
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
    # Remap OverhangSpecs from s2 → s1 (s2 is absorbed).
    new_overhangs = [
        o.model_copy(update={"strand_id": s1.id}) if o.strand_id == s2.id else o
        for o in design.overhangs
    ]
    return design.model_copy(update={
        "strands": new_strands,
        "extensions": new_extensions,
        "overhangs": new_overhangs,
    })


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
                    overhang_id=prev.overhang_id,
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

    Overhang handling:
    - Same overhang_id on both: preserved on merged domain.
    - Different (one overhang, one not): merged domain gets overhang_id=None
      and the orphaned OverhangSpec is removed.
    """
    dom_a = s1.domains[-1]
    dom_b = s2.domains[0]
    orphaned_ovhg_id: str | None = None  # OverhangSpec to remove if cross-type merge
    if dom_a.helix_id == dom_b.helix_id and dom_a.direction == dom_b.direction:
        if dom_a.overhang_id == dom_b.overhang_id:
            merged_ovhg = dom_a.overhang_id  # same tag (including None == None)
        else:
            # Cross-type merge: one overhang, one not → drop the tag
            orphaned_ovhg_id = dom_a.overhang_id or dom_b.overhang_id
            merged_ovhg = None
        merged_dom = Domain(
            helix_id=dom_a.helix_id,
            start_bp=dom_a.start_bp,
            end_bp=dom_b.end_bp,
            direction=dom_a.direction,
            overhang_id=merged_ovhg,
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
    # Remap surviving OverhangSpecs from s2 → s1; remove orphaned spec from
    # cross-type merge.
    new_overhangs = []
    for o in design.overhangs:
        if orphaned_ovhg_id is not None and o.id == orphaned_ovhg_id:
            continue  # drop orphaned spec
        if o.strand_id == s2.id:
            new_overhangs.append(o.model_copy(update={"strand_id": s1.id}))
        else:
            new_overhangs.append(o)
    return design.model_copy(update={
        "strands": new_strands,
        "extensions": new_extensions,
        "overhangs": new_overhangs,
    })


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

# ── Overhang extrusion ────────────────────────────────────────────────────────


def _sq_y_step_per_row(design: Design) -> float:
    """Return actual nm per NADOC row in the y-axis from existing helix positions.

    Native designs:   +SQUARE_ROW_PITCH  (y increases with row)
    Imported designs: −SQUARE_ROW_PITCH  (y negated at import time)
    Falls back to +SQUARE_ROW_PITCH when all helices share the same row.
    """
    ref_row: int | None = None
    ref_y: float | None = None
    for h in design.helices:
        if h.grid_pos is None:
            continue
        hr = h.grid_pos[0]
        if ref_row is None:
            ref_row = hr
            ref_y = h.axis_start.y
        elif hr != ref_row:
            return (h.axis_start.y - ref_y) / (hr - ref_row)
    return SQUARE_ROW_PITCH


def _overhang_neighbor_xy(
    parent_helix: Helix,
    neighbor_row: int,
    neighbor_col: int,
    design: Design,
) -> Tuple[float, float]:
    """Return (x, y) for the new overhang helix at (neighbor_row, neighbor_col).

    Uses the parent helix's actual axis position as a reference so that
    imported designs (where axes are shifted/negated vs. the lattice formula)
    place the overhang correctly adjacent to the parent.
    """
    if parent_helix.grid_pos is None:
        return _lattice_position(neighbor_row, neighbor_col, design.lattice_type)

    parent_row, parent_col = parent_helix.grid_pos
    dc = neighbor_col - parent_col
    dr = neighbor_row - parent_row

    if design.lattice_type == LatticeType.SQUARE:
        y_step = _sq_y_step_per_row(design)
        return (
            parent_helix.axis_start.x + dc * SQUARE_COL_PITCH,
            parent_helix.axis_start.y + dr * y_step,
        )
    # HC: formula relative offsets are correct for both native and imported.
    fpx, fpy = honeycomb_position(parent_row, parent_col)
    fnx, fny = honeycomb_position(neighbor_row, neighbor_col)
    return (
        parent_helix.axis_start.x + (fnx - fpx),
        parent_helix.axis_start.y + (fny - fpy),
    )


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
    nx, ny = _overhang_neighbor_xy(orig_helix, neighbor_row, neighbor_col, design)

    # ── New domain direction ─────────────────────────────────────────────────
    # For +Z overhangs the crossover is at local bp 0 (near-end):
    #   5′ nick → new domain 3′ end at near bp  → REVERSE
    #   3′ nick → new domain 5′ end at near bp  → FORWARD
    #
    # For −Z overhangs the axis is flipped to +Z so the domain extends
    # leftward in cadnano 2D.  The crossover is now at local bp L-1
    # (far-end), so the direction flips:
    #   5′ nick → FORWARD    3′ nick → REVERSE
    if overhang_z_dir >= 0:
        new_dir = Direction.REVERSE if is_five_prime else Direction.FORWARD
    else:
        new_dir = Direction.FORWARD if is_five_prime else Direction.REVERSE

    # ── Phase offset for new helix ───────────────────────────────────────────
    # local_orig_i already computed above for z_nick.
    theta   = orig_helix.phase_offset + local_orig_i * orig_helix.twist_per_bp_rad
    if overhang_z_dir >= 0:
        phase_new = (math.pi + theta) % (2 * math.pi)
    else:
        # Axis flipped to +Z — junction at local bp (L-1) instead of 0.
        # Phase must account for the (L-1) twist steps from axis_start to
        # the junction point so the nucleotide aligns with the parent.
        phase_new = (math.pi + theta - (length_bp - 1) * orig_helix.twist_per_bp_rad) % (2 * math.pi)

    # ── Check for existing overhang helix at this grid position ────────────
    # If a previous extrusion already created an overhang helix at
    # (neighbor_row, neighbor_col), reuse it — extend its bp range to cover
    # the new domain.  This ensures both overhangs share one helix row in
    # the cadnano 2D path view.
    ovhg_helix_ids = {o.helix_id for o in design.overhangs}
    reuse_helix: Helix | None = None
    for h in design.helices:
        if (h.grid_pos is not None
                and tuple(h.grid_pos) == (neighbor_row, neighbor_col)
                and h.id in ovhg_helix_ids):
            reuse_helix = h
            break

    # ── Domain bp range for this overhang ────────────────────────────────────
    # +Z overhang: bp_start = bp_index, domain spans bp_index … bp_index+L-1
    # −Z overhang: bp_start = bp_index-L+1, domain spans bp_index-L+1 … bp_index
    if overhang_z_dir >= 0:
        new_bp_start = bp_index
    else:
        new_bp_start = bp_index - length_bp + 1
    new_bp_end = new_bp_start + length_bp - 1

    if reuse_helix is not None:
        # ── Reuse existing overhang helix — extend to cover new domain ───
        new_helix_id = reuse_helix.id
        ex_lo = reuse_helix.bp_start
        ex_hi = reuse_helix.bp_start + reuse_helix.length_bp - 1
        union_lo = min(ex_lo, new_bp_start)
        union_hi = max(ex_hi, new_bp_end)

        # Axis extends in +Z.  Grow backward (lower Z) or forward (higher Z).
        backward = ex_lo - union_lo   # ≥ 0
        forward  = union_hi - ex_hi   # ≥ 0
        ext_axis_start_z = reuse_helix.axis_start.z - backward * BDNA_RISE_PER_BP
        ext_axis_end_z   = reuse_helix.axis_end.z   + forward  * BDNA_RISE_PER_BP
        # When axis_start moves backward, phase must shift so existing
        # nucleotide positions stay in place.
        ext_phase = reuse_helix.phase_offset - backward * reuse_helix.twist_per_bp_rad

        new_helix = Helix(
            id           = reuse_helix.id,
            grid_pos     = list(reuse_helix.grid_pos),
            axis_start   = Vec3(x=reuse_helix.axis_start.x, y=reuse_helix.axis_start.y, z=ext_axis_start_z),
            axis_end     = Vec3(x=reuse_helix.axis_end.x,   y=reuse_helix.axis_end.y,   z=ext_axis_end_z),
            bp_start     = union_lo,
            phase_offset = ext_phase,
            length_bp    = union_hi - union_lo + 1,
            direction    = reuse_helix.direction,
            twist_per_bp_rad = reuse_helix.twist_per_bp_rad,
            loop_skips   = list(reuse_helix.loop_skips),
        )
        # Replace the existing helix in the list (don't append a duplicate)
        new_helices_list: list[Helix] = [new_helix if h.id == reuse_helix.id else h for h in design.helices]
    else:
        # ── New helix ID (collision-safe) ────────────────────────────────────
        existing_ids = {h.id for h in design.helices}
        base_id      = f"h_XY_{neighbor_row}_{neighbor_col}"
        new_helix_id = base_id
        if new_helix_id in existing_ids:
            i = 1
            while f"{base_id}_{i}" in existing_ids:
                i += 1
            new_helix_id = f"{base_id}_{i}"

        # ── Axis + bp_start ─────────────────────────────────────────────────
        # +Z overhang: axis_start at z_nick, extends toward higher Z.
        #   bp_start = bp_index → junction at local bp 0.
        # −Z overhang: axis flipped to +Z so domain extends leftward in 2D.
        #   axis_start at the far (low-Z) end, bp_start = bp_index - L + 1
        #   → junction at local bp L-1 which maps to global bp_index.
        if overhang_z_dir >= 0:
            new_axis_start = Vec3(x=nx, y=ny, z=z_nick)
            new_axis_end   = Vec3(x=nx, y=ny, z=z_nick + length_nm)
        else:
            new_axis_start = Vec3(x=nx, y=ny, z=z_nick - (length_bp - 1) * BDNA_RISE_PER_BP)
            new_axis_end   = Vec3(x=nx, y=ny, z=z_nick + BDNA_RISE_PER_BP)

        new_helix = Helix(
            id           = new_helix_id,
            grid_pos     = [neighbor_row, neighbor_col],
            axis_start   = new_axis_start,
            axis_end     = new_axis_end,
            bp_start     = new_bp_start,
            phase_offset = phase_new,
            length_bp    = length_bp,
            direction    = new_dir,
        )
        new_helices_list = list(design.helices) + [new_helix]

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

    # ─��� OverhangSpec ─────────────────────────────────────────────────────────
    # Pivot = axis-point at the junction (nx, ny, z_nick), independent of ±Z direction.
    junction_pivot = [float(nx), float(ny), float(z_nick)]
    overhang_spec = OverhangSpec(
        id        = overhang_id,
        helix_id  = new_helix_id,
        strand_id = strand.id,
        pivot     = junction_pivot,
    )
    # Replace any existing spec with the same id (idempotent re-extrude)
    existing_overhangs = [o for o in design.overhangs if o.id != overhang_id]
    new_overhangs = existing_overhangs + [overhang_spec]

    # ── Register crossover between parent and overhang helix ────────────────
    # The junction is at global bp_index on both helices.  For +Z overhangs
    # that's local bp 0; for −Z (axis-flipped) it's local bp L-1.
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

    new_strands = [new_strand if s.id == strand.id else s for s in design.strands]

    # ── Add new helix + domain to the same cluster as the parent helix ─────
    # For domain-level clusters (domain_ids non-empty), also register the new
    # domain so the cluster's rigid transform applies to the overhang
    # nucleotides.  When prepending a domain (5' nick), existing DomainRef
    # indices for the same strand must shift +1 in ALL clusters.
    new_domain_index = 0 if is_five_prime else len(strand.domains)  # index in the *new* domain list
    new_cluster_transforms = list(design.cluster_transforms)

    # Step 1: if prepending, shift existing DomainRefs for this strand in all clusters
    if is_five_prime:
        for i, ct in enumerate(new_cluster_transforms):
            if not ct.domain_ids:
                continue
            shifted = False
            updated_refs = []
            for dr in ct.domain_ids:
                if dr.strand_id == strand.id:
                    updated_refs.append(DomainRef(strand_id=dr.strand_id, domain_index=dr.domain_index + 1))
                    shifted = True
                else:
                    updated_refs.append(dr)
            if shifted:
                new_cluster_transforms[i] = ct.model_copy(update={"domain_ids": updated_refs})

    # Step 2: add new helix (and domain, for domain-level clusters) to parent's cluster.
    # When reusing an existing overhang helix, it may already be in the cluster —
    # in that case only add the new domain, not the helix.
    for i, ct in enumerate(new_cluster_transforms):
        if helix_id in ct.helix_ids:
            updates: dict = {}
            if new_helix_id not in ct.helix_ids:
                updates["helix_ids"] = list(ct.helix_ids) + [new_helix_id]
            if ct.domain_ids:
                updates["domain_ids"] = list(ct.domain_ids) + [
                    DomainRef(strand_id=strand.id, domain_index=new_domain_index)
                ]
            if updates:
                new_cluster_transforms[i] = ct.model_copy(update=updates)
            break

    return design.model_copy(update={
        "helices":            new_helices_list,
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
    helices_by_id: dict | None = None,
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
        # Match any ovhg_inline_ tag, not just the one for the current strand.
        # After ligation, a terminal domain may carry a stale tag from a
        # different strand that was merged into this one.
        existing_tag = term_dom.overhang_id
        is_stale_inline = (existing_tag is not None
                           and existing_tag.startswith(_INLINE))
        existing_spec = overhangs_by_id.get(existing_tag if is_stale_inline else ovhg_id)
        if is_stale_inline:
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
            overhangs_by_id.pop(existing_tag, None)
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
            # Junction bp = the scaffold boundary where the split occurred.
            junction_bp = (
                scaf_lo if (is_5p and is_fwd) or (not is_5p and not is_fwd) else scaf_hi
            )
            pivot_xyz = (
                _pivot_for_junction(helices_by_id, helix_id, junction_bp)
                if helices_by_id else [0.0, 0.0, 0.0]
            )
            overhangs_by_id[ovhg_id] = OverhangSpec(
                id=ovhg_id,
                helix_id=helix_id,
                strand_id=strand_id,
                sequence=existing_spec.sequence if existing_spec else None,
                label=existing_spec.label    if existing_spec else None,
                rotation=existing_spec.rotation if existing_spec else [0.0, 0.0, 0.0, 1.0],
                pivot=pivot_xyz,
            )

        strands_by_id[strand_id] = strand.model_copy(update={"domains": domains})


def _pivot_for_junction(helices_by_id: dict, helix_id: str, bp: int) -> list[float]:
    """Helix axis position at *bp* as [x, y, z] nm — stored as OverhangSpec.pivot."""
    h = helices_by_id.get(helix_id)
    if h is None:
        return [0.0, 0.0, 0.0]
    ax, ae = h.axis_start, h.axis_end
    dx = ae.x - ax.x; dy = ae.y - ax.y; dz = ae.z - ax.z
    axis_nm = (dx * dx + dy * dy + dz * dz) ** 0.5
    phys_len = max(1, round(axis_nm / BDNA_RISE_PER_BP) + 1)
    t = (bp - h.bp_start) / max(phys_len - 1, 1)
    t = max(0.0, min(1.0, t))
    return [ax.x + t * dx, ax.y + t * dy, ax.z + t * dz]


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
    helices_by_id: dict[str, Helix] = {h.id: h for h in design.helices}
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

            # Pivot = helix axis position at the crossover junction on the adjacent
            # (main-bundle) domain.  For 3' end: junction is adjacent.end_bp.
            # For 5' end: junction is adjacent.start_bp.
            adj_dom  = domains[term_idx - 1] if end == "3p" else domains[term_idx + 1]
            junc_bp  = adj_dom.end_bp if end == "3p" else adj_dom.start_bp
            pivot_xyz = _pivot_for_junction(helices_by_id, adj_dom.helix_id, junc_bp)

            ovhg_id = f"{_INLINE}{strand.id}_{end}"
            domains[term_idx] = term_dom.model_copy(update={"overhang_id": ovhg_id})
            overhangs_by_id[ovhg_id] = OverhangSpec(
                id=ovhg_id,
                helix_id=term_dom.helix_id,
                strand_id=strand.id,
                pivot=pivot_xyz,
            )
            changed = True

        if changed:
            strands_by_id[strand.id] = strand.model_copy(update={"domains": domains})

    return design.copy_with(
        strands=[strands_by_id[s.id] for s in design.strands],
        overhangs=list(overhangs_by_id.values()),
    )


def reconcile_all_inline_overhangs(design: Design) -> Design:
    """Re-evaluate all inline overhang splits against current scaffold coverage.

    Merges stale inline splits where scaffold now covers the domain, and
    re-splits where domains still extend beyond scaffold boundaries.

    Call this after any operation that changes scaffold coverage (routing,
    partitioning, scaffold split, etc.) and on ``.nadoc`` load to clean up
    stale overhang tags saved from a previous session.
    """
    helices_by_id2: dict[str, Helix]        = {h.id: h for h in design.helices}
    strands_by_id:  dict[str, Strand]       = {s.id: s for s in design.strands}
    overhangs_by_id: dict[str, OverhangSpec] = {o.id: o for o in design.overhangs}
    scaf_cov = _scaffold_coverage_by_helix(design)

    all_modified: list[tuple[str, str]] = [
        (s.id, end)
        for s in design.strands
        if s.strand_type == StrandType.STAPLE
        for end in ("5p", "3p")
    ]
    _reconcile_inline_overhangs(strands_by_id, overhangs_by_id, all_modified, scaf_cov, helices_by_id2)

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
        (``reconcile_all_inline_overhangs``):
        A staple terminal domain shares a helix with the scaffold but its bp
        range extends *beyond* the scaffold coverage boundary.  ``autodetect_overhangs``
        explicitly skips these (``if term_dom.helix_id in scaf_cov: continue``) and
        defers to ``reconcile_all_inline_overhangs``, which merges stale splits and
        re-evaluates all staple ends against current scaffold coverage.

    This function is idempotent: already-tagged domains (``overhang_id`` set) are
    left unchanged by both passes.
    """
    # Pass 1: scaffold-free helix overhangs
    design = autodetect_overhangs(design)

    # Pass 2: domains that extend beyond scaffold boundary on scaffold-covered helices
    design = reconcile_all_inline_overhangs(design)

    # Assign default labels OH1, OH2, … to any overhang that has no label yet.
    # Sort by id for deterministic ordering across runs.
    overhangs_by_id: dict[str, OverhangSpec] = {o.id: o for o in design.overhangs}
    oh_counter = 1
    for ovhg_id in sorted(overhangs_by_id):
        ovhg = overhangs_by_id[ovhg_id]
        if not ovhg.label:
            overhangs_by_id[ovhg_id] = ovhg.model_copy(update={"label": f"OH{oh_counter}"})
        oh_counter += 1

    return design.copy_with(
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
    _reconcile_inline_overhangs(strands_by_id, overhangs_by_id, modified, scaf_cov, helices_by_id)

    new_strands  = [strands_by_id.get(s.id, s) for s in design.strands]
    new_helices  = [helices_by_id.get(h.id, h) for h in design.helices]
    new_overhangs = list(overhangs_by_id.values())

    return design.model_copy(update={
        "strands":      new_strands,
        "helices":      new_helices,
        "overhangs":    new_overhangs,
        "deformations": design.deformations,
    })
