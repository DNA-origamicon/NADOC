"""Shared API-layer builder for overhang metadata and topology patches."""

from fastapi import HTTPException
from pydantic import BaseModel

from backend.core.models import Design, Direction, OverhangSpec, Vec3


def _resplice_overhang_in_strand(design, overhang_id: str, strand_id: str):
    """Re-derive and update the sequence for only the strand that owns the overhang.

    If the strand already has an assembled sequence (from assign_staple_sequences)
    this re-derives it using the updated overhang spec so the new random sequence
    appears in the correct position while the rest of the strand is preserved.
    Silently no-ops when the strand has no sequence or there is no scaffold sequence.
    """
    from backend.core.sequences import reassign_strands

    strand = design.find_strand(strand_id)
    if strand is None or strand.sequence is None:
        return design
    return reassign_strands(design, {strand_id})


class OverhangPatchRequest(BaseModel):
    sequence: str | None = None
    label: str | None = None
    rotation: list[float] | None = (
        None  # unit quaternion [qx, qy, qz, qw]; None = no change
    )
    # When True, skip the auto re-derivation of staple sequences after a sequence write.
    # Used by the connection-CREATION flow, which sets both overhangs' sequences then
    # immediately applies the connection (which re-derives once, with the FINAL topology) —
    # so the intermediate per-set re-derivations are redundant. Standalone edits leave this
    # False (default) and re-derive as before.
    defer_reassign: bool = False


