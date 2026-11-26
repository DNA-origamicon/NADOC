"""Optional experimental image renderer; receives disposable graphics, not parts."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import time

from fastapi import APIRouter, HTTPException, Request, Response
from starlette.requests import ClientDisconnect
from backend.rendering.optix_service import OptixSession, blender_executable
from backend.rendering.resources import upload_capacity
from backend.rendering.optix_upload import append_upload, verify_upload

sessions = {}
admission = asyncio.Lock()


async def release_expired_sessions():
    """Reclaim abandoned acknowledgements and dead workers before admission.

    Claimed/live owners keep their normal idle lease; rendering/uploading work
    is never preempted to admit a different browser tab.
    """
    for key, session in list(sessions.items()):
        process = getattr(session, "process", None)
        dead = getattr(session, "closed", False) or (process is not None and process.returncode is not None)
        idle = not session.lock.locked() and not session.upload_lock.locked()
        timeout = 120 if getattr(session, "claimed", True) else 10
        if dead or (idle and time.monotonic() - session.touched > timeout):
            await session.close()
            if sessions.get(key) is session:
                sessions.pop(key, None)


@asynccontextmanager
async def lifespan(_app):
    async def reap():
        while True:
            await asyncio.sleep(5)
            async with admission:
                await release_expired_sessions()
    task = asyncio.create_task(reap())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        for session in list(sessions.values()):
            await session.close()
        sessions.clear()


router = APIRouter(prefix="/render/optix", tags=["render"], lifespan=lifespan)


@router.get("/capabilities")
async def capabilities():
    try:
        blender_executable()
        return {"installed": True, "experimental": True, "gpu_verified": False}
    except RuntimeError as error:
        return {"installed": False, "reason": str(error)}


@router.post("/session")
async def create_session(request: Request):
    async with admission:
        await release_expired_sessions()
        if sessions:
            raise HTTPException(409, "An OptiX renderer is active in another preview or export. Turn off Native OptiX in the other NADOC tab or finish its export, then retry. Abandoned startups can be reclaimed after 10 seconds.")
        try:
            session = OptixSession()
            task = asyncio.create_task(session.start())
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=.2)
                    if await request.is_disconnected():
                        raise asyncio.CancelledError()
                await task
                if await request.is_disconnected():
                    raise asyncio.CancelledError()
            except BaseException:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
                await session.close()
                raise
        except (RuntimeError, OSError, asyncio.TimeoutError) as error:
            raise HTTPException(503, str(error) or "OptiX startup timed out") from error
        session.touched = time.monotonic()
        sessions[session.id] = session
        return {"id": session.id, "device": session.device}


@router.delete("/{session_id}")
async def close_session(session_id: str):
    session = sessions.get(session_id)
    if session:
        await session.close()
        sessions.pop(session_id, None)
    return {"closed": True}


@router.get("/{session_id}/capacity")
async def capacity(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "OptiX export session expired")
    session.touched = time.monotonic()
    session.claimed = True
    return upload_capacity(session.root)


@router.get("/{session_id}/progress")
async def progress(session_id: str):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "OptiX export session expired")
    return session.progress


@router.post("/{session_id}/upload")
async def upload_piece(session_id: str, request: Request):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "OptiX export session expired")
    if session.upload_lock.locked() or session.lock.locked():
        raise HTTPException(409, "An OptiX frame is already uploading or rendering")
    session.claimed = True
    async with session.upload_lock:
        try:
            return await append_upload(session, request)
        except OSError as error:
            raise HTTPException(503, str(error)) from error


@router.post("/{session_id}/frame")
async def render_frame(session_id: str, request: Request):
    session = sessions.get(session_id)
    if not session:
        raise HTTPException(404, "OptiX export session expired")
    if session.upload_lock.locked() or session.lock.locked():
        raise HTTPException(409, "An OptiX frame is already uploading or rendering")
    session.claimed = True
    async with session.upload_lock:
        return await _uploaded_frame(session_id, session, request)


async def _uploaded_frame(session_id, session, request):
    source = session.root / "upload.json"
    session.progress = {"stage": "prepare", "label": "Uploading OptiX scene", "fraction": None,
                        "request_id": getattr(request, "headers", {}).get("x-nadoc-render-id")}
    try:
        # Stream to owned scratch rather than retaining/re-encoding a second copy
        # of a potentially large geometry upload in the web-server process.
        if getattr(request, 'headers', {}).get('x-nadoc-upload-bytes') is not None:
            verify_upload(session, request)
        else:
            size = 0
            with source.open('wb') as target:
                async for chunk in request.stream():
                    resources = await asyncio.to_thread(upload_capacity, session.root)
                    size += len(chunk)
                    if size > resources['available_memory_bytes'] or len(chunk) > resources['scratch_free_bytes']:
                        raise HTTPException(413, f"OptiX upload needs {size / 1048576:.1f} MiB; currently available RAM is {resources['available_memory_bytes'] / 1048576:.1f} MiB and scratch space is {resources['scratch_free_bytes'] / 1048576:.1f} MiB")
                    await asyncio.to_thread(target.write, chunk)
                    session.touched = time.monotonic()
        keys = ('width', 'height', 'samples')
        if all(f'x-nadoc-frame-{key}' in request.headers for key in keys):
            data = {key: int(request.headers[f'x-nadoc-frame-{key}']) for key in keys}
        else:
            # Compatibility for an already-open older client; new clients send
            # these three fields as headers and avoid parsing geometry here.
            def dimensions():
                with source.open() as stream:
                    payload = json.load(stream)
                return {key: payload[key] for key in keys}
            data = await asyncio.to_thread(dimensions)
        if any(type(data[k]) is not int or not 1 <= data[k] <= limit for k, limit in (("width", 2048), ("height", 2048), ("samples", 512))):
            raise ValueError("Invalid frame dimensions or samples")
        task = asyncio.create_task(session.render(data, source=source))
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=.2)
                if await request.is_disconnected():
                    raise asyncio.CancelledError()
            return Response(await task, media_type="application/octet-stream", headers={
                "X-NADOC-Render-Stats": json.dumps(getattr(session, "stats", {})),
            })
        except BaseException:
            task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            await session.close()
            sessions.pop(session_id, None)
            raise
    except (ClientDisconnect, asyncio.CancelledError):
        await session.close()
        sessions.pop(session_id, None)
        raise
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(422, str(error)) from error
    except (RuntimeError, OSError, MemoryError, asyncio.TimeoutError) as error:
        detail = "OptiX exhausted available system memory" if isinstance(error, MemoryError) else str(error) or "OptiX frame timed out"
        raise HTTPException(503, detail) from error
    finally:
        source.unlink(missing_ok=True)
