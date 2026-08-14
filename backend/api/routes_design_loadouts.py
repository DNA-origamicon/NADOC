"""HTTP ownership for active-design loadout branch operations."""

from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state
from backend.api.crud import _design_response, _design_response_with_geometry
from backend.core.design_loadouts import (
    decode_snapshot,
    encode_snapshot,
    ensure_loadouts,
    next_default_name,
    save_active_snapshot,
)
from backend.core.models import DesignLoadout
from backend.core.validator import validate_design

router = APIRouter()


class LoadoutCreateBody(BaseModel):
    name: Optional[str] = None


class LoadoutRenameBody(BaseModel):
    name: str


@router.post("/design/loadouts", status_code=200)
def create_loadout(body: LoadoutCreateBody) -> dict:
    current = design_state.get_or_404()
    loadouts, active_id = ensure_loadouts(current)
    loadouts = save_active_snapshot(current, loadouts, active_id)
    name = (body.name or "").strip() or next_default_name(loadouts)
    new_id = str(uuid.uuid4())
    payload, size = encode_snapshot(current)
    loadouts.append(
        DesignLoadout(
            id=new_id,
            name=name,
            design_snapshot_gz_b64=payload,
            snapshot_size_bytes=size,
        )
    )
    updated = current.copy_with(loadouts=loadouts, active_loadout_id=new_id)
    design_state.set_design(updated)
    return _design_response_with_geometry(updated, validate_design(updated))


@router.post("/design/loadouts/{loadout_id}/select", status_code=200)
def select_loadout(loadout_id: str, save_current: bool = True) -> dict:
    """Save the current branch, unless requested otherwise, then restore one."""
    current = design_state.get_or_404()
    loadouts, active_id = ensure_loadouts(current)
    if save_current:
        loadouts = save_active_snapshot(current, loadouts, active_id)
    selected = next((item for item in loadouts if item.id == loadout_id), None)
    if selected is None:
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    try:
        restored = decode_snapshot(selected.design_snapshot_gz_b64)
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to restore loadout: {exc}") from exc
    last_editable_id = current.last_editable_loadout_id
    if not selected.protected:
        last_editable_id = selected.id
    updated = restored.copy_with(
        loadouts=loadouts,
        active_loadout_id=loadout_id,
        last_editable_loadout_id=last_editable_id,
    )
    design_state.set_design_branch(updated)
    return _design_response_with_geometry(updated, validate_design(updated))


@router.post("/design/loadouts/activate-editable", status_code=200)
def activate_last_editable_loadout() -> dict:
    current = design_state.get_or_404()
    loadouts, _active_id = ensure_loadouts(current)
    target = next(
        (
            item
            for item in loadouts
            if item.id == current.last_editable_loadout_id and not item.protected
        ),
        None,
    )
    if target is None:
        target = next((item for item in loadouts if not item.protected), None)
    if target is None:
        raise HTTPException(409, detail="No editable loadout is available.")
    try:
        restored = decode_snapshot(target.design_snapshot_gz_b64)
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to restore editable loadout: {exc}") from exc
    updated = restored.copy_with(
        loadouts=loadouts,
        active_loadout_id=target.id,
        last_editable_loadout_id=target.id,
    )
    design_state.set_design_branch(updated, push_history=False)
    return _design_response_with_geometry(updated, validate_design(updated))


@router.patch("/design/loadouts/{loadout_id}", status_code=200)
def rename_loadout(loadout_id: str, body: LoadoutRenameBody) -> dict:
    design = design_state.get_or_404()
    loadouts, active_id = ensure_loadouts(design)
    if loadout_id == "__implicit_loadout_1__":
        loadout_id = active_id
    name = body.name.strip()
    if not name:
        raise HTTPException(400, detail="Loadout name cannot be empty.")
    if not any(item.id == loadout_id for item in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    if any(item.id == loadout_id and item.protected for item in loadouts):
        raise HTTPException(400, detail="Simulation loadouts cannot be renamed.")
    loadouts = [
        item.model_copy(update={"name": name}) if item.id == loadout_id else item
        for item in loadouts
    ]
    updated = design.copy_with(loadouts=loadouts, active_loadout_id=active_id)
    design_state.set_design(updated)
    return _design_response(updated, validate_design(updated))


@router.delete("/design/loadouts/{loadout_id}", status_code=200)
def delete_loadout(loadout_id: str) -> dict:
    current = design_state.get_or_404()
    loadouts, active_id = ensure_loadouts(current)
    if len(loadouts) <= 1:
        raise HTTPException(400, detail="Cannot delete the only loadout.")
    if not any(item.id == loadout_id for item in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    if any(item.id == loadout_id and item.protected for item in loadouts):
        raise HTTPException(400, detail="Simulation loadouts cannot be deleted.")
    loadouts = save_active_snapshot(current, loadouts, active_id)
    remaining = [item for item in loadouts if item.id != loadout_id]
    next_id = active_id if active_id != loadout_id else remaining[0].id
    if next_id == active_id:
        updated = current.copy_with(loadouts=remaining, active_loadout_id=next_id)
    else:
        try:
            restored = decode_snapshot(remaining[0].design_snapshot_gz_b64)
        except Exception as exc:
            raise HTTPException(500, detail=f"Failed to restore next loadout: {exc}") from exc
        updated = restored.copy_with(loadouts=remaining, active_loadout_id=next_id)
    design_state.set_design(updated)
    return _design_response_with_geometry(updated, validate_design(updated))
