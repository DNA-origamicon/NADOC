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
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_LATTICE_RADIUS,
    HONEYCOMB_ROW_PITCH,
)
from backend.core.crossover_positions import valid_crossover_positions
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
    offset_nm: float = 0.0,
    id_suffix: str = "",
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

    Returns
    -------
    A complete Design with helices and scaffold strands.  No crossovers are
    added (those are placed in a later phase).
    """
    actual_length = abs(length_bp)
    if actual_length < 1:
        raise ValueError(f"length_bp magnitude must be >= 1, got {length_bp}")
    if not cells:
        raise ValueError("cells list must not be empty")
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
        lx, ly = honeycomb_position(row, col)
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

        direction = scaffold_direction_for_cell(row, col)

        # Phase offset: shifted by +1 bp twist (34.3°) so bp=0 has the correct starting orientation.
        # FORWARD: 76.3° (= 42° + 34.3°).  REVERSE: 16.3° (= 342° + 34.3°).
        phase_offset = math.radians(76.3) if direction == Direction.FORWARD else math.radians(16.3)

        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            phase_offset=phase_offset,
        )
        helices.append(helix)

        # Convention: start_bp = 5′ end, end_bp = 3′ end (regardless of direction).
        if direction == Direction.FORWARD:
            scaf_start, scaf_end = 0, actual_length - 1
        else:
            scaf_start, scaf_end = actual_length - 1, 0

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
            stpl_start, stpl_end = 0, actual_length - 1
        else:
            stpl_start, stpl_end = actual_length - 1, 0

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
        lx, ly = honeycomb_position(row, col)
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

        direction    = scaffold_direction_for_cell(row, col)
        phase_offset = math.radians(76.3) if direction == Direction.FORWARD else math.radians(16.3)

        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            phase_offset=phase_offset,
        )
        new_helices.append(helix)

        if direction == Direction.FORWARD:
            scaf_start, scaf_end = 0, actual_length - 1
        else:
            scaf_start, scaf_end = actual_length - 1, 0

        new_strands.append(Strand(
            id=scaf_id,
            domains=[Domain(helix_id=helix_id, start_bp=scaf_start, end_bp=scaf_end, direction=direction)],
            is_scaffold=True,
        ))

        staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
        if staple_dir == Direction.FORWARD:
            stpl_start, stpl_end = 0, actual_length - 1
        else:
            stpl_start, stpl_end = actual_length - 1, 0

        new_strands.append(Strand(
            id=stpl_id,
            domains=[Domain(helix_id=helix_id, start_bp=stpl_start, end_bp=stpl_end, direction=staple_dir)],
            is_scaffold=False,
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
        if not h.id.startswith(prefix):
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
    invalid = [(r, c) for r, c in cells if not is_valid_honeycomb_cell(r, c)]
    if invalid:
        raise ValueError(f"Cells are not valid honeycomb positions: {invalid}")
    valid_planes = {"XY", "XZ", "YZ"}
    if plane not in valid_planes:
        raise ValueError(f"plane must be one of {sorted(valid_planes)}, got {plane!r}")

    existing_helix_ids:  set = {h.id for h in existing_design.helices}
    existing_strand_ids: set = {s.id for s in existing_design.strands}

    helix_length_nm = length_bp * BDNA_RISE_PER_BP  # signed
    new_helices:      List[Helix]  = []
    new_strands:      List[Strand] = []   # strands for fresh (non-continuation) cells
    # strand_id → {'prepend': [Domain, ...], 'append': [Domain, ...]}
    domain_additions: dict         = {}

    for row, col in cells:
        lx, ly = honeycomb_position(row, col)
        base_hid = f"h_{plane}_{row}_{col}"

        all_helix_ids  = existing_helix_ids  | {h.id for h in new_helices}
        all_strand_ids = existing_strand_ids | {s.id for s in new_strands}

        helix_id = _unique_id(base_hid, all_helix_ids)

        if plane == "XY":
            axis_start = Vec3(x=lx, y=ly, z=offset_nm)
            axis_end   = Vec3(x=lx, y=ly, z=offset_nm + helix_length_nm)
        elif plane == "XZ":
            axis_start = Vec3(x=lx, y=offset_nm,                    z=ly)
            axis_end   = Vec3(x=lx, y=offset_nm + helix_length_nm,  z=ly)
        else:  # YZ
            axis_start = Vec3(x=offset_nm,                    y=lx, z=ly)
            axis_end   = Vec3(x=offset_nm + helix_length_nm,  y=lx, z=ly)

        direction    = scaffold_direction_for_cell(row, col)
        phase_offset = math.radians(76.3) if direction == Direction.FORWARD else math.radians(16.3)

        helix = Helix(
            id=helix_id,
            axis_start=axis_start,
            axis_end=axis_end,
            length_bp=actual_length,
            phase_offset=phase_offset,
        )
        new_helices.append(helix)

        cont_helix = _find_continuation_helix(existing_design.helices, row, col, plane, offset_nm)

        if cont_helix is not None:
            _tol = BDNA_RISE_PER_BP * 0.05
            # Determine whether axis_end of the continuation helix is at offset_nm.
            # FORWARD: axis_end is the 3′ end → append new domain after existing.
            # REVERSE: axis_end is the 5′ end → prepend new domain before existing so
            #          the inter-domain junction is at the coaxial stack point (zero-length cone).
            if plane == "XY":
                is_end_at_offset = abs(cont_helix.axis_end.z - offset_nm) < _tol
            elif plane == "XZ":
                is_end_at_offset = abs(cont_helix.axis_end.y - offset_nm) < _tol
            else:
                is_end_at_offset = abs(cont_helix.axis_end.x - offset_nm) < _tol

            # Continuation: find each strand with a domain on cont_helix and extend it.
            seen_strand_ids: set = set()
            for strand in existing_design.strands:
                if strand.id in seen_strand_ids:
                    continue
                for domain in strand.domains:
                    if domain.helix_id == cont_helix.id:
                        d = domain.direction
                        if d == Direction.FORWARD:
                            new_dom = Domain(helix_id=helix_id, start_bp=0, end_bp=actual_length - 1, direction=d)
                            # FORWARD at axis_end → append; at axis_start → prepend
                            should_prepend = not is_end_at_offset
                        else:
                            new_dom = Domain(helix_id=helix_id, start_bp=actual_length - 1, end_bp=0, direction=d)
                            # REVERSE at axis_end (5′ end) → prepend; at axis_start (3′ end) → append
                            should_prepend = is_end_at_offset
                        entry = domain_additions.setdefault(strand.id, {"prepend": [], "append": []})
                        if should_prepend:
                            entry["prepend"].append(new_dom)
                        else:
                            entry["append"].append(new_dom)
                        seen_strand_ids.add(strand.id)
                        break  # one domain per strand per continuation helix
        else:
            # Fresh cell: new scaffold + staple strands (identical to make_bundle_segment).
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
                domains=[Domain(helix_id=helix_id, start_bp=scaf_start, end_bp=scaf_end, direction=direction)],
                is_scaffold=True,
            ))

            staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
            if staple_dir == Direction.FORWARD:
                stpl_start, stpl_end = 0, actual_length - 1
            else:
                stpl_start, stpl_end = actual_length - 1, 0

            new_strands.append(Strand(
                id=stpl_id,
                domains=[Domain(helix_id=helix_id, start_bp=stpl_start, end_bp=stpl_end, direction=staple_dir)],
                is_scaffold=False,
            ))

    # Rebuild the existing strand list, extending strands that have domain_additions.
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
        phase_offset = math.radians(76.3) if direction == Direction.FORWARD else math.radians(16.3)

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
                is_scaffold=True,
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
                is_scaffold=False,
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

    if (strand_a.is_scaffold or strand_b.is_scaffold) and not allow_scaffold:
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
                        is_scaffold=False,
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

    if strand_a.is_scaffold or strand_b.is_scaffold:
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
                    is_scaffold=False,
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
        is_scaffold=strand.is_scaffold,
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
      VERT  (same col, |row_diff|=1):               fwd_bp = 20  (cut between 20/21)
      HORIZ-A (lower-col cell has FORWARD scaffold): fwd_bp =  6  (cut between  6/ 7)
      HORIZ-B (lower-col cell has REVERSE scaffold): fwd_bp = 13  (cut between 13/14)

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
    """Nick every staple at every 7-bp boundary along each helix.

    Produces uniform 7-bp fragments on the staple strand of every helix.
    Scaffold directions and positions already at a strand terminus are skipped
    silently.  The autocrossover ligation pass then joins adjacent fragments
    across helix pairs at canonical crossover positions.
    """
    # Pre-compute which (helix_id, direction) pairs belong to scaffold strands.
    scaffold_dirs: set[tuple[str, Direction]] = set()
    for s in design.strands:
        if s.is_scaffold:
            for d in s.domains:
                scaffold_dirs.add((d.helix_id, d.direction))

    result = design
    for helix in design.helices:
        for direction in (Direction.FORWARD, Direction.REVERSE):
            if (helix.id, direction) in scaffold_dirs:
                continue
            # FORWARD: nick at 6, 13, 20, ...  (3′ side of position 6 → fragment [0..6])
            # REVERSE: nick at 7, 14, 21, ...  (+1 offset so fragment boundaries align with
            #          the canonical ligation bp values used by _ligation_positions_for_pair)
            start = 6 if direction == Direction.FORWARD else 7
            bp = start
            while bp < helix.length_bp:
                try:
                    result = make_nick(result, helix.id, bp, direction)
                except ValueError:
                    pass
                bp += 7
    return result


def _ligation_positions_for_pair(ha: "Helix", hb: "Helix") -> list[int]:  # type: ignore[name-defined]
    """Return bp values at which strand fragments should be ligated between ha and hb.

    Ligation is a pure endpoint join (3' end → 5' start), not a domain split.
    Positions are determined by the crossover rules:
      VERT  (same col, |row_diff|=1):               {0, 20, 21, 41, ...}
      HORIZ-A (lower-col FORWARD scaffold):          {6, 7, 27, 28, ...}
      HORIZ-B (lower-col REVERSE scaffold):          {13, 14, 34, 35, ...}
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
    min_len = min(ha.length_bp, hb.length_bp)

    def _scaf_dir(row: int, col: int) -> "Direction":  # type: ignore[name-defined]
        return Direction.FORWARD if (row + col % 2) % 3 == 0 else Direction.REVERSE

    positions: list[int] = []

    if col_a == col_b and abs(row_a - row_b) == 1:
        # VERT: termini at 0 and min_len-1, plus mid-period positions {20,21,41,42,...}
        positions.append(0)
        positions.append(min_len - 1)
        k = 0
        while True:
            p20 = 20 + k * _XOVER_PERIOD
            p21 = 21 + k * _XOVER_PERIOD
            if p20 >= min_len:
                break
            positions.append(p20)
            if p21 < min_len:
                positions.append(p21)
            k += 1

    elif abs(col_a - col_b) == 1:
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
        if lower_scaf == Direction.FORWARD:
            # HORIZ-A: {6, 7, 27, 28, ...}
            offsets = [6, 7]
        else:
            # HORIZ-B: {13, 14, 34, 35, ...}
            offsets = [13, 14]
        k = 0
        while True:
            added = False
            for off in offsets:
                bp = off + k * _XOVER_PERIOD
                if bp < min_len:
                    positions.append(bp)
                    added = True
            if not added:
                break
            k += 1
    else:
        return []

    return sorted(set(positions))


