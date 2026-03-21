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

import numpy as np

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_LATTICE_RADIUS,
    HONEYCOMB_ROW_PITCH,
    SQUARE_COL_PITCH,
    SQUARE_CROSSOVER_PERIOD,
    SQUARE_ROW_PITCH,
    SQUARE_TWIST_PER_BP_RAD,
)
from backend.core.crossover_positions import valid_crossover_positions
from backend.core.models import Design, DesignMetadata, Direction, Domain, Helix, LatticeType, OverhangSpec, Strand, StrandType, Vec3


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


# ── Square lattice helpers ────────────────────────────────────────────────────


def square_cell_direction(row: int, col: int) -> Direction:
    """Return the scaffold direction for a square lattice cell.

    Rule: (row + col) % 2 == 0 → FORWARD, else REVERSE.
    All cells are valid; this guarantees every adjacent pair is antiparallel.
    """
    return Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE


def square_position(row: int, col: int) -> Tuple[float, float]:
    """Return the XY centre of helix (row, col) on a 2.6 nm square grid.

    No stagger — both row and column indices map directly to a uniform grid.
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

    FORWARD helix: phase_offset = 322.2°.
    REVERSE helix: phase_offset = 252.2°.
    """
    if lattice_type == LatticeType.SQUARE:
        return math.radians(345.0) if direction == Direction.FORWARD else math.radians(285.0)
    return math.radians(322.2) if direction == Direction.FORWARD else math.radians(252.2)


def _lattice_twist(lattice_type: "LatticeType") -> float:  # type: ignore[name-defined]
    """Return twist_per_bp_rad for the given lattice type."""
    if lattice_type == LatticeType.SQUARE:
        return SQUARE_TWIST_PER_BP_RAD
    return BDNA_TWIST_PER_BP_RAD


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
    if lattice_type == LatticeType.HONEYCOMB:
        invalid = [(r, c) for r, c in cells if not is_valid_honeycomb_cell(r, c)]
        if invalid:
            raise ValueError(f"Cells are not valid honeycomb positions: {invalid}")
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

        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            phase_offset=phase_offset,
            twist_per_bp_rad=twist,
        )
        helices.append(helix)

        # Convention: start_bp = 5′ end, end_bp = 3′ end (regardless of direction).
        if direction == Direction.FORWARD:
            scaf_start, scaf_end = 0, actual_length - 1
        else:
            scaf_start, scaf_end = actual_length - 1, 0

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
                stpl_start, stpl_end = 0, actual_length - 1
            else:
                stpl_start, stpl_end = actual_length - 1, 0

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
    """Return *base* if not in *existing*, else *base_1*, *base_2*, …"""
    if base not in existing:
        return base
    i = 1
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
    if lt == LatticeType.HONEYCOMB:
        invalid = [(r, c) for r, c in cells if not is_valid_honeycomb_cell(r, c)]
        if invalid:
            raise ValueError(f"Cells are not valid honeycomb positions: {invalid}")
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

        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            phase_offset=phase_offset,
            twist_per_bp_rad=twist,
        )
        new_helices.append(helix)

        if direction == Direction.FORWARD:
            scaf_start, scaf_end = 0, actual_length - 1
        else:
            scaf_start, scaf_end = actual_length - 1, 0

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
                stpl_start, stpl_end = 0, actual_length - 1
            else:
                stpl_start, stpl_end = actual_length - 1, 0

            new_strands.append(Strand(
                id=stpl_id,
                domains=[Domain(helix_id=helix_id, start_bp=stpl_start, end_bp=stpl_end, direction=staple_dir)],
                strand_type=StrandType.STAPLE,
            ))

    return Design(
        metadata=existing_design.metadata,
        lattice_type=existing_design.lattice_type,
        helices=existing_design.helices + new_helices,
        strands=existing_design.strands + new_strands,
        crossovers=existing_design.crossovers,
        deformations=existing_design.deformations,
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
    if lt == LatticeType.HONEYCOMB:
        invalid = [(r, c) for r, c in cells if not is_valid_honeycomb_cell(r, c)]
        if invalid:
            raise ValueError(f"Cells are not valid honeycomb positions: {invalid}")
    valid_planes = {"XY", "XZ", "YZ"}
    if plane not in valid_planes:
        raise ValueError(f"plane must be one of {sorted(valid_planes)}, got {plane!r}")

    existing_helix_ids:  set = {h.id for h in existing_design.helices}
    existing_strand_ids: set = {s.id for s in existing_design.strands}

    actual_length_nm = actual_length * BDNA_RISE_PER_BP   # always positive
    new_helices:       List[Helix]  = []
    new_strands:       List[Strand] = []   # strands for fresh (non-continuation) cells
    # strand_id → {'prepend': [Domain, ...], 'append': [Domain, ...]}
    domain_additions:  dict         = {}
    # helix_id → replacement Helix (backward extension keeps the same ID, grows axis_start)
    helix_replacements: dict[str, "Helix"] = {}
    # helix_id → bp shift applied to all existing domains on that helix
    domain_shifts:     dict[str, int]      = {}

    for row, col in cells:
        lx, ly = _lattice_position(row, col, lt)
        base_hid = f"h_{plane}_{row}_{col}"

        all_helix_ids  = existing_helix_ids  | {h.id for h in new_helices}
        all_strand_ids = existing_strand_ids | {s.id for s in new_strands}

        direction    = _lattice_direction(row, col, lt)
        phase_offset = _lattice_phase_offset(direction, lt)

        cont_helix = _find_continuation_helix(existing_design.helices, row, col, plane, offset_nm)

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
            # increase length_bp.  All existing bp indices on cont_helix shift by
            # +actual_length so that the new backward bps occupy 0..actual_length-1,
            # keeping the numbering continuous across the junction.  Phase continuity
            # is guaranteed because phase_offset (the angle at bp 0) is inherited from
            # the existing helix — the geometry formula naturally produces the correct
            # twist at every bp in the extended helix.
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

            # Shifting all existing bp indices by +actual_length changes their
            # rotational angles by +actual_length × twist.  Subtract that same
            # offset from phase_offset so that every original bp retains its
            # absolute angle at its physical Z position.
            corrected_phase = (
                cont_helix.phase_offset - actual_length * cont_helix.twist_per_bp_rad
            )
            extended_helix = Helix(
                id=cont_helix.id,
                axis_start=new_axis_start,
                axis_end=cont_helix.axis_end,
                length_bp=cont_helix.length_bp + actual_length,
                phase_offset=corrected_phase,
                twist_per_bp_rad=cont_helix.twist_per_bp_rad,
                loop_skips=[
                    ls.model_copy(update={"bp_index": ls.bp_index + actual_length})
                    for ls in cont_helix.loop_skips
                ],
            )
            helix_replacements[cont_helix.id] = extended_helix
            domain_shifts[cont_helix.id]      = actual_length
            helix_id = cont_helix.id

            # Add domains covering the new backward bps (0..actual_length-1).
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
                                helix_id=helix_id, start_bp=0,
                                end_bp=actual_length - 1, direction=d)
                            should_prepend = True   # FORWARD: new bps precede shifted existing
                        else:
                            new_dom = Domain(
                                helix_id=helix_id, start_bp=actual_length - 1,
                                end_bp=0, direction=d)
                            should_prepend = False  # REVERSE: new bps follow shifted existing
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
            # Existing bp indices are unchanged (new bps occupy N..N+ext-1).
            # For FORWARD strands: append a new domain [N, N+ext-1].
            # For REVERSE strands: prepend a new domain [N+ext-1, N] (5'→3' = high→low).
            old_length = cont_helix.length_bp
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
                phase_offset=cont_helix.phase_offset,
                twist_per_bp_rad=cont_helix.twist_per_bp_rad,
                loop_skips=cont_helix.loop_skips,
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
                            # New far bps: start=old_length(5'), end=old_length+ext-1(3')
                            new_dom = Domain(
                                helix_id=helix_id,
                                start_bp=old_length,
                                end_bp=old_length + actual_length - 1,
                                direction=d)
                            entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                            entry["append"].append(new_dom)
                        else:
                            # REVERSE: far end is 5' (high bp). New bps: start=old_length+ext-1(5'), end=old_length(3')
                            new_dom = Domain(
                                helix_id=helix_id,
                                start_bp=old_length + actual_length - 1,
                                end_bp=old_length,
                                direction=d)
                            entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                            entry["prepend"].append(new_dom)
                        seen_strand_ids.add(strand.id)
                        break

        else:
            # ── Forward continuation OR fresh cell: create a new helix ──
            helix_id = _unique_id(base_hid, all_helix_ids)

            if plane == "XY":
                axis_start = Vec3(x=lx, y=ly, z=offset_nm)
                axis_end   = Vec3(x=lx, y=ly, z=offset_nm + actual_length_nm)
            elif plane == "XZ":
                axis_start = Vec3(x=lx, y=offset_nm,                   z=ly)
                axis_end   = Vec3(x=lx, y=offset_nm + actual_length_nm, z=ly)
            else:  # YZ
                axis_start = Vec3(x=offset_nm,                   y=lx, z=ly)
                axis_end   = Vec3(x=offset_nm + actual_length_nm, y=lx, z=ly)

            helix = Helix(
                id=helix_id,
                axis_start=axis_start,
                axis_end=axis_end,
                length_bp=actual_length,
                phase_offset=phase_offset,
                twist_per_bp_rad=_lattice_twist(lt),
            )
            new_helices.append(helix)

            if cont_helix is not None:
                # Forward continuation: extend each matching strand.
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
                                    helix_id=helix_id, start_bp=0,
                                    end_bp=actual_length - 1, direction=d)
                                # FORWARD at axis_end → append; at axis_start → prepend
                                should_prepend = not is_end_at_offset
                            else:
                                new_dom = Domain(
                                    helix_id=helix_id, start_bp=actual_length - 1,
                                    end_bp=0, direction=d)
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
                # Fresh cell: new scaffold + staple strands.
                include_scaffold = strand_filter in ("both", "scaffold")
                include_staples  = strand_filter in ("both", "staples")
                base_sid = f"scaf_{plane}_{row}_{col}"
                base_tid = f"stpl_{plane}_{row}_{col}"
                scaf_id  = _unique_id(base_sid, all_strand_ids)
                stpl_id  = _unique_id(base_tid, all_strand_ids | {scaf_id})

                if direction == Direction.FORWARD:
                    scaf_start, scaf_end = 0, actual_length - 1
                else:
                    scaf_start, scaf_end = actual_length - 1, 0

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
                        stpl_start, stpl_end = 0, actual_length - 1
                    else:
                        stpl_start, stpl_end = actual_length - 1, 0

                    new_strands.append(Strand(
                        id=stpl_id,
                        domains=[Domain(helix_id=helix_id, start_bp=stpl_start,
                                        end_bp=stpl_end, direction=staple_dir)],
                        strand_type=StrandType.STAPLE,
                    ))

    # Rebuild existing strands: first apply bp shifts for backward-extended helices,
    # then apply prepend/append domain additions.
    updated_strands: List[Strand] = []
    for strand in existing_design.strands:
        updated = strand
        if domain_shifts and any(d.helix_id in domain_shifts for d in strand.domains):
            shifted_domains = [
                d.model_copy(update={
                    "start_bp": d.start_bp + domain_shifts[d.helix_id],
                    "end_bp":   d.end_bp   + domain_shifts[d.helix_id],
                }) if d.helix_id in domain_shifts else d
                for d in strand.domains
            ]
            updated = strand.model_copy(update={"domains": shifted_domains})
        if strand.id in domain_additions:
            entry = domain_additions[strand.id]
            updated = updated.model_copy(update={
                "domains": entry["prepend"] + updated.domains + entry["append"]
            })
        updated_strands.append(updated)

    # Shift crossover bp indices for backward-extended helices.
    if domain_shifts:
        updated_crossovers = [
            xover.model_copy(update={
                "bp_a": xover.bp_a + domain_shifts.get(xover.helix_a, 0),
                "bp_b": xover.bp_b + domain_shifts.get(xover.helix_b, 0),
            }) if (xover.helix_a in domain_shifts or xover.helix_b in domain_shifts)
            else xover
            for xover in existing_design.crossovers
        ]
    else:
        updated_crossovers = existing_design.crossovers

    # Replace backward-extended helices in-place; append any new forward helices.
    final_helices = [
        helix_replacements.get(h.id, h) for h in existing_design.helices
    ] + new_helices

    return Design(
        metadata=existing_design.metadata,
        lattice_type=existing_design.lattice_type,
        helices=final_helices,
        strands=updated_strands + new_strands,
        crossovers=updated_crossovers,
        deformations=existing_design.deformations,
    )


