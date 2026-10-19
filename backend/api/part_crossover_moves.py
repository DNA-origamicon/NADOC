"""Native crossover move builders; no live-document or response dependencies."""

from fastapi import HTTPException
from backend.core.models import Design

KINDS = frozenset({"crossover-move", "crossover-move-batch"})


def move(design, body):
    from backend.core.crossover_positions import crossover_neighbor

    # ── Find the crossover ───────────────────────────────────────────────────
    xover = next((x for x in design.crossovers if x.id == body.crossover_id), None)
    if xover is None:
        raise HTTPException(404, detail=f"Crossover {body.crossover_id!r} not found.")

    old_index = xover.half_a.index
    new_index = body.new_index
    if new_index == old_index:
        return design, []

    # ── Validate new position is a valid lattice crossover site ──────────────
    helix_map = {h.id: h for h in design.helices}
    h_a = helix_map.get(xover.half_a.helix_id)
    h_b = helix_map.get(xover.half_b.helix_id)
    if h_a is None or h_b is None or h_a.grid_pos is None or h_b.grid_pos is None:
        raise HTTPException(422, detail="Crossover helices missing or have no grid_pos")

    def _is_valid_at(idx: int) -> bool:
        for is_scaf in (False, True):
            eb = crossover_neighbor(
                design.lattice_type, *h_a.grid_pos, idx, is_scaffold=is_scaf
            )
            ea = crossover_neighbor(
                design.lattice_type, *h_b.grid_pos, idx, is_scaffold=is_scaf
            )
            if (eb is not None and eb == tuple(h_b.grid_pos)) or (
                ea is not None and ea == tuple(h_a.grid_pos)
            ):
                return True
        return False

    if not _is_valid_at(new_index):
        raise HTTPException(
            422,
            detail=f"Index {new_index} is not a valid crossover site for this helix pair",
        )

    # ── Check no other crossover occupies the new position ───────────────────
    for xo in design.crossovers:
        if xo.id == body.crossover_id:
            continue
        for half in (xo.half_a, xo.half_b):
            if (
                half.helix_id == xover.half_a.helix_id
                and half.index == new_index
                and half.strand == xover.half_a.strand
            ):
                raise HTTPException(
                    422,
                    detail=f"Position {new_index} on helix A already occupied by another crossover",
                )
            if (
                half.helix_id == xover.half_b.helix_id
                and half.index == new_index
                and half.strand == xover.half_b.strand
            ):
                raise HTTPException(
                    422,
                    detail=f"Position {new_index} on helix B already occupied by another crossover",
                )

    # ── Find the two adjacent domains that the crossover connects ────────────
    # Same lookup logic as _desplice_strands_for_crossover: consecutive domains
    # d0.end_bp == old_index → d1.start_bp == old_index.
    found = None
    for ha_half, hb_half in [
        (xover.half_a, xover.half_b),
        (xover.half_b, xover.half_a),
    ]:
        if found:
            break
        for strand in design.strands:
            if found:
                break
            for di in range(len(strand.domains) - 1):
                d0 = strand.domains[di]
                d1 = strand.domains[di + 1]
                if (
                    d0.helix_id == ha_half.helix_id
                    and d0.direction == ha_half.strand
                    and d0.end_bp == old_index
                    and d1.helix_id == hb_half.helix_id
                    and d1.direction == hb_half.strand
                    and d1.start_bp == old_index
                ):
                    found = (strand, di, d0, d1)
                    break

    if found is None:
        raise HTTPException(
            422, detail="Could not find adjacent domains for this crossover"
        )

    strand, di, d0, d1 = found

    # ── Validate resized domains ─────────────────────────────────────────────
    new_d0_end = new_index
    new_d1_start = new_index

    # Domains must remain at least 1 bp long
    d0_lo = min(d0.start_bp, new_d0_end)
    d0_hi = max(d0.start_bp, new_d0_end)
    d1_lo = min(new_d1_start, d1.end_bp)
    d1_hi = max(new_d1_start, d1.end_bp)

    if d0_lo > d0_hi:
        raise HTTPException(
            422, detail="Moving crossover would make domain on first helix empty"
        )
    if d1_lo > d1_hi:
        raise HTTPException(
            422, detail="Moving crossover would make domain on second helix empty"
        )

    # Check overlap with other domains on same helix+direction
    def _overlaps(
        helix_id: str,
        direction,
        new_lo: int,
        new_hi: int,
        exclude_strand_id: str,
        exclude_dom_idx: int,
    ) -> bool:
        for s in design.strands:
            for dj, dom in enumerate(s.domains):
                if s.id == exclude_strand_id and dj == exclude_dom_idx:
                    continue
                if dom.helix_id != helix_id or dom.direction != direction:
                    continue
                dom_lo = min(dom.start_bp, dom.end_bp)
                dom_hi = max(dom.start_bp, dom.end_bp)
                if new_lo <= dom_hi and dom_lo <= new_hi:
                    return True
        return False

    if _overlaps(d0.helix_id, d0.direction, d0_lo, d0_hi, strand.id, di):
        raise HTTPException(
            422,
            detail="Moving crossover would overlap with existing domain on first helix",
        )
    if _overlaps(d1.helix_id, d1.direction, d1_lo, d1_hi, strand.id, di + 1):
        raise HTTPException(
            422,
            detail="Moving crossover would overlap with existing domain on second helix",
        )

    # ── Apply the move ───────────────────────────────────────────────────────
    # (No explicit design_state.snapshot() — the mutate_with_minor_log wrapper
    # at the end handles undo bookkeeping in one place.)

    # Update crossover index
    new_crossovers = []
    for xo in design.crossovers:
        if xo.id == body.crossover_id:
            new_crossovers.append(
                xo.model_copy(
                    update={
                        "half_a": xo.half_a.model_copy(update={"index": new_index}),
                        "half_b": xo.half_b.model_copy(update={"index": new_index}),
                    }
                )
            )
        else:
            new_crossovers.append(xo)

    # Update domains
    new_domains = list(strand.domains)
    new_domains[di] = d0.model_copy(update={"end_bp": new_d0_end})
    new_domains[di + 1] = d1.model_copy(update={"start_bp": new_d1_start})
    new_strand = strand.model_copy(update={"domains": new_domains})

    new_strands = [new_strand if s.id == strand.id else s for s in design.strands]

    # Grow helices if the new domain range extends past current helix bounds
    import math as _math
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import Vec3

    new_helices = list(design.helices)
    for idx_h, helix in enumerate(new_helices):
        if helix.id not in (d0.helix_id, d1.helix_id):
            continue
        check_lo = d0_lo if helix.id == d0.helix_id else d1_lo
        check_hi = d0_hi if helix.id == d0.helix_id else d1_hi
        helix_end_bp = helix.bp_start + helix.length_bp - 1

        if check_lo >= helix.bp_start and check_hi <= helix_end_bp:
            continue  # within bounds

        ax, bx = helix.axis_start, helix.axis_end
        dx = bx.x - ax.x
        dy = bx.y - ax.y
        dz = bx.z - ax.z
        length_nm = _math.sqrt(dx * dx + dy * dy + dz * dz)
        if length_nm < 1e-9:
            ux = uy = 0.0
            uz = 1.0
        else:
            ux = dx / length_nm
            uy = dy / length_nm
            uz = dz / length_nm

        new_bp_start = helix.bp_start
        new_length_bp = helix.length_bp
        new_axis_start = ax
        new_phase = helix.phase_offset

        if check_lo < helix.bp_start:
            extra = helix.bp_start - check_lo
            new_axis_start = Vec3(
                x=ax.x - extra * BDNA_RISE_PER_BP * ux,
                y=ax.y - extra * BDNA_RISE_PER_BP * uy,
                z=ax.z - extra * BDNA_RISE_PER_BP * uz,
            )
            new_phase = helix.phase_offset - extra * helix.twist_per_bp_rad
            new_bp_start = check_lo
            new_length_bp += extra

        new_axis_end = helix.axis_end
        if check_hi > helix_end_bp:
            extra = check_hi - helix_end_bp
            new_axis_end = Vec3(
                x=bx.x + extra * BDNA_RISE_PER_BP * ux,
                y=bx.y + extra * BDNA_RISE_PER_BP * uy,
                z=bx.z + extra * BDNA_RISE_PER_BP * uz,
            )
            new_length_bp += extra

        from backend.core.models import Helix

        new_helices[idx_h] = Helix(
            id=helix.id,
            axis_start=new_axis_start,
            axis_end=new_axis_end,
            length_bp=new_length_bp,
            bp_start=new_bp_start,
            phase_offset=new_phase,
            twist_per_bp_rad=helix.twist_per_bp_rad,
            grid_pos=helix.grid_pos,
            loop_skips=helix.loop_skips,
        )

    updated = design.copy_with(
        crossovers=new_crossovers,
        strands=new_strands,
        helices=new_helices,
    )

    return updated, list({d0.helix_id, d1.helix_id})


