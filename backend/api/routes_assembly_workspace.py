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
import json
import os
import shutil
import tempfile
import threading
import zipfile
import uuid
from datetime import datetime as _dt, timezone as _tz
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.background import BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from backend.api import assembly as _asm
from backend.api import assembly_state
from backend.api import state as design_state
from backend.core import workspace as _ws
from backend.core.job_cleanup import (
    find_associated_jobs,
    reassign_job_snapshot_identity,
    remap_design_source_paths,
)
from backend.core.models import Design, PartSourceFile

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

_identity_audit_lock = threading.Lock()
_identity_auditing: set[str] = set()
_identity_audited: set[str] = set()


def _atomic_write_text(path: Path, content: str) -> None:
    """Replace a workspace JSON file without exposing a partial background write."""
    temporary = path.with_name(f".{path.name}.identity-{threading.get_ident()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def _audit_workspace_design_identities(workspace_dir: Path | None = None) -> None:
    """Resolve duplicate legacy UUIDs deterministically before library use."""
    from backend.core.design_identity import (
        fork_identity_for_copy,
        normalize_workspace_path,
        reconcile_open_identity,
    )

    workspace_dir = workspace_dir or _asm._WORKSPACE_DIR
    records: list[tuple[Path, str, Design]] = []
    for path in sorted(workspace_dir.rglob("*.nadoc")):
        rel_parts = path.relative_to(workspace_dir).parts
        if any(part.startswith(".") or part.startswith("__") for part in rel_parts):
            continue
        try:
            design = Design.from_json(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        rel = str(path.relative_to(workspace_dir)).replace("\\", "/")
        records.append((path, rel, design))

    groups: dict[str, list[tuple[Path, str, Design]]] = {}
    for record in records:
        groups.setdefault(record[2].id, []).append(record)
    for group in groups.values():
        matching = [
            r
            for r in group
            if normalize_workspace_path(r[2].metadata.identity_last_known_path) == r[1]
        ]
        owner = (matching or group)[0]
        for path, rel, design in group:
            if path == owner[0]:
                resolved, _, _ = reconcile_open_identity(design, rel, workspace_dir)
            else:
                resolved = fork_identity_for_copy(design, rel)
            if resolved != design:
                _atomic_write_text(path, resolved.to_json())
                if resolved.id != design.id:
                    reassign_job_snapshot_identity(
                        workspace_dir, rel, design.id, resolved.id
                    )
    from backend.core.project_revisions import migrate_job_revision_provenance

    migrate_job_revision_provenance(workspace_dir)


def _schedule_workspace_identity_audit() -> None:
    """Run the legacy whole-workspace migration once, off the listing hot path."""
    workspace_dir = _asm._WORKSPACE_DIR.resolve()
    workspace = str(workspace_dir)
    with _identity_audit_lock:
        if workspace in _identity_audited or workspace in _identity_auditing:
            return
        _identity_auditing.add(workspace)

    def run() -> None:
        try:
            _audit_workspace_design_identities(workspace_dir)
            with _identity_audit_lock:
                _identity_audited.add(workspace)
        finally:
            with _identity_audit_lock:
                _identity_auditing.discard(workspace)

    threading.Thread(target=run, name="nadoc-identity-audit", daemon=True).start()


def _workspace_entries() -> list[dict]:
    """List user-visible workspace metadata without walking engine job trees."""
    entries: list[dict] = []
    workspace = _asm._WORKSPACE_DIR
    for root, dirs, files in os.walk(workspace):
        root_path = Path(root)
        rel_root = root_path.relative_to(workspace)
        dirs[:] = sorted(
            d
            for d in dirs
            if not _ws.is_internal_workspace_path(rel_root / d)
        )

        for dirname in dirs:
            p = root_path / dirname
            rel = str(p.relative_to(workspace))
            try:
                stat = p.stat()
            except OSError:
                continue
            entries.append(
                {
                    "name": dirname,
                    "path": rel,
                    "type": "folder",
                    "mtime_iso": _dt.fromtimestamp(
                        stat.st_mtime, tz=_tz.utc
                    ).isoformat(),
                    "size_bytes": 0,
                }
            )

        for filename in files:
            if filename.startswith((".", "__")):
                continue
            p = root_path / filename
            if p.suffix not in (".nadoc", ".nass"):
                continue
            try:
                stat = p.stat()
            except OSError:
                continue
            rel = str(p.relative_to(workspace))
            entries.append(
                {
                    "name": p.stem,
                    "path": rel,
                    "type": "assembly" if p.suffix == ".nass" else "part",
                    "mtime_iso": _dt.fromtimestamp(
                        stat.st_mtime, tz=_tz.utc
                    ).isoformat(),
                    "size_bytes": stat.st_size,
                }
            )
    entries.sort(key=lambda e: e["mtime_iso"], reverse=True)
    return entries


def _reconcile_nadoc_file(
    path: Path, rel_path: str
) -> tuple[Design | None, str | None]:
    """Reconcile a persisted part's UUID/path signoff and write migrations in place."""
    if path.suffix.lower() != ".nadoc" or not path.is_file():
        return None, None
    from backend.core.design_identity import reconcile_open_identity

    try:
        design = Design.from_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    resolved, disposition, previous = reconcile_open_identity(
        design, rel_path, _asm._WORKSPACE_DIR
    )
    if disposition == "move" and previous:
        remap_design_source_paths(_asm._WORKSPACE_DIR, previous, rel_path)
    elif disposition == "copy" and resolved.id != design.id:
        reassign_job_snapshot_identity(
            _asm._WORKSPACE_DIR, rel_path, design.id, resolved.id
        )
    if resolved != design:
        path.write_text(resolved.to_json(), encoding="utf-8")
    return resolved, disposition


def _sign_managed_relocation(
    dest: Path, old_rel: str, new_rel: str, is_dir: bool
) -> None:
    """Update embedded path signoffs after a NADOC-managed rename/move."""
    from backend.core.design_identity import relocate_identity

    files = (
        dest.rglob("*.nadoc")
        if is_dir
        else ([dest] if dest.suffix.lower() == ".nadoc" else [])
    )
    for file_path in files:
        try:
            design = Design.from_json(file_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        suffix = str(file_path.relative_to(dest)).replace("\\", "/") if is_dir else ""
        old_path = f"{old_rel}/{suffix}" if suffix else old_rel
        new_path = f"{new_rel}/{suffix}" if suffix else new_rel
        updated = relocate_identity(design, old_path, new_path)
        if updated != design:
            file_path.write_text(updated.to_json(), encoding="utf-8")
        active = design_state.get_design()
        if active is not None and active.id == design.id:
            design_state.set_design_silent(updated)


# ── Request bodies ────────────────────────────────────────────────────────────


class UploadFileRequest(BaseModel):
    content: str  # raw JSON string
    filename: str  # e.g. "my_part.nadoc"
    dest_path: Optional[str] = (
        None  # explicit workspace-relative path (skips auto-dedup)
    )
    overwrite: bool = False


class SaveAssemblyRequest(BaseModel):
    filename: Optional[str] = None  # stem only (backward compat)
    path: Optional[str] = (
        None  # full workspace-relative path, takes priority over filename
    )
    overwrite: bool = True


class SaveDesignWorkspaceRequest(BaseModel):
    path: str
    overwrite: bool = True


class MkdirRequest(BaseModel):
    path: str  # workspace-relative folder path to create


class RenameRequest(BaseModel):
    path: str  # current workspace-relative path (file or folder)
    new_name: str  # basename only — no path separators


class MoveRequest(BaseModel):
    path: str  # current workspace-relative path
    dest_folder: str  # destination folder (workspace-relative), "" = workspace root


class TrashRequest(BaseModel):
    path: str


class RestoreTrashRequest(BaseModel):
    trash_id: str


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
    """Quickly list user design files and folders, excluding internal trees.

    Disk usage is deliberately served by ``/library/disk-usage`` so this response
    can paint the welcome screen without waiting for job-folder accounting.
    """
    _asm._WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    entries = _workspace_entries()
    _schedule_workspace_identity_audit()
    return entries


@router.get("/library/disk-usage", status_code=200)
def library_disk_usage() -> dict[str, int]:
    """Simulation bytes by design path, fetched after the fast file listing."""
    from backend.core.design_disk_usage import sim_bytes_by_source_path

    return sim_bytes_by_source_path(_asm._WORKSPACE_DIR)


@router.get("/design/about", status_code=200)
def design_about(path: Optional[str] = None) -> dict:
    """Aggregate everything we know about the active design / a workspace file.

    Topology counts (total bases, loadouts, features-per-loadout) come from the
    live active design; the on-disk facts (file size, MD/oxDNA jobs + their
    sizes, assemblies that use this part) are keyed off ``path`` — the workspace-
    relative .nadoc path of the file currently open. ``path`` may be omitted for
    an unsaved design, in which case the disk-keyed sections are empty.
    """
    from backend.core.design_disk_usage import (
        assemblies_referencing,
        jobs_for_source_path,
    )
    from backend.core.models import Design

    ws = _asm._WORKSPACE_DIR

    # Topology comes from the live active design when one is open (what's on
    # screen, edits included); otherwise fall back to the file on disk so the
    # panel still works when invoked straight from the welcome screen.
    design = None
    try:
        design = design_state.get_or_404()
    except HTTPException:
        design = None
    if design is None and path:
        fpath = ws / path
        if fpath.is_file():
            try:
                design = Design.from_json(fpath.read_text())
            except Exception:  # noqa: BLE001 — advisory panel, never 500
                design = None
    if design is None:
        return {
            "empty": True,
            "path": path,
            "name": (Path(path).stem if path else None),
        }

    # ── Topology (from the live design) ──────────────────────────────────────
    total_bases = sum(
        abs(d.end_bp - d.start_bp) + 1 for s in design.strands for d in s.domains
    )

    loadouts_info = []
    if design.loadouts:
        from backend.core.design_loadouts import decode_snapshot

        for lo in design.loadouts:
            is_active = lo.id == design.active_loadout_id
            if is_active:
                fcount = len(design.feature_log)
            else:
                try:
                    fcount = len(
                        decode_snapshot(
                            lo.design_snapshot_gz_b64
                        ).feature_log
                    )
                except Exception:  # noqa: BLE001 — advisory count, never 500 the panel
                    fcount = None
            loadouts_info.append(
                {
                    "id": lo.id,
                    "name": lo.name,
                    "feature_count": fcount,
                    "is_active": is_active,
                    "snapshot_size_bytes": lo.snapshot_size_bytes,
                }
            )

    # ── On-disk facts (keyed off the open file path) ─────────────────────────
    file_size = 0
    jobs: list[dict] = []
    assemblies: list[dict] = []
    if path:
        fpath = ws / path
        try:
            file_size = fpath.stat().st_size if fpath.is_file() else 0
        except OSError:
            file_size = 0
        jobs = jobs_for_source_path(ws, path)
        assemblies = assemblies_referencing(ws, path)

    oxdna_jobs = [j for j in jobs if j["kind"] == "oxdna"]
    md_jobs = [j for j in jobs if j["kind"] == "md"]
    oxdna_bytes = sum(j["size_bytes"] for j in oxdna_jobs)
    md_bytes = sum(j["size_bytes"] for j in md_jobs)

    return {
        "path": path,
        "name": (Path(path).stem if path else (design.metadata.name or "Untitled")),
        "file_size_bytes": file_size,
        "total_bases": total_bases,
        "strand_count": len(design.strands),
        "helix_count": len(design.helices),
        "loadout_count": len(design.loadouts),
        "feature_log_count": len(design.feature_log),
        "loadouts": loadouts_info,
        "oxdna_jobs": oxdna_jobs,
        "md_jobs": md_jobs,
        "oxdna_total_bytes": oxdna_bytes,
        "md_total_bytes": md_bytes,
        "sim_total_bytes": oxdna_bytes + md_bytes,
        "total_disk_bytes": file_size + oxdna_bytes + md_bytes,
        "assemblies": assemblies,
    }


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

    content = body.content
    identity_disposition = None
    if p.suffix == ".nadoc":
        from backend.core.design_identity import prepare_workspace_save

        try:
            uploaded = Design.from_json(content)
            uploaded, identity_disposition, _ = prepare_workspace_save(
                uploaded, out_rel
            )
            content = uploaded.to_json()
        except Exception as exc:
            raise HTTPException(400, detail=f"Invalid .nadoc file: {exc}") from exc
    dest.write_text(content, encoding="utf-8")
    return {
        "path": out_rel,
        "name": Path(out_rel).stem,
        "type": "assembly" if p.suffix == ".nass" else "part",
        "identity_disposition": identity_disposition,
    }


@router.get("/library/content", status_code=200)
def get_library_file_content(path: str) -> dict:
    """Return the raw JSON content of a workspace file (path relative to workspace)."""
    dest = _safe_workspace_path(path)
    if not dest.is_file():
        raise HTTPException(404, detail=f"File not found in workspace: {path!r}")
    design, disposition = _reconcile_nadoc_file(dest, path)
    return {
        "content": design.to_json()
        if design is not None
        else dest.read_text(encoding="utf-8"),
        "identity_disposition": disposition,
    }


@router.get("/library/native-package")
def download_native_package(
    path: str,
    background_tasks: BackgroundTasks,
    mode: str = "full",
    jobs: str | None = None,
) -> FileResponse:
    """Download a portable .nadocpkg containing a part and all associated simulations."""
    from backend.core.native_part_package import create_package

    try:
        source = _safe_workspace_path(path)
        fd, temporary = tempfile.mkstemp(prefix="nadoc-part-", suffix=".nadocpkg")
        os.close(fd)
        create_package(
            _asm._WORKSPACE_DIR,
            path,
            Path(temporary),
            mode=mode,
            selected_job_ids={item for item in (jobs or "").split(",") if item},
        )
    except (ValueError, OSError) as exc:
        if "temporary" in locals():
            Path(temporary).unlink(missing_ok=True)
        raise HTTPException(400, detail=str(exc)) from exc
    background_tasks.add_task(Path(temporary).unlink, missing_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_. " else "_" for c in source.stem)
    return FileResponse(
        temporary,
        media_type="application/vnd.nadoc.part-package+zip",
        filename=f"{safe}.nadocpkg",
        background=background_tasks,
    )


@router.post("/library/native-package", status_code=201)
async def upload_native_package(
    request: Request, path: str, overwrite: bool = False
) -> dict:
    """Stream a .nadocpkg request body to disk, validate it, and restore its jobs."""
    from backend.core.native_part_package import import_package

    fd, temporary = tempfile.mkstemp(prefix="nadoc-upload-", suffix=".nadocpkg")
    os.close(fd)
    temp_path = Path(temporary)
    try:
        with temp_path.open("wb") as output:
            async for chunk in request.stream():
                output.write(chunk)
        result = await run_in_threadpool(
            import_package,
            _asm._WORKSPACE_DIR,
            temp_path,
            path,
            overwrite_part=overwrite,
        )
        return result
    except FileExistsError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, detail=str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)


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
        raise HTTPException(
            400, detail="new_name must be a plain basename (no path separators)."
        )
    src = _safe_workspace_path(body.path)
    if not src.exists():
        raise HTTPException(404, detail=f"Not found: {body.path!r}")
    dest = src.parent / body.new_name
    if dest.exists() and dest.resolve() != src.resolve():
        raise HTTPException(
            409, detail=f"{body.new_name!r} already exists in the same folder."
        )
    is_dir = src.is_dir()
    old_rel = str(src.relative_to(_asm._WORKSPACE_DIR))
    new_rel = str((src.parent / body.new_name).relative_to(_asm._WORKSPACE_DIR))
    src.rename(dest)
    old_ref = old_rel + "/" if is_dir else old_rel
    new_ref = new_rel + "/" if is_dir else new_rel
    patched = _patch_references(old_ref, new_ref)
    _sign_managed_relocation(dest, old_rel, new_rel, is_dir)
    remap_design_source_paths(_asm._WORKSPACE_DIR, old_rel, new_rel, old_is_dir=is_dir)
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
        raise HTTPException(
            409, detail=f"{src.name!r} already exists in the destination folder."
        )
    is_dir = src.is_dir()
    old_rel = str(src.relative_to(_asm._WORKSPACE_DIR))
    shutil.move(str(src), str(dest))
    new_rel = str(dest.relative_to(_asm._WORKSPACE_DIR))
    old_ref = old_rel + "/" if is_dir else old_rel
    new_ref = new_rel + "/" if is_dir else new_rel
    patched = _patch_references(old_ref, new_ref)
    _sign_managed_relocation(dest, old_rel, new_rel, is_dir)
    remap_design_source_paths(_asm._WORKSPACE_DIR, old_rel, new_rel, old_is_dir=is_dir)
    return {"old_path": old_rel, "new_path": new_rel, "patched_assemblies": patched}


@router.post("/library/trash", status_code=200)
def library_trash(body: TrashRequest) -> dict:
    """Move a file/folder into NADOC's hidden trash so it can be restored."""
    src = _safe_workspace_path(body.path)
    if not src.exists():
        raise HTTPException(404, detail=f"Not found: {body.path!r}")
    trash_id = uuid.uuid4().hex
    trash_dir = _asm._WORKSPACE_DIR / ".nadoc-trash" / trash_id
    trash_dir.mkdir(parents=True, exist_ok=False)
    dest = trash_dir / src.name
    shutil.move(str(src), str(dest))
    metadata = {
        "id": trash_id,
        "original_path": body.path,
        "name": src.name,
        "type": "folder" if dest.is_dir() else "file",
        "deleted_at": _dt.now(_tz.utc).isoformat(),
    }
    (trash_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return metadata


@router.get("/library/trash", status_code=200)
def library_trash_list() -> dict:
    root = _asm._WORKSPACE_DIR / ".nadoc-trash"
    items = []
    if root.is_dir():
        for metadata_path in root.glob("*/metadata.json"):
            try:
                items.append(json.loads(metadata_path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
    items.sort(key=lambda item: item.get("deleted_at", ""), reverse=True)
    return {"items": items}


@router.post("/library/trash/restore", status_code=200)
def library_trash_restore(body: RestoreTrashRequest) -> dict:
    trash_dir = _safe_workspace_path(f".nadoc-trash/{body.trash_id}")
    metadata_path = trash_dir / "metadata.json"
    if not metadata_path.is_file():
        raise HTTPException(404, detail="Trash item not found.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    source = trash_dir / metadata["name"]
    destination = _safe_workspace_path(metadata["original_path"])
    if destination.exists():
        raise HTTPException(409, detail=f"Restore destination already exists: {metadata['original_path']!r}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    shutil.rmtree(trash_dir)
    return {"path": metadata["original_path"]}


def _job_running(kind: str, job) -> bool:
    """True if an MD/oxDNA job is mid-run (active process or status==running).

    Runner modules are imported lazily so this workspace router stays cheap to
    import and free of circular-import risk with the job routers."""
    if kind == "md":
        from backend.core.md_job import MdStatus  # noqa: PLC0415
        from backend.core.namd_runner import is_running as _ir  # noqa: PLC0415

        return _ir(job.job_id) or job.status == MdStatus.running
    from backend.core.oxdna_job import OxdnaStatus  # noqa: PLC0415
    from backend.core.oxdna_runner import is_running as _ir  # noqa: PLC0415

    return _ir(job.job_id) or job.status == OxdnaStatus.running


@router.get("/library/file/jobs", status_code=200)
def library_file_jobs(path: str) -> dict:
    """List the MD / oxDNA job folders associated with a workspace file/folder.

    Used by the delete-file flow to decide whether to offer cleaning up the
    generated job folders. ``running`` flags a job whose process is still active
    (its folder cannot be removed until it is stopped)."""
    dest = _safe_workspace_path(path)
    if not dest.exists():
        raise HTTPException(404, detail=f"Not found: {path!r}")
    found = find_associated_jobs(_asm._WORKSPACE_DIR, path, dest.is_dir())
    md = [
        {
            "job_id": j.job_id,
            "design_name": j.design_name,
            "running": _job_running("md", j),
        }
        for j in found["md"]
    ]
    ox = [
        {
            "job_id": j.job_id,
            "design_name": j.design_name,
            "running": _job_running("oxdna", j),
        }
        for j in found["oxdna"]
    ]
    return {"md": md, "oxdna": ox, "running": any(e["running"] for e in (*md, *ox))}


@router.delete("/library/file", status_code=200)
def library_delete(path: str, delete_jobs: bool = False) -> dict:
    """Delete a workspace file or folder (folders are deleted recursively).

    With ``delete_jobs=true`` the MD / oxDNA job folders generated from this
    file (or any file under this folder) are removed too. If any of those jobs is
    still running the whole operation is refused with 409 — stop the job first."""
    dest = _safe_workspace_path(path)
    if not dest.exists():
        raise HTTPException(404, detail=f"Not found: {path!r}")

    deleted_jobs: list[str] = []
    if delete_jobs:
        found = find_associated_jobs(_asm._WORKSPACE_DIR, path, dest.is_dir())
        jobs = [("md", j) for j in found["md"]] + [("oxdna", j) for j in found["oxdna"]]
        running = [j.job_id for kind, j in jobs if _job_running(kind, j)]
        if running:
            raise HTTPException(
                409,
                detail="Stop running job(s) before deleting their folders: "
                + ", ".join(running),
            )
        from backend.core.job_archive import purge_index_entry

        for _kind, j in jobs:
            job_dir = j.job_dir(_asm._WORKSPACE_DIR)
            if job_dir.exists():
                shutil.rmtree(str(job_dir))
                deleted_jobs.append(j.job_id)
            purge_index_entry(_asm._WORKSPACE_DIR, f"{_kind}_jobs", j.job_id)

    if dest.is_dir():
        shutil.rmtree(str(dest))
    else:
        dest.unlink()
    return {"path": path, "deleted_jobs": deleted_jobs}


@router.post("/design/save-workspace", status_code=200)
def save_design_to_workspace(body: SaveDesignWorkspaceRequest) -> dict:
    """Write the active in-memory design to a workspace file."""
    design, save_revision, known_heads = design_state.copy_for_workspace_save()
    dest = _safe_workspace_path(body.path)
    if not body.overwrite and dest.exists():
        raise HTTPException(409, detail=f"File already exists: {body.path!r}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    from backend.api.crud import _design_response
    from backend.core.design_loadouts import decode_snapshot, encode_snapshot
    from backend.core.design_identity import prepare_workspace_save
    from backend.core.validator import validate_design

    saved, disposition, previous = prepare_workspace_save(design, body.path)
    if saved.id != design.id and saved.loadouts:
        migrated_loadouts = []
        for loadout in saved.loadouts:
            try:
                snapshot = decode_snapshot(
                    loadout.design_snapshot_gz_b64
                )
                snapshot = snapshot.model_copy(
                    update={"id": saved.id, "metadata": saved.metadata}
                )
                payload, size = encode_snapshot(snapshot)
                loadout = loadout.model_copy(
                    update={
                        "design_snapshot_gz_b64": payload,
                        "snapshot_size_bytes": size,
                        # A Save As is a new project. Its branches start from
                        # the copied content, never from the source project's
                        # content-addressed ref namespace.
                        "head_revision_id": None,
                        "base_revision_id": None,
                    }
                )
            except Exception:
                pass
            migrated_loadouts.append(loadout)
        saved = saved.model_copy(update={"loadouts": migrated_loadouts})
    # Mirror embedded loadout snapshots into immutable project revisions before
    # publishing the compatibility .nadoc.  A stale branch pointer is a real
    # multi-server conflict and must never degrade to last-writer-wins.
    from backend.core.project_revisions import BranchConflict, ProjectRevisionStore, refresh_active_revision

    # Undo and feature-history restores rewind content, but must not rewind the
    # save cursor. Adopt only a head this SAME session has observed; an unknown
    # head from another document/server must still produce a real conflict.
    if saved.id == design.id:
        revisions = ProjectRevisionStore(_asm._WORKSPACE_DIR)
        loadouts = []
        for loadout in saved.loadouts:
            head = revisions.branch_head(saved.id, loadout.id)
            if head and head in known_heads.get(loadout.id, set()):
                loadout = loadout.model_copy(update={"head_revision_id": head})
            loadouts.append(loadout)
        saved = saved.model_copy(update={"loadouts": loadouts})

    try:
        saved = refresh_active_revision(_asm._WORKSPACE_DIR, saved)
    except BranchConflict as exc:
        raise HTTPException(
            409,
            detail={
                "kind": "branch_diverged",
                "loadout_id": exc.loadout_id,
                "expected_head": exc.expected,
                "current_head": exc.current,
            },
        ) from exc
    dest.write_text(saved.to_json(), encoding="utf-8")
    design_state.acknowledge_workspace_save(design, saved, save_revision)
    # Same-path autosave is an acknowledgement, not a state sync: the frontend
    # deliberately keeps its current Design object to avoid an autosave loop.
    # Returning the full multi-megabyte design here made it JSON.parse data it
    # immediately discarded (notably ~142 ms for VoltronCoreArm).
    if disposition == "confirmed":
        return {
            "path": body.path,
            "identity_disposition": disposition,
            "previous_path": previous,
        }
    response = _design_response(saved, validate_design(saved))
    response.update(
        {
            "path": body.path,
            "identity_disposition": disposition,
            "previous_path": previous,
        }
    )
    return response


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
            design = inst.source.design
            safe_stem = "".join(
                c if c.isalnum() or c in "-_ " else "_"
                for c in (design.metadata.name or inst.name or "part")
            )
            filename = _ws.dedup_filename(safe_stem, ".nadoc", _asm._WORKSPACE_DIR)
            (_asm._WORKSPACE_DIR / filename).write_text(
                design.to_json(), encoding="utf-8"
            )
            new_instances[idx] = inst.model_copy(
                update={"source": PartSourceFile(path=filename)}
            )
            changed = True

    if changed:
        assembly = assembly.model_copy(update={"instances": new_instances})
        assembly_state.set_assembly_silent(assembly)

    # Determine output path
    if body and body.path:
        if not body.path.endswith(".nass"):
            raise HTTPException(400, detail="path must end with .nass")
        dest = _safe_workspace_path(body.path)
        if not body.overwrite and dest.exists():
            raise HTTPException(409, detail=f"File already exists: {body.path!r}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        out_rel = body.path
    else:
        asm_name = (
            (body.filename if body and body.filename else None)
            or assembly.metadata.name
            or "assembly"
        )
        safe_stem = "".join(c if c.isalnum() or c in "-_ " else "_" for c in asm_name)
        out_rel = f"{safe_stem}.nass"
        dest = _asm._WORKSPACE_DIR / out_rel

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
