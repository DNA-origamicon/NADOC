"""API layer — host filesystem directory browsing for the archive folder picker.

The job-archive feature lets the user move a job's heavy folder to *anywhere on
the host* (e.g. an external drive), so the frontend needs a system folder picker.
These endpoints expose a read-only directory walk plus a "new folder" action.

This is a single-user, localhost research tool, so browsing the host filesystem
is acceptable; the endpoints only ever list directory names and create folders —
they never read file contents. Listing is directories-only (it's a *folder*
picker) and degrades gracefully on permission errors.

One reason to change: how the archive folder picker enumerates the host filesystem.

Routes
------
  GET  /fs/listdir   — subdirectories of a path (defaults to the user's home)
  POST /fs/mkdir     — create a new folder
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _list_dir(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(404, detail=f"path does not exist: {path}")
    if not path.is_dir():
        raise HTTPException(400, detail=f"not a directory: {path}")
    entries = []
    try:
        for child in sorted(path.iterdir(), key=lambda p: p.name.lower()):
            if child.name.startswith("."):
                continue
            try:
                if child.is_dir():
                    entries.append({"name": child.name, "path": str(child)})
            except OSError:
                continue  # unreadable entry — skip
    except PermissionError:
        raise HTTPException(403, detail=f"permission denied: {path}")
    parent = str(path.parent) if path.parent != path else None
    return {"path": str(path), "parent": parent, "entries": entries}


@router.get("/fs/listdir")
def fs_listdir(path: Optional[str] = None) -> dict:
    """List subdirectories of ``path`` (default: the user's home directory)."""
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except OSError as e:
        raise HTTPException(400, detail=str(e))
    return _list_dir(base)


class MkdirRequest(BaseModel):
    path: str  # parent directory
    name: str  # new folder name (no path separators)


@router.post("/fs/mkdir", status_code=201)
def fs_mkdir(body: MkdirRequest) -> dict:
    """Create ``name`` inside ``path`` and return the listing of ``path``."""
    name = body.name.strip()
    if not name or "/" in name or "\\" in name:
        raise HTTPException(400, detail="folder name must not contain path separators")
    parent = Path(body.path).expanduser()
    if not parent.is_dir():
        raise HTTPException(400, detail=f"parent is not a directory: {parent}")
    target = parent / name
    if target.exists():
        raise HTTPException(409, detail=f"already exists: {target}")
    try:
        target.mkdir(parents=False)
    except OSError as e:
        raise HTTPException(400, detail=str(e))
    return _list_dir(parent)
