"""
API layer — bend/twist deformation route handlers (extracted from crud.py).

This module hosts the ``/design/deformation`` endpoints: add / update / delete
of geometric bend & twist ops, plus the ``/design/deformation/debug`` summary
route used by View>Debug to inspect per-helix frame math. They were factored
out of ``crud.py`` following the same template as Refactor 13-B (camera poses),
10-F (loop-skip), and the animations / extensions sub-routers.

The shared deformation business logic (``parse_deformation_params``,
``resolve_cluster_scope``) lives in ``backend/core/deformation.py`` — it is
imported here AND by crud.py's edit-feature dispatch, so neither file depends
on the other for it (the carve-router service push that preceded this lift).

Routes
------
  POST   /design/deformation              — add bend/twist op (?preview=true = no undo)
  PATCH  /design/deformation/{op_id}      — update params only (silent, no undo)
  DELETE /design/deformation/{op_id}      — remove op (?preview=true = no undo)
  GET    /design/deformation/debug        — per-helix frame/centroid diagnostics

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.api import state as design_state

# _design_response is the shared response helper used by 100+ crud.py routes;
# it stays in crud.py and is imported back here. Same convention as
# routes_camera_poses.py (13-B) / routes_animations.py.
from backend.api.crud import _design_response
from backend.core.deformation import (
    helices_crossing_planes,
    parse_deformation_params,
    resolve_cluster_scope,
)
from backend.core.models import DeformationLogEntry, DeformationOp, Design

router = APIRouter()


class AddDeformationBody(BaseModel):
    type: str  # 'twist' | 'bend'
    plane_a_bp: int
    plane_b_bp: int
    affected_helix_ids: list[str] = []
    # When non-empty, restrict affected helices to the union of these clusters' helix_ids.
    # Empty list = unscoped (apply to all helices crossing the planes).
    cluster_ids: list[str] = []
    params: dict  # raw dict; validated into TwistParams | BendParams below
    preview: bool = False  # when True, use silent update (no undo push)


class UpdateDeformationBody(BaseModel):
    params: dict  # updated params only


def _attach_deformation_warning(
    response: dict,
    design: Design,
    op_type: str,
    helix_ids: list[str],
    plane_a_bp: int,
    plane_b_bp: int,
    params,
) -> None:
    """Attach a non-fatal ``deformation_warning`` to *response* when a bend/twist
    would fold poorly (WARN) or is geometrically unachievable (BLOCK).

    Never raises and never blocks: the geometric editing layer stays permissive
    (warn-in-editor); the hard 422 lives only in the loop/skip realization path
    (apply-deformations). See classify_deformation for the 9–12 / 6–15 bp/turn
    thresholds.
    """
    from backend.core.loop_skip_calculator import classify_deformation

    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in helix_ids if hid in h_map]
    warning = classify_deformation(
        segment_helices, plane_a_bp, plane_b_bp, op_type, params, design=design
    )
    if warning["status"] != "ok":
        response["deformation_warning"] = warning


@router.post("/design/deformation", status_code=200)
def add_deformation(body: AddDeformationBody) -> dict:
    """Add a twist or bend deformation op to the active design.

    Pushes to the undo stack.  If affected_helix_ids is empty, auto-populates
    with all helices whose bp range covers both planes.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        params = parse_deformation_params(body.type, body.params)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    helix_ids = body.affected_helix_ids or helices_crossing_planes(
        design, body.plane_a_bp, body.plane_b_bp
    )

    # When clusters are specified, restrict affected helices to the union of those
    # clusters' helix_ids. Drops cluster ids that no longer exist in the design.
    resolved_cluster_ids = resolve_cluster_scope(design, body.cluster_ids, helix_ids)
    helix_ids = resolved_cluster_ids["helix_ids"]
    cluster_ids = resolved_cluster_ids["cluster_ids"]

    op = DeformationOp(
        type=body.type,
        plane_a_bp=body.plane_a_bp,
        plane_b_bp=body.plane_b_bp,
        affected_helix_ids=helix_ids,
        cluster_ids=cluster_ids,
        params=params,
    )
    new_deformations = list(design.deformations) + [op]
    if body.preview:
        updated = design.copy_with(deformations=new_deformations)
        design_state.set_design_silent(updated)
    else:
        # Truncate suppressed future entries if cursor is not at end.
        # cursor=-2 (empty/F0 state) means all entries are suppressed — clear the log.
        log = list(design.feature_log)
        if design.feature_log_cursor == -2:
            log = []
        elif design.feature_log_cursor >= 0:
            log = log[: design.feature_log_cursor + 1]
        log_entry = DeformationLogEntry(deformation_id=op.id, op_snapshot=op)
        updated = design.copy_with(
            deformations=new_deformations,
            feature_log=log + [log_entry],
            feature_log_cursor=-1,
        )
        design_state.set_design(updated)
    report = validate_design(updated)
    response = _design_response(updated, report)
    _attach_deformation_warning(
        response,
        updated,
        body.type,
        helix_ids,
        body.plane_a_bp,
        body.plane_b_bp,
        params,
    )
    return response


