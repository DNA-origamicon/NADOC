"""Transient PDF evidence evaluation, independent of active design/session."""
import asyncio
from fastapi import APIRouter, HTTPException, Request, Query
from starlette.concurrency import run_in_threadpool
from backend.core.image_evaluation import evaluate_pdf

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
            data.extend(chunk)
        try:
            return await run_in_threadpool(evaluate_pdf, bytes(data))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc


@router.post('/article-reconstruction/check')
async def check_article(request: Request):
    """Transient upload; streamed results do not touch document state."""
    import json
    from starlette.responses import StreamingResponse
    from backend.core.article_reconstruction import screen_article

    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
    try:
        payload = json.loads(data)
        if not isinstance(payload, dict) or not isinstance(payload.get('supplements', []), list):
            raise ValueError()
        if len(payload.get('supplements', [])) > 2:
            raise ValueError()
        if not isinstance(payload.get('doi', ''), str):
            raise ValueError()
        for item in [payload.get('paper'), *payload.get('supplements', [])]:
            if item is not None and (not isinstance(item, dict) or not isinstance(item.get('data'), str)):
                raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, 'Provide a DOI or paper and up to two supplement PDFs.')

    async def stream():
        # Serialize PDF scans with the existing evaluator; advance off the event loop.
        async with _gate:
            iterator = iter(screen_article(payload))
            while True:
                item = await run_in_threadpool(next, iterator, None)
                if item is None:
                    break
                yield json.dumps(item) + '\n'
    return StreamingResponse(stream(), media_type='application/x-ndjson')


@router.post('/article-reconstruction/analyze')
async def analyze_article(request: Request):
    from backend.core.article_design_detection import detect_designs
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('Expected article inputs.')
        for key in ('supplements', 'staple_lists'):
            if not isinstance(payload.get(key, []), list):
                raise ValueError(f'{key} must be a list of uploaded files.')
        if not isinstance(payload.get('scaffold_sequence', ''), str):
            raise ValueError('Scaffold sequence must be text.')
        for item in [payload.get('paper'), *payload.get('supplements', []), *payload.get('staple_lists', [])]:
            if item is not None and (not isinstance(item, dict) or not isinstance(item.get('data'), str)
                                     or not isinstance(item.get('name', ''), str)):
                raise ValueError('Invalid uploaded file.')
        async with _gate:
            return await run_in_threadpool(detect_designs, payload)
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/article-reconstruction/reconstruct')
async def reconstruct_article(request: Request):
    from starlette.responses import Response
    from backend.core.article_native_reconstruction import reconstruct_package
    try:
        payload=await request.json()
        if not isinstance(payload,dict):raise ValueError('Expected article inputs.')
        async with _gate:
            data=await run_in_threadpool(reconstruct_package,payload)
        return Response(data,media_type='application/zip',headers={
            'Content-Disposition':'attachment; filename="reconstructed-designs.zip"'})
    except (ValueError,TypeError,KeyError) as exc:
        raise HTTPException(422,str(exc)) from exc
