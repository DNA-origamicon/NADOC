"""
API layer — assembly workspace-library route handlers (extracted from assembly.py).

This module hosts the workspace file-library endpoints: list/upload/read/mkdir/
rename/move/delete workspace files, the SSE change-event stream, and the two
"save the active design/assembly into the workspace" routes. They were factored
out of ``assembly.py`` following the same template as the other assembly
sub-router lifts (``routes_assembly_animations.py``, ``routes_assembly_configs.py``,
``routes_assembly_linkers.py``).

The pure path/file/remap logic already lives in ``backend.core.workspace`` (the
service push of Refactor #10); these handlers parse the request, call those core
functions, and own only the api-layer concerns: the ``ValueError`` → 400
translation (``_safe_workspace_path``, imported back from assembly.py as shared
glue with the Instance-save region) and the in-memory ``assembly_state`` mutation
in ``_patch_references`` (kept here because core never imports api — L4).

One reason to change: the HTTP surface of the workspace file library (how files
are listed/saved/renamed/moved and how those changes are surfaced to clients).

Routes
------
  GET    /library/files            — list workspace .nadoc/.nass files + folders
  POST   /library/upload           — save a .nadoc/.nass into the workspace
  GET    /library/content          — raw JSON content of a workspace file
  POST   /library/mkdir            — create a workspace folder
  PATCH  /library/rename           — rename a file/folder (+ patch .nass refs)
  POST   /library/move             — move a file/folder (+ patch .nass refs)
  DELETE /library/file             — delete a workspace file/folder
  POST   /design/save-workspace    — write the active design to a workspace file
  POST   /assembly/save            — save the active assembly as a .nass file
  GET    /library/events           — SSE stream of file-changed/-deleted events

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.api import assembly as _asm
from backend.api import assembly_state
from backend.api import state as design_state
from backend.core import workspace as _ws
from backend.core.models import PartSourceFile

# Shared back-imports (count toward B):
#   _safe_workspace_path  — api-layer ValueError→HTTPException wrapper, also used
#                           by the Instance-save region that stays in assembly.py
#                           (L13 shared-glue, imported back rather than duplicated).
#   _assembly_response    — the shared assembly response helper (the assembly-side
#                           twin of crud.py's _design_response); shared kernel.
# The workspace directory is read live via ``_asm._WORKSPACE_DIR`` (module-attribute
# access) so that tests monkeypatching ``assembly._WORKSPACE_DIR`` redirect these
# routes too — preserving the original handlers' read-the-live-global behavior.
from backend.api.assembly import _safe_workspace_path, _assembly_response

router = APIRouter()


# ── Request bodies ────────────────────────────────────────────────────────────

class UploadFileRequest(BaseModel):
    content: str              # raw JSON string
    filename: str             # e.g. "my_part.nadoc"
    dest_path: Optional[str] = None   # explicit workspace-relative path (skips auto-dedup)
    overwrite: bool = False


class SaveAssemblyRequest(BaseModel):
    filename: Optional[str] = None   # stem only (backward compat)
    path: Optional[str] = None       # full workspace-relative path, takes priority over filename
    overwrite: bool = True


class SaveDesignWorkspaceRequest(BaseModel):
    path: str
    overwrite: bool = True


class MkdirRequest(BaseModel):
    path: str   # workspace-relative folder path to create


class RenameRequest(BaseModel):
    path: str       # current workspace-relative path (file or folder)
    new_name: str   # basename only — no path separators


class MoveRequest(BaseModel):
    path: str           # current workspace-relative path
    dest_folder: str    # destination folder (workspace-relative), "" = workspace root


# ── Internal helper (workspace-only; moved out of assembly.py) ─────────────────

def _patch_references(old_ref: str, new_ref: str) -> list[str]:
    """Cascade-update PartSourceFile.path across all on-disk .nass files and the
    in-memory assembly.

    The on-disk patching + remap is the pure core service
    (`backend.core.workspace`); the in-memory assembly mutation stays here
    because it touches `assembly_state` (L4: core never imports api).
    """
    patched = _ws.patch_nass_files(_asm._WORKSPACE_DIR, old_ref, new_ref)
    asm = assembly_state.get_assembly()
    if asm:
        new_asm = _ws.patch_assembly_instances(asm, old_ref, new_ref)
        if new_asm is not None:
            assembly_state.set_assembly_silent(new_asm)
    return patched


# ── Workspace library ─────────────────────────────────────────────────────────

@router.get("/library/files", status_code=200)
def list_library_files() -> list:
    """Scan workspace for .nadoc / .nass files and subdirectories, sorted by mtime desc."""
    _asm._WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for p in _asm._WORKSPACE_DIR.rglob("*"):
        # Skip hidden files / system dirs
        rel_parts = p.relative_to(_asm._WORKSPACE_DIR).parts
        if any(part.startswith(".") or part.startswith("__") for part in rel_parts):
            continue
        try:
            stat     = p.stat()
            rel      = str(p.relative_to(_asm._WORKSPACE_DIR))
            mtime    = _dt.fromtimestamp(stat.st_mtime, tz=_tz.utc).isoformat()
            if p.is_dir():
                entries.append({
                    "name":       p.name,
                    "path":       rel,
                    "type":       "folder",
                    "mtime_iso":  mtime,
                    "size_bytes": 0,
                })
            elif p.suffix in (".nadoc", ".nass"):
                entries.append({
                    "name":       p.stem,
                    "path":       rel,
                    "type":       "assembly" if p.suffix == ".nass" else "part",
                    "mtime_iso":  mtime,
                    "size_bytes": stat.st_size,
                })
        except OSError:
            continue
    entries.sort(key=lambda e: e["mtime_iso"], reverse=True)
    return entries


@router.post("/library/upload", status_code=201)
def upload_library_file(body: UploadFileRequest) -> dict:
    """Save a .nadoc or .nass file to the workspace directory.

    If dest_path is given, write to that exact workspace-relative path (with
    optional overwrite check).  Otherwise auto-dedup in the workspace root.
    """
    fn = body.filename.strip()
    if not fn:
        raise HTTPException(400, detail="filename is required")
    p = Path(fn)
    if p.suffix not in (".nadoc", ".nass"):
        raise HTTPException(400, detail="filename must end with .nadoc or .nass")

    if body.dest_path:
        dest = _safe_workspace_path(body.dest_path)
        if dest.suffix not in (".nadoc", ".nass"):
            raise HTTPException(400, detail="dest_path must end with .nadoc or .nass")
        if not body.overwrite and dest.exists():
            raise HTTPException(409, detail=f"File already exists: {body.dest_path!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        out_rel = body.dest_path
    else:
        safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in p.stem)
        if not safe_stem:
            safe_stem = "file"
        out_rel = _ws.dedup_filename(safe_stem, p.suffix, _asm._WORKSPACE_DIR)
        dest = _asm._WORKSPACE_DIR / out_rel

    dest.write_text(body.content, encoding="utf-8")
    return {
        "path": out_rel,
        "name": Path(out_rel).stem,
        "type": "assembly" if p.suffix == ".nass" else "part",
    }


@router.get("/library/content", status_code=200)
def get_library_file_content(path: str) -> dict:
    """Return the raw JSON content of a workspace file (path relative to workspace)."""
    dest = _safe_workspace_path(path)
    if not dest.is_file():
        raise HTTPException(404, detail=f"File not found in workspace: {path!r}")
    return {"content": dest.read_text(encoding="utf-8")}


@router.post("/library/mkdir", status_code=201)
def library_mkdir(body: MkdirRequest) -> dict:
    """Create a folder (and any missing parents) in the workspace."""
    dest = _safe_workspace_path(body.path)
    if dest.exists() and not dest.is_dir():
        raise HTTPException(400, detail=f"A file already exists at {body.path!r}.")
    dest.mkdir(parents=True, exist_ok=True)
    return {"path": body.path}


@router.patch("/library/rename", status_code=200)
def library_rename(body: RenameRequest) -> dict:
    """Rename a workspace file or folder; auto-patches all .nass references."""
    if "/" in body.new_name or "\\" in body.new_name:
        raise HTTPException(400, detail="new_name must be a plain basename (no path separators).")
    src = _safe_workspace_path(body.path)
    if not src.exists():
        raise HTTPException(404, detail=f"Not found: {body.path!r}")
    dest = src.parent / body.new_name
    if dest.exists() and dest.resolve() != src.resolve():
        raise HTTPException(409, detail=f"{body.new_name!r} already exists in the same folder.")
    is_dir   = src.is_dir()
    old_rel  = str(src.relative_to(_asm._WORKSPACE_DIR))
    new_rel  = str((src.parent / body.new_name).relative_to(_asm._WORKSPACE_DIR))
    src.rename(dest)
    old_ref  = old_rel + "/" if is_dir else old_rel
    new_ref  = new_rel + "/" if is_dir else new_rel
    patched  = _patch_references(old_ref, new_ref)
    return {"old_path": old_rel, "new_path": new_rel, "patched_assemblies": patched}


@router.post("/library/move", status_code=200)
def library_move(body: MoveRequest) -> dict:
    """Move a workspace file or folder to a new directory; auto-patches .nass references."""
    src = _safe_workspace_path(body.path)
    if not src.exists():
        raise HTTPException(404, detail=f"Not found: {body.path!r}")
    if body.dest_folder:
        dest_dir = _safe_workspace_path(body.dest_folder)
        dest_dir.mkdir(parents=True, exist_ok=True)
    else:
        dest_dir = _asm._WORKSPACE_DIR
    dest = dest_dir / src.name
    if dest.resolve() == src.resolve():
        old_rel = str(src.relative_to(_asm._WORKSPACE_DIR))
        return {"old_path": old_rel, "new_path": old_rel, "patched_assemblies": []}
    if dest.exists():
        raise HTTPException(409, detail=f"{src.name!r} already exists in the destination folder.")
    is_dir  = src.is_dir()
    old_rel = str(src.relative_to(_asm._WORKSPACE_DIR))
    shutil.move(str(src), str(dest))
    new_rel = str(dest.relative_to(_asm._WORKSPACE_DIR))
    old_ref = old_rel + "/" if is_dir else old_rel
    new_ref = new_rel + "/" if is_dir else new_rel
    patched = _patch_references(old_ref, new_ref)
    return {"old_path": old_rel, "new_path": new_rel, "patched_assemblies": patched}


@router.delete("/library/file", status_code=200)
def library_delete(path: str) -> dict:
    """Delete a workspace file or folder (folders are deleted recursively)."""
    dest = _safe_workspace_path(path)
    if not dest.exists():
        raise HTTPException(404, detail=f"Not found: {path!r}")
    if dest.is_dir():
        shutil.rmtree(str(dest))
    else:
        dest.unlink()
    return {"path": path}


@router.post("/design/save-workspace", status_code=200)
def save_design_to_workspace(body: SaveDesignWorkspaceRequest) -> dict:
    """Write the active in-memory design to a workspace file."""
    design = design_state.get_or_404()
    dest = _safe_workspace_path(body.path)
    if not body.overwrite and dest.exists():
        raise HTTPException(409, detail=f"File already exists: {body.path!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(design.to_json(), encoding="utf-8")
    return {"path": body.path}


@router.post("/assembly/save", status_code=200)
def save_assembly(body: SaveAssemblyRequest = None) -> dict:
    """Save the active assembly to the workspace as a .nass file.

    Inline PartInstances are auto-converted: their designs are saved as individual
    .nadoc files in the workspace and the instance source is updated to PartSourceFile.
    Returns the updated assembly (with file-backed sources) and the saved path.
    """
    assembly = assembly_state.get_or_404()
    _asm._WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # Convert any inline instances to file-backed
    new_instances = list(assembly.instances)
    changed = False
    for idx, inst in enumerate(new_instances):
        if inst.source.type == "inline":
            design    = inst.source.design
            safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_"
                                for c in (design.metadata.name or inst.name or "part"))
            filename  = _ws.dedup_filename(safe_stem, ".nadoc", _asm._WORKSPACE_DIR)
            (_asm._WORKSPACE_DIR / filename).write_text(design.to_json(), encoding="utf-8")
            new_instances[idx] = inst.model_copy(update={"source": PartSourceFile(path=filename)})
            changed = True

    if changed:
        assembly = assembly.model_copy(update={"instances": new_instances})
        assembly_state.set_assembly_silent(assembly)

    # Determine output path
    if body and body.path:
        if not body.path.endswith(".nass"):
            raise HTTPException(400, detail="path must end with .nass")
        dest    = _safe_workspace_path(body.path)
        if not body.overwrite and dest.exists():
            raise HTTPException(409, detail=f"File already exists: {body.path!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        out_rel = body.path
    else:
        asm_name  = (body.filename if body and body.filename else None) or assembly.metadata.name or "assembly"
        safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in asm_name)
        out_rel   = f"{safe_stem}.nass"
        dest      = _asm._WORKSPACE_DIR / out_rel

    dest.write_text(assembly.to_json(), encoding="utf-8")
    # Only return the full assembly payload when the in-memory state actually
    # changed (inline → file-backed conversion).  A pure persist-to-disk has
    # no client-visible state delta, so omitting the payload prevents the
    # frontend's _syncFromAssemblyResponse from re-storing currentAssembly,
    # which would otherwise fire the renderer's currentAssembly subscriber
    # and trigger a full geometry-refetch rebuild — observed as a multi-
    # second freeze on every Save of a large assembly.
    if changed:
        return {"path": out_rel, **_assembly_response(assembly)}
    return {"path": out_rel}


@router.get("/library/events", status_code=200)
async def library_events_stream():
    """SSE stream: pushes file-changed / file-deleted events for workspace files."""
    from backend.api import library_events

    async def _generator():
        q: asyncio.Queue = asyncio.Queue()
        library_events.subscribe(q)
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type":"ping"}\n\n'
        finally:
            library_events.unsubscribe(q)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
