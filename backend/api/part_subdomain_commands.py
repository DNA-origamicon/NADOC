"""Pure overhang subdomain edits; annotation updates belong to the same command."""

from typing import Optional
from fastapi import HTTPException
from backend.core.models import Design

ACTIONS = frozenset(
    {
        "sub-domain-split",
        "sub-domain-merge",
        "sub-domain-patch",
        "sub-domain-recompute-annotations",
        "tm-settings-update",
        "resize-free-end",
    }
)


def split(design, overhang_id, body, identity):
    from backend.api.crud import (
        _find_ovhg_or_404,
        _replace_ovhg,
        _validate_sub_domain_tiling,
    )

    spec = _find_ovhg_or_404(design, overhang_id)

    target = next((sd for sd in spec.sub_domains if sd.id == body.sub_domain_id), None)
    if target is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {body.sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    # ``split_at_offset`` is the absolute overhang offset (5'→3'). Translate to
    # a within-sub-domain offset and require strict interior.
    rel = body.split_at_offset - target.start_bp_offset
    if rel <= 0 or rel >= target.length_bp:
        raise HTTPException(
            422,
            detail=(
                f"split_at_offset {body.split_at_offset} is not strictly interior "
                f"to sub-domain {target.name!r} "
                f"(offset {target.start_bp_offset}, length {target.length_bp})."
            ),
        )

    # Phase 5: a sub-domain that is the endpoint of an OverhangBinding can't
    # be split without invalidating that binding's identity. Reject with 409
    # listing the offending binding ids.
    referencing = [
        bb.id
        for bb in design.overhang_bindings
        if target.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
    ]
    if referencing:
        raise HTTPException(
            409,
            detail={
                "error": "sub_domain_referenced_by_binding",
                "binding_ids": referencing,
            },
        )

    from backend.core.models import SubDomain as _SD

    override_5p = target.sequence_override[:rel] if target.sequence_override else None
    override_3p = target.sequence_override[rel:] if target.sequence_override else None

    new_5p = target.model_copy(
        update={
            "length_bp": rel,
            "sequence_override": override_5p,
            # Annotation caches must be re-derived after a split.
            "tm_celsius": None,
            "gc_percent": None,
            "hairpin_warning": False,
            "dimer_warning": False,
        }
    )
    new_3p = _SD(
        id=identity,
        name=f"{target.name} (split)",
        color=target.color,
        start_bp_offset=target.start_bp_offset + rel,
        length_bp=target.length_bp - rel,
        sequence_override=override_3p,
        rotation_theta_deg=target.rotation_theta_deg,
        rotation_phi_deg=target.rotation_phi_deg,
        notes=target.notes,
    )

    new_sub_doms = []
    for sd in spec.sub_domains:
        if sd.id == target.id:
            new_sub_doms.append(new_5p)
            new_sub_doms.append(new_3p)
        else:
            new_sub_doms.append(sd)
    new_sub_doms.sort(key=lambda sd: sd.start_bp_offset)

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        return _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))

    updated = _fn(design)
    _validate_sub_domain_tiling(updated, overhang_id)
    return updated


def merge(design, overhang_id, body):
    from backend.api.crud import (
        _find_ovhg_or_404,
        _replace_ovhg,
        _validate_sub_domain_tiling,
    )

    spec = _find_ovhg_or_404(design, overhang_id)

    a = next((sd for sd in spec.sub_domains if sd.id == body.sub_domain_a_id), None)
    b = next((sd for sd in spec.sub_domains if sd.id == body.sub_domain_b_id), None)
    if a is None or b is None:
        raise HTTPException(
            404,
            detail=(f"One or both sub-domains not found on overhang {overhang_id!r}."),
        )
    if a.id == b.id:
        raise HTTPException(422, detail="Cannot merge a sub-domain with itself.")

    # Order 5'→3'; require adjacency.
    if a.start_bp_offset > b.start_bp_offset:
        a, b = b, a
    if a.start_bp_offset + a.length_bp != b.start_bp_offset:
        raise HTTPException(
            422,
            detail=(
                f"Sub-domains {a.name!r} and {b.name!r} are not adjacent "
                f"(a ends at {a.start_bp_offset + a.length_bp}, "
                f"b starts at {b.start_bp_offset})."
            ),
        )

    # Phase 5: a sub-domain that is the endpoint of an OverhangBinding can't
    # disappear without orphaning that binding. Reject the merge with 409 and
    # list the offending binding ids so the UI can offer to remove them.
    _bound: set[str] = {bb.sub_domain_a_id for bb in design.overhang_bindings} | {
        bb.sub_domain_b_id for bb in design.overhang_bindings
    }
    referencing = [
        bb.id
        for bb in design.overhang_bindings
        if a.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
        or b.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
    ]
    if (a.id in _bound or b.id in _bound) and referencing:
        raise HTTPException(
            409,
            detail={
                "error": "sub_domain_referenced_by_binding",
                "binding_ids": referencing,
            },
        )

    if a.sequence_override is not None or b.sequence_override is not None:
        # Fill missing side with 'N'×length to keep the override length valid.
        seq_a = a.sequence_override or ("N" * a.length_bp)
        seq_b = b.sequence_override or ("N" * b.length_bp)
        merged_override: Optional[str] = (seq_a + seq_b).upper()
    else:
        merged_override = None

    survivor = a.model_copy(
        update={
            "length_bp": a.length_bp + b.length_bp,
            "sequence_override": merged_override,
            "notes": (a.notes + (" + " + b.notes if b.notes else ""))
            if a.notes
            else b.notes,
            "tm_celsius": None,
            "gc_percent": None,
            "hairpin_warning": False,
            "dimer_warning": False,
        }
    )

    new_sub_doms = [
        survivor if sd.id == a.id else sd for sd in spec.sub_domains if sd.id != b.id
    ]
    new_sub_doms.sort(key=lambda sd: sd.start_bp_offset)

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        return _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))

    updated = _fn(design)
    _validate_sub_domain_tiling(updated, overhang_id)
    return updated


