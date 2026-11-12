"""Server presentation library, independent of active design/assembly sessions."""

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from backend.api import assembly
from backend.core.presentation_library import (
    LIBRARY_FOLDER, MAX_PRESENTATION_BYTES, PresentationLibrary,
)

router = APIRouter(prefix="/presentations", tags=["presentations"])


@router.get("")
def list_presentations():
    try:
        return {"folder": LIBRARY_FOLDER, "items": PresentationLibrary(assembly._WORKSPACE_DIR).entries()}
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@router.post("", status_code=201)
async def save_presentation(request: Request, name: str = Query(min_length=1, max_length=200),
                            kind: Literal["presentation", "keyframe"] = "presentation"):
    if request.headers.get("content-type", "").split(";")[0] != "text/html":
        raise HTTPException(415, "Expected text/html")
    library = PresentationLibrary(assembly._WORKSPACE_DIR)
    temporary = None
    try:
        with await run_in_threadpool(library.begin) as handle:
            temporary = Path(handle.name)
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_PRESENTATION_BYTES:
                    raise HTTPException(413, "Presentation exceeds 512 MiB")
                await run_in_threadpool(handle.write, chunk)
            await run_in_threadpool(handle.flush)
            await run_in_threadpool(os.fsync, handle.fileno())
        return await run_in_threadpool(library.commit, temporary, name, kind)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@router.get("/{presentation_id}/content")
def presentation_content(presentation_id: str):
    library = PresentationLibrary(assembly._WORKSPACE_DIR)
    try:
        path = library.path(presentation_id)
        if not path.is_file() or not library.path(presentation_id, ".json").is_file():
            raise HTTPException(404, "Presentation not found")
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    # Never execute uploaded HTML on the app's origin. The client extracts data
    # and rebuilds its trusted, sandboxed player, just as for downloaded files.
    return FileResponse(path, media_type="application/octet-stream", filename="presentation.html",
                        headers={"X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "sandbox; default-src 'none'",
                                 "Cache-Control": "private, no-store"})
