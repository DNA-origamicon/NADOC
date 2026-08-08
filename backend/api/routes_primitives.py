"""API layer — primitive-library routes.

Serves the "Add Primitive" panel: a list of pre-validated building-block designs
plus their generated hover-preview assets. The catalog source is *temporarily*
the workspace ``Primitives/`` folder (scanned live); see ``backend.core.
primitive_catalog`` for the metadata derivation and ``workspace/Primitives/
README.md`` for the planned in-repo registry migration.

The workspace directory is read live via ``assembly._WORKSPACE_DIR`` (module-
attribute access) so tests that monkeypatch it redirect these routes too — same
pattern as ``routes_assembly_workspace.py``.

Routes
------
  GET /primitives                      — list available primitives + metadata
  GET /primitives/{id}/preview.gif     — looping preview GIF (404 if not built)
  GET /primitives/{id}/poster.png      — static first-frame poster (404 if not built)

Mounted in ``backend/api/main.py`` via ``app.include_router(..., prefix="/api")``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from backend.api import assembly as _asm
from backend.core import primitive_catalog as _pc

router = APIRouter()

# Subfolder of the workspace that holds the primitive designs + their assets.
_PRIMITIVES_SUBDIR = "Primitives"


def _primitives_dir() -> Path:
    """Resolve the workspace Primitives folder live (honors test monkeypatch)."""
    return _asm._WORKSPACE_DIR / _PRIMITIVES_SUBDIR


@router.get("/primitives", status_code=200)
def list_primitives() -> list[dict]:
    """List the available primitives with display metadata + asset URLs."""
    out = []
    for meta in _pc.list_primitives(_primitives_dir()):
        pid = meta["id"]
        out.append(
            {
                **meta,
                "preview_url": f"/api/primitives/{pid}/preview.gif"
                if meta["has_preview"]
                else None,
                "poster_url": f"/api/primitives/{pid}/poster.png"
                if meta["has_poster"]
                else None,
            }
        )
    return out


@router.get("/primitives/{primitive_id}/preview.gif")
def get_primitive_preview(primitive_id: str) -> FileResponse:
    """Serve a primitive's looping preview GIF."""
    p = _pc.preview_path(_primitives_dir(), primitive_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Preview not found")
    return FileResponse(p, media_type="image/gif")


@router.get("/primitives/{primitive_id}/poster.png")
def get_primitive_poster(primitive_id: str) -> FileResponse:
    """Serve a primitive's static first-frame poster."""
    p = _pc.poster_path(_primitives_dir(), primitive_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Poster not found")
    return FileResponse(p, media_type="image/png")
