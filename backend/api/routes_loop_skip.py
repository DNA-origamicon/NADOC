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
# _design_response and _helix_label are response/label helpers shared with
# the rest of crud.py's route handlers. They stay in crud.py (used by 100+
# routes there) and are imported here. This is a deliberate cross-module
# import — the helpers are not loop-skip specific.
from backend.api.crud import _design_response, _helix_label

router = APIRouter()


class LoopSkipInsertRequest(BaseModel):
    helix_id: str
    bp_index: int
    delta: int   # +1 = loop (insertion), -1 = skip (deletion), 0 = remove existing


@router.post("/design/loop-skip/insert", status_code=200)
def insert_loop_skip(body: LoopSkipInsertRequest) -> dict:
    """Insert or remove a single loop/skip modification at a bp position.

    delta=+1 inserts a loop (extra bp), delta=-1 inserts a skip (deleted bp),
    delta=0 removes any existing modification at that position.
    """
    from backend.core.models import LoopSkip
    from backend.core.loop_skip_calculator import apply_loop_skips

    design = design_state.get_or_404()

    helix = design.find_helix(body.helix_id)
    if helix is None:
        raise HTTPException(404, detail=f"Helix '{body.helix_id}' not found")
    if body.delta not in (-1, 0, 1):
        raise HTTPException(400, detail=f"delta must be -1, 0, or +1, got {body.delta}")
    # Range check only applies when inserting — removals (delta=0) must always
    # succeed so stale out-of-range skips can be cleared.
    if body.delta != 0 and (body.bp_index < helix.bp_start or body.bp_index >= helix.bp_start + helix.length_bp):
        raise HTTPException(400, detail=f"bp_index {body.bp_index} out of range [{helix.bp_start}, {helix.bp_start + helix.length_bp - 1}]")

    if body.delta == 0:
        # Remove any existing loop/skip at this position
        new_ls = [ls for ls in helix.loop_skips if ls.bp_index != body.bp_index]
        new_helix = helix.model_copy(update={"loop_skips": new_ls})
        new_helices = [new_helix if h.id == body.helix_id else h for h in design.helices]
        updated = design.model_copy(update={"helices": new_helices})
        kind = "Remove loop/skip"
    else:
        updated = apply_loop_skips(design, {body.helix_id: [LoopSkip(bp_index=body.bp_index, delta=body.delta)]})
        kind = "Loop" if body.delta > 0 else "Skip"

    label = f"{kind} · helix {_helix_label(design, body.helix_id)} bp {body.bp_index}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='loop-skip-insert',
        label=label,
        params=body.model_dump(mode='json'),
        fn=lambda _d: updated,
    )
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
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        twist_loop_skips,
    )

    design = design_state.get_or_404()
    helix_ids: list[str] = body.get("helix_ids", [])
    plane_a_bp: int = int(body["plane_a_bp"])
    plane_b_bp: int = int(body["plane_b_bp"])
    target_twist_deg: float = float(body["target_twist_deg"])

    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in helix_ids if hid in h_map]
    if not segment_helices:
        raise HTTPException(422, "No valid helix_ids provided.")

    try:
        mods = twist_loop_skips(segment_helices, plane_a_bp, plane_b_bp, target_twist_deg)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    updated = apply_loop_skips(design, mods)
    label = f"Twist {target_twist_deg:+.1f}° · {len(segment_helices)} helices · bp [{plane_a_bp}, {plane_b_bp}]"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='loop-skip-twist',
        label=label,
        params=body,
        fn=lambda _d: updated,
    )
    response = _design_response(updated, report)
    response["loop_skips"] = {
        hid: [{"bp_index": ls.bp_index, "delta": ls.delta} for ls in lst]
        for hid, lst in mods.items()
    }
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
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        bend_loop_skips,
    )

    design = design_state.get_or_404()
    helix_ids: list[str] = body.get("helix_ids", [])
    plane_a_bp: int = int(body["plane_a_bp"])
    plane_b_bp: int = int(body["plane_b_bp"])
    radius_nm: float = float(body["radius_nm"])
    direction_deg: float = float(body.get("direction_deg", 0.0))

    if radius_nm <= 0:
        raise HTTPException(422, "radius_nm must be positive.")

    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in helix_ids if hid in h_map]
    if not segment_helices:
        raise HTTPException(422, "No valid helix_ids provided.")

    try:
        mods = bend_loop_skips(segment_helices, plane_a_bp, plane_b_bp, radius_nm, direction_deg)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    updated = apply_loop_skips(design, mods)
    label = f"Bend r={radius_nm:.1f} nm · {len(segment_helices)} helices · bp [{plane_a_bp}, {plane_b_bp}]"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='loop-skip-bend',
        label=label,
        params=body,
        fn=lambda _d: updated,
    )
    response = _design_response(updated, report)
    response["loop_skips"] = {
        hid: [{"bp_index": ls.bp_index, "delta": ls.delta} for ls in lst]
        for hid, lst in mods.items()
    }
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
        "max_twist_deg":      max_t,
        "n_cells":            n_cells,
    }


@router.delete("/design/loop-skip", status_code=200)
def clear_loop_skip_range(
    helix_ids: str = Query(..., description="comma-separated helix IDs"),
    plane_a_bp: int = Query(...),
    plane_b_bp: int = Query(...),
) -> dict:
    """Remove all loop/skip modifications in [plane_a_bp, plane_b_bp) from the given helices."""
    from backend.core.loop_skip_calculator import clear_loop_skips

    design = design_state.get_or_404()
    ids = [s.strip() for s in helix_ids.split(",") if s.strip()]
    updated = clear_loop_skips(design, ids, plane_a_bp, plane_b_bp)
    updated, report = design_state.replace_with_reconcile(updated)
    return _design_response(updated, report)
