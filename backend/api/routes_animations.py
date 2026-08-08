"""
API layer — design-animation route handlers (extracted from crud.py).

This module hosts the ``/design/animations`` endpoints: animation CRUD plus
per-animation keyframe CRUD and reorder. They were factored out of
``crud.py`` following the same template as Refactor 13-B (camera poses) and
10-F (loop-skip sub-router extraction).

Routes
------
  POST   /design/animations                                   — create animation (undo)
  PATCH  /design/animations/{anim_id}                         — update metadata (undo)
  DELETE /design/animations/{anim_id}                         — remove animation (undo)
  POST   /design/animations/{anim_id}/keyframes              — append keyframe (undo)
  PATCH  /design/animations/{anim_id}/keyframes/{kf_id}      — update keyframe (silent)
  DELETE /design/animations/{anim_id}/keyframes/{kf_id}      — remove keyframe (undo)
  PUT    /design/animations/{anim_id}/keyframes/reorder      — reorder keyframes (undo)

URLs are unchanged from their previous home in crud.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import state as design_state

# _design_response is a response helper shared with the rest of crud.py's
# route handlers. It stays in crud.py (used by 100+ routes there) and is
# imported here. Same convention as routes_camera_poses.py (13-B).
from backend.api.crud import _design_response
from backend.core.models import AnimationKeyframe, DesignAnimation

router = APIRouter()


class CreateAnimationBody(BaseModel):
    name: str = "Animation"
    fps: int = 30
    loop: bool = False


class PatchAnimationBody(BaseModel):
    name: Optional[str] = None
    fps: Optional[int] = None
    loop: Optional[bool] = None


class CreateKeyframeBody(BaseModel):
    name: str = ""
    camera_pose_id: Optional[str] = None
    feature_log_index: Optional[int] = None
    hold_duration_s: float = 1.0
    transition_duration_s: float = 0.5
    easing: str = "ease-in-out"
    is_trajectory: bool = False
    trajectory_job_id: Optional[str] = None
    trajectory_engine: str = "oxdna"
    trajectory_frame_start: Optional[int] = None
    trajectory_frame_end: Optional[int] = None
    # Which composite frame space start/end index. Validated here rather than only on
    # the model so a typo comes back as a 422 instead of a 500 from model construction.
    trajectory_scope: Optional[Literal["lineage", "job"]] = None
    trajectory_stride: Optional[int] = Field(default=None, ge=1)
    spin_axis: Optional[str] = None
    spin_rotations: float = 0.0
    spin_invert: bool = False
    text: str = ""
    text_font_family: str = "sans-serif"
    text_font_size_px: int = 24
    text_color: str = "#ffffff"
    text_bold: bool = False
    text_italic: bool = False
    text_align: str = "center"
    binding_states: dict[str, float] = Field(default_factory=dict)  # binding id → φ
    strand_anim_phi: dict[str, float] = Field(default_factory=dict)  # overhang id → φ


class PatchKeyframeBody(BaseModel):
    name: Optional[str] = None
    camera_pose_id: Optional[str] = None
    feature_log_index: Optional[int] = None
    hold_duration_s: Optional[float] = None
    transition_duration_s: Optional[float] = None
    easing: Optional[str] = None
    is_trajectory: Optional[bool] = None
    trajectory_job_id: Optional[str] = None
    trajectory_engine: Optional[str] = None
    trajectory_frame_start: Optional[int] = None
    trajectory_frame_end: Optional[int] = None
    # Which composite frame space start/end index. Validated here rather than only on
    # the model so a typo comes back as a 422 instead of a 500 from model construction.
    trajectory_scope: Optional[Literal["lineage", "job"]] = None
    trajectory_stride: Optional[int] = Field(default=None, ge=1)
    spin_axis: Optional[str] = None
    spin_rotations: Optional[float] = None
    spin_invert: Optional[bool] = None
    text: Optional[str] = None
    text_font_family: Optional[str] = None
    text_font_size_px: Optional[int] = None
    text_color: Optional[str] = None
    text_bold: Optional[bool] = None
    text_italic: Optional[bool] = None
    text_align: Optional[str] = None
    binding_states: Optional[dict[str, float]] = None  # binding id → φ
    strand_anim_phi: Optional[dict[str, float]] = None  # overhang id → φ


class ReorderKeyframesBody(BaseModel):
    ordered_ids: List[str]


@router.post("/design/animations", status_code=200)
def create_animation(body: CreateAnimationBody) -> dict:
    """Create a new named animation. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anim = DesignAnimation(name=body.name, fps=body.fps, loop=body.loop)
    updated = design.model_copy(
        update={"animations": list(design.animations) + [anim]}, deep=True
    )
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/animations/{anim_id}", status_code=200)
def update_animation(anim_id: str, body: PatchAnimationBody) -> dict:
    """Update animation metadata (name/fps/loop). Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    patch = body.model_dump(exclude_none=True)
    anims[idx] = anims[idx].model_copy(update=patch)
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/animations/{anim_id}", status_code=200)
def delete_animation(anim_id: str) -> dict:
    """Remove an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = [a for a in design.animations if a.id != anim_id]
    if len(anims) == len(design.animations):
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/animations/{anim_id}/keyframes", status_code=200)
def create_keyframe(anim_id: str, body: CreateKeyframeBody) -> dict:
    """Append a keyframe to an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kf = AnimationKeyframe(
        name=body.name,
        camera_pose_id=body.camera_pose_id,
        feature_log_index=body.feature_log_index,
        hold_duration_s=body.hold_duration_s,
        transition_duration_s=body.transition_duration_s,
        easing=body.easing,
        is_trajectory=body.is_trajectory,
        trajectory_job_id=body.trajectory_job_id,
        trajectory_engine=body.trajectory_engine,
        trajectory_frame_start=body.trajectory_frame_start,
        trajectory_frame_end=body.trajectory_frame_end,
        trajectory_scope=body.trajectory_scope,
        trajectory_stride=body.trajectory_stride,
        spin_axis=body.spin_axis,
        spin_rotations=body.spin_rotations,
        spin_invert=body.spin_invert,
        text=body.text,
        text_font_family=body.text_font_family,
        text_font_size_px=body.text_font_size_px,
        text_color=body.text_color,
        text_bold=body.text_bold,
        text_italic=body.text_italic,
        text_align=body.text_align,
        binding_states=body.binding_states,
        strand_anim_phi=body.strand_anim_phi,
    )
    updated_anim = anims[idx].model_copy(
        update={"keyframes": list(anims[idx].keyframes) + [kf]}, deep=True
    )
    anims[idx] = updated_anim
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def update_keyframe(anim_id: str, kf_id: str, body: PatchKeyframeBody) -> dict:
    """Update a keyframe's properties (silent — no undo push)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kfs = list(anims[anim_idx].keyframes)
    kf_idx = next((i for i, k in enumerate(kfs) if k.id == kf_id), None)
    if kf_idx is None:
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")

    # Use model_fields_set so explicit nulls (e.g. spin_axis=null when clearing
    # spin) propagate. Skipping None values would make the field un-clearable
    # via the API once set — same convention as update_assembly_keyframe.
    patch = body.model_dump(include=body.model_fields_set)
    kfs[kf_idx] = kfs[kf_idx].model_copy(update=patch)
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def delete_keyframe(anim_id: str, kf_id: str) -> dict:
    """Remove a keyframe from an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kfs = [k for k in anims[anim_idx].keyframes if k.id != kf_id]
    if len(kfs) == len(anims[anim_idx].keyframes):
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")

    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.put("/design/animations/{anim_id}/keyframes/reorder", status_code=200)
def reorder_keyframes(anim_id: str, body: ReorderKeyframesBody) -> dict:
    """Reorder keyframes within an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kf_map = {k.id: k for k in anims[anim_idx].keyframes}
    missing = [kid for kid in body.ordered_ids if kid not in kf_map]
    if missing:
        raise HTTPException(400, detail=f"Unknown keyframe IDs: {missing}")

    reordered = [kf_map[kid] for kid in body.ordered_ids]
    listed = set(body.ordered_ids)
    reordered += [k for k in anims[anim_idx].keyframes if k.id not in listed]

    anims[anim_idx] = anims[anim_idx].model_copy(
        update={"keyframes": reordered}, deep=True
    )
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)
