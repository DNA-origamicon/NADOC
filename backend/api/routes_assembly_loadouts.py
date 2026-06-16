"""
API layer — assembly per-instance loadout route handlers (extracted from assembly.py).

A "loadout" is a saved design snapshot for a single PartInstance: the user can
stash several alternative designs (different staple sets, sequences, …) for the
same physical part and switch between them without re-importing. Each loadout
stores a gzip+base64 snapshot of the full Design; the active one is restored into
the instance's source file. These four routes (create / select / rename / delete)
are the assembly-side mirror of crud.py's `/design/loadouts/*` routes, operating
on the design backing a specific instance instead of the active design.

This module hosts that cohesive create/select/rename/delete cluster, factored out
of ``assembly.py`` following the same template as the other assembly-side
sub-routers (``routes_assembly_belts.py``, ``routes_assembly_configs.py``).

Routes
------
  POST   /assembly/instances/{instance_id}/loadouts                       — create
  POST   /assembly/instances/{instance_id}/loadouts/{loadout_id}/select   — switch
  PATCH  /assembly/instances/{instance_id}/loadouts/{loadout_id}          — rename
  DELETE /assembly/instances/{instance_id}/loadouts/{loadout_id}          — delete

Back-imports (B=5 — all shared kernel/infrastructure, zero bespoke): ``_assembly_response``
(shared kernel, the assembly-side twin of crud.py's ``_design_response``),
``_find_instance`` (the many-caller shared instance lookup), the file-IO design-load
infra ``_load_design_from_source`` / ``_assembly_source_path`` (L4-blocked, 20+ shared
callers), and ``_replace_instance_design`` (the shared cross-region helper that writes a
resolved instance design back to its workspace file + commits via ``assembly_state`` —
L4-blocked by file-IO + state mutation, also called by the instance-design routes that
stay in assembly.py). The two loadout-only request models moved IN. The per-loadout
encode/decode/snapshot helpers (``_ensure_loadouts``/``_save_active_loadout_snapshot``/
``_auto_loadout_name``/``_encode_loadout_design_snapshot``/``_decode_loadout_design_snapshot``)
are imported function-locally from ``crud`` exactly as before (shared with the design-side
loadout routes; the function-local import also avoids a circular import).

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api.assembly import (
    _assembly_response,
    _assembly_source_path,
    _find_instance,
    _load_design_from_source,
    _replace_instance_design,
)

router = APIRouter()


class InstanceLoadoutCreateRequest(BaseModel):
    name: Optional[str] = None


class InstanceLoadoutRenameRequest(BaseModel):
    name: str


@router.post("/assembly/instances/{instance_id}/loadouts", status_code=200)
def create_instance_loadout(instance_id: str, body: InstanceLoadoutCreateRequest) -> dict:
    from backend.api import crud as crud_api
    from backend.core.models import DesignLoadout

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    current = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(current)
    loadouts = crud_api._save_active_loadout_snapshot(current, loadouts, active_id)
    name = (body.name or "").strip() or crud_api._auto_loadout_name(loadouts)
    new_id = str(_uuid.uuid4())
    payload, size = crud_api._encode_loadout_design_snapshot(current)
    loadouts.append(DesignLoadout(
        id=new_id,
        name=name,
        design_snapshot_gz_b64=payload,
        snapshot_size_bytes=size,
    ))
    updated_design = current.copy_with(loadouts=loadouts, active_loadout_id=new_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


@router.post("/assembly/instances/{instance_id}/loadouts/{loadout_id}/select", status_code=200)
def select_instance_loadout(instance_id: str, loadout_id: str) -> dict:
    from backend.api import crud as crud_api

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    current = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(current)
    loadouts = crud_api._save_active_loadout_snapshot(current, loadouts, active_id)
    selected = next((l for l in loadouts if l.id == loadout_id), None)
    if selected is None:
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    try:
        restored = crud_api._decode_loadout_design_snapshot(selected.design_snapshot_gz_b64)
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to restore loadout: {exc}") from exc
    updated_design = restored.copy_with(loadouts=loadouts, active_loadout_id=loadout_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


@router.patch("/assembly/instances/{instance_id}/loadouts/{loadout_id}", status_code=200)
def rename_instance_loadout(instance_id: str, loadout_id: str, body: InstanceLoadoutRenameRequest) -> dict:
    from backend.api import crud as crud_api

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    design = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(design)
    if loadout_id == "__implicit_loadout_1__":
        loadout_id = active_id
    name = body.name.strip()
    if not name:
        raise HTTPException(400, detail="Loadout name cannot be empty.")
    if not any(l.id == loadout_id for l in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    loadouts = [
        l.model_copy(update={"name": name}) if l.id == loadout_id else l
        for l in loadouts
    ]
    updated_design = design.copy_with(loadouts=loadouts, active_loadout_id=active_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}


@router.delete("/assembly/instances/{instance_id}/loadouts/{loadout_id}", status_code=200)
def delete_instance_loadout(instance_id: str, loadout_id: str) -> dict:
    from backend.api import crud as crud_api

    assembly = assembly_state.get_or_404()
    inst = _find_instance(assembly, instance_id)
    current = _load_design_from_source(inst.source, _assembly_source_path(assembly))
    loadouts, active_id = crud_api._ensure_loadouts(current)
    if len(loadouts) <= 1:
        raise HTTPException(400, detail="Cannot delete the only loadout.")
    if not any(l.id == loadout_id for l in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    loadouts = crud_api._save_active_loadout_snapshot(current, loadouts, active_id)
    remaining = [l for l in loadouts if l.id != loadout_id]
    next_id = active_id if active_id != loadout_id else remaining[0].id
    if next_id == active_id:
        updated_design = current.copy_with(loadouts=remaining, active_loadout_id=next_id)
    else:
        try:
            restored = crud_api._decode_loadout_design_snapshot(remaining[0].design_snapshot_gz_b64)
        except Exception as exc:
            raise HTTPException(500, detail=f"Failed to restore next loadout: {exc}") from exc
        updated_design = restored.copy_with(loadouts=remaining, active_loadout_id=next_id)
    updated_assembly, _ = _replace_instance_design(assembly, inst, updated_design)
    return {**_assembly_response(updated_assembly), "design": updated_design.model_dump(mode="json")}
