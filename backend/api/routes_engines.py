"""MD-engine status endpoint — backs the "MD Engines" panel + sidebar gates.

Thin: delegates to `backend.core.engines`.  The auto-install build itself streams
over the `/ws/engines/install` WebSocket (see `api/ws.py`), not here.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.engines import engines_status

router = APIRouter(tags=["engines"])


@router.get("/engines/status")
async def get_engines_status() -> dict:
    """Per-engine availability, GPU + toolchain info, and per-section readiness.

    See `engines.engines_status()` for the response shape.  The frontend calls
    this on the Help-menu panel and to gate the oxDNA / MD sidebar sections.
    """
    return engines_status()


# Filename shapes worth highlighting per engine in the folder navigator.
_BROWSE_GLOB = {
    "arbd": "arbd*.tar.*",
    "namd": "namd_*linux-x86_64*.tar.gz",
}


@router.get("/engines/browse")
async def browse_files(path: str | None = None, kind: str | None = None) -> dict:
    """List a directory for the "pick a downloaded file" folder navigator.

    Backs the Browse… button in the install popups.  With no ``path`` it opens at
    the user's Downloads folder (the Windows one on WSL — see
    `fs_browse.default_downloads_dir`).  ``kind`` (``"arbd"`` | ``"namd"``) picks
    the filename glob used to *highlight* likely files (navigation is never
    restricted).  Returns ``fs_browse.list_dir`` shape.
    """
    from backend.core.fs_browse import list_dir
    return list_dir(path, name_glob=_BROWSE_GLOB.get(kind or ""))