def patch(design, overhang_id, sub_domain_id, body):
    from backend.api.crud import (
        _find_ovhg_or_404,
        _replace_ovhg,
        _HEX_RE,
        _DNA_BASES,
        _resolve_sub_domain_sequence,
        _compute_sub_domain_annotations,
        _resplice_overhang_in_strand,
        _apply_boundary_hairpin_warnings,
        _validate_sub_domain_tiling,
    )

    spec = _find_ovhg_or_404(design, overhang_id)
    sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
    if sd is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    fields_set = body.model_fields_set
    updates: dict = {}

    if "name" in fields_set and body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, detail="name must be non-empty.")
        updates["name"] = body.name

    if "color" in fields_set:
        if body.color is None or body.color == "":
            updates["color"] = None
        else:
            if not _HEX_RE.match(body.color):
                raise HTTPException(422, detail="color must be #RRGGBB hex.")
            updates["color"] = body.color

    sequence_override_changed = False
    if "sequence_override" in fields_set:
        if body.sequence_override is None or body.sequence_override == "":
            updates["sequence_override"] = None
        else:
            override = body.sequence_override.upper()
            if len(override) != sd.length_bp:
                raise HTTPException(
                    422,
                    detail=(
                        f"sequence_override length ({len(override)}) must equal "
                        f"length_bp ({sd.length_bp})."
                    ),
                )
            if any(b not in _DNA_BASES for b in override):
                raise HTTPException(
                    422, detail=("sequence_override must contain only ACGTN bases.")
                )
            updates["sequence_override"] = override
        sequence_override_changed = True

    if "rotation_theta_deg" in fields_set and body.rotation_theta_deg is not None:
        updates["rotation_theta_deg"] = float(body.rotation_theta_deg)
    if "rotation_phi_deg" in fields_set and body.rotation_phi_deg is not None:
        updates["rotation_phi_deg"] = float(body.rotation_phi_deg)
    if "notes" in fields_set and body.notes is not None:
        updates["notes"] = body.notes

    if not updates:
        # Nothing changed — return current state.
        return design

    # If the override changed, invalidate the cache and recompute annotations.
    if sequence_override_changed:
        updates.update(
            {
                "tm_celsius": None,
                "gc_percent": None,
                "hairpin_warning": False,
                "dimer_warning": False,
            }
        )

    new_sd = sd.model_copy(update=updates)

    if sequence_override_changed:
        # Recompute annotations from the new resolved sequence.
        new_seq = (
            new_sd.sequence_override
            if new_sd.sequence_override is not None
            else _resolve_sub_domain_sequence(spec, new_sd)
        )
        ann = _compute_sub_domain_annotations(
            new_seq, na_mM=design.tm_settings.na_mM, conc_nM=design.tm_settings.conc_nM
        )
        new_sd = new_sd.model_copy(update=ann)

    new_sub_doms = [new_sd if s.id == sd.id else s for s in spec.sub_domains]

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        updated = _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))
        if sequence_override_changed:
            updated = _resplice_overhang_in_strand(updated, overhang_id, cur.strand_id)
        return updated

    updated = _fn(design)
    if sequence_override_changed:
        updated = _apply_boundary_hairpin_warnings(updated, overhang_id)
    _validate_sub_domain_tiling(updated, overhang_id)
    return updated