def _find_strand_by_3prime(design: Design, helix_id: str, end_bp: int) -> "Strand | None":  # type: ignore[name-defined]
    """Return the non-scaffold strand whose last domain ends at (helix_id, end_bp)."""
    for s in design.strands:
        if s.is_scaffold or not s.domains:
            continue
        last = s.domains[-1]
        if last.helix_id == helix_id and last.end_bp == end_bp:
            return s
    return None


def _find_strand_by_5prime(design: Design, helix_id: str, start_bp: int) -> "Strand | None":  # type: ignore[name-defined]
    """Return the non-scaffold strand whose first domain starts at (helix_id, start_bp)."""
    for s in design.strands:
        if s.is_scaffold or not s.domains:
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
      VERT  (same col, |row_diff|=1):               ligation at {0, 20, 21, min_len-1, ...}
      HORIZ-A (lower-col cell has FORWARD scaffold): ligation at {6, 7, 27, 28, ...}
      HORIZ-B (lower-col cell has REVERSE scaffold): ligation at {13, 14, 34, 35, ...}
    """
    result = make_prebreak(design)

    helices = result.helices
    ligations: list[tuple[str, str, int]] = []  # (ha_id, hb_id, bp)
    for i in range(len(helices)):
        for j in range(i + 1, len(helices)):
            ha, hb = helices[i], helices[j]
            for bp in _ligation_positions_for_pair(ha, hb):
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
        if strand.is_scaffold:
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
        if strand.is_scaffold:
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


# ── Scaffold routing ───────────────────────────────────────────────────────────


def _get_scaffold_direction(design: Design, helix_id: str) -> "Direction | None":
    """Return the Direction of the scaffold strand on a given helix, or None."""
    for strand in design.strands:
        if strand.is_scaffold:
            for domain in strand.domains:
                if domain.helix_id == helix_id:
                    return domain.direction
    return None


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


def compute_scaffold_routing(
    design: Design,
    min_end_margin: int = 9,
) -> list[str] | None:
    """Find a greedy Hamiltonian path through helices for scaffold routing.

    Returns an ordered list of helix_ids starting from the first helix in
    ``design.helices``, or None if the greedy walk cannot visit all helices.

    Algorithm:
      1. Build adjacency: helices as nodes, edges where valid scaffold crossover
         candidates exist (≥ min_end_margin bp from each end).
      2. Greedy nearest-neighbour walk from design.helices[0].
    """
    if not design.helices:
        return []
    if len(design.helices) == 1:
        return [design.helices[0].id]

    adjacency = _helix_adjacency_graph(design, min_end_margin)
    start_id  = design.helices[0].id
    return _greedy_hamiltonian_path(adjacency, start_id)


def auto_scaffold(
    design: Design,
    mode: str = "seam_line",
    nick_offset: int = 7,
    min_end_margin: int = 9,
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
        Number of bp from the terminal of helix 1 (first helix in path) where the
        scaffold's 5′ end is placed.  Default 7.
    min_end_margin:
        For seam-line mode: minimum bp distance from helix ends for mid-helix crossovers.

    Raises
    ------
    ValueError
        If the number of helices is odd, if no Hamiltonian path exists, or if a
        required crossover position cannot be found (seam-line mode).
    """
    n_helices = len(design.helices)
    if n_helices == 0:
        return design
    if n_helices % 2 != 0:
        raise ValueError(
            f"auto_scaffold requires an even number of helices (got {n_helices}). "
            "Add or remove a helix so the count is even."
        )

    path = compute_scaffold_routing(design, min_end_margin=min_end_margin)
    if path is None:
        raise ValueError(
            "No greedy Hamiltonian scaffold path found. The helix adjacency graph "
            "may be disconnected — ensure all helices are reachable from helix 1."
        )

    if len(path) <= 1:
        return design

    helices_by_id = {h.id: h for h in design.helices}

    # Pre-compute scaffold direction for each helix in path
    scaf_dirs: dict[str, Direction] = {}
    for hid in path:
        d = _get_scaffold_direction(design, hid)
        if d is None:
            raise ValueError(f"No scaffold strand found on helix {hid}")
        scaf_dirs[hid] = d

    if mode == "seam_line":
        merged_domains = _build_seam_line_domains(
            path, helices_by_id, scaf_dirs, nick_offset, min_end_margin
        )
    elif mode == "end_to_end":
        merged_domains = _build_end_to_end_domains(path, helices_by_id, scaf_dirs, nick_offset)
    else:
        raise ValueError(f"Unknown scaffold routing mode {mode!r}. Use 'seam_line' or 'end_to_end'.")

    # Remove all per-helix scaffold strands on path helices
    path_set = set(path)
    scaf_ids_to_remove: set[str] = {
        s.id for s in design.strands
        if s.is_scaffold and any(d.helix_id in path_set for d in s.domains)
    }
    first_scaf_id = next(
        (s.id for s in design.strands if s.id in scaf_ids_to_remove),
        "scaffold_0",
    )

    merged_strand = Strand(id=first_scaf_id, domains=merged_domains, is_scaffold=True)
    new_strands   = [s for s in design.strands if s.id not in scaf_ids_to_remove]
    new_strands.append(merged_strand)
    return design.model_copy(update={"strands": new_strands})