@router.patch("/design/deformation/{op_id}", status_code=200)
def update_deformation(op_id: str, body: UpdateDeformationBody) -> dict:
    """Update params of an existing deformation op (live preview — no undo push)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    ops = list(design.deformations)
    idx = next((i for i, op in enumerate(ops) if op.id == op_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Deformation {op_id!r} not found.")

    old_op = ops[idx]
    try:
        new_params = parse_deformation_params(old_op.type, body.params)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    ops[idx] = old_op.model_copy(update={"params": new_params})

    updated = design.model_copy(update={"deformations": ops}, deep=True)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    response = _design_response(updated, report)
    _attach_deformation_warning(
        response,
        updated,
        old_op.type,
        old_op.affected_helix_ids,
        old_op.plane_a_bp,
        old_op.plane_b_bp,
        new_params,
    )
    return response


@router.delete("/design/deformation/{op_id}", status_code=200)
def delete_deformation(op_id: str, preview: bool = Query(False)) -> dict:
    """Remove a deformation op.

    When preview=true, uses a silent update (no undo push).  Used during
    preview cycles so only confirmed deformations appear in undo history.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    ops = [op for op in design.deformations if op.id != op_id]
    if len(ops) == len(design.deformations):
        raise HTTPException(404, detail=f"Deformation {op_id!r} not found.")

    updated = design.model_copy(update={"deformations": ops}, deep=True)
    if preview:
        design_state.set_design_silent(updated)
    else:
        design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Deformation debug ────────────────────────────────────────────────────────


