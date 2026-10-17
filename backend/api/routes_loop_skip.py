"""
API layer — loop/skip route handlers (extracted from crud.py).

This module hosts the 5 ``/design/loop-skip/*`` endpoints that mutate or
query loop/skip topology modifications. They were factored out of
``crud.py`` (Refactor 10-F) as the first FastAPI sub-router extraction;
the same pattern can be applied to other route clusters in subsequent
passes.

Routes
------
  POST   /design/loop-skip/insert   — insert/remove a single loop or skip
  POST   /design/loop-skip/twist    — apply twist via loop/skip strain
  POST   /design/loop-skip/bend     — apply bend via loop/skip strain
  GET    /design/loop-skip/limits   — query physical min/max
  DELETE /design/loop-skip          — clear modifications in a bp range

URLs are unchanged from their previous home in crud.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.

The ``apply-deformations`` and ``clear-all`` loop-skip endpoints remain
in crud.py for now (out of scope for 10-F; deferred to a follow-up).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.api import state as design_state

# _design_response is a response helper shared with
# the rest of crud.py's route handlers. It stays in crud.py (used by 100+
# routes there) and is imported here; it is not loop-skip specific.
from backend.api.crud import _design_response

router = APIRouter()


class LoopSkipInsertRequest(BaseModel):
    helix_id: str
    bp_index: int
    delta: int  # +1 = loop (insertion), -1 = skip (deletion), 0 = remove existing


@router.post("/design/loop-skip/insert", status_code=200)
def insert_loop_skip(body: LoopSkipInsertRequest) -> dict:
    """Insert or remove a single loop/skip modification at a bp position.

    delta=+1 inserts a loop (extra bp), delta=-1 inserts a skip (deleted bp),
    delta=0 removes any existing modification at that position.
    """
    from backend.api.part_routing_recording import record_loop_skip

    updated, report, _summary = record_loop_skip("loop-skip-insert", body.model_dump(mode="json"))
    return _design_response(updated, report)


@router.post("/design/loop-skip/twist", status_code=200)
def apply_twist_loop_skips(body: dict) -> dict:
    """
    Compute and apply loop/skip modifications to produce target global twist.

    Body:
      helix_ids   : list[str]  — helices to modify (must all cross both planes)
      plane_a_bp  : int        — start of modified segment (bp index)
      plane_b_bp  : int        — end of modified segment (bp index)
      target_twist_deg : float — desired twist (+ = left-handed, − = right-handed)

    Returns the full design response plus a "loop_skips" summary:
      { helix_id: [ { bp_index, delta }, ... ], ... }

    Raises 422 if target exceeds physical limits.
    """
    from backend.api.part_routing_recording import record_loop_skip

    updated, report, summary = record_loop_skip("loop-skip-twist", body)
    response = _design_response(updated, report)
    response["loop_skips"] = summary
    return response


@router.post("/design/loop-skip/bend", status_code=200)
def apply_bend_loop_skips(body: dict) -> dict:
    """
    Compute and apply loop/skip modifications to produce target bend radius.

    Body:
      helix_ids    : list[str]
      plane_a_bp   : int
      plane_b_bp   : int
      radius_nm    : float  — desired radius of curvature (nm); minimum ≈ 5 nm
      direction_deg: float  — bend direction in cross-section (0 = +X)

    Raises 422 if radius is below the physical minimum for this cross-section.
    """
    from backend.api.part_routing_recording import record_loop_skip

    updated, report, summary = record_loop_skip("loop-skip-bend", body)
    response = _design_response(updated, report)
    response["loop_skips"] = summary
    return response


@router.get("/design/loop-skip/limits", status_code=200)
def get_loop_skip_limits(
    helix_ids: str = Query(..., description="comma-separated helix IDs"),
    plane_a_bp: int = Query(...),
    plane_b_bp: int = Query(...),
    direction_deg: float = Query(0.0),
) -> dict:
    """
    Return the physical limits for loop/skip modifications over the given segment.

    Returns:
      min_bend_radius_nm : float  — minimum achievable radius (nm)
      max_twist_deg      : float  — maximum |twist| achievable
      n_cells            : int    — number of 7-bp array cells in the segment
    """
    from backend.core.loop_skip_calculator import (
        _cell_boundaries,
        max_twist_deg,
        min_bend_radius_nm,
    )

    design = design_state.get_or_404()
    ids = [s.strip() for s in helix_ids.split(",") if s.strip()]
    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in ids if hid in h_map]

    cells = _cell_boundaries(plane_a_bp, plane_b_bp)
    n_cells = len(cells)
    min_r = min_bend_radius_nm(segment_helices, plane_a_bp, plane_b_bp, direction_deg)
    max_t = max_twist_deg(n_cells)

    return {
        "min_bend_radius_nm": min_r if min_r != float("inf") else None,
        "max_twist_deg": max_t,
        "n_cells": n_cells,
    }


class DeformationValidateRequest(BaseModel):
    targets: list[dict] | None = None
    type: str  # 'twist' | 'bend'
    plane_a_bp: int
    plane_b_bp: int
    helix_ids: list[str] = []
    cluster_ids: list[str] = []
    params: dict = {}  # raw TwistParams | BendParams fields


@router.post("/design/deformation/validate", status_code=200)
def validate_deformation(body: DeformationValidateRequest) -> dict:
    """Predict + classify a bend/twist WITHOUT mutating the design.

    Returns ``classify_deformation(...)`` raw — ALWAYS HTTP 200. The verdict is
    carried in the ``status`` field ('ok' | 'warn' | 'block'); WARN/BLOCK never
    raise here so the frontend can poll this live as the user drags sliders.
    The hard 422 stays at realize time (apply-deformations / loop-skip/{twist,bend}).
    """
    from backend.core.deformation import (
        helices_crossing_planes,
        parse_deformation_params,
        resolve_cluster_scope,
    )
    from backend.core.loop_skip_calculator import classify_deformation

    design = design_state.get_or_404()
    try:
        params = parse_deformation_params(body.type, body.params)
    except ValueError as e:
        raise HTTPException(400, detail=str(e))

    helix_ids = body.helix_ids or helices_crossing_planes(
        design, body.plane_a_bp, body.plane_b_bp
    )
    helix_ids = resolve_cluster_scope(design, body.cluster_ids, helix_ids)["helix_ids"]

    ranges = None
    if body.targets is not None:
        from backend.core.deformation_scope import resolve_deformation_targets
        try:
            ranges = resolve_deformation_targets(design, body.targets)
        except ValueError as error:
            raise HTTPException(400, detail=str(error)) from error
        helix_ids = sorted({r.helix_id for r in ranges})
        if body.plane_a_bp >= body.plane_b_bp or not any(
                r.start_bp < body.plane_b_bp and r.end_bp > body.plane_a_bp for r in ranges):
            raise HTTPException(400, detail="Selection does not intersect an ordered deformation window")

    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in helix_ids if hid in h_map]

    result = classify_deformation(
        segment_helices,
        body.plane_a_bp,
        body.plane_b_bp,
        body.type,
        params,
        design=design,
    )

    from backend.core.deformation_scope import selection_boundary_warning
    boundary = selection_boundary_warning(design, ranges)
    if boundary:
        result = {**result, 'status': result['status'] if result['status'] != 'ok' else 'warn',
                  'message': ' '.join(filter(None, [result.get('message'), boundary['message']]))}
    return result


@router.delete("/design/loop-skip", status_code=200)
def clear_loop_skip_range(
    helix_ids: str = Query(..., description="comma-separated helix IDs"),
    plane_a_bp: int = Query(...),
    plane_b_bp: int = Query(...),
) -> dict:
    """Remove all loop/skip modifications in [plane_a_bp, plane_b_bp) from the given helices."""
    from backend.core.loop_skip_calculator import clear_loop_skips

    ids = [s.strip() for s in helix_ids.split(",") if s.strip()]
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="loop-skip-clear", label="Clear loop/skip range",
        params={"helix_ids": ids, "plane_a_bp": plane_a_bp, "plane_b_bp": plane_b_bp},
        fn=lambda d: clear_loop_skips(d, ids, plane_a_bp, plane_b_bp))
    return _design_response(updated, report)
