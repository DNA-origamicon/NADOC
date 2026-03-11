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

        # Phase offset: FORWARD helices (cell_value==0) start at 315° so that
        # backbone beads at bp=0 face their REVERSE neighbours, giving 4 valid
        # crossover positions per helix turn (every ~10.5 bp).
        # REVERSE helices (cell_value==1) use phase_offset=0.
        phase_offset = math.radians(315.0) if direction == Direction.FORWARD else 0.0

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
        phase_offset = math.radians(315.0) if direction == Direction.FORWARD else 0.0

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
        phase_offset = math.radians(315.0) if direction == Direction.FORWARD else 0.0

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
    - Both positions belong to the same strand (would create a hairpin loop)
    - No strand covers one of the specified positions
    """
    strand_a, domain_a_idx = _find_strand_at(existing_design, helix_a_id, bp_a, direction_a)
    strand_b, domain_b_idx = _find_strand_at(existing_design, helix_b_id, bp_b, direction_b)

    if strand_a.is_scaffold or strand_b.is_scaffold:
        raise ValueError("make_staple_crossover cannot operate on scaffold strands.")
    if strand_a.id == strand_b.id:
        raise ValueError(
            "Both crossover positions are on the same strand; "
            "this would create a hairpin loop."
        )

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

    # ── Reconnect ──────────────────────────────────────────────────────────────
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
    )
