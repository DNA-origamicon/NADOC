"""Native loop/skip realization from the live deformation recipe."""

import math
from fastapi import HTTPException


def plan(design):
    from backend.core.part_group_consumers import require_whole_helix_realization
    require_whole_helix_realization(design)
    from backend.core.loop_skip_calculator import (
        bend_loop_skips,
        clear_loop_skips,
        sq_lattice_periodic_skips,
        twist_loop_skips,
        _bend_params_to_radius_nm,
        CELL_BP_DEFAULT,
    )
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import LatticeType

    reference_helix_ids = design.reference_helix_ids()
    overhang_helix_ids = {o.helix_id for o in design.overhangs}
    linker_helix_ids = {
        h.id
        for h in design.helices
        if h.id.startswith("__lnk__") or "::__lnk__" in h.id
    }
    ignored_helix_ids = reference_helix_ids | overhang_helix_ids | linker_helix_ids

    # Check for cross-helix domain transitions (design.crossovers is always [] —
    # actual crossover topology lives in strand domain sequences).
    has_crossovers = any(
        d0.helix_id != d1.helix_id
        and d0.helix_id not in ignored_helix_ids
        and d1.helix_id not in ignored_helix_ids
        for strand in design.active_strands()
        for d0, d1 in zip(strand.domains, strand.domains[1:])
    )
    if not has_crossovers and not any(
        op.type == "sweep" and op.params.auto_loop_skips for op in design.deformations
    ):
        raise HTTPException(
            400,
            detail="No crossovers placed. Add crossovers before applying staple routing.",
        )
    if not design.deformations and design.lattice_type != LatticeType.SQUARE:
        raise HTTPException(400, detail="No deformation ops on the current design.")

    # Reference-only, overhang, and virtual linker helices are outside this
    # bundle-level tool: neither generate marks for them nor erase existing marks.
    # A mixed reference/active helix remains active by reference_helix_ids semantics.
    active_helix_ids = [h.id for h in design.helices if h.id not in ignored_helix_ids]

    # Wipe existing marks only on active bundle geometry so recomputed mods start clean.
    # This also removes orphaned active marks no longer covered by strands.
    design = clear_loop_skips(
        design,
        active_helix_ids,
        min((h.bp_start for h in design.helices), default=0),
        max((h.bp_start + h.length_bp for h in design.helices), default=0),
    )

    helix_map = {h.id: h for h in design.helices}

    # Accumulate all per-helix modifications from every DeformationOp.
    # SQ periodic skips go first so deformation mods win at any conflicting position.
    all_mods: dict[str, list] = {}

    generated_sweep_ids = {
        hid
        for op in design.deformations
        if op.type == "sweep" and op.params.auto_loop_skips
        for hid in op.affected_helix_ids
    }
    if design.lattice_type == LatticeType.SQUARE:
        for hid, ls_list in sq_lattice_periodic_skips(design).items():
            if hid in ignored_helix_ids or hid in generated_sweep_ids:
                continue
            all_mods.setdefault(hid, []).extend(ls_list)

    for op in design.deformations:
        if op.type == "sweep":
            continue  # Sweeps use local signed strain, merged below.
        affected = [
            helix_map[hid]
            for hid in op.affected_helix_ids
            if hid in helix_map and hid not in ignored_helix_ids
        ]
        if not affected:
            continue

        plane_a = op.plane_a_bp
        plane_b = op.plane_b_bp
        n_cells = (plane_b - plane_a) // CELL_BP_DEFAULT
        if n_cells < 1:
            continue

        if op.type == "twist":
            p = op.params
            if p.total_degrees is not None:
                target_deg = p.total_degrees
            elif p.degrees_per_nm is not None:
                length_nm = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP
                target_deg = p.degrees_per_nm * length_nm
            else:
                continue
            mods = twist_loop_skips(
                affected, plane_a, plane_b, target_deg, design=design
            )
        else:  # bend
            p = op.params
            # Geometric radius from κ (matches deformation.py: R = RISE / radians(κ)).
            radius_nm = _bend_params_to_radius_nm(p.curvature_deg_per_bp)
            if math.isinf(radius_nm):
                continue  # κ ≈ 0 → infinite radius, no bend
            mods = bend_loop_skips(
                affected, plane_a, plane_b, radius_nm, p.direction_deg, design=design
            )

        for hid, ls_list in mods.items():
            all_mods.setdefault(hid, []).extend(ls_list)

    from backend.core.sweep_loop_skips import sweep_loop_skips

    has_sweep = any(op.type == "sweep" for op in design.deformations)
    try:
        for hid, marks in sweep_loop_skips(
            design,
            existing=all_mods,
            ignored_helix_ids=ignored_helix_ids,
            include_generated=True,
        ).items():
            all_mods.setdefault(hid, []).extend(marks)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if not all_mods and not has_sweep:
        raise HTTPException(400, detail="No loop/skip modifications were produced.")

    # Relocate any auto-placed mark off a crossover / strand end / margin to the nearest free
    # interior bp (preserving each helix's net count → twist/bend magnitude unchanged).  The
    # realizers (twist_loop_skips / bend_loop_skips / sq_lattice_periodic_skips) place on an even
    # cell grid and don't self-enforce this; a deletion on a crossover breaks CanDo
    # (feedback_loopskip_no_crossover_ends).  Manual context-menu placement never hits this path.
    from backend.core.loop_skip_calculator import relocate_marks_off_forbidden

    all_mods = relocate_marks_off_forbidden(all_mods, design)
    if not all_mods and not has_sweep:
        raise HTTPException(400, detail="No loop/skip modifications were produced.")

    return all_mods, active_helix_ids


def apply(design, mods, helix_ids):
    from backend.core.loop_skip_calculator import apply_loop_skips, clear_loop_skips

    return apply_loop_skips(
        clear_loop_skips(
            design,
            helix_ids,
            min((h.bp_start for h in design.helices), default=0),
            max((h.bp_start + h.length_bp for h in design.helices), default=0),
        ),
        mods,
    )


def build(design):
    mods, ids = plan(design)
    return apply(design, mods, ids)