def _build_overhang_patch(
    design: Design, overhang_id: str, body: "OverhangPatchRequest"
) -> tuple[Design, dict, OverhangSpec]:
    """Pure builder for patch_overhang. Returns (updated_design, spec_updates, new_spec).

    Raises HTTPException for validation errors (404, 409, 422). Does NOT mutate
    feature_log or push to history — that bookkeeping is the caller's choice
    (design-mode path appends OverhangRotationLogEntry inline; assembly-mode
    path wraps the whole thing in a SnapshotLogEntry).
    """
    from backend.core.constants import BDNA_RISE_PER_BP
    import math as _math

    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")

    is_inline = overhang_id.startswith("ovhg_inline_")
    # For inline overhangs the ID encodes the end: ovhg_inline_{strand_id}_{5p|3p}
    inline_end: str | None = (
        overhang_id.rsplit("_", 1)[-1] if is_inline else None
    )  # "5p" or "3p"

    # ── Build updated OverhangSpec ────────────────────────────────────────────
    # Use model_fields_set so that an explicit {"sequence": null} (clear) is
    # distinguished from the field simply being absent from the request body.
    spec_updates: dict = {}
    sequence_was_set = "sequence" in body.model_fields_set
    if sequence_was_set:
        spec_updates["sequence"] = body.sequence.upper() if body.sequence else None
    if body.label is not None:
        spec_updates["label"] = body.label
    if body.rotation is not None:
        if len(body.rotation) != 4:
            raise HTTPException(
                422, detail="rotation must be a length-4 quaternion [qx, qy, qz, qw]."
            )
        import math as _math_rot

        mag = _math_rot.sqrt(sum(x * x for x in body.rotation))
        if abs(mag) < 1e-9:
            raise HTTPException(
                422, detail="rotation quaternion must not be zero-length."
            )
        # Normalise to unit quaternion in case of minor floating-point drift.
        spec_updates["rotation"] = [x / mag for x in body.rotation]

    # ── Sub-domain override conflict guard ──────────────────────────────────
    # A whole-overhang sequence write is incompatible with sub-domain
    # overrides because the override slices would be silently overwritten.
    # Require the user to clear them first (Phase 1 design contract).
    if sequence_was_set and body.sequence is not None:
        conflicting = [
            sd.id for sd in (spec.sub_domains or []) if sd.sequence_override is not None
        ]
        if conflicting:
            raise HTTPException(
                409,
                detail={
                    "detail": "Sub-domain overrides conflict with whole-overhang sequence write",
                    "sub_domain_ids": conflicting,
                },
            )

    new_seq: str | None = spec_updates.get("sequence", spec.sequence)
    new_length_bp: int | None = len(new_seq) if new_seq else None

    # ── Resize policy: last sub-domain absorbs Δ; reject pathological shrink ─
    # If the sequence write changes the backing domain length, we must update
    # the sub-domain tiling so that Σ length_bp == new_length_bp. Per the
    # locked design: the highest-offset sub-domain absorbs the delta.
    if new_length_bp is not None and spec.sub_domains:
        current_total = sum(sd.length_bp for sd in spec.sub_domains)
        delta = new_length_bp - current_total
        if delta != 0:
            sub_doms_sorted = sorted(
                spec.sub_domains, key=lambda sd: sd.start_bp_offset
            )
            last = sub_doms_sorted[-1]
            new_last_len = last.length_bp + delta
            if new_last_len < 1:
                raise HTTPException(
                    422,
                    detail=(
                        f"Shrink would reduce sub-domain {last.name!r} ({last.id}) "
                        f"below 1 bp; delete it (or another sub-domain) first."
                    ),
                )
            if last.sequence_override is not None and new_last_len < len(
                last.sequence_override
            ):
                raise HTTPException(
                    422,
                    detail=(
                        f"Shrink would shorten sub-domain {last.name!r} ({last.id}) "
                        f"below its locked override length ({len(last.sequence_override)} bp); "
                        f"clear the override first."
                    ),
                )
            new_sub_doms = [sd for sd in sub_doms_sorted[:-1]]
            new_sub_doms.append(
                last.model_copy(
                    update={
                        "length_bp": new_last_len,
                        # Annotation caches are stale once length changes.
                        "tm_celsius": None,
                        "gc_percent": None,
                        "hairpin_warning": False,
                        "dimer_warning": False,
                    }
                )
            )
            spec_updates["sub_domains"] = new_sub_doms
    elif new_length_bp is not None and not spec.sub_domains:
        # Edge case: backfill validator hasn't run (shouldn't happen post-load
        # because validators are always invoked). Insert a single whole-overhang
        # sub-domain matching the new length.
        from backend.core.models import (
            SubDomain as _SubDomain,
            NADOC_SUBDOMAIN_NS as _NS,
        )
        import uuid as _uuid_local

        spec_updates["sub_domains"] = [
            _SubDomain(
                id=str(_uuid_local.uuid5(_NS, f"{spec.id}:whole")),
                name="a",
                start_bp_offset=0,
                length_bp=new_length_bp,
            )
        ]

    new_spec = spec.model_copy(update=spec_updates)
    new_overhangs = [new_spec if o.id == overhang_id else o for o in design.overhangs]

    # ── Resize helix + domain when sequence length changes ───────────────────
    new_helices = list(design.helices)
    new_strands = list(design.strands)

    # For extrude-style overhangs we need the junction bp on the dedicated
    # helix. The junction can be at the helix's low (+Z extrude) OR high
    # (−Z extrude, axis flipped) bp end — see Bug 06.
    extrude_junction_bp: int | None = None
    if not is_inline:
        from backend.core.lattice import _overhang_junction_bp

        extrude_junction_bp = _overhang_junction_bp(design, spec.helix_id)

    if new_length_bp is not None:
        if not is_inline:
            # ── Extrude-style: resize the dedicated overhang helix ────────────
            # Keep the junction's world-space position fixed; move axis_start
            # inward/outward on the tip side. Correct for both +Z and −Z
            # extrudes (the latter has bp_start at the tip end of the bp range).
            for hi, helix in enumerate(new_helices):
                if helix.id != spec.helix_id:
                    continue
                if helix.length_bp == new_length_bp:
                    break
                ax = helix.axis_end.to_array() - helix.axis_start.to_array()
                ax_len = _math.sqrt(ax[0] ** 2 + ax[1] ** 2 + ax[2] ** 2)
                if ax_len < 1e-9:
                    break
                unit = ax / ax_len
                if extrude_junction_bp is None:
                    # Fall back to legacy +Z behaviour if no crossover record.
                    new_len_nm = new_length_bp * BDNA_RISE_PER_BP
                    new_end = helix.axis_start.to_array() + unit * new_len_nm
                    new_helices[hi] = helix.model_copy(
                        update={
                            "length_bp": new_length_bp,
                            "axis_end": Vec3(
                                x=float(new_end[0]),
                                y=float(new_end[1]),
                                z=float(new_end[2]),
                            ),
                        }
                    )
                    break
                helix_lo = helix.bp_start
                helix_hi = helix.bp_start + helix.length_bp - 1
                # Find the current tip bp (the helix endpoint that is not the junction).
                tip_bp = helix_hi if extrude_junction_bp == helix_lo else helix_lo
                tip_sign = 1 if tip_bp > extrude_junction_bp else -1
                new_tip_bp = extrude_junction_bp + tip_sign * (new_length_bp - 1)
                new_bp_start = min(extrude_junction_bp, new_tip_bp)
                # Junction's world position from the current axis.
                local_junc_old = extrude_junction_bp - helix.bp_start
                junction_world = (
                    helix.axis_start.to_array()
                    + local_junc_old * BDNA_RISE_PER_BP * unit
                )
                # New axis_start = junction_world − (junction_local_new) * RISE * unit.
                local_junc_new = extrude_junction_bp - new_bp_start
                new_axis_start = (
                    junction_world - local_junc_new * BDNA_RISE_PER_BP * unit
                )
                new_axis_end = new_axis_start + new_length_bp * BDNA_RISE_PER_BP * unit
                new_helices[hi] = helix.model_copy(
                    update={
                        "length_bp": new_length_bp,
                        "bp_start": new_bp_start,
                        "axis_start": Vec3(
                            x=float(new_axis_start[0]),
                            y=float(new_axis_start[1]),
                            z=float(new_axis_start[2]),
                        ),
                        "axis_end": Vec3(
                            x=float(new_axis_end[0]),
                            y=float(new_axis_end[1]),
                            z=float(new_axis_end[2]),
                        ),
                    }
                )
                break

        # ── Resize the overhang domain ────────────────────────────────────────
        for si, strand in enumerate(new_strands):
            for di, domain in enumerate(strand.domains):
                if domain.overhang_id != overhang_id:
                    continue

                is_fwd = domain.direction == Direction.FORWARD

                if is_inline:
                    # Junction end (adjacent to scaffold) is fixed; free end moves.
                    # inline_end tells us which terminus is the free (dragged) end.
                    if inline_end == "3p":
                        if is_fwd:
                            # 5' junction = start_bp (fixed), 3' free = end_bp
                            new_domain = domain.model_copy(
                                update={"end_bp": domain.start_bp + new_length_bp - 1}
                            )
                        else:
                            # 5' junction = start_bp (fixed), 3' free = end_bp (lower)
                            new_domain = domain.model_copy(
                                update={"end_bp": domain.start_bp - (new_length_bp - 1)}
                            )
                    else:  # "5p"
                        if is_fwd:
                            # 3' junction = end_bp (fixed), 5' free = start_bp (lower)
                            new_domain = domain.model_copy(
                                update={"start_bp": domain.end_bp - (new_length_bp - 1)}
                            )
                        else:
                            # 3' junction = end_bp (fixed), 5' free = start_bp (higher)
                            new_domain = domain.model_copy(
                                update={"start_bp": domain.end_bp + (new_length_bp - 1)}
                            )

                    # Grow the main helix if the new domain falls outside its bounds
                    helix_idx = next(
                        (
                            hi
                            for hi, h in enumerate(new_helices)
                            if h.id == spec.helix_id
                        ),
                        None,
                    )
                    if helix_idx is not None:
                        h = new_helices[helix_idx]
                        free_bp = (
                            new_domain.end_bp
                            if inline_end == "3p"
                            else new_domain.start_bp
                        )
                        helix_end_bp = h.bp_start + h.length_bp - 1
                        ax = h.axis_end.to_array() - h.axis_start.to_array()
                        ax_len = _math.sqrt(ax[0] ** 2 + ax[1] ** 2 + ax[2] ** 2)
                        unit = ax / ax_len if ax_len > 1e-9 else ax
                        if free_bp < h.bp_start:
                            extra = h.bp_start - free_bp
                            new_start = (
                                h.axis_start.to_array()
                                - extra * BDNA_RISE_PER_BP * unit
                            )
                            new_helices[helix_idx] = h.model_copy(
                                update={
                                    "axis_start": Vec3(
                                        x=float(new_start[0]),
                                        y=float(new_start[1]),
                                        z=float(new_start[2]),
                                    ),
                                    "length_bp": h.length_bp + extra,
                                    "bp_start": free_bp,
                                    "phase_offset": h.phase_offset
                                    - extra * h.twist_per_bp_rad,
                                }
                            )
                        elif free_bp > helix_end_bp:
                            extra = free_bp - helix_end_bp
                            new_end = (
                                h.axis_end.to_array() + extra * BDNA_RISE_PER_BP * unit
                            )
                            new_helices[helix_idx] = h.model_copy(
                                update={
                                    "axis_end": Vec3(
                                        x=float(new_end[0]),
                                        y=float(new_end[1]),
                                        z=float(new_end[2]),
                                    ),
                                    "length_bp": h.length_bp + extra,
                                }
                            )
                else:
                    # Extrude-style: keep the junction bp fixed; move only the
                    # tip endpoint of the domain. The tip is whichever endpoint
                    # is NOT the junction. Works for +Z and −Z extrudes.
                    if extrude_junction_bp is None:
                        # Legacy fallback (no crossover record found).
                        if is_fwd:
                            new_domain = domain.model_copy(
                                update={"end_bp": domain.start_bp + new_length_bp - 1}
                            )
                        else:
                            new_domain = domain.model_copy(
                                update={"start_bp": domain.end_bp + new_length_bp - 1}
                            )
                    else:
                        if domain.start_bp == extrude_junction_bp:
                            tip_sign = 1 if domain.end_bp > domain.start_bp else -1
                            new_tip = domain.start_bp + tip_sign * (new_length_bp - 1)
                            new_domain = domain.model_copy(update={"end_bp": new_tip})
                        else:
                            tip_sign = 1 if domain.start_bp > domain.end_bp else -1
                            new_tip = domain.end_bp + tip_sign * (new_length_bp - 1)
                            new_domain = domain.model_copy(update={"start_bp": new_tip})

                new_domains = list(strand.domains)
                new_domains[di] = new_domain
                new_strands[si] = strand.model_copy(
                    update={"domains": new_domains, "sequence": None}
                )
                break

    updated = design.model_copy(
        update={
            "helices": new_helices,
            "strands": new_strands,
            "overhangs": new_overhangs,
        }
    )

    # When the sequence is cleared (no resize happened so strand.sequence was not
    # touched above), re-derive the strand's assembled sequence so the overhang
    # position reverts to N×len instead of retaining the old bases.
    if new_seq is None and "sequence" in body.model_fields_set:
        updated = _resplice_overhang_in_strand(updated, overhang_id, spec.strand_id)

    return updated, spec_updates, new_spec