def make_bundle_deformed_continuation(
    existing_design: Design,
    cells: List[Tuple[int, int]],
    length_bp: int,
    frame: dict,
    deformed_endpoints: dict,
    plane: str = "XY",
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
    invalid = [(r, c) for r, c in cells if not is_valid_honeycomb_cell(r, c)]
    if invalid:
        raise ValueError(f"Cells are not valid honeycomb positions: {invalid}")

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

        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            phase_offset=phase_offset,
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
            seen_strand_ids: set = set()
            for strand in existing_design.strands:
                if strand.id in seen_strand_ids:
                    continue
                for domain in strand.domains:
                    if domain.helix_id == cont_helix.id:
                        d = domain.direction
                        if d == Direction.FORWARD:
                            new_dom = Domain(helix_id=helix_id, start_bp=0,
                                             end_bp=actual_length - 1, direction=d)
                            should_prepend = not is_end_at_offset
                        else:
                            new_dom = Domain(helix_id=helix_id, start_bp=actual_length - 1,
                                             end_bp=0, direction=d)
                            should_prepend = is_end_at_offset
                        entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                        if should_prepend:
                            entry["prepend"].append(new_dom)
                        else:
                            entry["append"].append(new_dom)
                        seen_strand_ids.add(strand.id)
                        break
        else:
            # Fresh cell: new scaffold + staple strands
            base_sid = f"scaf_{plane}_{row}_{col}"
            base_tid = f"stpl_{plane}_{row}_{col}"
            scaf_id  = _unique_id(base_sid, all_strand_ids)
            stpl_id  = _unique_id(base_tid, all_strand_ids | {scaf_id})

            if direction == Direction.FORWARD:
                scaf_start, scaf_end = 0, actual_length - 1
            else:
                scaf_start, scaf_end = actual_length - 1, 0

            new_strands.append(Strand(
                id=scaf_id,
                domains=[Domain(helix_id=helix_id, start_bp=scaf_start,
                                end_bp=scaf_end, direction=direction)],
                strand_type=StrandType.SCAFFOLD,
            ))

            staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
            if staple_dir == Direction.FORWARD:
                stpl_start, stpl_end = 0, actual_length - 1
            else:
                stpl_start, stpl_end = actual_length - 1, 0

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

    return Design(
        metadata=existing_design.metadata,
        lattice_type=existing_design.lattice_type,
        helices=existing_design.helices + new_helices,
        strands=updated_strands + new_strands,
        crossovers=existing_design.crossovers,
        deformations=existing_design.deformations,
    )


# ── Staple crossover topology operation ───────────────────────────────────────


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


def make_staple_crossover(
    existing_design: Design,
    helix_a_id: str,
    bp_a: int,
    direction_a: Direction,
    helix_b_id: str,
    bp_b: int,
    direction_b: Direction,
    allow_scaffold: bool = False,
) -> Design:
    """Perform a staple-strand crossover and return the updated Design.

    The crossover junction connects bp_a on helix_a (strand direction_a) to
    bp_b on helix_b (strand direction_b).  The backbone path becomes:

        … → bp_a [jump] → bp_b → …

    This splits the strand on helix_a at bp_a and the strand on helix_b at bp_b,
    then reconnects them so that:

        New strand 1: [helix_a 5′ … bp_a] + [helix_b bp_b … 3′]
        New strand 2: [helix_b 5′ … (bp_b-1 or bp_b+1)] + [helix_a (next after bp_a) … 3′]

    "Next after bp_a" in 5′→3′ direction means bp_a+1 for FORWARD or bp_a-1 for REVERSE.
    A piece that has no nucleotides (crossover at the 3′ end of a domain, or 5′ end of
    the other) is simply omitted from the reconnected strand.

    Raises ValueError if:
    - Either strand is a scaffold strand
    - Both positions are on the same strand AND domain_a precedes domain_b in 5′→3′
      order with the later domain having a lower domain index (pseudoknot case)
    - No strand covers one of the specified positions
    """
    strand_a, domain_a_idx = _find_strand_at(existing_design, helix_a_id, bp_a, direction_a)
    strand_b, domain_b_idx = _find_strand_at(existing_design, helix_b_id, bp_b, direction_b)

    if (strand_a.strand_type == StrandType.SCAFFOLD or strand_b.strand_type == StrandType.SCAFFOLD) and not allow_scaffold:
        raise ValueError("make_staple_crossover cannot operate on scaffold strands.")

    d_a = strand_a.domains[domain_a_idx]
    d_b = strand_b.domains[domain_b_idx]

    # ── Split domain A at bp_a ─────────────────────────────────────────────────
    # a_left  = 5′ piece of A up to and including bp_a (3′ end = bp_a)
    # a_right = 3′ piece of A starting AFTER bp_a (may be None if bp_a is A's 3′ end)
    a_left = Domain(helix_id=helix_a_id, start_bp=d_a.start_bp, end_bp=bp_a, direction=direction_a)

    if direction_a == Direction.FORWARD:
        # FORWARD: 5′=start_bp (LOW), 3′=end_bp (HIGH). After bp_a → bp_a+1.
        a_right_5p = bp_a + 1
        a_right = (
            Domain(helix_id=helix_a_id, start_bp=a_right_5p, end_bp=d_a.end_bp, direction=direction_a)
            if a_right_5p <= d_a.end_bp else None
        )
    else:
        # REVERSE: 5′=start_bp (HIGH), 3′=end_bp (LOW). After bp_a → bp_a-1.
        a_right_5p = bp_a - 1
        a_right = (
            Domain(helix_id=helix_a_id, start_bp=a_right_5p, end_bp=d_a.end_bp, direction=direction_a)
            if a_right_5p >= d_a.end_bp else None
        )

    # ── Split domain B at bp_b ─────────────────────────────────────────────────
    # b_right = 3′ piece of B starting at bp_b (5′ end = bp_b) — always non-empty
    # b_left  = 5′ piece of B up to the nucleotide BEFORE bp_b (may be None if bp_b is B's 5′ end)
    b_right = Domain(helix_id=helix_b_id, start_bp=bp_b, end_bp=d_b.end_bp, direction=direction_b)

    if direction_b == Direction.FORWARD:
        # FORWARD: before bp_b → bp_b-1.
        b_left_3p = bp_b - 1
        b_left = (
            Domain(helix_id=helix_b_id, start_bp=d_b.start_bp, end_bp=b_left_3p, direction=direction_b)
            if b_left_3p >= d_b.start_bp else None
        )
    else:
        # REVERSE: before bp_b → bp_b+1 (going from HIGH toward LOW; bp_b+1 comes before bp_b).
        b_left_3p = bp_b + 1
        b_left = (
            Domain(helix_id=helix_b_id, start_bp=d_b.start_bp, end_bp=b_left_3p, direction=direction_b)
            if b_left_3p <= d_b.start_bp else None
        )

    # ── Same-strand case ───────────────────────────────────────────────────────
    # Both positions are on the same strand (common after a previous crossover
    # merged two staple strands into one spanning both helices).  Split the
    # single strand at two internal points to produce two new strands:
    #
    #   Outer: 5′-end … a_left → b_right … 3′-end
    #   Inner: a_right → [middle domains] → b_left
    #
    if strand_a.id == strand_b.id:
        ai, bi = domain_a_idx, domain_b_idx
        if ai == bi:
            raise ValueError(
                f"same strand crossover with domain_a_idx==domain_b_idx={ai}; "
                "both positions are in the same domain (pseudoknot)."
            )

        # Normalise so that ai < bi (a-cut comes first in 5'→3' order).
        if ai > bi:
            ai, bi = bi, ai
            a_left, a_right, b_left, b_right = b_left, b_right, a_left, a_right

        strand = strand_a

        outer_middle: List[Domain] = [d for d in [a_left, b_right] if d is not None]
        outer_domains: List[Domain] = (
            list(strand.domains[:ai])
            + outer_middle
            + list(strand.domains[bi + 1:])
        )

        inner_domains: List[Domain] = []
        if a_right is not None:
            inner_domains.append(a_right)
        inner_domains.extend(strand.domains[ai + 1:bi])
        if b_left is not None:
            inner_domains.append(b_left)

        existing_ids = {s.id for s in existing_design.strands}
        new_strands_same: List[Strand] = []
        for s in existing_design.strands:
            if s.id == strand.id:
                if outer_domains:
                    new_outer = strand.model_copy(deep=True)
                    new_outer.domains = outer_domains
                    new_strands_same.append(new_outer)
                if inner_domains:
                    inner_strand = Strand(
                        id=_unique_id(f"{strand.id}_x{bp_a}", existing_ids),
                        domains=inner_domains,
                        strand_type=StrandType.STAPLE,
                    )
                    new_strands_same.append(inner_strand)
            else:
                new_strands_same.append(s)

        return Design(
            metadata=existing_design.metadata,
            lattice_type=existing_design.lattice_type,
            helices=existing_design.helices,
            strands=new_strands_same,
            crossovers=existing_design.crossovers,
            deformations=existing_design.deformations,
        )

    # ── Two-strand reconnect ───────────────────────────────────────────────────
    # Strand 1: A's domains before d_a + [a_left, b_right] + B's domains after d_b
    strand1_domains: List[Domain] = (
        list(strand_a.domains[:domain_a_idx])
        + [a_left, b_right]
        + list(strand_b.domains[domain_b_idx + 1:])
    )

    # Strand 2: B's domains before d_b + [b_left? a_right?] + A's domains after d_a
    strand2_middle: List[Domain] = []
    if b_left is not None:
        strand2_middle.append(b_left)
    if a_right is not None:
        strand2_middle.append(a_right)

    strand2_domains: List[Domain] = (
        list(strand_b.domains[:domain_b_idx])
        + strand2_middle
        + list(strand_a.domains[domain_a_idx + 1:])
    )

    # Build new strand objects (reuse IDs so history/undo works correctly)
    new_strand_a = strand_a.model_copy(deep=True)
    new_strand_a.domains = strand1_domains

    new_strand_b = strand_b.model_copy(deep=True)
    new_strand_b.domains = strand2_domains

    # Rebuild strand list — drop strand_b if it ends up with no domains
    new_strands: List[Strand] = []
    for s in existing_design.strands:
        if s.id == strand_a.id:
            new_strands.append(new_strand_a)
        elif s.id == strand_b.id:
            if strand2_domains:
                new_strands.append(new_strand_b)
            # else: strand_b is fully absorbed into strand_a's path — omit it
        else:
            new_strands.append(s)

    return Design(
        metadata=existing_design.metadata,
        lattice_type=existing_design.lattice_type,
        helices=existing_design.helices,
        strands=new_strands,
        crossovers=existing_design.crossovers,
        deformations=existing_design.deformations,
    )


def make_half_crossover(
    existing_design: Design,
    helix_a_id: str,
    bp_a: int,
    direction_a: Direction,
    helix_b_id: str,
    bp_b: int,
    direction_b: Direction,
) -> Design:
    """Place only the A→B backbone jump, leaving B_left and A_right as free strands.

    Unlike ``make_staple_crossover`` (which creates a full DX by connecting both
    A_left→B_right AND B_left→A_right), this function places only ONE backbone
    jump: the strand on helix_a is rerouted onto helix_b, while the displaced
    pieces (B's left side, A's right side) become independent free strands.

    Special case — endpoint join: if ``bp_b`` is the 3′ end of the strand on
    helix_b AND ``bp_a`` is the 5′ start of the strand on helix_a, the two strands
    are simply concatenated (no splitting needed).  This is used for the companion
    half of a DX after the first half has already been placed.

    Same-strand case (both positions on the same strand): behaves identically to
    ``make_staple_crossover`` same-strand, producing an outer and inner strand.

    Raises ValueError if either position is on a scaffold strand or if the
    endpoint-join case would create a circular strand.
    """
    strand_a, domain_a_idx = _find_strand_at(existing_design, helix_a_id, bp_a, direction_a)
    strand_b, domain_b_idx = _find_strand_at(existing_design, helix_b_id, bp_b, direction_b)

    if strand_a.strand_type == StrandType.SCAFFOLD or strand_b.strand_type == StrandType.SCAFFOLD:
        raise ValueError("make_half_crossover cannot operate on scaffold strands.")

    d_a = strand_a.domains[domain_a_idx]
    d_b = strand_b.domains[domain_b_idx]

    # ── Split domain A at bp_a ─────────────────────────────────────────────────
    a_left = Domain(helix_id=helix_a_id, start_bp=d_a.start_bp, end_bp=bp_a, direction=direction_a)
    if direction_a == Direction.FORWARD:
        a_right_5p = bp_a + 1
        a_right = (
            Domain(helix_id=helix_a_id, start_bp=a_right_5p, end_bp=d_a.end_bp, direction=direction_a)
            if a_right_5p <= d_a.end_bp else None
        )
    else:
        a_right_5p = bp_a - 1
        a_right = (
            Domain(helix_id=helix_a_id, start_bp=a_right_5p, end_bp=d_a.end_bp, direction=direction_a)
            if a_right_5p >= d_a.end_bp else None
        )

    # ── Split domain B at bp_b ─────────────────────────────────────────────────
    b_right = Domain(helix_id=helix_b_id, start_bp=bp_b, end_bp=d_b.end_bp, direction=direction_b)
    if direction_b == Direction.FORWARD:
        b_left_3p = bp_b - 1
        b_left = (
            Domain(helix_id=helix_b_id, start_bp=d_b.start_bp, end_bp=b_left_3p, direction=direction_b)
            if b_left_3p >= d_b.start_bp else None
        )
    else:
        b_left_3p = bp_b + 1
        b_left = (
            Domain(helix_id=helix_b_id, start_bp=d_b.start_bp, end_bp=b_left_3p, direction=direction_b)
            if b_left_3p <= d_b.start_bp else None
        )

    # ── Same-strand case: delegate to staple-crossover logic ──────────────────
    if strand_a.id == strand_b.id:
        return make_staple_crossover(
            existing_design, helix_a_id, bp_a, direction_a, helix_b_id, bp_b, direction_b
        )

    # ── Endpoint-join case: strand_b's 3′ end meets strand_a's 5′ start ───────
    # This connects two free-end pieces without any splitting.
    is_5p_start_of_a = (domain_a_idx == 0 and d_a.start_bp == bp_a)
    is_3p_end_of_b   = (domain_b_idx == len(strand_b.domains) - 1 and d_b.end_bp == bp_b)

    if is_5p_start_of_a and is_3p_end_of_b:
        # Sanity check: joining a strand's end to its own start would make a loop.
        if strand_a.id == strand_b.id:
            raise ValueError(
                "make_half_crossover endpoint-join would create a circular strand."
            )
        new_strand_b = strand_b.model_copy(deep=True)
        new_strand_b.domains = list(strand_b.domains) + list(strand_a.domains)
        new_strands: List[Strand] = []
        for s in existing_design.strands:
            if s.id == strand_b.id:
                new_strands.append(new_strand_b)
            elif s.id == strand_a.id:
                pass  # absorbed into strand_b
            else:
                new_strands.append(s)
        return Design(
            metadata=existing_design.metadata,
            lattice_type=existing_design.lattice_type,
            helices=existing_design.helices,
            strands=new_strands,
            crossovers=existing_design.crossovers,
            deformations=existing_design.deformations,
        )

    # ── Normal half-crossover: A_left→B_right connected; B_left and A_right free ─
    existing_ids = {s.id for s in existing_design.strands}

    # Strand 1 (A's ID): A_before + [a_left, b_right] + B_after
    strand1_domains: List[Domain] = (
        list(strand_a.domains[:domain_a_idx])
        + [a_left, b_right]
        + list(strand_b.domains[domain_b_idx + 1:])
    )

    # B_left piece: B_before + [b_left?]
    b_left_domains: List[Domain] = (
        list(strand_b.domains[:domain_b_idx])
        + ([b_left] if b_left is not None else [])
    )

    # A_right piece: [a_right?] + A_after
    a_right_domains: List[Domain] = (
        ([a_right] if a_right is not None else [])
        + list(strand_a.domains[domain_a_idx + 1:])
    )

    new_strand_a = strand_a.model_copy(deep=True)
    new_strand_a.domains = strand1_domains

    new_strand_b_left = strand_b.model_copy(deep=True)
    new_strand_b_left.domains = b_left_domains

    new_strands_normal: List[Strand] = []
    for s in existing_design.strands:
        if s.id == strand_a.id:
            new_strands_normal.append(new_strand_a)
            # Append A_right piece if it has content
            if a_right_domains:
                a_right_strand = Strand(
                    id=_unique_id(f"{strand_a.id}_r{bp_a}", existing_ids),
                    domains=a_right_domains,
                    strand_type=StrandType.STAPLE,
                )
                new_strands_normal.append(a_right_strand)
        elif s.id == strand_b.id:
            # Keep B_left piece in strand_b's slot; skip if empty
            if b_left_domains:
                new_strands_normal.append(new_strand_b_left)
        else:
            new_strands_normal.append(s)

    return Design(
        metadata=existing_design.metadata,
        lattice_type=existing_design.lattice_type,
        helices=existing_design.helices,
        strands=new_strands_normal,
        crossovers=existing_design.crossovers,
        deformations=existing_design.deformations,
    )


def _pre_nick_for_crossover(
    design: Design,
    helix_id: str,
    bp: int,
    direction: Direction,
) -> Design:
    """Nick the strand 7 bp away from *bp* on *helix_id* to break a same-strand
    crossover that would otherwise form a closed-loop inner strand.

    Tries bp±7 in the natural 3′ direction first, then the opposite side.
    Returns the design unchanged if neither nick position is valid.
    """
    if direction == Direction.REVERSE:
        candidates = [bp - 7, bp + 7]
    else:
        candidates = [bp + 7, bp - 7]
    for nick_bp in candidates:
        try:
            return make_nick(design, helix_id, nick_bp, direction)
        except ValueError:
            continue
    return design  # neither side worked — crossover will be skipped


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

    return Design(
        metadata=existing_design.metadata,
        lattice_type=existing_design.lattice_type,
        helices=existing_design.helices,
        strands=new_strands,
        crossovers=existing_design.crossovers,
        deformations=existing_design.deformations,
    )


# ── Auto Crossover ─────────────────────────────────────────────────────────────

_XOVER_PERIOD = 21


def _auto_crossover_candidates(
    ha: "Helix", hb: "Helix"  # type: ignore[name-defined]
) -> list[tuple[int, "Direction", int, "Direction"]]:  # type: ignore[name-defined]
    """Return (bp_a, direction_a, bp_b, direction_b) tuples for canonical crossover
    positions between ha and hb.  bp_a and bp_b are already direction-adjusted so
    that the physical cut falls between the same two base-pair positions regardless
    of strand direction (FORWARD strand gets the lower index, REVERSE gets +1).

    Canonical FWD-strand bp per 21-bp period:
      p90   (same col, FORWARD lower / REVERSE upper): fwd_bp = 20  (cut between 20/21)
      p330  (lower-col cell has FORWARD scaffold):     fwd_bp =  6  (cut between  6/ 7)
      p210  (lower-col cell has REVERSE scaffold):     fwd_bp = 13  (cut between 13/14)

    Requires standard helix IDs of the form h_{plane}_{row}_{col}.
    Returns [] for non-standard IDs.
    """
    def _parse(hid: str):
        parts = hid.split("_")
        if len(parts) < 4:
            return None
        try:
            return int(parts[2]), int(parts[3])
        except ValueError:
            return None

    rc_a = _parse(ha.id)
    rc_b = _parse(hb.id)
    if rc_a is None or rc_b is None:
        return []

    row_a, col_a = rc_a
    row_b, col_b = rc_b

    def _scaf_dir(row: int, col: int) -> "Direction":  # type: ignore[name-defined]
        return Direction.FORWARD if (row + col % 2) % 3 == 0 else Direction.REVERSE

    def _staple_dir(row: int, col: int) -> "Direction":  # type: ignore[name-defined]
        return Direction.REVERSE if _scaf_dir(row, col) == Direction.FORWARD else Direction.FORWARD

    dir_a = _staple_dir(row_a, col_a)
    dir_b = _staple_dir(row_b, col_b)

    if col_a == col_b and abs(row_a - row_b) == 1:
        fwd_offsets = [20]  # VERT: cut between 20 and 21
    elif abs(col_a - col_b) == 1:
        # HORIZ: verify geometric adjacency in the honeycomb.
        # For col_left c_l and col_right c_r = c_l+1:
        #   c_l even → valid row pairs: r_right ∈ {r_left, r_left + 1}
        #   c_l odd  → valid row pairs: r_right ∈ {r_left, r_left - 1}
        if col_a < col_b:
            c_l, r_l, r_r = col_a, row_a, row_b
        else:
            c_l, r_l, r_r = col_b, row_b, row_a
        if c_l % 2 == 0:
            if r_r - r_l not in (0, 1):
                return []
        else:
            if r_l - r_r not in (0, 1):
                return []
        lower_scaf = _scaf_dir(r_l, c_l)
        fwd_offsets = [6] if lower_scaf == Direction.FORWARD else [13]  # HORIZ-A or HORIZ-B
    else:
        return []

    min_len = min(ha.length_bp, hb.length_bp)
    result: list[tuple[int, Direction, int, Direction]] = []
    for fwd_off in fwd_offsets:
        k = 0
        while True:
            base = fwd_off + k * _XOVER_PERIOD
            # Both the FWD bp (base) and REV bp (base+1) must be within the helix.
            if base + 1 >= min_len:
                break
            # "Cut between N and N+1": source strand A uses +1 for REV, dest strand B uses +1 for FWD.
            bp_a = base + (1 if dir_a == Direction.REVERSE else 0)
            bp_b = base + (1 if dir_b == Direction.FORWARD else 0)
            result.append((bp_a, dir_a, bp_b, dir_b))
            k += 1
    return result


def make_prebreak(design: Design) -> Design:
    """Nick every staple at every N-bp boundary along each helix.

    N = 7 bp for honeycomb lattice (caDNAno standard).
    N = 8 bp for square lattice (2-turn / 24-bp period, 8-bp crossover grid).

    Produces uniform N-bp fragments on the staple strand of every helix.
    Scaffold directions and positions already at a strand terminus are skipped
    silently.  The autocrossover ligation pass then joins adjacent fragments
    across helix pairs at canonical crossover positions.

    The N-bp grid is anchored to the actual minimum bp covered by the staple on
    each (helix, direction) pair — not to bp=0.  This ensures that helices whose
    staple domains have been shifted (e.g. after a near-end scaffold extrusion)
    produce clean N-nt fragments rather than a short stub at the boundary.
    """
    period = SQUARE_CROSSOVER_PERIOD if design.lattice_type == LatticeType.SQUARE else 7
    # Pre-compute which (helix_id, direction) pairs belong to scaffold strands.
    scaffold_dirs: set[tuple[str, Direction]] = set()
    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            for d in s.domains:
                scaffold_dirs.add((d.helix_id, d.direction))

    # Minimum bp covered by any staple domain on each (helix_id, direction).
    staple_low: dict[tuple[str, "Direction"], int] = {}  # type: ignore[type-arg]
    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            continue
        for d in s.domains:
            key = (d.helix_id, d.direction)
            lo = min(d.start_bp, d.end_bp)
            if key not in staple_low or lo < staple_low[key]:
                staple_low[key] = lo

    result = design
    for helix in design.helices:
        for direction in (Direction.FORWARD, Direction.REVERSE):
            if (helix.id, direction) in scaffold_dirs:
                continue
            # Anchor the grid to where the staple actually starts (low-bp end).
            # FORWARD: nick at low+(period-1), low+(2*period-1), ...
            # REVERSE: nick at low+period, low+(2*period), ...
            low_bp = staple_low.get((helix.id, direction), 0)
            bp = low_bp + (period - 1 if direction == Direction.FORWARD else period)
            while bp < helix.length_bp:
                try:
                    result = make_nick(result, helix.id, bp, direction)
                except ValueError:
                    pass
                bp += period
    return result


def _ligation_positions_for_pair(
    ha: "Helix", hb: "Helix", offset: int = 0  # type: ignore[name-defined]
) -> list[int]:
    """Return bp values at which strand fragments should be ligated between ha and hb.

    Ligation is a pure endpoint join (3' end → 5' start), not a domain split.

    Both square and honeycomb lattice positions come from the lookup tables in
    crossover_positions.py (via valid_crossover_positions) — every bp_a in the
    CrossoverCandidate list.  See drawings/lattice_ground_truth.png for ground truth.

    Parameters
    ----------
    offset:
        Shift applied to every canonical position (default 0).  Pass the
        minimum staple bp of the helix pair when staple domains have been
        shifted by a near-end scaffold extrusion.
    """
    from backend.core.crossover_positions import valid_crossover_positions

    # ── Delegate to lookup table (HC and SQ) ──────────────────────────────────
    candidates = valid_crossover_positions(ha, hb)
    positions = sorted(set(c.bp_a for c in candidates))
    if offset:
        positions = [p + offset for p in positions]
    return positions


def _find_strand_by_3prime(design: Design, helix_id: str, end_bp: int) -> "Strand | None":  # type: ignore[name-defined]
    """Return the non-scaffold strand whose last domain ends at (helix_id, end_bp)."""
    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD or not s.domains:
            continue
        last = s.domains[-1]
        if last.helix_id == helix_id and last.end_bp == end_bp:
            return s
    return None


def _find_strand_by_5prime(design: Design, helix_id: str, start_bp: int) -> "Strand | None":  # type: ignore[name-defined]
    """Return the non-scaffold strand whose first domain starts at (helix_id, start_bp)."""
    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD or not s.domains:
            continue
        first = s.domains[0]
        if first.helix_id == helix_id and first.start_bp == start_bp:
            return s
    return None


def _ligate(design: Design, s1: "Strand", s2: "Strand") -> Design:  # type: ignore[name-defined]
    """Join s2's domains onto the 3' end of s1. Returns updated Design."""
    new_domains = list(s1.domains) + list(s2.domains)
    new_strand = s1.model_copy(update={"domains": new_domains})
    new_strands = [
        new_strand if s.id == s1.id else s
        for s in design.strands
        if s.id != s2.id
    ]
    return design.model_copy(update={"strands": new_strands})


def make_auto_crossover(design: Design) -> Design:
    """Ligate staple strand fragments at canonical crossover positions.

    Applies make_prebreak first (idempotent if already applied), then joins
    3' ends to 5' ends at each crossover position. No domain boundaries are
    created or modified — only strand connectivity changes.

    Rules (per 21-bp period):
      p90   (same col, FORWARD lower / REVERSE upper): ligation at {0, 20, 21, min_len-1, ...}
      p330  (lower-col cell has FORWARD scaffold):     ligation at {6, 7, 27, 28, ...}
      p210  (lower-col cell has REVERSE scaffold):     ligation at {13, 14, 34, 35, ...}
    """
    result = make_prebreak(design)

    # Per-helix minimum staple bp (0 for unextended helices, N for near-extended).
    # Adjacent honeycomb helices always share the same extension, so using the
    # per-helix minimum as the ligation offset keeps prebreak grids aligned.
    helix_low: dict[str, int] = {}
    for s in result.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            continue
        for d in s.domains:
            lo = min(d.start_bp, d.end_bp)
            hid = d.helix_id
            if hid not in helix_low or lo < helix_low[hid]:
                helix_low[hid] = lo

    helices = result.helices
    ligations: list[tuple[str, str, int]] = []  # (ha_id, hb_id, bp)
    for i in range(len(helices)):
        for j in range(i + 1, len(helices)):
            ha, hb = helices[i], helices[j]
            offset = min(helix_low.get(ha.id, 0), helix_low.get(hb.id, 0))
            for bp in _ligation_positions_for_pair(ha, hb, offset=offset):
                ligations.append((ha.id, hb.id, bp))

    ligations.sort(key=lambda x: (x[2], x[0]))

    for ha_id, hb_id, bp in ligations:
        # Try ha→hb direction
        s1 = _find_strand_by_3prime(result, ha_id, bp)
        s2 = _find_strand_by_5prime(result, hb_id, bp)
        if s1 is not None and s2 is not None and s1.id != s2.id:
            result = _ligate(result, s1, s2)
        # Try hb→ha direction
        s1 = _find_strand_by_3prime(result, hb_id, bp)
        s2 = _find_strand_by_5prime(result, ha_id, bp)
        if s1 is not None and s2 is not None and s1.id != s2.id:
            result = _ligate(result, s1, s2)

    return result


# ── Nick placement (Stage 2 of autostaple pipeline) ───────────────────────────


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
        if d == Direction.FORWARD:
            for bp in range(domain.start_bp, domain.end_bp + 1):
                positions.append((h, bp, d))
        else:
            for bp in range(domain.start_bp, domain.end_bp - 1, -1):
                positions.append((h, bp, d))
    return positions


def compute_nick_plan_for_strand(
    strand,
    preferred_lengths: "list[int] | None" = None,
    min_length: int = 21,
    max_length: int = 60,
    min_crossover_gap: int = 7,
) -> list[dict]:
    """Return nick positions to break this strand into segments of min_length..max_length nt,
    preferring segment lengths in preferred_lengths, and avoiding the no-sandwich rule.

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
        Minimum distance in nt between a nick and any helix-transition boundary
        within the strand (default 7 — one B-DNA minor-groove period).

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

    # Crossover boundaries: index of the last nt before each helix transition.
    crossover_indices: list[int] = []
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
    """Compute nick positions for ALL non-scaffold strands.

    Returns a flat list of {helix_id, bp_index, direction} dicts — the full
    Stage 2 plan that can be shown as a progress list in the UI or applied in
    batch via make_nicks_for_autostaple().
    """
    plan = []
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            continue
        strand_nicks = compute_nick_plan_for_strand(
            strand, preferred_lengths, min_length, max_length, min_crossover_gap
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

    Applies nicks to every non-scaffold strand that either exceeds max_length or
    contains a sandwich violation (interior domain shorter than both neighbours).
    Targets segments of target_length nt while never creating segments shorter than
    min_length.  Sandwich-aware: prefers nick positions that avoid the pattern
    [longer, shorter, longer] in the resulting strand domains.

    This is Stage 2 of the two-stage autostaple pipeline:
      Stage 1: make_auto_crossover()      — place crossovers (creates zigzag strands)
      Stage 2: make_nicks_for_autostaple() — nick to 21–60 nt, no sandwiches
    """
    result = design
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            continue
        nicks = compute_nick_plan_for_strand(strand, preferred_lengths, min_length, max_length, min_crossover_gap)
        for nick in nicks:
            try:
                result = make_nick(
                    result,
                    nick["helix_id"],
                    nick["bp_index"],
                    nick["direction"],
                )
            except ValueError:
                pass  # skip if position is already a boundary or strand has changed
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


def _scaffold_xover_candidates(
    h_a: "Helix",
    dir_a: "Direction",
    h_b: "Helix",
    dir_b: "Direction",
    min_end_margin: int,
) -> list[tuple[int, int, float]]:
    """Return (bp_a, bp_b, dist_nm) triples suitable for scaffold crossovers.

    Scaffold crossover positions share the same bp-grid as staple crossovers
    (the helix backbone twist period determines where any strand can span).
    We therefore find positions where ANY backbone bead pair is close (using all
    four direction combinations), filter by end-margin, and return those bp
    indices for the scaffold strand — regardless of which direction pair happened
    to be closest.  This matches the caDNAno convention.
    """
    from backend.core.crossover_positions import valid_crossover_positions

    candidates = valid_crossover_positions(h_a, h_b)
    result = []
    for c in candidates:
        margin_a = min(c.bp_a, h_a.length_bp - 1 - c.bp_a)
        margin_b = min(c.bp_b, h_b.length_bp - 1 - c.bp_b)
        if margin_a >= min_end_margin and margin_b >= min_end_margin:
            result.append((c.bp_a, c.bp_b, c.distance_nm))
    return result


def _helix_adjacency_graph(
    design: Design,
    min_end_margin: int = 9,
) -> dict[str, list[str]]:
    """Build XY-adjacency graph for scaffold routing.

    Two helices are adjacent if there is at least one valid scaffold crossover
    candidate between them (backbone beads within MAX_CROSSOVER_REACH_NM with
    ≥ min_end_margin bp from each end).

    Returns hid → sorted list of adjacent hids (sorted by XY centre-to-centre
    distance ascending so the greedy algorithm always picks the nearest neighbour
    in a deterministic order).
    """
    helices_by_id = {h.id: h for h in design.helices}
    helix_ids = list(helices_by_id.keys())

    scaf_dir: dict[str, Direction | None] = {
        hid: _get_scaffold_direction(design, hid) for hid in helix_ids
    }

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
            if _scaffold_xover_candidates(h_a, dir_a, h_b, dir_b, min_end_margin):
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

    # Exclude helices that carry only overhang (single-stranded) domains — they
    # are structural stubs and must not participate in scaffold routing.
    skip_ids = _overhang_only_helix_ids(design)
    routable_helices = [h for h in design.helices if h.id not in skip_ids]
    if not routable_helices:
        return design

    # Group helices by Z-segment so coaxially-stacked bundles are routed independently.
    plane    = _infer_plane(routable_helices)
    segments = _group_helices_by_z_segment(routable_helices, plane)

    for seg_helices in segments:
        if len(seg_helices) % 2 != 0:
            raise ValueError(
                f"auto_scaffold requires an even number of helices per Z-segment "
                f"(a segment has {len(seg_helices)} helices). "
                "Add or remove a helix so every segment has an even count."
            )

    # Collect all scaffold strand IDs to remove (across every segment).
    all_helix_ids = {h.id for h in routable_helices}
    scaf_ids_to_remove: set[str] = {
        s.id for s in design.strands
        if s.strand_type == StrandType.SCAFFOLD and any(d.helix_id in all_helix_ids for d in s.domains)
    }
    old_scaf_ids = sorted(s.id for s in design.strands if s.id in scaf_ids_to_remove)
    base_strands = [s for s in design.strands if s.id not in scaf_ids_to_remove]

    # Shared new-ID counter so old IDs are reused in order across all segments.
    _id_counter: list[int] = [0]

    def _new_scaf_id() -> str:
        j = _id_counter[0]
        _id_counter[0] += 1
        return old_scaf_ids[j] if j < len(old_scaf_ids) else f"scaffold_{j}"

    all_new_strands: list[Strand] = []

    for seg_helices in segments:
        # Sub-design: same strands, only this segment's helices.
        # _get_scaffold_direction still works because sub_design.strands = design.strands.
        sub_design = design.model_copy(update={"helices": seg_helices})

        path = compute_scaffold_routing(sub_design, min_end_margin=min_end_margin)
        if path is None:
            # Retry with an adaptive margin sized to the shortest helix in this
            # segment.  Short extension helices (e.g. 10 bp created by a regular
            # Extrude) don't have valid VERT crossover positions with the default
            # min_end_margin=9, so the adjacency graph becomes disconnected.
            seg_min_len = min(h.length_bp for h in seg_helices)
            eff_margin  = max(0, (seg_min_len - 1) // 2)
            if eff_margin < min_end_margin:
                path = compute_scaffold_routing(sub_design, min_end_margin=eff_margin)

        if path is None:
            # Final fallback: per-helix end-to-end strands.  Used when no
            # Hamiltonian path exists even with a reduced margin (e.g. helices
            # that share no crossover-compatible positions at all).  Each helix
            # gets a single scaffold domain spanning its full length.
            for h in seg_helices:
                d = _get_scaffold_direction(sub_design, h.id)
                if d is None:
                    d = _scaffold_direction_from_helix_id(h.id)
                if d is None:
                    continue
                if d == Direction.FORWARD:
                    dom = Domain(helix_id=h.id, start_bp=0, end_bp=h.length_bp - 1, direction=d)
                else:
                    dom = Domain(helix_id=h.id, start_bp=h.length_bp - 1, end_bp=0, direction=d)
                all_new_strands.append(
                    Strand(id=_new_scaf_id(), domains=[dom], strand_type=StrandType.SCAFFOLD)
                )
            continue

        if len(path) <= 1:
            continue

        helices_by_id = {h.id: h for h in seg_helices}
        scaf_dirs: dict[str, Direction] = {}
        for hid in path:
            d = _get_scaffold_direction(sub_design, hid)
            if d is None:
                raise ValueError(f"No scaffold direction found for helix {hid}")
            scaf_dirs[hid] = d

        if mode == "seam_line":
            domain_lists = _build_seam_only_scaffold_strands(
                path, helices_by_id, scaf_dirs, seam_bp=seam_bp,
            )
            all_new_strands.extend(
                Strand(id=_new_scaf_id(), domains=domains, strand_type=StrandType.SCAFFOLD)
                for domains in domain_lists
            )
        else:
            merged_domains = _build_end_to_end_domains(
                path, helices_by_id, scaf_dirs, nick_offset,
                scaffold_loops=scaffold_loops,
            )
            all_new_strands.append(
                Strand(id=_new_scaf_id(), domains=merged_domains, strand_type=StrandType.SCAFFOLD)
            )

    return design.model_copy(update={"strands": base_strands + all_new_strands})


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
        cands = _scaffold_xover_candidates(
            h_a, scaf_dirs[hid_a], h_b, scaf_dirs[hid_b], min_end_margin
        )
        if not cands:
            raise ValueError(f"No valid scaffold crossover between {hid_a} and {hid_b}")
        all_candidates.append([(c[0], c[1]) for c in cands])

    def _pick(candidates: list[tuple[int, int]], target_bp: int | None, h_a: "Helix", h_b: "Helix") -> tuple[int, int]:
        """Pick best candidate: nearest to target_bp, or most-central if target is None."""
        if target_bp is not None:
            return min(candidates, key=lambda c: abs(c[0] - target_bp))
        return max(candidates, key=lambda c: min(c[0], h_a.length_bp - 1 - c[0],
                                                  h_b.length_bp - 1 - c[1]))

    # Sequentially commit crossover positions, respecting direction order on shared helices.
    # xover_bps[i] = (bp_a on path[i], bp_b on path[i+1])
    xover_bps: list[tuple[int, int]] = []
    for i, cands in enumerate(all_candidates):
        h_a  = helices_by_id[path[i]]
        h_b  = helices_by_id[path[i + 1]]
        L_a  = h_a.length_bp
        dir_a = scaf_dirs[path[i]]

        # Determine target for this pair: loop (even) vs seam (odd)
        is_loop_pair = (i % 2 == 0)
        if is_loop_pair:
            target = (L_a - 1 - loop_size) if dir_a == Direction.FORWARD else loop_size
        else:
            target = seam_bp  # None → most-central heuristic

        if i == 0:
            best = _pick(cands, target, h_a, h_b)
        else:
            entry_bp = xover_bps[i - 1][1]
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

    # Build domain list — start_bp = 5′ end, end_bp = 3′ end (model convention)
    merged_domains: list[Domain] = []
    for i, hid in enumerate(path):
        dir_i = scaf_dirs[hid]
        L     = helices_by_id[hid].length_bp

        if i == 0:
            # 5′ end: physical terminus when scaffold_loops=True; else nick_offset offset
            if scaffold_loops:
                five_prime = 0 if dir_i == Direction.FORWARD else L - 1
            else:
                five_prime = nick_offset if dir_i == Direction.FORWARD else L - 1 - nick_offset
            three_prime = xover_bps[0][0]
        elif i == len(path) - 1:
            five_prime  = xover_bps[i - 1][1]
            three_prime = L - 1 if dir_i == Direction.FORWARD else 0
        else:
            five_prime  = xover_bps[i - 1][1]
            three_prime = xover_bps[i][0]

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
        L     = helices_by_id[hid].length_bp

        if i == 0:
            if scaffold_loops:
                five_prime = 0 if dir_i == Direction.FORWARD else L - 1
            else:
                # nick_offset bp in from the terminal defines the 5′ start
                five_prime = nick_offset if dir_i == Direction.FORWARD else L - 1 - nick_offset
            three_prime = L - 1 if dir_i == Direction.FORWARD else 0
        else:
            # Full span of every other helix
            five_prime  = 0 if dir_i == Direction.FORWARD else L - 1
            three_prime = L - 1 if dir_i == Direction.FORWARD else 0

        merged_domains.append(Domain(
            helix_id=hid,
            start_bp=five_prime,
            end_bp=three_prime,
            direction=dir_i,
        ))

    return merged_domains


_SEAM_SEARCH_OFFSETS = (-14, -7, 0, 7, 14)


def _build_seam_only_scaffold_strands(
    path: list[str],
    helices_by_id: dict,
    scaf_dirs: dict,
    seam_bp: int | None = None,
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
    from backend.core.crossover_positions import valid_crossover_positions
    from backend.core.geometry import nucleotide_positions

    domain_lists: list[list[Domain]] = []

    # ── Outer-rail helices: full-length single domains ───────────────────────
    for hid in (path[0], path[-1]):
        d = scaf_dirs[hid]
        L = helices_by_id[hid].length_bp
        start = 0       if d == Direction.FORWARD else L - 1
        end   = L - 1   if d == Direction.FORWARD else 0
        domain_lists.append([Domain(helix_id=hid, start_bp=start, end_bp=end, direction=d)])

    # ── Inner pairs: seam DX crossovers ──────────────────────────────────────
    for i in range(1, len(path) - 2, 2):
        hid_a = path[i]
        hid_b = path[i + 1]
        dir_a = scaf_dirs[hid_a]
        dir_b = scaf_dirs[hid_b]
        L_a = helices_by_id[hid_a].length_bp
        L_b = helices_by_id[hid_b].length_bp

        base_lo = seam_bp if seam_bp is not None else L_a // 2
        max_lo  = min(L_a, L_b) - 2

        h_a = helices_by_id[hid_a]
        h_b = helices_by_id[hid_b]
        sq = abs(h_a.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9

        # Backbone positions for the scaffold direction on each helix
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
            # Square lattice: search every 8 bp within 32 bp of the seam plane;
            # pick the position that minimises actual scaffold backbone distance.
            lo_start = max(0, base_lo - 32)
            lo_end   = min(max_lo, base_lo + 32)
            lo_candidates = list(range(lo_start, lo_end + 1, 8))
        else:
            # Honeycomb: search fixed offsets around seam_bp
            lo_candidates = [
                max(0, min(base_lo + delta, max_lo))
                for delta in _SEAM_SEARCH_OFFSETS
            ]

        best_lo: int | None = None
        best_dist = float("inf")

        for lo in lo_candidates:
            hi = lo + 1
            pa_lo = pos_a.get(lo)
            pb_lo = pos_b.get(lo)
            pa_hi = pos_a.get(hi)
            pb_hi = pos_b.get(hi)
            if pa_lo is None or pb_lo is None or pa_hi is None or pb_hi is None:
                continue
            dist = (
                float(np.linalg.norm(pa_lo - pb_lo))
                + float(np.linalg.norm(pa_hi - pb_hi))
            )
            if dist < best_dist:
                best_dist = dist
                best_lo = lo

        if best_lo is None:
            best_lo = max(0, min(base_lo, max_lo))

        lo = best_lo
        hi = lo + 1

        if dir_a == Direction.FORWARD:
            # A = FORWARD (5′→3′ = 0 → L-1), B = REVERSE (5′→3′ = L-1 → 0)
            low_u = [
                Domain(helix_id=hid_a, start_bp=0,       end_bp=lo,       direction=dir_a),
                Domain(helix_id=hid_b, start_bp=lo,      end_bp=0,        direction=dir_b),
            ]
            high_u = [
                Domain(helix_id=hid_b, start_bp=L_b - 1, end_bp=hi,       direction=dir_b),
                Domain(helix_id=hid_a, start_bp=hi,      end_bp=L_a - 1,  direction=dir_a),
            ]
        else:
            # A = REVERSE (5′→3′ = L-1 → 0), B = FORWARD (5′→3′ = 0 → L-1)
            low_u = [
                Domain(helix_id=hid_b, start_bp=0,       end_bp=lo,       direction=dir_b),
                Domain(helix_id=hid_a, start_bp=lo,      end_bp=0,        direction=dir_a),
            ]
            high_u = [
                Domain(helix_id=hid_a, start_bp=L_a - 1, end_bp=hi,       direction=dir_a),
                Domain(helix_id=hid_b, start_bp=hi,      end_bp=L_b - 1,  direction=dir_b),
            ]

        domain_lists.append(low_u)
        domain_lists.append(high_u)

    return domain_lists


# ── Scaffold end-loop operations ───────────────────────────────────────────────


def _find_scaffold_by_3prime(design: "Design", helix_id: str, end_bp: int) -> "Strand | None":
    """Return the scaffold strand whose last domain ends at (helix_id, end_bp)."""
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD or not s.domains:
            continue
        last = s.domains[-1]
        if last.helix_id == helix_id and last.end_bp == end_bp:
            return s
    return None


def _find_scaffold_by_5prime(design: "Design", helix_id: str, start_bp: int) -> "Strand | None":
    """Return the scaffold strand whose first domain starts at (helix_id, start_bp)."""
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD or not s.domains:
            continue
        first = s.domains[0]
        if first.helix_id == helix_id and first.start_bp == start_bp:
            return s
    return None


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
    nick_bp = (nick_offset - 1) if direction == Direction.FORWARD else nick_offset
    try:
        return make_nick(design, hid, nick_bp, direction)
    except ValueError:
        return design


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
    """Extend all near-end helices backward so they all reach the same target plane.

    Computes a global target = (minimum near-end offset across the segment) minus
    *length_bp* bp.  Each helix subgroup is extended by the exact number of bp
    needed to reach that target, so helices whose near ends are set back from the
    global minimum are extended further and end up flush with all their neighbours.

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
    global_min_lo = min(_helix_axis_lo(h, plane) for h in near_seg)
    target_lo = global_min_lo - length_bp * BDNA_RISE_PER_BP
    result = design
    for near_offset, group_helices in _subgroup_by_offset(near_seg, plane, use_hi=False):
        cells = _cells_from_helices(group_helices, plane)
        if not cells:
            continue
        ext_bp = round((near_offset - target_lo) / BDNA_RISE_PER_BP)
        if ext_bp < 1:
            continue
        result = make_bundle_continuation(
            result, cells, -ext_bp,
            plane=plane, offset_nm=near_offset, strand_filter="scaffold",
        )
    return result


def scaffold_extrude_far(
    design: Design,
    length_bp: int = 10,
    plane: str | None = None,
) -> Design:
    """Extend all far-end helices forward so they all reach the same target plane.

    Computes a global target = (maximum far-end offset across the segment) plus
    *length_bp* bp.  Each helix subgroup is extended by the exact number of bp
    needed to reach that target, so helices whose far ends fall short of the
    global maximum are extended further and end up flush with all their neighbours.

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
    global_max_hi = max(_helix_axis_hi(h, plane) for h in far_seg)
    target_hi = global_max_hi + length_bp * BDNA_RISE_PER_BP
    result = design
    for far_offset, group_helices in _subgroup_by_offset(far_seg, plane, use_hi=True):
        cells = _cells_from_helices(group_helices, plane)
        if not cells:
            continue
        ext_bp = round((target_hi - far_offset) / BDNA_RISE_PER_BP)
        if ext_bp < 1:
            continue
        result = make_bundle_continuation(
            result, cells, ext_bp,
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
        path = compute_scaffold_routing(sub_design, min_end_margin=min_end_margin)
        if path is None or len(path) < 2:
            continue

        helices_by_id = {h.id: h for h in seg_helices}
        scaf_dirs = {
            hid: _get_scaffold_direction(sub_design, hid) for hid in path
        }

        # Between-pair junctions: path[0]↔path[1], path[2]↔path[3], path[4]↔path[5], ...
        # Each junction: near-end ligation (REVERSE_3'@bp0 → FORWARD_5'@bp0)
        #                far-end  ligation (FORWARD_3'@bpL → REVERSE_5'@bpL)
        for i in range(0, len(path) - 1, 2):
            hid_odd  = path[i]
            hid_even = path[i + 1]
            dir_odd  = scaf_dirs[hid_odd]
            dir_even = scaf_dirs[hid_even]

            # Near-end: REVERSE has 3'@bp0; FORWARD has 5'@bp0
            if dir_odd == Direction.REVERSE:
                hid_3 = hid_odd;  hid_5 = hid_even
            else:
                hid_3 = hid_even; hid_5 = hid_odd

            s3 = _find_scaffold_by_3prime(result, hid_3, 0)
            s5 = _find_scaffold_by_5prime(result, hid_5, 0)
            if s3 is not None and s5 is not None and s3.id != s5.id:
                result = _ligate(result, s3, s5)

            # Far-end: FORWARD has 3'@bpL-1; REVERSE has 5'@bpL-1
            L_odd  = helices_by_id[hid_odd].length_bp
            L_even = helices_by_id[hid_even].length_bp
            if dir_odd == Direction.FORWARD:
                hid_3f = hid_odd;  bp_3f = L_odd - 1
                hid_5f = hid_even; bp_5f = L_even - 1
            else:
                hid_3f = hid_even; bp_3f = L_even - 1
                hid_5f = hid_odd;  bp_5f = L_odd - 1

            s3f = _find_scaffold_by_3prime(result, hid_3f, bp_3f)
            s5f = _find_scaffold_by_5prime(result, hid_5f, bp_5f)
            if s3f is not None and s5f is not None and s3f.id != s5f.id:
                result = _ligate(result, s3f, s5f)

    return result


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
    axis_z_span = orig_helix.axis_end.z - orig_helix.axis_start.z
    rise = BDNA_RISE_PER_BP if axis_z_span >= 0 else -BDNA_RISE_PER_BP
    z_nick = orig_helix.axis_start.z + bp_index * rise

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
    # The crossover is at bp 0 on the new helix.
    # 5′ nick → new domain 3′ end at bp 0  → REVERSE  (start_bp = L−1, end_bp = 0)
    # 3′ nick → new domain 5′ end at bp 0  → FORWARD  (start_bp = 0, end_bp = L−1)
    new_dir = Direction.REVERSE if is_five_prime else Direction.FORWARD
    if new_dir == Direction.FORWARD:
        new_start_bp, new_end_bp = 0, length_bp - 1
    else:
        new_start_bp, new_end_bp = length_bp - 1, 0

    # ── Phase offset for new helix ───────────────────────────────────────────
    # Crossover-alignment derivation (geometry.py convention):
    #   For a +Z helix: x_hat=(0,−1,0), y_hat=(1,0,0)
    #     bead world-direction = (sin θ, −cos θ, 0)
    #   For a −Z helix: x_hat=(0,+1,0), y_hat=(1,0,0)  [frame mirrored]
    #     bead world-direction = (sin θ, +cos θ, 0)
    #
    # The original bead at bp_index points toward the overhang cell with angle:
    #   θ = orig.phase_offset + bp_index · twist
    #   world dir = (sin θ, −cos θ)  (for +Z original helix)
    #
    # The overhang bead at bp=0 must point BACK toward the original cell,
    # i.e. world direction = (−sin θ, +cos θ).
    #
    # For a +Z overhang: (sin φ, −cos φ) = (−sin θ, cos θ)  → φ = π + θ
    # For a −Z overhang: (sin φ, +cos φ) = (−sin θ, cos θ)  → φ = −θ
    theta   = orig_helix.phase_offset + bp_index * BDNA_TWIST_PER_BP_RAD
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

    new_helix = Helix(
        id           = new_helix_id,
        axis_start   = Vec3(x=nx, y=ny, z=z_nick),
        axis_end     = Vec3(x=nx, y=ny, z=z_nick + overhang_z_dir * length_nm),
        phase_offset = phase_new,
        length_bp    = length_bp,
    )

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

    # ── Extend the strand ────────────────────────────────────────────────────
    new_strand = strand.model_copy(deep=True)
    new_strand.sequence = None   # topology changed; sequence no longer valid
    if is_five_prime:
        new_strand.domains = [new_domain] + list(new_strand.domains)
    else:
        new_strand.domains = list(new_strand.domains) + [new_domain]

    new_helices = list(design.helices) + [new_helix]
    new_strands = [new_strand if s.id == strand.id else s for s in design.strands]

    return design.model_copy(update={
        "helices":      new_helices,
        "strands":      new_strands,
        "overhangs":    new_overhangs,
        "deformations": design.deformations,
    })