def annotations(design, overhang_id, sub_domain_id):
    from backend.api.crud import (
        _find_ovhg_or_404,
        _replace_ovhg,
        _resolve_sub_domain_sequence,
        _compute_sub_domain_annotations,
        _apply_boundary_hairpin_warnings,
        _validate_sub_domain_tiling,
    )

    spec = _find_ovhg_or_404(design, overhang_id)
    sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
    if sd is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    seq = _resolve_sub_domain_sequence(spec, sd)
    ann = _compute_sub_domain_annotations(
        seq, na_mM=design.tm_settings.na_mM, conc_nM=design.tm_settings.conc_nM
    )
    new_sd = sd.model_copy(update=ann)
    new_sub_doms = [new_sd if s.id == sd.id else s for s in spec.sub_domains]

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        return _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))

    updated = _fn(design)
    updated = _apply_boundary_hairpin_warnings(updated, overhang_id)
    _validate_sub_domain_tiling(updated, overhang_id)
    return updated


def settings(design, body):

    new_na = design.tm_settings.na_mM if body.na_mM is None else float(body.na_mM)
    new_conc = (
        design.tm_settings.conc_nM if body.conc_nM is None else float(body.conc_nM)
    )
    if new_na <= 0 or new_conc <= 0:
        raise HTTPException(422, detail="na_mM and conc_nM must be positive.")

    from backend.core.models import TmSettings

    new_settings = TmSettings(na_mM=new_na, conc_nM=new_conc)

    # Invalidate ALL sub-domain Tm caches across every overhang. GC / hairpin /
    # dimer are independent of conditions, so we leave them set — callers can
    # explicitly re-run /recompute-annotations to refresh everything together.
    new_overhangs = []
    for ovhg in design.overhangs:
        if not ovhg.sub_domains:
            new_overhangs.append(ovhg)
            continue
        new_sub_doms = [
            sd.model_copy(update={"tm_celsius": None}) for sd in ovhg.sub_domains
        ]
        new_overhangs.append(ovhg.model_copy(update={"sub_domains": new_sub_doms}))

    def _fn(d: Design) -> Design:
        return d.model_copy(
            update={
                "tm_settings": new_settings,
                "overhangs": new_overhangs,
            }
        )

    updated = _fn(design)
    return updated


