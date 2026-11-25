"""Job-owned UV analysis API lifecycle; display filters never launch workers."""
import asyncio
from contextlib import suppress

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from backend.core import uv_crosslinking as uv

_ACTIVE = {}


def inputs(job_id):
    from backend.api.routes_md import _load_job, _workspace, _md_segment_dcds
    from backend.core.md_trajectory import md_production_segments
    job = _load_job(job_id)
    folder = job.job_dir(_workspace())
    design = folder / 'design.json'
    if not design.exists():
        raise HTTPException(422, 'UV analysis requires the saved simulation design snapshot')
    psf = job.package_dir(_workspace()) / f'{job.name_stem}.psf'
    if not psf.exists():
        raise HTTPException(422, 'Simulation topology is unavailable')
    segments = _md_segment_dcds(job)
    paths = [segments[i][2] for i in md_production_segments(segments)]
    if not paths:
        raise HTTPException(422, 'A free production trajectory is required')
    cache, source = uv.cache_spec(folder,psf,paths,design)
    return psf, paths, design, cache, source


async def result(job_id, request):
    from backend.core.md_analysis_runner import run_analysis
    args = await run_in_threadpool(inputs,job_id)
    cached = await run_in_threadpool(uv.read_result,args[3])
    if cached and cached['complete']:
        return {**cached, 'cached': True}
    token = object()
    _ACTIVE[job_id] = (token,args[3])
    task = asyncio.create_task(run_analysis(job_id,'photoproduct',
                               'backend.core.uv_crosslinking','md_uv_crosslinking',
                               args,timeout_s=86400))
    try:
        while not task.done():
            if request is not None and await request.is_disconnected():
                # Cancel this request's worker, not a replacement that a rapid
                # off/on may have registered under the same job/kind meanwhile.
                task.cancel()
                break
            await asyncio.sleep(.1)
        return await task
    finally:
        if _ACTIVE.get(job_id,(None,None))[0] is token:
            _ACTIVE.pop(job_id,None)
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def progress(job_id):
    active = _ACTIVE.get(job_id)
    if active:
        return await run_in_threadpool(uv.progress,active[1])
    args = await run_in_threadpool(inputs,job_id)
    return await run_in_threadpool(uv.progress,args[3])