@router.get("/design/deformation/debug", status_code=200)
def deformation_debug() -> dict:
    """
    Return intermediate deformation-geometry values for every helix.

    Intended for diagnosing bend/twist placement bugs.  Call this BEFORE and
    AFTER applying a deformation to see exactly what centroid, tangent,
    cs_offset, and frame values are used.

    Response shape:
      {
        ops: [ { id, type, plane_a_bp, plane_b_bp, affected_helix_ids, params } ],
        cluster_transforms: [ { id, name, helix_ids, translation, rotation, pivot } ],
        helices: [
          {
            helix_id, bp_start, length_bp,
            axis_start, axis_end,
            arm_helix_ids,          # IDs used after cluster filtering
            centroid_0,             # centroid of arm_helices at bp 0
            tangent_0,              # unit tangent of the arm
            cs_offset,              # radial cross-section offset from centroid
            arm_min_bp_start,
            frames: [               # sampled at key bp values
              { bp_local, bp_global, spine, R_row0, R_row1, R_row2,
                axis_deformed, tangent }
            ]
          }
        ]
      }
    """
    import numpy as np
    from backend.core.deformation import (
        _arm_helices_for,
        _bundle_centroid_and_tangent,
        _cluster_for_helix,
        _frame_at_bp,
    )

    design = design_state.get_or_404()

    def _v(arr) -> list[float]:
        return [round(float(x), 6) for x in arr]

    # ── ops summary ──────────────────────────────────────────────────────────
    ops_out = []
    for op in design.deformations:
        ops_out.append(
            {
                "id": op.id,
                "type": op.type,
                "plane_a_bp": op.plane_a_bp,
                "plane_b_bp": op.plane_b_bp,
                "cluster_ids": list(op.cluster_ids),
                "affected_helix_ids": list(op.affected_helix_ids),
                "params": op.params.model_dump(),
            }
        )

    # ── cluster_transforms summary ───────────────────────────────────────────
    cts_out = []
    for ct in design.cluster_transforms:
        cts_out.append(
            {
                "id": ct.id,
                "name": ct.name,
                "is_default": ct.is_default,
                "helix_ids": list(ct.helix_ids),
                "translation": _v(ct.translation),
                "rotation": _v(ct.rotation),
                "pivot": _v(ct.pivot),
            }
        )

    # ── per-helix breakdown ──────────────────────────────────────────────────
    helices_out = []
    for h in design.helices:
        cluster = _cluster_for_helix(design, h.id)

        arm_all = _arm_helices_for(design, h.id)
        arm_helices = arm_all
        if cluster:
            cluster_ids = set(cluster.helix_ids)
            filtered = [ah for ah in arm_all if ah.id in cluster_ids]
            if filtered:
                arm_helices = filtered

        centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)
        h_start = h.axis_start.to_array()
        cs_raw = h_start - centroid_0
        cs_offset = cs_raw - float(np.dot(cs_raw, tangent_0)) * tangent_0

        arm_min_bp_start = min((ah.bp_start for ah in arm_helices), default=0)

        # ── sample key bp values ─────────────────────────────────────────────
        sample_local_bps: list[int] = [0]
        for op in design.deformations:
            # Only include ops relevant to this helix
            arm_ids = {ah.id for ah in arm_helices}
            if op.affected_helix_ids and not (arm_ids & set(op.affected_helix_ids)):
                continue
            for bp_global in (
                op.plane_a_bp,
                (op.plane_a_bp + op.plane_b_bp) // 2,
                op.plane_b_bp,
            ):
                local = bp_global - arm_min_bp_start
                if 0 <= local < h.length_bp:
                    sample_local_bps.append(local)
            # One step past each plane to see the post-bend tangent
            for bp_global in (op.plane_b_bp + 1, op.plane_b_bp + 5):
                local = bp_global - arm_min_bp_start
                if 0 <= local < h.length_bp:
                    sample_local_bps.append(local)
        sample_local_bps.append(h.length_bp - 1)
        sample_local_bps = sorted(set(sample_local_bps))

        frames_out = []
        for local_bp in sample_local_bps:
            spine_p, R_p, tang = _frame_at_bp(design, local_bp, arm_helices)
            axis_d = spine_p + R_p @ cs_offset
            frames_out.append(
                {
                    "bp_local": local_bp,
                    "bp_global": local_bp + arm_min_bp_start,
                    "spine": _v(spine_p),
                    "axis_deformed": _v(axis_d),
                    "tangent": _v(tang),
                    "R": [_v(R_p[0]), _v(R_p[1]), _v(R_p[2])],
                }
            )

        helices_out.append(
            {
                "helix_id": h.id,
                "bp_start": h.bp_start,
                "length_bp": h.length_bp,
                "axis_start": _v(h.axis_start.to_array()),
                "axis_end": _v(h.axis_end.to_array()),
                "cluster_id": cluster.id if cluster else None,
                "arm_helix_ids": [ah.id for ah in arm_helices],
                "arm_all_ids": [ah.id for ah in arm_all],
                "centroid_0": _v(centroid_0),
                "tangent_0": _v(tangent_0),
                "cs_offset": _v(cs_offset),
                "arm_min_bp_start": arm_min_bp_start,
                "frames": frames_out,
            }
        )

    return {
        "ops": ops_out,
        "cluster_transforms": cts_out,
        "helices": helices_out,
    }
