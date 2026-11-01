"""Unchanged pure normalization shared by lattice import route and replay."""

from backend.core.models import Design, Vec3


def _recenter_design(design: "Design") -> "Design":
    """Translate all helix axes so the XY bounding box center is at the origin.

    Only X and Y are shifted (Z runs along the helix axis and is left alone).
    No-op when the design has no helices or is already centered.
    """
    if not design.helices:
        return design
    xs = [h.axis_start.x for h in design.helices]
    ys = [h.axis_start.y for h in design.helices]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    if abs(cx) < 1e-6 and abs(cy) < 1e-6:
        return design
    new_helices = [
        h.model_copy(
            update={
                "axis_start": Vec3(
                    x=h.axis_start.x - cx, y=h.axis_start.y - cy, z=h.axis_start.z
                ),
                "axis_end": Vec3(
                    x=h.axis_end.x - cx, y=h.axis_end.y - cy, z=h.axis_end.z
                ),
            }
        )
        for h in design.helices
    ]
    new_overhangs = [
        o.model_copy(update={"pivot": [o.pivot[0] - cx, o.pivot[1] - cy, o.pivot[2]]})
        for o in design.overhangs
    ]
    # Shift previously-set cluster pivots so they stay in sync with the recentered
    # helix axes.  Skip pivots that are still [0,0,0] (never activated) — those will
    # be computed fresh from geometry when the move/rotate tool is first used.
    _ZERO = [0.0, 0.0, 0.0]
    new_clusters = [
        ct.model_copy(
            update={"pivot": [ct.pivot[0] - cx, ct.pivot[1] - cy, ct.pivot[2]]}
        )
        if list(ct.pivot) != _ZERO
        else ct
        for ct in design.cluster_transforms
    ]
    return design.model_copy(
        update={
            "helices": new_helices,
            "overhangs": new_overhangs,
            "cluster_transforms": new_clusters,
        }
    )


def _backfill_overhang_sequences(design: Design) -> Design:
    """After autodetect_all_overhangs, populate OverhangSpec.sequence from strand.sequence.

    scadnano designs often carry pre-assigned sequences on all domains, including
    those that become overhangs after import.  autodetect_all_overhangs creates
    OverhangSpec objects with sequence=None.  This function walks each sequenced
    strand in 5'→3' domain order, extracts the substring corresponding to each
    overhang domain (accounting for skip positions), and stores it on the matching
    OverhangSpec so the sequence survives future assign_staple_sequences calls.

    Strands without a sequence, and overhangs whose OverhangSpec already has a
    sequence set, are left unchanged.
    """
    overhang_by_id: dict[str, object] = {o.id: o for o in design.overhangs}
    if not overhang_by_id:
        return design

    # Build per-helix skip sets once.
    helix_skips: dict[str, set] = {
        h.id: {ls.bp_index for ls in h.loop_skips if ls.delta == -1}
        for h in design.helices
    }

    updated_overhangs = list(design.overhangs)
    ovhg_index = {o.id: i for i, o in enumerate(updated_overhangs)}

    for strand in design.strands:
        if strand.sequence is None:
            continue
        seq = strand.sequence
        pos = 0
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            skips = helix_skips.get(domain.helix_id, set())
            n = (hi - lo + 1) - sum(1 for bp in skips if lo <= bp <= hi)
            if n <= 0:
                continue
            if domain.overhang_id is not None:
                spec_idx = ovhg_index.get(domain.overhang_id)
                if spec_idx is not None:
                    spec = updated_overhangs[spec_idx]
                    if spec.sequence is None:
                        updated_overhangs[spec_idx] = spec.model_copy(
                            update={"sequence": seq[pos : pos + n]}
                        )
            pos += n

    return design.copy_with(overhangs=updated_overhangs)
