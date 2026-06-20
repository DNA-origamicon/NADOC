"""MD-engine status endpoint — backs the "MD Engines" panel + sidebar gates.

Thin: delegates to `backend.core.engines`.  The auto-install build itself streams
over the `/ws/engines/install` WebSocket (see `api/ws.py`), not here.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.engines import engines_status, gpu_info

router = APIRouter(tags=["engines"])


@router.get("/engines/status")
async def get_engines_status() -> dict:
    """Per-engine availability, GPU + toolchain info, and per-section readiness.

    See `engines.engines_status()` for the response shape.  The frontend calls
    this on the Help-menu panel and to gate the oxDNA / MD sidebar sections.
    """
    return engines_status()


@router.get("/engines/namd/scan-download")
async def scan_namd_download() -> dict:
    """Look for a user-downloaded NAMD tarball in the usual download folders.

    Backs the "check download & install" button: NAMD is license-gated so it
    can't be auto-downloaded, but once the user has the tarball NADOC can verify
    it and finish (extract + detect).  Returns ``{candidates, best}`` (filename
    checks only — the deep tar-peek happens at install time).
    """
    from backend.core.engine_artifact import pick_best_candidate, scan_namd_downloads
    gpu = gpu_info()
    candidates = scan_namd_downloads(gpu)
    best = pick_best_candidate(candidates, gpu)
    return {"candidates": candidates, "best": best}
