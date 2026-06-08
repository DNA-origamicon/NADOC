"""
API layer — assembly-animation route handlers (extracted from assembly.py).

This module hosts the seven ``/assembly/animations`` endpoints that mutate the
assembly's named-animation + keyframe list. They were factored out of
``assembly.py`` following the same template as the crud.py sub-router lifts
(``routes_animations.py``, ``routes_camera_poses.py``).

Routes
------
  POST   /assembly/animations                              — create animation
  PATCH  /assembly/animations/{anim_id}                    — update metadata
  DELETE /assembly/animations/{anim_id}                    — remove animation
  POST   /assembly/animations/{anim_id}/keyframes          — append keyframe
  PATCH  /assembly/animations/{anim_id}/keyframes/{kf_id}  — update keyframe (silent)
  DELETE /assembly/animations/{anim_id}/keyframes/{kf_id}  — remove keyframe
  PUT    /assembly/animations/{anim_id}/keyframes/reorder  — reorder keyframes

URLs are unchanged from their previous home in assembly.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
# _assembly_response is the shared assembly response helper (the assembly-side
# twin of crud.py's _design_response). It stays in assembly.py — used by
# every assembly route there — and is imported back here. Same convention as
# routes_camera_poses.py importing _design_response from crud.py.
from backend.api.assembly import _assembly_response
from backend.core.models import AnimationKeyframe, Assembly, DesignAnimation

router = APIRouter()


class CreateAssemblyAnimationBody(BaseModel):
    name: str = "Animation"
    fps: int = 30
    loop: bool = False


class PatchAssemblyAnimationBody(BaseModel):
    name: Optional[str] = None
    fps: Optional[int] = None
    loop: Optional[bool] = None


class CreateAssemblyKeyframeBody(BaseModel):
    name: str = ""
    camera_pose_id: Optional[str] = None
    configuration_id: Optional[str] = None
    hold_duration_s: float = 1.0
    transition_duration_s: float = 0.5
    easing: str = "ease-in-out"
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


class PatchAssemblyKeyframeBody(BaseModel):
    name: Optional[str] = None
    camera_pose_id: Optional[str] = None
    configuration_id: Optional[str] = None
    hold_duration_s: Optional[float] = None
    transition_duration_s: Optional[float] = None
    easing: Optional[str] = None
    spin_axis: Optional[str] = None
    spin_rotations: Optional[float] = None
    spin_invert: Optional[bool] = None
    joint_values: Optional[dict] = None
    text: Optional[str] = None
    text_font_family: Optional[str] = None
    text_font_size_px: Optional[int] = None
    text_color: Optional[str] = None
    text_bold: Optional[bool] = None
    text_italic: Optional[bool] = None
    text_align: Optional[str] = None


class ReorderAssemblyKeyframesBody(BaseModel):
    ordered_ids: list[str]


def _find_animation(assembly: Assembly, anim_id: str) -> DesignAnimation:
    anim = next((a for a in assembly.animations if a.id == anim_id), None)
    if anim is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    return anim


@router.post("/assembly/animations", status_code=200)
def create_assembly_animation(body: CreateAssemblyAnimationBody) -> dict:
    """Create a new named animation on the assembly."""
    assembly = assembly_state.get_or_create()
    anim     = DesignAnimation(name=body.name, fps=body.fps, loop=body.loop)
    updated  = assembly.model_copy(
        update={"animations": list(assembly.animations) + [anim]}, deep=True,
    )
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.patch("/assembly/animations/{anim_id}", status_code=200)
def update_assembly_animation(anim_id: str, body: PatchAssemblyAnimationBody) -> dict:
    """Update animation metadata (name / fps / loop)."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    idx      = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    patch    = body.model_dump(include=body.model_fields_set)
    anims[idx] = anims[idx].model_copy(update=patch)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.delete("/assembly/animations/{anim_id}", status_code=200)
def delete_assembly_animation(anim_id: str) -> dict:
    """Remove an animation from the assembly."""
    assembly = assembly_state.get_or_create()
    anims    = [a for a in assembly.animations if a.id != anim_id]
    if len(anims) == len(assembly.animations):
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.post("/assembly/animations/{anim_id}/keyframes", status_code=200)
def create_assembly_keyframe(anim_id: str, body: CreateAssemblyKeyframeBody) -> dict:
    """
    Append a keyframe to an assembly animation.
    Automatically captures all assembly joint current_values into joint_values.
    """
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    idx      = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    # Auto-capture current joint values
    joint_values = {j.id: j.current_value for j in assembly.joints}

    kf = AnimationKeyframe(
        name=body.name,
        camera_pose_id=body.camera_pose_id,
        configuration_id=body.configuration_id,
        hold_duration_s=body.hold_duration_s,
        transition_duration_s=body.transition_duration_s,
        easing=body.easing,
        spin_axis=body.spin_axis,
        spin_rotations=body.spin_rotations,
        spin_invert=body.spin_invert,
        joint_values=joint_values,
        text=body.text,
        text_font_family=body.text_font_family,
        text_font_size_px=body.text_font_size_px,
        text_color=body.text_color,
        text_bold=body.text_bold,
        text_italic=body.text_italic,
        text_align=body.text_align,
    )
    anims[idx] = anims[idx].model_copy(
        update={"keyframes": list(anims[idx].keyframes) + [kf]}, deep=True,
    )
    updated = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.patch("/assembly/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def update_assembly_keyframe(anim_id: str, kf_id: str, body: PatchAssemblyKeyframeBody) -> dict:
    """Update a keyframe's properties (silent — no undo push for playback frames)."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    kfs      = list(anims[anim_idx].keyframes)
    kf_idx   = next((i for i, k in enumerate(kfs) if k.id == kf_id), None)
    if kf_idx is None:
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")
    patch    = body.model_dump(include=body.model_fields_set)
    kfs[kf_idx] = kfs[kf_idx].model_copy(update=patch)
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.delete("/assembly/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def delete_assembly_keyframe(anim_id: str, kf_id: str) -> dict:
    """Remove a keyframe from an assembly animation."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    kfs = [k for k in anims[anim_idx].keyframes if k.id != kf_id]
    if len(kfs) == len(anims[anim_idx].keyframes):
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.put("/assembly/animations/{anim_id}/keyframes/reorder", status_code=200)
def reorder_assembly_keyframes(anim_id: str, body: ReorderAssemblyKeyframesBody) -> dict:
    """Reorder keyframes by supplying a new ordered list of IDs."""
    assembly = assembly_state.get_or_create()
    anims    = list(assembly.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")
    kf_map   = {k.id: k for k in anims[anim_idx].keyframes}
    reordered = [kf_map[id] for id in body.ordered_ids if id in kf_map]
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": reordered}, deep=True)
    updated  = assembly.model_copy(update={"animations": anims}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)
