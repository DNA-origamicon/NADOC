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

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


def _is_wsl() -> bool:
    return "microsoft" in platform.release().lower()


def _browse_path(value: Optional[str]) -> Path:
    """Accept native paths and Windows drive paths pasted into a WSL picker."""
    if not value:
        return Path.home()
    value = value.strip().strip('"')
    if _is_wsl() and re.match(r"^[A-Za-z]:[\\/]", value):
        try:
            result = subprocess.run(
                ["wslpath", "-u", value], capture_output=True, text=True,
                check=True, timeout=3,
            )
            value = result.stdout.strip()
            if not value:
                raise ValueError("empty converted path")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            raise HTTPException(400, detail="Could not translate the Windows path. Use its mounted Linux path, such as /mnt/f/NADOC.") from exc
    return Path(value).expanduser().resolve()


def _mounted_paths() -> list[Path]:
    if os.name == "nt":
        return [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                if Path(f"{letter}:\\").is_dir()]
    try:
        lines = Path("/proc/self/mountinfo").read_text().splitlines()
    except OSError:
        return []
    paths = []
    for line in lines:
        fields = line.split()
        if len(fields) < 5:
            continue
        path = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), fields[4])
        if path.startswith(("/mnt/", "/media/", "/run/media/")) and path != "/mnt/wsl" and not path.startswith("/mnt/wslg"):
            paths.append(Path(path))
    return sorted(set(paths), key=str)


def _locations() -> list[dict]:
    locations = [{"name": "Home", "path": str(Path.home())},
                 {"name": "Filesystem root", "path": str(Path(Path.home().anchor))}]
    for path in _mounted_paths():
        if not path.is_dir():
            continue
        drive = re.fullmatch(r"/mnt/([a-zA-Z])", str(path))
        name = f"Windows drive ({drive[1].upper()}:)" if drive else f"Drive: {path.name or path}"
        item = {"name": name, "path": str(path)}
        try:
            usage = shutil.disk_usage(path)
            item.update(free_bytes=usage.free, total_bytes=usage.total)
        except OSError:
            pass
        locations.append(item)
    for path in (Path("/mnt"), Path("/media"), Path("/run/media")):
        if path.is_dir():
            locations.append({"name": f"Browse {path}", "path": str(path)})
    return locations


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
    return {"path": str(path), "parent": parent, "entries": entries,
            "locations": _locations(), "wsl": _is_wsl()}


@router.get("/fs/listdir")
def fs_listdir(path: Optional[str] = None) -> dict:
    """List subdirectories of ``path`` (default: the user's home directory)."""
    try:
        base = _browse_path(path)
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
    parent = _browse_path(body.path)
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