def _build_seam_line_domains(
    path: list[str],
    helices_by_id: dict,
    scaf_dirs: dict,
    nick_offset: int,
    min_end_margin: int,
) -> list[Domain]:
    """Build scaffold domain list for seam-line mode (mid-helix DX crossovers).

    Crossover positions are chosen sequentially so the scaffold direction on each
    middle helix is respected: FORWARD helices require entry_bp < exit_bp;
    REVERSE helices require entry_bp > exit_bp.  For each pair the most-central
    candidate that is compatible with the already-committed entry bp is selected.
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

    # Sequentially commit crossover positions, respecting direction order on shared helices.
    # xover_bps[i] = (bp_a on path[i], bp_b on path[i+1])
    xover_bps: list[tuple[int, int]] = []
    for i, cands in enumerate(all_candidates):
        h_a = helices_by_id[path[i]]

        if i == 0:
            # No constraint from the previous pair — pick most central candidate.
            best = max(cands, key=lambda c: min(c[0], h_a.length_bp - 1 - c[0],
                                                helices_by_id[path[i+1]].length_bp - 1 - c[1]))
        else:
            # Constrain: bp_a must respect the scaffold direction on path[i].
            # path[i] is helix A for this pair; it previously committed bp_b = xover_bps[i-1][1]
            # as its entry point.  Exit (bp_a here) must be in the correct direction.
            entry_bp = xover_bps[i - 1][1]
            dir_a    = scaf_dirs[path[i]]
            if dir_a == Direction.FORWARD:
                # 5'→3' in increasing bp: exit > entry
                filtered = [(a, b) for a, b in cands if a > entry_bp]
            else:
                # 5'→3' in decreasing bp: exit < entry
                filtered = [(a, b) for a, b in cands if a < entry_bp]

            if not filtered:
                raise ValueError(
                    f"No valid scaffold crossover on {path[i]} consistent with "
                    f"entry at bp={entry_bp} (direction {dir_a.value}). "
                    f"Available candidates: {cands}"
                )
            h_b   = helices_by_id[path[i + 1]]
            best  = max(filtered, key=lambda c: min(c[0], h_a.length_bp - 1 - c[0],
                                                    h_b.length_bp - 1 - c[1]))

        xover_bps.append(best)

    # Build domain list — start_bp = 5′ end, end_bp = 3′ end (model convention)
    merged_domains: list[Domain] = []
    for i, hid in enumerate(path):
        dir_i = scaf_dirs[hid]
        L     = helices_by_id[hid].length_bp

        if i == 0:
            # 5′ end is nick_offset bp away from the terminal
            five_prime  = nick_offset if dir_i == Direction.FORWARD else L - 1 - nick_offset
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
) -> list[Domain]:
    """Build scaffold domain list for end-to-end mode (full helix spans, no mid-helix crossovers).

    The scaffold traverses each helix in full.  On the first helix the 5′ end
    is placed nick_offset bp away from the helix terminal so the scaffold's
    5′/3′ labels are visible near helix 1.
    """
    merged_domains: list[Domain] = []
    for i, hid in enumerate(path):
        dir_i = scaf_dirs[hid]
        L     = helices_by_id[hid].length_bp

        if i == 0:
            # nick_offset bp in from the terminal defines the 5′ start
            five_prime  = nick_offset if dir_i == Direction.FORWARD else L - 1 - nick_offset
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
