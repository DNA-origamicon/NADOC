"""Pure native pencil/cell/extent commands, shared with interactive routes."""

from fastapi import HTTPException
from backend.core.models import Helix, Strand, Domain, Direction, StrandType, Vec3

KINDS = frozenset({"helix-add-at-cell", "helix-extend", "scaffold-domain-paint"})


def cell(design, body, params):
    from backend.core.constants import BDNA_RISE_PER_BP as _RISE
    from backend.core.lattice import (
        _LINKER_HELIX_PREFIX,
        _lattice_direction,
        _lattice_phase_offset,
        _lattice_position,
        _lattice_twist,
        _overhang_neighbor_xy,
    )

    lt = design.lattice_type

    direction = _lattice_direction(body.row, body.col, lt)
    phase_base = _lattice_phase_offset(direction, lt)  # angle at global bp 0
    twist = _lattice_twist(lt)

    # Reference = nearest existing lattice helix (Manhattan distance in grid
    # cells).  Linker helices are synthetic and parked far off-lattice, so they
    # are excluded as references.
    candidates = [
        h
        for h in design.helices
        if h.grid_pos is not None
        and h.lattice_frame_id is None
        and not h.id.startswith(_LINKER_HELIX_PREFIX)
    ]
    ref = (
        min(
            candidates,
            key=lambda h: abs(h.grid_pos[0] - body.row) + abs(h.grid_pos[1] - body.col),
        )
        if candidates
        else None
    )

    if ref is not None:
        # Adjacent placement: XY offset from the reference's real axis, Z-span +
        # bp_start + length copied so the new track lines up with its neighbours.
        nx, ny = _overhang_neighbor_xy(ref, body.row, body.col, design)
        bp_start = ref.bp_start
        length_bp = ref.length_bp
        axis_start = Vec3(x=nx, y=ny, z=ref.axis_start.z)
        axis_end = Vec3(x=nx, y=ny, z=ref.axis_end.z)
        phase_offset = phase_base + bp_start * twist
    else:
        # Empty design (first helix): raw lattice position, requested default length.
        lx, ly = _lattice_position(body.row, body.col, lt)
        bp_start = 0
        length_bp = body.length_bp
        axis_start = Vec3(x=lx, y=ly, z=0.0)
        axis_end = Vec3(x=lx, y=ly, z=length_bp * _RISE)
        phase_offset = phase_base

    new_helix = Helix(
        id=params["_helix_id"],
        axis_start=axis_start,
        axis_end=axis_end,
        length_bp=length_bp,
        phase_offset=phase_offset,
        twist_per_bp_rad=twist,
        bp_start=bp_start,
        grid_pos=(body.row, body.col),
    )

    # When populate_strands is set, also add a full-length scaffold + staple
    # strand to the new helix (same convention as make_bundle_design: scaffold
    # runs in the lattice direction, staple runs opposite; start_bp is the 5′ end).
    # Legacy path — the 2D editor now creates empty helices.  Domains use GLOBAL
    # bp indices so they remain correct when bp_start was inherited from a neighbour.
    if body.populate_strands:
        lo = bp_start
        hi = bp_start + length_bp - 1
        if direction == Direction.FORWARD:
            scaf_start, scaf_end = lo, hi
        else:
            scaf_start, scaf_end = hi, lo
        staple_dir = (
            Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
        )
        if staple_dir == Direction.FORWARD:
            stpl_start, stpl_end = lo, hi
        else:
            stpl_start, stpl_end = hi, lo

        scaffold = Strand(
            id=params["_scaffold_id"],
            domains=[
                Domain(
                    helix_id=new_helix.id,
                    start_bp=scaf_start,
                    end_bp=scaf_end,
                    direction=direction,
                )
            ],
            strand_type=StrandType.SCAFFOLD,
        )
        staple = Strand(
            id=params["_staple_id"],
            domains=[
                Domain(
                    helix_id=new_helix.id,
                    start_bp=stpl_start,
                    end_bp=stpl_end,
                    direction=staple_dir,
                )
            ],
            strand_type=StrandType.STAPLE,
        )

    from backend.core.cluster_autodetect import with_default_cluster
    from backend.core.feature_identity import identity_factory

    updated = design.copy_with(
        helices=[*design.helices, new_helix],
        strands=[
            *design.strands,
            *([scaffold, staple] if body.populate_strands else []),
        ],
    )
    return with_default_cluster(
        updated, identity_factory=identity_factory(params["_helix_id"])
    )