def resize(design, overhang_id, body):
    from backend.api.crud import (
        _find_ovhg_or_404,
        _validate_sub_domain_tiling,
    )
    from backend.core.lattice import resize_strand_ends as _resize_strand_ends

    spec = _find_ovhg_or_404(design, overhang_id)

    # Locate the backing domain on the strand to determine which strand-end
    # is the FREE end. Designs in the wild can have an "orphan" overhang
    # (id not on any strand domain) when an inline-style overhang and an
    # extrude-style overhang both reference the same helix; in that case fall
    # back to the strand's terminal domain on the overhang's helix so the
    # resize still lands on the physically-correct end.
    strand = next((s for s in design.strands if s.id == spec.strand_id), None)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {spec.strand_id!r} not found.")
    domains = list(strand.domains or [])
    # Strict match: domain whose overhang_id == this overhang's id.
    dom_idx = next(
        (i for i, d in enumerate(domains) if d.overhang_id == overhang_id),
        -1,
    )
    if dom_idx < 0:
        # Fallback 1: any domain on the overhang's helix that already carries
        # SOME overhang_id tag (typically an inline-overhang sibling).
        dom_idx = next(
            (
                i
                for i, d in enumerate(domains)
                if d.helix_id == spec.helix_id and d.overhang_id is not None
            ),
            -1,
        )
    if dom_idx < 0:
        # Fallback 2: the strand's first domain that touches this helix.
        dom_idx = next(
            (i for i, d in enumerate(domains) if d.helix_id == spec.helix_id),
            -1,
        )
    if dom_idx < 0:
        raise HTTPException(
            404,
            detail=f"Backing domain for {overhang_id!r} not found on strand "
            f"(also tried fallback to helix {spec.helix_id!r}).",
        )
    is_first = dom_idx == 0
    is_last = dom_idx == len(domains) - 1
    free_end: str
    if is_first and not is_last:
        free_end = "5p"
    elif is_last and not is_first:
        free_end = "3p"
    elif is_first and is_last:
        free_end = "5p"  # whole-strand: arbitrary
    else:
        raise HTTPException(
            409, detail="Overhang is sandwiched between domains; resize unsupported."
        )

    if body.end != free_end:
        raise HTTPException(
            422,
            detail=f"Requested end {body.end!r} is the root, not the free end ({free_end!r}).",
        )

    # Sub-domain length change matches |Δ length of overhang|. We resolve the
    # signed Δ from the backing domain length change, NOT from delta_bp (which
    # is signed in global-bp space; for REVERSE strands the polarity flips).
    backing = domains[dom_idx]
    old_len = abs(backing.end_bp - backing.start_bp) + 1

    if not spec.sub_domains:
        raise HTTPException(
            409,
            detail="Overhang has no sub-domains; legacy state — open it once to migrate.",
        )
    last_sd = spec.sub_domains[-1]
    # Predict the new sub-domain length so we can fail BEFORE mutating state.
    # The resize moves the free end by `delta_bp` in global bp. For the FREE
    # end, the strand-domain length change equals (delta_bp * sign) where sign
    # depends on whether free is 5' (which contracts when delta_bp > 0 on a
    # FORWARD strand) or 3'. We compute the predicted new length empirically:
    #   new_start = start_bp + delta_bp if end == '5p' else start_bp
    #   new_end   = end_bp   + delta_bp if end == '3p' else end_bp
    new_start = backing.start_bp + (body.delta_bp if free_end == "5p" else 0)
    new_end = backing.end_bp + (body.delta_bp if free_end == "3p" else 0)
    new_len = abs(new_end - new_start) + 1
    delta_len = new_len - old_len  # positive = grow, negative = shrink

    new_last_len = (last_sd.length_bp or 0) + delta_len
    # Last sub-domain must remain ≥ 1 bp. Sequence_override (if present) is
    # auto-truncated/extended in `_fn` to track length_bp, so we don't gate
    # on its current length here.
    if new_last_len < 1:
        raise HTTPException(
            422,
            detail=f"Shrink would push last sub-domain below 1 bp (would become {new_last_len}).",
        )

    def _fn(d: Design) -> Design:
        # 1. Resize the strand domain. _reconcile_inline_overhangs runs inside
        #    and preserves existing sub-domains as-is (Σ length will now drift
        #    from the new overhang length until step 2 fixes it).
        d2 = _resize_strand_ends(
            d,
            [
                {
                    "strand_id": spec.strand_id,
                    "helix_id": spec.helix_id,
                    "end": body.end,
                    "delta_bp": body.delta_bp,
                }
            ],
        )
        # 2. Re-tile sub-domains: last absorbs Δ length.
        ovhg_after = next((o for o in d2.overhangs if o.id == overhang_id), None)
        if ovhg_after is None or not ovhg_after.sub_domains:
            return d2
        new_subs = list(ovhg_after.sub_domains)
        last_after = new_subs[-1]
        new_last_len_inner = (last_after.length_bp or 0) + delta_len
        # Keep sequence_override length in sync with length_bp (validator
        # requires equality). Extend with 'N' on grow, truncate on shrink.
        new_override = last_after.sequence_override
        if new_override is not None:
            cur_len = len(new_override)
            if new_last_len_inner > cur_len:
                new_override = new_override + ("N" * (new_last_len_inner - cur_len))
            elif new_last_len_inner < cur_len:
                new_override = new_override[:new_last_len_inner]
        adjusted_last = last_after.model_copy(
            update={
                "length_bp": new_last_len_inner,
                "sequence_override": new_override,
                # Tm/GC/warning caches invalidate when the slice length changes.
                "tm_celsius": None,
                "gc_percent": None,
                "hairpin_warning": False,
                "dimer_warning": False,
            }
        )
        new_subs[-1] = adjusted_last
        new_overhangs = [
            o.model_copy(update={"sub_domains": new_subs}) if o.id == overhang_id else o
            for o in d2.overhangs
        ]
        return d2.model_copy(update={"overhangs": new_overhangs})

    updated = _fn(design)
    _validate_sub_domain_tiling(updated, overhang_id)
    return updated


def build(design, params):
    from backend.api import crud

    action = params["action"]
    oid = params.get("overhang_id")
    if action == "sub-domain-split":
        return split(
            design,
            oid,
            crud.SubDomainSplitRequest.model_validate(params),
            params["_sub_domain_id"],
        )
    if action == "sub-domain-merge":
        return merge(design, oid, crud.SubDomainMergeRequest.model_validate(params))
    if action == "sub-domain-patch":
        return patch(
            design,
            oid,
            params["sub_domain_id"],
            crud.SubDomainPatchRequest.model_validate(params),
        )
    if action == "sub-domain-recompute-annotations":
        return annotations(design, oid, params["sub_domain_id"])
    if action == "tm-settings-update":
        return settings(design, crud.TmSettingsPatchRequest.model_validate(params))
    if action == "resize-free-end":
        return resize(
            design, oid, crud.OverhangResizeFreeEndRequest.model_validate(params)
        )
    raise NotImplementedError(action)
