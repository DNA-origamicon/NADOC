"""
API layer — camera-pose route handlers (extracted from crud.py).

This module hosts the four ``/design/camera-poses`` endpoints that mutate
the named-camera-pose list. They were factored out of ``crud.py``
(Refactor 13-B) following the same template as Refactor 10-F (loop-skip
sub-router extraction).

Routes
------
  POST   /design/camera-poses           — add a named camera pose (undo)
  PATCH  /design/camera-poses/{id}      — update an existing pose (silent, no undo)
  DELETE /design/camera-poses/{id}      — remove a camera pose (undo)
  PUT    /design/camera-poses/reorder   — reorder by full ID list (undo)

URLs are unchanged from their previous home in crud.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
# _design_response is a response helper shared with the rest of crud.py's
# route handlers. It stays in crud.py (used by 100+ routes there) and is
# imported here. Same convention as routes_loop_skip.py (10-F).
from backend.api.crud import _design_response
from backend.core.models import CameraPose

router = APIRouter()


class CreateCameraPoseBody(BaseModel):
    name: str = "Camera Pose"
    position: List[float]   # [x, y, z]
    target: List[float]     # [x, y, z]
    up: List[float]         # [x, y, z]
    fov: float = 55.0
    orbit_mode: str = "trackball"


class PatchCameraPoseBody(BaseModel):
    name: Optional[str] = None
    position: Optional[List[float]] = None
    target: Optional[List[float]] = None
    up: Optional[List[float]] = None
    fov: Optional[float] = None
    orbit_mode: Optional[str] = None


class ReorderCameraPosesBody(BaseModel):
    ordered_ids: List[str]


@router.post("/design/camera-poses", status_code=200)
def create_camera_pose(body: CreateCameraPoseBody) -> dict:
    """Save a new named camera pose. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    pose = CameraPose(
        name=body.name,
        position=body.position,
        target=body.target,
        up=body.up,
        fov=body.fov,
        orbit_mode=body.orbit_mode,
    )
    updated = design.model_copy(
        update={"camera_poses": list(design.camera_poses) + [pose]}, deep=True
    )
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/camera-poses/{pose_id}", status_code=200)
def update_camera_pose(pose_id: str, body: PatchCameraPoseBody) -> dict:
    """Rename or overwrite an existing camera pose (silent — no undo push)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    poses = list(design.camera_poses)
    idx = next((i for i, p in enumerate(poses) if p.id == pose_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")

    patch = body.model_dump(exclude_none=True)
    poses[idx] = poses[idx].model_copy(update=patch)
    updated = design.model_copy(update={"camera_poses": poses}, deep=True)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/camera-poses/{pose_id}", status_code=200)
def delete_camera_pose(pose_id: str) -> dict:
    """Remove a camera pose. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    poses = [p for p in design.camera_poses if p.id != pose_id]
    if len(poses) == len(design.camera_poses):
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")

    updated = design.model_copy(update={"camera_poses": poses}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.put("/design/camera-poses/reorder", status_code=200)
def reorder_camera_poses(body: ReorderCameraPosesBody) -> dict:
    """Reorder camera poses by providing a full ordered list of IDs. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    pose_map = {p.id: p for p in design.camera_poses}
    missing = [pid for pid in body.ordered_ids if pid not in pose_map]
    if missing:
        raise HTTPException(400, detail=f"Unknown pose IDs: {missing}")

    reordered = [pose_map[pid] for pid in body.ordered_ids]
    # Include any poses not listed in ordered_ids at the end (safety net)
    listed = set(body.ordered_ids)
    reordered += [p for p in design.camera_poses if p.id not in listed]

    updated = design.model_copy(update={"camera_poses": reordered}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)
