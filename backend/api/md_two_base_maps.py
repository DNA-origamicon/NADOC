"""Selected-job two-base measurement endpoint."""
import asyncio
from contextlib import suppress
import json
import uuid

from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

router = APIRouter()


class TwoBaseRequest(BaseModel):
    bases: list[str] = Field(min_length=2,max_length=2)
    design_id: str
    request_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=r'^[a-zA-Z0-9-]{1,64}$')


def inputs(job_id, body):
    from backend.api.routes_md import _load_job, _workspace, _md_segment_dcds
    from backend.core.md_trajectory import md_production_segments
    job = _load_job(job_id)
    folder = job.job_dir(_workspace())
    design = folder/'design.json'
    if not design.exists():
        raise HTTPException(422,'Saved simulation design is unavailable')
    if json.loads(design.read_text()).get('id') != body.design_id:
        raise HTTPException(422,'Select bases from the design used for this job')
    topology = job.package_dir(_workspace())/f'{job.name_stem}.psf'
    segments = _md_segment_dcds(job)
    paths = [segments[i][2] for i in md_production_segments(segments)]
    if not topology.exists() or not paths:
        raise HTTPException(422,'A saved production trajectory and topology are required')
    return topology,paths,design,folder,body.bases


@router.post('/md/jobs/{job_id}/two-base-maps')
async def generate(job_id: str, body: TwoBaseRequest, request: Request):
    from backend.core.md_analysis_runner import run_analysis
    if body.bases[0] == body.bases[1] or any(not key or len(key)>512 for key in body.bases):
        raise HTTPException(422,'Choose two different individual bases')
    args = await run_in_threadpool(inputs,job_id,body)
    progress_path = args[3]/'analysis'/'two_base_maps'/'progress'/(body.request_id+'.json')
    from backend.core.md_two_base_progress import write_progress
    await run_in_threadpool(write_progress,progress_path,0,0)
    task = asyncio.create_task(run_analysis(job_id,'two-base-maps','backend.core.md_two_base_maps',
                                           'md_two_base_maps',(*args,progress_path),timeout_s=86400))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                break
            await asyncio.sleep(.1)
        return await task
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        progress_path.unlink(missing_ok=True)
        progress_path.with_suffix('.tmp').unlink(missing_ok=True)


def read_progress(job_id, request_id):
    from backend.api.routes_md import _load_job, _workspace
    path = _load_job(job_id).job_dir(_workspace())/'analysis'/'two_base_maps'/'progress'/(request_id+'.json')
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return dict(done=0,total=0,percent=0)


@router.get('/md/jobs/{job_id}/two-base-maps/progress')
async def progress(job_id: str, request_id: str = Query(pattern=r'^[a-zA-Z0-9-]{1,64}$')):
    return await run_in_threadpool(read_progress,job_id,request_id)