def extend(design, helix_id, body):
    import math as _math

    from backend.core.constants import BDNA_RISE_PER_BP

    from backend.api.crud import _find_helix

    helix = _find_helix(design, helix_id)

    h_lo = helix.bp_start
    h_hi = helix.bp_start + helix.length_bp - 1

    new_lo = min(body.lo_bp, h_lo)
    new_hi = max(body.hi_bp, h_hi)

    if new_lo == h_lo and new_hi == h_hi:
        return design

    ax = helix.axis_end.to_array() - helix.axis_start.to_array()
    ax_len = float(_math.sqrt(float((ax * ax).sum())))
    unit = ax / ax_len if ax_len > 1e-9 else helix.axis_start.to_array() * 0 + [0, 0, 1]

    extra_lo = h_lo - new_lo  # bps prepended (≥ 0)
    extra_hi = new_hi - h_hi  # bps appended  (≥ 0)

    new_axis_start = helix.axis_start.to_array() - extra_lo * BDNA_RISE_PER_BP * unit
    new_axis_end = helix.axis_end.to_array() + extra_hi * BDNA_RISE_PER_BP * unit

    updated = helix.model_copy(
        update={
            "axis_start": Vec3.from_array(new_axis_start),
            "axis_end": Vec3.from_array(new_axis_end),
            "length_bp": new_hi - new_lo + 1,
            "bp_start": new_lo,
            # phase_offset is defined at local_bp=0 (= axis_start).  Moving axis_start
            # back by extra_lo steps means the old geometry now starts at local_bp=extra_lo,
            # so we subtract extra_lo × twist to keep the old nucleotides in place.
            "phase_offset": helix.phase_offset - extra_lo * helix.twist_per_bp_rad,
        }
    )

    return design.copy_with(
        helices=[updated if h.id == helix_id else h for h in design.helices]
    )


def paint(design, body, identity):
    import re
    from backend.core.lattice import (
        _lattice_direction,
    )

    _HC_RE = re.compile(r"^h_\w+_(-?\d+)_(-?\d+)$")

    from backend.api.crud import _find_helix

    helix = _find_helix(design, body.helix_id)
    lt = design.lattice_type

    # Resolve (row, col) for direction lookup
    if helix.grid_pos is not None:
        row, col = helix.grid_pos
    else:
        m = _HC_RE.match(helix.id)
        if m:
            row, col = int(m.group(1)), int(m.group(2))
        else:
            raise HTTPException(
                400,
                detail=f"Helix {helix.id!r} has no grid_pos — cannot determine scaffold direction.",
            )

    direction = _lattice_direction(row, col, lt)

    # Clamp to helix bp bounds
    h_lo = helix.bp_start
    h_hi = helix.bp_start + helix.length_bp - 1
    lo = max(body.lo_bp, h_lo)
    hi = min(body.hi_bp, h_hi)
    if lo > hi:
        raise HTTPException(400, detail="bp range outside helix bounds.")

    # Reject overlap with existing scaffold domains on this helix
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in strand.domains:
            if dom.helix_id != body.helix_id:
                continue
            d_lo = min(dom.start_bp, dom.end_bp)
            d_hi = max(dom.start_bp, dom.end_bp)
            if d_lo <= hi and d_hi >= lo:
                raise HTTPException(
                    409,
                    detail=(
                        f"Scaffold domain already covers helix {body.helix_id!r} "
                        f"in range [{d_lo}, {d_hi}]."
                    ),
                )

    # Polarity: start_bp = 5' end
    if direction == Direction.FORWARD:
        start_bp, end_bp = lo, hi
    else:
        start_bp, end_bp = hi, lo  # REVERSE: 5' is at higher bp index

    new_strand = Strand(
        id=identity,
        domains=[
            Domain(
                helix_id=body.helix_id,
                start_bp=start_bp,
                end_bp=end_bp,
                direction=direction,
            )
        ],
        strand_type=StrandType.SCAFFOLD,
    )

    return design.copy_with(strands=[*design.strands, new_strand])


def build(kind, design, params):
    from backend.api.crud import (
        HelixAtCellRequest,
        HelixExtendRequest,
        ScaffoldPaintRequest,
    )

    if kind == "helix-extend":
        return extend(
            design, params["helix_id"], HelixExtendRequest.model_validate(params)
        )
    if kind == "scaffold-domain-paint":
        return paint(
            design, ScaffoldPaintRequest.model_validate(params), params["_strand_id"]
        )
    body = HelixAtCellRequest.model_validate(params)
    if body.lattice_frame_id:
        from backend.core.lattice_frames import append_frame_cell

        return append_frame_cell(
            design,
            body.lattice_frame_id,
            body.row,
            body.col,
            length_bp=body.length_bp,
            populate_strands=body.populate_strands,
            identity_seed=params["history_seed"],
        )[0]
    return cell(design, body, params)
