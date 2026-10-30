"""Transient PDF evidence evaluation, independent of active design/session."""
import asyncio
from fastapi import APIRouter, HTTPException, Request, Query
from starlette.concurrency import run_in_threadpool
from backend.core.image_evaluation import MAX_BYTES, evaluate_pdf

router = APIRouter(tags=['image evaluation'])
_gate = asyncio.Semaphore(1)


@router.get('/image-evaluation/brick-matches')
def brick_matches(minimum: int = Query(12, ge=6, le=40), reference: str = Query('brick', pattern='^(brick|42hb13|42hb14)$'), register: int | None = Query(None, ge=0, le=7559)):
    from backend.api import state
    from backend.core.image_sequence_matches import preview_matches
    design, revision = state.get_design_with_revision()
    if design is None:
        raise HTTPException(404, 'Open a design to compare its domains with the published list.')
    snapshot = design.model_copy(deep=True)
    try:
        return {**preview_matches(snapshot, minimum, reference, register), 'design_revision': revision}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/image-evaluation')
async def image_evaluation(request: Request):
    async with _gate:
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_BYTES:
                raise HTTPException(413, 'PDF exceeds the 25 MiB limit.')
            data.extend(chunk)
        try:
            return await run_in_threadpool(evaluate_pdf, bytes(data))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