def batch_move(design, body):
    from backend.core.crossover_positions import crossover_neighbor
    import math as _math
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import Vec3, Helix

    # Filter out no-ops
    moves = []
    for m in body.moves:
        xover = next((x for x in design.crossovers if x.id == m.crossover_id), None)
        if xover is None:
            raise HTTPException(404, detail=f"Crossover {m.crossover_id!r} not found.")
        if m.new_index != xover.half_a.index:
            moves.append(m)

    if not moves:
        return design, []

    # Build a map of crossover_id → new_index for all moves in this batch
    move_ids = {m.crossover_id for m in moves}
    changed_helix_ids: set[str] = set()

    # ── Phase 1: Validate all moves against current design state ─────────
    # Collect move info from current state before any mutations
    move_infos = []  # list of (xover, new_index, strand, di, d0, d1)
    helix_map = {h.id: h for h in design.helices}

    for m in moves:
        xover = next((x for x in design.crossovers if x.id == m.crossover_id), None)
        if xover is None:
            raise HTTPException(404, detail=f"Crossover {m.crossover_id!r} not found.")

        old_index = xover.half_a.index
        new_index = m.new_index

        # Validate lattice position
        h_a = helix_map.get(xover.half_a.helix_id)
        h_b = helix_map.get(xover.half_b.helix_id)
        if h_a is None or h_b is None or h_a.grid_pos is None or h_b.grid_pos is None:
            raise HTTPException(
                422, detail="Crossover helices missing or have no grid_pos"
            )

        valid = False
        for is_scaf in (False, True):
            eb = crossover_neighbor(
                design.lattice_type, *h_a.grid_pos, new_index, is_scaffold=is_scaf
            )
            ea = crossover_neighbor(
                design.lattice_type, *h_b.grid_pos, new_index, is_scaffold=is_scaf
            )
            if (eb is not None and eb == tuple(h_b.grid_pos)) or (
                ea is not None and ea == tuple(h_a.grid_pos)
            ):
                valid = True
                break
        if not valid:
            raise HTTPException(
                422, detail=f"Index {new_index} is not a valid crossover site"
            )

        # Check occupancy — skip crossovers that are also being moved in this batch
        for xo in design.crossovers:
            if xo.id == m.crossover_id or xo.id in move_ids:
                continue
            for half in (xo.half_a, xo.half_b):
                if (
                    half.helix_id == xover.half_a.helix_id
                    and half.index == new_index
                    and half.strand == xover.half_a.strand
                ):
                    raise HTTPException(
                        422, detail=f"Position {new_index} already occupied"
                    )
                if (
                    half.helix_id == xover.half_b.helix_id
                    and half.index == new_index
                    and half.strand == xover.half_b.strand
                ):
                    raise HTTPException(
                        422, detail=f"Position {new_index} already occupied"
                    )

        # Find adjacent domains
        found = None
        for ha_half, hb_half in [
            (xover.half_a, xover.half_b),
            (xover.half_b, xover.half_a),
        ]:
            if found:
                break
            for strand in design.strands:
                if found:
                    break
                for di in range(len(strand.domains) - 1):
                    d0 = strand.domains[di]
                    d1 = strand.domains[di + 1]
                    if (
                        d0.helix_id == ha_half.helix_id
                        and d0.direction == ha_half.strand
                        and d0.end_bp == old_index
                        and d1.helix_id == hb_half.helix_id
                        and d1.direction == hb_half.strand
                        and d1.start_bp == old_index
                    ):
                        found = (strand, di, d0, d1)
                        break

        if found is None:
            raise HTTPException(
                422, detail="Could not find adjacent domains for crossover"
            )

        move_infos.append((xover, new_index, *found))

    # ── Phase 2: Apply all moves atomically ──────────────────────────────
    def _apply(d: "Design") -> None:
        nonlocal changed_helix_ids

        # Update crossover indices
        xover_updates = {m.crossover_id: m.new_index for m in moves}
        for i, xo in enumerate(d.crossovers):
            if xo.id in xover_updates:
                ni = xover_updates[xo.id]
                d.crossovers[i] = xo.model_copy(
                    update={
                        "half_a": xo.half_a.model_copy(update={"index": ni}),
                        "half_b": xo.half_b.model_copy(update={"index": ni}),
                    }
                )

        # Update domains — group edits by strand to handle multiple moves on same strand
        strand_dom_edits: dict[str, list[tuple[int, int]]] = {}
        for xover, new_index, strand, di, d0, d1 in move_infos:
            strand_dom_edits.setdefault(strand.id, []).append((di, new_index))
            changed_helix_ids.update({d0.helix_id, d1.helix_id})

        for si, s in enumerate(d.strands):
            if s.id not in strand_dom_edits:
                continue
            new_doms = list(s.domains)
            for di, new_index in strand_dom_edits[s.id]:
                new_doms[di] = new_doms[di].model_copy(update={"end_bp": new_index})
                new_doms[di + 1] = new_doms[di + 1].model_copy(
                    update={"start_bp": new_index}
                )
            d.strands[si] = s.model_copy(update={"domains": new_doms})

        # Grow helices if needed
        for _, new_index, strand, di, d0, d1 in move_infos:
            d0_lo = min(d0.start_bp, new_index)
            d0_hi = max(d0.start_bp, new_index)
            d1_lo = min(new_index, d1.end_bp)
            d1_hi = max(new_index, d1.end_bp)

            for idx_h, helix in enumerate(d.helices):
                if helix.id not in (d0.helix_id, d1.helix_id):
                    continue
                check_lo = d0_lo if helix.id == d0.helix_id else d1_lo
                check_hi = d0_hi if helix.id == d0.helix_id else d1_hi
                helix_end_bp = helix.bp_start + helix.length_bp - 1
                if check_lo >= helix.bp_start and check_hi <= helix_end_bp:
                    continue

                ax, bx = helix.axis_start, helix.axis_end
                dx = bx.x - ax.x
                dy = bx.y - ax.y
                dz = bx.z - ax.z
                length_nm = _math.sqrt(dx * dx + dy * dy + dz * dz)
                if length_nm < 1e-9:
                    ux = uy = 0.0
                    uz = 1.0
                else:
                    ux = dx / length_nm
                    uy = dy / length_nm
                    uz = dz / length_nm

                new_bp_start = helix.bp_start
                new_length_bp = helix.length_bp
                new_axis_start = ax
                new_phase = helix.phase_offset
                new_axis_end = helix.axis_end

                if check_lo < helix.bp_start:
                    extra = helix.bp_start - check_lo
                    new_axis_start = Vec3(
                        x=ax.x - extra * BDNA_RISE_PER_BP * ux,
                        y=ax.y - extra * BDNA_RISE_PER_BP * uy,
                        z=ax.z - extra * BDNA_RISE_PER_BP * uz,
                    )
                    new_phase = helix.phase_offset - extra * helix.twist_per_bp_rad
                    new_bp_start = check_lo
                    new_length_bp += extra
                if check_hi > helix_end_bp:
                    extra = check_hi - helix_end_bp
                    new_axis_end = Vec3(
                        x=bx.x + extra * BDNA_RISE_PER_BP * ux,
                        y=bx.y + extra * BDNA_RISE_PER_BP * uy,
                        z=bx.z + extra * BDNA_RISE_PER_BP * uz,
                    )
                    new_length_bp += extra

                d.helices[idx_h] = Helix(
                    id=helix.id,
                    axis_start=new_axis_start,
                    axis_end=new_axis_end,
                    length_bp=new_length_bp,
                    bp_start=new_bp_start,
                    phase_offset=new_phase,
                    twist_per_bp_rad=helix.twist_per_bp_rad,
                    grid_pos=helix.grid_pos,
                    loop_skips=helix.loop_skips,
                )

    candidate = design.copy_with(
        helices=list(design.helices),
        strands=list(design.strands),
        crossovers=list(design.crossovers),
    )
    _apply(candidate)
    # Per-move checks skip crossovers moved in the same batch, so validate the
    # combined result: a batch must never put two strands on the same slots.
    from backend.core.occupancy import occupancy_conflicts
    if occupancy_conflicts(candidate, limit=0)[1] > occupancy_conflicts(design, limit=0)[1]:
        raise HTTPException(
            422,
            detail="Moving these crossovers together would overlap existing domains "
                   "(two bases in the same helix position, bp and direction).",
        )
    return candidate, list(changed_helix_ids)


def build(kind, design, params):
    from backend.api.crud import MoveCrossoverRequest, BatchMoveCrossoversRequest

    if kind == "crossover-move":
        return move(design, MoveCrossoverRequest.model_validate(params))[0]
    return batch_move(design, BatchMoveCrossoversRequest.model_validate(params))[0]
